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
