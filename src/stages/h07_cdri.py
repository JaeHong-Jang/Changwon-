"""H07 CDRI 통합·민감도 — 창원형 도시침수 선제대응 우선순위지수.

CDRI = f(Hazard, Exposure, Vulnerability, Capacity 부족도). 국제 표준 공식이 아니라
본 연구가 정의한 작업명이다 (RESEARCH_PLAN §0-4). 기본은 가중기하평균이며 근거는
IPCC AR5 의 세 요소 필요조건과 OECD/JRC(2008) 의 비보상성이다. 가법형은 병기해
Moreira et al.(2021) 이 지적한 기하평균의 과소평가 경향을 확인한다.

Layer 2(하수 역류)는 관로 비공개로 검증할 수 없어 **기본 산식에서 제외**하고 시나리오로만
넣는다 (docs/decisions/001-layer2-design.md).

최종 등급은 R1~R5 오름차순이며 5가 가장 위험하다 (docs/CDRI_GRADE_SYSTEM.md, decisions/003).
검증용 `grade_raw` 와 대응표용 `grade_final` 을 분리한다.

이 파일은 **단계를 조립**한다. 계산 자체는 `src/data/layers.py`(정규화·집계·통계)와
`src/data/grades.py`(등급 체계)에 있다. 아래 `_` 함수들은 `cdri()` 가 너무 길어져
읽기 어려워지는 것을 막으려고 단계별로 끊어 둔 것이며, 각각 하나의 질문에 답한다.
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
LAYER1_PATH = "data/processed/layers/layer1_flood.gpkg"
LAYER2_PATH = "data/processed/layers/layer2_sewer.gpkg"
LAYER3_PATH = "data/processed/layers/layer3_vuln.gpkg"
DONG_NAME_PATH = "data/external/adm_dong_names.csv"
MAUP_BLOCK_M = 500

# 산출 gpkg 에 남길 열. 순서가 곧 표의 순서다.
OUTPUT_COLUMNS = [
    "grid_id", "adm_cd", "gu_code", "rank", "cdri", "cdri_raw", "cdri_additive",
    "grade_raw", "grade_final", "grade_jenks", "grade_balica", "grade_percentile",
    "grade_code", "grade_name",
    "grade_review_flag", "primary_cause", "in_robust_core",
    "H_scaled", "E_scaled", "V_scaled", "D_scaled",
    "h_contribution", "e_contribution", "v_contribution", "d_contribution",
    "h_percentile", "e_percentile", "v_percentile", "d_percentile",
    "L1", "E", "V", "capacity_deficit", "pop_total", "houses", "elderly_ratio",
    "shelter_dist_m", "vulnerability_grade", "geometry",
]


def _load_layers():
    """Layer 1·3 을 grid_id 로 붙인다. 두 레이어가 같은 격자 집합이어야 CDRI 가 성립한다."""
    import geopandas as gpd

    layer1 = gpd.read_file(PROJECT_ROOT / LAYER1_PATH, layer="layer1_flood")
    layer3 = gpd.read_file(PROJECT_ROOT / LAYER3_PATH, layer="layer3_vuln")
    joined = layer3.merge(
        layer1[["grid_id", "L1", "vulnerability_grade", "z_exposure", "z_sensitivity"]],
        on="grid_id", how="inner",
    )
    return gpd.GeoDataFrame(joined, geometry="geometry", crs=layer3.crs)


def _component_matrix(sub, floor: float):
    """네 구성요소를 [floor, 1] 로 재척도한 (n × 4) 행렬.

    하한을 0 이 아니라 floor 로 두는 이유: minmax 는 최솟값을 정확히 0 으로 만드는데,
    기하평균에서 0 하나면 전체가 0 이 되어 순위 정보가 통째로 사라진다.
    """
    import numpy as np

    from src.data import layers as L

    return np.column_stack([
        L.rescale_positive(sub["L1"].to_numpy(), floor),
        L.rescale_positive(sub["E"].to_numpy(), floor),
        L.rescale_positive(sub["V"].to_numpy(), floor),
        L.rescale_positive(sub["capacity_deficit"].to_numpy(), floor),
    ])


def _build_variants(matrix, sub, floor: float) -> tuple[dict, dict, dict[str, Any]]:
    """가중치(동일·엔트로피) × 집계형(곱셈·가법) 조합을 만든다. 민감도 판정의 입력이다.

    Layer 2 산출물이 있으면 H = 0.5·L1 + 0.5·L2 시나리오를 하나 더 얹는다.
    기본 산식에는 넣지 않는다 (decisions/001).
    """
    import geopandas as gpd
    import numpy as np

    from src.data import layers as L

    weights = {
        "equal": np.full(len(COMPONENTS), 1.0 / len(COMPONENTS)),
        "entropy": L.entropy_weights(matrix),
    }
    variants: dict[str, np.ndarray] = {}
    for name, weight in weights.items():
        variants[f"geometric_{name}"] = L.geometric_aggregate(matrix, weight)
        variants[f"additive_{name}"] = L.additive_aggregate(matrix, weight)

    meta: dict[str, Any] = {
        "weights": {k: [round(float(x), 4) for x in v] for k, v in weights.items()},
        "weights_note": "AHP 3안은 전문가 설문 미수집 — 동일·엔트로피 2안만 비교 (ANALYSIS_PLAN §5)",
    }

    layer2_path = PROJECT_ROOT / LAYER2_PATH
    if layer2_path.exists():
        layer2 = gpd.read_file(layer2_path, layer="layer2_sewer")[["grid_id", "L2"]]
        l2 = sub[["grid_id"]].merge(layer2, on="grid_id", how="left")["L2"].to_numpy(dtype=float)
        covered = np.isfinite(l2)
        blended = np.where(covered, 0.5 * sub["L1"].to_numpy() + 0.5 * l2, sub["L1"].to_numpy())
        scenario = matrix.copy()
        scenario[:, 0] = L.rescale_positive(blended, floor)
        variants["geometric_equal_with_layer2"] = L.geometric_aggregate(scenario, weights["equal"])
        meta["layer2_scenario"] = {
            "coverage": round(float(covered.mean()), 4),
            "note": "H = 0.5·L1 + 0.5·L2, 관로 미커버 격자는 L1 단독",
        }
    return variants, weights, meta


def _assess_robustness(variants: dict, primary_name: str, grid_ids, top_n: int) -> dict[str, Any]:
    """변형 간 순위가 얼마나 흔들리는지 잰다. 상위 목록은 한 번만 계산해 재사용한다."""
    import numpy as np
    from scipy.stats import spearmanr

    def top_set(values) -> set[str]:
        """점수 상위 top_n 격자의 grid_id 집합."""
        return set(grid_ids[np.argsort(-values, kind="stable")[:top_n]])

    tops = {name: top_set(values) for name, values in variants.items()}
    primary = variants[primary_name]

    rows = [
        {
            "variant": name,
            "spearman_rho_vs_primary": round(float(spearmanr(primary, values).statistic), 4),
            f"top{top_n}_overlap": len(tops[primary_name] & tops[name]),
            f"top{top_n}_overlap_pct": round(len(tops[primary_name] & tops[name]) / top_n, 3),
        }
        for name, values in variants.items()
    ]
    others = [r for r in rows if r["variant"] != primary_name]
    return {
        "rows": rows,
        "median_rho": float(np.median([r["spearman_rho_vs_primary"] for r in others])),
        "min_rho": float(min(r["spearman_rho_vs_primary"] for r in others)),
        "min_overlap": int(min(r[f"top{top_n}_overlap"] for r in others)),
        # 모든 변형의 상위 목록에 공통으로 드는 격자 = 산식 선택과 무관하게 위험한 곳
        "robust_core": set.intersection(*tops.values()),
    }


def _maup_check(sub, primary) -> dict[str, Any]:
    """해상도를 500m 로 낮춰도 순위가 유지되는지 본다 (Fontecha et al. 2021)."""
    import numpy as np
    import pandas as pd
    from scipy.stats import spearmanr

    centroids = sub.geometry.centroid
    block = (np.floor(centroids.x / MAUP_BLOCK_M).astype(int).astype(str) + "_"
             + np.floor(centroids.y / MAUP_BLOCK_M).astype(int).astype(str))
    coarse = pd.DataFrame({"block": block.to_numpy(), "cdri": primary}).groupby("block")["cdri"]
    return {
        "resolution_m": MAUP_BLOCK_M,
        "n_blocks": int(coarse.ngroups),
        "spearman_rho_mean_vs_max": round(float(spearmanr(coarse.mean(), coarse.max()).statistic), 4),
        "note": "500m 블록의 평균과 최대 재집계 순위 비교",
    }


def _attach_contributions(sub, matrix, weights):
    """기여도(가법형 구성비)와 백분위를 sub 에 붙이고 주 원인을 정한다. 백분위 행렬을 돌려준다.

    **주 원인은 최대 백분위 요소**다 (ANALYSIS_PLAN §5). 구성비의 최댓값을 쓰면 분포가
    치우친 요소(인구)가 거의 항상 이겨서 조치가 한쪽으로 쏠린다.
    """
    import numpy as np
    import pandas as pd

    from src.data import layers as L

    for key, values in L.contribution_share(matrix, weights, COMPONENTS).items():
        sub[f"{key.lower()}_contribution"] = values
    percentiles = np.column_stack([
        pd.Series(matrix[:, i]).rank(pct=True).to_numpy() for i in range(len(COMPONENTS))
    ])
    for i, key in enumerate(COMPONENTS):
        sub[f"{key.lower()}_percentile"] = percentiles[:, i]
    sub["primary_cause"] = np.asarray(COMPONENTS)[percentiles.argmax(axis=1)]
    return percentiles


TRACE_LABEL_COLUMNS = ("trace_label", "trace_label_cal", "trace_label_val")


def _load_trace_labels(grid_ids) -> dict[str, Any] | None:
    """Layer 1 이 남긴 침수흔적 라벨을 순위 대상 격자 순서에 맞춰 읽는다.

    전체·캘리브레이션 기간·검증 기간 세 벌을 함께 가져온다. 경계를 맞출 때와 채점할 때
    서로 다른 사상을 써야 in-sample 순환이 생기지 않기 때문이다.
    """
    import geopandas as gpd
    import numpy as np
    import pandas as pd

    available = gpd.read_file(PROJECT_ROOT / LAYER1_PATH, layer="layer1_flood", rows=1).columns
    present = [c for c in TRACE_LABEL_COLUMNS if c in available]
    if "trace_label" not in present:
        return None
    labelled = gpd.read_file(
        PROJECT_ROOT / LAYER1_PATH, layer="layer1_flood", columns=["grid_id", *present]
    )
    aligned = pd.DataFrame({"grid_id": grid_ids}).merge(labelled, on="grid_id", how="left")
    out = {
        name.replace("trace_label", "").strip("_") or "all":
            aligned[name].fillna(0).to_numpy().astype(np.int8)
        for name in present
    }
    out["has_time_split"] = bool("cal" in out and "val" in out and out["cal"].sum() and out["val"].sum())
    return out


def _grade_validation(grades, val_labels, p, n_classes: int = 5) -> dict[str, Any]:
    """검증 기간 사상으로 등급을 채점한다 — 경계를 맞추지 않은 사상이라 out-of-sample 이다.

    판정은 단조성과 **효과크기**를 함께 본다. 격자가 수만 개면 p 값은 거의 항상 유의해서
    p 만으로는 아무것도 말하지 못한다 (CDRI_GRADE_SYSTEM 지적사항 13).
    lift 기준은 최상위·차상위 등급에 건다. 통합 등급이면 남은 등급 중 그 둘에 적용된다.
    """
    from src.data import calibration as C

    table = C.incidence_table(grades, val_labels, n_classes)
    ratios = [r for r in table["adjacent_ratios"] if r is not None]
    lift_top = table["rows"][-1]["lift"]
    lift_second = table["rows"][-2]["lift"] if n_classes >= 2 else None
    min_ratio = float(p["cdri.calibration_min_ratio"])
    table["criteria"] = {
        "monotone": table["monotone"],
        "trend_significant": table["p_value"] < float(p["cdri.calibration_trend_p_max"]),
        "all_adjacent_ratios_met": bool(ratios) and min(ratios) >= min_ratio,
        "lift_top_met": lift_top is not None and lift_top >= float(p["cdri.calibration_lift_r5_min"]),
        "lift_second_met": lift_second is not None and lift_second >= float(p["cdri.calibration_lift_r4_min"]),
    }
    table["failed_criteria"] = [k for k, ok in table["criteria"].items() if not ok]
    table["passed"] = not table["failed_criteria"]
    table["sample"] = "out-of-sample (검증 기간 사상)"
    return table


def _reporting_constraint(validation: dict[str, Any], min_ratio: float, lift_min: float) -> dict[str, Any]:
    """검증 결과로 **무엇을 주장해도 되는지**를 정한다. 보고서 문장을 코드가 제한한다.

    등급 체계가 판정 기준을 다 통과하지 못했을 때, 통과한 부분까지 버릴 이유는 없고
    통과하지 못한 부분을 주장할 권리도 없다. 그 선을 사람 판단이 아니라 지표가 긋게 한다.
    """
    table = validation["calibration"]
    return {
        "monotone_claim_allowed": table["monotone"] and table["criteria"]["trend_significant"],
        # 기저 대비 lift 가 기준 이상인 등급만 "실제로 더 자주 잠긴다"고 말할 수 있다.
        "separable_grades": [
            f"R{r['grade']}" for r in table["rows"]
            if r["lift"] is not None and r["lift"] >= lift_min
        ],
        # 인접 발생률 비가 기준에 못 미친 쌍은 떼어 주장하지 않고 통합 단계로 보고한다.
        "pairs_not_separable": [
            f"R{i + 1}-R{i + 2}" for i, ratio in enumerate(table["adjacent_ratios"])
            if ratio is not None and ratio < min_ratio
        ],
        "tier_structure_for_report": validation["calibration_merged"]["tier_members"],
        "failed_criteria": table["failed_criteria"],
        "note": (
            "단조 추세는 검증 사상에서 확인됐다. 인접 발생률 비가 기준에 못 미친 등급쌍은 "
            "개별 등급으로 주장하지 않고 통합 단계로 보고한다 (CDRI_GRADE_SYSTEM §1③ ④)."
        ),
    }


def _calibrate_and_validate(primary_scaled, labels, grade_jenks, p):
    """캘리브레이션 기간으로 경계를 맞추고 검증 기간으로 채점한다. (등급, 경계진단, 검증)."""
    from src.data import calibration as C
    from src.data import grades as G

    grade_calibration, calibration = G.calibration_grades(
        primary_scaled, labels["cal"],
        tolerance=float(p["cdri.calibration_tolerance"]),
        min_ratio=float(p["cdri.calibration_min_ratio"]),
    )
    calibration["sensitivity"] = C.sensitivity(primary_scaled, labels["cal"])
    calibration["n_calibration_positive"] = int(labels["cal"].sum())
    calibration["sample"] = "in-sample (캘리브레이션 기간 사상) — 경계 산출에만 쓴다"

    # 캘리브레이션 자료가 통합을 권고한 등급을 묶어 본 결과도 함께 채점한다 (절차 ④).
    merged, merge_map = C.merge_weak_grades(grade_calibration, calibration["merge_recommended"])
    validation = {
        "calibration": _grade_validation(grade_calibration, labels["val"], p),
        "calibration_merged": {
            **merge_map,
            **_grade_validation(merged, labels["val"], p, merge_map["n_tiers"]),
        },
        # Jenks 도 같은 자료로 채점해 둔다. 본안 선택 기준이 아니라 비교 정보다.
        "jenks": _grade_validation(grade_jenks, labels["val"], p),
    }
    validation["reporting_constraint"] = _reporting_constraint(
        validation,
        min_ratio=float(p["cdri.calibration_min_ratio"]),
        lift_min=float(p["cdri.calibration_lift_r4_min"]),
    )
    return grade_calibration, calibration, validation


def _assign_grades(sub, primary_scaled, percentiles, p) -> dict[str, Any]:
    """R1~R5 등급을 매긴다. 본안(Jenks vs 캘리브레이션)은 라벨 수와 시간 분할 가능 여부가 정한다."""
    import pandas as pd

    from src.data import grades as G

    labels = _load_trace_labels(sub["grid_id"].to_numpy())
    n_positive = int(labels["all"].sum()) if labels else 0
    scheme, reason = G.choose_scheme(n_positive, has_time_split=bool(labels and labels["has_time_split"]))

    grade_jenks, breaks = G.jenks_grades(primary_scaled)
    grade_balica = G.balica_grades(primary_scaled)
    grade_percentile = G.percentile_grades(primary_scaled)

    grade_calibration, calibration, validation = (
        _calibrate_and_validate(primary_scaled, labels, grade_jenks, p)
        if scheme == "calibration" else (None, None, {})
    )

    # 본안은 결정 003 이 미리 고른 3안(캘리브레이션)이다. 검증 결과로 방식을 갈아타지
    # 않는다 — 그러면 검증 자료가 선택에 개입해 out-of-sample 이 아니게 된다. 검증은
    # "무엇을 주장해도 되는지"를 정할 뿐이며, 미달 기준은 지우지 않고 그대로 싣는다.
    grade_raw = grade_calibration if grade_calibration is not None else grade_jenks
    grade_final, review_flag, rules = G.apply_rules(
        grade_raw,
        l1_percentile=percentiles[:, COMPONENTS.index("H")],
        v_percentile=percentiles[:, COMPONENTS.index("V")],
        h_percentile=percentiles[:, COMPONENTS.index("H")],
        designated_near=None,   # 규칙 C 는 지정지구 좌표 확보 후
    )

    sub["grade_raw"] = grade_raw
    sub["grade_final"] = grade_final
    sub["grade_jenks"] = grade_jenks
    sub["grade_balica"] = grade_balica
    sub["grade_percentile"] = grade_percentile
    sub["grade_code"] = pd.Series(grade_final).map(G.GRADE_CODES).to_numpy()
    sub["grade_name"] = pd.Series(grade_final).map(G.GRADE_NAMES).to_numpy()
    sub["grade_review_flag"] = review_flag

    kappa = {
        "jenks_vs_balica": round(G.weighted_kappa(grade_jenks, grade_balica), 4),
        "jenks_vs_percentile": round(G.weighted_kappa(grade_jenks, grade_percentile), 4),
        "balica_vs_percentile": round(G.weighted_kappa(grade_balica, grade_percentile), 4),
        "note": "2차 가중 kappa. Landis & Koch(1977) 기준 0.61~0.80 substantial",
    }
    if grade_calibration is not None:
        kappa["calibration_vs_jenks"] = round(G.weighted_kappa(grade_calibration, grade_jenks), 4)
        kappa["calibration_vs_balica"] = round(G.weighted_kappa(grade_calibration, grade_balica), 4)

    return {
        "direction": "R1~R5 오름차순, 5 가 가장 위험 (국토부 지침 I~IV 와 방향 반대)",
        "scheme": scheme,
        "scheme_reason": reason,
        "n_trace_positive": n_positive,
        "jenks_breaks": [round(v, 4) for v in breaks],
        "calibration": calibration,
        "calibration_adopted": grade_calibration is not None,
        "validation": validation or None,
        "raw": G.grade_summary(grade_raw),
        "final": G.grade_summary(grade_final),
        "jenks_for_comparison": G.grade_summary(grade_jenks),
        "balica_for_comparison": G.grade_summary(grade_balica),
        "percentile_for_comparison": G.grade_summary(grade_percentile),
        "rules": rules,
        "weighted_kappa": kappa,
        "note": "검증은 grade_raw, 대응 행동표는 grade_final 을 쓴다 (순환 방지)",
    }


def _write_grade_by_dong(sub, path: Path) -> int:
    """행정동 × 등급 격자 수와 인구·고령 추정치. 부서가 바로 쓰는 표다 (CDRI_GRADE_SYSTEM §3)."""
    import pandas as pd

    names_path = PROJECT_ROOT / DONG_NAME_PATH
    dong = sub[["grid_id", "adm_cd", "grade_code", "pop_total", "elderly_ratio"]].copy()
    if names_path.exists():
        lookup = pd.read_csv(names_path, encoding="utf-8-sig", dtype={"adm_cd": str})
        dong = dong.merge(lookup[["adm_cd", "adm_name", "gu_name"]], on="adm_cd", how="left")
    else:
        dong["adm_name"], dong["gu_name"] = "행정동명 미확보", ""

    dong["고령추정"] = dong["pop_total"] * dong["elderly_ratio"]
    by_grade = (
        dong.pivot_table(index=["gu_name", "adm_name"], columns="grade_code",
                         values="grid_id", aggfunc="count", fill_value=0)
        .reindex(columns=["R5", "R4", "R3", "R2", "R1"], fill_value=0)
    )
    totals = dong.groupby(["gu_name", "adm_name"]).agg(
        격자수=("grid_id", "count"), 인구=("pop_total", "sum"), 고령추정=("고령추정", "sum"),
    ).round({"고령추정": 0})

    table = by_grade.join(totals).reset_index().sort_values(["R5", "R4"], ascending=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False, encoding="utf-8-sig")
    return len(table)


def _decide_ranking_mode(robustness, top_n: int, min_rho: float, min_overlap: int):
    """순위를 그대로 보고해도 되는지 정한다. (지표, 모드, 설명).

    강건성 미달은 **실패가 아니라 분기**다 (하네스 H07 on_fail). 임계값을 낮추는
    재튜닝은 금지이므로 기준은 그대로 두고 산출물의 성격만 바꾼다 — 정밀 순위 대신
    위험군과 강건 공통집합으로 말한다.
    """
    unmet = []
    if robustness["median_rho"] < min_rho:
        unmet.append(f"중위 Spearman rho {round(robustness['median_rho'], 4)} < {min_rho}")
    if robustness["min_overlap"] < min_overlap:
        unmet.append(f"TOP {top_n} 최소 중첩 {robustness['min_overlap']} < {min_overlap}")
    metrics = {
        "median_spearman_rho": round(robustness["median_rho"], 4),
        "min_spearman_rho": round(robustness["min_rho"], 4),
        f"min_top{top_n}_overlap": robustness["min_overlap"],
        "min_spearman_required": min_rho,
        "min_overlap_required": min_overlap,
        "unmet": unmet,
    }
    note = (
        "정밀 순위 보고 가능" if not unmet else
        "정밀 순위를 주장하지 않는다. 위험군(tier)과 강건 공통집합으로만 보고한다 — 하네스 H07 분기"
    )
    return metrics, ("rank" if not unmet else "tier"), note


def _write_outputs(ctx: StageContext, sub, variant_rows, m: dict[str, Any], formula: dict) -> None:
    """격자 gpkg·민감도표·행정동표·확정 산식 manifest 를 쓴다.

    manifest 를 따로 남기는 이유: 승인 뒤 산식을 바꾸지 않았다는 것을 나중에 대조할 수
    있어야 한다. `retuning_prohibited` 와 run_id 가 그 증거다.
    """
    import pandas as pd

    gpkg = next(o for o in ctx.outputs if o.suffix == ".gpkg")
    gpkg.parent.mkdir(parents=True, exist_ok=True)
    if gpkg.exists():
        gpkg.unlink()
    sub[OUTPUT_COLUMNS].to_file(gpkg, layer="cdri", driver="GPKG")

    sensitivity = next(o for o in ctx.outputs if o.name == "sensitivity.csv")
    sensitivity.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(variant_rows).to_csv(sensitivity, index=False, encoding="utf-8-sig")

    by_dong = next(o for o in ctx.outputs if o.name == "grade_by_dong.csv")
    m["grade_system"]["by_dong_rows"] = _write_grade_by_dong(sub, by_dong)

    manifest = next(o for o in ctx.outputs if o.suffix == ".json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "primary_formula": formula["name"],
        "definition": "CDRI = Π (X_k ^ w_k), X ∈ {H, E, V, D}, 각 [floor, 1] 재척도",
        "components": COMPONENT_LABELS,
        "weights": m["weights"]["equal"],
        "weight_scheme": "equal",
        "rescale_floor": formula["floor"],
        "universe_rule": "pop_total > 0 또는 houses >= 1",
        "n_universe": formula["n_universe"],
        "layer2_included": False,
        "ranking_mode": formula["ranking_mode"],
        "ranking_mode_note": m["ranking_mode_note"],
        "grade_scheme": m["grade_system"]["scheme"],
        "grade_direction": "R1~R5 오름차순 (5 = 최위험)",
        "robustness_unmet": formula["unmet"],
        "robust_core_n": formula["robust_core_n"],
        "decision": "docs/decisions/001-layer2-design.md",
        "run_id": ctx.run_id,
        "retuning_prohibited": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def cdri(ctx: StageContext) -> dict[str, Any]:
    """통과: 가중치·집계형 변형 사이 중위 Spearman ρ ≥ params.min_spearman,
    TOP 20 중첩 ≥ params.min_top20_overlap, 구성요소 결측 0 대체 없음.

    강건성 미달은 **실패가 아니라 분기**다. 하네스 H07 의 on_fail 은 goto 없이
    "정밀 순위 대신 위험군(tier) 모드로 보고"라고 정했다. 임계값을 낮추는 재튜닝은
    금지이므로 기준은 그대로 두고 산출물의 성격만 바꾼다.
    """
    import numpy as np
    import pandas as pd

    from src.data import layers as L

    p = ctx.params
    top_n = int(p["cdri.top_n"])
    floor = float(p["cdri.rescale_floor"])
    min_rho = float(p["cdri.min_spearman"])
    min_overlap = int(p["cdri.min_top20_overlap"])

    df = _load_layers()
    universe = df["universe"].to_numpy().astype(bool)
    m: dict[str, Any] = {
        "n_grid": int(len(df)),
        "n_universe": int(universe.sum()),
        "components": COMPONENT_LABELS,
        "layer2_included_in_primary": False,
        "layer2_reason": "관로 비공개로 검증 불가 — docs/decisions/001-layer2-design.md",
    }

    # 순위 대상 격자만으로 재척도한다. 무인구 격자를 섞으면 분포가 왜곡된다.
    sub = df.loc[universe].copy()
    matrix = _component_matrix(sub, floor)
    if not np.isfinite(matrix).all():
        raise StageFailed(
            "구성요소에 결측이 있다 — 0 으로 대체하지 않고 중단한다",
            [{"code": "component_missing", "detail": COMPONENTS}], metrics=m,
        )

    variants, weights, variant_meta = _build_variants(matrix, sub, floor)
    m.update(variant_meta)
    primary_name = "geometric_equal"
    primary = variants[primary_name]
    m["primary_formula"] = primary_name

    robustness = _assess_robustness(variants, primary_name, sub["grid_id"].to_numpy(), top_n)
    m["variants"] = robustness["rows"]
    m["robust_core"] = {
        "n": len(robustness["robust_core"]),
        "note": f"가중치·집계형 변형 {len(variants)}개 모두의 TOP {top_n} 에 공통으로 드는 격자",
    }
    m["maup"] = _maup_check(sub, primary)

    percentiles = _attach_contributions(sub, matrix, weights["equal"])
    primary_scaled = L.minmax(primary)
    m["grade_system"] = _assign_grades(sub, primary_scaled, percentiles, p)

    sub["cdri"] = primary_scaled
    sub["cdri_raw"] = primary
    sub["cdri_additive"] = L.minmax(variants["additive_equal"])
    sub["rank"] = (-sub["cdri"]).rank(method="first").astype(int)
    sub["in_robust_core"] = sub["grid_id"].isin(robustness["robust_core"]).astype("int8")
    for i, name in enumerate(COMPONENTS):
        sub[f"{name}_scaled"] = matrix[:, i]

    m["cdri_summary"] = {
        "mean": round(float(sub["cdri"].mean()), 4),
        "p50": round(float(sub["cdri"].median()), 4),
        "p90": round(float(sub["cdri"].quantile(0.9)), 4),
        "primary_cause_counts": {k: int(v) for k, v in sub["primary_cause"].value_counts().items()},
        "primary_cause_rule": "구성요소 백분위가 가장 높은 것 (ANALYSIS_PLAN §5)",
    }

    m["robustness"], m["ranking_mode"], m["ranking_mode_note"] = _decide_ranking_mode(
        robustness, top_n, min_rho, min_overlap
    )
    unmet, ranking_mode = m["robustness"]["unmet"], m["ranking_mode"]

    _write_outputs(ctx, sub, robustness["rows"], m,
                   formula=dict(name=primary_name, floor=floor, unmet=unmet,
                                ranking_mode=ranking_mode, n_universe=int(universe.sum()),
                                robust_core_n=len(robustness["robust_core"])))
    _cdri_map(df, sub, PROJECT_ROOT / "reports/figures/cdri_map.png")
    return m


def _cdri_map(df, sub, out: Path) -> None:
    """지수와 등급을 나란히 보여주는 2면 지도. 등급 색은 grades 모듈의 정의를 그대로 쓴다."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    from src.data.grades import GRADE_COLORS
    from src.visualization import style

    style.apply()
    merged = df[["grid_id", "geometry"]].merge(
        sub[["grid_id", "cdri", "grade_final"]], on="grid_id", how="left"
    )
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    merged.plot(column="cdri", ax=axes[0], linewidth=0, legend=True, cmap="magma_r",
                legend_kwds={"shrink": 0.6}, missing_kwds={"color": "0.92"})
    axes[0].set_title("CDRI 우선대응 지수 (회색 = 순위 대상 밖)", fontsize=10)

    cmap = ListedColormap([GRADE_COLORS[g] for g in (1, 2, 3, 4, 5)])
    merged.plot(column="grade_final", ax=axes[1], linewidth=0, legend=True, cmap=cmap,
                vmin=1, vmax=5, missing_kwds={"color": "0.92"})
    axes[1].set_title("위험 등급 R1~R5 (5 = 최우선 대응)", fontsize=10)
    for ax in axes:
        ax.set_axis_off()
        ax.grid(False)
    fig.tight_layout()
    style.save(fig, out)
