"""침수흔적도 로더: 흔적도는 Layer 1 입력이 아니라 검증 라벨이다."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from src.data.trace_events import _derive_event_fields
from src.data.trace_labels import label_grid
from src.data.trace_registry import (
    PROJECT_ROOT,
    SKIP_NAME_TOKENS,
    VECTOR_SUFFIXES,
    files_for,
    load_registry,
    registered_files,
)

IMAGE_SUFFIXES = {".pdf", ".csd", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dwg", ".dxf"}


class FloodTraceUnavailable(RuntimeError):
    """읽을 수 있는 벡터 침수흔적 자료가 없다. 사유와 다음 행동을 메시지에 담는다."""


def find_files(root: Path) -> tuple[list[Path], list[Path]]:
    """(벡터 파일, 그림 파일) 로 나눠 돌려준다."""
    # 없는 경로는 빈 결과로 반환하고 벡터와 그림 파일을 분류한다.
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


def _read_vectors(paths: list[Path], crs: str):
    """벡터 파일들을 한 표로 읽는다. 읽히지 않는 파일은 멈추지 않고 사유만 기록한다."""
    # 벡터 파일과 속성 표를 읽을 도구를 준비한다.
    import geopandas as gpd
    import pandas as pd

    # 자료원의 좌표계를 분석 좌표계로 맞출 함수를 준비한다.
    from src.data.spatial import ensure_crs

    # 등록된 출처를 연결하고 읽기 실패 사유와 원본 행번호를 보존한다.
    sources = {path: (source_id, role) for path, source_id, role
               in registered_files(load_registry(), PROJECT_ROOT)}
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
        gdf["source_id"], gdf["role"] = sources.get(path.resolve(), (path.stem, "unregistered"))
        # 원본 행번호는 1부터 세며 중복 제거 뒤에도 바꾸지 않는다.
        gdf["source_record_id"] = [f"{path.name}#{i + 1}" for i in range(len(gdf))]
        per_file[path.name] = int(len(gdf))
        frames.append(gdf)
    if not frames:
        raise FloodTraceUnavailable(f"읽을 수 있는 도형이 없다 (건너뜀 {sorted(skipped)})")
    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=crs)
    return merged, per_file, skipped


def _drop_duplicate_geometries(gdf):
    """같은 역할·호우의 도형이 여러 레이어에 반복되면 하나만 남긴다."""
    # 중복 도형의 호우를 대조할 표 연산 도구를 준비한다.
    import pandas as pd

    # 도형 표준형·일자 유무·속성 완성도로 중복 제거 우선순위를 만든다.
    before = len(gdf)
    gdf = gdf.assign(
        _wkb=gdf.geometry.apply(lambda g: g.normalize().wkb),
        _dated=gdf["event_date"].notna(),
        _filled=gdf.notna().sum(axis=1),
    )
    # 날짜 없는 L100은 같은 연도·도형에 호우가 하나인 경우에만 L110과 묶는다.
    keys = ["role", "event_year", "_wkb"]
    dated = gdf[gdf["event_date"].notna()].drop_duplicates(keys + ["storm_id"])
    unique = dated[~dated.duplicated(keys, keep=False)].set_index(keys)["storm_id"]
    matched = unique.reindex(pd.MultiIndex.from_frame(gdf[keys])).to_numpy()
    gdf["_dedup_storm"] = gdf["storm_id"].where(gdf["event_date"].notna(),
                                               pd.Series(matched, index=gdf.index)).fillna(gdf["storm_id"])
    # 매칭에 사용한 날짜·호우가 사라지지 않도록 날짜 있는 행부터 남긴다.
    gdf = (gdf.sort_values(["_dated", "_filled"], ascending=False, kind="stable")
           .drop_duplicates(["role", "_dedup_storm", "_wkb"])
           .drop(columns=["_wkb", "_dated", "_filled", "_dedup_storm"])
           .reset_index(drop=True))
    return gdf, before - len(gdf)


def load(paths: Iterable[Path], *, crs: str = "EPSG:5179") -> tuple[Any, dict[str, Any]]:
    """벡터 침수흔적 파일들을 하나의 GeoDataFrame 으로. 좌표계·중복·사상 컬럼까지 정리한다."""
    # 유효하지 않은 도형을 복원할 함수를 준비한다.
    from src.data.spatial import fix_geometry

    # 입력 경로를 정규화하고 빈 입력을 거부한다.
    paths = [Path(p) for p in paths]
    if not paths:
        raise FloodTraceUnavailable("벡터 침수흔적 파일이 없다")

    # 벡터를 읽고 도형·사상·중복을 정리한 뒤 안정적인 객체 ID를 부여한다.
    merged, per_file, skipped = _read_vectors(paths, crs)
    merged, fixed = fix_geometry(merged)
    merged = merged[merged.geometry.notna() & ~merged.geometry.is_empty].copy()
    merged, column_meta = _derive_event_fields(merged)
    merged, duplicates = _drop_duplicate_geometries(merged)
    merged["object_id"] = [
        sha256(f"{role}|{storm}|".encode() + geometry.normalize().wkb).hexdigest()
        for role, storm, geometry in zip(merged["role"], merged["storm_id"], merged.geometry)
    ]

    # 정리된 도형의 면적·사상·품질 지표를 원래 순서로 집계한다.
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
        "union_area_km2": float(merged.loc[is_area].geometry.union_all().area / 1e6),
        **column_meta,
        "date_range": (
            [str(merged["event_date"].min().date()), str(merged["event_date"].max().date())]
            if merged["event_date"].notna().any() else None
        ),
        "n_events": int(merged["event_name"].nunique()) if merged["event_name"].notna().any() else None,
        "years": sorted(merged["event_year"].dropna().unique().tolist()),
        "n_years": int(merged["event_year"].nunique()),
        "n_storms": int(merged["storm_id"].nunique()),
        "n_inland": int(merged["is_inland"].sum()) if merged["is_inland"].notna().any() else None,
        "causes": sorted(merged["cause"].dropna().unique().tolist())[:6] if merged["cause"].notna().any() else None,
        "columns": merged.columns.tolist(),
        "crs": crs,
    }
    return merged, metrics


def load_holdout(*, crs: str = "EPSG:5179") -> tuple[Any, dict[str, Any]]:
    """최종 평가용 홀드아웃 정본만 읽는다."""
    # 홀드아웃 역할로 등록된 파일만 공통 로더에 전달한다.
    return load(files_for("holdout"), crs=crs)
