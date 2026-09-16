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

# 사상 일자·원인으로 쓸 컬럼 이름 후보 (먼저 맞는 것을 쓴다).
# F_SAT_YMD·F_RSN_DTL 은 2026-09-16 수령분의 NDMS 표준 스키마다.
DATE_COLUMN_CANDIDATES = (
    "F_SAT_YMD", "침수일자", "발생일자", "사상일자", "피해일자", "일자", "OCCUR_DE", "FLUD_DE", "date",
)
CAUSE_COLUMN_CANDIDATES = ("F_RSN_DTL", "침수원인", "원인", "재해원인", "F_RSN_CD", "CAUSE", "cause")
EVENT_COLUMN_CANDIDATES = ("F_DISA_NM", "사상명", "재해명", "EVENT")
# 침수 원인이 내수(배수 불량·용량 부족)인지 외수(하천 범람·해일)인지. Layer 1 은 내수를 겨냥한다.
INLAND_CAUSE_TOKENS = ("내수", "배수", "우수", "관거", "맨홀")


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

    # 같은 도형이 여러 레이어에 반복될 수 있다. 실제 수령분은 L100(침수심)·L110(침수위)이
    # **같은 폴리곤**이었다 (교집합 비율 1.0). 그대로 두면 면적과 라벨이 두 배가 된다.
    before = len(merged)
    merged["_wkb"] = merged.geometry.apply(lambda g: g.normalize().wkb)
    # 속성이 많은 행을 남긴다 (L110 이 사상·원인을 담고 있다).
    merged["_filled"] = merged.notna().sum(axis=1)
    merged = (merged.sort_values("_filled", ascending=False)
              .drop_duplicates("_wkb").drop(columns=["_wkb", "_filled"]))
    duplicate_geometries = before - len(merged)

    date_col = next((c for c in DATE_COLUMN_CANDIDATES if c in merged.columns), None)
    cause_col = next((c for c in CAUSE_COLUMN_CANDIDATES if c in merged.columns), None)
    event_col = next((c for c in EVENT_COLUMN_CANDIDATES if c in merged.columns), None)
    merged["event_date"] = (
        pd.to_datetime(merged[date_col].astype(str), format="%Y%m%d", errors="coerce")
        if date_col else pd.NaT
    )
    if date_col and merged["event_date"].isna().all():   # 다른 형식일 수 있다
        merged["event_date"] = pd.to_datetime(merged[date_col], errors="coerce")
    merged["cause"] = merged[cause_col].astype(str) if cause_col else None
    merged["event_name"] = merged[event_col].astype(str) if event_col else None
    merged["is_inland"] = (
        merged["cause"].str.contains("|".join(INLAND_CAUSE_TOKENS), na=False)
        if cause_col else pd.NA
    )

    merged = merged.reset_index(drop=True)   # 중복 제거로 어긋난 인덱스를 되돌린다
    is_area = merged.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    metrics = {
        "n_files": len(paths),
        "rows_per_file": per_file,
        "duplicate_geometries_dropped": duplicate_geometries,
        "n_traces": int(len(merged)),
        "n_polygons": int(is_area.sum()),
        "invalid_fixed": fixed,
        "area_km2": round(float(merged.loc[is_area].geometry.area.sum() / 1e6), 3),
        "date_column": date_col,
        "cause_column": cause_col,
        "date_range": (
            [str(merged["event_date"].min().date()), str(merged["event_date"].max().date())]
            if date_col and merged["event_date"].notna().any() else None
        ),
        "n_events": int(merged["event_name"].nunique()) if event_col else None,
        "events": sorted(merged["event_name"].dropna().unique().tolist())[:10] if event_col else None,
        "n_inland": int(merged["is_inland"].sum()) if cause_col else None,
        "causes": sorted(merged["cause"].dropna().unique().tolist())[:6] if cause_col else None,
        "columns": merged.columns.tolist(),
        "crs": crs,
    }
    return merged, metrics


def label_grid(grid, traces, *, min_overlap: float = 0.10):
    """격자마다 침수흔적과 겹치는지 표시한다. 면적 비율이 `min_overlap` 을 넘으면 양성.

    임계가 0 이면 폴리곤이 모서리만 스쳐도 양성이 된다. 실제 수령분에서 겹침 비율의
    중앙값이 6%였으므로(대부분 스침), 기본값을 10%로 둔다. 임계는 설정으로 조절한다.
    """
    import geopandas as gpd
    import numpy as np

    areas = np.zeros(len(grid))
    joined = gpd.sjoin(
        grid[["geometry"]].reset_index(names="_row"), traces[["geometry"]], predicate="intersects", how="inner"
    )
    for row, group in joined.groupby("_row"):
        cell = grid.geometry.iloc[row]
        # sjoin 의 index_right 는 위치가 아니라 **라벨**이다. iloc 을 쓰면 인덱스가
        # 0..n-1 이 아닐 때 어긋난다.
        overlap = traces.geometry.loc[group["index_right"].to_numpy()].intersection(cell).area.sum()
        areas[row] = min(float(overlap) / cell.area, 1.0)
    return areas > min_overlap, areas
