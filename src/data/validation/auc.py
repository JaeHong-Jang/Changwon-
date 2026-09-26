"""격자·객체·침수면적 기준 관측라벨 AUC."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from src.data import layers, uncertainty
from ._common import _mid_cdf, _overlaps

if TYPE_CHECKING:
    import geopandas as gpd


def cell_auc(
    labels: np.ndarray, scores: np.ndarray, x: np.ndarray, y: np.ndarray,
    *, background_mask: np.ndarray | None = None, n_boot: int = 2000, seed: int = 42,
) -> dict:
    """배경 격자와 양성 격자로 관측라벨 AUC 및 덩어리 재표본 구간을 구한다."""
    # 입력과 배경 마스크를 검사하고 유효 격자의 AUC를 계산한다.
    labels = np.asarray(labels, dtype=bool)
    scores = np.asarray(scores, dtype=float)
    background = ~labels if background_mask is None else np.asarray(background_mask, dtype=bool)
    if len(labels) != len(scores) or len(x) != len(scores) or len(y) != len(scores) or len(background) != len(scores):
        raise ValueError("격자 입력 길이가 다르다")
    if np.any(labels & background):
        raise ValueError("양성과 배경 격자가 겹친다")
    keep = (labels | background) & np.isfinite(scores)
    if not labels[keep].any() or not background[keep].any():
        return {"observed-label_auc_cell": np.nan, "observed-label_auc_cluster": np.nan,
                "ci95_cell": (np.nan, np.nan), "ci95_cluster": (np.nan, np.nan), "n_cluster": 0}
    truth = labels[keep]
    result = uncertainty.cluster_bootstrap_auc(truth, scores[keep], np.asarray(x)[keep],
                                               np.asarray(y)[keep], n_boot=n_boot, seed=seed)
    return {
        "observed-label_auc_cell": layers.roc_auc(truth, scores[keep]),
        "observed-label_auc_cluster": result["auc_cluster_weighted"],
        "ci95_cell": tuple(result["ci95"]),
        "ci95_cluster": tuple(result["ci95_cluster_weighted"]),
        "n_cluster": result["n_cluster"],
    }



def object_auc(
    scores: np.ndarray, grid: gpd.GeoDataFrame, traces: gpd.GeoDataFrame,
    *, background_mask: np.ndarray | None = None,
) -> dict:
    """각 폴리곤에 한 표를 주는 면적가중·대표점 관측라벨 AUC를 구한다."""
    # 교차면적과 대표점에서 객체별 AUC를 집계한다.
    score = np.asarray(scores, dtype=float)
    if len(score) != len(grid):
        raise ValueError("점수와 격자 길이가 다르다")
    obj, cell, area, point, _ = _overlaps(grid, traces)
    touched = np.zeros(len(grid), bool)
    touched[cell] = True
    background = ~touched if background_mask is None else np.array(background_mask, dtype=bool, copy=True)
    if len(background) != len(grid) or np.any(background & touched):
        raise ValueError("배경 마스크가 평가 흔적과 겹치거나 길이가 다르다")
    background &= np.isfinite(score)
    fractions = _mid_cdf(score[cell], score[background])
    valid = np.isfinite(score[cell])
    sums = np.bincount(obj[valid], weights=area[valid] * fractions[valid], minlength=len(traces))
    weights = np.bincount(obj[valid], weights=area[valid], minlength=len(traces))
    per_object = np.divide(sums, weights, out=np.full(len(traces), np.nan), where=weights > 0)
    point_auc = np.full(len(traces), np.nan)
    good_point = (point >= 0) & np.isfinite(score[np.maximum(point, 0)]) if len(score) else np.zeros(len(point), bool)
    point_auc[good_point] = _mid_cdf(score[point[good_point]], score[background])
    return {"observed-label_auc_object": float(np.nanmean(per_object)) if np.isfinite(per_object).any() else np.nan,
            "observed-label_auc_representative": float(np.nanmean(point_auc)) if np.isfinite(point_auc).any() else np.nan,
            "per_object": per_object, "per_representative": point_auc, "object_area": weights,
            "object_index": obj, "cell_index": cell, "overlap_area": area,
            "representative_cell": point, "background_mask": background}



def area_weighted_auc(scores: np.ndarray, grid: gpd.GeoDataFrame, traces: gpd.GeoDataFrame,
                      *, background_mask: np.ndarray | None = None) -> float:
    """관측 침수 면적마다 같은 가중치를 주는 관측라벨 AUC를 구한다."""
    # 유효 객체 AUC를 관측 면적으로 가중 평균한다.
    result = object_auc(scores, grid, traces, background_mask=background_mask)
    area = result["object_area"]
    valid = np.isfinite(result["per_object"]) & (area > 0)
    return float(np.average(result["per_object"][valid], weights=area[valid])) if valid.any() else np.nan

