"""100 m 분석 격자를 EPSG:5179 절대좌표에 정렬한 굵은 격자로 묶는다 (docs/q1/M4_protocol.md §3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BASE_RES = 100.0


@dataclass(frozen=True)
class Blocks:
    """100 m 칸마다 굵은 칸 번호, 굵은 칸마다 면적·중심점."""

    size: float
    code: np.ndarray
    area: np.ndarray
    x: np.ndarray
    y: np.ndarray

    @property
    def n(self) -> int:
        """굵은 칸 수."""
        return len(self.area)


def make_blocks(grid, size: float) -> Blocks:
    """격자 폴리곤 좌하단 좌표의 floor(·/size) 로 굵은 칸을 만들고 면적 합·중심점 평균을 모은다."""
    # 100 m 정렬과 크기를 확인하고 좌하단 좌표를 굵은 칸 열쇠로 바꾼다
    b = grid.geometry.bounds
    if not (np.allclose(b.minx % BASE_RES, 0) and np.allclose(b.miny % BASE_RES, 0)):
        raise ValueError("격자가 100 m 격자망에 정렬돼 있지 않다")
    if size < BASE_RES or size % BASE_RES:
        raise ValueError(f"굵은 칸 크기는 100 m 의 배수여야 한다: {size}")
    ix = np.floor(b.minx.to_numpy() / size + 1e-9).astype(np.int64)
    iy = np.floor(b.miny.to_numpy() / size + 1e-9).astype(np.int64)
    _, code = np.unique(np.column_stack([iy, ix]), axis=0, return_inverse=True)
    code = np.asarray(code).ravel()

    # 구성 칸 면적을 더하고 같은 크기 정사각형 합집합의 무게중심(면적가중 중심점 평균)을 구한다
    cell_area = grid.geometry.area.to_numpy()
    centers = grid.geometry.centroid
    n = int(code.max()) + 1 if len(code) else 0
    area = np.bincount(code, weights=cell_area, minlength=n)
    x = np.bincount(code, weights=cell_area * centers.x.to_numpy(), minlength=n) / area
    y = np.bincount(code, weights=cell_area * centers.y.to_numpy(), minlength=n) / area
    return Blocks(float(size), code, area, x, y)


def block_mean(values: np.ndarray, blocks: Blocks) -> np.ndarray:
    """구성 100 m 칸 값의 결측 제외 산술평균 (모두 결측이면 NaN)."""
    # 유한한 값만 더하고 개수로 나눈다
    v = np.asarray(values, dtype=float)
    ok = np.isfinite(v)
    total = np.bincount(blocks.code[ok], weights=v[ok], minlength=blocks.n)
    count = np.bincount(blocks.code[ok], minlength=blocks.n)
    return np.divide(total, count, out=np.full(blocks.n, np.nan), where=count > 0)


def block_any(mask: np.ndarray, blocks: Blocks) -> np.ndarray:
    """구성 100 m 칸 중 하나라도 참이면 참."""
    return np.bincount(blocks.code, weights=np.asarray(mask, dtype=bool), minlength=blocks.n) > 0
