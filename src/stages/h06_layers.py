"""H06 Layer 1 침수취약성 — 기후노출(IDW 강수) × 도시민감도(지형·피복·배수).

근거: 국토부 「도시 기후변화 재해취약성분석 지침」(100m 격자, 노출×민감도, z-score 합산,
Jenks 4등급 매트릭스). 계산은 `src/data/interpolate.py`·`src/data/layers.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.data.interpolate import EXPOSURE_VARIABLES
from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT

EXPOSURE_SPEC: dict[str, int] = {name: +1 for name in EXPOSURE_VARIABLES}

# 부호: +1 = 값이 클수록 침수 취약, -1 = 값이 작을수록 취약
SENSITIVITY_SPEC: dict[str, int] = {
    "rel_elev_m": -1,              # 주변보다 낮으면 물이 모인다
    "slope_deg": -1,               # 평평하면 배수가 느리다
    "twi": +1,                     # 지형상 물이 모이는 정도
    "impervious_frac": +1,         # 불투수면이 많으면 유출이 빠르다
    "river_proximity": +1,         # 하천 300m 이내 근접도
    "flood_l210_100_depth_m": +1,  # 창원시 내수침수 예상 침수심 (모형 산출물 = 입력)
    "pump_within_km": +1,          # 배수펌프장 서비스권 = 자연배수 불가지역의 행정적 인정
}
# 하천 근접·침수예상도를 뺀 민감도. 홍재주 외(2015)가 지적한 '하천 인접도에 따른 I등급 과다'와
# 예상도 의존을 확인하는 제외 민감도 (ANALYSIS_PLAN §2-1·2-3).
EXCLUDED_FOR_ROBUSTNESS = ("river_proximity", "flood_l210_100_depth_m")

# 선행연구(최유라·한우석 2024) 현장조사 사례지. 독립 성능검증이 아니라 face-validity 점검이다.
CASE_STUDY_DONG = ("양덕동", "봉암동", "팔용동", "명서동", "사화동")
DONG_NAME_FILE = "data/external/adm_dong_names.csv"


def _load_dong_names() -> dict[str, str] | None:
    """행정동 코드 → 이름. 아직 확보하지 못했으면 None (사례지 점검을 건너뛴다)."""
    import pandas as pd

    path = PROJECT_ROOT / DONG_NAME_FILE
    if not path.exists():
        return None
    table = pd.read_csv(path, encoding="utf-8-sig", dtype={"adm_cd": str})
    return dict(zip(table["adm_cd"], table["adm_name"]))


def layer1_flood(ctx: StageContext) -> dict[str, Any]:
    """통과: IDW 에 쓴 지점 ≥ params.min_idw_stations_per_event, 등급 4개가 모두 나타남,
    L1 결측 0. 사례지 lift 와 침수흔적 AUC 는 자료가 있을 때만 판정하고, 없으면
    `case_study_available` / `label_available` 을 false 로 남긴다 (성능 주장 금지)."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from scipy.stats import spearmanr

    from src.data import flood_traces as FT
    from src.data import interpolate as I
    from src.data import layers as L

    p = ctx.params
    n_classes = int(p["layer1.n_classes"])
    winsor = (float(p["layer1.winsor_lo"]), float(p["layer1.winsor_hi"]))
    min_stations = int(p["analysis.min_idw_stations_per_event"])

    features = pd.read_parquet(PROJECT_ROOT / "data/processed/features/grid_features.parquet")
    grid = gpd.read_file(PROJECT_ROOT / "data/processed/spatial/grid_base.gpkg", layer="grid")
    df = gpd.GeoDataFrame(
        features.merge(grid[["grid_id", "geometry"]], on="grid_id", how="left"),
        geometry="geometry", crs=p["analysis.canonical_crs"],
    )
    m: dict[str, Any] = {"n_grid": int(len(df)), "n_universe": int(df["universe"].sum())}

    # ── 기후노출: 지점 통계 → IDW ──────────────────────────────────────────
    stations = gpd.read_file(PROJECT_ROOT / "data/processed/spatial/stations.gpkg", layer="stations")
    cohort = stations[(stations["station_type"] == "rain") & stations["in_rain_cohort"]]
    station_xy = pd.DataFrame({
        "station_code": cohort["station_code"].to_numpy(),
        "x": cohort.geometry.x.to_numpy(),
        "y": cohort.geometry.y.to_numpy(),
    })
    rain = pd.read_parquet(
        PROJECT_ROOT / "data/processed/canonical/rainfall_hourly.parquet",
        columns=["station_id", "obs_date", "observed_at", "rainfall_mm", "quality_flag"],
    )
    exposure = I.station_exposure(
        rain,
        pd.Timestamp(p["analysis.climatology_start"]),
        pd.Timestamp(p["analysis.climatology_end"]),
        station_ids=station_xy["station_code"].tolist(),
    )
    centroids = df.geometry.centroid
    grids, idw_meta = I.interpolate_to_grid(
        station_xy, exposure, np.column_stack([centroids.x, centroids.y]),
        variables=EXPOSURE_VARIABLES,
        powers=p["layer1.idw_powers"], k=int(p["layer1.idw_k"]), max_dist=float(p["layer1.idw_max_dist_m"]),
    )
    for name, values in grids.items():
        df[name] = values
    m["idw"] = idw_meta
    m["min_idw_stations_required"] = min_stations

    # ── 도시민감도 ───────────────────────────────────────────────────────
    df["river_proximity"] = np.maximum(0.0, 1.0 - df["water_dist_m"] / float(p["layer1.river_proximity_m"]))

    z_exposure, exposure_detail = L.composite(df, EXPOSURE_SPEC, winsor_lo=winsor[0], winsor_hi=winsor[1])
    z_sensitivity, sensitivity_detail = L.composite(df, SENSITIVITY_SPEC, winsor_lo=winsor[0], winsor_hi=winsor[1])
    df["z_exposure"] = z_exposure
    df["z_sensitivity"] = z_sensitivity
    df["L1"] = L.minmax(z_exposure + z_sensitivity)

    exposure_breaks = L.jenks_breaks(z_exposure, n_classes)
    sensitivity_breaks = L.jenks_breaks(z_sensitivity, n_classes)
    df["exposure_class"] = L.classify(z_exposure, exposure_breaks)
    df["sensitivity_class"] = L.classify(z_sensitivity, sensitivity_breaks)
    df["vulnerability_class"] = L.vulnerability_class(df["exposure_class"], df["sensitivity_class"])
    df["vulnerability_grade"] = pd.Series(df["vulnerability_class"]).map(L.ROMAN)

    m["composite"] = {"exposure": exposure_detail, "sensitivity": sensitivity_detail}
    m["jenks_breaks"] = {
        "exposure": [round(v, 4) for v in exposure_breaks],
        "sensitivity": [round(v, 4) for v in sensitivity_breaks],
    }
    m["class_counts"] = {
        L.ROMAN[c]: int((df["vulnerability_class"] == c).sum()) for c in sorted(L.ROMAN)
    }
    m["class_counts_universe"] = {
        L.ROMAN[c]: int(((df["vulnerability_class"] == c) & (df["universe"] == 1)).sum()) for c in sorted(L.ROMAN)
    }

    # ── 검증 (a) 하천·예상도 제외 민감도 ────────────────────────────────────
    reduced_spec = {k: v for k, v in SENSITIVITY_SPEC.items() if k not in EXCLUDED_FOR_ROBUSTNESS}
    z_reduced, _ = L.composite(df, reduced_spec, winsor_lo=winsor[0], winsor_hi=winsor[1])
    l1_reduced = L.minmax(z_exposure + z_reduced)
    universe = df["universe"].to_numpy().astype(bool)
    rho = float(spearmanr(df["L1"].to_numpy()[universe], l1_reduced[universe]).statistic)
    m["exclusion_sensitivity"] = {
        "excluded": list(EXCLUDED_FOR_ROBUSTNESS),
        "spearman_rho_universe": round(rho, 4),
        "note": "하천 근접·침수예상도를 뺐을 때 순위가 얼마나 유지되는가 (홍재주 외 2015)",
    }

    # ── 검증 (b) 사례지 face-validity ──────────────────────────────────────
    names = _load_dong_names()
    if names is None:
        m["case_study"] = {"available": False, "reason": f"{DONG_NAME_FILE} 없음 — 행정동 코드-이름 매핑 미확보"}
    else:
        df["adm_name"] = df["adm_cd"].map(names)
        found = sorted({n for n in CASE_STUDY_DONG if (df["adm_name"] == n).any()})
        in_case = df["adm_name"].isin(CASE_STUDY_DONG).to_numpy()
        high = df["vulnerability_class"].isin([1, 2]).to_numpy()
        base = float(high[universe].mean())
        share = float(high[universe & in_case].mean()) if (universe & in_case).any() else float("nan")
        m["case_study"] = {
            "available": True,
            "dong_found": found,
            "dong_missing": sorted(set(CASE_STUDY_DONG) - set(found)),
            "n_grid": int((universe & in_case).sum()),
            "high_grade_share": round(share, 4),
            "base_rate": round(base, 4),
            "lift": round(share / base, 3) if base > 0 else None,
            "lift_min": float(p["layer1.case_study_lift_min"]),
            "note": "선행연구 사례지는 독립 성능검증이 아니라 face-validity 점검이다 (하네스 §7)",
        }

    # ── 검증 (c) 침수흔적 라벨 ─────────────────────────────────────────────
    vectors, images = FT.find_files(PROJECT_ROOT / "data/raw/flood_traces")
    if not vectors:
        m["label_available"] = False
        m["label_note"] = (
            f"침수흔적 벡터 자료 없음 (그림 파일 {len(images)}개). 예측 성능을 주장하지 않는다. "
            "2026-09-14 정보공개 회신분 수령 후 이 노드만 재실행한다"
        )
    else:
        traces, trace_meta = FT.load(vectors, crs=p["analysis.canonical_crs"])
        labels, overlap = FT.label_grid(df, traces)
        df["trace_overlap"] = overlap
        df["trace_label"] = labels.astype("int8")
        scores = df["L1"].to_numpy()
        m["label_available"] = True
        m["trace"] = {
            **trace_meta,
            "n_labelled_grid": int(labels.sum()),
            "auc": round(L.roc_auc(labels[universe], scores[universe]), 4),
            "auc_min": float(p["layer1.trace_auc_min"]),
            "top20pct": L.top_share_lift(labels[universe], scores[universe], 0.20),
            "capture_min": float(p["layer1.trace_top20_capture_min"]),
        }

    # ── 통과 판정 ─────────────────────────────────────────────────────────
    findings: list[dict[str, Any]] = []
    if idw_meta["min_stations_used"] < min_stations:
        findings.append({
            "code": "too_few_idw_stations",
            "detail": f"{idw_meta['min_stations_used']} < {min_stations}",
        })
    if int(df["L1"].isna().sum()):
        findings.append({"code": "l1_missing", "detail": int(df["L1"].isna().sum())})
    if len(m["class_counts"]) != n_classes or min(m["class_counts"].values()) == 0:
        findings.append({"code": "empty_class", "detail": m["class_counts"]})
    if m.get("label_available") and m["trace"]["auc"] < m["trace"]["auc_min"]:
        findings.append({"code": "trace_auc", "detail": f"{m['trace']['auc']} < {m['trace']['auc_min']}"})
    if findings:
        raise StageFailed("Layer 1 통과 기준 미달", findings, metrics=m)

    columns = [
        "grid_id", "adm_cd", "gu_code", "universe",
        *EXPOSURE_VARIABLES, "river_proximity",
        "z_exposure", "z_sensitivity", "exposure_class", "sensitivity_class",
        "vulnerability_class", "vulnerability_grade", "L1", "geometry",
    ]
    if "trace_label" in df.columns:
        columns[-1:-1] = ["trace_overlap", "trace_label"]
    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    df[columns].to_file(out, layer="layer1_flood", driver="GPKG")
    _layer1_map(df, PROJECT_ROOT / "reports/figures/layer1_map.png")
    return m


def _layer1_map(df, out: Path) -> None:
    """G007 증거용 4면 지도. 데이터 산출물이 아니므로 outputs 에 넣지 않는다."""
    import matplotlib.pyplot as plt

    from src.visualization import style

    style.apply()
    fig, axes = plt.subplots(2, 2, figsize=(13, 11))
    panels = [
        ("z_exposure", "기후노출 (IDW 강수 z-score 합)", dict(cmap="YlOrRd")),
        ("z_sensitivity", "도시민감도 (지형·피복·배수 z-score 합)", dict(cmap="YlGnBu")),
        ("vulnerability_class", "침수취약성 등급 (I 이 가장 취약)", dict(cmap="RdYlGn", vmin=1, vmax=4)),
        ("L1", "Layer 1 침수취약성 지수 (0~1)", dict(cmap="magma_r")),
    ]
    for ax, (col, title, kw) in zip(axes.ravel(), panels):
        df.plot(column=col, ax=ax, linewidth=0, legend=True, legend_kwds={"shrink": 0.6}, **kw)
        ax.set_title(title, fontsize=10)
        ax.set_axis_off()
        ax.grid(False)
    fig.tight_layout()
    style.save(fig, out)


# ── Layer 3 취약계층·노출·대응역량 ─────────────────────────────────────────
# V(취약성)는 **비율**, E(노출)는 **수**로 나눈다 (ANALYSIS_PLAN §4 이중계산 방지).
LAYER3_VULNERABILITY_SPEC: dict[str, int] = {"elderly_ratio": +1}
LAYER3_EXPOSURE_SPEC: dict[str, int] = {"pop_total": +1, "houses": +1}
# 아직 확보하지 못해 V 에서 빠진 변수. 보고서 한계와 metrics 에 그대로 남긴다.
LAYER3_MISSING_VARIABLES = {
    "one_person_household_ratio": "SGIS 1인가구 미보유 (100m·집계구 모두)",
    "old_building_ratio": "GIS건물통합정보 SHP 미확보 (V-World 키 필요)",
    "basement_building_count": "건축물대장 지하층수 미확보 (건축HUB 키 필요)",
}


def layer3_vuln(ctx: StageContext) -> dict[str, Any]:
    """통과: 65세 이상은 확정된 연령 코드북으로만 파생, 집계구 조인율·결측률 기록,
    대응역량은 높을수록 좋은 방향으로 정규화한 뒤 capacity_deficit = 1 - capacity_norm."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from scipy.spatial import cKDTree

    from src.data import layers as L
    from src.data import sgis, shelters

    p = ctx.params
    n_classes = int(p["layer1.n_classes"])
    winsor = (float(p["layer1.winsor_lo"]), float(p["layer1.winsor_hi"]))
    capacity_max = float(p["layer3.capacity_max_dist_m"])
    year = int(p["features.sgis_year"])

    features = pd.read_parquet(PROJECT_ROOT / "data/processed/features/grid_features.parquet")
    grid = gpd.read_file(PROJECT_ROOT / "data/processed/spatial/grid_base.gpkg", layer="grid")
    df = gpd.GeoDataFrame(
        features[["grid_id", "adm_cd", "gu_code", "universe", "pop_total", "households", "houses"]]
        .merge(grid[["grid_id", "geometry"]], on="grid_id", how="left"),
        geometry="geometry", crs=p["analysis.canonical_crs"],
    )
    m: dict[str, Any] = {"n_grid": int(len(df)), "n_universe": int(df["universe"].sum())}

    # 65세 이상 비율: 집계구에서 구해 격자 중심점이 속한 집계구 값을 붙인다.
    aggregation = pd.read_parquet(PROJECT_ROOT / "data/processed/canonical/sgis_aggregation.parquet")
    elderly = sgis.elderly_ratio(aggregation, year)
    shapes = sorted((PROJECT_ROOT / "data/raw/sgis/aggregation_boundaries_2025_2Q").glob("*.shp"))
    boundaries = pd.concat([gpd.read_file(q) for q in shapes], ignore_index=True)
    boundaries = gpd.GeoDataFrame(boundaries, geometry="geometry", crs=boundaries.crs).to_crs(df.crs)
    boundaries["spatial_id"] = boundaries["TOT_OA_CD"].astype(str)
    centroids = gpd.GeoDataFrame({"grid_id": df["grid_id"]}, geometry=df.geometry.centroid, crs=df.crs)
    joined = gpd.sjoin(centroids, boundaries[["spatial_id", "geometry"]], predicate="within", how="left")
    joined = joined.drop_duplicates(subset="grid_id")[["grid_id", "spatial_id"]]
    df = df.merge(joined, on="grid_id", how="left").merge(
        elderly[["spatial_id", "elderly_ratio", "pop_elderly", "pop_age_total"]], on="spatial_id", how="left"
    )
    universe = df["universe"].to_numpy().astype(bool)
    first_elderly_col = sgis.age_columns(sgis.AGE_BLOCK_TOTAL, min_age=sgis.ELDERLY_FROM_AGE)[0]
    m["elderly"] = {
        "age_codebook": f"in_age 5세 계급, {sgis.ELDERLY_FROM_AGE}세 이상 = {first_elderly_col} 이후",
        "codebook_verified": "노령화지수(to_in_004) 항등식 대조 — src/data/sgis.py 주석",
        "n_aggregation_units": int(len(elderly)),
        "join_rate_all": round(float(df["spatial_id"].notna().mean()), 4),
        "join_rate_universe": round(float(df.loc[universe, "spatial_id"].notna().mean()), 4),
        "missing_ratio_universe": round(float(df.loc[universe, "elderly_ratio"].isna().mean()), 4),
        "city_elderly_share": round(float(elderly["pop_elderly"].sum() / elderly["pop_age_total"].sum()), 4),
        # 단순평균은 면적이 넓은 농촌 집계구가 격자를 많이 차지해 부풀려진다(0.32).
        # 시 전체와 대조할 수 있는 것은 인구가중 평균이다.
        "grid_pop_weighted_universe": round(
            float((df.loc[universe, "elderly_ratio"] * df.loc[universe, "pop_total"]).sum()
                  / df.loc[universe, "pop_total"].sum()), 4
        ),
        "grid_unweighted_mean_universe": round(float(df.loc[universe, "elderly_ratio"].mean()), 4),
        "grids_per_aggregation_unit": {
            "median": float(df.loc[universe].groupby("spatial_id").size().median()),
            "max": int(df.loc[universe].groupby("spatial_id").size().max()),
            "note": "집계구 하나가 격자 여러 개에 같은 비율을 준다 — 배분 불확실성 (ANALYSIS_PLAN §4)",
        },
    }
    # 집계구에 걸치지 못한 격자는 구 중앙값으로 채우고 플래그를 남긴다 (0 대체 금지).
    df["elderly_imputed"] = df["elderly_ratio"].isna().astype("int8")
    df["elderly_ratio"] = df["elderly_ratio"].fillna(
        df.groupby("gu_code")["elderly_ratio"].transform("median")
    ).fillna(df["elderly_ratio"].median())

    # 대응역량: 대피장소·방재기관 최근접 거리 → 가까울수록 1
    points, shelter_meta = shelters.load(
        sorted((PROJECT_ROOT / "data/raw/shelters").glob("*.json")), crs=p["analysis.canonical_crs"]
    )
    cent_xy = np.column_stack([df.geometry.centroid.x, df.geometry.centroid.y])
    for kind, column in (("shelter", "shelter_dist_m"), ("facility", "facility_dist_m")):
        sub = points[points["kind"] == kind]
        tree = cKDTree(np.column_stack([sub.geometry.x, sub.geometry.y]))
        df[column] = tree.query(cent_xy)[0]
    df["capacity_norm"] = 1.0 - np.mean(
        [np.minimum(df["shelter_dist_m"], capacity_max) / capacity_max,
         np.minimum(df["facility_dist_m"], capacity_max) / capacity_max], axis=0
    )
    df["capacity_deficit"] = 1.0 - df["capacity_norm"]
    m["capacity"] = {
        **shelter_meta,
        "max_dist_m": capacity_max,
        "shelter_dist_median_universe": round(float(df.loc[universe, "shelter_dist_m"].median()), 1),
        "facility_dist_median_universe": round(float(df.loc[universe, "facility_dist_m"].median()), 1),
        "capacity_deficit_mean_universe": round(float(df.loc[universe, "capacity_deficit"].mean()), 4),
        "note": "펌프장 거리는 Layer 1 배수조건으로 이미 썼으므로 대응역량에서 제외 (하네스 §7 이중투입 금지)",
    }

    # E(노출, 수) · V(취약성, 비율)
    z_exposure, exposure_detail = L.composite(df, LAYER3_EXPOSURE_SPEC, winsor_lo=winsor[0], winsor_hi=winsor[1])
    z_vulnerability, vulnerability_detail = L.composite(
        df, LAYER3_VULNERABILITY_SPEC, winsor_lo=winsor[0], winsor_hi=winsor[1]
    )
    df["E"] = L.minmax(z_exposure)
    df["V"] = L.minmax(z_vulnerability)
    df["L3"] = df["V"]
    breaks = L.jenks_breaks(df.loc[universe, "V"].to_numpy(), n_classes)
    df["l3_class"] = L.classify(df["V"].to_numpy(), breaks)
    m["composite"] = {"exposure": exposure_detail, "vulnerability": vulnerability_detail}
    m["jenks_breaks_v_universe"] = [round(v, 4) for v in breaks]
    m["class_counts_universe"] = {
        int(c): int(((df["l3_class"] == c) & universe).sum()) for c in range(1, n_classes + 1)
    }
    m["missing_variables"] = LAYER3_MISSING_VARIABLES
    m["n_vulnerability_variables"] = len(LAYER3_VULNERABILITY_SPEC)

    findings: list[dict[str, Any]] = []
    if m["elderly"]["join_rate_universe"] < 0.95:
        findings.append({"code": "aggregation_join", "detail": m["elderly"]["join_rate_universe"]})
    if int(df.loc[universe, ["E", "V", "capacity_deficit"]].isna().sum().sum()):
        findings.append({"code": "layer3_missing", "detail": "E·V·capacity_deficit 에 결측"})
    if findings:
        raise StageFailed("Layer 3 통과 기준 미달", findings, metrics=m)

    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    df[[
        "grid_id", "adm_cd", "gu_code", "universe", "pop_total", "households", "houses",
        "spatial_id", "elderly_ratio", "elderly_imputed",
        "shelter_dist_m", "facility_dist_m", "capacity_norm", "capacity_deficit",
        "E", "V", "L3", "l3_class", "geometry",
    ]].to_file(out, layer="layer3_vuln", driver="GPKG")
    _layer3_map(df, PROJECT_ROOT / "reports/figures/layer3_map.png")
    return m


def _layer3_map(df, out: Path) -> None:
    import matplotlib.pyplot as plt

    from src.visualization import style

    style.apply()
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    panels = [
        ("E", "노출 E (인구·주택 수)", dict(cmap="magma_r")),
        ("V", "취약성 V (65세 이상 비율)", dict(cmap="YlOrBr")),
        ("capacity_deficit", "대응역량 부족도 (대피소·방재기관 거리)", dict(cmap="PuBu")),
    ]
    for ax, (col, title, kw) in zip(axes, panels):
        df.plot(column=col, ax=ax, linewidth=0, legend=True, legend_kwds={"shrink": 0.6}, **kw)
        ax.set_title(title, fontsize=10)
        ax.set_axis_off()
        ax.grid(False)
    fig.tight_layout()
    style.save(fig, out)
