"""관측 포착곡선·Boyce 지수·평균정밀도."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import FRACTIONS


def capture_curve(
    scores: np.ndarray, weights: np.ndarray, fractions: tuple[float, ...] = FRACTIONS,
    *, cell_areas: np.ndarray | None = None,
) -> pd.DataFrame:
    """상위 격자 면적 비율의 관측 포착률을 구한다; 2차원 가중치는 행마다 한 표다."""
    # 입력 가중치와 유효 격자를 검사한 뒤 상위 면적 순으로 포착률을 계산한다.
    score = np.asarray(scores, dtype=float)
    weight = np.asarray(weights, dtype=float)
    if weight.ndim not in (1, 2) or weight.shape[-1] != len(score):
        raise ValueError("가중치는 격자 길이의 벡터 또는 객체×격자 행렬이어야 한다")
    area = np.ones(len(score)) if cell_areas is None else np.asarray(cell_areas, dtype=float)
    if len(area) != len(score) or np.any(area < 0) or not np.isfinite(area).all() or np.any(weight < 0) or not np.isfinite(weight).all():
        raise ValueError("면적과 가중치는 유한한 음이 아닌 값이어야 한다")
    valid = np.isfinite(score) & (area > 0)
    order = np.flatnonzero(valid)[np.argsort(-score[valid], kind="stable")]
    total_area = area[order].sum()
    selected_area = np.cumsum(area[order])
    rows = []
    for fraction in fractions:
        if not 0 <= fraction <= 1:
            raise ValueError("면적 비율은 0~1이어야 한다")
        share = np.clip((fraction * total_area - (selected_area - area[order])) / area[order], 0, 1)
        if weight.ndim == 1:
            denominator = weight[order].sum()
            captured = float(np.dot(weight[order], share) / denominator) if denominator else np.nan
            n_units = int(np.count_nonzero(weight[order]))
        else:
            denominator = weight[:, order].sum(axis=1)
            per_object = np.divide(weight[:, order] @ share, denominator,
                                   out=np.full(len(weight), np.nan), where=denominator > 0)
            captured = float(np.nanmean(per_object)) if np.isfinite(per_object).any() else np.nan
            n_units = int(np.count_nonzero(denominator))
        rows.append({"fraction": float(fraction), "capture": captured, "n_units": n_units})
    return pd.DataFrame(rows)



def _object_capture(
    scores: np.ndarray, cell_areas: np.ndarray, obj: np.ndarray, cell: np.ndarray,
    overlap: np.ndarray, n_objects: int,
) -> pd.DataFrame:
    """조밀한 객체×격자 행렬 없이 객체별 포착률을 구한다."""
    # 정렬된 격자에 객체 교차면적을 누적해 포착률을 계산한다.
    valid = np.isfinite(scores) & (cell_areas > 0)
    order = np.flatnonzero(valid)[np.argsort(-scores[valid], kind="stable")]
    cumulative = np.cumsum(cell_areas[order])
    position = np.full(len(scores), -1, int)
    position[order] = np.arange(len(order))
    pair_valid = position[cell] >= 0
    denominator = np.bincount(obj[pair_valid], weights=overlap[pair_valid], minlength=n_objects)
    rows = []
    for fraction in FRACTIONS:
        share = np.clip((fraction * cumulative[-1] - (cumulative - cell_areas[order])) / cell_areas[order], 0, 1) if len(order) else np.array([])
        contribution = overlap[pair_valid] * share[position[cell[pair_valid]]]
        numerator = np.bincount(obj[pair_valid], weights=contribution, minlength=n_objects)
        captured = np.divide(numerator, denominator, out=np.full(n_objects, np.nan), where=denominator > 0)
        rows.append({"fraction": fraction, "capture": float(np.nanmean(captured)) if np.isfinite(captured).any() else np.nan,
                     "n_units": int(np.count_nonzero(denominator))})
    return pd.DataFrame(rows)



def continuous_boyce(
    pos_scores: np.ndarray, pos_weights: np.ndarray, bg_scores: np.ndarray,
    window: float = 0.1, n_points: int = 101, *, bg_weights: np.ndarray | None = None,
) -> dict:
    """이동창 P/E와 Spearman 계수; 빈 기대 창은 제외하고 상수 점수·곡선은 NaN으로 둔다."""
    # 이동창 결과의 순위 상관을 계산할 함수를 불러온다.
    from scipy.stats import spearmanr

    # 양성과 배경의 유효 점수 및 가중치를 정리한다.
    pos = np.asarray(pos_scores, dtype=float)
    weights = np.asarray(pos_weights, dtype=float)
    bg = np.asarray(bg_scores, dtype=float)
    expected_weights = np.ones(len(bg)) if bg_weights is None else np.asarray(bg_weights, dtype=float)
    if (len(pos) != len(weights) or len(bg) != len(expected_weights) or
            np.any(expected_weights < 0) or not np.isfinite(expected_weights).all() or
            not 0 < window <= 1 or n_points < 2):
        raise ValueError("Boyce 입력 길이 또는 창 설정이 잘못됐다")
    valid_pos = np.isfinite(pos) & np.isfinite(weights) & (weights > 0)
    valid_bg = np.isfinite(bg) & (expected_weights > 0)
    pos, weights = pos[valid_pos], weights[valid_pos]
    bg, expected_weights = bg[valid_bg], expected_weights[valid_bg]
    empty = {"boyce": np.nan, "curve": pd.DataFrame(columns=["score", "pe"])}
    if not len(pos) or not len(bg) or max(pos.max(), bg.max()) == min(pos.min(), bg.min()):
        return empty
    lo, hi = min(pos.min(), bg.min()), max(pos.max(), bg.max())
    width = window * (hi - lo)
    centers = np.linspace(lo + width / 2, hi - width / 2, n_points)
    pe = np.full(n_points, np.nan)
    for i, center in enumerate(centers):
        in_bg = (bg >= center - width / 2) & (bg <= center + width / 2)
        expected = expected_weights[in_bg].sum()
        if not expected:
            continue
        in_pos = (pos >= center - width / 2) & (pos <= center + width / 2)
        pe[i] = (weights[in_pos].sum() / weights.sum()) / (expected / expected_weights.sum())
    valid = np.isfinite(pe)
    coefficient = float(spearmanr(centers[valid], pe[valid]).statistic) if valid.sum() >= 2 and np.ptp(pe[valid]) > 0 else np.nan
    return {"boyce": coefficient, "curve": pd.DataFrame({"score": centers[valid], "pe": pe[valid]})}



def average_precision_observed(labels: np.ndarray, scores: np.ndarray) -> float:
    """관측 양성 대비 배경 격자의 observed-label 평균정밀도를 구한다."""
    # 평균정밀도 계산 함수를 불러온다.
    from sklearn.metrics import average_precision_score

    # 유효 점수에서 관측 양성의 평균정밀도를 계산한다.
    labels, scores = np.asarray(labels, dtype=bool), np.asarray(scores, dtype=float)
    if len(labels) != len(scores):
        raise ValueError("라벨과 점수 길이가 다르다")
    valid = np.isfinite(scores)
    if not labels[valid].any():
        return np.nan
    return float(average_precision_score(labels[valid], scores[valid]))
