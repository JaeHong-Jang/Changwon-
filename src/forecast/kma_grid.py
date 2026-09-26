"""기상청 LCC 격자 좌표와 격자 응답을 해석한다."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


def lonlat_to_grid(lon: float, lat: float) -> tuple[int, int]:
    """경위도를 1부터 시작하는 기상청 5 km LCC 격자로 바꾼다."""
    # 기상청 동네예보 LCC 상수로 원뿔 투영 계수를 계산한다.
    re, grid, slat1, slat2, olon, olat, xo, yo = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43.0, 136.0
    rad = math.pi / 180.0
    sn = math.log(math.cos(slat1 * rad) / math.cos(slat2 * rad)) / math.log(
        math.tan(math.pi / 4 + slat2 * rad / 2) / math.tan(math.pi / 4 + slat1 * rad / 2))
    sf = math.tan(math.pi / 4 + slat1 * rad / 2) ** sn * math.cos(slat1 * rad) / sn
    ro = re / grid * sf / math.tan(math.pi / 4 + olat * rad / 2) ** sn

    # 경도 차이를 정규화하고 투영한 뒤 기상청 방식으로 반올림한다.
    ra = re / grid * sf / math.tan(math.pi / 4 + lat * rad / 2) ** sn
    theta = ((lon - olon + 180) % 360 - 180) * rad * sn
    return int(math.floor(ra * math.sin(theta) + xo + 0.5)), int(math.floor(ro - ra * math.cos(theta) + yo + 0.5))


def parse_grid(raw: bytes) -> np.ndarray:
    """쉼표 구분 격자를 남쪽부터 북쪽까지 (253, 149) 배열로 읽는다."""
    # 마지막 쉼표 뒤의 빈 토큰은 버리고 격자 크기를 검사한다.
    tokens = [part.strip() for part in raw.decode('ascii').split(',') if part.strip()]
    if len(tokens) != 253 * 149:
        raise ValueError(f'기상청 격자 값 수가 {len(tokens)}개입니다')

    # 결측 코드만 NaN 으로 바꾸고 원본 행 순서를 유지한다.
    values = np.array([float(part) for part in tokens], dtype=float).reshape(253, 149)
    values[values == -99.0] = np.nan
    return values


def value_at(grid: np.ndarray, nx: int, ny: int) -> float:
    """1부터 시작하는 기상청 좌표의 값을 반환한다."""
    # 남쪽 첫 행과 서쪽 첫 열을 각각 좌표 1에 맞춘다.
    if not (1 <= nx <= 149 and 1 <= ny <= 253):
        raise IndexError((nx, ny))
    return float(grid[ny - 1, nx - 1])


def changwon_cells(grid_gpkg: str | Path = 'data/processed/layers/layer1_flood.gpkg') -> tuple[pd.DataFrame, pd.DataFrame]:
    """창원 분석 격자 중심을 기상청 격자에 대응시키고 개수를 센다."""
    # 원본 CRS 가 지정된 분석 격자의 ID 와 중심점을 읽는다.
    import geopandas as gpd
    layer = gpd.read_file(grid_gpkg, layer='layer1_flood', columns=['grid_id', 'geometry'])
    if layer.crs is None:
        raise ValueError('분석 격자의 CRS 가 없습니다')
    centers = gpd.GeoSeries(layer.geometry.centroid, crs=layer.crs).to_crs(4326)

    # 변환 좌표를 격자별로 집계하고 역방향 매핑을 만든다.
    xy = [lonlat_to_grid(point.x, point.y) for point in centers]
    mapping = pd.DataFrame({'grid_id': layer.grid_id.astype(str).to_numpy(),
                            'nx': [item[0] for item in xy], 'ny': [item[1] for item in xy]})
    cells = mapping.groupby(['nx', 'ny'], as_index=False).size().rename(columns={'size': 'n_grid_cells'})
    return cells.sort_values(['nx', 'ny']).reset_index(drop=True), mapping
