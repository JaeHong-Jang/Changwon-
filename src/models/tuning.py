"""학습 자료 내부의 공간 교차검증으로 고정 후보를 선택한다."""

from __future__ import annotations

from typing import Any

import numpy as np

from src.data.uncertainty import cluster_weighted_auc
from src.models.estimators import CANDIDATES, make_model


def tune_model(
    name: str, X: np.ndarray, labels: np.ndarray, points: np.ndarray, inner: list[Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """외부 학습 자료의 내부 공간 그룹 CV로만 파라미터를 선택한다."""
    # 각 후보를 동일한 내부 fold에서 평가하고 선언 순서로 동점을 푼다.
    trials = []
    for params in CANDIDATES[name]:
        values = []
        for fold in inner:
            if np.unique(labels[fold.train]).size != 2 or np.unique(labels[fold.test]).size != 2:
                raise ValueError("내부 fold에 양성 또는 음성이 없어 사전 지정 CV를 수행할 수 없다")
            model = make_model(name, params).fit(X[fold.train], labels[fold.train])
            scores = model.predict_proba(X[fold.test])[:, 1]
            p = points[fold.test]
            values.append(cluster_weighted_auc(labels[fold.test], scores, p[:, 0], p[:, 1]))
        trials.append({"params": params, "inner_cluster_auc": values, "mean": float(np.mean(values))})
    best = int(np.argmax([trial["mean"] for trial in trials]))
    return dict(CANDIDATES[name][best]), trials
