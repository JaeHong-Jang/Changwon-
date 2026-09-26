"""로그정규 크기의 지수 기울임으로 얻는 모집단 격자–객체 AUC 차이 Δ* 와 가중치 집중 기준값 (docs/q1/M4S_protocol.md §5.3)."""

from __future__ import annotations

import numpy as np
from scipy.stats import norm


def tilted_gap(sigma: float, beta: float, mu0: float, tau: float) -> float:
    """Δ* = Φ((μ0 + βσ)/D) − Φ(μ0/D), D = √(2 + β² + τ²): 면적가중 격자 AUC − 객체 AUC (n → ∞)."""
    # 기울인 평균과 원래 평균의 객체 값 차이
    d = np.sqrt(2.0 + beta ** 2 + tau ** 2)
    return float(norm.cdf((mu0 + beta * sigma) / d) - norm.cdf(mu0 / d))


def object_auc_limit(beta: float, mu0: float, tau: float) -> float:
    """모집단 객체 AUC Φ(μ0/D)."""
    return float(norm.cdf(mu0 / np.sqrt(2.0 + beta ** 2 + tau ** 2)))


def lognormal_top_share(sigma: float, q: float = 0.1) -> float:
    """면적 가중에서 상위 q 객체가 가진 몫 1 − Φ(Φ⁻¹(1 − q) − σ)."""
    return float(1.0 - norm.cdf(norm.ppf(1.0 - q) - sigma))


def lognormal_neff_ratio(sigma: float) -> float:
    """면적 가중에서 n_eff / n 의 극한 e^(−σ²)."""
    return float(np.exp(-sigma ** 2))
