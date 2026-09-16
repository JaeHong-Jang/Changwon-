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
# 같은 폴더에 수집 기록·메타데이터가 함께 놓인다. .json 은 GeoJSON 일 수도 있어
# 확장자만으로는 못 거르므로 이름으로 먼저 걸러 내고, 그래도 안 읽히면 건너뛴다.
SKIP_NAME_TOKENS = ("metric", "meta", "manifest", "readme", "log")
IMAGE_SUFFIXES = {".pdf", ".csd", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dwg", ".dxf"}

# 사상 일자·원인으로 쓸 컬럼 이름 후보 (먼저 맞는 것을 쓴다).
# F_SAT_YMD·F_RSN_DTL 은 2026-09-16 수령분의 NDMS 표준 스키마다.
# F_* 는 창원시 회신분(NDMS 표준), FLDN_* 은 행안부 공유플랫폼 API(DSSP-IF-00117) 스키마다.
DATE_COLUMN_CANDIDATES = (
    "F_SAT_YMD", "FLDN_BGNG_YMD", "침수일자", "발생일자", "사상일자", "피해일자", "일자",
    "OCCUR_DE", "FLUD_DE", "date",
)
CAUSE_COLUMN_CANDIDATES = (
    "F_RSN_DTL", "FLDN_CS_DTL_NM", "침수원인", "원인", "재해원인", "F_RSN_CD", "CAUSE", "cause",
)
EVENT_COLUMN_CANDIDATES = ("F_DISA_NM", "FLDN_DST_NM", "사상명", "재해명", "EVENT")
YEAR_COLUMN_CANDIDATES = ("FLDN_YR", "F_YR", "INV_YR", "연도")
# 침수 원인이 내수(배수 불량·용량 부족)인지 외수(하천 범람·해일)인지. Layer 1 은 내수를 겨냥한다.
INLAND_CAUSE_TOKENS = ("내수", "배수", "우수", "관거", "맨홀", "저지대")


class FloodTraceUnavailable(RuntimeError):
    """읽을 수 있는 벡터 침수흔적 자료가 없다. 사유와 다음 행동을 메시지에 담는다."""


def find_files(root: Path) -> tuple[list[Path], list[Path]]:
    """(벡터 파일, 그림 파일) 로 나눠 돌려준다."""
    if not root.exists():
        return [], []
    files = [p for p in root.rglob("*") if p.is_file()]
    vectors = sorted(
        p for p in files
        if p.suffix.lower() in VECTOR_SUFFIXES
        and not any(tok in p.stem.lower() for tok in SKIP_NAME_TOKENS)
    )
    images = sorted(p for p in files if p.suffix.lower() in IMAGE_SUFFIXES)
    return vectors, images


def _read_vectors(paths, crs: str):
    """벡터 파일들을 한 표로 읽는다. 읽히지 않는 파일은 멈추지 않고 사유만 기록한다."""
    import geopandas as gpd
    import pandas as pd

    from src.data.spatial import ensure_crs

    frames, per_file, skipped = [], {}, {}
    for path in paths:
        try:
            gdf = gpd.read_file(path)
        except Exception as exc:   # 지리 파일이 아닌 것이 섞여 있어도 멈추지 않는다
            skipped[path.name] = type(exc).__name__
            continue
        if gdf.empty:
            per_file[path.name] = 0
            continue
        gdf = ensure_crs(gdf, crs)
        gdf["source_file"] = path.name
        per_file[path.name] = int(len(gdf))
        frames.append(gdf)
    if not frames:
        raise FloodTraceUnavailable(f"읽을 수 있는 도형이 없다 (건너뜀 {sorted(skipped)})")
    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=crs)
    return merged, per_file, skipped


def _drop_duplicate_geometries(gdf):
    """같은 도형이 여러 레이어에 반복되면 하나만 남긴다. (표, 제거 건수).

    창원시 회신분의 L100(침수심)과 L110(침수위)이 **같은 폴리곤**이었다. 그대로 두면
    면적과 라벨이 두 배가 된다. 속성이 많은 행을 남겨 사상·원인 정보를 지키다.
    """
    before = len(gdf)
    gdf = gdf.assign(
        _wkb=gdf.geometry.apply(lambda g: g.normalize().wkb),
        _filled=gdf.notna().sum(axis=1),
    )
    gdf = (gdf.sort_values("_filled", ascending=False)
           .drop_duplicates("_wkb")
           .drop(columns=["_wkb", "_filled"])
           .reset_index(drop=True))
    return gdf, before - len(gdf)


def _derive_event_fields(gdf):
    """자료원마다 다른 컬럼명에서 일자·원인·사상·연도를 뽑아 공통 이름으로 맞춘다."""
    import pandas as pd

    date_col = next((c for c in DATE_COLUMN_CANDIDATES if c in gdf.columns), None)
    cause_col = next((c for c in CAUSE_COLUMN_CANDIDATES if c in gdf.columns), None)
    event_col = next((c for c in EVENT_COLUMN_CANDIDATES if c in gdf.columns), None)
    year_col = next((c for c in YEAR_COLUMN_CANDIDATES if c in gdf.columns), None)

    gdf["event_date"] = (
        pd.to_datetime(gdf[date_col].astype(str), format="%Y%m%d", errors="coerce")
        if date_col else pd.NaT
    )
    if date_col and gdf["event_date"].isna().all():   # 다른 형식일 수 있다
        gdf["event_date"] = pd.to_datetime(gdf[date_col], errors="coerce")
    gdf["cause"] = gdf[cause_col].astype(str) if cause_col else None
    gdf["event_name"] = gdf[event_col].astype(str) if event_col else None
    gdf["event_year"] = (
        gdf[year_col].astype(str) if year_col
        else gdf["event_date"].dt.year.astype("Int64").astype(str)
    )
    gdf["is_inland"] = (
        gdf["cause"].str.contains("|".join(INLAND_CAUSE_TOKENS), na=False) if cause_col else pd.NA
    )
    return gdf, {"date_column": date_col, "cause_column": cause_col}


def load(paths: Iterable[Path], *, crs: str = "EPSG:5179") -> tuple[Any, dict[str, Any]]:
    """벡터 침수흔적 파일들을 하나의 GeoDataFrame 으로. 좌표계·중복·사상 컬럼까지 정리한다."""
    from src.data.spatial import fix_geometry

    paths = [Path(p) for p in paths]
    if not paths:
        raise FloodTraceUnavailable("벡터 침수흔적 파일이 없다")

    merged, per_file, skipped = _read_vectors(paths, crs)
    merged, fixed = fix_geometry(merged)
    merged = merged[merged.geometry.notna() & ~merged.geometry.is_empty].copy()
    merged, duplicates = _drop_duplicate_geometries(merged)
    merged, column_meta = _derive_event_fields(merged)

    is_area = merged.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    metrics = {
        "n_files": len(paths),
        "rows_per_file": per_file,
        "skipped_files": skipped,
        "duplicate_geometries_dropped": duplicates,
        "n_traces": int(len(merged)),
        "n_polygons": int(is_area.sum()),
        "invalid_fixed": fixed,
        "area_km2": round(float(merged.loc[is_area].geometry.area.sum() / 1e6), 3),
        **column_meta,
        "date_range": (
            [str(merged["event_date"].min().date()), str(merged["event_date"].max().date())]
            if merged["event_date"].notna().any() else None
        ),
        "n_events": int(merged["event_name"].nunique()) if merged["event_name"].notna().any() else None,
        "years": sorted(merged["event_year"].dropna().unique().tolist()),
        "n_years": int(merged["event_year"].nunique()),
        "n_inland": int(merged["is_inland"].sum()) if merged["is_inland"].notna().any() else None,
        "causes": sorted(merged["cause"].dropna().unique().tolist())[:6] if merged["cause"].notna().any() else None,
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
