"""M1 실행: HAND·기준선·시간순 모델 점수를 사상별·층별로 채점하고 사전 판정을 기록한다."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.models.provenance import file_sha256, git_state, package_versions

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/q1/M1"
KEEP = {("cell_gate", "observed-label_auc"), ("cell_gate", "capture_0.2"), ("cluster_gate", "observed-label_auc"),
        ("object", "observed-label_auc"), ("object", "capture_0.2")}
CODE_FILES = ["src/models/m1_run.py", "src/models/m1_scores.py", "src/models/m1_strata.py", "src/models/m1_decision.py",
              "src/data/hand.py", "src/data/features.py", "src/models/features.py", "src/models/estimators.py",
              "src/data/validation/evaluate.py", "src/data/validation/auc.py", "src/data/validation/curves.py",
              "src/data/flood_traces.py", "docs/q1/M1_protocol.md"]
INPUT_FILES = ["data/processed/layers/layer1_flood.gpkg", "data/processed/features/grid_features.parquet",
               "data/raw/rivers/osm_waterways.gpkg", ".omc/benchmark/final_model.joblib", ".omc/benchmark/prespec.json"]
HAND_ACC_MIN_CELLS = 100


def hand_layers(layer: Any, features: Any) -> tuple[np.ndarray, np.ndarray, dict]:
    """90 m DEM 을 격자망에 올리고 OSM·유량누적 하천망 두 가지 HAND 를 격자 순서로 돌려준다."""
    import geopandas as gpd

    from src.data import features as F
    from src.data import hand as H

    # H04 와 같은 격자망·DEM 재표집을 하고 기존 표고와 같은지 확인한다
    lat, row, col = F.lattice_from_grid(layer, 100.0)
    elev, meta = F.dem_to_lattice(sorted((ROOT / "data/raw/dem/public_dem_2025").glob("*.img")), lat)
    diff = float(np.nanmax(np.abs(elev[row, col] - features["elev_m"].to_numpy(float))))
    if not diff <= 1e-3:
        raise RuntimeError(f"재계산 표고가 elev_m 과 다르다 (최대차 {diff})")

    # OSM 하천(river·stream·canal)과 유량누적 ≥ 100칸 하천망으로 HAND 를 잰다
    ways = gpd.read_file(ROOT / "data/raw/rivers/osm_waterways.gpkg", layer="waterways").to_crs(layer.crs)
    osm = H.stream_mask_from_lines(ways.loc[ways["waterway"].isin(["river", "stream", "canal"]), "geometry"], lat)
    hand_osm, s_osm = H.hand(elev, osm, lat.res)
    hand_acc, s_acc = H.hand(elev, H.stream_mask_from_accumulation(elev, lat.res, HAND_ACC_MIN_CELLS), lat.res)
    info = {"dem": meta, "elev_max_abs_diff": diff, "osm": s_osm, "acc": s_acc | {"min_cells": HAND_ACC_MIN_CELLS}}
    return hand_osm[row, col], hand_acc[row, col], info


def run(include_holdout: bool = True, n_boot: int = 1000) -> dict[str, Any]:
    """개발(과 홀드아웃) 사상을 시간순으로 채점해 실행별 폴더에 표·판정·HAND 를 남긴다."""
    import geopandas as gpd
    import joblib
    import pandas as pd

    from src.data import flood_traces as FT
    from src.data import validation as V
    from src.models.features import FEATURES, feature_frame
    from src.models.estimators import make_model
    from src.models.m1_decision import decide, median_table
    from src.models.m1_scores import DEV_YEARS, baseline_scores, prior_years, trained_before
    from src.models.m1_strata import strata

    # 실행 식별자를 만들고 격자·특징을 격자 순서로 맞춘다
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT, ("src", "config", "docs/q1"))
    tag = "" if include_holdout else "_devonly"
    run_id = f"m1{tag}_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"
    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    features = pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet")
    features = layer[["grid_id"]].merge(features, on="grid_id", how="left", validate="one_to_one")
    frame = feature_frame(layer, features)

    # 자명 기준선·HAND·비교 점수와 층을 만든다
    hand_osm, hand_acc, hand_info = hand_layers(layer, features)
    fixed = baseline_scores(features, hand_osm, hand_acc)
    fixed |= {"L1": layer["L1"].to_numpy(float), "z_sensitivity": layer["z_sensitivity"].to_numpy(float)}
    rf = joblib.load(ROOT / ".omc/benchmark/final_model.joblib")
    rf_columns = json.loads((ROOT / ".omc/benchmark/prespec.json").read_text(encoding="utf-8"))["selection"]["feature_columns"]
    logit = make_model("ridge", {"C": 1.0})
    masks = strata(features)

    # 개발 흔적(날짜 있는 것)과, 옵션이면 홀드아웃 호우를 시험 사상으로 나열한다
    development, _ = FT.load(FT.files_for("development"))
    tests = [(str(y), "development", y, development[development["event_date"].dt.year == y]) for y in DEV_YEARS]
    traces = [development]
    if include_holdout:
        holdout, _ = FT.load(FT.files_for("holdout"))
        traces.append(holdout)
        tests += [(str(s), "holdout", int(p["event_date"].dt.year.iloc[0]), p) for s, p in holdout.groupby("storm_id")]

    # 어떤 흔적과도 닿은 격자를 비접촉 배경에서 뺀다 (walkforward 와 같은 정의)
    touched = np.zeros(len(layer), bool)
    for t in traces:
        touched[gpd.sjoin(layer[["geometry"]], t[["geometry"]], predicate="intersects").index.unique()] = True

    # 사상마다 이전 사상으로 모델을 다시 학습하고 모든 점수를 층별로 채점한다
    rows, cache = [], {}
    for name, role, year, polys in tests:
        scores = dict(fixed)
        key = tuple(prior_years(year))
        if key and key not in cache:
            cache[key] = {"rf_F1_wf": trained_before(frame, layer, year, rf, rf_columns),
                          "logit_F1_wf": trained_before(frame, layer, year, logit, FEATURES["F1"])}
        scores |= cache.get(key, {})
        table = V.evaluate(scores, layer, polys.reset_index(drop=True), strata=masks, background_mask=~touched,
                           n_boot=n_boot, seed=42)
        table = table[(table["storm"] == "ALL") & table[["unit", "metric"]].apply(tuple, axis=1).isin(KEEP)]
        rows.append(table.assign(test_event=name, role=role, year=year, n_polygons=len(polys), train_events=str(list(key))))
        print(f"{name} done ({len(polys)} polygons, trained on {list(key)})", file=sys.stderr, flush=True)

    # 긴 표·중앙값 표·판정·HAND·출처를 실행별 폴더에 쓴다
    long = pd.concat(rows, ignore_index=True).assign(run_id=run_id)
    decision = decide(long)
    out = OUTPUT / run_id
    out.mkdir(parents=True, exist_ok=False)
    long.to_csv(out / "metrics_long.csv", index=False, encoding="utf-8-sig")
    median_table(long).to_csv(out / "median_table.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"grid_id": layer["grid_id"], "hand_osm_m": hand_osm, "hand_acc_m": hand_acc}).to_parquet(out / "hand.parquet")
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"run_id": run_id, "started_utc": started.isoformat(), "git_head": head, "source_dirty": dirty,
               "command": f"PYTHONPATH=. .venv/bin/python -m src.models.m1_run{'' if include_holdout else ' --dev-only'}"
                          f" --n-boot {n_boot}",
               "role": "post_hoc — 홀드아웃 결과를 본 뒤 설계한 자명 기준선 비교. 홀드아웃은 채점에만 쓴다 (AGENTS §2-2)",
               "protocol": "docs/q1/M1_protocol.md", "include_holdout": include_holdout, "n_boot": n_boot,
               "hand": hand_info, "strata_n_cells": {k: int(v.sum()) for k, v in masks.items()},
               "train_events": {n: prior_years(y) for n, _, y, _ in tests},
               "n_undated_dev_polygons_excluded": int(development["event_date"].isna().sum()),
               "code_sha256": {p: file_sha256(ROOT / p) for p in CODE_FILES},
               "input_sha256": {p: file_sha256(ROOT / p) for p in INPUT_FILES}, "packages": package_versions(),
               "verdict": decision["verdict"]}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-only", action="store_true", help="홀드아웃을 읽지 않는다 (작업자·검토자용)")
    parser.add_argument("--n-boot", type=int, default=1000)
    args = parser.parse_args()
    result = run(include_holdout=not args.dev_only, n_boot=args.n_boot)
    print(json.dumps({k: result[k] for k in ("run_id", "verdict")}, ensure_ascii=False))
