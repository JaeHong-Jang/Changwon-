"""M4 실행: 라벨 규칙 8개 × 격자 크기 4개로 사상별·합동 홀드아웃을 채점하고 분해·생존·판정을 기록한다."""

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
OUTPUT = ROOT / "artifacts/q1/M4"
SIZES = (100, 200, 500, 1000)
CODE_FILES = ["src/models/m4_run.py", "src/models/m4_metrics.py", "src/models/m4_decision.py", "src/models/m4_survival.py",
              "src/models/m4_checks.py", "src/data/coarse_grid.py", "src/data/trace_footprint.py", "src/data/label_rules.py",
              "src/data/validation/weighted_auc.py", "src/data/validation/decomposition.py",
              "src/data/validation/_common.py", "src/data/validation/curves.py", "src/models/m1_run.py",
              "src/models/m1_scores.py", "src/data/hand.py", "src/data/features.py", "src/models/features.py",
              "src/models/estimators.py", "src/models/label_audit.py", "src/data/flood_traces.py", "docs/q1/M4_protocol.md"]
INPUT_FILES = ["data/processed/layers/layer1_flood.gpkg", "data/processed/features/grid_features.parquet",
               "data/raw/rivers/osm_waterways.gpkg", ".omc/benchmark/final_model.joblib", ".omc/benchmark/prespec.json"]


def test_events(include_holdout: bool) -> tuple[list[tuple[str, str, int, Any]], list[Any]]:
    """M1 과 같은 시험 사상 목록(개발 연도·홀드아웃 호우)과 합동 홀드아웃, 배경 계산용 흔적 묶음."""
    from src.data import flood_traces as FT
    from src.models.m1_scores import DEV_YEARS

    # 날짜 있는 개발 흔적을 연도별로 나눈다
    development, _ = FT.load(FT.files_for("development"))
    tests = [(str(y), "development", y, development[development["event_date"].dt.year == y]) for y in DEV_YEARS]
    traces = [development]

    # 옵션이면 홀드아웃 호우별 사상과 4사상 합동 사상을 더한다
    if include_holdout:
        holdout, _ = FT.load(FT.files_for("holdout"))
        traces.append(holdout)
        tests += [(str(s), "holdout", int(p["event_date"].dt.year.iloc[0]), p) for s, p in holdout.groupby("storm_id")]
        tests.append(("HOLDOUT_ALL", "holdout_pooled", int(holdout["event_date"].dt.year.max()), holdout))
    return [(n, r, y, p.reset_index(drop=True)) for n, r, y, p in tests], traces


def run(include_holdout: bool = True) -> dict[str, Any]:
    """시험 사상 × 규칙 × 크기를 채점해 실행별 폴더에 긴 표·분해·생존·판정을 남긴다."""
    import geopandas as gpd
    import joblib
    import pandas as pd

    from src.data.coarse_grid import block_any, block_mean, make_blocks
    from src.data.label_rules import RULES, positive_mass
    from src.data.trace_footprint import center_inside, coarsen, footprint
    from src.models import m4_checks, m4_decision
    from src.models.estimators import make_model
    from src.models.features import FEATURES, feature_frame
    from src.models.label_audit import _land_class
    from src.models.m1_run import hand_layers
    from src.models.m1_scores import baseline_scores, prior_years, trained_before
    from src.models.m4_metrics import event_sample, score_config
    from src.models.m4_survival import area_bin, in_domain, summarise, survives

    # 실행 식별자를 만들고 격자·특징을 격자 순서로 맞춘다 (M1 과 같음)
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT, ("src", "config", "docs/q1"))
    run_id = f"m4{'' if include_holdout else '_devonly'}_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"
    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    features = pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet")
    features = layer[["grid_id"]].merge(features, on="grid_id", how="left", validate="one_to_one")
    frame = feature_frame(layer, features)

    # M1 과 같은 고정 점수를 만들고 HAND 가 M1 산출과 같은지 확인한다
    hand_osm, hand_acc, hand_info = hand_layers(layer, features)
    fixed = baseline_scores(features, hand_osm, hand_acc)
    fixed |= {"L1": layer["L1"].to_numpy(float), "z_sensitivity": layer["z_sensitivity"].to_numpy(float)}
    m1_hand = ROOT / m4_checks.M1_RUN / "hand.parquet"
    if m1_hand.exists():
        h = layer[["grid_id"]].merge(pd.read_parquet(m1_hand), on="grid_id", how="left")
        hand_info["max_abs_diff_vs_m1"] = float(np.nanmax(np.abs(np.r_[h["hand_osm_m"] - hand_osm,
                                                                        h["hand_acc_m"] - hand_acc])))
    rf = joblib.load(ROOT / ".omc/benchmark/final_model.joblib")
    rf_columns = json.loads((ROOT / ".omc/benchmark/prespec.json").read_text(encoding="utf-8"))["selection"]["feature_columns"]
    logit = make_model("ridge", {"C": 1.0})

    # 시험 사상과, 어떤 흔적과도 닿은 100 m 칸(비접촉 배경의 여집합)을 준비한다
    tests, traces = test_events(include_holdout)
    touched = np.zeros(len(layer), bool)
    for t in traces:
        touched[gpd.sjoin(layer[["geometry"]], t[["geometry"]], predicate="intersects").index.unique()] = True

    # 크기마다 굵은 칸·배경을 만들고 고정 점수를 평균 집계한다
    blocks = {s: make_blocks(layer, s) for s in SIZES}
    background = {s: ~block_any(touched, b) for s, b in blocks.items()}
    fixed_at = {s: {k: block_mean(v, b) for k, v in fixed.items()} for s, b in blocks.items()}

    # 사상마다 이전 사상 모델을 다시 학습하고, 크기 × 규칙마다 채점·분해·생존을 모은다
    metric_rows, decomposition_rows, object_parts, survival_parts, event_rows, cache = [], [], [], [], [], {}
    for name, role, year, polys in tests:
        key = tuple(prior_years(year))
        if key and key not in cache:
            cache[key] = {"rf_F1_wf": trained_before(frame, layer, year, rf, rf_columns),
                          "logit_F1_wf": trained_before(frame, layer, year, logit, FEATURES["F1"])}
        base = footprint(layer, polys)
        area = polys.geometry.area.to_numpy()
        land = polys.get("land_use", pd.Series(None, index=polys.index)).map(_land_class).to_numpy()
        for size, b in blocks.items():
            scores = dict(fixed_at[size]) | {k: block_mean(v, b) for k, v in cache.get(key, {}).items()}
            scores = {k: scores[k] for k in m4_decision.SCORES if k in scores}
            fp = coarsen(base, b)
            inside_center = center_inside(polys, b.x, b.y)
            domain = in_domain(fp)
            for rule in RULES:
                p = positive_mass(rule, fp, inside_center)
                weight = p * b.area if rule == "soft" else p
                tag = {"test_event": name, "role": role, "rule": rule, "size_m": size}
                metrics, decomposition, objects = score_config(scores, p, weight, fp, b, background[size])
                metric_rows += [tag | m for m in metrics]
                decomposition_rows += [tag | d for d in decomposition]
                object_parts.append(objects.assign(**tag, object_id=polys["object_id"].to_numpy()[objects["object_index"]],
                                                   area_m2=area[objects["object_index"]]))
                survival_parts.append(pd.DataFrame(tag | {"object_id": polys["object_id"].to_numpy(), "area_m2": area,
                                                          "land_class": land, "in_domain": domain,
                                                          "survive": survives(p, fp)}))
                event_rows.append(tag | event_sample(p, fp, b) | {"train_events": str(list(key))})
        print(f"{name} done ({len(polys)} polygons, trained on {list(key)})", file=sys.stderr, flush=True)

    # 표를 묶고 판정·순위·정합 확인을 계산한다
    long = pd.DataFrame(metric_rows).assign(run_id=run_id)
    events = pd.DataFrame(event_rows)
    survival = pd.concat(survival_parts, ignore_index=True)
    survival["area_bin"] = area_bin(survival["area_m2"])
    survival["role_group"] = survival["role"]
    verdicts = m4_decision.verdict_table(long, events)
    decision = m4_decision.decide(verdicts)
    checks = {"m1": m4_checks.against_m1(long, ROOT), "official_holdout": m4_checks.against_official(long, ROOT),
              "identity_max_abs_diff": float(pd.DataFrame(decomposition_rows)["identity_abs_diff"].max())}

    # 실행별 폴더에 산출물과 출처를 쓴다
    out = OUTPUT / run_id
    out.mkdir(parents=True, exist_ok=False)
    long.to_csv(out / "metrics_long.csv", index=False, encoding="utf-8-sig")
    events.to_csv(out / "events.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(decomposition_rows).to_csv(out / "decomposition.csv", index=False, encoding="utf-8-sig")
    pd.concat(object_parts, ignore_index=True).to_parquet(out / "object_contrib.parquet")
    survival.to_csv(out / "survival_objects.csv", index=False, encoding="utf-8-sig")
    summarise(survival).to_csv(out / "survival_summary.csv", index=False, encoding="utf-8-sig")
    verdicts.to_csv(out / "verdicts.csv", index=False, encoding="utf-8-sig")
    m4_decision.ranking(verdicts).to_csv(out / "ranking.csv", index=False, encoding="utf-8-sig")
    m4_decision.pair_reversals(verdicts).to_csv(out / "pair_reversals.csv", index=False, encoding="utf-8-sig")
    m4_decision.cb_recheck(verdicts).to_csv(out / "cb_recheck.csv", index=False, encoding="utf-8-sig")
    m4_decision.median_table(long, events).to_csv(out / "median_table.csv", index=False, encoding="utf-8-sig")
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    summary = {"run_id": run_id, "started_utc": started.isoformat(), "git_head": head, "source_dirty": dirty,
               "command": f"PYTHONPATH=. .venv/bin/python -m src.models.m4_run{'' if include_holdout else ' --dev-only'}",
               "role": "post_hoc — 홀드아웃 결과를 본 뒤 설계한 라벨 규칙·격자 크기 민감도. 홀드아웃은 채점에만 쓴다 (AGENTS §2-2)",
               "protocol": "docs/q1/M4_protocol.md", "include_holdout": include_holdout, "rules": list(RULES),
               "sizes_m": list(SIZES), "n_blocks": {s: b.n for s, b in blocks.items()},
               "n_background_blocks": {s: int(v.sum()) for s, v in background.items()}, "hand": hand_info,
               "train_events": {n: prior_years(y) for n, _, y, _ in tests}, "checks": checks,
               "code_sha256": {p: file_sha256(ROOT / p) for p in CODE_FILES},
               "input_sha256": {p: file_sha256(ROOT / p) for p in INPUT_FILES}, "packages": package_versions(),
               "verdict": decision["verdict"]}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-only", action="store_true", help="홀드아웃을 읽지 않는다 (작업자·검토자용)")
    args = parser.parse_args()
    result = run(include_holdout=not args.dev_only)
    print(json.dumps({k: result[k] for k in ("run_id", "verdict", "checks")}, ensure_ascii=False, default=str))
