"""고정된 CDRI 산식의 Shapley 기여도."""

from math import factorial

import numpy as np


def geometric_shapley(matrix, background, weights, *, output_bounds):
    """배경 격자 대비 기여도와 기준값. 출력 정규화 범위는 고정한다."""
    x = np.asarray(matrix, dtype=float)
    b = np.asarray(background, dtype=float)
    w = np.asarray(weights, dtype=float)
    if x.ndim != 2 or b.ndim != 2 or x.shape[1] != 4 or b.shape[1] != 4:
        raise ValueError("H·E·V·D 네 열이 필요하다")
    if not len(b) or not np.isfinite(x).all() or not np.isfinite(b).all():
        raise ValueError("유한한 입력과 비어 있지 않은 배경이 필요하다")
    if (x <= 0).any() or (b <= 0).any():
        raise ValueError("기하평균 입력은 양수여야 한다")
    if w.shape != (4,) or not np.isfinite(w).all() or (w < 0).any() or not np.isclose(w.sum(), 1):
        raise ValueError("가중치는 합이 1인 비음수 네 개여야 한다")
    lo, hi = output_bounds
    if not np.isfinite([lo, hi]).all() or hi <= lo:
        raise ValueError("출력 범위의 최댓값은 최솟값보다 커야 한다")

    # 빠진 요소는 같은 배경 행에서 함께 가져온다.
    observed = x ** w
    reference = b ** w
    coalitions = np.empty((16, len(x)))
    for mask in range(16):
        present = np.array([bool(mask & (1 << j)) for j in range(4)])
        raw = observed[:, present].prod(axis=1) * reference[:, ~present].prod(axis=1).mean()
        coalitions[mask] = (raw - lo) / (hi - lo)

    values = np.zeros_like(x)
    for j in range(4):
        for mask in range(16):
            if mask & (1 << j):
                continue
            size = mask.bit_count()
            weight = factorial(size) * factorial(3 - size) / factorial(4)
            values[:, j] += weight * (coalitions[mask | (1 << j)] - coalitions[mask])
    baseline = (reference.prod(axis=1).mean() - lo) / (hi - lo)
    return values, float(baseline)
