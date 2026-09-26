"""H04 격자 피처 결합."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT

SGIS_VARIABLES = {"to_in_001": "pop_total", "to_ga_001": "households", "to_ho_001": "houses"}

# (변수, 출처, 단위, Layer 1 취약 방향(+ 높을수록 취약 / − 낮을수록 취약 / E 노출 / · 참고), 산출 방법)
FEATURE_SPEC: list[tuple[str, str, str, str, str]] = [
    ("elev_m", "국토지리정보원 DEM (90m, EPSG:5179)", "m", "−", "6도엽 mosaic → 100m 격자망 bilinear 재표집"),
    ("slope_deg", "DEM", "도", "−", "100m 표고의 기울기 (np.gradient)"),
    ("rel_elev_m", "DEM", "m", "−", "표고 − 반경 {rel_radius}m 초점평균 (NaN 제외). 음수 = 주변보다 낮음"),
    ("twi", "DEM", "−", "+", "싱크 채움(priority-flood) → D8 유량누적 → ln(a/tanβ), tanβ 하한 0.001"),
    ("flow_acc_cells", "DEM", "셀", "+", "D8 상류 셀 수 (자신 포함)"),
    ("impervious_frac", "환경부 토지피복 중분류 2025, 코드 110~160(시가화·건조지역)", "비율 0~1", "+", "{sub}m 래스터화 → 100m 면적 비율"),
    ("inland_water_frac", "토지피복 코드 710(내륙수)", "비율 0~1", "·", "위와 같음"),
    ("water_dist_m", "토지피복 코드 710(내륙수) — 폭이 있는 수역만 잡힌다", "m", "−", "{sub}m 래스터 EDT, 셀 중심 거리"),
    ("river_dist_m", "OpenStreetMap waterway = river·stream·canal (창원 692개, 총연장 501km)", "m", "−", "하천 중심선까지 {sub}m 래스터 EDT. 토지피복이 못 잡는 소하천까지 포함"),
    ("culvert_dist_m", "OpenStreetMap waterway 중 tunnel=culvert (복개 구간 191개)", "m", "−", "복개천까지 거리. 최유라·한우석(2024)이 창원 피해 가중요인으로 지목"),
    ("sea_dist_m", "토지피복 코드 720(해양수)", "m", "−", "위와 같음"),
    ("flood_l210_100_frac", "창원 도시침수정보시스템 침수예상도 L210_100 (내수침수, 100년 빈도)", "비율 0~1", "+", "{sub}m 래스터화 → 침수 면적 비율"),
    ("flood_l210_100_depth_m", "침수예상도 L210_100 침수심 구간 대표값", "m", "+", "면적가중 평균 침수심 (겹치면 깊은 쪽, 비침수 부분 0)"),
    ("flood_l200_100_frac", "침수예상도 L200_100 (하천범람, 100년)", "비율 0~1", "+", "침수 면적 비율"),
    ("flood_l220_100_frac", "침수예상도 L220_100 (해안침수, 100년)", "비율 0~1", "+", "침수 면적 비율"),
    ("pump_dist_m", "h03_pump_stations (창원시 배수펌프장 표준데이터 15 + 지오코딩 2)", "m", "−", "셀 중심에서 최근접 펌프장 거리"),
    ("pump_within_km", "위와 같음", "0/1", "+", "펌프장 반경 {pump_radius}m 이내 = 자연배수 불가 지역의 행정적 인정 (ANALYSIS_PLAN §2-1). Layer 3 에는 쓰지 않음"),
    ("pop_total", "SGIS 100m 격자통계 {sgis_year} to_in_001", "명", "E", "grid_id 결합. SGIS 가 발행하지 않은 격자는 0 (sgis_reported=0)"),
    ("households", "SGIS to_ga_001", "가구", "E", "위와 같음"),
    ("houses", "SGIS to_ho_001", "호", "E", "위와 같음"),
    ("sgis_reported", "SGIS", "0/1", "·", "SGIS 가 하나라도 값을 발행한 격자"),
    ("universe", "파생", "0/1", "·", "pop_total > 0 또는 houses ≥ 1 — 순위 대상 격자 (ANALYSIS_PLAN §1)"),
]
CORE = [
    "elev_m", "slope_deg", "rel_elev_m", "twi", "impervious_frac", "water_dist_m",
    "flood_l210_100_depth_m", "pump_dist_m", "pop_total", "river_dist_m",
]


def _terrain_layers(dem_paths, lat, rel_radius_m: float):
    """DEM 에서 지형 변수를 만든다."""
    from src.data import features as F

    elev, meta = F.dem_to_lattice(dem_paths, lat)
    twi, acc = F.twi(elev, lat.res)
    layers = {
        "elev_m": elev,
        "slope_deg": F.slope_deg(elev, lat.res),
        "rel_elev_m": F.relative_elevation(elev, lat.res, rel_radius_m),
        "twi": twi,
        "flow_acc_cells": acc,
    }
    return layers, meta


def _land_cover_layers(lc_paths, lat, sub: int, crs: str):
    """토지피복에서 불투수면 비율과 수역까지의 거리를 만든다. (변수 dict, 메타)."""
    import geopandas as gpd
    import pandas as pd

    from src.data import features as F

    lc = pd.concat([gpd.read_file(q) for q in lc_paths], ignore_index=True)
    lc = gpd.GeoDataFrame(lc, geometry="geometry", crs=lc.crs).to_crs(crs)
    lc["L2_CODE"] = lc["L2_CODE"].astype(str)
    inland = lc.loc[lc["L2_CODE"] == F.INLAND_WATER_CODE, "geometry"]
    layers = {
        "impervious_frac": F.area_fraction(lc.loc[lc["L2_CODE"].isin(F.IMPERVIOUS_CODES), "geometry"], lat, sub),
        "inland_water_frac": F.area_fraction(inland, lat, sub),
        "water_dist_m": F.distance_to(inland, lat, sub),
        "sea_dist_m": F.distance_to(lc.loc[lc["L2_CODE"] == F.SEA_CODE, "geometry"], lat, sub),
    }
    return layers, {"land_cover_polygons": int(len(lc))}


def _waterway_layers(lat, sub: int, crs: str):
    """OSM 하천망에서 하천·복개천까지의 거리를 만든다."""
    import geopandas as gpd

    from src.data import features as F

    waterways = gpd.read_file(PROJECT_ROOT / "data/raw/rivers/osm_waterways.gpkg", layer="waterways").to_crs(crs)
    channels = waterways[waterways["waterway"].isin(["river", "stream", "canal"])]
    culverts = waterways[waterways["tunnel"] == "culvert"]
    layers = {
        "river_dist_m": F.distance_to(channels["geometry"], lat, sub),
        "culvert_dist_m": F.distance_to(culverts["geometry"], lat, sub) if len(culverts) else None,
    }
    meta = {"waterways": {
        "n_total": int(len(waterways)),
        "by_type": {k: int(v) for k, v in waterways["waterway"].value_counts().items()},
        "n_channel": int(len(channels)),
        "n_culvert": int(len(culverts)),
        "channel_length_km": round(float(channels.geometry.length.sum() / 1000), 1),
    }}
    return layers, meta


def _flood_map_layers(lat, sub: int, crs: str):
    """창원시 침수예상도에서 100년 빈도 면적비와 침수심을 만든다."""
    import geopandas as gpd

    from src.data import features as F

    fm = gpd.read_file(PROJECT_ROOT / "data/processed/canonical/flood_maps.gpkg", layer="flood_maps").to_crs(crs)
    l210_frac, l210_depth = F.value_fraction_and_mean(fm[fm["layer"] == "L210_100"], "depth_m", lat, sub)
    return {
        "flood_l210_100_frac": l210_frac,
        "flood_l210_100_depth_m": l210_depth,
        "flood_l200_100_frac": F.area_fraction(fm.loc[fm["layer"] == "L200_100", "geometry"], lat, sub),
        "flood_l220_100_frac": F.area_fraction(fm.loc[fm["layer"] == "L220_100", "geometry"], lat, sub),
    }


def _pump_layers(lat, crs: str):
    """배수펌프장까지의 거리. (변수 dict, 메타)."""
    import geopandas as gpd

    from src.data import features as F

    pumps = gpd.read_file(
        PROJECT_ROOT / "data/processed/spatial/pump_stations.gpkg", layer="pump_stations"
    ).to_crs(crs)
    return {"pump_dist_m": F.nearest_point_distance(lat, pumps)}, {"n_pumps": int(len(pumps))}


def _attach_population(out, sgis_year: int):
    """SGIS 인구·가구·주택을 붙이고 순위 대상(universe)을 정한다."""
    import pandas as pd

    from src.data import features as F

    stats = pd.read_parquet(PROJECT_ROOT / "data/processed/canonical/sgis_grid_statistics.parquet")
    out = out.merge(F.sgis_wide(stats, sgis_year, SGIS_VARIABLES), on="grid_id", how="left")
    out["sgis_reported"] = out[list(SGIS_VARIABLES.values())].notna().any(axis=1).astype("int8")
    for column in SGIS_VARIABLES.values():
        out[column] = out[column].fillna(0).astype("int64")
    out["universe"] = ((out["pop_total"] > 0) | (out["houses"] >= 1)).astype("int8")
    return out


def grid_features(ctx: StageContext) -> dict[str, Any]:
    """통과: 핵심 변수 결측률 < params.features.max_missing_rate, 변수별 출처·방향·단위가
    data_dictionary 에 있음, 라벨(침수흔적·민원)을 입력으로 쓰지 않았음(누수 점검)."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd

    from src.data import features as F

    p = ctx.params
    sub = int(p["features.raster_subdivision"])
    rel_radius = float(p["features.relative_elevation_radius_m"])
    pump_radius = float(p["features.pump_service_radius_m"])
    sgis_year = int(p["features.sgis_year"])
    max_missing = float(p["features.max_missing_rate"])
    crs = p["analysis.canonical_crs"]

    grid = gpd.read_file(PROJECT_ROOT / "data/processed/spatial/grid_base.gpkg", layer="grid")
    lat, row, col = F.lattice_from_grid(grid, float(p["analysis.grid_size_m"]))
    m: dict[str, Any] = {"n_grid": int(len(grid)), "lattice_shape": list(lat.shape)}

    # 자료원별로 격자망 위의 2차원 배열을 만든 뒤, 마지막에 (row, col) 로 한 번에 읽는다.
    layers: dict[str, Any] = {}
    for produced, meta in (
        _terrain_layers(sorted(q for q in ctx.inputs if q.suffix.lower() in (".img", ".tif", ".tiff")),
                        lat, rel_radius),
        _land_cover_layers(sorted(q for q in ctx.inputs if q.suffix.lower() == ".shp"), lat, sub, crs),
        _waterway_layers(lat, sub, crs),
        (_flood_map_layers(lat, sub, crs), {}),
        _pump_layers(lat, crs),
    ):
        layers.update(produced)
        m.update(meta)

    out = pd.DataFrame({
        "grid_id": grid["grid_id"].to_numpy(),
        "adm_cd": grid["adm_cd"].to_numpy(),
        "gu_code": grid["gu_code"].to_numpy(),
        **{name: (values[row, col] if values is not None else np.nan) for name, values in layers.items()},
    })
    out["pump_within_km"] = (out["pump_dist_m"] <= pump_radius).astype("int8")
    out = _attach_population(out, sgis_year).sort_values("grid_id").reset_index(drop=True)

    missing = {c: round(float(out[c].isna().mean()), 4) for c in CORE}
    universe = out[out["universe"] == 1]
    m.update({
        "n_features": int(len(FEATURE_SPEC)),
        "n_universe": int(len(universe)),
        "pop_total_sum": int(out["pop_total"].sum()),
        "sgis_reported_grids": int(out["sgis_reported"].sum()),
        "missing_rate_by_feature": missing,
        "missing_rate_in_universe": {c: round(float(universe[c].isna().mean()), 4) for c in CORE},
        "max_missing_rate": max_missing,
        "label_sources_used": [],  # 누수 점검: 침수흔적·민원은 이 노드의 입력이 아니다
        "feature_summary": {
            c: {"mean": round(float(out[c].mean()), 4), "p50": round(float(out[c].median()), 4)}
            for c in CORE
        },
    })

    findings: list[dict[str, Any]] = []
    over = {c: r for c, r in missing.items() if r >= max_missing}
    if over:
        findings.append({"code": "missing_rate", "detail": over})
    declared = {f[0] for f in FEATURE_SPEC}
    undocumented = [c for c in out.columns if c not in declared | {"grid_id", "adm_cd", "gu_code"}]
    if undocumented:
        findings.append({"code": "undocumented_feature", "detail": undocumented})
    if findings:
        raise StageFailed("격자 피처 통과 기준 미달", findings, metrics=m)

    parquet = next(o for o in ctx.outputs if o.suffix == ".parquet")
    parquet.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(parquet, index=False)
    _write_dictionary(
        next(o for o in ctx.outputs if o.suffix == ".md"), out, m,
        fmt=dict(rel_radius=int(rel_radius), sub=int(lat.res / sub),
                 pump_radius=int(pump_radius), sgis_year=sgis_year),
    )
    return m


def _write_dictionary(path: Path, out, m: dict[str, Any], fmt: dict[str, Any]) -> None:
    lines = [
        "# 격자 피처 사전 (data_dictionary)",
        "",
        f"> 생성: `python -m src.pipeline run --only h04_grid_features` · 격자 {m['n_grid']:,}개, 순위 대상(universe) {m['n_universe']:,}개",
        "> 좌표계 EPSG:5179, 100m 격자 = SGIS 격자ID. 산출 코드 `src/data/features.py`, 조립 `src/stages/h04_features.py`.",
        "> 방향: **+** 높을수록 침수 취약 / **−** 낮을수록 취약 / **E** 노출(수) / **·** 참고·플래그. 부호 정렬은 Layer 1 에서 한다.",
        "",
        "| 변수 | 출처 | 단위 | 방향 | 산출 | 결측률(전체) | 결측률(universe) |",
        "|---|---|---|---|---|---:|---:|",
    ]
    missing = m["missing_rate_by_feature"]
    missing_u = m["missing_rate_in_universe"]
    for name, source, unit, sign, method in FEATURE_SPEC:
        mr = f"{missing[name]:.2%}" if name in missing else f"{out[name].isna().mean():.2%}"
        mu = f"{missing_u[name]:.2%}" if name in missing_u else "—"
        lines.append(f"| `{name}` | {source.format(**fmt)} | {unit} | {sign} | {method.format(**fmt)} | {mr} | {mu} |")
    lines += [
        "",
        "## 한계·누수 점검",
        "",
        f"- DEM 원본이 {m['dem_source_res_m']:.0f}m 라 100m 격자에서 경사·TWI 가 평활화된다. 5m DEM 으로 교체 시 이 노드만 재실행.",
        "- `water_dist_m` 은 토지피복 내륙수(710)까지 거리이고, `river_dist_m`·`culvert_dist_m` 은 OSM 하천 중심선까지 거리다. 전자는 폭이 있는 수역만, 후자는 소하천·복개천까지 잡는다.",
        "- 침수예상도는 창원시 모형 산출물이므로 **입력**으로만 쓴다. 침수흔적도(실제 발생)는 검증 전용이며 이 노드의 입력이 아니다.",
        f"- 라벨 자료 사용: {m['label_sources_used'] or '없음'} (침수흔적·민원 미사용).",
        f"- SGIS {fmt['sgis_year']} 가 값을 발행한 격자 {m['sgis_reported_grids']:,}개, 총인구 {m['pop_total_sum']:,}명. 미발행 격자는 0 으로 두고 `sgis_reported` 로 구분.",
        "- 펌프장 `pump_within_km` 은 Layer 1 배수조건 변수다. Layer 3 대응역량에 중복 투입하지 않는다.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
