"""사상 단위 확률·범주 지표와 짝지은 불확실성을 계산한다."""

import numpy as np
import pandas as pd
from scipy.stats import beta, rankdata


def _paired(*arrays):
    """같은 길이의 벡터에서 모든 값이 유한한 짝만 남긴다."""
    # 모형과 기준의 결측은 반드시 같은 사상에서 제거한다.
    values = [np.asarray(a, dtype=float) for a in arrays]
    if any(a.ndim != 1 or a.shape != values[0].shape for a in values):
        raise ValueError("arrays must be equal-length vectors")
    keep = np.logical_and.reduce([np.isfinite(a) for a in values])
    return [a[keep] for a in values]


def brier(p, y):
    """유효 사상의 평균 확률 제곱오차를 반환한다."""
    # 공통 유효 쌍이 없으면 점수를 정의하지 않는다.
    p, y = _paired(p, y)
    return float(np.mean((p - y) ** 2)) if len(y) else np.nan


def bss_pooled(p, y, p_ref):
    """사상별 기준오차 합으로 나눈 pooled BSS를 반환한다."""
    # fold별 BSS를 평균하지 않고 같은 사상의 오차를 합친다.
    p, y, p_ref = _paired(p, y, p_ref)
    denominator = np.sum((p_ref - y) ** 2)
    return float(1 - np.sum((p - y) ** 2) / denominator) if denominator > 0 else np.nan


def auc(p, y):
    """평균 동점 순위를 쓰는 사상 ROC AUC를 반환한다."""
    # 한 클래스만 있는 재표집은 정의 불가로 남긴다.
    p, y = _paired(p, y)
    n_pos, n_neg = int((y == 1).sum()), int((y == 0).sum())
    if not n_pos or not n_neg:
        return np.nan
    return float((rankdata(p)[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def reliability(p, y, edges=(0, 0.1, 0.3, 0.6, 1.0)):
    """마지막 오른쪽 경계만 포함하는 고정 구간 신뢰도표를 만든다."""
    # 빈 구간도 남겨 자료가 없는 확률 범위를 드러낸다.
    p, y = _paired(p, y)
    rows = []
    for i, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
        mask = (p >= left) & ((p <= right) if i == len(edges) - 2 else (p < right))
        rows.append(dict(left=left, right=right, n=int(mask.sum()),
                         mean_p=float(p[mask].mean()) if mask.any() else np.nan,
                         observed=float(y[mask].mean()) if mask.any() else np.nan))
    return pd.DataFrame(rows)


def categorical(warn, y):
    """이진 경보의 분할표와 POD·FAR·CSI를 반환한다."""
    # 결측 경보를 음성으로 바꾸지 않고 분할표에서 제외한다.
    warn, y = _paired(warn, y)
    hits = int(((warn == 1) & (y == 1)).sum())
    misses = int(((warn == 0) & (y == 1)).sum())
    false = int(((warn == 1) & (y == 0)).sum())
    correct = int(((warn == 0) & (y == 0)).sum())
    return dict(hits=hits, misses=misses, false_alarms=false, correct_negatives=correct,
                pod=hits / (hits + misses) if hits + misses else np.nan,
                far=false / (hits + false) if hits + false else np.nan,
                csi=hits / (hits + misses + false) if hits + misses + false else np.nan)


def clopper_pearson(k, n, confidence=0.95):
    """이항 성공 횟수의 양측 Clopper–Pearson 구간을 반환한다."""
    # 성공 또는 실패가 전혀 없는 끝점도 정확 구간으로 처리한다.
    if n < 0 or k < 0 or k > n or int(k) != k or int(n) != n or not 0 < confidence < 1:
        raise ValueError("invalid binomial counts or confidence")
    if n == 0:
        return np.nan, np.nan
    alpha = (1 - confidence) / 2
    return (0.0 if k == 0 else float(beta.ppf(alpha, k, n - k + 1)),
            1.0 if k == n else float(beta.ppf(1 - alpha, k + 1, n - k)))


def paired_bootstrap(stat_fn, arrays, n=2000, seed=20260926):
    """같은 사상 인덱스를 모든 배열에 적용해 백분위 구간을 구한다."""
    # 결측 제거는 지표 함수에 맡기고 원래 짝과 표본 크기를 보존한다.
    arrays = [np.asarray(a) for a in arrays]
    if not arrays or any(a.ndim == 0 or len(a) != len(arrays[0]) for a in arrays):
        raise ValueError("arrays must have equal event counts")
    if n < 0:
        raise ValueError("n must be nonnegative")
    estimate = float(stat_fn(*arrays))
    rng = np.random.default_rng(seed)
    valid = []
    for _ in range(n):
        indices = rng.integers(0, len(arrays[0]), len(arrays[0]))
        value = float(stat_fn(*(a[indices] for a in arrays)))
        if np.isfinite(value):
            valid.append(value)
    lo, hi = np.percentile(valid, [2.5, 97.5]) if valid else (np.nan, np.nan)
    return dict(estimate=estimate, lo=float(lo), hi=float(hi), n_valid=len(valid), n_undefined=n - len(valid))
