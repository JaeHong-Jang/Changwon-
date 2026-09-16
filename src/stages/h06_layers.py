"""H06 Layer 1 침수취약성 · Layer 3 취약계층·대응역량.

Layer 1 은 국토부 「도시 기후변화 재해취약성분석 지침」 구조를 따른다 —
기후노출(IDW 강수) × 도시민감도(지형·피복·배수) → z-score 합산 → Jenks 4등급 매트릭스.
Layer 3 은 사람 쪽을 노출 E(수)·취약성 V(비율)·대응역량 부족도 D 로 나눈다.

이 파일은 **단계를 조립**한다. 계산은 `src/data/` 의 모듈이 한다
(interpolate 보간, layers 정규화·집계, sgis 연령, shelters 대피시설, flood_traces 검증 라벨).
아래 `_` 함수들은 러너가 길어져 읽기 어려워지는 것을 막으려고 단계별로 끊은 것이며,
각각 "무엇을 구하는가" 하나에만 답한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.data.interpolate import EXPOSURE_VARIABLES
from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT

EXPOSURE_SPEC: dict[str, int] = {name: +1 for name in EXPOSURE_VARIABLES}

# 부호: +1 = 값이 클수록 침수 취약, -1 = 값이 작을수록 취약.
# 계산 **전에** 물리적 근거로 고정하며 결과를 보고 바꾸지 않는다.
SENSITIVITY_SPEC: dict[str, int] = {
    "rel_elev_m": -1,              # 주변보다 낮으면 물이 모인다
    "slope_deg": -1,               # 평평하면 배수가 느리다
    "twi": +1,                     # 지형상 물이 모이는 정도
    "impervious_frac": +1,         # 불투수면이 많으면 유출이 빠르다
    "river_proximity": +1,         # 하천 중심선(OSM) 근접도
    "culvert_proximity": +1,       # 복개천 근접도 — 최유라·한우석(2024) 창원 피해 가중요인
    "flood_l210_100_depth_m": +1,  # 창원시 내수침수 예상 침수심 (모형 산출물 = 입력)
    "pump_within_km": +1,          # 배수펌프장 서비스권 = 자연배수 불가지역의 행정적 인정
}
# 하천·복개·예상도를 뺀 민감도로 다시 계산해 순위가 유지되는지 본다.
# 홍재주 외(2015)가 지적한 '하천 인접도에 따른 I등급 과다'와 예상도 의존을 확인하는 점검이다.
EXCLUDED_FOR_ROBUSTNESS = ("river_proximity", "culvert_proximity", "flood_l210_100_depth_m")
# 창원시 침수예상도에서 온 변수. 이것만 빼고 다시 채점하면 '우리가 더한 것'이 분리된다.
FLOOD_MAP_VARIABLES = ("flood_l210_100_depth_m",)

# 선행연구(최유라·한우석 2024) 현장조사 사례지. 독립 성능검증이 아니라 face-validity 점검이다.
# 논문은 **법정동** 이름을 쓰고 우리 경계는 **행정동**이라 1:1 로 대응하지 않는다.
# 대응이 확인된 것만 넣는다. 명서동·사화동은 관할 행정동을 확인하지 못해 제외했다.
CASE_STUDY_MAPPING = {
    "양덕동": ("양덕1동", "양덕2동"),
    "봉암동": ("봉암동",),
    "팔용동": ("팔룡동",),        # 법정동 팔용동 = 행정동 팔룡동
}
CASE_STUDY_UNMATCHED = ("명서동", "사화동")
CASE_STUDY_DONG = tuple(n for names in CASE_STUDY_MAPPING.values() for n in names)
DONG_NAME_FILE = "data/external/adm_dong_names.csv"
TRACE_DIR = "data/raw/flood_traces"
EVENT_LABEL_PREFIX = "trace_ev_"   # 사상(연도)별 침수 라벨 열 이름 앞머리
# 침수흔적 격자가 왜 그 점수를 받았는지 설명할 때 보는 변수
DIAGNOSIS_COLUMNS = ["elev_m", "slope_deg", "twi", "impervious_frac",
                     "flood_l210_100_frac", "pump_dist_m", "pop_total"]

# 도시성은 **중앙값으로 요약하면 안 된다**. 불투수면 같은 변수는 0 에 몰린 양봉분포라,
# 절반을 조금 넘는 칸이 0 이면 중앙값이 0 이 되어 "전부 농경지"처럼 보인다. 실제로는
# 절반이 시가지일 수 있다. 그래서 "조건을 만족하는 칸의 **비율**"로 함께 낸다.
URBANNESS_SHARES = {
    "impervious_gt0": ("impervious_frac", lambda v: v > 0),
    "flood_map_gt0": ("flood_l210_100_frac", lambda v: v > 0),
    "pump_within_1km": ("pump_dist_m", lambda v: v <= 1000),
    "river_within_200m": ("river_dist_m", lambda v: v <= 200),
}


def _load_grid_features(crs: str):
    """격자 피처에 도형을 붙인다. Layer 1·3 의 공통 출발점이다."""
    import geopandas as gpd
    import pandas as pd

    features = pd.read_parquet(PROJECT_ROOT / "data/processed/features/grid_features.parquet")
    grid = gpd.read_file(PROJECT_ROOT / "data/processed/spatial/grid_base.gpkg", layer="grid")
    return gpd.GeoDataFrame(
        features.merge(grid[["grid_id", "geometry"]], on="grid_id", how="left"),
        geometry="geometry", crs=crs,
    )


def _load_dong_names() -> dict[str, str] | None:
    """행정동 코드 → 이름. 아직 확보하지 못했으면 None (사례지 점검을 건너뛴다)."""
    import pandas as pd

    path = PROJECT_ROOT / DONG_NAME_FILE
    if not path.exists():
        return None
    table = pd.read_csv(path, encoding="utf-8-sig", dtype={"adm_cd": str})
    return dict(zip(table["adm_cd"], table["adm_name"]))


def _climate_exposure(df, p) -> dict[str, Any]:
    """관측지점 강수 통계를 격자로 보간해 df 에 붙인다. 보간 메타를 돌려준다.

    지점 cohort 는 h03_stations 가 표시해 둔 `in_rain_cohort` 를 따른다.
    """
    import geopandas as gpd
    import numpy as np
    import pandas as pd

    from src.data import interpolate as I

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
    grids, meta = I.interpolate_to_grid(
        station_xy, exposure, np.column_stack([centroids.x, centroids.y]),
        variables=EXPOSURE_VARIABLES,
        powers=p["layer1.idw_powers"], k=int(p["layer1.idw_k"]),
        max_dist=float(p["layer1.idw_max_dist_m"]),
    )
    for name, values in grids.items():
        df[name] = values
    return meta


def _add_proximity(df, radius_m: float) -> None:
    """하천·복개천 근접도를 만든다. 거리를 0~1 근접도로 뒤집어야 부호가 다른 변수와 합산된다."""
    import numpy as np

    df["river_proximity"] = np.maximum(0.0, 1.0 - df["river_dist_m"] / radius_m)
    # 복개 구간이 없는 지역은 거리가 결측이다. 근접도 0(먼 것)으로 두는 것이 맞다.
    df["culvert_proximity"] = np.maximum(0.0, 1.0 - df["culvert_dist_m"] / radius_m).fillna(0.0)


def _classify_layer1(df, z_exposure, z_sensitivity, n_classes: int) -> dict[str, Any]:
    """두 축을 각각 Jenks 등급으로 나누고 매트릭스로 취약성 I~IV 를 준다 (지침 구조)."""
    import pandas as pd

    from src.data import layers as L

    exposure_breaks = L.jenks_breaks(z_exposure, n_classes)
    sensitivity_breaks = L.jenks_breaks(z_sensitivity, n_classes)
    df["exposure_class"] = L.classify(z_exposure, exposure_breaks)
    df["sensitivity_class"] = L.classify(z_sensitivity, sensitivity_breaks)
    df["vulnerability_class"] = L.vulnerability_class(df["exposure_class"], df["sensitivity_class"])
    df["vulnerability_grade"] = pd.Series(df["vulnerability_class"]).map(L.ROMAN)

    universe = df["universe"] == 1
    return {
        "jenks_breaks": {
            "exposure": [round(v, 4) for v in exposure_breaks],
            "sensitivity": [round(v, 4) for v in sensitivity_breaks],
        },
        "class_counts": {L.ROMAN[c]: int((df["vulnerability_class"] == c).sum()) for c in sorted(L.ROMAN)},
        "class_counts_universe": {
            L.ROMAN[c]: int(((df["vulnerability_class"] == c) & universe).sum()) for c in sorted(L.ROMAN)
        },
    }


def _exclusion_sensitivity(df, z_exposure, universe, winsor) -> dict[str, Any]:
    """하천·복개·예상도를 빼고 다시 계산했을 때 순위가 얼마나 유지되는가."""
    from scipy.stats import spearmanr

    from src.data import layers as L

    reduced_spec = {k: v for k, v in SENSITIVITY_SPEC.items() if k not in EXCLUDED_FOR_ROBUSTNESS}
    z_reduced, _ = L.composite(df, reduced_spec, winsor_lo=winsor[0], winsor_hi=winsor[1])
    reduced = L.minmax(z_exposure + z_reduced)
    rho = float(spearmanr(df["L1"].to_numpy()[universe], reduced[universe]).statistic)
    return {
        "excluded": list(EXCLUDED_FOR_ROBUSTNESS),
        "spearman_rho_universe": round(rho, 4),
        "note": "하천 근접·복개·침수예상도를 뺐을 때 순위가 얼마나 유지되는가 (홍재주 외 2015)",
    }


def _case_study_check(df, universe, lift_min: float) -> dict[str, Any]:
    """선행연구 현장조사 사례지가 우리 지도에서도 높은 등급인가 (face-validity)."""
    names = _load_dong_names()
    if names is None:
        return {"available": False, "reason": f"{DONG_NAME_FILE} 없음 — 행정동 코드-이름 매핑 미확보"}

    df["adm_name"] = df["adm_cd"].map(names)
    found = sorted({n for n in CASE_STUDY_DONG if (df["adm_name"] == n).any()})
    in_case = df["adm_name"].isin(CASE_STUDY_DONG).to_numpy()
    high = df["vulnerability_class"].isin([1, 2]).to_numpy()
    base = float(high[universe].mean())
    share = float(high[universe & in_case].mean()) if (universe & in_case).any() else float("nan")
    return {
        "available": True,
        "mapping": {k: list(v) for k, v in CASE_STUDY_MAPPING.items()},
        "unmatched_legal_dong": list(CASE_STUDY_UNMATCHED),
        "dong_found": found,
        "dong_missing": sorted(set(CASE_STUDY_DONG) - set(found)),
        "n_grid": int((universe & in_case).sum()),
        "high_grade_share": round(share, 4),
        "base_rate": round(base, 4),
        "lift": round(share / base, 3) if base > 0 else None,
        "lift_min": lift_min,
        "note": "선행연구 사례지는 독립 성능검증이 아니라 face-validity 점검이다 (하네스 §7)",
    }


def _time_split_labels(df, traces, min_overlap: float, cal_share: float) -> dict[str, Any]:
    """사상을 연도 시간순으로 나눠 앞뒤 라벨을 따로 붙인다. 분할 내역을 돌려준다.

    등급 경계를 침수흔적으로 맞추고 **같은** 흔적으로 검증하면 in-sample 순환이 된다
    (CDRI_GRADE_SYSTEM §1③, 지적사항 3). 앞 사상으로 경계를 정하고 뒤 사상으로 검증하면
    그 순환이 끊긴다.

    분할 기준은 결과를 보기 전에 정한 규칙이다 — **연도를 시간순으로 세워 앞 cal_share 를
    캘리브레이션, 나머지를 검증**으로 한다. 홀수면 여분을 캘리브레이션 쪽에 준다.
    창원 기록은 연도마다 사상이 정확히 하나씩이라 연도 분할이 곧 사상 분할이다.
    """
    from src.data import flood_traces as FT

    years = sorted(y for y in traces["event_year"].dropna().unique())
    n_cal = max(1, int(round(len(years) * cal_share)))
    cal_years, val_years = years[:n_cal], years[n_cal:]

    split = {"years": years, "calibration_years": cal_years, "validation_years": val_years}
    for name, subset in (("cal", cal_years), ("val", val_years)):
        if not subset:
            df[f"trace_label_{name}"] = 0
            split[f"n_{name}"] = 0
            continue
        labels, _ = FT.label_grid(df, traces[traces["event_year"].isin(subset)], min_overlap=min_overlap)
        df[f"trace_label_{name}"] = labels.astype("int8")
        split[f"n_{name}"] = int(labels.sum())
    # 사상 단위 교차검증(LOEO)은 사상마다 라벨이 따로 있어야 한다. 연도가 곧 사상이다.
    split["event_columns"] = []
    for year in years:
        labels, _ = FT.label_grid(df, traces[traces["event_year"] == year], min_overlap=min_overlap)
        column = f"{EVENT_LABEL_PREFIX}{year}"
        df[column] = labels.astype("int8")
        split["event_columns"].append(column)
    # 두 쪽 모두 양성이 있어야 캘리브레이션-검증 분리가 성립한다.
    split["usable"] = bool(split["n_cal"] and split["n_val"])
    split["n_both"] = int((df["trace_label_cal"].to_numpy() & df["trace_label_val"].to_numpy()).sum())
    return split


def _urbanness(frame) -> dict[str, float]:
    """도시성 지표를 '조건을 만족하는 칸의 비율'로 낸다.

    중앙값을 쓰면 안 되는 이유는 `URBANNESS_SHARES` 주석에 적었다. 비율로 내면
    창원 전체와 바로 견줄 수 있어 "이 사상이 평균보다 도시적인가"를 판단할 수 있다.
    """
    return {
        name: round(float(test(frame[column]).mean()), 3)
        for name, (column, test) in URBANNESS_SHARES.items()
        if column in frame.columns
    }


def _per_event_scores(df, traces, scores, any_label, min_overlap: float) -> list[dict[str, Any]]:
    """사상 하나씩 따로 채점한다. 성능이 특정 호우 한 건에 기대고 있는지 보는 장치다.

    전체를 합쳐 계산한 AUC 는 큰 사상 하나가 좋으면 나머지가 나빠도 높게 나온다.
    사상별로 나눠 보면 그 편중이 드러난다.

    음성은 **어느 사상에서도 잠기지 않은 격자**로 둔다. 다른 사상에서 잠긴 칸을 음성으로
    세면 "맞힌 것"을 틀렸다고 채점하게 된다.
    """
    import numpy as np

    from src.data import flood_traces as FT
    from src.data import layers as L
    from src.data import uncertainty as U

    centroids = df.geometry.centroid
    cx, cy = centroids.x.to_numpy(), centroids.y.to_numpy()
    rows = []
    for year in sorted(traces["event_year"].dropna().unique()):
        subset = traces[traces["event_year"] == year]
        labels, _ = FT.label_grid(df, subset, min_overlap=min_overlap)
        keep = labels | ~any_label            # 이 사상의 양성 + 한 번도 안 잠긴 칸
        n_positive = int(labels.sum())
        row: dict[str, Any] = {
            "event_year": str(year),
            "event_name": (subset["event_name"].dropna().mode().iloc[0]
                           if subset["event_name"].notna().any() else None),
            "n_traces": int(len(subset)),
            "n_positive_grid": n_positive,
        }
        # 양성이 너무 적으면 AUC 가 한두 칸에 좌우되므로 계산하지 않는다.
        if n_positive >= 20:
            row["auc"] = round(L.roc_auc(labels[keep], scores[keep]), 4)
            row["top20pct"] = L.top_share_lift(labels[keep], scores[keep], 0.20)
        else:
            row["note"] = f"양성 {n_positive}칸 < 20칸 — 사상 단독 판정 보류"
        # 같은 라벨을 쓰는 김에 진단값도 여기서 낸다 (공간 조인 재실행 방지).
        flooded = df.loc[labels]
        row["median"] = {c: round(float(flooded[c].median()), 3) for c in DIAGNOSIS_COLUMNS}
        row["urbanness"] = _urbanness(flooded)
        # 사상별 AUC 가 흔들리는 이유를 읽으려면 격자 수가 아니라 덩어리 수를 봐야 한다.
        row["n_cluster"] = U.effective_sample(labels, cx, cy)["n_cluster"]
        row["inland_share"] = (round(float(subset["is_inland"].mean()), 3)
                               if subset["is_inland"].notna().any() else None)
        rows.append(row)
    return rows


def _event_spread(by_event: list[dict[str, Any]], auc_min: float) -> dict[str, Any]:
    """사상별 AUC 가 고르게 나왔는지 요약한다. 합산 지표가 숨기는 편차를 드러낸다.

    합산 AUC 는 큰 사상 하나가 좋으면 높게 나온다. 사상별로 나눠 기준 미달 사상을
    이름으로 적어 두면, 보고서를 쓸 때 그 사실을 빠뜨릴 수 없다.
    """
    scored = {r["event_year"]: r["auc"] for r in by_event if "auc" in r}
    below = sorted(y for y, auc in scored.items() if auc < auc_min)
    return {
        "n_scored": len(scored),
        "min": min(scored.values()) if scored else None,
        "max": max(scored.values()) if scored else None,
        "all_above_min": bool(scored) and not below,
        "events_below_min": below,
        "note": (
            "합산 AUC 는 기준을 넘었으나 사상별로는 갈린다. 미달 사상을 함께 보고하지 않으면 "
            "성능을 과대 진술하게 된다"
            if below else "사상별 AUC 가 모두 기준을 넘었다 — 성능이 한 호우에 기댄 것이 아니다"
        ),
    }


def _incremental_value(df, labels, z_exposure, winsor, centroids) -> dict[str, Any]:
    """우리 지수가 **창원시가 이미 가진 자료에 무엇을 더했는지** 잰다.

    시 침수예상도는 Layer 1 의 입력이다. 그래서 "우리 지수가 실제 침수를 잘 맞혔다"는
    문장에는 시 모형의 성과가 섞여 있다. 세 가지로 분리한다.

    1. **같은 라벨로 세 점수를 채점** — 예상도 단독 / Layer 1 / Layer 1 − 예상도.
       격자마다 1표인 AUC 와 침수 한 건마다 1표인 AUC 를 함께 낸다.
    2. **짝지은 차이** — 두 점수의 신뢰구간이 겹친다고 "차이 없음"이라 하면 틀린다.
       같은 침수로 채점한 두 점수는 강하게 상관돼 있으므로, 같은 재표본에서 차이를 직접 잰다.
    3. **예상도 안/밖 분리** — 예상도가 0 인 구역에서 예상도는 아무 정보도 주지 않는다
       (AUC 0.5). 그 구역에서 우리 지수의 AUC 가 곧 **예상도와 무관한 우리 기여**다.
    """
    from src.data import layers as L
    from src.data import uncertainty as U

    cx, cy = centroids
    depth = df["flood_l210_100_depth_m"].to_numpy(dtype=float)
    without_map = {k: v for k, v in SENSITIVITY_SPEC.items() if k not in FLOOD_MAP_VARIABLES}
    z_reduced, _ = L.composite(df, without_map, winsor_lo=winsor[0], winsor_hi=winsor[1])
    scores = {
        "city_flood_map_only": depth,
        "layer1": df["L1"].to_numpy(dtype=float),
        "layer1_without_flood_map": L.minmax(z_exposure + z_reduced),
    }

    rows = {
        name: {
            "auc": round(L.roc_auc(labels, s), 4),
            "auc_cluster_weighted": round(U.cluster_weighted_auc(labels, s, cx, cy), 4),
            "top20pct_capture": L.top_share_lift(labels, s, 0.20)["capture_rate"],
        }
        for name, s in scores.items()
    }

    strata = {}
    for name, mask in (("outside_city_map", depth <= 0), ("inside_city_map", depth > 0)):
        y = labels[mask]
        strata[name] = {
            "n_grid": int(mask.sum()),
            **U.effective_sample(y, cx[mask], cy[mask]),
            "auc": {k: round(L.roc_auc(y, v[mask]), 4) for k, v in scores.items()} if 0 < y.sum() < y.size else None,
        }
    strata["note"] = (
        "예상도 밖에서는 예상도 점수가 모두 0 이라 AUC 가 0.5 로 고정된다. "
        "그 구역의 Layer 1 AUC 가 예상도와 무관한 우리 기여다"
    )

    return {
        "scores": rows,
        "auc_gain_over_city_map": round(rows["layer1"]["auc"] - rows["city_flood_map_only"]["auc"], 4),
        "paired": U.paired_cluster_bootstrap(labels, scores, "city_flood_map_only", cx, cy),
        "strata": strata,
        "removed_variables": list(FLOOD_MAP_VARIABLES),
        "note": (
            "시 침수예상도는 Layer 1 의 입력이다. 예상도 단독 AUC 와 짝지은 차이를 함께 "
            "보고하지 않으면 시 모형의 성과를 우리 것으로 진술하게 된다"
        ),
    }


def _flood_trace_check(df, universe, p, z_exposure, winsor) -> tuple[dict[str, Any] | None, str | None]:
    """실제 침수 기록으로 Layer 1 을 채점한다. (지표, 안내문) 을 돌려준다.

    표본이 판정에 쓸 만한지를 **먼저** 본다. 양성 격자가 기준 미만이면 AUC 를 참고값으로만
    남기고 성능을 주장하지 않는다 (하네스 H06 '라벨 부족 시 성능 주장 금지로 전환').
    """
    from src.data import flood_traces as FT
    from src.data import layers as L
    from src.data import uncertainty as U

    vectors, images = FT.find_files(PROJECT_ROOT / TRACE_DIR)
    if not vectors:
        return None, f"침수흔적 벡터 자료 없음 (그림 파일 {len(images)}개). 예측 성능을 주장하지 않는다"

    min_overlap = float(p["layer1.trace_min_overlap"])
    min_positive = int(p["layer1.trace_min_positive"])
    traces, meta = FT.load(vectors, crs=p["analysis.canonical_crs"])
    labels, overlap = FT.label_grid(df, traces, min_overlap=min_overlap)
    df["trace_overlap"] = overlap
    df["trace_label"] = labels.astype("int8")
    split = _time_split_labels(df, traces, min_overlap, float(p["layer1.trace_calibration_share"]))

    scores = df["L1"].to_numpy()
    n_all, n_universe = int(labels.sum()), int((labels & universe).sum())
    trace: dict[str, Any] = {
        **meta,
        "min_overlap": min_overlap,
        "n_labelled_grid": n_all,
        "n_labelled_in_universe": n_universe,
        "min_positive_required": min_positive,
        "label_sufficient": n_all >= min_positive,
        "time_split": split,
        "auc_min": float(p["layer1.trace_auc_min"]),
        "capture_min": float(p["layer1.trace_top20_capture_min"]),
    }
    if n_all >= 3:
        # 순위대상만으로는 양성이 적을 수 있어 전 격자 기준을 주지표로 쓴다.
        trace["auc_all_grid"] = round(L.roc_auc(labels, scores), 4)
        trace["top20pct_all_grid"] = L.top_share_lift(labels, scores, 0.20)
        if n_universe >= 3:
            trace["auc_universe"] = round(L.roc_auc(labels[universe], scores[universe]), 4)
            trace["top20pct_universe"] = L.top_share_lift(labels[universe], scores[universe], 0.20)
        trace["by_event"] = _per_event_scores(df, traces, scores, labels, min_overlap)
        trace["event_auc_spread"] = _event_spread(trace["by_event"], trace["auc_min"])
        # 격자 수는 표본 수가 아니다. 유효 표본과 그에 맞는 신뢰구간을 함께 낸다.
        centroids = df.geometry.centroid
        cx, cy = centroids.x.to_numpy(), centroids.y.to_numpy()
        trace["effective_sample"] = U.effective_sample(labels, cx, cy)
        trace["auc_ci"] = U.cluster_bootstrap_auc(labels, scores, cx, cy)
        trace["incremental_value"] = _incremental_value(df, labels, z_exposure, winsor, (cx, cy))
        trace["diagnosis"] = {
            "flooded_median": {c: round(float(df.loc[labels, c].median()), 3) for c in DIAGNOSIS_COLUMNS},
            "city_median": {c: round(float(df[c].median()), 3) for c in DIAGNOSIS_COLUMNS},
            # 사상별 비율을 견줄 대조군. 이게 없으면 "0.271 이 높은 건가 낮은 건가"를 알 수 없다.
            "flooded_urbanness": _urbanness(df.loc[labels]),
            "city_urbanness": _urbanness(df),
            "n_covered_by_city_flood_map": int((df.loc[labels, "flood_l210_100_frac"] > 0).sum()),
            "note": "시 침수예상도가 이 격자들을 잡았는지 보면, 점수가 낮은 이유가 우리 지수만의 문제인지 알 수 있다",
        }

    note = None
    if not trace["label_sufficient"]:
        note = (
            f"침수흔적 양성 격자 {n_all}칸 < {min_positive}칸 기준. AUC 는 참고값으로만 기록하고 "
            "예측 성능을 주장하지 않는다. 도시 침수 사상을 담은 자료를 추가로 확보해야 판정이 가능하다"
        )
    elif trace.get("event_auc_spread", {}).get("events_below_min"):
        # 합산 지표만 보고 "검증 통과"라고 쓰면 과대 진술이 된다. 사상 목록을 안내문에 박아 둔다.
        below = ", ".join(trace["event_auc_spread"]["events_below_min"])
        note = (
            f"합산 AUC 는 기준을 넘었으나 {below} 사상은 기준 미달이다. "
            "성능을 서술할 때 사상별 표(trace.by_event)를 함께 싣는다"
        )
    return trace, note


def layer1_flood(ctx: StageContext) -> dict[str, Any]:
    """통과: IDW 에 쓴 지점 ≥ min_idw_stations_per_event, 등급 I~IV 가 모두 나타남, L1 결측 0.
    침수흔적 AUC 는 **양성 격자가 trace_min_positive 이상일 때만** 판정한다."""
    from src.data import layers as L

    p = ctx.params
    n_classes = int(p["layer1.n_classes"])
    winsor = (float(p["layer1.winsor_lo"]), float(p["layer1.winsor_hi"]))
    min_stations = int(p["analysis.min_idw_stations_per_event"])

    df = _load_grid_features(p["analysis.canonical_crs"])
    universe = df["universe"].to_numpy().astype(bool)
    m: dict[str, Any] = {"n_grid": int(len(df)), "n_universe": int(universe.sum())}

    m["idw"] = _climate_exposure(df, p)
    m["min_idw_stations_required"] = min_stations

    _add_proximity(df, float(p["layer1.river_proximity_m"]))
    z_exposure, exposure_detail = L.composite(df, EXPOSURE_SPEC, winsor_lo=winsor[0], winsor_hi=winsor[1])
    z_sensitivity, sensitivity_detail = L.composite(df, SENSITIVITY_SPEC, winsor_lo=winsor[0], winsor_hi=winsor[1])
    df["z_exposure"] = z_exposure
    df["z_sensitivity"] = z_sensitivity
    df["L1"] = L.minmax(z_exposure + z_sensitivity)
    m["composite"] = {"exposure": exposure_detail, "sensitivity": sensitivity_detail}
    m.update(_classify_layer1(df, z_exposure, z_sensitivity, n_classes))

    m["exclusion_sensitivity"] = _exclusion_sensitivity(df, z_exposure, universe, winsor)
    m["case_study"] = _case_study_check(df, universe, float(p["layer1.case_study_lift_min"]))

    trace, note = _flood_trace_check(df, universe, p, z_exposure, winsor)
    m["label_available"] = trace is not None
    if trace:
        m["trace"] = trace
    if note:
        m["label_note"] = note

    findings: list[dict[str, Any]] = []
    if m["idw"]["min_stations_used"] < min_stations:
        findings.append({"code": "too_few_idw_stations",
                         "detail": f"{m['idw']['min_stations_used']} < {min_stations}"})
    if int(df["L1"].isna().sum()):
        findings.append({"code": "l1_missing", "detail": int(df["L1"].isna().sum())})
    if len(m["class_counts"]) != n_classes or min(m["class_counts"].values()) == 0:
        findings.append({"code": "empty_class", "detail": m["class_counts"]})
    if trace and trace["label_sufficient"] and "auc_all_grid" in trace:
        if trace["auc_all_grid"] < trace["auc_min"]:
            findings.append({
                "code": "trace_auc",
                "detail": f"AUC {trace['auc_all_grid']} < {trace['auc_min']} (양성 {trace['n_labelled_grid']}칸)",
            })
    if findings:
        raise StageFailed("Layer 1 통과 기준 미달", findings, metrics=m)

    columns = [
        "grid_id", "adm_cd", "gu_code", "universe",
        *EXPOSURE_VARIABLES, "river_proximity",
        "z_exposure", "z_sensitivity", "exposure_class", "sensitivity_class",
        "vulnerability_class", "vulnerability_grade", "L1", "geometry",
    ]
    if "trace_label" in df.columns:
        # 캘리브레이션·검증 라벨을 따로 실어 H07 이 in-sample 순환 없이 등급 경계를 맞춘다.
        columns[-1:-1] = [
            "trace_overlap", "trace_label", "trace_label_cal", "trace_label_val",
            *sorted(c for c in df.columns if c.startswith(EVENT_LABEL_PREFIX)),
        ]
    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    df[columns].to_file(out, layer="layer1_flood", driver="GPKG")
    _layer1_map(df, PROJECT_ROOT / "reports/figures/layer1_map.png")
    return m


def _layer1_map(df, out: Path) -> None:
    """노출·민감도·등급·지수를 한 장에 보여주는 4면 지도 (G007 증거)."""
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
AGGREGATION_BOUNDARY_DIR = "data/raw/sgis/aggregation_boundaries_2025_2Q"


def _attach_elderly_ratio(df, year: int) -> dict[str, Any]:
    """집계구 단위 65세 이상 비율을 격자에 붙인다 (중심점이 속한 집계구의 **비율**을 그대로).

    수를 면적 비례로 쪼개지 않는 이유: 비율은 그 지역의 성질이지 면적의 성질이 아니다.
    """
    import geopandas as gpd
    import pandas as pd

    from src.data import sgis

    aggregation = pd.read_parquet(PROJECT_ROOT / "data/processed/canonical/sgis_aggregation.parquet")
    elderly = sgis.elderly_ratio(aggregation, year)

    shapes = sorted((PROJECT_ROOT / AGGREGATION_BOUNDARY_DIR).glob("*.shp"))
    boundaries = pd.concat([gpd.read_file(q) for q in shapes], ignore_index=True)
    boundaries = gpd.GeoDataFrame(boundaries, geometry="geometry", crs=boundaries.crs).to_crs(df.crs)
    boundaries["spatial_id"] = boundaries["TOT_OA_CD"].astype(str)

    centroids = gpd.GeoDataFrame({"grid_id": df["grid_id"]}, geometry=df.geometry.centroid, crs=df.crs)
    joined = gpd.sjoin(centroids, boundaries[["spatial_id", "geometry"]], predicate="within", how="left")
    joined = joined.drop_duplicates(subset="grid_id")[["grid_id", "spatial_id"]]

    merged = df.merge(joined, on="grid_id", how="left").merge(
        elderly[["spatial_id", "elderly_ratio", "pop_elderly", "pop_age_total"]],
        on="spatial_id", how="left",
    )
    # 두 열을 한 numpy 배열로 대입하면 문자열(spatial_id)과 실수(elderly_ratio)가 섞여
    # object dtype 이 되고, 그대로 gpkg 에 쓰면 비율이 TEXT 로 저장돼 하류에서 깨진다.
    df["spatial_id"] = merged["spatial_id"].to_numpy()
    df["elderly_ratio"] = merged["elderly_ratio"].to_numpy(dtype=float)

    universe = df["universe"].to_numpy().astype(bool)
    first_elderly_col = sgis.age_columns(sgis.AGE_BLOCK_TOTAL, min_age=sgis.ELDERLY_FROM_AGE)[0]
    weighted = float(
        (df.loc[universe, "elderly_ratio"] * df.loc[universe, "pop_total"]).sum()
        / df.loc[universe, "pop_total"].sum()
    )
    meta = {
        "age_codebook": f"in_age 5세 계급, {sgis.ELDERLY_FROM_AGE}세 이상 = {first_elderly_col} 이후",
        "codebook_verified": "노령화지수(to_in_004) 항등식 대조 — src/data/sgis.py 주석",
        "n_aggregation_units": int(len(elderly)),
        "join_rate_all": round(float(df["spatial_id"].notna().mean()), 4),
        "join_rate_universe": round(float(df.loc[universe, "spatial_id"].notna().mean()), 4),
        "missing_ratio_universe": round(float(df.loc[universe, "elderly_ratio"].isna().mean()), 4),
        "city_elderly_share": round(float(elderly["pop_elderly"].sum() / elderly["pop_age_total"].sum()), 4),
        # 단순평균은 면적이 넓은 농촌 집계구가 격자를 많이 차지해 부풀려진다.
        # 시 전체와 비교할 수 있는 것은 인구가중 평균이다.
        "grid_pop_weighted_universe": round(weighted, 4),
        "grid_unweighted_mean_universe": round(float(df.loc[universe, "elderly_ratio"].mean()), 4),
        "grids_per_aggregation_unit": {
            "median": float(df.loc[universe].groupby("spatial_id").size().median()),
            "max": int(df.loc[universe].groupby("spatial_id").size().max()),
            "note": "집계구 하나가 격자 여러 개에 같은 비율을 준다 — 배분 불확실성 (ANALYSIS_PLAN §4)",
        },
    }
    # 집계구에 걸치지 못한 격자는 구 중앙값으로 채우고 플래그를 남긴다 (0 대체 금지).
    df["elderly_imputed"] = df["elderly_ratio"].isna().astype("int8")
    df["elderly_ratio"] = (
        df["elderly_ratio"].fillna(df.groupby("gu_code")["elderly_ratio"].transform("median"))
        .fillna(df["elderly_ratio"].median())
    )
    return meta


def _attach_capacity(df, crs: str, max_dist_m: float) -> dict[str, Any]:
    """대피장소·방재기관 최근접 거리로 대응역량과 그 부족도를 만든다.

    상한을 두는 이유: 그보다 멀면 도보 대피가 어려워 거리 차이가 의미를 잃는다.
    펌프장은 Layer 1 배수조건에 이미 썼으므로 여기 넣지 않는다 (이중투입 금지).
    """
    import numpy as np
    from scipy.spatial import cKDTree

    from src.data import shelters

    points, meta = shelters.load(sorted((PROJECT_ROOT / "data/raw/shelters").glob("*.json")), crs=crs)
    centroids = np.column_stack([df.geometry.centroid.x, df.geometry.centroid.y])
    for kind, column in (("shelter", "shelter_dist_m"), ("facility", "facility_dist_m")):
        sub = points[points["kind"] == kind]
        tree = cKDTree(np.column_stack([sub.geometry.x, sub.geometry.y]))
        df[column] = tree.query(centroids)[0]

    df["capacity_norm"] = 1.0 - np.mean([
        np.minimum(df["shelter_dist_m"], max_dist_m) / max_dist_m,
        np.minimum(df["facility_dist_m"], max_dist_m) / max_dist_m,
    ], axis=0)
    df["capacity_deficit"] = 1.0 - df["capacity_norm"]

    universe = df["universe"].to_numpy().astype(bool)
    meta.update({
        "max_dist_m": max_dist_m,
        "shelter_dist_median_universe": round(float(df.loc[universe, "shelter_dist_m"].median()), 1),
        "facility_dist_median_universe": round(float(df.loc[universe, "facility_dist_m"].median()), 1),
        "capacity_deficit_mean_universe": round(float(df.loc[universe, "capacity_deficit"].mean()), 4),
        "note": "펌프장 거리는 Layer 1 배수조건으로 이미 썼으므로 대응역량에서 제외 (하네스 §7)",
    })
    return meta


def layer3_vuln(ctx: StageContext) -> dict[str, Any]:
    """통과: 65세 이상은 확정된 연령 코드북으로만 파생, 집계구 조인율 ≥95%,
    E·V·capacity_deficit 결측 0 (0 으로 대체하지 않는다)."""
    from src.data import layers as L

    p = ctx.params
    n_classes = int(p["layer1.n_classes"])
    winsor = (float(p["layer1.winsor_lo"]), float(p["layer1.winsor_hi"]))

    df = _load_grid_features(p["analysis.canonical_crs"])
    df = df[["grid_id", "adm_cd", "gu_code", "universe", "pop_total", "households", "houses", "geometry"]].copy()
    universe = df["universe"].to_numpy().astype(bool)
    m: dict[str, Any] = {"n_grid": int(len(df)), "n_universe": int(universe.sum())}

    m["elderly"] = _attach_elderly_ratio(df, int(p["features.sgis_year"]))
    m["capacity"] = _attach_capacity(df, p["analysis.canonical_crs"], float(p["layer3.capacity_max_dist_m"]))

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
    """노출·취약성·대응역량 부족도를 나란히 보여주는 3면 지도 (G009 증거)."""
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
