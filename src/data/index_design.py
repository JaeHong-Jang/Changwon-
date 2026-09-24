"""CDRI 불확실성 분석의 설계 공간과 요소 정규화를 정의한다."""

from __future__ import annotations

import itertools

import numpy as np

from src.data import layers as L

RAW_COLUMNS = ("L1", "E", "V", "capacity_deficit")
FLOORS = (0.01, 0.05, 0.10)
NORMALIZATIONS = ("minmax", "percentile")
AGGREGATIONS = ("geometric", "additive")
WEIGHT_MODES = ("equal", "entropy", "dirichlet")
COMPONENT_SETS = ("HEVD", "HEV")
FACTOR_LEVELS = {
    "floor": FLOORS,
    "normalization": NORMALIZATIONS,
    "aggregation": AGGREGATIONS,
    "weights": WEIGHT_MODES,
    "components": COMPONENT_SETS,
}
DEFAULT_REPLICATES = 40
DEFAULT_SEED = 20260924


def _normalise(raw: np.ndarray, floor: float, method: str) -> np.ndarray:
    """요소별 순위 대상 내부 정규화 후 양의 하한을 적용한다."""
    import pandas as pd

    # 지정한 방식으로 각 요소를 양의 범위로 재척도한다.
    if method == "minmax":
        return np.column_stack([L.rescale_positive(raw[:, j], floor) for j in range(raw.shape[1])])
    if method == "percentile":
        return np.column_stack([
            floor + (1.0 - floor) * pd.Series(raw[:, j]).rank(method="average", pct=True).to_numpy()
            for j in range(raw.shape[1])
        ])
    raise ValueError(f"알 수 없는 정규화: {method}")


def design_combinations():
    """기존 요인 선언 순서대로 설계 조합을 순회한다."""
    # 각 요인의 수준을 직적곱으로 결합한다.
    return itertools.product(*FACTOR_LEVELS.values())
