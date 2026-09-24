"""사전등록된 격자 AUC와 상위 20% 포착 게이트를 계산한다."""

from __future__ import annotations

from typing import Any

import numpy as np

GATE = {"auc_min": 0.70, "top20_capture_min": 0.50}


def gate(labels: np.ndarray, score: np.ndarray, points: np.ndarray) -> dict[str, Any]:
    """사전 게이트: h06 과 같은 L.roc_auc(결측 제외)·L.top_share_lift. 구간은 같은 유효 표본으로."""
    from src.data import layers as L
    from src.data import uncertainty as U

    # 비유한 점수를 제외하고 양성·음성 모두 있는지 확인한다.
    valid = np.isfinite(score)
    y = labels[valid]
    if y.all() or not y.any():
        return {"evaluable": False, "reason": "유효 표본에 양성 또는 음성이 없다", "n_nonfinite": int((~valid).sum())}

    # 기존 덩어리 재표본 구간과 격자 AUC·상위 20% 포착률을 계산한다.
    ci = U.cluster_bootstrap_auc(y, score[valid], points[valid, 0], points[valid, 1])
    auc = L.roc_auc(labels, score)
    top = L.top_share_lift(labels, score, 0.20)

    # 사전등록된 두 임계값의 통과 여부를 원래 키 구조로 반환한다.
    return {
        "evaluable": True, "n_nonfinite": int((~valid).sum()),
        "auc_cell": round(auc, 4), "auc_cell_ci95": ci["ci95"],
        "auc_cluster": ci["auc_cluster_weighted"], "auc_cluster_ci95": ci["ci95_cluster_weighted"],
        "n_positive_cells": int(labels.sum()), "n_clusters": ci["n_cluster"], "n_boot": ci["n_boot"],
        "top20_capture": top["capture_rate"],
        "passes_auc": bool(auc >= GATE["auc_min"]),
        "passes_capture": bool(top["capture_rate"] >= GATE["top20_capture_min"]),
    }


_gate = gate
