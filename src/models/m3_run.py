"""M3 실행: 이전 사상 안 LOEO 로 설정을 고르고 고정 구성·경사와 함께 사상별·층별로 채점해 판정을 기록한다."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.models.provenance import file_sha256, git_state, package_versions

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/q1/M3"
BENCHMARK = ROOT / ".omc/benchmark"
M1_RUN = ROOT / "artifacts/q1/M1/m1_20260926T160821Z_a181f6c"
KEEP = {("cell_gate", "observed-label_auc"), ("cell_gate", "capture_0.2"), ("cluster_gate", "observed-label_auc"),
        ("object", "observed-label_auc"), ("object", "capture_0.2")}
CODE_FILES = ["src/models/m3_run.py", "src/models/m3_configs.py", "src/models/m3_select.py", "src/models/m3_checks.py",
              "src/models/m3_decision.py", "src/models/prior_fit.py", "src/models/m1_decision.py",
              "src/models/m1_scores.py", "src/models/m1_strata.py", "src/models/folds.py", "src/models/scoring.py",
              "src/models/estimators.py", "src/models/features.py", "src/data/uncertainty.py",
              "src/data/validation/evaluate.py", "src/data/validation/auc.py", "src/data/validation/curves.py",
              "src/data/flood_traces.py", "docs/q1/M3_protocol.md"]
INPUT_FILES = ["data/processed/layers/layer1_flood.gpkg", "data/processed/features/grid_features.parquet",
               ".omc/benchmark/final_model.joblib", ".omc/benchmark/prespec.json", ".omc/benchmark/results_dev.csv",
               "artifacts/q1/M1/m1_20260926T160821Z_a181f6c/metrics_long.csv"]


def status(prior: tuple[int, ...]) -> str:
    """이전 사상 수로 중첩 선택 상태를 적는다."""
    return "학습 불가" if not prior else ("선택 불가" if len(prior) < 2 else "선택")


def run(include_holdout: bool = True, n_boot: int = 1000) -> dict[str, Any]:
    """안쪽 선택 → 이전 사상 재학습 → 사상별·층별 채점 → 판정·재현 확인을 실행별 폴더에 남긴다."""
    import geopandas as gpd
    import joblib
    import pandas as pd
    from threadpoolctl import threadpool_limits

    from src.data import flood_traces as FT
    from src.data import validation as V
    from src.models.estimators import make_model
    from src.models.features import FEATURES, feature_frame
    from src.models.m1_decision import median_table
    from src.models.m1_scores import BASELINES
    from src.models.m1_strata import strata
    from src.models.m3_checks import benchmark_loeo, match_reference
    from src.models.m3_configs import FIXED_ID, VARIANTS, check_prespec, grid
    from src.models.m3_decision import decide, selection_gap
    from src.models.m3_select import select_for_prior
    from src.models.prior_fit import DEV_YEARS, prior_years, trained_before

    # 실행 식별자를 만들고 격자·특징·사상 라벨·설정 공간을 격자 순서로 준비한다
    started, clock = datetime.now(timezone.utc), time.monotonic()
    head, dirty = git_state(ROOT, ("src", "config", "docs/q1"))
    tag = "" if include_holdout else "_devonly"
    run_id = f"m3{tag}_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"
    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    features = pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet")
    features = layer[["grid_id"]].merge(features, on="grid_id", how="left", validate="one_to_one")
    frame = feature_frame(layer, features)
    centers = layer.geometry.centroid
    points = np.column_stack([centers.x, centers.y])
    labels = {y: layer[f"trace_ev_{y}"].to_numpy().astype(bool) for y in DEV_YEARS}
    X = {name: frame[columns].to_numpy(float) for name, columns in FEATURES.items()}
    prespec = check_prespec(BENCHMARK / "prespec.json")
    fixed_model = joblib.load(BENCHMARK / "final_model.joblib")
    fixed_columns = prespec["selection"]["feature_columns"]
    configs = grid()
    by_id = {c["id"]: c for c in configs}
    column, sign = BASELINES["slope_neg"]
    slope = sign * features[column].to_numpy(float)
    masks = strata(features)

    # 개발 흔적(날짜 있는 것)과, 옵션이면 홀드아웃 호우를 시험 사상으로 나열한다
    development, _ = FT.load(FT.files_for("development"))
    tests = [(str(y), "development", y, development[development["event_date"].dt.year == y]) for y in DEV_YEARS]
    traces = [development]
    if include_holdout:
        holdout, _ = FT.load(FT.files_for("holdout"))
        traces.append(holdout)
        tests += [(str(s), "holdout", int(p["event_date"].dt.year.iloc[0]), p) for s, p in holdout.groupby("storm_id")]

    # 어떤 흔적과도 닿은 격자를 비접촉 배경에서 뺀다 (M1 과 같은 정의)
    touched = np.zeros(len(layer), bool)
    for t in traces:
        touched[gpd.sjoin(layer[["geometry"]], t[["geometry"]], predicate="intersects").index.unique()] = True

    with threadpool_limits(limits=2):
        # 안쪽 LOEO 기계가 동결 벤치마크를 재현하는지 먼저 확인한다 (다르면 멈춘다)
        results_dev = pd.read_csv(BENCHMARK / "results_dev.csv")
        bench = benchmark_loeo(X["F1"], points, np.column_stack([labels[y] for y in DEV_YEARS]),
                               [str(y) for y in DEV_YEARS], results_dev)
        print(f"benchmark LOEO reproduced (max diff {bench['max_abs_diff']:.2e})", file=sys.stderr, flush=True)

        # 이전 사상이 둘 이상인 집합마다 전체 설정의 LOEO 지표를 구하고 변형별로 고른다
        priors = sorted({tuple(prior_years(y)) for _, _, y, _ in tests if len(prior_years(y)) >= 2}, key=len)
        loeo_tables, chosen = [], {}
        for prior in priors:
            table, rankings = select_for_prior(X, points, labels, prior, configs, VARIANTS)
            loeo_tables.append(table)
            chosen[prior] = {}
            for variant, ranking in rankings.items():
                fixed_row = ranking[ranking["config"] == FIXED_ID].iloc[0]
                chosen[prior][variant] = {"config": ranking["config"].iloc[0],
                                          "selection_score": float(ranking["selection_score"].iloc[0]),
                                          "fixed_rank": int(fixed_row["rank"]),
                                          "fixed_selection_score": float(fixed_row["selection_score"]),
                                          "n_configs": len(ranking), "ranking": json.loads(ranking.to_json(orient="records"))}
            print(f"P={list(prior)} chosen {({v: c['config'] for v, c in chosen[prior].items()})}",
                  file=sys.stderr, flush=True)

        # 사상마다 고정 구성·고른 설정을 이전 사상으로 재학습하고 모든 점수를 층별로 채점한다
        rows, cache, identical = [], {}, {}
        for name, role, year, polys in tests:
            key = tuple(prior_years(year))
            if key and key not in cache:
                cache[key] = {"rf_F1_wf": trained_before(frame, layer, year, fixed_model, fixed_columns)}
                for variant, pick in chosen.get(key, {}).items():
                    c = by_id[pick["config"]]
                    cache[key][variant] = trained_before(frame, layer, year, make_model(c["model"], c["params"]),
                                                         FEATURES[c["feature_set"]])
                    identical[f"{list(key)}:{variant}"] = bool(np.array_equal(cache[key][variant], cache[key]["rf_F1_wf"]))
            scores = {"slope_neg": slope} | cache.get(key, {})
            table = V.evaluate(scores, layer, polys.reset_index(drop=True), strata=masks, background_mask=~touched,
                               n_boot=n_boot, seed=42)
            table = table[(table["storm"] == "ALL") & table[["unit", "metric"]].apply(tuple, axis=1).isin(KEEP)]
            rows.append(table.assign(test_event=name, role=role, year=year, n_polygons=len(polys),
                                     train_events=str(list(key)), nested_status=status(key)))
            print(f"{name} done ({len(polys)} polygons, P={list(key)}, {status(key)})", file=sys.stderr, flush=True)

    # 판정·중앙값·선택 낙관·M1 재현 확인을 만든다
    long = pd.concat(rows, ignore_index=True).assign(run_id=run_id)
    decision = decide(long)
    m1_long = pd.read_csv(M1_RUN / "metrics_long.csv", encoding="utf-8-sig")
    # 개발 전용 실행은 홀드아웃 흔적이 비접촉 배경에 남아 객체 지표가 M1 과 달라지므로 격자·덩어리 행만 본다
    m1_match = match_reference(long, m1_long, ("rf_F1_wf", "slope_neg"),
                               units=None if include_holdout else ("cell_gate", "cluster_gate"))
    if not m1_match["passes"]:
        decision["verdict"] = f"재현 실패 (규칙상 판정: {decision['verdict']})"
    picks = pd.DataFrame([{"test_event": n, "score": v, "config": chosen[tuple(prior_years(y))][v]["config"],
                           "selection_score": chosen[tuple(prior_years(y))][v]["selection_score"]}
                          for n, _, y, _ in tests if tuple(prior_years(y)) in chosen for v in VARIANTS])
    gap = selection_gap(long, picks)
    decision["secondary"]["selection_gap"] = gap.round(4).to_dict("records")

    # 긴 표·중앙값 표·LOEO 표·선택·판정·출처를 실행별 폴더에 쓴다
    out = OUTPUT / run_id
    out.mkdir(parents=True, exist_ok=False)
    long.to_csv(out / "metrics_long.csv", index=False, encoding="utf-8-sig")
    median_table(long).to_csv(out / "median_table.csv", index=False, encoding="utf-8-sig")
    pd.concat(loeo_tables, ignore_index=True).to_csv(out / "selection_loeo.csv", index=False, encoding="utf-8-sig")
    selected = {"fixed_config": FIXED_ID,
                "by_prior": {",".join(map(str, p)): v for p, v in chosen.items()},
                "by_test_event": {n: {"role": r, "prior": prior_years(y), "status": status(tuple(prior_years(y))),
                                      **{v: chosen[tuple(prior_years(y))][v]["config"]
                                         for v in VARIANTS if tuple(prior_years(y)) in chosen}}
                                  for n, r, y, _ in tests},
                "nested_equals_fixed_scores": identical}
    (out / "selected.json").write_text(json.dumps(selected, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    summary = {"run_id": run_id, "started_utc": started.isoformat(), "git_head": head, "source_dirty": dirty,
               "command": f"PYTHONPATH=. .venv/bin/python -m src.models.m3_run{'' if include_holdout else ' --dev-only'}"
                          f" --n-boot {n_boot}",
               "role": "post_hoc — M1·홀드아웃 결과를 본 뒤 설계한 중첩 시간순 선택. 홀드아웃은 채점에만 쓴다 (AGENTS §2-2)",
               "protocol": "docs/q1/M3_protocol.md", "include_holdout": include_holdout, "n_boot": n_boot,
               "prespec_run_id": prespec["run_id"], "n_configs": {v: len(grid(m)) for v, m in VARIANTS.items()},
               "priors": [list(p) for p in priors], "strata_n_cells": {k: int(v.sum()) for k, v in masks.items()},
               "checks": {"benchmark_loeo": bench, "m1_reproduction": m1_match},
               "n_undated_dev_polygons_excluded": int(development["event_date"].isna().sum()),
               "elapsed_seconds": round(time.monotonic() - clock, 1),
               "code_sha256": {p: file_sha256(ROOT / p) for p in CODE_FILES},
               "input_sha256": {p: file_sha256(ROOT / p) for p in INPUT_FILES}, "packages": package_versions(),
               "verdict": decision["verdict"], "m1_recheck": decision["m1_recheck"]["slope_vs_nested"].get("verdict")}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-only", action="store_true", help="홀드아웃을 읽지 않는다 (검토자용)")
    parser.add_argument("--n-boot", type=int, default=1000)
    args = parser.parse_args()
    result = run(include_holdout=not args.dev_only, n_boot=args.n_boot)
    print(json.dumps({k: result[k] for k in ("run_id", "verdict", "m1_recheck")}, ensure_ascii=False))
