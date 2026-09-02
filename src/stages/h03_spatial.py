"""H03 공간기반 구축. 전 레이어 EPSG:5179(params.canonical_crs), geometry valid 100%."""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

from src.data.spatial import CHANGWON_AREA_KM2, CHANGWON_GU_CODES, build_boundary, select_grid_in_boundary
from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT


def boundary(ctx: StageContext) -> dict[str, Any]:
    """SGIS 집계구 경계(창원 5개 구)를 dissolve 해 행정동·구·시 3단계 경계를 만든다.

    통과: 구 코드가 정확히 38111~38115, 시 면적이 공식 748 km² ±1%,
    구끼리 겹침이 **격자 1칸(10,000 m²) 미만**.

    겹침 기준을 격자 1칸으로 잡은 이유: 이 경계의 용도는 100m 격자를 구/동에 배정하는
    것이고, 배정은 격자 중심점 1개로 결정된다. 격자 한 칸보다 작은 접합부 슬리버는
    어떤 격자의 배정도 바꿀 수 없으므로 분석 결과에 영향이 없다. 실측 겹침 값은
    metrics 에 항상 남겨 눈으로 확인할 수 있게 한다.
    """
    grid_cell_m2 = float(ctx.params["analysis.grid_size_m"]) ** 2
    paths = [Path(p) for p in sorted(glob.glob(str(PROJECT_ROOT / "data/raw/sgis/aggregation_boundaries_2025_2Q/*.shp")))]
    layers, m = build_boundary(paths)

    findings: list[dict[str, Any]] = []
    if set(m["gu_codes"]) != CHANGWON_GU_CODES:
        findings.append({"code": "gu_codes", "detail": f"{m['gu_codes']} != {sorted(CHANGWON_GU_CODES)}"})
    m["gu_overlap_threshold_m2"] = grid_cell_m2
    if m["gu_overlap_m2"] >= grid_cell_m2:
        findings.append({
            "code": "gu_overlap",
            "detail": f"{m['gu_overlap_m2']} m² ≥ 격자 1칸 {grid_cell_m2} m² — 실제 중복 영역 의심",
        })
    if not (0.99 <= m["area_ratio_vs_official"] <= 1.01):
        findings.append({
            "code": "area_mismatch",
            "detail": f"{m['area_km2']} km² / 공식 {CHANGWON_AREA_KM2} km² = {m['area_ratio_vs_official']}",
        })
    if findings:
        raise StageFailed("창원시 경계 파생 통과 기준 미달", findings)

    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    for name, gdf in layers.items():
        gdf.to_file(out, layer=name, driver="GPKG")
    return m


def grid_base(ctx: StageContext) -> dict[str, Any]:
    """창원시 경계로 SGIS 100m 격자를 선택(중심점 기준)해 분석격자를 만든다.

    통과: grid_id 중복 0, 격자 수가 시 면적 기준 예상치의 ±15% 이내.
    """
    import geopandas as gpd

    bpath = PROJECT_ROOT / "data/processed/spatial/changwon_boundary.gpkg"
    si = gpd.read_file(bpath, layer="si")
    emd = gpd.read_file(bpath, layer="emd")
    paths = [Path(p) for p in sorted(glob.glob(str(PROJECT_ROOT / "data/raw/sgis/grid_boundaries_100m_2025/*.shp")))]
    grid, m = select_grid_in_boundary(paths, si, emd)

    area_km2 = float(si.geometry.iloc[0].area / 1e6)
    expected = area_km2 / 0.01  # 100m 격자 = 0.01 km²
    m["expected_n_grid"] = round(expected)
    m["n_grid_ratio"] = round(m["n_grid"] / expected, 4)

    findings: list[dict[str, Any]] = []
    if m["duplicate_grid_id"]:
        findings.append({"code": "duplicate_grid_id", "detail": m["duplicate_grid_id"]})
    if not (0.85 <= m["n_grid_ratio"] <= 1.15):
        findings.append({"code": "grid_count", "detail": f"{m['n_grid']} vs 예상 {round(expected)} (비 {m['n_grid_ratio']})"})
    if findings:
        raise StageFailed("분석격자 구축 통과 기준 미달", findings)

    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    grid.to_file(out, layer="grid", driver="GPKG")
    return m


def flood_maps(ctx: StageContext) -> dict[str, Any]:
    """창원 침수예상도 13개 레이어를 분석 CRS 로 재투영하고 깨진 한글을 복원한다.

    통과: 원본 CRS 가 예상대로 EPSG:5181, 변환 후 EPSG:5179, 침수심 구간이 전부
    대표값으로 매핑됨, invalid geometry 0. 한글 복원 결과를 metrics 에 남겨 눈으로 본다.
    """
    from src.data import flood_maps as fm

    paths = [Path(p) for p in sorted(glob.glob(str(PROJECT_ROOT / "data/raw/flood_maps/changwon_wfs/*.geojson")))]
    merged, m = fm.combine(paths)

    findings: list[dict[str, Any]] = []
    if m["source_crs"] != [fm.SOURCE_CRS]:
        findings.append({"code": "unexpected_source_crs", "detail": m["source_crs"]})
    if m["unmapped_depth_classes"]:
        findings.append({"code": "unmapped_depth_class", "detail": m["unmapped_depth_classes"]})
    if m["invalid_geometry_remaining"]:
        findings.append({"code": "invalid_geometry", "detail": m["invalid_geometry_remaining"]})
    if not m["repaired_text_sample"]:
        findings.append({
            "code": "text_not_repaired",
            "detail": "한글이 하나도 복원되지 않았다. 인코딩 처리가 건너뛰어졌을 수 있다",
        })
    if findings:
        raise StageFailed("침수예상도 정규화 통과 기준 미달", findings, metrics=m)

    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_file(out, layer="flood_maps", driver="GPKG")
    return m
