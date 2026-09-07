"""침수흔적도 로더 — Layer 1 의 검증 라벨 (2026-09-14 정보공개 회신분).

**예상도는 입력, 흔적도는 검증**이다 (ANALYSIS_PLAN §2-3). 이 모듈이 읽은 자료는
`h04_grid_features` 의 입력이 아니며 Layer 1 산출 뒤 평가에만 쓴다.

회신 파일의 형식을 아직 모르므로 벡터 형식(SHP·GPKG·GeoJSON)을 모두 받아들이고,
그림 형식(PDF·csd)이면 무엇을 해야 하는지 알려주며 멈춘다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

VECTOR_SUFFIXES = {".shp", ".gpkg", ".geojson", ".json", ".gml", ".kml"}
IMAGE_SUFFIXES = {".pdf", ".csd", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dwg", ".dxf"}

# 회신 파일에서 사상 일자로 쓸 만한 컬럼 이름 후보 (먼저 맞는 것을 쓴다).
DATE_COLUMN_CANDIDATES = ("침수일자", "발생일자", "사상일자", "피해일자", "일자", "OCCUR_DE", "FLUD_DE", "date")
CAUSE_COLUMN_CANDIDATES = ("침수원인", "원인", "재해원인", "CAUSE", "cause")


class FloodTraceUnavailable(RuntimeError):
    """읽을 수 있는 벡터 침수흔적 자료가 없다. 사유와 다음 행동을 메시지에 담는다."""


def find_files(root: Path) -> tuple[list[Path], list[Path]]:
    """(벡터 파일, 그림 파일) 로 나눠 돌려준다."""
    if not root.exists():
        return [], []
    files = [p for p in root.rglob("*") if p.is_file()]
    vectors = sorted(p for p in files if p.suffix.lower() in VECTOR_SUFFIXES)
    images = sorted(p for p in files if p.suffix.lower() in IMAGE_SUFFIXES)
    return vectors, images


def load(paths: Iterable[Path], *, crs: str = "EPSG:5179") -> tuple[Any, dict[str, Any]]:
    """벡터 침수흔적 파일들을 하나의 GeoDataFrame 으로. 좌표계 통일과 geometry 보정까지."""
    import geopandas as gpd
    import pandas as pd

    from src.data.spatial import ensure_crs, fix_geometry

    paths = [Path(p) for p in paths]
    if not paths:
        raise FloodTraceUnavailable("벡터 침수흔적 파일이 없다")

    frames, per_file = [], {}
    for path in paths:
        gdf = gpd.read_file(path)
        if gdf.empty:
            per_file[path.name] = 0
            continue
        gdf = ensure_crs(gdf, crs)
        gdf["source_file"] = path.name
        per_file[path.name] = int(len(gdf))
        frames.append(gdf)
    if not frames:
        raise FloodTraceUnavailable(f"파일은 있으나 도형이 하나도 없다: {sorted(per_file)}")

    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=crs)
    merged, fixed = fix_geometry(merged)
    merged = merged[merged.geometry.notna() & ~merged.geometry.is_empty].copy()

    date_col = next((c for c in DATE_COLUMN_CANDIDATES if c in merged.columns), None)
    cause_col = next((c for c in CAUSE_COLUMN_CANDIDATES if c in merged.columns), None)
    if date_col:
        merged["event_date"] = pd.to_datetime(merged[date_col], errors="coerce")
    merged["cause"] = merged[cause_col] if cause_col else None

    is_area = merged.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    metrics = {
        "n_files": len(paths),
        "rows_per_file": per_file,
        "n_traces": int(len(merged)),
        "n_polygons": int(is_area.sum()),
        "invalid_fixed": fixed,
        "area_km2": round(float(merged.loc[is_area].geometry.area.sum() / 1e6), 3),
        "date_column": date_col,
        "cause_column": cause_col,
        "date_range": (
            [str(merged["event_date"].min()), str(merged["event_date"].max())] if date_col else None
        ),
        "columns": merged.columns.tolist(),
        "crs": crs,
    }
    return merged, metrics


def label_grid(grid, traces, *, min_overlap: float = 0.0):
    """격자마다 침수흔적과 겹치는지 표시한다. 면적 비율이 `min_overlap` 을 넘으면 양성."""
    import geopandas as gpd
    import numpy as np

    areas = np.zeros(len(grid))
    joined = gpd.sjoin(
        grid[["geometry"]].reset_index(names="_row"), traces[["geometry"]], predicate="intersects", how="inner"
    )
    for row, group in joined.groupby("_row"):
        cell = grid.geometry.iloc[row]
        overlap = traces.geometry.iloc[group["index_right"].to_numpy()].intersection(cell).area.sum()
        areas[row] = min(float(overlap) / cell.area, 1.0)
    return areas > min_overlap, areas
