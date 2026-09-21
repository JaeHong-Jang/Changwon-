"""정제된 데이터가 분석에 쓸 수 있는지 판정하는 순수 함수들."""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any, ClassVar

import pandas as pd

# 원본이 쓰는 하천수위 결측 코드.
RIVER_SENTINELS = {-47999, -8383, 9321, 9999}


@dataclass(frozen=True)
class Thresholds:
    """판정 기준. 기본값은 config/config.yaml 의 값과 같아야 한다."""

    rainfall_station_ratio_min: float = 0.5
    rainfall_station_ratio_max: float = 2.0
    rainfall_year_obsday_min: float = 0.95
    rainfall_annual_min_mm: float = 700.0
    rainfall_annual_max_mm: float = 2600.0
    cohort_coverage_min: float = 0.90
    river_usable_ratio_min: float = 0.10
    river_min_usable_stations: int = 1
    sgis_pop_tolerance: float = 0.10
    changwon_registered_population: float = 1_002_000.0

    # 필드별 analysis 설정 키
    CONFIG_KEYS: ClassVar[dict[str, str]] = {
        "rainfall_station_ratio_min": "rainfall_station_ratio_min",
        "rainfall_station_ratio_max": "rainfall_station_ratio_max",
        "rainfall_year_obsday_min": "rainfall_year_obsday_min",
        "rainfall_annual_min_mm": "rainfall_annual_min_mm",
        "rainfall_annual_max_mm": "rainfall_annual_max_mm",
        "cohort_coverage_min": "min_station_day_coverage",
        "river_usable_ratio_min": "river_usable_ratio_min",
        "river_min_usable_stations": "river_min_usable_stations",
        "sgis_pop_tolerance": "sgis_pop_tolerance",
        "changwon_registered_population": "changwon_registered_population",
    }

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> "Thresholds":
        """StageContext.params(`{"analysis.키": 값}`)에서 만든다. 누락 키는 KeyError."""
        return cls(**{
            field.name: params[f"analysis.{cls.CONFIG_KEYS[field.name]}"]
            for field in dataclasses.fields(cls)
        })


def _anomaly(target: str, metric: str, value: str, threshold: str) -> dict[str, str]:
    return {"target": target, "metric": metric, "value": value, "threshold": threshold}


def _number(value: Any, digits: int = 1) -> float | None:
    """NaN 은 None 으로. metrics 는 manifest JSON 으로 나가므로 NaN 이 있으면 안 된다."""
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) else round(number, digits)


def _days_in_year(year: int) -> int:
    return 366 if pd.Timestamp(year=int(year), month=12, day=31).dayofyear == 366 else 365


def cohort_station_ids(
    rain: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp, min_coverage: float
) -> list[int]:
    """분석기간 안 관측일 비율이 `min_coverage` 이상인 지점 코드. `rainfall_table` 과 같은 정의다."""
    rain = rain[(rain["obs_date"] >= lo) & (rain["obs_date"] <= hi)]
    total_days = (hi - lo).days + 1
    ratios = rain.groupby("station_id")["obs_date"].nunique() / total_days
    return sorted(int(sid) for sid, value in ratios.items() if value >= min_coverage)


def rainfall_table(
    rain: pd.DataFrame,
    lo: pd.Timestamp,
    hi: pd.Timestamp,
    thresholds: Thresholds = Thresholds(),
) -> pd.DataFrame:
    """분석기간 안의 cohort 지점 연총량 표."""
    rain = rain[(rain["obs_date"] >= lo) & (rain["obs_date"] <= hi)]
    total_days = (hi - lo).days + 1

    by_station = rain.groupby("station_id")
    ratios = by_station["obs_date"].nunique() / total_days
    names = by_station["station_name"].first()
    coverage = pd.Series(
        ratios.to_numpy(),
        index=pd.MultiIndex.from_arrays(
            [ratios.index, names.reindex(ratios.index).to_numpy()],
            names=["station_id", "station_name"],
        ),
    ).sort_values(ascending=False)
    cohort_ids = cohort_station_ids(rain, lo, hi, thresholds.cohort_coverage_min)

    annual = (
        rain[rain["quality_flag"] == "ok"]
        .dropna(subset=["rainfall_mm"])
        .assign(year=lambda d: d["obs_date"].dt.year)
        .groupby(["station_id", "year"], as_index=False)["rainfall_mm"]
        .sum()
    )
    annual = annual[annual["station_id"].isin(cohort_ids)].copy()
    annual["station_name"] = annual["station_id"].map(names)

    observed = (
        rain.assign(year=rain["obs_date"].dt.year)
        .groupby(["station_id", "year"], as_index=False)["obs_date"]
        .nunique()
        .rename(columns={"obs_date": "obs_days"})
    )
    observed["obs_ratio"] = observed["obs_days"] / observed["year"].map(_days_in_year)
    annual = annual.merge(observed, on=["station_id", "year"], how="left")

    comparable = annual["obs_ratio"] >= thresholds.rainfall_year_obsday_min
    annual["comparable"] = comparable
    year_median = annual[comparable].groupby("year")["rainfall_mm"].median()
    annual["year_median"] = annual["year"].map(year_median)
    annual["ratio"] = annual["rainfall_mm"] / annual["year_median"]

    annual.attrs["coverage"] = coverage
    annual.attrs["cohort_ids"] = cohort_ids
    annual.attrs["thresholds"] = thresholds
    return annual


def check_rainfall(annual: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """관측일이 충분한데도 이웃 지점과 어긋나는 지점을 차단한다."""
    thresholds: Thresholds = annual.attrs.get("thresholds", Thresholds())
    metrics: dict[str, Any] = {
        "rainfall_cohort_stations": len(annual.attrs["cohort_ids"]),
        "rainfall_annual_median_mm": _number(annual["rainfall_mm"].median()) if len(annual) else None,
        "rainfall_ratio_p01_p99": [
            _number(annual["ratio"].quantile(0.01), 3) if len(annual) else None,
            _number(annual["ratio"].quantile(0.99), 3) if len(annual) else None,
        ],
    }

    gaps = annual[~annual["comparable"]]
    metrics["rainfall_coverage_gap_station_years"] = [
        {
            "station": f"{row['station_name']}({int(row['station_id'])})",
            "year": int(row["year"]),
            "obs_days": int(row["obs_days"]),
            "obs_ratio": _number(row["obs_ratio"], 3),
            "annual_mm": _number(row["rainfall_mm"]),
            "note": "관측 중단이 있어 연총량 비교에서 제외. 이벤트별 IDW 정상지점 수 규칙이 처리",
        }
        for _, row in gaps.iterrows()
    ]

    comparable = annual[annual["comparable"]]
    deviant = comparable[
        (comparable["ratio"] < thresholds.rainfall_station_ratio_min)
        | (comparable["ratio"] > thresholds.rainfall_station_ratio_max)
    ]
    metrics["rainfall_deviant_station_years"] = int(len(deviant))
    anomalies = [
        _anomaly(
            f"강수 {row['station_name']}({int(row['station_id'])})",
            f"{int(row['year'])}년 연총량 / 같은 해 지점 중앙값",
            f"{row['rainfall_mm']:.0f} mm ({row['ratio']:.0%} of {row['year_median']:.0f} mm)",
            f"{thresholds.rainfall_station_ratio_min:.0%}~{thresholds.rainfall_station_ratio_max:.0%}",
        )
        for _, row in deviant.iterrows()
    ]

    # 참고 기록: 지점 전체가 함께 벗어난 해 (기후 신호 후보 — 차단하지 않음)
    year_median = comparable.groupby("year")["rainfall_mm"].median()
    obs_by_year = comparable.groupby("year")["obs_days"].mean()
    metrics["rainfall_year_median_mm"] = {int(y): _number(v) for y, v in year_median.items()}
    metrics["rainfall_unusual_years"] = [
        {
            "year": int(year),
            "median_mm": _number(value),
            "mean_obs_days": _number(obs_by_year.get(year)),
            "note": "지점 전체가 함께 벗어남 + 관측일수 정상 → 기후 신호(가뭄/다우). 결측 아님",
        }
        for year, value in year_median.items()
        if value < thresholds.rainfall_annual_min_mm or value > thresholds.rainfall_annual_max_mm
    ]
    return metrics, anomalies


def check_river(
    river: pd.DataFrame,
    lo: pd.Timestamp,
    hi: pd.Timestamp,
    thresholds: Thresholds = Thresholds(),
) -> tuple[dict[str, Any], list[dict[str, str]], pd.Series]:
    """센티널이 정제값에 샜는지와 쓸 수 있는 지점이 남았는지 판정한다."""
    sub = river[(river["obs_date"] >= lo) & (river["obs_date"] <= hi)]
    by_station = (
        sub.assign(ok=sub["level_cm"].notna())
        .groupby(["station_id", "station_name"])["ok"]
        .mean()
        .sort_values(ascending=False)
    )
    leaked = int(sub["level_cm"].isin(RIVER_SENTINELS).sum())
    # 경계값 포함 (>=)
    usable = int((by_station >= thresholds.river_usable_ratio_min).sum())

    metrics: dict[str, Any] = {
        "river_cells": int(len(sub)),
        "river_valid_ratio": _number(sub["level_cm"].notna().mean(), 4) if len(sub) else 0.0,
        "river_valid_ratio_by_station": {
            f"{name}({int(sid)})": _number(value, 4) for (sid, name), value in by_station.items()
        },
        "river_sentinel_leaked_into_level": leaked,
        "river_usable_stations": usable,
    }

    anomalies: list[dict[str, str]] = []
    if leaked:
        anomalies.append(_anomaly("하천수위", "센티널 값이 정제된 level_cm 에 남은 셀", f"{leaked}개", "0개"))
    if usable < thresholds.river_min_usable_stations:
        anomalies.append(
            _anomaly(
                "하천수위",
                f"유효값 {thresholds.river_usable_ratio_min:.0%} 이상인 지점 수",
                f"{usable}개",
                f"≥ {thresholds.river_min_usable_stations}개",
            )
        )
    return metrics, anomalies, by_station


def check_grid_population(
    grid_stats: pd.DataFrame,
    analysis_grid_ids: set[str] | None,
    thresholds: Thresholds = Thresholds(),
) -> tuple[dict[str, Any], list[dict[str, str]], pd.Series]:
    """분석격자로 자른 인구 합이 주민등록인구와 맞는지 판정한다."""
    pop = grid_stats[grid_stats["variable"] == "to_in_001"]
    metrics: dict[str, Any] = {"sgis_sheet_population_sum": int(pop["value"].sum())}

    if analysis_grid_ids is None:
        metrics["sgis_grid_join_rate"] = None
        metrics["sgis_grid_population_sum"] = None
        metrics["sgis_pop_ratio_vs_registered"] = None
        metrics["sgis_grid_cells_with_population"] = None
        return (
            metrics,
            [_anomaly("SGIS 100m 격자", "분석격자 파일", "없음", "h03_grid_base 선행 필요")],
            pop["value"],
        )

    pop = pop[pop["spatial_id"].isin(analysis_grid_ids)]
    metrics["sgis_analysis_grid_cells"] = len(analysis_grid_ids)
    metrics["sgis_grid_join_rate"] = (
        _number(pop["spatial_id"].nunique() / len(analysis_grid_ids), 4) if analysis_grid_ids else 0.0
    )

    total = float(pop["value"].sum())
    ratio = total / thresholds.changwon_registered_population
    metrics["sgis_grid_population_sum"] = int(total)
    metrics["sgis_pop_ratio_vs_registered"] = _number(ratio, 4)
    metrics["sgis_grid_cells_with_population"] = int((pop["value"] > 0).sum())

    anomalies: list[dict[str, str]] = []
    if abs(ratio - 1.0) > thresholds.sgis_pop_tolerance:
        anomalies.append(
            _anomaly(
                "SGIS 100m 격자",
                "총인구 합계 / 주민등록인구",
                f"{total:,.0f} ({ratio:.1%})",
                f"100% ± {thresholds.sgis_pop_tolerance:.0%}",
            )
        )
    return metrics, anomalies, pop["value"]
