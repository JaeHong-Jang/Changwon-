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


def _si_boundary():
    import geopandas as gpd

    return gpd.read_file(PROJECT_ROOT / "data/processed/spatial/changwon_boundary.gpkg", layer="si").geometry.iloc[0]


def _write_layer(out: Path, gdf, layer: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    gdf.to_file(out, layer=layer, driver="GPKG")


def stations(ctx: StageContext) -> dict[str, Any]:
    """강수 관측지점·수위계 좌표(`data/external/stations.csv`)를 EPSG:5179 포인트로 결합한다.

    통과: 좌표 확보율 ≥ params.min_station_coord_coverage, 위경도 뒤바뀜·중복 코드 없음,
    전 지점이 창원시 경계 안, 좌표가 있는 강수 cohort(2015~2024 관측일 ≥90%) 지점 수 ≥
    params.min_idw_stations_per_event. reviewed=N 은 실제 설치 위치 비공개 근사점이므로
    `is_proxy` 로 남기고 통과 여부에는 쓰지 않는다 (Layer 1 에서 제외 민감도 1회).
    이벤트별 정상지점 수는 이벤트 정의가 Layer 1 에 있으므로 거기서 판정한다.
    """
    import pandas as pd

    from src.data.quality import cohort_station_ids
    from src.data.stations import station_table, to_points

    csv = next(p for p in ctx.inputs if p.name == "stations.csv")
    table, m = station_table(pd.read_csv(csv, encoding="utf-8-sig"))

    rain = pd.read_parquet(
        PROJECT_ROOT / "data/processed/canonical/rainfall_hourly.parquet", columns=["station_id", "obs_date"]
    )
    cohort = cohort_station_ids(
        rain,
        pd.Timestamp(ctx.params["analysis.climatology_start"]),
        pd.Timestamp(ctx.params["analysis.climatology_end"]),
        float(ctx.params["analysis.min_station_day_coverage"]),
    )
    table["in_rain_cohort"] = (table["station_type"] == "rain") & table["station_code"].isin(cohort)

    pts = to_points(table.dropna(subset=["lat", "lon"]))
    si = _si_boundary()
    outside = pts[~pts.within(si)]
    m.update({
        "n_rain_cohort": len(cohort),
        "n_rain_cohort_with_coords": int(pts["in_rain_cohort"].sum()),
        "min_idw_stations_per_event": int(ctx.params["analysis.min_idw_stations_per_event"]),
        "min_coord_coverage": float(ctx.params["analysis.min_station_coord_coverage"]),
        "n_outside_boundary": int(len(outside)),
        "outside_boundary_codes": outside["station_code"].tolist(),
        "crs": pts.crs.to_string(),
    })

    findings: list[dict[str, Any]] = []
    if m["coord_coverage"] < m["min_coord_coverage"]:
        findings.append({"code": "coord_coverage", "detail": f"{m['coord_coverage']} < {m['min_coord_coverage']}"})
    if m["out_of_box_codes"]:
        findings.append({"code": "lat_lon_swapped_or_far", "detail": m["out_of_box_codes"]})
    if m["duplicate_codes"]:
        findings.append({"code": "duplicate_station_code", "detail": m["duplicate_codes"]})
    if m["n_outside_boundary"]:
        findings.append({"code": "outside_boundary", "detail": m["outside_boundary_codes"]})
    if m["n_rain_cohort_with_coords"] < m["min_idw_stations_per_event"]:
        findings.append({
            "code": "too_few_idw_stations",
            "detail": f"cohort 좌표 지점 {m['n_rain_cohort_with_coords']} < {m['min_idw_stations_per_event']}",
        })
    if findings:
        raise StageFailed("관측지점 좌표 결합 통과 기준 미달", findings, metrics=m)

    pts = pts[[
        "station_code", "station_name", "station_type", "in_rain_cohort", "lat", "lon",
        "source", "reviewed", "is_proxy", "note", "geometry",
    ]]
    _write_layer(ctx.outputs[0], pts, "stations")
    _stations_map(pts, si, PROJECT_ROOT / "reports/figures/stations_map.png")
    return m


def _stations_map(pts, si, out: Path) -> None:
    """G003 증거용 그림. 데이터 산출물이 아니므로 outputs 에 넣지 않는다."""
    import geopandas as gpd

    from src.visualization import style

    fig, ax = style.new_axes("관측지점 위치", "번호 = 지점 코드 · 빈 기호 = 실제 설치 위치 비공개 근사점", figsize=(8, 7))
    gpd.GeoSeries([si], crs=pts.crs).plot(ax=ax, facecolor="none", edgecolor="0.5", linewidth=0.8)
    for kind, marker, label in (("rain", "o", "강수"), ("water_level", "^", "수위계")):
        sub = pts[pts["station_type"] == kind]
        sub[~sub["is_proxy"]].plot(ax=ax, marker=marker, markersize=36, label=f"{label} (검수)")
        if sub["is_proxy"].any():
            sub[sub["is_proxy"]].plot(ax=ax, marker=marker, markersize=36, facecolor="none", edgecolor="C3", label=f"{label} (근사점)")
    for r in pts.itertuples():
        ax.annotate(str(r.station_code), (r.geometry.x, r.geometry.y), fontsize=6, xytext=(3, 3), textcoords="offset points")
    ax.legend()
    ax.set_axis_off()
    style.save(fig, out)


def pump_stations(ctx: StageContext) -> dict[str, Any]:
    """배수펌프장 좌표: 창원시 배수펌프장 표준데이터(공식 좌표)를 기본으로, 공식 목록에 없는
    지오코딩 펌프장(`pump_stations_geocoded.csv`, 사람 검수)을 보탠다.

    통과: 공식 좌표 결측 0, 지오코딩으로 추가된 행 전부 reviewed=Y, 전 지점 창원 경계 안.
    """
    import pandas as pd

    from src.data.stations import merge_pump_sources

    geocoded_csv = next(p for p in ctx.inputs if p.name == "pump_stations_geocoded.csv")
    official_csv = next(p for p in ctx.inputs if p != geocoded_csv)
    merged, m = merge_pump_sources(
        pd.read_csv(official_csv, encoding="utf-8-sig"), pd.read_csv(geocoded_csv, encoding="utf-8-sig")
    )
    si = _si_boundary()
    outside = merged[~merged.within(si)]
    m["n_outside_boundary"] = int(len(outside))
    m["outside_boundary_names"] = outside["pump_name"].tolist()
    m["n_reviewed"] = int(merged["reviewed"].sum())
    m["crs"] = merged.crs.to_string()

    findings: list[dict[str, Any]] = []
    if m["n_official_without_coords"]:
        findings.append({"code": "official_missing_coords", "detail": m["n_official_without_coords"]})
    if m["n_added_unreviewed"]:
        names = merged.loc[(merged["source_kind"] == "geocoded") & ~merged["reviewed"], "pump_name"].tolist()
        findings.append({"code": "geocoded_not_reviewed", "detail": names})
    if m["n_outside_boundary"]:
        findings.append({"code": "outside_boundary", "detail": m["outside_boundary_names"]})
    if findings:
        raise StageFailed("펌프장 좌표 결합 통과 기준 미달", findings, metrics=m)

    _write_layer(ctx.outputs[0], merged, "pump_stations")
    return m
