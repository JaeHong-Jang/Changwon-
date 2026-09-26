"""M1 점수: 지형·불투수 자명 기준선과 이전 사상만으로 다시 학습한 모델 점수."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone

# 기준선 이름 → (특징 열, 부호). 부호 −1 은 "작을수록 위험"을 "클수록 위험"으로 뒤집는다.
BASELINES = {
    "slope_neg": ("slope_deg", -1.0),
    "relelev_neg": ("rel_elev_m", -1.0),
    "twi": ("twi", 1.0),
    "impervious": ("impervious_frac", 1.0),
}
DEV_YEARS = (2006, 2012, 2014, 2016, 2019, 2025)


def baseline_scores(features: pd.DataFrame, hand_osm: np.ndarray, hand_acc: np.ndarray) -> dict[str, np.ndarray]:
    """격자 순서의 특징표와 HAND 두 가지로 자명 기준선 점수를 만든다."""
    # 특징 열에 부호를 곱하고 HAND 는 낮을수록 위험으로 뒤집는다
    out = {name: sign * features[column].to_numpy(float) for name, (column, sign) in BASELINES.items()}
    out["hand_neg"] = -np.asarray(hand_osm, float)
    out["hand_acc_neg"] = -np.asarray(hand_acc, float)
    return out


def prior_years(year: int) -> list[int]:
    """시험 연도보다 이른 개발 사상 (2025 제외)."""
    return [y for y in DEV_YEARS if y < year and y != 2025]


def trained_before(frame: pd.DataFrame, layer: Any, year: int, model: Any, columns: list[str]) -> np.ndarray | None:
    """year 이전 개발 사상 라벨 합집합으로 모델을 다시 학습한 전 격자 점수 (이전 사상이 없으면 None)."""
    # 이전 사상의 격자 라벨을 합치고 복제한 모델을 학습해 전 격자에 점수를 매긴다
    prior = prior_years(year)
    if not prior:
        return None
    y_train = layer[[f"trace_ev_{y}" for y in prior]].to_numpy().any(axis=1)
    X = frame[columns].to_numpy(float)
    return clone(model).fit(X, y_train).predict_proba(X)[:, 1]
