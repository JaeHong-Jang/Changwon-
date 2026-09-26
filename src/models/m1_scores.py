"""M1 점수: 지형·불투수 자명 기준선 (시간순 재학습은 prior_fit 에서 가져온다)."""

from __future__ import annotations

import numpy as np
import pandas as pd

# 기존 호출자(m1_run·tests)의 import 경로를 유지한다.
from src.models.prior_fit import DEV_YEARS, prior_years, trained_before  # noqa: F401

# 기준선 이름 → (특징 열, 부호). 부호 −1 은 "작을수록 위험"을 "클수록 위험"으로 뒤집는다.
BASELINES = {
    "slope_neg": ("slope_deg", -1.0),
    "relelev_neg": ("rel_elev_m", -1.0),
    "twi": ("twi", 1.0),
    "impervious": ("impervious_frac", 1.0),
}


def baseline_scores(features: pd.DataFrame, hand_osm: np.ndarray, hand_acc: np.ndarray) -> dict[str, np.ndarray]:
    """격자 순서의 특징표와 HAND 두 가지로 자명 기준선 점수를 만든다."""
    # 특징 열에 부호를 곱하고 HAND 는 낮을수록 위험으로 뒤집는다
    out = {name: sign * features[column].to_numpy(float) for name, (column, sign) in BASELINES.items()}
    out["hand_neg"] = -np.asarray(hand_osm, float)
    out["hand_acc_neg"] = -np.asarray(hand_acc, float)
    return out
