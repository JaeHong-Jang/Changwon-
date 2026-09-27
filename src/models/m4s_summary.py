"""M4S 요약: 평가 가능 복제의 시나리오 × 규칙 요약·분류, 게이트 뒤집힘, 사상 집계(V1·V2) (docs/q1/M4S_protocol.md §4·§6.3)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.models.gates import GATE

MIN_POS = 5
MIN_OBJECTS = 3
DIVERGE = 0.1
REFERENCE_RULE = "f10"
DISTANCE_BINS = [-np.inf, -0.1, -0.05, 0.0, 0.05, 0.1, np.inf]
GAP_BINS = [-np.inf, -0.2, -0.1, 0.0, 0.1, 0.2, np.inf]


def passes(auc, capture) -> np.ndarray:
    """사전 게이트: AUC ≥ 0.70 이고 상위 20% 포착 ≥ 0.50."""
    return (np.asarray(auc) >= GATE["auc_min"]) & (np.asarray(capture) >= GATE["top20_capture_min"])


def classify(p10: float) -> str:
    """P10 ≥ 0.5 벌어짐, 0.1 ≤ P10 < 0.5 가끔, P10 < 0.1 없음."""
    # 결측이면 평가불가, 아니면 두 경계로 나눈다
    if not np.isfinite(p10):
        return "평가불가"
    return "벌어짐" if p10 >= 0.5 else "가끔" if p10 >= 0.1 else "없음"


def median_interval(values: np.ndarray) -> tuple[float, float]:
    """중앙값의 95% 순서통계량 구간: 1부터 센 순위 ⌊R/2 − 0.98√R⌋, ⌈1 + R/2 + 0.98√R⌉ (범위 밖이면 끝값)."""
    # 정렬한 뒤 이항 근사 순위의 값을 고른다
    v = np.sort(np.asarray(values, dtype=float)[np.isfinite(values)])
    r = len(v)
    if not r:
        return np.nan, np.nan
    lo = min(max(math.floor(r / 2 - 0.98 * math.sqrt(r)), 1), r)
    hi = min(max(math.ceil(1 + r / 2 + 0.98 * math.sqrt(r)), 1), r)
    return float(v[lo - 1]), float(v[hi - 1])


def annotate(rep: pd.DataFrame) -> pd.DataFrame:
    """복제 행에 평가 가능 여부·게이트·단위 뒤집힘·규칙 뒤집힘(같은 복제의 f10 대비)을 붙인다."""
    # 최소 표본과 격자·객체 게이트를 계산한다
    out = rep.copy()
    out["evaluable"] = (out["n_pos_cells"] >= MIN_POS) & (out["n_K"] >= MIN_OBJECTS) & np.isfinite(out["gap"])
    out["grid_pass"] = passes(out["cell_auc"], out["capture"])
    out["object_pass"] = passes(out["object_auc"], out["object_capture"])
    out["unit_flip"] = out["grid_pass"] != out["object_pass"]
    out["auc_unit_flip"] = (out["cell_auc"] >= GATE["auc_min"]) != (out["object_auc"] >= GATE["auc_min"])

    # 같은 시나리오·복제의 참조 규칙 격자 게이트와 비교한다
    ref = out[out["rule"] == REFERENCE_RULE].set_index(["scenario_no", "replicate"])
    key = pd.MultiIndex.from_frame(out[["scenario_no", "replicate"]])
    out["ref_grid_pass"] = ref["grid_pass"].reindex(key).to_numpy()
    out["ref_evaluable"] = ref["evaluable"].reindex(key).to_numpy()
    out["rule_flip"] = out["ref_evaluable"].astype(bool) & (out["grid_pass"] != out["ref_grid_pass"])
    return out


def scenario_summary(rep: pd.DataFrame, scenarios: pd.DataFrame) -> pd.DataFrame:
    """시나리오 × 규칙마다 평가 가능 복제의 차이 분포·세 항·집중·뒤집힘 비율과 분류."""
    # 평가 가능 복제만 모아 시나리오 × 규칙으로 묶는다
    rows = []
    for (no, rule), part in rep.groupby(["scenario_no", "rule"], sort=True):
        ok = part[part["evaluable"]]
        gap = ok["gap"].to_numpy()
        lo, hi = median_interval(gap)
        p10 = float(np.mean(np.abs(gap) >= DIVERGE)) if len(gap) else np.nan
        row = {"scenario_no": no, "rule": rule, "n_replicates": len(part), "n_evaluable": len(ok),
               "gap_median": float(np.median(gap)) if len(gap) else np.nan, "gap_median_lo": lo, "gap_median_hi": hi,
               "gap_mean": float(gap.mean()) if len(gap) else np.nan, "gap_sd": float(gap.std(ddof=1)) if len(gap) > 1 else np.nan,
               "p10": p10, "p_pos10": float(np.mean(gap >= DIVERGE)) if len(gap) else np.nan,
               "p_neg10": float(np.mean(gap <= -DIVERGE)) if len(gap) else np.nan, "class": classify(p10)}

        # 세 항·집중·게이트의 중앙값과 뒤집힘 비율을 붙인다
        for col in ("cell_auc", "object_auc", "capture", "object_capture", "term_size_weight", "term_within_object",
                    "term_erasure", "n_eff", "n_survive", "n_K", "top10_share", "max_event_share", "sd_A", "rho_wA",
                    "concentration_factor", "n_pos_cells", "n_polygons"):
            row[f"{col}_median"] = float(ok[col].median()) if len(ok) else np.nan
        row["erased_frac_median"] = float((1 - ok["n_survive"] / ok["n_K"]).median()) if len(ok) else np.nan
        erasure = ok["term_erasure"].to_numpy()
        row["erasure_median_lo"], row["erasure_median_hi"] = median_interval(erasure)
        for col in ("grid_pass", "object_pass", "unit_flip", "auc_unit_flip", "rule_flip"):
            row[f"{col}_rate"] = float(ok[col].mean()) if len(ok) else np.nan
        rows.append(row)
    table = pd.DataFrame(rows)
    return scenarios.merge(table, left_on="no", right_on="scenario_no", how="right").drop(columns="no")


def flip_conditions(rep: pd.DataFrame) -> pd.DataFrame:
    """모든 평가 가능 복제를 (Ã − 0.70) 구간 × 차이 구간으로 묶은 AUC·게이트 단위 뒤집힘 비율 (규칙별)."""
    # 구간을 매기고 규칙 × 두 구간으로 센다
    ok = rep[rep["evaluable"]].copy()
    ok["distance_bin"] = pd.cut(ok["object_auc"] - GATE["auc_min"], DISTANCE_BINS, right=False).astype(str)
    ok["gap_bin"] = pd.cut(ok["gap"], GAP_BINS, right=False).astype(str)
    return ok.groupby(["rule", "distance_bin", "gap_bin"], sort=True).agg(
        n=("gap", "size"), auc_unit_flip_rate=("auc_unit_flip", "mean"), unit_flip_rate=("unit_flip", "mean"),
        grid_pass_rate=("grid_pass", "mean"), object_pass_rate=("object_pass", "mean")).reset_index()


def event_aggregation(rep: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """B 묶음 복제마다 V1(합동 라벨 게이트)과 V2(양성 칸 ≥ 5 사상의 AUC·포착 중앙값 게이트)."""
    # 사상별 행에서 V2 중앙값을 만든다
    ok = events[events["n_pos_cells"] >= MIN_POS]
    v2 = ok.groupby(["scenario_no", "replicate"]).agg(v2_auc=("cell_auc", "median"), v2_capture=("capture", "median"),
                                                     v2_object_auc=("object_auc", "median"), n_events_used=("event", "size"))
    v1 = rep[rep["rule"] == REFERENCE_RULE].set_index(["scenario_no", "replicate"])[
        ["cell_auc", "capture", "object_auc", "max_event_share", "evaluable"]].rename(
        columns={"cell_auc": "v1_auc", "capture": "v1_capture", "object_auc": "v1_object_auc"})

    # 합동과 사상 중앙값 게이트를 비교한다
    table = v1.join(v2, how="left").reset_index()
    table["v1_pass"] = passes(table["v1_auc"], table["v1_capture"])
    table["v2_pass"] = passes(table["v2_auc"], table["v2_capture"])
    table["v2_evaluable"] = table["n_events_used"].fillna(0) > 0
    table["v1_v2_flip"] = table["evaluable"] & table["v2_evaluable"] & (table["v1_pass"] != table["v2_pass"])
    table["v1_minus_v2_auc"] = table["v1_auc"] - table["v2_auc"]
    return table


def event_summary(agg: pd.DataFrame) -> pd.DataFrame:
    """B 시나리오마다 사상 최대 몫·V1−V2 차이·뒤집힘 비율의 요약."""
    # 두 쪽 모두 평가 가능한 복제만 센다
    ok = agg[agg["evaluable"] & agg["v2_evaluable"]]
    return ok.groupby("scenario_no").agg(
        n=("v1_auc", "size"), max_event_share_median=("max_event_share", "median"),
        v1_auc_median=("v1_auc", "median"), v2_auc_median=("v2_auc", "median"),
        v1_minus_v2_auc_median=("v1_minus_v2_auc", "median"),
        p_abs_v1_v2_ge_01=("v1_minus_v2_auc", lambda d: float(np.mean(np.abs(d) >= DIVERGE))),
        v1_pass_rate=("v1_pass", "mean"), v2_pass_rate=("v2_pass", "mean"), v1_v2_flip_rate=("v1_v2_flip", "mean"),
        n_events_used_median=("n_events_used", "median")).reset_index()
