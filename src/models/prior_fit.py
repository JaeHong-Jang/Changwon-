"""시간순 재학습 공통: 시험 사상 이전 개발 사상만으로 모델을 다시 학습한다 (M1·M3)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone

DEV_YEARS = (2006, 2012, 2014, 2016, 2019, 2025)


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
