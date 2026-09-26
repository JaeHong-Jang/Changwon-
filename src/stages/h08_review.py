"""H08 결과 확인 EDA. 분포, TOP 20 편중, 침수예상도·침수흔적 대조를 확인한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT

CDRI_PATH = "data/processed/layers/cdri.gpkg"
LAYER1_PATH = "data/processed/layers/layer1_flood.gpkg"
TOP20_PATH = "reports/tables/top20.csv"
FLOOD_MAP_PATH = "data/processed/canonical/flood_maps.gpkg"
# A7 홍수위험지도 경로
FLOOD_RISK_DIR = "data/raw/flood_risk"
DONG_MAX_SHARE = 0.50          # 한 행정동이 TOP 20 의 절반을 넘으면 편중으로 본다
CONTRIBUTION_TOLERANCE = 1e-3  # 기여도 4성분 합이 1 에서 벗어나도 되는 폭


def _load_results():
    """CDRI 격자, TOP 20, Layer 1 침수흔적 라벨을 한 번에 읽는다."""
    import geopandas as gpd
    import pandas as pd

    cdri = gpd.read_file(PROJECT_ROOT / CDRI_PATH, layer="cdri")
    top20 = pd.read_csv(PROJECT_ROOT / TOP20_PATH)
    traces = gpd.read_file(
        PROJECT_ROOT / LAYER1_PATH, layer="layer1_flood", columns=["grid_id", "trace_label"]
    )
    return cdri.merge(traces.drop(columns="geometry"), on="grid_id", how="left"), top20


def _check_contributions(cdri) -> dict[str, Any]:
    """기여도 4성분의 합이 1 인지 본다. 어긋나면 산식이나 저장 과정이 깨진 것이다."""
    columns = ["h_contribution", "e_contribution", "v_contribution", "d_contribution"]
    total = cdri[columns].sum(axis=1)
    off = (total - 1.0).abs() > CONTRIBUTION_TOLERANCE
    return {
        "n_grid": int(len(cdri)),
        "sum_min": round(float(total.min()), 6),
        "sum_max": round(float(total.max()), 6),
        "n_off_by_more_than_tolerance": int(off.sum()),
        "tolerance": CONTRIBUTION_TOLERANCE,
        "ok": bool(not off.any()),
    }


def _check_dong_concentration(top20) -> dict[str, Any]:
    """TOP 20 이 한 행정동에 몰려 있지 않은지 본다."""
    counts = top20["neighborhood"].value_counts()
    return {
        "n_dong": int(len(counts)),
        "top_dong": str(counts.index[0]),
        "top_dong_n": int(counts.iloc[0]),
        "max_share": round(float(counts.iloc[0] / len(top20)), 4),
        "threshold": DONG_MAX_SHARE,
        "by_district": {k: int(v) for k, v in top20["district"].value_counts().items()},
        "ok": bool(counts.iloc[0] / len(top20) <= DONG_MAX_SHARE),
    }


def _overlap_with_flood_map(top20, cdri) -> dict[str, Any]:
    """TOP 20 이 창원시 침수예상도 구역과 얼마나 겹치나."""
    import geopandas as gpd

    path = PROJECT_ROOT / FLOOD_MAP_PATH
    if not path.exists():
        return {"available": False, "reason": f"{FLOOD_MAP_PATH} 없음"}

    selected = cdri[cdri["grid_id"].isin(top20["grid_id"])]
    flood = gpd.read_file(path, layer="flood_maps", where="layer = 'L210_100'").to_crs(selected.crs)
    joined = gpd.sjoin(selected[["grid_id", "geometry"]], flood[["geometry"]],
                       predicate="intersects", how="inner")
    hit = set(joined["grid_id"])
    return {
        "available": True,
        "layer": "L210_100 (100년 빈도 예상 침수심)",
        "n_top20": int(len(selected)),
        "n_overlap": len(hit),
        "share": round(len(hit) / len(selected), 3) if len(selected) else None,
        "note": "침수예상도는 Layer 1 의 입력이므로 성능 근거가 아니다 (순환). 정합성 점검용",
    }


def _overlap_with_traces(top20, cdri) -> dict[str, Any]:
    """TOP 20 중 실제 침수 기록이 있는 격자 수."""
    selected = cdri[cdri["grid_id"].isin(top20["grid_id"])]
    if "trace_label" not in selected.columns or selected["trace_label"].isna().all():
        return {"available": False, "reason": "Layer 1 에 침수흔적 라벨이 없다"}

    labels = selected["trace_label"].fillna(0).to_numpy().astype(bool)
    base = float(cdri["trace_label"].fillna(0).mean())
    share = float(labels.mean())
    return {
        "available": True,
        "n_top20": int(len(selected)),
        "n_with_trace": int(labels.sum()),
        "share": round(share, 3),
        # lift 기준 모집단: 순위 대상 격자
        "base_population": "순위 대상 격자 (인구 또는 주택이 있는 칸)",
        "base_n": int(len(cdri)),
        "base_rate": round(base, 5),
        "lift": round(share / base, 2) if base > 0 else None,
        "note": "표본 20칸이라 비율의 신뢰구간이 넓다. 칸 수를 그대로 읽는다",
    }


def _flood_risk_status() -> dict[str, Any]:
    """A7 홍수위험지도 확보 여부. 없으면 없다고 남긴다 — 빠진 것을 조용히 넘기지 않는다."""
    directory = PROJECT_ROOT / FLOOD_RISK_DIR
    files = sorted(p.name for p in directory.glob("*")) if directory.exists() else []
    return {
        "available": bool(files),
        "files": files,
        "note": ("A7 홍수위험지도 미확보 — 대조는 침수예상도(A1)와 실제 침수흔적으로 대체했다. "
                 "흔적도는 입력이 아니므로 A7 보다 강한 근거다"),
    }


def _distribution_figure(cdri, out: Path) -> None:
    """CDRI 분포와 등급 구성. 점수가 한쪽으로 쏠렸는지 한눈에 본다."""
    import matplotlib.pyplot as plt

    from src.data.grades import GRADE_CODES, GRADE_COLORS
    from src.visualization import style

    style.apply()
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))

    axes[0].hist(cdri["cdri"], bins=60, color=style.MID, edgecolor="none")
    axes[0].set_title("CDRI 분포 (순위 대상 격자)", fontsize=10)
    axes[0].set_xlabel("CDRI")
    axes[0].set_ylabel("격자 수")

    counts = cdri["grade_raw"].value_counts().sort_index()
    axes[1].bar([GRADE_CODES[g] for g in counts.index], counts.to_numpy(),
                color=[GRADE_COLORS[g] for g in counts.index], edgecolor=style.INK, linewidth=0.5)
    axes[1].set_title("등급 구성 (grade_raw, 캘리브레이션 본안)", fontsize=10)
    axes[1].set_ylabel("격자 수")

    # 등급별 실제 침수 발생률
    rate = cdri.groupby("grade_raw")["trace_label"].mean()
    axes[2].bar([GRADE_CODES[g] for g in rate.index], rate.to_numpy() * 100,
                color=[GRADE_COLORS[g] for g in rate.index], edgecolor=style.INK, linewidth=0.5)
    axes[2].axhline(cdri["trace_label"].mean() * 100, color=style.INK, linestyle="--", linewidth=1)
    axes[2].set_title("등급별 실제 침수 발생률 (점선 = 전체 평균)", fontsize=10)
    axes[2].set_ylabel("%")

    fig.tight_layout()
    style.save(fig, out)


def _top20_figure(cdri, top20, out: Path) -> None:
    """TOP 20 위치를 침수예상도·실제 침수흔적과 겹쳐 본다."""
    import geopandas as gpd
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    from src.visualization import style

    style.apply()
    selected = cdri[cdri["grid_id"].isin(top20["grid_id"])]
    flooded = cdri[cdri["trace_label"].fillna(0) == 1]

    fig, ax = plt.subplots(figsize=(9, 9))
    cdri.plot(ax=ax, color=style.PALE, linewidth=0)

    path = PROJECT_ROOT / FLOOD_MAP_PATH
    if path.exists():
        flood = gpd.read_file(path, layer="flood_maps", where="layer = 'L210_100'").to_crs(cdri.crs)
        flood.plot(ax=ax, color=style.LIGHT, linewidth=0)

    flooded.plot(ax=ax, color=style.DARK, linewidth=0)
    selected.geometry.centroid.plot(ax=ax, color="#bd0026", markersize=44,
                                    marker="o", edgecolor=style.INK, linewidth=0.6)
    ax.set_axis_off()
    ax.grid(False)
    ax.set_title("우선대응 TOP 20 · 침수예상도 · 실제 침수흔적", fontsize=11)
    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="", color="#bd0026", markeredgecolor=style.INK,
               markersize=8, label=f"TOP 20 (n={len(selected)})"),
        Line2D([], [], marker="s", linestyle="", color=style.DARK, markersize=8,
               label=f"실제 침수흔적 격자 (순위대상 n={len(flooded)})"),
        Line2D([], [], marker="s", linestyle="", color=style.LIGHT, markersize=8,
               label="침수예상도 L210 100년빈도"),
    ], loc="upper right", fontsize=8, frameon=True)
    fig.tight_layout()
    style.save(fig, out)


def _write_review(path: Path, m: dict[str, Any]) -> None:
    """사람이 읽고 판단할 수 있게 결과를 문장으로 정리한다. 승인자가 보는 문서다."""
    trace, fmap = m["overlap_traces"], m["overlap_flood_map"]
    dong, contrib = m["dong_concentration"], m["contributions"]
    lines = [
        "# 결과 확인 EDA (H08)",
        "",
        "자동 생성 문서다. 사람이 지도를 보고 판단하는 것을 대신하지 않는다.",
        "",
        "## 1. 산식 정합성",
        "",
        f"- 기여도 4성분 합: {contrib['sum_min']} ~ {contrib['sum_max']} "
        f"(허용 오차 {contrib['tolerance']} 밖 격자 {contrib['n_off_by_more_than_tolerance']}개)",
        f"- 판정: {'통과' if contrib['ok'] else '미달'}",
        "",
        "## 2. TOP 20 의 지역 분포",
        "",
        f"- 행정동 {dong['n_dong']}곳에 흩어져 있다. 가장 많은 곳은 {dong['top_dong']} "
        f"{dong['top_dong_n']}곳({dong['max_share']:.0%})",
        f"- 구별 분포: {dong['by_district']}",
        f"- 한 동 쏠림 기준 {dong['threshold']:.0%} → 판정: {'통과' if dong['ok'] else '미달'}",
        "",
        "## 3. 독립 자료와의 대조",
        "",
    ]
    if trace["available"]:
        lines += [
            f"**실제 침수흔적** (Layer 1 의 입력이 아니므로 순환 없음)",
            "",
            f"- TOP 20 중 실제 침수 기록이 있는 격자: **{trace['n_with_trace']}칸 / {trace['n_top20']}칸**",
            f"- 비교 모집단: {trace['base_population']} {trace['base_n']:,}칸, "
            f"기저 발생률 {trace['base_rate']:.2%} → **{trace['lift']}배**",
            f"- {trace['note']}",
            "",
        ]
    if fmap["available"]:
        lines += [
            f"**창원시 침수예상도 {fmap['layer']}**",
            "",
            f"- TOP 20 중 예상 침수구역과 겹치는 격자: {fmap['n_overlap']}칸 / {fmap['n_top20']}칸 "
            f"({fmap['share']:.0%})",
            f"- {fmap['note']}",
            "",
        ]
    lines += [
        f"**홍수위험지도(A7)**: {m['flood_risk_map']['note']}",
        "",
        "## 4. 사람이 확인할 것",
        "",
        "- `reports/figures/result_review/top20_vs_flood_maps.png` 를 열어 TOP 20 이 상식적인 곳에 있는지",
        "- 사례지(양덕동·봉암동·팔용동) 주변이 상위에 드는지",
        "- 예상도와 겹치지 않는 TOP 20 격자가 있다면, 그 격자의 주 원인이 무엇인지 (V·D 가 끌어올린 것인지)",
        "",
        "## 5. 등급별 실제 침수 발생률",
        "",
        "| 등급 | 격자 | 침수 격자 | 발생률 |",
        "|---|---:|---:|---:|",
    ]
    for row in m["incidence_by_grade"]:
        lines.append(f"| R{row['grade']} | {row['n']:,} | {row['positives']} | {row['incidence']:.2%} |")
    lines += [
        "",
        "등급이 오를수록 발생률이 오르는지 본다. 여기 쓴 라벨은 **전체 사상**이므로 "
        "등급 경계 산출에 쓴 사상이 섞여 있다. 순수한 out-of-sample 판정은 "
        "`METHODOLOGY.md` §7.5 를 본다.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def result_review(ctx: StageContext) -> dict[str, Any]:
    """통과: 기여도 4성분 합 = 1, TOP 20 이 한 행정동에 절반 넘게 몰리지 않음,
    독립 자료와의 중첩률을 보고. 중첩이 낮으면 '왜 다른가'를 result_review.md 에 남긴다."""
    from src.data import calibration as C

    cdri, top20 = _load_results()
    m: dict[str, Any] = {
        "contributions": _check_contributions(cdri),
        "dong_concentration": _check_dong_concentration(top20),
        "overlap_flood_map": _overlap_with_flood_map(top20, cdri),
        "overlap_traces": _overlap_with_traces(top20, cdri),
        "flood_risk_map": _flood_risk_status(),
    }
    labels = cdri["trace_label"].fillna(0).to_numpy()
    m["incidence_by_grade"] = C.incidence_table(cdri["grade_raw"].to_numpy(), labels)["rows"]

    findings = []
    if not m["contributions"]["ok"]:
        findings.append({"code": "contribution_sum", "detail": m["contributions"]})
    if not m["dong_concentration"]["ok"]:
        findings.append({"code": "dong_concentration", "detail": m["dong_concentration"]})
    if findings:
        raise StageFailed("결과 확인 통과 기준 미달", findings, metrics=m)

    figures = [o for o in ctx.outputs if o.suffix == ".png"]
    _distribution_figure(cdri, next(o for o in figures if "distribution" in o.name))
    _top20_figure(cdri, top20, next(o for o in figures if "top20" in o.name))
    _write_review(next(o for o in ctx.outputs if o.suffix == ".md"), m)
    return m
