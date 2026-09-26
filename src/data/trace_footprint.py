"""사상 폴리곤이 격자에 남기는 자국: 폴리곤-칸 겹침 면적, 칸별 합집합 면적, 대표점 칸 (docs/q1/M4_protocol.md §2·§3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.data.coarse_grid import Blocks


@dataclass(frozen=True)
class Footprint:
    """겹침 쌍(폴리곤 번호·칸 번호·면적)과 칸별 침수 합집합 면적·칸 면적, 폴리곤별 대표점 칸(-1 은 격자 밖)."""

    obj: np.ndarray
    cell: np.ndarray
    area: np.ndarray
    flooded: np.ndarray
    cell_area: np.ndarray
    rep_cell: np.ndarray

    @property
    def n_obj(self) -> int:
        """폴리곤 수."""
        return len(self.rep_cell)

    @property
    def n_cells(self) -> int:
        """칸 수."""
        return len(self.cell_area)


def footprint(grid, traces) -> Footprint:
    """100 m 칸과 사상 폴리곤의 겹침을 한 번 계산한다 (겹친 폴리곤 면적은 칸 안에서 한 번만 센다)."""
    import shapely

    from src.data.validation._common import _overlaps

    # evaluate 와 같은 공통 함수로 겹침 쌍과 교차 조각을 구한다
    obj, cell, area, _, pieces = _overlaps(grid, traces)
    cell_area = grid.geometry.area.to_numpy()
    flooded = np.bincount(cell, weights=area, minlength=len(grid))

    # 조각이 둘 이상인 칸은 조각 합집합 면적으로 바꾼다 (evaluate 의 label_area 와 같은 규칙)
    order = np.argsort(cell, kind="stable")
    starts = np.flatnonzero(np.r_[True, np.diff(cell[order]) != 0]) if len(cell) else np.array([], int)
    for start, stop in zip(starts, np.r_[starts[1:], len(cell)]):
        if stop - start > 1:
            flooded[cell[order[start]]] = shapely.area(shapely.union_all(pieces[order[start:stop]]))
    flooded = np.minimum(flooded, cell_area)

    # 대표점이 든 칸이 여럿(경계)이면 번호가 가장 작은 칸을 쓴다
    points = traces.geometry.representative_point()
    hit = grid.sindex.query(points.array, predicate="intersects")
    rep = np.full(len(traces), np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(rep, hit[0], hit[1])
    rep[rep == np.iinfo(np.int64).max] = -1
    return Footprint(obj.astype(np.int64), cell.astype(np.int64), area, flooded, cell_area, rep)


def coarsen(fp: Footprint, blocks: Blocks) -> Footprint:
    """100 m 자국을 굵은 칸으로 합친다: 같은 폴리곤-굵은 칸 쌍의 겹침 면적과 칸별 합집합 면적을 더한다."""
    # 폴리곤·굵은 칸 쌍마다 겹침 면적을 더한다
    block = blocks.code[fp.cell]
    key, inverse = np.unique(fp.obj * blocks.n + block, return_inverse=True)
    area = np.bincount(np.asarray(inverse).ravel(), weights=fp.area, minlength=len(key))

    # 100 m 칸끼리는 겹치지 않으므로 합집합 면적도 더하면 된다
    flooded = np.bincount(blocks.code, weights=fp.flooded, minlength=blocks.n)
    rep = np.where(fp.rep_cell >= 0, blocks.code[np.maximum(fp.rep_cell, 0)], -1)
    return Footprint(key // blocks.n, key % blocks.n, area, np.minimum(flooded, blocks.area), blocks.area, rep)


def center_inside(traces, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """점 (x, y) 가 사상 폴리곤 어느 하나의 안(경계 제외)에 있는지."""
    import shapely

    # 폴리곤 공간 색인에 점을 질의해 안에 든 점을 표시한다
    tree = shapely.STRtree(traces.geometry.array)
    hit = tree.query(shapely.points(np.asarray(x, float), np.asarray(y, float)), predicate="within")
    inside = np.zeros(len(x), bool)
    inside[hit[0]] = True
    return inside
