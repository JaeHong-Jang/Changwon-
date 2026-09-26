"""M3 재현 확인: 안쪽 LOEO 가 동결 벤치마크를, 바깥 채점이 M1 공식 run 을 재현하는지 본다 (절차 §4.3)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.models.m3_select import config_loeo, loeo_splits

TOL = 1e-9
BENCH_HELD = ("2014", "2025")
BENCH_METRICS = ("grid_auc", "cluster_auc", "top20_capture")
KEYS = ["score", "unit", "stratum", "storm", "metric", "test_event"]


def benchmark_loeo(X_f1: np.ndarray, points: np.ndarray, events: np.ndarray, names: list[str],
                   results: pd.DataFrame) -> dict[str, Any]:
    """개발 6사상 LOEO 에서 RF/F1/(4,400) 지표가 results_dev.csv 와 같은지 확인한다 (다르면 멈춘다)."""
    # 여섯 사상 분할 중 벤치마크가 세 부분 모두 (4,400) 을 고른 사상만 고정 구성으로 채점한다
    splits = [s for s in loeo_splits(points, events, names) if s[0].name in BENCH_HELD]
    rows = config_loeo(X_f1, points, splits, "random_forest", {"max_depth": 4, "min_samples_leaf": 400})

    # 벤치마크의 같은 모델·특징·사상 값과 표본 수·지표 차이를 잰다
    ref = results[(results["model"] == "random_forest") & (results["feature_set"] == "F1") & (results["cv"] == "loeo")]
    diffs = {}
    for row in rows:
        held = ref[ref["fold"].astype(str) == row["held_event"]]
        for metric in BENCH_METRICS:
            expected = held.loc[held["metric"] == metric]
            if len(expected) != 1 or int(expected["n_test"].iloc[0]) != row["n_test"] \
                    or int(expected["n_positive"].iloc[0]) != row["n_positive"]:
                raise RuntimeError(f"벤치마크 LOEO 행·표본 수 불일치: {row['held_event']} {metric}")
            diffs[f"{row['held_event']}:{metric}"] = abs(row[metric] - float(expected["value"].iloc[0]))
    worst = max(diffs.values())
    if not worst <= TOL:
        raise RuntimeError(f"안쪽 LOEO 가 동결 벤치마크를 재현하지 못한다 (최대차 {worst})")
    return {"held_events": list(BENCH_HELD), "max_abs_diff": worst, "diffs": diffs}


def match_reference(long: pd.DataFrame, reference: pd.DataFrame, scores: tuple[str, ...],
                    units: tuple[str, ...] | None = None) -> dict[str, Any]:
    """같은 점수·사상·층·단위·지표 행의 값을 기준 긴 표와 비교한다 (양쪽 NaN 은 같다고 본다)."""
    # 두 표를 같은 키로 맞춘다 (units 를 주면 그 단위 행만 본다)
    a = long.loc[long["score"].isin(scores) & (units is None or long["unit"].isin(units)), KEYS + ["value"]]
    a = a.astype({"test_event": str})
    b = reference.loc[reference["score"].isin(scores), KEYS + ["value"]].astype({"test_event": str})
    merged = a.merge(b, on=KEYS, how="left", suffixes=("", "_ref"), validate="one_to_one", indicator=True)

    # 기준에 없는 행, NaN 불일치, 유한 값 최대 절대차를 센다
    missing = int((merged["_merge"] != "both").sum())
    nan_mismatch = int((merged["value"].isna() != merged["value_ref"].isna()).sum())
    finite = merged["value"].notna() & merged["value_ref"].notna()
    worst = float((merged.loc[finite, "value"] - merged.loc[finite, "value_ref"]).abs().max()) if finite.any() else 0.0
    return {"scores": list(scores), "units": "all" if units is None else list(units), "n_rows": len(merged),
            "n_missing_in_reference": missing,
            "n_nan_mismatch": nan_mismatch, "max_abs_diff": worst,
            "passes": missing == 0 and nan_mismatch == 0 and worst <= TOL}
