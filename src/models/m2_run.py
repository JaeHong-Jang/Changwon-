"""M2 실행: M1 사상별 AUC 를 logit·부트스트랩 SE 로 무작위효과 통합하고 판정·민감도·SE 점검을 기록한다."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.models.provenance import file_sha256, git_state, package_versions

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/q1/M2"
M1_RUN = "m1_20260926T160821Z_a181f6c"
M1_LONG = f"artifacts/q1/M1/{M1_RUN}/metrics_long.csv"
M1_HAND = f"artifacts/q1/M1/{M1_RUN}/hand.parquet"
CODE_FILES = ["src/models/m2_run.py", "src/models/m2_effects.py", "src/models/m2_pooling.py", "src/models/m2_decision.py",
              "src/models/m2_se_check.py", "src/models/m2_forest.py", "src/data/validation/meta_analysis.py",
              "src/data/uncertainty.py", "src/data/trace_labels.py", "src/models/m1_scores.py", "docs/q1/M2_protocol.md"]
SE_CHECK_INPUTS = ["data/processed/layers/layer1_flood.gpkg", "data/processed/features/grid_features.parquet", M1_HAND,
                   ".omc/benchmark/final_model.joblib", ".omc/benchmark/prespec.json"]
LOO_CASES = [("cell_gate", "combined"), ("cell_gate", "development"), ("cell_gate", "holdout"),
             ("object", "combined"), ("object", "development"), ("object", "holdout")]


def _clean(value: Any) -> Any:
    """JSON 에 넣을 수 있게 NaN 은 None 으로, numpy 수는 파이썬 수로 바꾼다."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    return value


def se_check(effect_rows: pd.DataFrame, n_boot: int) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """개발 사상만 읽어 M1 격자 AUC 재표본을 다시 만들고 SE 근사·짝 상관을 잰다 (S4, 홀드아웃 미사용)."""
    import geopandas as gpd
    import joblib

    from src.data import flood_traces as FT
    from src.data.trace_labels import label_grid
    from src.models.estimators import make_model
    from src.models.features import FEATURES, feature_frame
    from src.models.m1_scores import DEV_YEARS, baseline_scores, prior_years, trained_before
    from src.models.m2_pooling import PAIRS
    from src.models.m2_se_check import check_event, compare_with_m1

    # M1 과 같은 격자 순서·특징·기준선 점수(HAND 는 M1 산출)를 만든다
    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    features = pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet")
    features = layer[["grid_id"]].merge(features, on="grid_id", how="left", validate="one_to_one")
    hand = layer[["grid_id"]].merge(pd.read_parquet(ROOT / M1_HAND), on="grid_id", how="left", validate="one_to_one")
    fixed = baseline_scores(features, hand["hand_osm_m"].to_numpy(float), hand["hand_acc_m"].to_numpy(float))
    fixed |= {"L1": layer["L1"].to_numpy(float), "z_sensitivity": layer["z_sensitivity"].to_numpy(float)}
    frame = feature_frame(layer, features)
    rf = joblib.load(ROOT / ".omc/benchmark/final_model.joblib")
    rf_columns = json.loads((ROOT / ".omc/benchmark/prespec.json").read_text(encoding="utf-8"))["selection"]["feature_columns"]
    logit = make_model("ridge", {"C": 1.0})
    centers = layer.geometry.centroid
    x, y = centers.x.to_numpy(), centers.y.to_numpy()

    # 개발 흔적만 읽어 사상마다 10% 규칙 라벨·재학습 점수·재표본 요약을 만든다
    development, _ = FT.load(FT.files_for("development"))
    rows, pairs = [], []
    for year in DEV_YEARS:
        polys = development[development["event_date"].dt.year == year].reset_index(drop=True)
        labels, _ = label_grid(layer, polys, min_overlap=0.10)
        scores = dict(fixed)
        if prior_years(year):
            scores |= {"rf_F1_wf": trained_before(frame, layer, year, rf, rf_columns),
                       "logit_F1_wf": trained_before(frame, layer, year, logit, FEATURES["F1"])}
        r, p = check_event(str(year), labels, scores, x, y, PAIRS, n_boot=n_boot, seed=42)
        rows.append(r)
        pairs.append(p)
        print(f"se_check {year} done ({int(labels.sum())} positive cells)", file=sys.stderr, flush=True)
    check = compare_with_m1(pd.concat(rows, ignore_index=True), effect_rows)
    info = {"n_boot": n_boot, "seed": 42, "events": [str(y) for y in DEV_YEARS], "holdout_read": False,
            "input_sha256": {p: file_sha256(ROOT / p) for p in SE_CHECK_INPUTS},
            "development_trace_files": [str(Path(p).relative_to(ROOT)) for p in FT.files_for("development")]}
    return check, pd.concat(pairs, ignore_index=True), info


def s4_pooled(check: pd.DataFrame, pair_check: pd.DataFrame, effect_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """S4: 재표본 SD 를 SE 로 쓴 개발 통합(점수)과 짝지은 재표본 SE 로 쓴 개발 짝 통합(절차 외 추가)."""
    from src.models.m2_effects import paired
    from src.models.m2_pooling import PAIRS, pool

    # 점수: M1 포함 행의 logit AUC 에 SE_draw 를 붙여 통합한다
    base = effect_rows[(effect_rows["unit"] == "cell_gate") & (effect_rows["stratum"] == "ALL")
                       & (effect_rows["role"] == "development") & effect_rows["included"]]
    se_draw = check.set_index(["score", "test_event"])["se_draw"]
    base = base.assign(se=se_draw.reindex(pd.MultiIndex.from_frame(base[["score", "test_event"]])).to_numpy())
    score_rows = [{"score": s, "unit": "cell_gate", "stratum": "ALL", "set": "development", "variant": "S4_se_draw"}
                  | pool(g) for s, g in base.groupby("score", sort=False) if g["se"].notna().all()]

    # 짝: 짝지은 재표본의 logit 차이 SD 를 SE 로 쓴다 (양성 격자 집합이 같은 경우만)
    diff_rows = []
    paired_se = pair_check[pair_check["aligned"]].set_index(["model", "baseline", "test_event"])["se_diff_draw"]
    for model, baseline in PAIRS:
        d = paired(effect_rows, model, baseline)
        d = d[(d["unit"] == "cell_gate") & (d["stratum"] == "ALL") & (d["role"] == "development")]
        d = d.assign(se=paired_se.reindex(pd.MultiIndex.from_arrays(
            [d["model"], d["baseline"], d["test_event"].astype(str)])).to_numpy())
        if len(d) and d["se"].notna().all():
            diff_rows.append({"model": model, "baseline": baseline, "unit": "cell_gate", "stratum": "ALL",
                              "set": "development", "variant": "S4_paired_draw", "rho": np.nan}
                             | pool(d, auc_scale=False))
    return pd.DataFrame(score_rows), pd.DataFrame(diff_rows)


def run(n_boot: int = 1000, with_se_check: bool = True) -> dict[str, Any]:
    """M1 긴 표를 읽어 통합·판정·민감도·그림을 실행별 폴더에 남긴다."""
    from src.models.m2_decision import decide
    from src.models.m2_effects import effects
    from src.models.m2_forest import forest
    from src.models.m2_pooling import diff_frames, leave_one_out, pooled_diff_table, pooled_table, transport

    # 실행 식별자를 만들고 M1 사상별 결과를 효과 크기로 바꾼다
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT, ("src", "config", "docs/q1"))
    run_id = f"m2_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"
    long = pd.read_csv(ROOT / M1_LONG, encoding="utf-8-sig", dtype={"test_event": str})
    effect_rows = effects(long)

    # 주 통합·민감도(S1·S2·S3)·한 사상 빼기(S5)·이전 가능성(R5)
    pooled = pooled_table(effect_rows)
    pooled_diff = pooled_diff_table(effect_rows)
    diffs = diff_frames(effect_rows, 0.0)
    loo = pd.concat([leave_one_out(diffs, "rf_F1_wf", "slope_neg", u, s) for u, s in LOO_CASES], ignore_index=True)
    moved = transport(effect_rows, pooled)

    # S4: 개발 사상만 다시 읽어 SE 근사를 점검하고 통합 표에 변형으로 붙인다
    check, pair_check, check_info = (pd.DataFrame(), pd.DataFrame(), {"skipped": True})
    if with_se_check:
        check, pair_check, check_info = se_check(effect_rows, n_boot)
        extra_scores, extra_diffs = s4_pooled(check, pair_check, effect_rows)
        pooled = pd.concat([pooled, extra_scores], ignore_index=True)
        pooled_diff = pd.concat([pooled_diff, extra_diffs], ignore_index=True)
    decision = decide(pooled, pooled_diff, loo, moved)

    # 표·판정·그림·출처를 실행별 폴더에 쓴다
    out = OUTPUT / run_id
    out.mkdir(parents=True, exist_ok=False)
    for name, table in (("effects", effect_rows), ("pooled", pooled), ("pooled_diff", pooled_diff), ("loo", loo),
                        ("transport", moved), ("se_check", check), ("se_check_pairs", pair_check)):
        table.assign(run_id=run_id).to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")
    forest(effect_rows, pooled, out / "forest_grid_auc.png")
    (out / "decision.json").write_text(json.dumps(_clean(decision), ensure_ascii=False, indent=1, allow_nan=False),
                                       encoding="utf-8")
    summary = {"run_id": run_id, "started_utc": started.isoformat(), "git_head": head, "source_dirty": dirty,
               "command": f"PYTHONPATH=. .venv/bin/python -m src.models.m2_run --n-boot {n_boot}"
                          f"{'' if with_se_check else ' --skip-se-check'}",
               "role": "post_hoc — M1 사상별 결과(홀드아웃 포함)를 본 뒤의 사상 단위 재요약. 홀드아웃 원본은 읽지 않는다",
               "protocol": "docs/q1/M2_protocol.md", "input": {M1_LONG: file_sha256(ROOT / M1_LONG)},
               "n_effect_rows": int(len(effect_rows)), "n_included": int(effect_rows["included"].sum()),
               "exclusions": effect_rows.loc[~effect_rows["included"], "reason"].value_counts().to_dict(),
               "se_check": check_info, "code_sha256": {p: file_sha256(ROOT / p) for p in CODE_FILES},
               "packages": package_versions(), "R3_primary": decision["R3_cb"]["primary"]["class"],
               "R4_statement": decision["R4_object"]["statement"]}
    (out / "summary.json").write_text(json.dumps(_clean(summary), ensure_ascii=False, indent=1, default=str),
                                      encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-boot", type=int, default=1000, help="S4 재표본 횟수 (M1 과 같게 1000)")
    parser.add_argument("--skip-se-check", action="store_true", help="S4 개발 사상 재표본 점검을 건너뛴다")
    args = parser.parse_args()
    result = run(n_boot=args.n_boot, with_se_check=not args.skip_se_check)
    print(json.dumps({k: result[k] for k in ("run_id", "R3_primary", "R4_statement")}, ensure_ascii=False))
