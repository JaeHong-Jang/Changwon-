"""지수 합성 도구 — 윈저라이즈·z-score·Jenks 자연구분·취약성 매트릭스.

근거: 국토부 「도시 기후변화 재해취약성분석 지침」(z-score 표준화 → 합산 → Jenks 4등급 →
노출×민감도 매트릭스), OECD/JRC(2008) 복합지수 핸드북(정규화·집계).

Jenks 는 외부 패키지(jenkspy·mapclassify) 없이 Fisher 의 최적 1차원 분할을 직접 구현했다.
정확해를 구하되 분할점 탐색에 divide-and-conquer 최적화를 써서 7만 개 값도 몇 초에 끝난다.
"""

from __future__ import annotations

import numpy as np

# 취약성 매트릭스: (노출등급 + 민감도등급) → 취약성 I~IV. 등급은 1~4 이며 4가 가장 높다.
# I 이 가장 취약하다 (지침 표기). 두 축이 모두 높아야 I 이 되도록 합으로 자른다.
VULNERABILITY_MATRIX: dict[int, int] = {2: 4, 3: 4, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1}
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}


def winsorize(a: np.ndarray, lo: float = 0.01, hi: float = 0.99) -> np.ndarray:
    """양극단을 분위수로 자른다. 이상치 하나가 z-score 전체를 눌러버리는 것을 막는다."""
    a = np.asarray(a, dtype=float)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return a.copy()
    low, high = np.quantile(finite, [lo, hi])
    return np.clip(a, low, high)


def zscore(a: np.ndarray) -> np.ndarray:
    """평균 0, 표준편차 1. 표준편차가 0이면 전부 0 (변별력 없는 변수)."""
    a = np.asarray(a, dtype=float)
    mean = np.nanmean(a)
    std = np.nanstd(a)
    return np.zeros_like(a) if not np.isfinite(std) or std == 0 else (a - mean) / std


def minmax(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    lo, hi = np.nanmin(a), np.nanmax(a)
    return np.zeros_like(a) if hi == lo else (a - lo) / (hi - lo)


def _prefix_sums(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.concatenate([[0.0], np.cumsum(x)]),
        np.concatenate([[0.0], np.cumsum(x * x)]),
    )


def jenks_breaks(values: np.ndarray, k: int) -> list[float]:
    """Fisher-Jenks 자연구분. 등급별 상한값 k개를 오름차순으로 돌려준다.

    급간 내 편차제곱합을 최소화하는 정확해다. dp[m][j] = min_i dp[m-1][i-1] + cost(i, j) 를
    divide-and-conquer 로 풀어 O(k·n·log n) 이다.
    """
    x = np.sort(np.asarray(values, dtype=float))
    x = x[np.isfinite(x)]
    n = x.size
    if n == 0:
        raise ValueError("유한한 값이 하나도 없다")
    if k < 1:
        raise ValueError("k 는 1 이상이어야 한다")
    uniq = np.unique(x)
    if uniq.size <= k:
        # 서로 다른 값이 등급 수보다 적으면 값 자체가 경계다. 남는 등급은 최댓값으로 채운다.
        return [float(v) for v in uniq] + [float(uniq[-1])] * (k - uniq.size)

    s1, s2 = _prefix_sums(x)

    def cost(i: np.ndarray, j: int) -> np.ndarray:
        count = j - i + 1
        total = s1[j + 1] - s1[i]
        square = s2[j + 1] - s2[i]
        return square - total * total / count

    counts = np.arange(1, n + 1, dtype=float)
    prev = (s2[1:] - s2[0]) - (s1[1:] - s1[0]) ** 2 / counts  # m = 1
    args: list[np.ndarray] = [np.zeros(n, dtype=int)]

    for m in range(2, k + 1):
        cur = np.full(n, np.inf)
        arg = np.zeros(n, dtype=int)
        stack = [(m - 1, n - 1, m - 1, n - 1)]
        while stack:
            lo, hi, opt_lo, opt_hi = stack.pop()
            if lo > hi:
                continue
            mid = (lo + hi) // 2
            idx = np.arange(opt_lo, min(mid, opt_hi) + 1)
            total = prev[idx - 1] + cost(idx, mid)
            best = int(np.argmin(total))
            cur[mid] = total[best]
            arg[mid] = idx[best]
            stack.append((lo, mid - 1, opt_lo, arg[mid]))
            stack.append((mid + 1, hi, arg[mid], opt_hi))
        prev = cur
        args.append(arg)

    breaks: list[float] = []
    end = n - 1
    for m in range(k, 1, -1):
        start = int(args[m - 1][end])
        breaks.append(float(x[start - 1]))
        end = start - 1
    breaks.reverse()
    return breaks + [float(x[-1])]


def classify(values: np.ndarray, breaks: list[float]) -> np.ndarray:
    """등급 상한 목록으로 1~k 등급을 매긴다. 값이 상한과 같으면 그 등급에 들어간다."""
    a = np.asarray(values, dtype=float)
    upper = np.asarray(breaks[:-1], dtype=float)
    cls = np.searchsorted(upper, a, side="left") + 1
    return np.clip(cls, 1, len(breaks)).astype("int8")


def vulnerability_class(exposure_class: np.ndarray, sensitivity_class: np.ndarray) -> np.ndarray:
    """노출·민감도 등급(1~4) → 취약성 1~4. 1 이 가장 취약(I등급)."""
    total = np.asarray(exposure_class, dtype=int) + np.asarray(sensitivity_class, dtype=int)
    lookup = np.zeros(max(VULNERABILITY_MATRIX) + 1, dtype="int8")
    for key, value in VULNERABILITY_MATRIX.items():
        lookup[key] = value
    return lookup[np.clip(total, 2, max(VULNERABILITY_MATRIX))]


def composite(frame, spec: dict[str, int], *, winsor_lo: float, winsor_hi: float) -> tuple[np.ndarray, dict]:
    """부호를 맞춘 z-score 합. `spec` 은 {변수명: +1 높을수록 취약 / -1 낮을수록 취약}.

    동일가중이며, 가중치를 바꾸는 것은 H07 민감도 분석의 일이다.
    """
    parts = {}
    for name, sign in spec.items():
        z = zscore(winsorize(frame[name].to_numpy(dtype=float), winsor_lo, winsor_hi)) * sign
        parts[name] = z
    stacked = np.column_stack(list(parts.values()))
    total = stacked.sum(axis=1)
    detail = {
        name: {"sign": spec[name], "z_mean": round(float(np.nanmean(z)), 4), "z_std": round(float(np.nanstd(z)), 4)}
        for name, z in parts.items()
    }
    return total, detail


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """양·음성 라벨이 모두 있을 때의 ROC-AUC (동점은 평균순위로 처리)."""
    y = np.asarray(labels).astype(bool)
    s = np.asarray(scores, dtype=float)
    keep = np.isfinite(s)
    y, s = y[keep], s[keep]
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUC 는 양성과 음성이 모두 있어야 계산할 수 있다")
    order = np.argsort(s, kind="stable")
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1, dtype=float)
    # 동점 보정: 같은 점수 구간의 순위를 평균으로 바꾼다
    sorted_scores = s[order]
    start = 0
    for i in range(1, len(s) + 1):
        if i == len(s) or sorted_scores[i] != sorted_scores[start]:
            if i - start > 1:
                ranks[order[start:i]] = (start + i + 1) / 2.0
            start = i
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def top_share_lift(mask: np.ndarray, scores: np.ndarray, top_fraction: float) -> dict[str, float]:
    """상위 `top_fraction` 격자에 `mask` 가 얼마나 몰려 있는가. 무작위 대비 lift 로 본다."""
    s = np.asarray(scores, dtype=float)
    m = np.asarray(mask).astype(bool)
    n_top = max(1, int(round(len(s) * top_fraction)))
    top = np.argsort(-s, kind="stable")[:n_top]
    capture = float(m[top].sum() / max(1, m.sum()))
    base = float(m.mean())
    share = float(m[top].mean())
    return {
        "n_top": n_top,
        "capture_rate": round(capture, 4),
        "share_in_top": round(share, 4),
        "base_rate": round(base, 4),
        "lift": round(share / base, 3) if base > 0 else float("nan"),
    }


# ── 복합지수 집계 (OECD/JRC 2008 §6·§7) ────────────────────────────────────
# Balica(2012) UNESCO-IHE 박사논문의 5등급 구간. Karmaoui et al.(2016) Table 4 재수록.
BALICA_BREAKS = (0.01, 0.25, 0.50, 0.75)
BALICA_LABELS = ("매우낮음", "낮음", "보통", "높음", "매우높음")


def rescale_positive(a: np.ndarray, floor: float = 0.05) -> np.ndarray:
    """minmax 후 [floor, 1] 로 재척도. 기하평균에서 0 이 전체를 0 으로 만드는 것을 막는다."""
    return floor + (1.0 - floor) * minmax(a)


def entropy_weights(matrix: np.ndarray) -> np.ndarray:
    """엔트로피 가중치. 격자 간 변별력이 큰 지표에 큰 가중치를 준다 (OECD/JRC §6)."""
    x = np.asarray(matrix, dtype=float)
    x = np.where(np.isfinite(x), x, 0.0) + 1e-9
    share = x / x.sum(axis=0, keepdims=True)
    entropy = -(share * np.log(share)).sum(axis=0) / np.log(len(x))
    diversity = 1.0 - entropy
    total = diversity.sum()
    return np.full(x.shape[1], 1.0 / x.shape[1]) if total <= 0 else diversity / total


def geometric_aggregate(matrix: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """가중기하평균. 한 요소가 낮으면 다른 요소가 높아도 보상되지 않는다(비보상성)."""
    x = np.asarray(matrix, dtype=float)
    w = np.asarray(weights, dtype=float)
    return np.exp((w * np.log(np.maximum(x, 1e-12))).sum(axis=1))


def additive_aggregate(matrix: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """가중합. 기하평균의 과소평가 경향(Moreira et al. 2021)을 확인하는 병기용."""
    return (np.asarray(matrix, dtype=float) * np.asarray(weights, dtype=float)).sum(axis=1)


def balica_tier(values: np.ndarray) -> np.ndarray:
    """0~1 지수를 Balica 5등급 라벨로."""
    idx = np.searchsorted(np.asarray(BALICA_BREAKS), np.asarray(values, dtype=float), side="left")
    return np.asarray(BALICA_LABELS, dtype=object)[np.clip(idx, 0, len(BALICA_LABELS) - 1)]


def cohen_kappa(a: np.ndarray, b: np.ndarray) -> float:
    """두 등급 배정의 일치도. 등급화 방식(Balica vs Jenks)이 결과를 얼마나 바꾸는지 본다."""
    a = np.asarray(a)
    b = np.asarray(b)
    labels = sorted(set(a.tolist()) | set(b.tolist()), key=str)
    index = {label: i for i, label in enumerate(labels)}
    table = np.zeros((len(labels), len(labels)))
    for x, y in zip(a, b):
        table[index[x], index[y]] += 1
    total = table.sum()
    observed = np.trace(table) / total
    expected = float((table.sum(axis=0) * table.sum(axis=1)).sum()) / total**2
    return 1.0 if expected >= 1.0 else float((observed - expected) / (1.0 - expected))


def contribution_share(matrix: np.ndarray, weights: np.ndarray, names: list[str]) -> dict[str, np.ndarray]:
    """가법형 구성비 w_k·X_k / Σ w_j·X_j. TOP 20 의 '주 원인'을 이 값으로 설명한다."""
    weighted = np.asarray(matrix, dtype=float) * np.asarray(weights, dtype=float)
    total = weighted.sum(axis=1, keepdims=True)
    share = np.divide(weighted, total, out=np.zeros_like(weighted), where=total > 0)
    return {name: share[:, i] for i, name in enumerate(names)}
