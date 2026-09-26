"""사상별 효과 크기의 무작위효과 통합: REML·DL τ², 수정 HKSJ 구간, 예측구간, Q·I² 와 Q-profile 구간."""

from __future__ import annotations

import numpy as np
from scipy import optimize, stats

Z975 = float(stats.norm.ppf(0.975))


def logit(p: np.ndarray | float) -> np.ndarray:
    """확률을 로그 오즈로 바꾼다."""
    p = np.asarray(p, dtype=float)
    return np.log(p) - np.log1p(-p)


def expit(x: np.ndarray | float) -> np.ndarray:
    """로그 오즈를 확률로 되돌린다."""
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def se_from_ci(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """95% 구간 양 끝의 logit 거리로 정규 근사 표준오차를 구한다."""
    return (logit(hi) - logit(lo)) / (2.0 * Z975)


def _weighted_mean(y: np.ndarray, v: np.ndarray, tau2: float) -> tuple[float, np.ndarray]:
    """τ² 를 더한 역분산 가중 평균과 가중치."""
    w = 1.0 / (v + tau2)
    return float(np.sum(w * y) / np.sum(w)), w


def cochran_q(y: np.ndarray, v: np.ndarray) -> float:
    """고정효과 가중치로 잰 Cochran Q."""
    mu, w = _weighted_mean(y, v, 0.0)
    return float(np.sum(w * (y - mu) ** 2))


def generalized_q(y: np.ndarray, v: np.ndarray, tau2: float) -> float:
    """τ² 를 더한 가중치로 잰 일반화 Q (Q-profile 에 쓴다)."""
    mu, w = _weighted_mean(y, v, tau2)
    return float(np.sum(w * (y - mu) ** 2))


def tau2_dl(y: np.ndarray, v: np.ndarray) -> float:
    """DerSimonian–Laird 적률 추정 τ²."""
    w = 1.0 / v
    denominator = np.sum(w) - np.sum(w ** 2) / np.sum(w)
    return float(max(0.0, (cochran_q(y, v) - (len(y) - 1)) / denominator)) if denominator > 0 else 0.0


def _reml_negloglik(tau2: float, y: np.ndarray, v: np.ndarray) -> float:
    """상수를 뺀 음의 제한 로그우도."""
    mu, w = _weighted_mean(y, v, tau2)
    return 0.5 * float(np.sum(np.log(v + tau2)) + np.log(np.sum(w)) + np.sum(w * (y - mu) ** 2))


def _upper(y: np.ndarray, v: np.ndarray) -> float:
    """τ² 탐색 상한: 1, 10×분산(y), 10×최대 분산 중 큰 값."""
    spread = float(np.var(y, ddof=1)) if len(y) > 1 else 0.0
    return max(1.0, 10.0 * spread, 10.0 * float(np.max(v)))


def tau2_reml(y: np.ndarray, v: np.ndarray) -> float:
    """제한 로그우도를 [0, U] 에서 최대화한 REML τ² (경계 0 과 비교)."""
    # 유계 Brent 탐색 결과와 τ² = 0 중 우도가 큰 쪽을 고른다
    if len(y) < 2:
        return 0.0
    upper = _upper(y, v)
    found = optimize.minimize_scalar(_reml_negloglik, bounds=(0.0, upper), args=(y, v), method="bounded",
                                     options={"xatol": 1e-12, "maxiter": 2000})
    best = float(found.x)
    return 0.0 if _reml_negloglik(0.0, y, v) <= _reml_negloglik(best, y, v) else best


def q_profile_tau2(y: np.ndarray, v: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    """일반화 Q 가 카이제곱 분위와 같아지는 τ² 로 Q-profile 구간을 구한다."""
    # Q(τ²) 는 τ² 에 대해 감소하므로 경계마다 한 번 근을 찾는다
    df = len(y) - 1
    if df < 1:
        return np.nan, np.nan
    alpha = 1.0 - level
    bounds = []
    for target in (stats.chi2.ppf(1 - alpha / 2, df), stats.chi2.ppf(alpha / 2, df)):
        if generalized_q(y, v, 0.0) <= target:
            bounds.append(0.0)
            continue
        upper = _upper(y, v)
        while generalized_q(y, v, upper) > target:
            upper *= 10.0
        bounds.append(float(optimize.brentq(lambda t: generalized_q(y, v, t) - target, 0.0, upper, xtol=1e-12)))
    return bounds[0], bounds[1]


def i2_from_tau2(tau2: float, v: np.ndarray) -> float:
    """τ² 를 전형적 사상 안 분산 s² 로 나눠 I² 로 옮긴다."""
    w = 1.0 / v
    s2 = (len(v) - 1) * np.sum(w) / (np.sum(w) ** 2 - np.sum(w ** 2))
    return float(tau2 / (tau2 + s2))


def random_effects(y: np.ndarray, se: np.ndarray, *, method: str = "REML", ci: str = "mhksj") -> dict:
    """logit 효과 크기와 SE 를 무작위효과로 통합해 평균·구간·예측구간·이질성을 돌려준다."""
    # 입력을 검사하고 방법에 따라 τ² 를 추정한다
    y, se = np.asarray(y, dtype=float), np.asarray(se, dtype=float)
    if len(y) != len(se) or not len(y) or not np.all(np.isfinite(y)) or not np.all(np.isfinite(se)) or np.any(se <= 0):
        raise ValueError("효과 크기와 표준오차가 유한하고 SE > 0 이어야 한다")
    if method not in ("REML", "DL") or ci not in ("mhksj", "hksj", "wald"):
        raise ValueError("통합 방법 또는 구간 방법이 잘못됐다")
    k, v = len(y), se ** 2
    out = {"k": k, "method": method, "ci_method": ci}
    if k == 1:
        return out | {"mu": float(y[0]), "se": float(se[0]), "ci_lo": np.nan, "ci_hi": np.nan, "pi_lo": np.nan,
                      "pi_hi": np.nan, "tau2": np.nan, "q": np.nan, "q_p": np.nan, "i2": np.nan, "i2_lo": np.nan,
                      "i2_hi": np.nan, "tau2_lo": np.nan, "tau2_hi": np.nan, "weights_re": np.array([1.0]),
                      "weights_fe": np.array([1.0])}
    tau2 = tau2_reml(y, v) if method == "REML" else tau2_dl(y, v)
    mu, w = _weighted_mean(y, v, tau2)
    se_plain = float(np.sqrt(1.0 / np.sum(w)))

    # 평균의 구간: 수정·원래 HKSJ 는 t(k−1), Wald 는 정규 분위
    if ci == "wald":
        se_mu, crit = se_plain, Z975
    else:
        scale = float(np.sum(w * (y - mu) ** 2) / (k - 1))
        se_mu = float(np.sqrt((max(1.0, scale) if ci == "mhksj" else scale) / np.sum(w)))
        crit = float(stats.t.ppf(0.975, k - 1))

    # 예측구간(k ≥ 3)과 Q·I²·Q-profile 구간
    if k >= 3:
        half = float(stats.t.ppf(0.975, k - 2)) * np.sqrt(tau2 + se_plain ** 2)
        pi_lo, pi_hi = mu - half, mu + half
    else:
        pi_lo = pi_hi = np.nan
    q = cochran_q(y, v)
    tau2_lo, tau2_hi = q_profile_tau2(y, v)
    return out | {"mu": mu, "se": se_mu, "ci_lo": mu - crit * se_mu, "ci_hi": mu + crit * se_mu,
                  "pi_lo": pi_lo, "pi_hi": pi_hi, "tau2": tau2, "q": q, "q_p": float(stats.chi2.sf(q, k - 1)),
                  "i2": max(0.0, (q - (k - 1)) / q) if q > 0 else 0.0,
                  "tau2_lo": tau2_lo, "tau2_hi": tau2_hi, "i2_lo": i2_from_tau2(tau2_lo, v),
                  "i2_hi": i2_from_tau2(tau2_hi, v), "weights_re": w / np.sum(w), "weights_fe": (1 / v) / np.sum(1 / v)}
