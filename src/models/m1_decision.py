"""M1 사전 판정: 사상별 AUC 중앙값으로 자명 기준선과 학습 모델을 비교한다 (docs/q1/M1_protocol.md §5)."""

from __future__ import annotations

import numpy as np
import pandas as pd

MARGIN = 0.02
MIN_UNITS = {"cell_gate": 5, "object": 3}
BASELINES = ("slope_neg", "relelev_neg", "twi", "impervious", "hand_neg", "hand_acc_neg")


def compare(long: pd.DataFrame, trivial: str, model: str, *, unit: str = "cell_gate", stratum: str = "ALL",
            roles: tuple[str, ...] = ("development", "holdout")) -> dict:
    """두 점수가 모두 있고 최소 표본을 넘는 사상에서 AUC 중앙값과 짝 차이 중앙값을 구한다."""
    # 해당 단위·층·역할의 사상별 AUC 를 점수별 열로 편다
    rows = long[(long["unit"] == unit) & (long["stratum"] == stratum) & (long["metric"] == "observed-label_auc")
                & (long["storm"] == "ALL") & long["role"].isin(roles) & long["score"].isin([trivial, model])]
    wide = rows.pivot_table(index="test_event", columns="score", values="value", aggfunc="first")
    units = rows.pivot_table(index="test_event", columns="score", values="n_units", aggfunc="first")
    if trivial not in wide or model not in wide:
        return {"events": [], "evaluable": False}

    # 두 점수가 유한하고 최소 표본 이상인 사상만 남겨 중앙값을 비교한다
    keep = wide[trivial].notna() & wide[model].notna() & (units[model] >= MIN_UNITS[unit])
    w = wide[keep]
    if w.empty:
        return {"events": [], "evaluable": False}
    m_trivial, m_model = float(np.median(w[trivial])), float(np.median(w[model]))
    return {"events": list(w.index), "evaluable": True, trivial: w[trivial].round(4).tolist(),
            model: w[model].round(4).tolist(), "median_" + trivial: round(m_trivial, 4),
            "median_" + model: round(m_model, 4), "median_gap": round(m_model - m_trivial, 4),
            "median_paired_diff": round(float(np.median(w[model] - w[trivial])), 4),
            "within_margin": bool(m_trivial >= m_model - MARGIN)}


def median_table(long: pd.DataFrame) -> pd.DataFrame:
    """점수·층·역할·지표별 사상 중앙값과 사전 게이트 통과 사상 수 (최소 표본 미달 사상 제외)."""
    # 판정에 쓰는 네 지표 행만 고르고 최소 표본을 적용한다
    keys = {("cell_gate", "observed-label_auc"), ("cell_gate", "capture_0.2"), ("object", "observed-label_auc")}
    rows = long[(long["storm"] == "ALL") & long[["unit", "metric"]].apply(tuple, axis=1).isin(keys)].copy()
    rows = rows[rows["value"].notna() & (rows["n_units"] >= rows["unit"].map(MIN_UNITS))]
    gate = {"observed-label_auc": 0.70, "capture_0.2": 0.50}
    rows["passes_gate"] = rows["value"] >= rows["metric"].map(gate)

    # 역할별과 합산으로 중앙값·사상 수·게이트 통과 수를 센다
    parts = [rows.assign(role_group=rows["role"]), rows.assign(role_group="all")]
    table = pd.concat(parts).groupby(["score", "stratum", "unit", "metric", "role_group"]).agg(
        median=("value", "median"), n_events=("value", "size"), n_pass_gate=("passes_gate", "sum")).reset_index()
    return table.round({"median": 4})


def decide(long: pd.DataFrame) -> dict:
    """주 판정(경사 대 RF, 전 격자·격자 AUC·개발+홀드아웃)과 보조 비교를 묶는다."""
    # 주 판정: 경사 중앙값이 RF 중앙값 − 0.02 이상이면 C-b 폐기
    primary = compare(long, "slope_neg", "rf_F1_wf")
    verdict = ("C-b 폐기" if primary["within_margin"] else "C-b 가 자명 기준선 검사에서 탈락하지 않음") \
        if primary["evaluable"] else "판정 불가"

    # 보조: 역할별·객체·평지층, 다른 기준선과 로지스틱
    secondary = {
        "dev_only": compare(long, "slope_neg", "rf_F1_wf", roles=("development",)),
        "holdout_only": compare(long, "slope_neg", "rf_F1_wf", roles=("holdout",)),
        "object_auc": compare(long, "slope_neg", "rf_F1_wf", unit="object"),
        "flat_stratum": compare(long, "slope_neg", "rf_F1_wf", stratum="FLAT"),
        "other_baselines_vs_rf": {b: compare(long, b, "rf_F1_wf") for b in BASELINES if b != "slope_neg"},
        "baselines_vs_logit": {b: compare(long, b, "logit_F1_wf") for b in BASELINES},
    }
    return {"rule": f"median(slope_neg) >= median(rf_F1_wf) - {MARGIN} 이면 C-b 폐기",
            "primary": primary, "verdict": verdict, "secondary": secondary}
