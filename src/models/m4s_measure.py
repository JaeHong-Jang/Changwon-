"""M4S 복제 하나: 가상 인벤토리·점수를 만들고 합동 라벨을 규칙별로, B 묶음은 사상별로 채점한다 (docs/q1/M4S_protocol.md §3·§4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from src.data.label_rules import RULES

CAPTURE_FRACTION = 0.2
IDENTITY_TOL = 1e-9
EVENT_RULE = "f10"


@dataclass(frozen=True)
class Landscape:
    """작업자마다 한 번 만드는 격자와 칸 면적·중심점."""

    grid: Any
    n_side: int
    box: tuple[float, float, float, float]
    cell_area: np.ndarray
    x: np.ndarray
    y: np.ndarray


def make_landscape(n_side: int | None = None) -> Landscape:
    """가상 격자와 공간 색인·칸 면적·중심점을 준비한다 (기본 200 × 200)."""
    from src.synth.landscape import N_SIDE, bounds, lattice

    # 격자를 만들고 공간 색인을 미리 짓는다
    n_side = n_side or N_SIDE
    grid = lattice(n_side)
    grid.sindex
    centers = grid.geometry.centroid
    return Landscape(grid, n_side, bounds(n_side), grid.geometry.area.to_numpy(), centers.x.to_numpy(), centers.y.to_numpy())


def generate(scenario, j: int, land: Landscape) -> tuple[Any, Any, np.ndarray, np.ndarray]:
    """절차 §1.6 의 난수로 객체 표·자국·점수·비접촉 배경을 만든다."""
    from src.data.trace_footprint import footprint
    from src.synth.detectability import assemble, detectability
    from src.synth.inventory import inventory
    from src.synth.landscape import background
    from src.synth.scenarios import SEED

    # 객체 → 배경 잡음 → 탐지력 순서로 같은 난수 생성기에서 뽑는다
    rng = np.random.default_rng([SEED, scenario.no, j])
    polys = inventory(rng, scenario, land.box)
    z = background(rng, land.n_side)
    mu = detectability(rng, polys["zeta"].to_numpy(), polys["event"].to_numpy(), scenario.n_events,
                       scenario.mu0, scenario.beta, scenario.tau, scenario.upsilon)

    # 자국을 계산해 점수를 조립하고, 어떤 객체와도 겹치지 않은 칸을 배경으로 둔다
    fp = footprint(land.grid, polys)
    score = assemble(z, fp, mu)
    touched = np.bincount(fp.cell, minlength=fp.n_cells) > 0
    return polys, fp, score, ~touched


def score_rule(score: np.ndarray, p: np.ndarray, capture_weight: np.ndarray, fp, background: np.ndarray,
               land: Landscape, groups: np.ndarray | None = None, check_sklearn: bool = False) -> dict[str, Any]:
    """한 라벨의 격자 AUC·포착·객체 AUC·분해·집중·항등식 오차."""
    from src.data.validation import capture_curve
    from src.data.validation.decomposition import decompose, object_terms
    from src.data.validation.weight_concentration import covariance_form, group_share, top_share
    from src.data.validation.weighted_auc import weighted_auc
    from src.models.m4_metrics import sklearn_auc

    # 격자 AUC 와 분해를 구하고 분해 항등식을 확인한다
    auc = weighted_auc(score, p)
    terms = object_terms(score, p, fp, background)
    parts = decompose(terms)
    identity = abs(parts["auc_from_objects"] - auc) if np.isfinite(auc) else 0.0
    sk = sklearn_auc(score, p) if check_sklearn else np.nan
    sk_diff = abs(sk - auc) if check_sklearn and np.isfinite(auc) else np.nan
    if not identity <= IDENTITY_TOL or (check_sklearn and not sk_diff <= IDENTITY_TOL):
        raise RuntimeError(f"격자 AUC 분해 항등식 불일치 {identity:.3e} / sklearn {sk_diff:.3e}")

    # 포착과 가중치 집중, 크기 가중 항의 공분산 형태를 구한다
    capture = capture_curve(score, capture_weight, (CAPTURE_FRACTION,), cell_areas=land.cell_area)["capture"].iloc[0] \
        if capture_weight.sum() > 0 else np.nan
    cov = covariance_form(terms["W"], terms["A"], terms["At"])
    exact = terms["orphan_mass"] == 0 and parts.get("n_survive_no_At", 0) == 0
    cov_diff = abs(cov["size_term_product"] - parts.get("term_size_weight", np.nan)) if exact and cov["n_S"] else np.nan
    if exact and cov["n_S"] and not cov_diff <= IDENTITY_TOL:
        raise RuntimeError(f"크기 가중 항 공분산 형태 불일치 {cov_diff:.3e}")
    object_auc = parts.get("object_auc", np.nan)
    return {"cell_auc": auc, "capture": capture, "object_auc": object_auc, "gap": auc - object_auc,
            "term_size_weight": parts.get("term_size_weight", np.nan), "term_within_object": parts.get("term_within_object", np.nan),
            "term_erasure": parts.get("term_erasure", np.nan), "n_eff": parts.get("n_eff", np.nan),
            "n_objects": parts["n_objects"], "n_survive": parts["n_survive"], "n_K": int(np.isfinite(terms["At"]).sum()),
            "n_pos_cells": int((np.asarray(p) > 0).sum()), "orphan_weight": parts.get("orphan_weight", np.nan),
            "top10_share": top_share(terms["W"], 0.1, terms["orphan_mass"]),
            "max_event_share": group_share(terms["W"], groups, terms["orphan_mass"]) if groups is not None else np.nan,
            "n_eff_S": cov["n_eff_S"], "sd_A": cov["sd_A"], "rho_wA": cov["rho_wA"],
            "concentration_factor": cov["concentration_factor"], "size_term_product": cov["size_term_product"],
            "identity_abs_diff": identity, "sklearn_abs_diff": sk_diff, "cov_abs_diff": cov_diff}


def replicate(scenario, j: int, land: Landscape) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """복제 j 의 합동 라벨 행(규칙별)과 B 묶음 사상별 행."""
    from src.data.label_rules import positive_mass
    from src.data.trace_footprint import center_inside, footprint
    from src.data.validation.curves import _object_capture

    # 가상 자료를 만들고 규칙과 무관한 객체 포착을 구한다
    polys, fp, score, background = generate(scenario, j, land)
    obj_cap = _object_capture(score, land.cell_area, fp.obj, fp.cell, fp.area, fp.n_obj)
    obj_capture = float(obj_cap.loc[np.isclose(obj_cap["fraction"], CAPTURE_FRACTION), "capture"].iloc[0])
    inside = center_inside(polys, land.x, land.y)
    events = polys["event"].to_numpy()
    tag = {"scenario_no": scenario.no, "block": scenario.block, "replicate": j, "n_polygons": len(polys)}

    # 합동 라벨을 규칙마다 채점한다 (B 묶음은 참조 규칙만)
    rows = []
    for rule in (RULES if scenario.block != "B" else (EVENT_RULE,)):
        p = positive_mass(rule, fp, inside)
        weight = p * land.cell_area if rule == "soft" else p
        result = score_rule(score, p, weight, fp, background, land, events, check_sklearn=(j == 0))
        rows.append(tag | {"rule": rule, "object_capture": obj_capture} | result)

    # B 묶음은 사상마다 그 사상 객체만으로 라벨을 만들어 채점한다
    event_rows = []
    if scenario.block == "B":
        for e in np.unique(events):
            part = polys[events == e].reset_index(drop=True)
            fp_e = footprint(land.grid, part)
            p = positive_mass(EVENT_RULE, fp_e)
            result = score_rule(score, p, p, fp_e, background, land)
            event_rows.append(tag | {"event": int(e), "rule": EVENT_RULE, "n_event_polygons": len(part)} |
                              {k: result[k] for k in ("cell_auc", "capture", "object_auc", "gap", "n_pos_cells",
                                                      "n_objects", "n_survive", "n_K", "identity_abs_diff")})
    return rows, event_rows


def run_scenario(scenario, replicates: int, land: Landscape) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """시나리오 하나의 복제 0..R−1 을 차례로 채점한다."""
    # 복제 행을 모은다
    rows, event_rows = [], []
    for j in range(replicates):
        r, e = replicate(scenario, j, land)
        rows += r
        event_rows += e
    return rows, event_rows
