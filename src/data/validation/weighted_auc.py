"""양성·음성 질량을 가진 칸의 가중 중간 누적분포와 가중 Mann–Whitney AUC (docs/q1/M4_protocol.md §5)."""

from __future__ import annotations

import numpy as np


def weighted_mid_cdf(values: np.ndarray, reference: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """reference 점수의 가중 경험분포에서 values 의 중간 누적확률 (동점 질량은 절반)."""
    # 기준 점수를 정렬하고 누적 질량으로 왼쪽·오른쪽 누적값을 찾는다
    ref = np.asarray(reference, dtype=float)
    w = np.asarray(weights, dtype=float)
    order = np.argsort(ref, kind="stable")
    ref, cum = ref[order], np.concatenate([[0.0], np.cumsum(w[order])])
    if not len(ref) or cum[-1] <= 0:
        return np.full(len(np.atleast_1d(values)), np.nan)
    v = np.asarray(values, dtype=float)
    left = cum[np.searchsorted(ref, v, side="left")]
    right = cum[np.searchsorted(ref, v, side="right")]
    return np.where(np.isfinite(v), (left + right) / (2 * cum[-1]), np.nan)


def weighted_auc(score: np.ndarray, p: np.ndarray, q: np.ndarray | None = None) -> float:
    """칸별 양성 질량 p·음성 질량 q(기본 1 − p)로 Σ p_i q_j H(s_i − s_j) / (Σp Σq) 를 구한다 (점수 결측 칸 제외)."""
    # 점수가 있는 칸만 남기고 양성·음성 질량이 모두 있는지 확인한다
    s = np.asarray(score, dtype=float)
    p = np.asarray(p, dtype=float)
    q = 1.0 - p if q is None else np.asarray(q, dtype=float)
    keep = np.isfinite(s)
    s, p, q = s[keep], p[keep], q[keep]
    if p.sum() <= 0 or q.sum() <= 0:
        return np.nan

    # 양성 질량으로 음성 질량 중간 누적분포를 평균한다
    return float(np.dot(p, weighted_mid_cdf(s, s, q)) / p.sum())
