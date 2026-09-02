"""H02 데이터 확인 EDA. 탐색이 아니라 '이 데이터를 써도 되는가'를 판정하는 검증 노드다.

판정은 `src/data/quality.py`, 그림은 `src/visualization/eda_figures.py` 가 맡고
여기서는 파일을 읽어 넘기고 결과를 문서로 쓰는 일만 한다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.data.quality import (
    Thresholds,
    check_grid_population,
    check_rainfall,
    check_river,
    rainfall_table,
)
from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT
from src.visualization import eda_figures

CANONICAL = PROJECT_ROOT / "data/processed/canonical"
GRID_BASE = PROJECT_ROOT / "data/processed/spatial/grid_base.gpkg"


def _read_canonical(name: str) -> pd.DataFrame:
    """canonical parquet 을 읽는다. `obs_date` 는 정제 단계가 저장한 것을 그대로 쓴다.

    여기서 `observed_at.dt.normalize()` 로 재계산하면 안 된다. 정제 단계는 24시를
    다음날 00:00 으로 옮기므로, 재계산한 날짜는 정제 단계가 cohort 를 셀 때 쓴 날짜와
    달라진다(리뷰 M3: 2일치 입력에서 2일 vs 3일). 두 노드가 서로 다른 관측일 수를
    쓰면서 아무도 오류를 내지 않는 상태가 된다.
    """
    df = pd.read_parquet(CANONICAL / name)
    if "obs_date" not in df.columns:
        raise StageFailed(
            f"{name} 에 obs_date 컬럼이 없다 — 정제 단계를 다시 실행해야 한다",
            [{"code": "missing_obs_date", "file": name,
              "detail": "python -m src.pipeline run --only h02_rainfall_long --force (수위도 동일)"}],
        )
    return df


def data_check(ctx: StageContext) -> dict[str, Any]:
    """정제된 강수·수위·SGIS 가 분석에 쓸 수 있는 데이터인지 판정한다."""
    lo = pd.Timestamp(ctx.params["analysis.climatology_start"])
    hi = pd.Timestamp(ctx.params["analysis.climatology_end"])
    thresholds = Thresholds.from_params(ctx.params)
    fig_coverage, fig_annual, fig_river, fig_population, report = ctx.outputs

    annual = rainfall_table(_read_canonical("rainfall_hourly.parquet"), lo, hi, thresholds)
    rain_metrics, rain_anomalies = check_rainfall(annual)
    eda_figures.station_coverage(annual.attrs["coverage"], lo, hi, fig_coverage, thresholds)
    eda_figures.annual_totals(annual, fig_annual, thresholds)

    river_metrics, river_anomalies, by_station = check_river(
        _read_canonical("river_level_hourly.parquet"), lo, hi, thresholds
    )
    eda_figures.river_validity(by_station, fig_river, thresholds)

    grid_ids = None
    if GRID_BASE.exists():
        import geopandas as gpd

        grid_ids = set(gpd.read_file(GRID_BASE, layer="grid")["grid_id"].astype(str))
    grid_metrics, grid_anomalies, populations = check_grid_population(
        pd.read_parquet(CANONICAL / "sgis_grid_statistics.parquet"), grid_ids, thresholds
    )
    eda_figures.grid_population(populations, fig_population)

    metrics = {**rain_metrics, **river_metrics, **grid_metrics}
    anomalies = rain_anomalies + river_anomalies + grid_anomalies
    metrics["anomalies"] = anomalies

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(_report(ctx, metrics, anomalies, thresholds, ctx.outputs[:4]), encoding="utf-8")

    if anomalies:
        raise StageFailed(
            f"데이터 확인 EDA 이상 징후 {len(anomalies)}건 — {report.name} 에 원인을 기록하라",
            [{"code": "anomaly", **a} for a in anomalies],
            metrics=metrics,
        )
    return metrics


def _pct(value: float | None) -> str:
    return "측정 안 함" if value is None else f"{value:.1%}"


def _report(
    ctx: StageContext,
    metrics: dict[str, Any],
    anomalies: list[dict[str, str]],
    thresholds: Thresholds,
    figures,
) -> str:
    """`docs/eda_data_check.md` 본문. 마지막 '판단' 칸은 사람이 채운다."""
    population = metrics["sgis_grid_population_sum"]
    lines = [
        "# 데이터 확인 EDA — 이상 징후",
        "",
        f"> 생성: `python -m src.pipeline run --only {ctx.node.id}` (run_id `{ctx.run_id}`)",
        "> **판단** 칸은 사람이 채운다. 데이터원인이면 그 묶음의 수집 노드로,",
        "> 정제원인이면 해당 정제 노드로 돌아간다 (`config/pipeline.yaml` 의 on_fail).",
        "",
        "## 요약",
        "",
        f"- 강수 cohort 지점: {metrics['rainfall_cohort_stations']}개, "
        f"연총량 중앙값 {metrics['rainfall_annual_median_mm'] or '—'} mm",
        f"- 강수 관측 중단 지점-연도: {len(metrics['rainfall_coverage_gap_station_years'])}건 (연총량 비교 제외)",
        f"- 강수 지점 이탈({thresholds.rainfall_station_ratio_min:.0%}~"
        f"{thresholds.rainfall_station_ratio_max:.0%} 밖): {metrics['rainfall_deviant_station_years']}건",
        f"- 강수 지점간 비율 1~99%: {metrics['rainfall_ratio_p01_p99'][0]}~{metrics['rainfall_ratio_p01_p99'][1]}",
        f"- 하천수위 유효 셀 비율: {_pct(metrics['river_valid_ratio'])} "
        f"(센티널 누출 {metrics['river_sentinel_leaked_into_level']}건, 사용 가능 지점 {metrics['river_usable_stations']}개)",
        f"- SGIS 분석격자 총인구: {f'{population:,}명' if population is not None else '분석격자 없음 — 비교 안 함'} "
        f"(주민등록 대비 {_pct(metrics['sgis_pop_ratio_vs_registered'])}, "
        f"join 성공률 {metrics.get('sgis_grid_join_rate')})",
        "",
        "## 이상 징후",
        "",
        "| 대상 | 항목 | 값 | 기준 | 판단 (사람) |",
        "|---|---|---|---|---|",
    ]
    lines += (
        [f"| {a['target']} | {a['metric']} | {a['value']} | {a['threshold']} | ⬜ 미기입 |" for a in anomalies]
        if anomalies
        else ["| — | — | — | — | 이상 없음 |"]
    )

    if metrics["rainfall_coverage_gap_station_years"]:
        lines += [
            "",
            "## 참고: 관측 중단이 있어 연총량 비교에서 제외한 지점-연도",
            "",
            "| 지점 | 연도 | 관측일 | 비율 | 연총량 | 처리 |",
            "|---|---|---|---|---|---|",
        ] + [
            f"| {g['station']} | {g['year']} | {g['obs_days']}일 | {g['obs_ratio']:.0%} | "
            f"{g['annual_mm']:.0f} mm | {g['note']} |"
            for g in metrics["rainfall_coverage_gap_station_years"]
        ]

    if metrics["rainfall_unusual_years"]:
        lines += [
            "",
            "## 참고: 지점 전체가 함께 벗어난 해 (차단하지 않음)",
            "",
            "| 연도 | 지점 중앙 연총량 | 평균 관측일수 | 해석 |",
            "|---|---|---|---|",
        ] + [
            f"| {u['year']} | {u['median_mm']:.0f} mm | {u['mean_obs_days']:.0f}일 | {u['note']} |"
            for u in metrics["rainfall_unusual_years"]
        ]

    lines += ["", "## 그림", ""]
    lines += [f"- `{p.relative_to(PROJECT_ROOT)}`" for p in figures]
    return "\n".join(lines) + "\n"
