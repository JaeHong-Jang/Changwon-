"""데이터 확인 EDA 그림 (H02). 판정은 하지 않고 이미 계산된 표를 그리기만 한다.

흑백 인쇄 기준으로 그린다. 기준선은 점선, 기준 미달은 해칭으로 구분하며 색에 의미를
싣지 않는다. 각 그림은 각주 한 줄로 무엇을 봐야 하는지 스스로 설명한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.quality import Thresholds
from src.visualization import style


def station_coverage(coverage: pd.Series, lo, hi, path: Path, thresholds: Thresholds = Thresholds()) -> None:
    """지점별 관측일 커버리지. 기준 미달 지점은 해칭으로 표시한다."""
    passed = coverage >= thresholds.cohort_coverage_min
    fig, ax = style.new_axes(
        f"강수 지점별 관측일 커버리지 ({lo.year}~{hi.year})",
        f"해칭 = 기준 미달로 cohort 제외 ({int((~passed).sum())}개 지점)",
        figsize=(9, 4.4),
    )
    ax.bar(
        range(len(coverage)),
        coverage.values,
        color=[style.MID if ok else "white" for ok in passed],
        edgecolor=style.INK,
        hatch=["" if ok else "///" for ok in passed],
    )
    ax.axhline(thresholds.cohort_coverage_min, ls="--", c=style.INK, lw=1)
    ax.annotate(
        f"cohort 기준 {thresholds.cohort_coverage_min:.0%}",
        xy=(len(coverage) - 0.5, thresholds.cohort_coverage_min),
        xytext=(-4, 6), textcoords="offset points", ha="right", fontsize=9,
    )
    ax.set_xticks(range(len(coverage)))
    ax.set_xticklabels([name for _, name in coverage.index], rotation=90, fontsize=7)
    ax.set_ylabel("관측일 / 전체일")
    ax.set_ylim(0, 1.05)
    style.save(fig, path)


def annual_totals(annual: pd.DataFrame, path: Path, thresholds: Thresholds = Thresholds()) -> None:
    """연도별 지점 연총량 분포. 어느 해가 지점 전체로 낮은지 본다."""
    fig, ax = style.new_axes(
        "연도별 강수 지점 연총량 분포",
        f"음영 = 기후값 참고 범위 {thresholds.rainfall_annual_min_mm:.0f}~{thresholds.rainfall_annual_max_mm:.0f}mm (판정 기준 아님)",
        figsize=(9, 4.4),
    )
    years = [int(y) for y in sorted(annual["year"].unique())]
    ax.boxplot(
        [annual.loc[annual["year"] == y, "rainfall_mm"].to_numpy(dtype=float) for y in years],
        tick_labels=[str(y) for y in years],
        medianprops=dict(color=style.INK, lw=1.4),
        boxprops=dict(color=style.INK),
        whiskerprops=dict(color=style.DARK),
        capprops=dict(color=style.DARK),
        flierprops=dict(marker="o", ms=3, mfc="white", mec=style.DARK),
    )
    ax.axhspan(thresholds.rainfall_annual_min_mm, thresholds.rainfall_annual_max_mm, color=style.PALE, zorder=0)
    ax.set_ylabel("연총 강수량 (mm)")
    ax.set_ylim(bottom=0)
    style.save(fig, path)


def river_validity(by_station: pd.Series, path: Path, thresholds: Thresholds = Thresholds()) -> None:
    """지점별 유효값 비율. 사례분석에 쓸 수 있는 지점을 가른다."""
    usable = by_station >= thresholds.river_usable_ratio_min
    fig, ax = style.new_axes(
        "하천수위 지점별 유효값 비율",
        f"점선 = 사용 가능선 {thresholds.river_usable_ratio_min:.0%}. 해칭 = 코드북 확인 전까지 사용 보류",
        figsize=(8, 3.8),
    )
    labels = [f"{name} ({int(sid)})" for sid, name in by_station.index]
    ax.barh(
        labels, by_station.values,
        color=[style.MID if ok else "white" for ok in usable],
        edgecolor=style.INK,
        hatch=["" if ok else "///" for ok in usable],
    )
    ax.axvline(thresholds.river_usable_ratio_min, ls="--", c=style.INK, lw=1)
    ax.set_xlabel("센티널·범위밖을 제외한 유효 셀 비율")
    ax.set_xlim(0, 1.0)
    ax.margins(x=0)
    ax.grid(axis="x", visible=True)
    ax.grid(axis="y", visible=False)
    ax.invert_yaxis()
    style.save(fig, path)


def grid_population(values: pd.Series, path: Path) -> None:
    """분석격자 인구 분포.

    y축을 로그로 그리는 이유: 인구 격자의 절반이 10명 이하라 가장 높은 막대가 꼬리보다
    수천 배 크다. 선형 축이면 인구가 많은 구간의 막대가 1픽셀 미만이 되어 보이지 않는다.
    확인하려는 것이 "희박한 격자가 대부분이고 시가지 격자가 소수 있는가"이므로
    두 끝이 모두 보여야 한다.
    """
    nonzero = values[values > 0].to_numpy(dtype=float)
    series = pd.Series(nonzero)
    ratio = 0
    fig, ax = style.new_axes(
        "100m 분석격자 인구 분포",
        f"인구가 있는 격자 {len(nonzero):,}개 · 중앙값 {series.median():.0f}명 · "
        f"상위 1% {series.quantile(0.99):.0f}명 이상 (인구 0인 격자 제외)",
        figsize=(8, 4.0),
    )
    counts, edges, _ = ax.hist(nonzero, bins=60, color=style.LIGHT, edgecolor=style.INK, lw=0.5)
    ax.set_yscale("log")
    ax.set_xlim(0, edges[-1])
    ax.margins(x=0)
    ax.set_xlabel("격자 인구 (명)")
    ax.set_ylabel("격자 수 (로그 눈금)")
    ax.annotate(
        f"막대 높이 최대 {counts.max():,.0f} vs 최소 {counts[counts > 0].min():,.0f}\n"
        "→ 선형 눈금이면 오른쪽 꼬리가 보이지 않는다",
        xy=(0.97, 0.93), xycoords="axes fraction", ha="right", va="top",
        fontsize=8, color=style.DARK,
    )
    style.save(fig, path)
