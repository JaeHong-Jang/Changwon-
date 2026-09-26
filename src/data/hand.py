"""HAND(배수로 위 높이): 채운 DEM 의 D8 흐름을 따라 처음 만나는 하천 칸과의 표고차."""

from __future__ import annotations

import heapq
from typing import Iterable

import numpy as np
from rasterio.features import rasterize

from src.data.features import _D8, Lattice, fill_sinks


def fill_sinks_epsilon(elev: np.ndarray) -> np.ndarray:
    """Priority-Flood+ε (Barnes et al. 2014): 채운 칸마다 가장 작은 증분을 더해 평탄 칸에도 내리막 흐름을 만든다."""
    # 격자 끝과 결측에 닿은 칸을 시작점으로 둔다 (fill_sinks 와 같은 시작 규칙)
    h, w = elev.shape
    out = np.full_like(elev, np.nan, dtype="float64")
    nan_mask = np.isnan(elev)
    closed = nan_mask.copy()
    heap: list[tuple[float, int, int]] = []
    for r in range(h):
        for c in range(w):
            if nan_mask[r, c]:
                continue
            on_edge = r in (0, h - 1) or c in (0, w - 1)
            touches_nan = any(
                nan_mask[r + dr, c + dc] for dr, dc in _D8 if 0 <= r + dr < h and 0 <= c + dc < w
            )
            if on_edge or touches_nan:
                heapq.heappush(heap, (float(elev[r, c]), r, c))
                out[r, c] = elev[r, c]
                closed[r, c] = True

    # 이웃은 max(원래 표고, 현재 표고의 다음 부동소수) 로 채워 항상 현재 칸보다 높게 둔다
    while heap:
        z, r, c = heapq.heappop(heap)
        for dr, dc in _D8:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and not closed[nr, nc]:
                closed[nr, nc] = True
                out[nr, nc] = max(float(elev[nr, nc]), float(np.nextafter(z, np.inf)))
                heapq.heappush(heap, (out[nr, nc], nr, nc))
    return out


def d8_receivers(filled: np.ndarray, res: float) -> np.ndarray:
    """각 칸의 D8 최급경사 하류 칸 평면 번호 (`flow_accumulation` 과 같은 규칙, 없으면 -1)."""
    # 결측을 무한대로 두고 8방향 중 낙차/거리가 가장 큰 양수 방향을 고른다
    h, w = filled.shape
    z = np.where(np.isnan(filled), np.inf, filled)
    recv = np.full((h, w), -1, dtype=np.int64)
    best = np.zeros((h, w))
    rows = np.arange(h)[:, None]
    cols = np.arange(w)[None, :]
    for dr, dc in _D8:
        dist = res * float(np.hypot(dr, dc))
        shifted = np.full((h, w), np.inf)
        rs = slice(max(dr, 0), h + min(dr, 0))
        cs = slice(max(dc, 0), w + min(dc, 0))
        rt = slice(max(-dr, 0), h + min(-dr, 0))
        ct = slice(max(-dc, 0), w + min(-dc, 0))
        shifted[rt, ct] = z[rs, cs]
        drop = (z - shifted) / dist
        better = drop > best
        best = np.where(better, drop, best)
        recv = np.where(better, (rows + dr) * w + (cols + dc), recv)
    return recv.ravel()


def accumulation_from_receivers(recv: np.ndarray, filled: np.ndarray) -> np.ndarray:
    """하류 번호로 상류 칸 수를 센다 (규칙 일치 확인용)."""
    # 높은 칸부터 하류로 자기 누적을 넘긴다
    z = np.where(np.isnan(filled), np.inf, filled).ravel()
    acc = np.ones(z.size)
    acc[~np.isfinite(z)] = 0
    for i in np.argsort(-z, kind="stable"):
        if recv[i] >= 0:
            acc[recv[i]] += acc[i]
    acc = acc.reshape(filled.shape)
    acc[np.isnan(filled)] = np.nan
    return acc


def stream_mask_from_lines(lines: Iterable, lat: Lattice) -> np.ndarray:
    """하천 중심선이 지나는 격자망 칸 (all_touched 래스터화)."""
    # 선이 닿은 칸을 모두 하천으로 굽는다
    lines = list(lines)
    if not lines:
        return np.zeros(lat.shape, bool)
    burned = rasterize(((g, 1) for g in lines), out_shape=lat.shape, transform=lat.transform,
                       fill=0, all_touched=True, dtype="uint8")
    return burned.astype(bool)


def stream_mask_from_accumulation(elev: np.ndarray, res: float, min_cells: float) -> np.ndarray:
    """ε 채움 DEM 의 D8 유량누적이 min_cells 이상인 칸."""
    # 평탄 칸도 흐르게 한 방향으로 상류 칸 수를 세어 임계로 자른다
    routed = fill_sinks_epsilon(elev)
    acc = accumulation_from_receivers(d8_receivers(routed, res), routed)
    return np.nan_to_num(acc, nan=0.0) >= min_cells


def hand(elev: np.ndarray, streams: np.ndarray, res: float) -> tuple[np.ndarray, dict]:
    """HAND 와 요약: 방향은 ε 채움 DEM, 높이는 채운 DEM. 하천을 못 만난 흐름은 흐름 끝 칸을 기준으로 쓴다."""
    # 평탄 칸도 흐르도록 ε 채움으로 D8 하류 칸을 구하고, 높이는 ε 없는 채움 표고를 쓴다
    routed = fill_sinks_epsilon(elev)
    recv = d8_receivers(routed, res)
    z = fill_sinks(elev).ravel()
    order_z = routed.ravel()
    finite = np.isfinite(z)

    # 낮은 칸부터 배수 기준 표고를 정한다: 하천 칸·끝 칸은 자기 표고, 나머지는 하류 칸의 기준을 물려받는다
    base = np.full(z.size, np.nan)
    ends_at = np.zeros(z.size, np.int8)  # 0 결측, 1 하천, 2 흐름 끝
    is_stream = streams.ravel().astype(bool)
    for i in np.argsort(np.where(finite, order_z, np.inf), kind="stable"):
        if not finite[i]:
            break
        j = recv[i]
        if is_stream[i]:
            base[i], ends_at[i] = z[i], 1
        elif j < 0:
            base[i], ends_at[i] = z[i], 2
        else:
            base[i], ends_at[i] = base[j], ends_at[j]

    # 음수를 0 으로 자르고 배수 기준의 종류를 센다
    out = np.maximum(z - base, 0.0).reshape(elev.shape)
    out[~finite.reshape(elev.shape)] = np.nan
    summary = {"n_cells": int(finite.sum()), "n_stream_cells": int((is_stream & finite).sum()),
               "n_reach_stream": int((ends_at == 1).sum()), "n_reach_flow_end": int((ends_at == 2).sum()),
               "n_flow_end_cells": int(((recv < 0) & finite & ~is_stream).sum())}
    return out, summary
