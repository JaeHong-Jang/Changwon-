"""가상 경관: 100 m 칸 정사각 격자와 공간 자기상관이 있는 표준화 배경 점수 (docs/q1/M4S_protocol.md §1.1)."""

from __future__ import annotations

import numpy as np

ORIGIN = (1_000_000.0, 1_700_000.0)
N_SIDE = 200
RES = 100.0
SMOOTH_CELLS = 2.0


def lattice(n_side: int = N_SIDE, origin: tuple[float, float] = ORIGIN, res: float = RES):
    """좌하단이 origin 인 n_side × n_side 개 칸 (행 우선, 아래 행부터; 칸 번호 = 행 × n_side + 열)."""
    import geopandas as gpd
    import shapely

    # 칸 좌하단 좌표를 행 우선으로 펴서 정사각 폴리곤을 만든다
    x, y = np.meshgrid(origin[0] + res * np.arange(n_side), origin[1] + res * np.arange(n_side))
    x, y = x.ravel(), y.ravel()
    return gpd.GeoDataFrame({"grid_id": np.arange(n_side * n_side)}, geometry=shapely.box(x, y, x + res, y + res),
                            crs="EPSG:5179")


def bounds(n_side: int = N_SIDE, origin: tuple[float, float] = ORIGIN, res: float = RES) -> tuple[float, float, float, float]:
    """격자 영역 (xmin, ymin, xmax, ymax)."""
    return origin[0], origin[1], origin[0] + n_side * res, origin[1] + n_side * res


def background(rng: np.random.Generator, n_side: int = N_SIDE, smooth: float = SMOOTH_CELLS) -> np.ndarray:
    """독립 N(0,1) 을 가우스 평활(주기 경계)한 뒤 표본 평균 0·표준편차 1 로 맞춘 칸 점수 (격자 순서)."""
    from scipy.ndimage import gaussian_filter

    # 백색 잡음을 평활하고 이 복제 안에서 표준화한다
    field = gaussian_filter(rng.standard_normal((n_side, n_side)), sigma=smooth, mode="wrap").ravel()
    return (field - field.mean()) / field.std()
