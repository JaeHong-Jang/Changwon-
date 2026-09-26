"""CDRI 설계 선택에 따른 순위와 우선대상의 불확실성을 계산한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.data import layers as L
from src.data.index_design import (AGGREGATIONS, COMPONENT_SETS, DEFAULT_REPLICATES, DEFAULT_SEED,
                                   FACTOR_LEVELS, FLOORS, NORMALIZATIONS, RAW_COLUMNS, WEIGHT_MODES,
                                   _normalise, design_combinations)

def _rank_first(scores: np.ndarray) -> np.ndarray:
    """기존 rank(method='first')와 같은 내림차순 순위를 만든다."""
    # 같은 점수에는 입력 순서대로 순위를 부여한다.
    ranks = np.empty(len(scores), dtype=np.int16 if len(scores) <= 32767 else np.int32)
    ranks[np.argsort(-scores, kind="stable")] = np.arange(1, len(scores) + 1)
    return ranks


def _nms(scores: np.ndarray, xy: np.ndarray, limit: int = 20, radius_m: float = 300.0) -> np.ndarray:
    """H08의 안정 정렬과 단계별 후보 확장을 따라 NMS를 수행한다."""
    # 우선순위가 높은 격자부터 시작하고 필요할 때 후보 창을 넓힌다.
    order = np.argsort(-scores, kind="stable")
    head = min(len(order), max(limit * 30, 512))
    while True:
        chosen: list[int] = []
        for idx in order[:head]:
            if not chosen or np.hypot(*(xy[idx] - xy[chosen]).T).min() >= radius_m:
                chosen.append(int(idx))
                if len(chosen) == limit:
                    return np.asarray(chosen, dtype=int)
        if head == len(order):
            return np.asarray(chosen, dtype=int)
        head = min(len(order), head * 2)


def _main_effects(values: np.ndarray, designs, metric: str) -> list[dict]:
    """각 격자 출력의 조건부 평균 분산을 전체 설계 분산과 비교한다."""
    # 전체 설계 변동을 격자별 제곱편차 합으로 구한다.
    y = np.asarray(values, dtype=float)
    mean = y.mean(axis=0)
    total = np.square(y - mean).mean(axis=0).sum()

    # 각 요인의 수준별 조건부 평균 변동을 기록한다.
    rows = []
    for factor, levels in FACTOR_LEVELS.items():
        between = 0.0
        for level in levels:
            mask = designs[factor].eq(level).to_numpy()
            between += float(mask.mean()) * np.square(y[mask].mean(axis=0) - mean).sum()
        rows.append({
            "metric": metric,
            "factor": factor,
            "first_order_variance": between,
            "total_variance": float(total),
            "first_order_ratio": between / total if total else 0.0,
        })
    return rows


def _distribution(values: np.ndarray) -> dict:
    """설계 간 분포의 최소·분위수·최대를 기록한다."""
    # 5·50·95 분위수와 양 끝값을 반환한다.
    v = np.asarray(values, dtype=float)
    q = np.quantile(v, [0.05, 0.5, 0.95])
    return {"min": float(v.min()), "p05": float(q[0]), "median": float(q[1]),
            "p95": float(q[2]), "max": float(v.max())}


def analyse(frame, *, replicates: int = DEFAULT_REPLICATES, seed: int = DEFAULT_SEED,
            top_n: int = 20, radius_m: float = 300.0):
    """기준값 재현 후 독립 요인 전 조합을 반복 추출해 결과를 돌려준다."""
    import pandas as pd
    from scipy.stats import spearmanr

    # 요청한 설계 수와 입력 격자의 키·값·좌표계를 확인한다.
    if replicates < 14:  # 72 조합 × 14회 = 1008 설계
        raise ValueError("72개 전 조합에서 최소 14회 반복해 N≥1000을 충족해야 한다")
    if not (0 < top_n <= len(frame)):
        raise ValueError("top_n은 순위 대상 수 이하여야 한다")
    if frame["grid_id"].duplicated().any():
        raise ValueError("grid_id 중복")
    raw = frame[list(RAW_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(raw).all():
        raise ValueError("구성요소에 결측 또는 비유한값이 있다")
    if not frame.crs or frame.crs.to_epsg() != 5179:
        raise ValueError("좌표계는 EPSG:5179여야 한다")
    centroid = frame.geometry.centroid
    xy = np.column_stack((centroid.x.to_numpy(), centroid.y.to_numpy()))

    # 저장된 기준 점수·순위와 재계산 결과를 정확히 비교한다.
    baseline_matrix = _normalise(raw, 0.05, "minmax")
    baseline_raw = L.geometric_aggregate(baseline_matrix, np.full(4, 0.25))
    baseline = L.minmax(baseline_raw)
    baseline_rank = _rank_first(baseline)
    actual_cdri = frame["cdri"].to_numpy(dtype=float)
    actual_rank = frame["rank"].to_numpy(dtype=int)
    if not np.array_equal(baseline, actual_cdri) or not np.array_equal(baseline_rank, actual_rank):
        raise ValueError("기준 설계가 cdri.gpkg의 cdri·rank를 정확히 재현하지 못한다")
    baseline_top = _nms(baseline, xy, top_n, radius_m)

    # 설계 조합별 정규화 행렬을 재사용하며 고정 난수열을 준비한다.
    cache = {(floor, method): _normalise(raw, floor, method)
             for floor in FLOORS for method in NORMALIZATIONS}
    rng = np.random.default_rng(seed)
    ranks: list[np.ndarray] = []
    inclusion: list[np.ndarray] = []
    records = []
    baseline_set = set(baseline_top)

    # 각 설계와 반복의 순위·NMS 포함 여부·기준 대비 지표를 기록한다.
    for floor, method, aggregation, weight_mode, components in design_combinations():
        matrix = cache[(floor, method)][:, :len(components)]
        equal = np.full(matrix.shape[1], 1.0 / matrix.shape[1])
        fixed_weight = L.entropy_weights(matrix) if weight_mode == "entropy" else equal
        for repeat in range(replicates):
            weights = rng.dirichlet(10.0 * equal) if weight_mode == "dirichlet" else fixed_weight
            scores = (L.geometric_aggregate(matrix, weights) if aggregation == "geometric"
                      else L.additive_aggregate(matrix, weights))
            rank = _rank_first(scores)
            selected = _nms(scores, xy, top_n, radius_m)
            included = np.zeros(len(frame), dtype=np.uint8)
            included[selected] = 1
            ranks.append(rank)
            inclusion.append(included)
            records.append({
                "floor": floor, "normalization": method, "aggregation": aggregation,
                "weights": weight_mode, "components": components, "repeat": repeat,
                "spearman_vs_baseline": float(spearmanr(baseline, scores).statistic),
                "top20_overlap": len(baseline_set.intersection(selected)),
            })

    # 전체 설계의 격자별 우선대상 포함 횟수와 순위 구간을 집계한다.
    rank_values = np.stack(ranks)
    inclusion_values = np.stack(inclusion)
    designs = pd.DataFrame.from_records(records)
    probability = inclusion_values.mean(axis=0)
    grid = pd.DataFrame({
        "grid_id": frame["grid_id"].to_numpy(), "baseline_rank": baseline_rank,
        "baseline_top20_nms": np.isin(np.arange(len(frame)), baseline_top).astype(int),
        "in_robust_core": frame["in_robust_core"].to_numpy(dtype=int),
        "top20_count": inclusion_values.sum(axis=0), "top20_probability": probability,
    })
    candidate = (rank_values <= 50).any(axis=0)
    low, high = np.quantile(rank_values[:, candidate], [0.05, 0.95], axis=0)
    rank90 = grid.loc[candidate, ["grid_id", "baseline_rank", "top20_probability"]].copy()
    rank90["rank_p05"] = low
    rank90["rank_p95"] = high
    rank90["rank_min"] = rank_values[:, candidate].min(axis=0)
    rank90["rank_max"] = rank_values[:, candidate].max(axis=0)

    # 요인별 변동 기여와 강건 우선대상 격자를 구한다.
    effects = pd.DataFrame(_main_effects(rank_values, designs, "rank") +
                           _main_effects(inclusion_values, designs, "top20_inclusion"))
    robust = grid.loc[grid.top20_probability >= 0.8].sort_values(
        ["top20_probability", "baseline_rank"], ascending=[False, True]
    ).copy()
    core = grid.in_robust_core.eq(1)
    robust_ids = set(robust.grid_id)
    core_ids = set(grid.loc[core, "grid_id"])

    # 실행 설정·분포·기준 재현·강건성 결과를 원래 키 구조로 요약한다.
    summary = {
        "input": "data/processed/layers/cdri.gpkg:cdri",
        "run_id": f"index_uncertainty_s{seed}_r{replicates}",
        "seed": seed, "replicates_per_combination": replicates,
        "design_count": len(designs), "n_grid": len(frame), "top_n": top_n,
        "distinct_parameter_settings": 48 + 24 * replicates,
        "dirichlet_draw_count": 24 * replicates,
        "nms_radius_m": radius_m,
        "factor_levels": {key: list(levels) for key, levels in FACTOR_LEVELS.items()},
        "dirichlet_alpha": "10 × equal weight (4 components: 2.5 each; 3 components: 10/3 each)",
        "percentile_rule": "pandas rank(method='average', pct=True), then floor + (1-floor)*pct",
        "rank_rule": "descending, first tie break in original row order",
        "baseline": {"exact_cdri": True, "exact_rank": True,
                     "top20_grid_ids": frame.iloc[baseline_top].grid_id.tolist()},
        "spearman_vs_baseline": _distribution(designs.spearman_vs_baseline.to_numpy()),
        "top20_overlap": _distribution(designs.top20_overlap.to_numpy()),
        "rank90_candidate_count": int(candidate.sum()),
        "robust_priority_threshold": 0.8, "robust_priority_count": len(robust),
        "existing_robust_core_count": len(core_ids),
        "robust_and_existing_core": sorted(robust_ids & core_ids),
        "robust_only": sorted(robust_ids - core_ids),
        "existing_core_only": sorted(core_ids - robust_ids),
        "effects_rule": "first-order Var(E[Y|factor])/Var(Y), summed over grids; rank and NMS inclusion separately",
        "effects_note": "first-order ratios need not sum to one; interactions and Dirichlet draws remain",
        "method_reference": "Saisana et al. (2005), doi:10.1111/j.1467-985X.2005.00350.x",
        "aggregation_reference": "Greco et al. (2019), doi:10.1007/s11205-017-1832-9",
        "document_correction_proposal": (
            "METHODOLOGY §2.3·§5.1의 '비보상 집계'를 '보상이 제한되는 기하 집계'로 고친다. "
            "[0.05,1] 재척도 후 입력 요소는 0이 될 수 없으므로 '0이면 전체 0'을 현행 산식의 설명으로 쓰지 않는다."
        ),
    }
    return grid, rank90, robust, effects, designs, summary


def main() -> None:
    """확정된 격자만 읽고 불확실성 산출물을 .omc 아래에 저장한다."""
    import argparse
    import geopandas as gpd

    # 명령행 인수를 읽고 확정된 격자만 분석한다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    frame = gpd.read_file("data/processed/layers/cdri.gpkg", layer="cdri")
    grid, rank90, robust, effects, designs, summary = analyse(
        frame, replicates=args.replicates, seed=args.seed
    )

    # H08의 기존 NMS 결과와 기준 상위 격자를 교차 확인한다.
    from src.stages.h08_policy import _suppress_neighbours

    # 기준 설계의 TOP20 이 H08 선정과 다르면 중단한다.
    reference_top = _suppress_neighbours(frame, 300.0, 20).grid_id.tolist()
    if summary["baseline"]["top20_grid_ids"] != reference_top:
        raise ValueError("NMS 구현이 H08 기준 TOP20을 재현하지 못한다")
    summary["baseline"]["exact_h08_nms_top20"] = True

    # 다섯 CSV와 요약 JSON을 같은 경로·형식으로 저장한다.
    output = Path(".omc/uncertainty")
    output.mkdir(parents=True, exist_ok=True)
    grid.to_csv(output / "top20_inclusion.csv", index=False)
    rank90.to_csv(output / "rank90_top50.csv", index=False)
    robust.to_csv(output / "robust_priorities.csv", index=False)
    effects.to_csv(output / "design_effects.csv", index=False)
    designs.to_csv(output / "design_metrics.csv", index=False)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in (
        "run_id", "design_count", "n_grid", "rank90_candidate_count", "robust_priority_count",
        "existing_robust_core_count", "spearman_vs_baseline", "top20_overlap"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
