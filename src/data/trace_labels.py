"""침수흔적과 격자의 겹침 면적으로 검증 라벨을 만든다."""


def label_grid(grid, traces, *, min_overlap: float = 0.10, mode: str = "union"):
    """겹침 합집합(또는 기존 합산) 면적 비율이 임계를 초과하는 격자를 표시한다."""
    # 공간 조인과 면적 배열 계산에 필요한 도구를 준비한다.
    import geopandas as gpd
    import numpy as np

    # 겹침 모드를 검증하고 교차 도형의 면적 비율을 격자별로 계산한다.
    if mode not in {"union", "sum"}:
        raise ValueError(f"잘못된 겹침 모드: {mode}")
    areas = np.zeros(len(grid))
    cells = grid[["geometry"]].reset_index(drop=True)
    polygons = traces[["geometry"]].reset_index(drop=True)
    joined = gpd.sjoin(
        cells.reset_index(names="_row"), polygons, predicate="intersects", how="inner"
    )
    for row, group in joined.groupby("_row"):
        cell = cells.geometry.iloc[row]
        intersections = polygons.geometry.iloc[group["index_right"].to_numpy()].intersection(cell)
        overlap = intersections.union_all().area if mode == "union" else intersections.area.sum()
        areas[row] = min(float(overlap) / cell.area, 1.0)
    return areas > min_overlap, areas
