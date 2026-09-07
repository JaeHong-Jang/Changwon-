"""H07 CDRI 통합·민감도 — 창원형 도시침수 선제대응 우선순위지수.

CDRI = f(Hazard, Exposure, Vulnerability, Capacity 부족도). 국제 표준 공식이 아니라
본 연구가 정의한 작업명이다 (RESEARCH_PLAN §0-4). 기본은 가중기하평균이며 근거는
IPCC AR5 의 세 요소 필요조건과 OECD/JRC(2008) 의 비보상성이다. 가법형은 병기해
Moreira et al.(2021) 이 지적한 기하평균의 과소평가 경향을 확인한다.

Layer 2(하수 역류)는 관로 비공개로 검증할 수 없어 **기본 산식에서 제외**하고 시나리오로만
넣는다 (docs/decisions/001-layer2-design.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT

COMPONENTS = ["H", "E", "V", "D"]
COMPONENT_LABELS = {
    "H": "Hazard 물리적 침수위험 (Layer 1)",
    "E": "Exposure 노출 (인구·주택 수)",
    "V": "Vulnerability 취약성 (65세 이상 비율)",
    "D": "Capacity 부족도 (1 - 대피소·방재기관 접근성)",
}
LAYER2_PATH = "data/processed/layers/layer2_sewer.gpkg"


def cdri(ctx: StageContext) -> dict[str, Any]:
    """통과: 가중치·집계형 변형 사이 중위 Spearman ρ ≥ params.min_spearman,
    TOP 20 중첩 ≥ params.min_top20_overlap, Capacity 결측 0 대체 없음."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from scipy.stats import spearmanr

    from src.data import layers as L

    p = ctx.params
    top_n = int(p["cdri.top_n"])
    floor = float(p["cdri.rescale_floor"])
    min_rho = float(p["cdri.min_spearman"])
    min_overlap = int(p["cdri.min_top20_overlap"])

    layer1 = gpd.read_file(PROJECT_ROOT / "data/processed/layers/layer1_flood.gpkg", layer="layer1_flood")
    layer3 = gpd.read_file(PROJECT_ROOT / "data/processed/layers/layer3_vuln.gpkg", layer="layer3_vuln")
    df = layer3.merge(
        layer1[["grid_id", "L1", "vulnerability_grade", "z_exposure", "z_sensitivity"]], on="grid_id", how="inner"
    )
    df = gpd.GeoDataFrame(df, geometry="geometry", crs=layer3.crs)
    universe = df["universe"].to_numpy().astype(bool)
    m: dict[str, Any] = {
        "n_grid": int(len(df)),
        "n_universe": int(universe.sum()),
        "components": COMPONENT_LABELS,
        "layer2_included_in_primary": False,
        "layer2_reason": "관로 비공개로 검증 불가 — docs/decisions/001-layer2-design.md",
    }

    # 순위 대상 격자만으로 재척도한다. 무인구 격자는 지도 표기용으로만 남는다.
    sub = df.loc[universe].copy()
    matrix = np.column_stack([
        L.rescale_positive(sub["L1"].to_numpy(), floor),
        L.rescale_positive(sub["E"].to_numpy(), floor),
        L.rescale_positive(sub["V"].to_numpy(), floor),
        L.rescale_positive(sub["capacity_deficit"].to_numpy(), floor),
    ])
    if not np.isfinite(matrix).all():
        raise StageFailed(
            "구성요소에 결측이 있다 — 0 으로 대체하지 않고 중단한다",
            [{"code": "component_missing", "detail": COMPONENTS}],
            metrics=m,
        )

    weights = {
        "equal": np.full(len(COMPONENTS), 1.0 / len(COMPONENTS)),
        "entropy": L.entropy_weights(matrix),
    }
    m["weights"] = {k: [round(float(x), 4) for x in v] for k, v in weights.items()}
    m["weights_note"] = "AHP 3안은 전문가 설문 미수집 — 동일·엔트로피 2안만 비교 (ANALYSIS_PLAN §5)"

    variants: dict[str, np.ndarray] = {}
    for weight_name, weight in weights.items():
        variants[f"geometric_{weight_name}"] = L.geometric_aggregate(matrix, weight)
        variants[f"additive_{weight_name}"] = L.additive_aggregate(matrix, weight)

    # Layer 2 가 있으면 H = 0.5·L1 + 0.5·L2 시나리오를 하나 더 만든다 (기본 산식은 아니다).
    layer2_path = PROJECT_ROOT / LAYER2_PATH
    if layer2_path.exists():
        layer2 = gpd.read_file(layer2_path, layer="layer2_sewer")[["grid_id", "L2"]]
        merged = sub[["grid_id"]].merge(layer2, on="grid_id", how="left")
        l2 = merged["L2"].to_numpy(dtype=float)
        coverage = float(np.isfinite(l2).mean())
        blended = np.where(np.isfinite(l2), 0.5 * sub["L1"].to_numpy() + 0.5 * l2, sub["L1"].to_numpy())
        scenario = matrix.copy()
        scenario[:, 0] = L.rescale_positive(blended, floor)
        variants["geometric_equal_with_layer2"] = L.geometric_aggregate(scenario, weights["equal"])
        m["layer2_scenario"] = {"coverage": round(coverage, 4), "note": "H = 0.5·L1 + 0.5·L2, 관로 미커버 격자는 L1 단독"}

    primary_name = "geometric_equal"
    primary = variants[primary_name]
    m["primary_formula"] = primary_name

    # ── 민감도: 변형 간 순위 상관과 TOP N 중첩 ────────────────────────────
    def top_ids(values: np.ndarray) -> set[str]:
        order = np.argsort(-values, kind="stable")[:top_n]
        return set(sub["grid_id"].to_numpy()[order])

    primary_top = top_ids(primary)
    rows = []
    for name, values in variants.items():
        rho = float(spearmanr(primary, values).statistic)
        overlap = len(primary_top & top_ids(values))
        rows.append({
            "variant": name,
            "spearman_rho_vs_primary": round(rho, 4),
            f"top{top_n}_overlap": overlap,
            f"top{top_n}_overlap_pct": round(overlap / top_n, 3),
        })
    others = [r for r in rows if r["variant"] != primary_name]
    median_rho = float(np.median([r["spearman_rho_vs_primary"] for r in others]))
    min_overlap_seen = int(min(r[f"top{top_n}_overlap"] for r in others))
    # 모든 변형의 TOP N 에 공통으로 드는 격자 = 가중치·집계형 선택과 무관하게 위험한 곳
    robust_core = set.intersection(*(top_ids(v) for v in variants.values()))
    m["variants"] = rows
    m["robust_core"] = {
        "n": len(robust_core),
        "note": f"가중치·집계형 변형 {len(variants)}개 모두의 TOP {top_n} 에 공통으로 드는 격자",
    }

    # ── MAUP: 500m 재집계 후 순위가 유지되는가 ────────────────────────────
    centroids = sub.geometry.centroid
    block = (np.floor(centroids.x / 500).astype(int).astype(str) + "_"
             + np.floor(centroids.y / 500).astype(int).astype(str))
    coarse = pd.DataFrame({"block": block.to_numpy(), "cdri": primary}).groupby("block")["cdri"]
    maup_rho = float(spearmanr(coarse.mean(), coarse.max()).statistic)
    m["maup"] = {
        "resolution_m": 500,
        "n_blocks": int(coarse.ngroups),
        "spearman_rho_mean_vs_max": round(maup_rho, 4),
        "note": "500m 블록의 평균과 최대 재집계 순위 비교 (Fontecha et al. 2021 해상도 비교 논리)",
    }

    # ── 등급화 민감도: Balica 5등급 vs Jenks 5등급 ────────────────────────
    primary_scaled = L.minmax(primary)
    balica = L.balica_tier(primary_scaled)
    jenks = L.classify(primary_scaled, L.jenks_breaks(primary_scaled, len(L.BALICA_LABELS)))
    jenks_labels = np.asarray(L.BALICA_LABELS, dtype=object)[jenks - 1]
    m["tiering"] = {
        "balica_counts": {k: int(v) for k, v in pd.Series(balica).value_counts().items()},
        "jenks_counts": {k: int(v) for k, v in pd.Series(jenks_labels).value_counts().items()},
        "cohen_kappa": round(L.cohen_kappa(balica, jenks_labels), 4),
        "note": "Moreira et al.(2021) 은 등급화가 가장 민감하다고 지적한다. 두 방식을 병기한다",
    }

    # ── 기여도 (가법형 구성비) ────────────────────────────────────────────
    shares = L.contribution_share(matrix, weights["equal"], COMPONENTS)
    for key, values in shares.items():
        sub[f"{key.lower()}_contribution"] = values
    sub["primary_cause"] = np.asarray(COMPONENTS)[np.column_stack(list(shares.values())).argmax(axis=1)]

    sub["cdri"] = primary_scaled
    sub["cdri_raw"] = primary
    sub["cdri_additive"] = L.minmax(variants["additive_equal"])
    sub["risk_tier"] = balica
    sub["jenks_tier"] = jenks_labels
    sub["rank"] = (-sub["cdri"]).rank(method="first").astype(int)
    sub["in_robust_core"] = sub["grid_id"].isin(robust_core).astype("int8")
    for name, column in zip(COMPONENTS, ["H_scaled", "E_scaled", "V_scaled", "D_scaled"]):
        sub[column] = matrix[:, COMPONENTS.index(name)]

    m["cdri_summary"] = {
        "mean": round(float(sub["cdri"].mean()), 4),
        "p50": round(float(sub["cdri"].median()), 4),
        "p90": round(float(sub["cdri"].quantile(0.9)), 4),
        "primary_cause_counts": {k: int(v) for k, v in sub["primary_cause"].value_counts().items()},
    }
    # 강건성 판정. 미달이면 **실패가 아니라 분기**다 — 하네스 H07 on_fail 은 goto 없이
    # "정밀 순위 대신 위험군(tier) 모드로 보고"라고 정했다. 임계값을 낮추는 재튜닝은 금지이므로
    # 기준은 그대로 두고 산출물의 성격을 바꾼다.
    unmet = []
    if median_rho < min_rho:
        unmet.append(f"중위 Spearman ρ {round(median_rho, 4)} < {min_rho}")
    if min_overlap_seen < min_overlap:
        unmet.append(f"TOP {top_n} 최소 중첩 {min_overlap_seen} < {min_overlap}")
    ranking_mode = "rank" if not unmet else "tier"
    m["robustness"] = {
        "median_spearman_rho": round(median_rho, 4),
        "min_spearman_rho": round(float(min(r["spearman_rho_vs_primary"] for r in others)), 4),
        f"min_top{top_n}_overlap": min_overlap_seen,
        "min_spearman_required": min_rho,
        "min_overlap_required": min_overlap,
        "unmet": unmet,
    }
    m["ranking_mode"] = ranking_mode
    m["ranking_mode_note"] = (
        "정밀 순위 보고 가능" if ranking_mode == "rank" else
        "정밀 순위를 주장하지 않는다. 위험군(tier)과 강건 공통집합으로만 보고한다 — 하네스 H07 분기"
    )

    # ── 산출물 ───────────────────────────────────────────────────────────
    gpkg = next(o for o in ctx.outputs if o.suffix == ".gpkg")
    csv = next(o for o in ctx.outputs if o.suffix == ".csv")
    manifest_path = next(o for o in ctx.outputs if o.suffix == ".json")

    keep = [
        "grid_id", "adm_cd", "gu_code", "rank", "cdri", "cdri_raw", "cdri_additive",
        "risk_tier", "jenks_tier", "primary_cause", "in_robust_core",
        "H_scaled", "E_scaled", "V_scaled", "D_scaled",
        "h_contribution", "e_contribution", "v_contribution", "d_contribution",
        "L1", "E", "V", "capacity_deficit", "pop_total", "houses", "elderly_ratio",
        "shelter_dist_m", "vulnerability_grade", "geometry",
    ]
    gpkg.parent.mkdir(parents=True, exist_ok=True)
    if gpkg.exists():
        gpkg.unlink()
    sub[keep].to_file(gpkg, layer="cdri", driver="GPKG")

    csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(csv, index=False, encoding="utf-8-sig")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "primary_formula": primary_name,
        "definition": "CDRI = Π (X_k ^ w_k), X ∈ {H, E, V, D}, 각 [floor, 1] 재척도",
        "components": COMPONENT_LABELS,
        "weights": m["weights"]["equal"],
        "weight_scheme": "equal",
        "rescale_floor": floor,
        "universe_rule": "pop_total > 0 또는 houses >= 1",
        "n_universe": int(universe.sum()),
        "layer2_included": False,
        "ranking_mode": ranking_mode,
        "ranking_mode_note": m["ranking_mode_note"],
        "robustness_unmet": unmet,
        "robust_core_n": len(robust_core),
        "decision": "docs/decisions/001-layer2-design.md",
        "run_id": ctx.run_id,
        "retuning_prohibited": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    _cdri_map(df, sub, PROJECT_ROOT / "reports/figures/cdri_map.png")
    return m


def _cdri_map(df, sub, out: Path) -> None:
    import matplotlib.pyplot as plt

    from src.visualization import style

    style.apply()
    merged = df[["grid_id", "geometry"]].merge(
        sub[["grid_id", "cdri", "primary_cause"]], on="grid_id", how="left"
    )
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    merged.plot(column="cdri", ax=axes[0], linewidth=0, legend=True, cmap="magma_r",
                legend_kwds={"shrink": 0.6}, missing_kwds={"color": "0.92"})
    axes[0].set_title("CDRI 우선대응 지수 (회색 = 순위 대상 밖)", fontsize=10)
    merged.plot(column="primary_cause", ax=axes[1], linewidth=0, legend=True, cmap="Set2",
                missing_kwds={"color": "0.92"})
    axes[1].set_title("주 원인 (가법형 기여도 최대 요소)", fontsize=10)
    for ax in axes:
        ax.set_axis_off()
        ax.grid(False)
    fig.tight_layout()
    style.save(fig, out)
