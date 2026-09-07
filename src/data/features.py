"""H04 격자 피처 (ANALYSIS_PLAN §1~2, RESEARCH_HARNESS §6).

SGIS 100m 격자가 EPSG:5179 의 100m 격자망에 정확히 정렬돼 있으므로(`h03_grid_base` 검증),
모든 변수를 그 격자망 위의 2차원 배열로 계산한 뒤 grid_id 의 (row, col) 로 읽는다.
폴리곤 변수(토지피복·침수예상도)는 10m 로 래스터화한 뒤 100m 블록 평균 = 면적 비율이다.

여기 있는 함수는 전부 순수 계산이다. 파일 경로·통과 판정은 `src/stages/h04_features.py` 가 맡는다.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio import Affine
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.merge import merge as rio_merge
from rasterio.warp import reproject
from scipy import ndimage
from scipy.spatial import cKDTree

# 토지피복 중분류 코드 (환경부 EGIS). 100번대 = 시가화·건조지역 → 불투수면 proxy.
IMPERVIOUS_CODES = {"110", "120", "130", "140", "150", "160"}
INLAND_WATER_CODE = "710"
SEA_CODE = "720"


@dataclass(frozen=True)
class Lattice:
    """분석격자와 정렬된 100m 래스터 격자망."""

    transform: Affine
    shape: tuple[int, int]
    res: float

    @property
    def x0(self) -> float:
        return self.transform.c

    @property
    def y_top(self) -> float:
        return self.transform.f

    def rowcol(self, minx: np.ndarray, maxy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        col = np.round((minx - self.x0) / self.res).astype(int)
        row = np.round((self.y_top - maxy) / self.res).astype(int)
        return row, col

    def centers(self) -> tuple[np.ndarray, np.ndarray]:
        """(row, col) 배열 모양의 셀 중심 x, y."""
        rows, cols = np.indices(self.shape)
        x = self.x0 + (cols + 0.5) * self.res
        y = self.y_top - (rows + 0.5) * self.res
        return x, y

    def refined(self, factor: int) -> "Lattice":
        return Lattice(
            Affine(self.res / factor, 0, self.x0, 0, -self.res / factor, self.y_top),
            (self.shape[0] * factor, self.shape[1] * factor),
            self.res / factor,
        )


def lattice_from_grid(grid: gpd.GeoDataFrame, res: float = 100.0) -> tuple[Lattice, np.ndarray, np.ndarray]:
    """격자 폴리곤에서 격자망을 만들고 각 격자의 (row, col) 을 돌려준다. 정렬이 어긋나면 ValueError."""
    b = grid.geometry.bounds
    if not (np.allclose(b.minx % res, 0) and np.allclose(b.miny % res, 0)):
        raise ValueError(f"격자가 {res}m 격자망에 정렬돼 있지 않다")
    x0, y_top = float(b.minx.min()), float(b.maxy.max())
    shape = (int(round((y_top - b.miny.min()) / res)), int(round((b.maxx.max() - x0) / res)))
    lat = Lattice(Affine(res, 0, x0, 0, -res, y_top), shape, res)
    row, col = lat.rowcol(b.minx.to_numpy(), b.maxy.to_numpy())
    return lat, row, col


# ── DEM ────────────────────────────────────────────────────────────────────
def dem_to_lattice(dem_paths: Iterable, lat: Lattice, nodata: float = -9999.0) -> tuple[np.ndarray, dict[str, Any]]:
    """DEM 도엽을 mosaic 한 뒤 격자망으로 bilinear resample 한다. NoData 는 NaN."""
    import rasterio

    srcs = [rasterio.open(p) for p in dem_paths]
    try:
        mosaic, src_tr = rio_merge(srcs, nodata=nodata)
        crs = srcs[0].crs
        src_res = srcs[0].res[0]
    finally:
        for s in srcs:
            s.close()
    out = np.full(lat.shape, np.nan, dtype="float32")
    reproject(
        mosaic[0], out,
        src_transform=src_tr, src_crs=crs, src_nodata=nodata,
        dst_transform=lat.transform, dst_crs=crs, dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    meta = {
        "dem_source_res_m": float(src_res),
        "dem_resampling": "bilinear",
        "dem_mosaic_shape": [int(v) for v in mosaic.shape[1:]],
        "dem_nodata_cells": int(np.isnan(out).sum()),
    }
    return out, meta


def slope_deg(elev: np.ndarray, res: float) -> np.ndarray:
    dy, dx = np.gradient(elev, res)
    return np.degrees(np.arctan(np.hypot(dx, dy)))


def relative_elevation(elev: np.ndarray, res: float, radius_m: float) -> np.ndarray:
    """격자 표고 − 반경 radius_m 초점평균 (NaN 제외 평균). 음수 = 주변보다 낮은 저지대."""
    size = 2 * int(round(radius_m / res)) + 1
    valid = ~np.isnan(elev)
    filled = np.where(valid, elev, 0.0)
    total = ndimage.uniform_filter(filled, size=size, mode="constant")
    count = ndimage.uniform_filter(valid.astype(float), size=size, mode="constant")
    with np.errstate(invalid="ignore", divide="ignore"):
        focal = np.where(count > 0, total / count, np.nan)
    return elev - focal


_D8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def fill_sinks(elev: np.ndarray) -> np.ndarray:
    """Priority-flood (Barnes et al. 2014) 로 싱크를 채운다. NaN 은 경계(바다·자료 밖)로 본다."""
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
    while heap:
        z, r, c = heapq.heappop(heap)
        for dr, dc in _D8:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and not closed[nr, nc]:
                closed[nr, nc] = True
                out[nr, nc] = max(float(elev[nr, nc]), z)
                heapq.heappush(heap, (out[nr, nc], nr, nc))
    return out


def flow_accumulation(filled: np.ndarray, res: float) -> np.ndarray:
    """D8 (최급경사) 유량누적 — 각 셀 자신을 포함한 상류 셀 수. NaN 셀은 흐름이 끊긴다."""
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
        idx = (rows + dr) * w + (cols + dc)
        recv = np.where(better, idx, recv)
    acc = np.ones(h * w)
    acc[~np.isfinite(z.ravel())] = 0
    order = np.argsort(-z.ravel(), kind="stable")
    recv_flat = recv.ravel()
    for i in order:
        j = recv_flat[i]
        if j >= 0:
            acc[j] += acc[i]
    acc = acc.reshape(h, w)
    acc[np.isnan(filled)] = np.nan
    return acc


def twi(elev: np.ndarray, res: float, tanb_floor: float = 0.001) -> tuple[np.ndarray, np.ndarray]:
    """TWI = ln(a / tanβ). a = 단위 등고선 길이당 상류 면적 (상류 셀 수 × res). 채운 DEM 의 경사 사용."""
    filled = fill_sinks(elev)
    acc = flow_accumulation(filled, res)
    dy, dx = np.gradient(filled, res)
    tanb = np.maximum(np.hypot(dx, dy), tanb_floor)
    a = acc * res
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.log(a / tanb), acc


# ── 폴리곤 → 면적 비율 ────────────────────────────────────────────────────────
def _block_mean(fine: np.ndarray, factor: int) -> np.ndarray:
    h, w = fine.shape
    return fine.reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))


def area_fraction(geoms: Iterable, lat: Lattice, sub: int = 10) -> np.ndarray:
    """폴리곤이 각 100m 셀에서 차지하는 면적 비율 (10m 래스터화 → 블록 평균)."""
    fine = lat.refined(sub)
    geoms = list(geoms)
    if not geoms:
        return np.zeros(lat.shape, dtype="float32")
    mask = rasterize(
        ((g, 1) for g in geoms), out_shape=fine.shape, transform=fine.transform, fill=0, dtype="uint8"
    )
    return _block_mean(mask.astype("float32"), sub)


def value_fraction_and_mean(
    gdf: gpd.GeoDataFrame, value_col: str, lat: Lattice, sub: int = 10
) -> tuple[np.ndarray, np.ndarray]:
    """겹치는 폴리곤은 값이 큰 쪽이 이기도록 오름차순으로 굽는다.

    (셀 안 폴리곤 면적 비율, 면적가중 평균값) 을 돌려준다. 평균은 폴리곤이 없는 부분을 0 으로 친다.
    """
    fine = lat.refined(sub)
    if gdf.empty:
        z = np.zeros(lat.shape, dtype="float32")
        return z, z.copy()
    ordered = gdf.sort_values(value_col)
    burned = rasterize(
        zip(ordered.geometry, ordered[value_col].astype("float32")),
        out_shape=fine.shape, transform=fine.transform, fill=0.0, dtype="float32",
    )
    return _block_mean((burned > 0).astype("float32"), sub), _block_mean(burned, sub)


def distance_to(geoms: Iterable, lat: Lattice, sub: int = 10) -> np.ndarray:
    """각 100m 셀 중심에서 가장 가까운 폴리곤까지 거리(m). 10m 래스터 위 EDT."""
    fine = lat.refined(sub)
    geoms = list(geoms)
    if not geoms:
        return np.full(lat.shape, np.nan, dtype="float32")
    mask = rasterize(
        ((g, 1) for g in geoms), out_shape=fine.shape, transform=fine.transform, fill=0, dtype="uint8"
    )
    dist = ndimage.distance_transform_edt(mask == 0) * fine.res
    half = sub // 2
    return dist[half::sub, half::sub].astype("float32")


def nearest_point_distance(lat: Lattice, points: gpd.GeoDataFrame) -> np.ndarray:
    x, y = lat.centers()
    tree = cKDTree(np.column_stack([points.geometry.x, points.geometry.y]))
    d, _ = tree.query(np.column_stack([x.ravel(), y.ravel()]))
    return d.reshape(lat.shape).astype("float32")


def sgis_wide(stats: pd.DataFrame, year: int, variables: dict[str, str]) -> pd.DataFrame:
    """long SGIS 격자통계 → grid_id 별 wide. 발행되지 않은 격자는 행이 없다 (= 0 이 아니라 '미발행')."""
    sub = stats[(stats["year"] == year) & stats["variable"].isin(variables)]
    wide = sub.pivot_table(index="spatial_id", columns="variable", values="value", aggfunc="first")
    wide = wide.rename(columns=variables).reset_index().rename(columns={"spatial_id": "grid_id"})
    wide.columns.name = None
    return wide.reindex(columns=["grid_id", *variables.values()])
