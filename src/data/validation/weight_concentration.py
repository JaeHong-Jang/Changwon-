"""객체 가중치 집중: 생존 객체의 유효 수·상위 몫·묶음 몫과 크기 가중 항의 공분산 형태 (docs/q1/M4S_protocol.md §5.2)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def covariance_form(W: np.ndarray, A: np.ndarray, At: np.ndarray) -> dict[str, Any]:
    """S = {W>0, Ã 유한} 위에서 크기 가중 항 = ρ(w̃, A) · sd(A) · √(n_S / n_eff,S − 1) 의 각 인수를 구한다."""
    # 생존 객체와 정규화 가중치를 만든다
    W, A, At = (np.asarray(v, dtype=float) for v in (W, A, At))
    S = (W > 0) & np.isfinite(At) & np.isfinite(A)
    n = int(S.sum())
    if n == 0:
        return {"n_S": 0, "n_eff_S": np.nan, "sd_A": np.nan, "rho_wA": np.nan, "size_term_direct": np.nan,
                "size_term_product": np.nan, "concentration_factor": np.nan}
    w = W[S] / W[S].sum()
    a = A[S]
    n_eff = float(1.0 / np.sum(w ** 2))

    # 직접 형태(Σ w̃A − Ā)와 곱 형태(ρ · sd · √(n/n_eff − 1))를 모두 계산한다
    direct = float(np.dot(w, a) - a.mean())
    sd_a, sd_w = float(a.std()), float(w.std())
    rho = float(np.mean((w - w.mean()) * (a - a.mean())) / (sd_w * sd_a)) if sd_a > 0 and sd_w > 0 else np.nan
    factor = math.sqrt(max(n / n_eff - 1.0, 0.0))
    product = rho * sd_a * factor if np.isfinite(rho) else 0.0
    return {"n_S": n, "n_eff_S": n_eff, "sd_A": sd_a, "rho_wA": rho, "size_term_direct": direct,
            "size_term_product": float(product), "concentration_factor": factor}


def top_share(W: np.ndarray, q: float = 0.1, extra_mass: float = 0.0) -> float:
    """가중치가 큰 순서로 ⌈q × 객체 수⌉ 개가 가진 몫 (분모는 전체 가중치 + 할당 안 된 질량)."""
    # 내림차순 정렬 후 앞쪽 합을 전체로 나눈다
    W = np.sort(np.asarray(W, dtype=float))[::-1]
    total = W.sum() + extra_mass
    if not len(W) or total <= 0:
        return np.nan
    return float(W[: math.ceil(q * len(W))].sum() / total)


def group_share(W: np.ndarray, groups: np.ndarray, extra_mass: float = 0.0) -> float:
    """묶음(사상 등)별 가중치 몫의 최댓값."""
    # 묶음마다 가중치를 더해 가장 큰 몫을 고른다
    W = np.asarray(W, dtype=float)
    total = W.sum() + extra_mass
    if not len(W) or total <= 0:
        return np.nan
    _, code = np.unique(np.asarray(groups), return_inverse=True)
    return float(np.bincount(np.asarray(code).ravel(), weights=W).max() / total)
