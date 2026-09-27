"""객체 탐지력 μ_k 와 칸 점수 조립: 겹침 면적이 가장 큰 객체의 μ 를 배경 점수에 더한다 (docs/q1/M4S_protocol.md §1.5)."""

from __future__ import annotations

import numpy as np

from src.data.trace_footprint import Footprint


def detectability(rng: np.random.Generator, zeta: np.ndarray, event: np.ndarray, n_events: int,
                  mu0: float, beta: float, tau: float, upsilon: float) -> np.ndarray:
    """μ_k = μ0 + β ζ_k + τ ε_k + υ η_e(k), ε·η 는 독립 N(0,1)."""
    # 객체 잡음과 사상 효과를 차례로 뽑는다
    eps = rng.standard_normal(len(zeta))
    eta = rng.standard_normal(n_events)
    return mu0 + beta * np.asarray(zeta, float) + tau * eps + upsilon * eta[np.asarray(event, int)]


def dominant_object(fp: Footprint) -> np.ndarray:
    """칸마다 겹침 면적이 가장 큰 객체 번호 (동점은 번호가 작은 객체, 겹침 없으면 −1)."""
    # 칸 → 겹침 면적 내림차순 → 객체 번호 순으로 정렬해 칸마다 첫 쌍을 고른다
    owner = np.full(fp.n_cells, -1, dtype=np.int64)
    if not len(fp.cell):
        return owner
    order = np.lexsort((fp.obj, -fp.area, fp.cell))
    first = order[np.r_[True, np.diff(fp.cell[order]) != 0]]
    owner[fp.cell[first]] = fp.obj[first]
    return owner


def assemble(z: np.ndarray, fp: Footprint, mu: np.ndarray) -> np.ndarray:
    """s_i = z_i + μ_{k(i)} (겹친 칸), 겹침 없는 칸은 z_i."""
    # 칸 주인 객체의 탐지력을 더한다
    owner = dominant_object(fp)
    return np.asarray(z, float) + np.where(owner >= 0, np.asarray(mu, float)[np.maximum(owner, 0)], 0.0)
