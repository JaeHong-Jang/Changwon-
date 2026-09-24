"""검증 지표에서 공유하는 상수와 공간·통계 보조 함수."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import geopandas as gpd


FRACTIONS = (0.05, 0.1, 0.2, 0.3, 0.5)
COLUMNS = ["score", "unit", "stratum", "storm", "metric", "value", "ci_lo", "ci_hi", "n_units"]


def _mid_cdf(positive: np.ndarray, background: np.ndarray) -> np.ndarray:
    """배경 점수의 동점을 절반으로 센 경험 누적분포를 반환한다."""
    # 배경 점수를 정렬한 뒤 양성 점수의 동점 중간 순위를 계산한다.
    bg = np.sort(np.asarray(background, dtype=float))
    if not len(bg):
        return np.full(len(positive), np.nan)
    pos = np.asarray(positive, dtype=float)
    left = np.searchsorted(bg, pos, side="left")
    right = np.searchsorted(bg, pos, side="right")
    return (left + right) / (2 * len(bg))



def _interval(draws: np.ndarray) -> tuple[float, float]:
    """유한한 재표본의 백분위 95% 구간을 구한다."""
    # 유한한 재표본만 골라 백분위 구간을 계산한다.
    finite = np.asarray(draws)[np.isfinite(draws)]
    if not len(finite):
        return np.nan, np.nan
    return tuple(float(v) for v in np.percentile(finite, [2.5, 97.5]))



def _overlaps(grid: gpd.GeoDataFrame, traces: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """폴리곤·격자 교차면적과 대표점이 속한 격자 번호를 한 번 계산한다."""
    # 공간 연산에 필요한 라이브러리를 불러온다.
    import shapely

    # 같은 투영 좌표계인지 확인한 뒤 교차 면적을 계산한다.
    if grid.crs is None or traces.crs is None or grid.crs != traces.crs or grid.crs.is_geographic:
        raise ValueError("격자와 흔적은 같은 투영 좌표계여야 한다")
    if len(traces) == 0 or len(grid) == 0:
        return (np.array([], int), np.array([], int), np.array([], float),
                np.full(len(traces), -1, int), np.array([], object))
    pairs = grid.sindex.query(traces.geometry.array, predicate="intersects")
    obj, cell = pairs[0], pairs[1]
    intersection = shapely.intersection(traces.geometry.array[obj], grid.geometry.array[cell])
    area = shapely.area(intersection)
    positive = area > 0
    obj, cell, area, intersection = obj[positive], cell[positive], area[positive], intersection[positive]
    points = traces.geometry.representative_point()
    point_pairs = grid.sindex.query(points.array, predicate="intersects")
    representative = np.full(len(traces), -1, dtype=int)
    representative[point_pairs[0]] = point_pairs[1]
    return obj.astype(int), cell.astype(int), area.astype(float), representative, intersection
