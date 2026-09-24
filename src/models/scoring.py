"""비교 모델의 격자·덩어리 지표와 상위 포착률을 계산한다."""

from __future__ import annotations

import numpy as np

from src.data.uncertainty import cluster_weighted_auc


METRICS = ["grid_auc", "cluster_auc", "observed_label_ap", "top20_capture"]


def score_metrics(labels: np.ndarray, scores: np.ndarray, points: np.ndarray) -> dict[str, float]:
    """격자·덩어리 AUC와 관측 라벨 AP 및 동점 분할 상위 20% 포착률을 구한다."""
    # 격자 AUC와 관측 라벨 AP 계산 함수를 불러온다.
    from sklearn.metrics import average_precision_score, roc_auc_score

    # 예측을 검증하고 단일 클래스 입력은 NaN 지표로 반환한다.
    labels = np.asarray(labels, dtype=bool)
    if not np.isfinite(scores).all():
        raise ValueError("예측에 비유한 값이 있다")
    if not labels.any() or labels.all():
        return dict.fromkeys(METRICS, float("nan"))
    # 경계 동점에 분수 가중치를 주어 정확히 20% 예산을 평가한다.
    budget = 0.2 * len(labels)
    threshold = np.sort(scores)[-int(np.ceil(budget))]
    above, tied = scores > threshold, scores == threshold
    fraction = (budget - above.sum()) / tied.sum()
    capture = (labels[above].sum() + fraction * labels[tied].sum()) / labels.sum()
    return {"grid_auc": float(roc_auc_score(labels, scores)),
            "cluster_auc": cluster_weighted_auc(labels, scores, points[:, 0], points[:, 1]),
            "observed_label_ap": float(average_precision_score(labels, scores)),
            "top20_capture": float(capture)}
