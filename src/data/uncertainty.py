"""공간 자기상관을 반영한 불확실성. 재표본 단위는 격자가 아니라 침수 덩어리다."""

from __future__ import annotations

from typing import Any

import numpy as np

# 100m 격자의 상하좌우·대각선 이웃을 같은 덩어리로 묶는 반경.
NEIGHBOUR_RADIUS_M = 150.0
DEFAULT_N_BOOT = 4000


# 덩어리.

def spatial_clusters(x: np.ndarray, y: np.ndarray, radius_m: float = NEIGHBOUR_RADIUS_M) -> np.ndarray:
    """중심점이 radius_m 안에서 이어지는 격자를 한 덩어리로 묶는다."""
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
    sizes = np.bincount(spatial_clusters(x[positive], y[positive]))
    return {
        "n_positive_grid": int(positive.size),
        "n_cluster": int(sizes.size),
        "cluster_size_median": int(np.median(sizes)),
        "cluster_size_max": int(sizes.max()),
        "largest_cluster_share": round(float(sizes.max() / positive.size), 3),
        "note": "격자 수가 아니라 덩어리 수가 유효 표본이다. 붙어 있는 격자는 같은 침수 한 건이다",
    }


def _resample(n_units: int, n_boot: int, seed: int) -> np.ndarray:
    """덩어리 번호를 복원추출한 (n_boot × n_units) 행렬. 모든 재표본을 한 번에 뽑는다."""
    return np.random.default_rng(seed).integers(0, n_units, (n_boot, n_units))


def _ci(values: np.ndarray, digits: int = 4) -> list[float]:
    finite = values[np.isfinite(values)]
    lo, hi = np.percentile(finite, [2.5, 97.5])
    return [round(float(lo), digits), round(float(hi), digits)]


# AUC.

def auc_fractions(labels: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """양성 격자마다 임의의 음성보다 점수가 높을 확률. 동점은 절반이다."""
    y = np.asarray(labels).astype(bool)
    s = np.asarray(scores, dtype=float)
    negative = np.sort(s[~y])
    below = np.searchsorted(negative, s[y], side="left")
    at_or_below = np.searchsorted(negative, s[y], side="right")
    return (below + 0.5 * (at_or_below - below)) / negative.size


class _ClusteredPositives:
    """양성 격자를 덩어리로 묶고, 덩어리별 합·개수를 들고 다닌다. 재표본 계산의 공통 재료."""

    def __init__(self, labels: np.ndarray, x: np.ndarray, y: np.ndarray):
        positive = np.flatnonzero(np.asarray(labels).astype(bool))
        self.cluster_id = spatial_clusters(x[positive], y[positive])
        self.n_cluster = int(self.cluster_id.max()) + 1
        self.counts = np.bincount(self.cluster_id, minlength=self.n_cluster).astype(float)

    def sums(self, per_grid: np.ndarray) -> np.ndarray:
        """양성 격자별 값을 덩어리별로 더한다."""
        return np.bincount(self.cluster_id, weights=per_grid, minlength=self.n_cluster)

    def grid_weighted(self, per_grid: np.ndarray) -> float:
        """격자마다 1표 — 보통의 평균."""
        return float(per_grid.mean())

    def cluster_weighted(self, per_grid: np.ndarray) -> float:
        """침수마다 1표 — 덩어리 안에서 평균한 뒤 덩어리끼리 평균한다."""
        return float((self.sums(per_grid) / self.counts).mean())


def cluster_weighted_auc(labels: np.ndarray, scores: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    """침수 1건 = 1표로 센 AUC. 덩어리 안의 격자들을 평균한 뒤 덩어리끼리 평균한다."""
    return _ClusteredPositives(labels, x, y).cluster_weighted(auc_fractions(labels, scores))


def cluster_bootstrap_auc(
    labels: np.ndarray,
    scores: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = 42,
) -> dict[str, Any]:
    """덩어리 단위 재표본으로 AUC 의 95% 신뢰구간을 구한다."""
    y_true = np.asarray(labels).astype(bool)
    if not y_true.any() or y_true.all():
        return {"auc": None, "reason": "양성 또는 음성이 없다"}

    fractions = auc_fractions(y_true, scores)
    cp = _ClusteredPositives(y_true, x, y)
    sums = cp.sums(fractions)
    means = sums / cp.counts
    picks = _resample(cp.n_cluster, n_boot, seed)
    grid_draws = sums[picks].sum(axis=1) / cp.counts[picks].sum(axis=1)
    cluster_draws = means[picks].mean(axis=1)

    ci = _ci(grid_draws)
    return {
        "auc": round(cp.grid_weighted(fractions), 4),
        "ci95": ci,
        "ci_width": round(ci[1] - ci[0], 4),
        "auc_cluster_weighted": round(cp.cluster_weighted(fractions), 4),
        "ci95_cluster_weighted": _ci(cluster_draws),
        "n_cluster": cp.n_cluster,
        "n_boot": n_boot,
        "resample_unit": "덩어리 (연결된 양성 격자 묶음)",
        "note": "auc 는 격자마다 1표, auc_cluster_weighted 는 침수 한 건마다 1표",
    }


def paired_cluster_bootstrap(
    labels: np.ndarray,
    scores: dict[str, np.ndarray],
    reference: str,
    x: np.ndarray,
    y: np.ndarray,
    *,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = 42,
) -> dict[str, Any]:
    """여러 점수를 기준 점수와 짝지어 비교한다. 같은 재표본을 모든 점수에 쓴다."""
    y_true = np.asarray(labels).astype(bool)
    cp = _ClusteredPositives(y_true, x, y)
    picks = _resample(cp.n_cluster, n_boot, seed)
    denominator = cp.counts[picks].sum(axis=1)

    fractions = {name: auc_fractions(y_true, s) for name, s in scores.items()}
    sums = {name: cp.sums(f) for name, f in fractions.items()}
    means = {name: sums[name] / cp.counts for name in fractions}

    out: dict[str, Any] = {"reference": reference, "n_cluster": cp.n_cluster, "n_boot": n_boot}
    for name in scores:
        if name == reference:
            continue
        grid_diff = (sums[name] - sums[reference])[picks].sum(axis=1) / denominator
        cluster_diff = (means[name] - means[reference])[picks].mean(axis=1)
        out[name] = {
            "diff": round(cp.grid_weighted(fractions[name]) - cp.grid_weighted(fractions[reference]), 4),
            "diff_ci95": _ci(grid_diff),
            "prob_better": round(float((grid_diff > 0).mean()), 3),
            "diff_cluster_weighted": round(
                cp.cluster_weighted(fractions[name]) - cp.cluster_weighted(fractions[reference]), 4
            ),
            "diff_ci95_cluster_weighted": _ci(cluster_diff),
            "prob_better_cluster_weighted": round(float((cluster_diff > 0).mean()), 3),
        }
    return out


# 등급별 발생률.

def grade_incidence_bootstrap(
    unit_counts: np.ndarray,
    sizes: np.ndarray,
    *,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = 42,
) -> dict[str, Any]:
    """침수 덩어리 단위로 등급별 발생률을 재표본한다."""
    unit_counts = np.asarray(unit_counts, dtype=float)
    sizes = np.asarray(sizes, dtype=float)
    k = sizes.size
    levels = np.arange(1, k + 1, dtype=float)
    weights = sizes / sizes.sum()
    centred = levels - (weights * levels).sum()
    denominator = (weights * centred**2).sum()

    def slope(rate: np.ndarray) -> np.ndarray:
        """등급 점수에 대한 발생률의 가중 최소제곱 기울기 (행마다)."""
        mean = (rate * weights).sum(axis=-1, keepdims=True)
        return ((rate - mean) * centred * weights).sum(axis=-1) / denominator

    point = unit_counts.sum(axis=0) / sizes
    picks = _resample(len(unit_counts), n_boot, seed)
    counts = unit_counts[picks].sum(axis=1)                  # (n_boot, k)
    rate = counts / sizes
    base = counts.sum(axis=1) / sizes.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        top_lift = rate[:, -1] / base
    slopes = slope(rate)
    return {
        "n_cluster": int(len(unit_counts)),
        "top_grade_lift_ci95": _ci(top_lift, 2),
        "monotone_share": round(float(np.all(np.diff(rate, axis=1) >= 0, axis=1).mean()), 3),
        "trend_slope": round(float(slope(point)), 6),
        "trend_slope_ci95": _ci(slopes, 6),
        "p_slope_nonpositive": round(float((slopes <= 0).mean()), 4),
        "n_boot": n_boot,
    }


def unit_grade_counts(
    grades: np.ndarray, labels: np.ndarray, x: np.ndarray, y: np.ndarray, n_classes: int = 5
) -> np.ndarray:
    """양성 격자를 덩어리로 묶고, 덩어리마다 각 등급에 걸친 격자 수를 센다."""
    g = np.asarray(grades).astype(int)
    positive = np.flatnonzero(np.asarray(labels).astype(bool))
    if positive.size == 0:
        return np.zeros((0, n_classes))
    cid = spatial_clusters(x[positive], y[positive])
    counts = np.zeros((int(cid.max()) + 1, n_classes))
    np.add.at(counts, (cid, g[positive] - 1), 1)
    return counts


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
    """한 벌의 라벨로 등급 배정을 채점할 때의 덩어리 단위 불확실성."""
    g = np.asarray(grades).astype(int)
    if not np.asarray(labels).astype(bool).any():
        return {"available": False, "reason": "양성이 없다"}
    units = unit_grade_counts(g, labels, x, y, n_classes)
    sizes = np.bincount(g, minlength=n_classes + 1)[1:]
    result = grade_incidence_bootstrap(units, sizes, n_boot=n_boot, seed=seed)
    result["available"] = True
    result["clusters_by_grade"] = {f"R{k + 1}": int((units[:, k] > 0).sum()) for k in range(n_classes)}
    return result
