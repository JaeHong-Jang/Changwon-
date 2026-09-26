"""M1 배경 층: 평지·시가지·농경지 대리·인구 거주 격자 (임계는 docs/q1/M1_protocol.md §3)."""

from __future__ import annotations

import numpy as np
import pandas as pd

FLAT_SLOPE_DEG = 5.0
URBAN_IMPERVIOUS = 0.5
AGRI_IMPERVIOUS = 0.1
AGRI_WATER = 0.5


def strata(features: pd.DataFrame) -> dict[str, np.ndarray]:
    """격자 순서의 특징표로 층 마스크를 만든다 (ALL 은 evaluate 가 붙인다)."""
    # 경사·불투수·내륙수·거주 열로 층을 정의한다
    slope = features["slope_deg"].to_numpy(float)
    imp = features["impervious_frac"].to_numpy(float)
    water = features["inland_water_frac"].fillna(0).to_numpy(float)
    flat = slope <= FLAT_SLOPE_DEG
    return {
        "FLAT": flat,
        "URBAN": imp >= URBAN_IMPERVIOUS,
        "AGRI": (imp < AGRI_IMPERVIOUS) & flat & (water < AGRI_WATER),
        "UNIVERSE": features["universe"].fillna(0).to_numpy().astype(bool),
    }
