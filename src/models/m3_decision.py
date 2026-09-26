"""M3 사전 판정: 중첩 선택·고정 구성·경사 기준선의 사상별 격자 AUC 중앙값 비교 (docs/q1/M3_protocol.md §5)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.models.m1_decision import MARGIN, compare

FIXED, PRIMARY, SECONDARY, SLOPE = "rf_F1_wf", "nested_rf", "nested_all", "slope_neg"
OPTIMISTIC = "고정 구성 walk-forward 는 설정 선택에 쓴 미래 정보로 0.02 넘게 낙관적이다"
NOT_OPTIMISTIC = "설정 선택의 미래 정보가 격자 AUC 중앙값을 0.02 넘게 올리지 않았다"
M1_HOLDS = "M1 의 C-b 폐기 판정은 중첩 선택에서도 유지된다"
M1_DEPENDS = "M1 판정이 설정 선택 방식에 달려 있다"


def optimism(long: pd.DataFrame, nested: str, **kwargs: Any) -> dict:
    """중첩 점수 대 고정 구성 비교 (within_margin 은 중첩 ≥ 고정 − 0.02, 짝 차이는 고정 − 중첩)."""
    # 판정 문구와 '중첩이 0.02 넘게 높다' 여부를 붙인다
    result = compare(long, nested, FIXED, **kwargs)
    if result["evaluable"]:
        result["verdict"] = NOT_OPTIMISTIC if result["within_margin"] else OPTIMISTIC
        result["nested_higher_by_margin"] = bool(result["median_" + nested] > result["median_" + FIXED] + MARGIN)
    return result


def m1_recheck(long: pd.DataFrame, events: list[str], nested: str) -> dict:
    """E_nest 사상에서 경사 대 중첩, 경사 대 고정 구성을 M1 규칙으로 다시 본다."""
    # E_nest 로 제한한 표에서 두 비교를 한다
    sub = long[long["test_event"].astype(str).isin(events)]
    vs_nested, vs_fixed = compare(sub, SLOPE, nested), compare(sub, SLOPE, FIXED)
    if vs_nested["evaluable"]:
        vs_nested["verdict"] = M1_HOLDS if vs_nested["within_margin"] else M1_DEPENDS
    return {"slope_vs_nested": vs_nested, "slope_vs_fixed": vs_fixed}


def decide(long: pd.DataFrame) -> dict:
    """주 판정(nested_rf 대 고정 구성, ALL·격자 AUC·개발+홀드아웃), M1 재확인, 보조 비교를 묶는다."""
    # 주 판정과 E_nest
    primary = optimism(long, PRIMARY)
    events = [str(e) for e in primary["events"]]
    verdict = primary.get("verdict", "판정 불가")

    # M1 재확인과 보조 비교 (판정에 쓰지 않는다)
    secondary = {
        "nested_all_vs_fixed": optimism(long, SECONDARY),
        "m1_recheck_nested_all": m1_recheck(long, events, SECONDARY),
        "dev_only": optimism(long, PRIMARY, roles=("development",)),
        "holdout_only": optimism(long, PRIMARY, roles=("holdout",)),
        "object_auc": optimism(long, PRIMARY, unit="object"),
        "capture_0.2": optimism(long, PRIMARY, metric="capture_0.2"),
        "flat_stratum": optimism(long, PRIMARY, stratum="FLAT"),
        "nested_all_object_auc": optimism(long, SECONDARY, unit="object"),
    }
    return {"rule": f"median({PRIMARY}) < median({FIXED}) - {MARGIN} 이면 고정 구성 낙관 판정",
            "E_nest": events, "primary": primary, "verdict": verdict,
            "m1_recheck": m1_recheck(long, events, PRIMARY), "secondary": secondary}


def selection_gap(long: pd.DataFrame, chosen: pd.DataFrame) -> pd.DataFrame:
    """고른 설정의 안쪽 선택 점수와 바깥 격자·덩어리 AUC (ALL 층) 를 사상별로 나란히 놓는다."""
    # 바깥 격자·덩어리 AUC 를 사상·점수별로 편다
    rows = long[(long["stratum"] == "ALL") & (long["storm"] == "ALL") & (long["metric"] == "observed-label_auc")
                & long["unit"].isin(["cell_gate", "cluster_gate"]) & long["score"].isin([PRIMARY, SECONDARY, FIXED])]
    outer = rows.pivot_table(index=["test_event", "score"], columns="unit", values="value").reset_index()
    outer["test_event"] = outer["test_event"].astype(str)

    # 사상별 선택 점수를 붙이고 차이(안쪽 − 바깥 덩어리 AUC)를 구한다
    merged = chosen.astype({"test_event": str}).merge(outer, on=["test_event", "score"], how="left")
    merged["inner_minus_outer_cluster"] = merged["selection_score"] - merged["cluster_gate"]
    return merged
