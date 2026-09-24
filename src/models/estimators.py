"""고정 후보와 학습 fold 전처리를 사용하는 비교 모델을 정의한다."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin


# 실행 전에 고정한 소규모 후보 집합이며 모든 모델에 클래스 가중을 쓰지 않는다.
CANDIDATES = {
    "ridge": [{"C": 0.1}, {"C": 1.0}],
    "frequency_ratio": [{"n_bins": 5, "alpha": 1.0}, {"n_bins": 10, "alpha": 1.0}],
    "random_forest": [{"max_depth": 2, "min_samples_leaf": 200},
                      {"max_depth": 4, "min_samples_leaf": 400}],
    "xgboost": [{"max_depth": 1}, {"max_depth": 3}],
}


FIXED_PARAMS = {
    "ridge": {"solver": "lbfgs", "max_iter": 500, "class_weight": None, "random_state": 42},
    "frequency_ratio": {},
    "random_forest": {"n_estimators": 48, "max_features": "sqrt", "class_weight": None,
                      "n_jobs": 2, "random_state": 42},
    "xgboost": {"n_estimators": 80, "learning_rate": 0.05, "reg_lambda": 20.0,
                "reg_alpha": 1.0, "min_child_weight": 10, "subsample": 1.0,
                "colsample_bytree": 1.0, "scale_pos_weight": 1.0, "tree_method": "hist",
                "n_jobs": 2, "random_state": 42, "eval_metric": "logloss"},
}


class FrequencyRatio(ClassifierMixin, BaseEstimator):
    """학습 분위 구간의 양성 비율과 면적 비율을 평활화해 로그 비율을 합산한다."""

    def __init__(self, n_bins: int = 5, alpha: float = 1.0):
        """분위 구간 수와 평활화 강도를 저장한다."""
        # 학습 전에 생성자 인자를 그대로 보관한다.
        self.n_bins = n_bins
        self.alpha = alpha

    def fit(self, X: np.ndarray, y: np.ndarray) -> FrequencyRatio:
        """학습 자료에서만 구간 경계와 평활 빈도비를 구한다."""
        # 학습 열별 분위 경계와 평활 로그 빈도비를 저장한다.
        X, y = np.asarray(X), np.asarray(y, dtype=bool)
        self.classes_ = np.array([False, True])
        self.n_features_in_ = X.shape[1]
        self.edges_, self.log_ratios_ = [], []
        for column in X.T:
            edges = np.unique(np.quantile(column, np.linspace(0, 1, self.n_bins + 1)[1:-1]))
            bins = np.searchsorted(edges, column, side="right")
            k = len(edges) + 1
            total = np.bincount(bins, minlength=k)
            positive = np.bincount(bins[y], minlength=k)
            ratio = ((positive + self.alpha) / (y.sum() + self.alpha * k)
                     / ((total + self.alpha) / (len(y) + self.alpha * k)))
            self.edges_.append(edges)
            self.log_ratios_.append(np.log(ratio))
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """로그 빈도비를 단조 변환한 비교 점수를 반환한다."""
        # 로그 빈도비를 확률 범위로 옮길 단조 함수를 불러온다.
        from scipy.special import expit

        # 열별 학습 빈도비를 합산해 두 클래스 점수를 반환한다.
        score = np.zeros(len(X))
        for column, edges, ratios in zip(np.asarray(X).T, self.edges_, self.log_ratios_):
            score += ratios[np.searchsorted(edges, column, side="right")]
        probability = expit(score)
        return np.column_stack([1 - probability, probability])


def make_model(name: str, params: dict[str, Any]) -> Any:
    """결측 대치와 로지스틱 표준화를 학습 fold 안에서 수행하는 모델을 만든다."""
    # fold 안에서 전처리와 학습을 묶는 구성 요소를 불러온다.
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    # 고정 설정과 후보 파라미터로 지정한 모델을 만든다.
    config = FIXED_PARAMS[name] | params
    if name == "ridge":
        estimator = LogisticRegression(**config)
    elif name == "frequency_ratio":
        estimator = FrequencyRatio(**config)
    elif name == "random_forest":
        estimator = RandomForestClassifier(**config)
    elif name == "xgboost":
        # XGBoost 후보를 선택한 경우에만 해당 구현을 불러온다.
        from xgboost import XGBClassifier

        # 고정 설정을 사용하는 부스팅 모델을 만든다.
        estimator = XGBClassifier(**config)
    else:
        raise ValueError(name)
    # 모든 모델은 중앙값 대치를 하고 ridge만 표준화한다.
    steps = [("impute", SimpleImputer(strategy="median", keep_empty_features=True))]
    if name == "ridge":
        steps.append(("scale", StandardScaler()))
    return Pipeline(steps + [("model", estimator)])
