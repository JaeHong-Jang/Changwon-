"""모델 선택 낙관성 점검(대안 설정의 시간 순 결과)과 설명(계수·순열 중요도·부분의존 방향) — 리더 전용 일회성."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.inspection import partial_dependence, permutation_importance

from src.data import flood_traces as FT
from src.data import layers as L
from src.models.estimators import make_model
from src.models.features import FEATURES, feature_frame
from src.models.provenance import git_state
from src.utils.config import PROJECT_ROOT as ROOT

DEV_YEARS = (2006, 2012, 2014, 2016, 2019, 2025)
# 선택된 설정, 격자 안의 다른 설정, 튜닝하지 않은 기본값, 선형 로지스틱
VARIANTS = {
    "rf_F1_d4_selected": ("random_forest", "F1", {"max_depth": 4, "min_samples_leaf": 400}),
    "rf_F1_d2": ("random_forest", "F1", {"max_depth": 2, "min_samples_leaf": 200}),
    "rf_F1_untuned": ("random_forest", "F1", {}),
    "rf_F0_d4": ("random_forest", "F0", {"max_depth": 4, "min_samples_leaf": 400}),
    "logit_F1_C1": ("ridge", "F1", {"C": 1.0}),
    "logit_F1_C0.1": ("ridge", "F1", {"C": 0.1}),
}


def fit_score(name, fset, params, frame, y):
    """설정대로 학습한 모델과 전 격자 점수."""
    X = frame[FEATURES[fset]].to_numpy(float)
    model = make_model(name, params).fit(X, y)
    return model, model.predict_proba(X)[:, 1]


def main() -> dict:
    """사상별 시간 순 결과와 2019년까지 학습 모델의 설명을 만든다."""
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT)
    run_id = f"robust_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"

    # 격자·특징과 사상별 시험 라벨(10% 규칙)을 준비한다; 홀드아웃은 채점에만 쓴다
    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    frame = feature_frame(layer, pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet"))
    holdout, _ = FT.load(FT.files_for("holdout"))
    tests = [(str(y), y, layer[f"trace_ev_{y}"].to_numpy().astype(bool)) for y in DEV_YEARS]
    for storm, polys in holdout.groupby("storm_id"):
        labels, _ = FT.label_grid(layer, polys, min_overlap=0.10)
        tests.append((str(storm), int(polys["event_date"].dt.year.iloc[0]), np.asarray(labels).astype(bool)))
    fixed = {"L1": layer["L1"].to_numpy(float), "z_sensitivity": layer["z_sensitivity"].to_numpy(float)}

    # 시험 사상마다 그 이전 개발 사상(2025·홀드아웃 제외)으로만 학습해 격자 AUC·상위 20% 포착을 잰다
    rows, cache = [], {}
    for name, year, y_test in sorted(tests, key=lambda t: t[1]):
        if not y_test.any():
            continue
        prior = tuple(y for y in DEV_YEARS if y < year and y != 2025)
        scores = dict(fixed)
        if prior:
            y_train = layer[[f"trace_ev_{y}" for y in prior]].to_numpy().any(axis=1)
            for v, (m, fset, params) in VARIANTS.items():
                if (v, prior) not in cache:
                    cache[(v, prior)] = fit_score(m, fset, params, frame, y_train)
                scores[v] = cache[(v, prior)][1]
        for s, sc in scores.items():
            rows.append({"test_event": name, "year": year, "n_pos": int(y_test.sum()), "score": s,
                         "auc": L.roc_auc(y_test, sc), "top20": L.top_share_lift(y_test, sc, 0.20)["capture_rate"]})
        print(f"{name} done", file=sys.stderr, flush=True)
    table = pd.DataFrame(rows)

    # 2019년까지 학습한 선택 RF 와 로지스틱을 설명한다: 계수, 순열 중요도, 부분의존 방향
    early = tuple(y for y in DEV_YEARS if y != 2025)
    y_early = layer[[f"trace_ev_{y}" for y in early]].to_numpy().any(axis=1)
    cols = FEATURES["F1"]
    X = frame[cols].to_numpy(float)
    explain = {}
    for v in ("rf_F1_d4_selected", "logit_F1_C1"):
        model, score = cache[(v, early)]
        imp = permutation_importance(model, X, y_early, scoring="roc_auc", n_repeats=3, random_state=42, n_jobs=2)
        direction = {}
        for i, c in enumerate(cols):
            try:
                pd_res = partial_dependence(model, X, [i], grid_resolution=8, percentiles=(0.05, 0.95), kind="average")
            except ValueError:  # 대부분 0 인 변수는 5~95% 구간이 한 값이라 전 범위로 본다
                pd_res = partial_dependence(model, X, [i], grid_resolution=8, percentiles=(0.0, 1.0), kind="average")
            grid = pd_res["grid_values"][0]
            direction[c] = (round(float(spearmanr(grid, pd_res["average"][0]).statistic), 3) if len(grid) > 2
                            else round(float(np.sign(pd_res["average"][0][-1] - pd_res["average"][0][0])), 3))
        explain[v] = {"permutation_auc_drop": {c: round(float(m), 4) for c, m in zip(cols, imp.importances_mean)},
                      "partial_dependence_direction": direction,
                      "spearman_vs_z_sensitivity": round(float(spearmanr(score, fixed["z_sensitivity"], nan_policy="omit").statistic), 4)}
        if v.startswith("logit"):
            explain[v]["standardized_coef"] = dict(zip(cols, np.round(model.named_steps["model"].coef_[0], 4).tolist()))

    # 실행별 폴더에 표와 설명을 남긴다
    out = ROOT / ".omc/posthoc_h" / run_id
    out.mkdir(parents=True, exist_ok=False)
    table.assign(run_id=run_id).to_csv(out / "walkforward_variants.csv", index=False, encoding="utf-8-sig")
    result = {"run_id": run_id, "git_head": head, "source_dirty": dirty,
              "command": "PYTHONPATH=. python .omc/posthoc_h/robust_explain.py",
              "role": "post_hoc 점검 — 홀드아웃은 채점에만, 학습은 이전 개발 사상만", "variants": VARIANTS,
              "sensitivity_axis_signs": "h06 SENSITIVITY_SPEC (동일 가중 z 합)", "explain_trained_on": list(early),
              "explain": explain}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = main()
    print(json.dumps({"run_id": r["run_id"], "explain": r["explain"]}, ensure_ascii=False, indent=1))
