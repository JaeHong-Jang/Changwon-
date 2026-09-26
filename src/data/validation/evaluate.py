"""검증 지표를 층·사상·점수별 표로 통합한다."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from src.data import layers, uncertainty
from ._common import COLUMNS, FRACTIONS, _interval, _mid_cdf, _overlaps
from .auc import cell_auc
from .curves import _object_capture, average_precision_observed, capture_curve, continuous_boyce
from .resampling import paired_bootstrap

if TYPE_CHECKING:
    import geopandas as gpd


def evaluate(
    scores: dict[str, np.ndarray], grid: gpd.GeoDataFrame, traces: gpd.GeoDataFrame,
    *, strata: dict[str, np.ndarray] | None = None, background_mask: np.ndarray | None = None,
    min_overlap: float = 0.10, reference: str | None = None, n_boot: int = 2000, seed: int = 42,
) -> pd.DataFrame:
    """cell_gate는 전 비양성·덩어리 구간·포착률, cell_bg는 비접촉 배경을 쓰며 결측 제외 면적과 사상 동일가중 평균을 기록한다."""
    # 입력을 검사하고 층·사상·점수별 결과 행을 순서대로 생성한다.
    if not 0 <= min_overlap <= 1 or n_boot < 1:
        raise ValueError("겹침 임계값 또는 재표본 횟수가 잘못됐다")
    if "storm_id" not in traces or "object_id" not in traces:
        raise ValueError("흔적에 storm_id와 object_id가 필요하다")
    if traces.duplicated(["storm_id", "object_id"]).any():
        raise ValueError("사상 안에서 object_id가 중복된다")
    if reference is not None and reference not in scores:
        raise ValueError("기준 점수가 없다")
    if not scores:
        raise ValueError("평가할 점수가 없다")
    n = len(grid)
    for name, score in scores.items():
        if len(score) != n:
            raise ValueError(f"{name} 점수와 격자 길이가 다르다")
    if background_mask is not None and len(background_mask) != n:
        raise ValueError("배경 마스크와 격자 길이가 다르다")

    # 각 층의 격자·점수·흔적 교차 정보를 준비한다.
    masks = {"ALL": np.ones(n, bool)} if strata is None else {"ALL": np.ones(n, bool), **strata}
    rows = []
    for stratum, mask in masks.items():
        mask = np.asarray(mask, dtype=bool)
        if len(mask) != n:
            raise ValueError("층화 마스크와 격자 길이가 다르다")
        grid_part = grid.loc[mask].reset_index(drop=True)
        score_part = {name: np.asarray(score, dtype=float)[mask] for name, score in scores.items()}
        given_background = None if background_mask is None else np.asarray(background_mask, dtype=bool)[mask]
        all_obj, all_cell, all_area, all_point, all_geometry = _overlaps(grid_part, traces)
        storms = traces["storm_id"].to_numpy()
        storm_names = list(pd.unique(storms))
        cell_area = grid_part.geometry.area.to_numpy()
        centers = grid_part.geometry.centroid
        x, y = centers.x.to_numpy(), centers.y.to_numpy()

        # 전체와 각 사상의 교차 면적을 격자 라벨과 배경으로 바꾼다.
        for storm_name in ["ALL", *storm_names]:
            selected = np.ones(len(traces), bool) if storm_name == "ALL" else storms == storm_name
            object_ids = np.flatnonzero(selected)
            pair_keep = selected[all_obj]
            obj_global, cell, area = all_obj[pair_keep], all_cell[pair_keep], all_area[pair_keep]
            intersection = all_geometry[pair_keep]
            obj = np.searchsorted(object_ids, obj_global)
            point = all_point[object_ids]
            flood_area = np.bincount(cell, weights=area, minlength=len(grid_part))
            label_area = np.minimum(flood_area, cell_area)
            if len(cell):
                import shapely

                # 같은 격자에 여러 흔적이 닿으면 합집합 면적을 사용한다.
                repeated = np.flatnonzero(np.bincount(cell, minlength=len(grid_part)) > 1)
                for index in repeated:
                    label_area[index] = shapely.area(shapely.union_all(intersection[cell == index]))
            labels = label_area > min_overlap * cell_area
            touched = flood_area > 0
            bg = ~touched if given_background is None else given_background.copy()
            if np.any(bg & touched):
                raise ValueError("배경 마스크가 평가 흔적과 겹친다")
            obj_storms = storms[object_ids]
            per_object: dict[str, np.ndarray] = {}
            per_point: dict[str, np.ndarray] = {}
            per_area: dict[str, np.ndarray] = {}
            per_area_weights: dict[str, np.ndarray] = {}

            # 공통 유효 격자에서 기준 점수와 비교 점수의 짝지은 차이를 기록한다.
            if reference is not None and len(scores) > 1 and labels.any():
                for suffix, comparison_bg in (("gate", ~labels), ("bg", bg)):
                    common = (labels | comparison_bg) & np.logical_and.reduce(
                        [np.isfinite(s) for s in score_part.values()])
                    if not labels[common].any() or not comparison_bg[common].any():
                        continue
                    paired = uncertainty.paired_cluster_bootstrap(
                        labels[common], {name: score[common] for name, score in score_part.items()},
                        reference, x[common], y[common], n_boot=n_boot, seed=seed,
                    )
                    for name in scores:
                        if name == reference:
                            continue
                        comparison = paired[name]
                        for unit, value_key, ci_key, count in (
                            (f"cell_{suffix}", "diff", "diff_ci95", int(labels[common].sum())),
                            (f"cluster_{suffix}", "diff_cluster_weighted", "diff_ci95_cluster_weighted", paired["n_cluster"]),
                        ):
                            rows.append((name, unit, stratum, storm_name, "observed-label_auc_diff",
                                         comparison[value_key], *comparison[ci_key], count))

            # 점수마다 객체·격자 AUC와 정밀도·Boyce·포착률을 기록한다.
            for name, score in score_part.items():
                finite = np.isfinite(score)
                finite_bg = bg & finite
                fraction = _mid_cdf(score[cell], score[finite_bg])
                valid = np.isfinite(score[cell]) & np.isfinite(fraction)
                obj_sum = np.bincount(obj[valid], weights=area[valid] * fraction[valid], minlength=len(object_ids))
                valid_area = np.bincount(obj[valid], weights=area[valid], minlength=len(object_ids))
                obj_auc = np.divide(obj_sum, valid_area, out=np.full(len(object_ids), np.nan), where=valid_area > 0)
                point_auc = np.full(len(object_ids), np.nan)
                point_valid = (point >= 0) & np.isfinite(score[np.maximum(point, 0)]) if len(score) else np.zeros(len(point), bool)
                point_auc[point_valid] = _mid_cdf(score[point[point_valid]], score[finite_bg])
                per_object[name], per_point[name], per_area[name] = obj_auc, point_auc, obj_auc
                per_area_weights[name] = valid_area
                for suffix, comparison_bg in (("gate", ~labels), ("bg", bg)):
                    cell_result = cell_auc(labels, score, x, y, background_mask=comparison_bg,
                                           n_boot=n_boot, seed=seed)
                    for unit, key, ci, count in (
                        (f"cell_{suffix}", "observed-label_auc_cell", "ci95_cell", int((labels & finite).sum())),
                        (f"cluster_{suffix}", "observed-label_auc_cluster", "ci95_cluster", cell_result["n_cluster"]),
                    ):
                        rows.append((name, unit, stratum, storm_name, "observed-label_auc", cell_result[key],
                                     *cell_result[ci], count))
                    eligible = (labels | comparison_bg) & finite
                    ap = average_precision_observed(labels[eligible], score[eligible])
                    rows.append((name, f"cell_{suffix}", stratum, storm_name, "observed-label_ap",
                                 ap, np.nan, np.nan, int((labels & eligible).sum())))
                excluded = cell_area[~finite].sum() / cell_area.sum() if cell_area.sum() else np.nan
                rows.append((name, "cell_gate", stratum, storm_name, "excluded_area_fraction",
                             excluded, np.nan, np.nan, int(finite.sum())))
                boyce = continuous_boyce(score[cell], area, score, bg_weights=cell_area)
                rows.append((name, "area", stratum, storm_name, "boyce", boyce["boyce"], np.nan, np.nan,
                             int(np.count_nonzero(valid_area))))
                for fraction in FRACTIONS:
                    capture = layers.top_share_lift(labels, score, fraction)["capture_rate"]
                    rows.append((name, "cell_gate", stratum, storm_name, f"capture_{fraction:g}", capture,
                                 np.nan, np.nan, int(labels.sum())))
                curve = capture_curve(score, flood_area, cell_areas=cell_area)
                for row in curve.itertuples():
                    rows.append((name, "area", stratum, storm_name, f"capture_{row.fraction:g}", row.capture,
                                 np.nan, np.nan, row.n_units))
                curve = _object_capture(score, cell_area, obj, cell, area, len(object_ids))
                for row in curve.itertuples():
                    rows.append((name, "object", stratum, storm_name, f"capture_{row.fraction:g}", row.capture,
                                 np.nan, np.nan, row.n_units))

            # 객체·대표점·면적 AUC의 짝지은 재표본 행을 추가한다.
            for unit, values, weights in (("object", per_object, None),
                                          ("representative", per_point, None),
                                          ("area", per_area, per_area_weights)):
                frame = paired_bootstrap(values, obj_storms, reference=reference, resample="object",
                                         unit_weights=weights, n_boot=n_boot, seed=seed)
                for row in frame.itertuples():
                    rows.append((row.score, unit, stratum, storm_name, row.metric, row.value,
                                 row.ci_lo, row.ci_hi, row.n_units))

    # 사상별 값의 동일가중 평균과 신뢰구간을 전체 결과 뒤에 붙인다.
    result = pd.DataFrame(rows, columns=COLUMNS)
    storm_rows = result[result["storm"].isin(traces["storm_id"].unique())]
    macro = []
    rng = np.random.default_rng(seed)
    for (score, unit, stratum, metric), frame in storm_rows.groupby(["score", "unit", "stratum", "metric"], sort=False):
        if ((result["score"] == score) & (result["unit"] == unit) & (result["stratum"] == stratum) &
                (result["storm"] == "MACRO") & (result["metric"] == metric)).any():
            continue
        values = frame["value"].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if not len(values):
            value, lo, hi = np.nan, np.nan, np.nan
        else:
            value = float(values.mean())
            draws = values[rng.integers(0, len(values), (n_boot, len(values)))].mean(axis=1)
            lo, hi = _interval(draws)
        macro.append((score, unit, stratum, "MACRO", metric, value, lo, hi, len(values)))
    return pd.concat([result, pd.DataFrame(macro, columns=COLUMNS)], ignore_index=True)
