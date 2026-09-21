"""공간자료 처리. 기준 CRS는 EPSG:5179."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import make_valid

CANONICAL_CRS = "EPSG:5179"
CHANGWON_GU_CODES = {"38111", "38112", "38113", "38114", "38115"}
CHANGWON_AREA_KM2 = 748.0  # 창원시 공식 면적 (검증 기준)


def ensure_crs(gdf: gpd.GeoDataFrame, target: str = CANONICAL_CRS) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        raise ValueError("CRS 정보가 없는 레이어입니다 (.prj 누락)")
    return gdf if gdf.crs.to_string() == target else gdf.to_crs(target)


def fix_geometry(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, int]:
    """invalid geometry를 make_valid로 고치고 고친 건수를 함께 반환한다."""
    invalid = ~gdf.geometry.is_valid
    n = int(invalid.sum())
    if n:
        gdf = gdf.copy()
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].apply(make_valid)
    return gdf, n


def build_boundary(agg_boundary_paths: list[Path]) -> tuple[dict[str, gpd.GeoDataFrame], dict[str, Any]]:
    """집계구 경계에서 행정동·구·시 경계를 만든다."""
    frames = [ensure_crs(gpd.read_file(p)) for p in sorted(agg_boundary_paths)]
    agg = pd.concat(frames, ignore_index=True)
    agg = gpd.GeoDataFrame(agg, geometry="geometry", crs=CANONICAL_CRS)
    agg, fixed = fix_geometry(agg)

    agg["adm_cd"] = agg["ADM_CD"].astype(str)
    agg["gu_code"] = agg["adm_cd"].str[:5]

    emd = agg.dissolve(by="adm_cd", as_index=False)[["adm_cd", "gu_code", "geometry"]]
    gu = agg.dissolve(by="gu_code", as_index=False)[["gu_code", "geometry"]]
    si = gpd.GeoDataFrame(
        {"si_code": ["38110"], "si_name": ["창원시"]},
        geometry=[agg.union_all()],
        crs=CANONICAL_CRS,
    )

    overlap_m2 = 0.0
    for i in range(len(gu)):
        for j in range(i + 1, len(gu)):
            overlap_m2 += gu.geometry.iloc[i].intersection(gu.geometry.iloc[j]).area

    area_km2 = float(si.geometry.iloc[0].area / 1e6)
    metrics = {
        "n_aggregation_units": int(len(agg)),
        "n_emd": int(len(emd)),
        "n_gu": int(len(gu)),
        "gu_codes": sorted(gu["gu_code"].tolist()),
        "area_km2": round(area_km2, 2),
        "area_ratio_vs_official": round(area_km2 / CHANGWON_AREA_KM2, 4),
        "gu_overlap_m2": round(overlap_m2, 3),
        "invalid_fixed": fixed,
        "crs": CANONICAL_CRS,
    }
    return {"emd": emd, "gu": gu, "si": si}, metrics


def select_grid_in_boundary(
    grid_paths: list[Path], si: gpd.GeoDataFrame, emd: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """전국 100m 격자 도엽에서 중심점이 창원 경계 안인 격자만 고른다."""
    bbox = tuple(si.total_bounds)
    frames = []
    read_counts = {}
    for path in sorted(grid_paths):
        g = gpd.read_file(path, bbox=bbox)
        read_counts[path.name] = int(len(g))
        if len(g):
            frames.append(ensure_crs(g))
    if not frames:
        raise ValueError("시 경계 bbox 안에 격자가 하나도 없습니다 — 좌표계 불일치 의심")

    grid = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=CANONICAL_CRS)
    grid = grid.rename(columns={"GRID_CD": "grid_id"})
    grid["grid_id"] = grid["grid_id"].astype(str)
    n_bbox = len(grid)

    centroids = gpd.GeoDataFrame(
        {"grid_id": grid["grid_id"]}, geometry=grid.geometry.centroid, crs=CANONICAL_CRS
    )
    inside = gpd.sjoin(centroids, si[["geometry"]], predicate="within", how="inner")
    grid = grid[grid["grid_id"].isin(inside["grid_id"])].copy()

    # 행정동 부여도 중심점 기준.
    cent = gpd.GeoDataFrame(
        {"grid_id": grid["grid_id"]}, geometry=grid.geometry.centroid, crs=CANONICAL_CRS
    )
    joined = gpd.sjoin(cent, emd[["adm_cd", "gu_code", "geometry"]], predicate="within", how="left")
    joined = joined.drop_duplicates(subset="grid_id")
    grid = grid.merge(
        joined[["grid_id", "adm_cd", "gu_code"]], on="grid_id", how="left"
    )
    grid, fixed = fix_geometry(grid)

    metrics = {
        "tiles_read": read_counts,
        "n_in_bbox": int(n_bbox),
        "n_grid": int(len(grid)),
        "duplicate_grid_id": int(grid["grid_id"].duplicated().sum()),
        "n_without_emd": int(grid["adm_cd"].isna().sum()),
        "invalid_fixed": fixed,
        "crs": CANONICAL_CRS,
    }
    return grid[["grid_id", "adm_cd", "gu_code", "geometry"]], metrics
