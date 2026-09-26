"""침수흔적 자국을 격자 라벨로 바꾸는 8개 규칙. 결과는 칸별 양성 질량 p ∈ [0, 1] (docs/q1/M4_protocol.md §2)."""

from __future__ import annotations

import numpy as np

from src.data.trace_footprint import Footprint

THRESHOLDS = {"any": 0.0, "f01": 0.01, "f10": 0.10, "f25": 0.25, "f50": 0.50}
RULES = ("any", "f01", "f10", "f25", "f50", "center", "rep_point", "soft")
REFERENCE = "f10"


def positive_mass(rule: str, fp: Footprint, center_in: np.ndarray | None = None) -> np.ndarray:
    """규칙 하나로 칸별 양성 질량을 만든다 (이진 규칙은 0/1, soft 는 침수 비율)."""
    # 칸 면적 대비 침수 합집합 비율을 구한다
    fraction = np.minimum(np.divide(fp.flooded, fp.cell_area, out=np.zeros(fp.n_cells), where=fp.cell_area > 0), 1.0)

    # 임계 규칙은 초과 비교, 연성은 비율 그대로, 중심점·대표점은 해당 칸만 양성이다
    if rule in THRESHOLDS:
        return (fraction > THRESHOLDS[rule]).astype(float)
    if rule == "soft":
        return fraction
    if rule == "center":
        if center_in is None or len(center_in) != fp.n_cells:
            raise ValueError("center 규칙에는 칸 수만큼의 중심점 포함 여부가 필요하다")
        return np.asarray(center_in, dtype=bool).astype(float)
    if rule == "rep_point":
        p = np.zeros(fp.n_cells)
        p[fp.rep_cell[fp.rep_cell >= 0]] = 1.0
        return p
    raise ValueError(f"알 수 없는 라벨 규칙: {rule}")
