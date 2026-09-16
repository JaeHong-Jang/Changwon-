"""공간 자기상관을 반영한 불확실성 — 격자 수는 표본 수가 아니다.

침수흔적 라벨은 폴리곤 하나가 격자 수십 칸을 덮는다. 붙어 있는 격자들은 **같은 침수 한 건**
이므로 독립 관측이 아니다. 그런데 ROC-AUC 와 부트스트랩은 관측이 독립이라고 가정한다.

이 가정을 무시하면 신뢰구간이 실제보다 훨씬 좁게 나온다. 창원 자료에서 실측하면
격자 단위 95% 구간 폭이 0.035, 덩어리 단위가 0.228 로 **6.5배** 차이였다.
좁은 쪽을 보고하면 "게이트를 여유 있게 통과했다"고 쓰게 되는데 사실이 아니다.

그래서 재표본은 격자가 아니라 **덩어리(연결된 양성 격자 묶음)** 단위로 한다.
이것이 통계학에서 말하는 cluster bootstrap 이며, 유사복제(pseudo-replication)를
바로잡는 표준적인 방법이다.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# 100m 격자에서 대각선 이웃까지 이으면 약 141m 다. 150m 면 상하좌우·대각선이 한 덩어리가 된다.
NEIGHBOUR_RADIUS_M = 150.0
DEFAULT_N_BOOT = 2000


def spatial_clusters(x: np.ndarray, y: np.ndarray, radius_m: float = NEIGHBOUR_RADIUS_M) -> np.ndarray:
    """중심점이 radius_m 안에서 이어지는 격자를 한 덩어리로 묶어 번호를 돌려준다.

    KD-tree 로 반경 내 쌍만 뽑아 연결 성분을 구한다. 모든 쌍을 비교하면 O(n²) 인데,
    이웃만 보면 사실상 O(n log n) 이다.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    points = np.column_stack([x, y])
    pairs = cKDTree(points).query_pairs(radius_m, output_type="ndarray")
    if len(pairs) == 0:
        return np.arange(len(points))
    adjacency = coo_matrix(
        (np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(points),) * 2
    )
    _, labels = connected_components(adjacency, directed=False)
    return labels


def effective_sample(labels: np.ndarray, x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    """양성 격자가 실제로 몇 개의 독립 사건인지 센다. 보고서에 격자 수와 함께 싣는다."""
    positive = np.flatnonzero(np.asarray(labels).astype(bool))
    if positive.size == 0:
        return {"n_positive_grid": 0, "n_cluster": 0}
    clusters = spatial_clusters(x[positive], y[positive])
    sizes = np.bincount(clusters)
    return {
        "n_positive_grid": int(positive.size),
        "n_cluster": int(sizes.size),
        "cluster_size_median": int(np.median(sizes)),
        "cluster_size_max": int(sizes.max()),
        "largest_cluster_share": round(float(sizes.max() / positive.size), 3),
        "note": "격자 수가 아니라 덩어리 수가 유효 표본이다. 붙어 있는 격자는 같은 침수 한 건이다",
    }


def cluster_bootstrap_grades(
    grades: np.ndarray,
    labels: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    n_classes: int = 5,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = 42,
) -> dict[str, Any]:
    """등급별 발생률의 불확실성을 덩어리 단위로 잰다.

    Cochran-Armitage p 값은 격자가 독립이라고 가정한다. 창원 검증 자료에서는 양성 180칸이
    12개 덩어리였고, R5 의 양성 9칸은 **2개 덩어리**였다. 이 상태에서 p = 10⁻⁸ 을 보고하면
    침수 두 건을 아홉 건으로 센 결과를 확정적 증거처럼 쓰게 된다.

    그래서 양성 덩어리를 복원추출해 (1) 최상위 등급 lift 구간, (2) 모든 등급이 단조로
    나오는 재표본의 비율을 낸다. 두 번째가 낮으면 "등급이 오를수록 더 잠긴다"는 주장을
    이 표본으로는 할 수 없다.
    """
    g = np.asarray(grades)
    positive = np.flatnonzero(np.asarray(labels).astype(bool))
    sizes = np.array([(g == k).sum() for k in range(1, n_classes + 1)], dtype=float)
    if positive.size == 0:
        return {"available": False, "reason": "양성이 없다"}

    clusters = spatial_clusters(x[positive], y[positive])
    groups = [positive[clusters == c] for c in np.unique(clusters)]
    by_grade = {
        f"R{k}": int(np.unique(clusters[g[positive] == k]).size) for k in range(1, n_classes + 1)
    }
    rng = np.random.default_rng(seed)

    top_lift = np.empty(n_boot)
    monotone = np.empty(n_boot, dtype=bool)
    for i in range(n_boot):
        picked = np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
        counts = np.bincount(g[picked].astype(int), minlength=n_classes + 1)[1:].astype(float)
        rate = np.divide(counts, sizes, out=np.zeros_like(counts), where=sizes > 0)
        base = counts.sum() / sizes.sum()
        top_lift[i] = rate[-1] / base if base > 0 else np.nan
        monotone[i] = bool(np.all(np.diff(rate) >= 0))

    finite = top_lift[np.isfinite(top_lift)]
    lo, hi = np.percentile(finite, [2.5, 97.5])
    return {
        "available": True,
        "n_cluster": len(groups),
        "clusters_by_grade": by_grade,
        "top_grade_lift_ci95": [round(float(lo), 2), round(float(hi), 2)],
        "monotone_share": round(float(monotone.mean()), 3),
        "n_boot": n_boot,
        "note": (
            "monotone_share 는 덩어리를 재표본했을 때 모든 등급이 단조로 나온 비율이다. "
            "0.95 에 못 미치면 단조성을 확정적으로 주장하지 않는다"
        ),
    }


def cluster_bootstrap_auc(
    labels: np.ndarray,
    scores: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = 42,
) -> dict[str, Any]:
    """덩어리 단위 재표본으로 AUC 의 95% 신뢰구간을 구한다.

    음성 격자는 그대로 두고 양성 덩어리만 복원추출한다. 음성은 수만 칸이라 재표본해도
    분포가 거의 바뀌지 않는 반면, 불확실성의 거의 전부가 양성 쪽에서 오기 때문이다.
    """
    from src.data.layers import roc_auc

    y_true = np.asarray(labels).astype(bool)
    s = np.asarray(scores, dtype=float)
    positive = np.flatnonzero(y_true)
    negative = np.flatnonzero(~y_true)
    if positive.size == 0 or negative.size == 0:
        return {"auc": None, "reason": "양성 또는 음성이 없다"}

    clusters = spatial_clusters(x[positive], y[positive])
    groups = [positive[clusters == c] for c in np.unique(clusters)]
    rng = np.random.default_rng(seed)
    negative_scores = s[negative]

    draws = np.empty(n_boot)
    for i in range(n_boot):
        picked = np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
        resampled = np.concatenate([s[picked], negative_scores])
        truth = np.concatenate([np.ones(picked.size, bool), np.zeros(negative.size, bool)])
        draws[i] = roc_auc(truth, resampled)

    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {
        "auc": round(float(roc_auc(y_true, s)), 4),
        "ci95": [round(float(lo), 4), round(float(hi), 4)],
        "ci_width": round(float(hi - lo), 4),
        "n_cluster": len(groups),
        "n_boot": n_boot,
        "resample_unit": "덩어리 (연결된 양성 격자 묶음)",
    }
