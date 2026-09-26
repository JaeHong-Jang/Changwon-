"""M4 채점: 한 사상·한 설정(규칙 × 크기)에서 점수별 격자 AUC·포착·객체 AUC·분해를 구한다 (docs/q1/M4_protocol.md §5·§6)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.data.coarse_grid import Blocks
from src.data.trace_footprint import Footprint

CAPTURE_FRACTION = 0.2
IDENTITY_TOL = 1e-9


def sklearn_auc(score: np.ndarray, p: np.ndarray) -> float:
    """칸을 양성(질량 p)·음성(질량 1 − p) 가중 표본 두 개로 복제해 sklearn 으로 AUC 를 구한다 (분해 검산용 독립 경로)."""
    from sklearn.metrics import roc_auc_score

    # 점수가 있는 칸을 복제하고 질량 0 인 표본을 뺀다
    s = np.asarray(score, dtype=float)
    keep = np.isfinite(s)
    s, p = s[keep], np.asarray(p, dtype=float)[keep]
    y = np.r_[np.ones(len(s)), np.zeros(len(s))]
    w = np.r_[p, 1.0 - p]
    use = w > 0
    if not (y[use] == 1).any() or not (y[use] == 0).any():
        return np.nan
    return float(roc_auc_score(y[use], np.r_[s, s][use], sample_weight=w[use]))


def event_sample(p: np.ndarray, fp: Footprint, blocks: Blocks) -> dict[str, int]:
    """양성 칸 수, 양성 칸 덩어리 수(반경 1.5 × 크기), 폴리곤 수."""
    from src.data.uncertainty import spatial_clusters

    # 양성 질량이 있는 칸의 중심점을 덩어리로 묶는다
    positive = np.asarray(p) > 0
    n_clusters = len(np.unique(spatial_clusters(blocks.x[positive], blocks.y[positive],
                                                radius_m=1.5 * blocks.size))) if positive.any() else 0
    return {"n_pos_cells": int(positive.sum()), "n_clusters": int(n_clusters), "n_polygons": fp.n_obj}


def score_config(scores: dict[str, np.ndarray], p: np.ndarray, capture_weight: np.ndarray, fp: Footprint,
                 blocks: Blocks, background: np.ndarray) -> tuple[list[dict[str, Any]], list[dict[str, Any]], pd.DataFrame]:
    """점수마다 격자 AUC(가중·sklearn·분해 세 경로)·포착·객체 AUC 행, 분해 행, 객체별 기여 표를 만든다."""
    from src.data.validation import capture_curve
    from src.data.validation.decomposition import decompose, object_terms
    from src.data.validation.weighted_auc import weighted_auc

    # 점수마다 세 경로의 격자 AUC 와 포착·객체 AUC 를 구하고 분해 항등식을 확인한다
    metrics, decomposition, objects = [], [], []
    for name, score in scores.items():
        finite = np.isfinite(score)
        auc = weighted_auc(score, p)
        auc_sk = sklearn_auc(score, p)
        terms = object_terms(score, p, fp, background)
        parts = decompose(terms)
        gap = max(abs(parts["auc_from_objects"] - auc), abs(auc_sk - auc)) if np.isfinite(auc) else 0.0
        if not gap <= IDENTITY_TOL:
            raise RuntimeError(f"{name}: 격자 AUC 분해 항등식 불일치 {gap:.3e}")
        capture = capture_curve(score, capture_weight, (CAPTURE_FRACTION,), cell_areas=blocks.area)["capture"].iloc[0] \
            if (capture_weight[finite] > 0).any() else np.nan
        n_pos = int(((p > 0) & finite).sum())
        n_obj = int(np.isfinite(terms["At"]).sum())
        metrics += [{"score": name, "metric": "cell_auc", "value": auc, "n_units": n_pos},
                    {"score": name, "metric": "cell_auc_sklearn", "value": auc_sk, "n_units": n_pos},
                    {"score": name, "metric": f"capture_{CAPTURE_FRACTION:g}", "value": capture, "n_units": n_pos},
                    {"score": name, "metric": "object_auc", "value": parts.get("object_auc", np.nan), "n_units": n_obj}]
        decomposition.append({"score": name, "cell_auc": auc, "cell_auc_sklearn": auc_sk,
                              "identity_abs_diff": gap, **parts})

        # 객체별 가중치·기여·객체 값을 남긴다
        total = terms["W"].sum() + terms["orphan_mass"]
        objects.append(pd.DataFrame({"score": name, "object_index": np.arange(fp.n_obj), "W": terms["W"],
                                     "w": terms["W"] / total if total > 0 else np.nan,
                                     "A_gate": terms["A"], "A_object": terms["At"]}))
    return metrics, decomposition, pd.concat(objects, ignore_index=True)
