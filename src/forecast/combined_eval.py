"""사상별 결합 Brier와 위치 지표를 계산한다."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data import validation as V

SEED = 20260926
N_BOOT = 2000


def evaluate_storms(storms, p: dict, q: dict, y: dict, p_ref: dict) -> pd.DataFrame:
    """사상별 결합 확률과 동일 q 기준의 제곱오차를 집계한다."""
    # 확률이 있는 라벨 사상만 한 개씩 순회해 격자 행렬 생성을 피한다.
    rows = []
    for storm in storms.itertuples():
        sid = str(storm.storm_id)
        try:
            event_label = float(storm.label)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{sid}: 사상 라벨은 유한한 0/1이어야 한다") from error
        if not np.isfinite(event_label) or event_label not in (0, 1):
            raise ValueError(f"{sid}: 사상 라벨은 유한한 0/1이어야 한다")
        if sid not in p or sid not in p_ref or sid not in q:
            continue
        score = np.asarray(q[sid], float)
        truth = np.zeros(len(score), float) if int(event_label) == 0 else np.asarray(y[sid], float)
        if (score.ndim != 1 or not len(score) or score.shape != truth.shape or
                not np.isfinite(score).all() or ((score < 0) | (score > 1)).any()):
            raise ValueError(f"{sid}: q 격자 점수·라벨 길이 또는 범위가 잘못됐다")
        if not np.isfinite(truth).all() or not np.isin(truth, [0, 1]).all():
            raise ValueError(f"{sid}: 격자 라벨은 유한한 0/1이어야 한다")
        probability, reference = float(p[sid]), float(p_ref[sid])
        if not 0 <= probability <= 1 or not 0 <= reference <= 1:
            raise ValueError(f"{sid}: 사상 확률 범위가 잘못됐다")

        # 격자 제곱오차와 예상·관측 양성 면적을 사상 하나로 압축한다.
        predicted = probability * score
        baseline = reference * score
        sse = float(np.square(predicted - truth).sum())
        sse_ref = float(np.square(baseline - truth).sum())
        rows.append({"storm_id": sid, "label": int(storm.label), "n_cells": len(score),
                     "sse": sse, "sse_ref": sse_ref, "mean_brier": sse / len(score),
                     "mean_brier_ref": sse_ref / len(score), "predicted_area": float(predicted.sum()),
                     "observed_area": float(truth.sum()),
                     "area_error": float(predicted.sum() - truth.sum())})
    return pd.DataFrame(rows)


def summarize(per_storm: pd.DataFrame, *, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """전체 Brier·BSS와 사상 짝지은 붓스트랩 구간을 반환한다."""
    # 모든 사상 격자를 합쳐 Brier와 기준 대비 BSS를 계산한다.
    if per_storm.empty:
        return {"n_storms": 0, "brier": np.nan, "brier_ref": np.nan, "bss": np.nan,
                "bss_ci_lo": np.nan, "bss_ci_hi": np.nan, "n_boot_valid": 0,
                "n_boot_excluded": n_boot}
    n = int(per_storm["n_cells"].sum())
    sse = per_storm["sse"].to_numpy(float)
    ref = per_storm["sse_ref"].to_numpy(float)
    total_ref = ref.sum()
    bss = 1 - sse.sum() / total_ref if total_ref > 0 else np.nan

    # 사상별 오차 쌍을 함께 재표집해 정의 가능한 BSS만 남긴다.
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(sse), size=(n_boot, len(sse)))
    draw_sse, draw_ref = sse[picks].sum(axis=1), ref[picks].sum(axis=1)
    valid = draw_ref > 0
    draws = 1 - draw_sse[valid] / draw_ref[valid]
    lo, hi = (np.percentile(draws, [2.5, 97.5]) if len(draws) else (np.nan, np.nan))
    result = {"n_storms": len(per_storm), "n_cells": n, "brier": float(sse.sum() / n),
              "brier_ref": float(total_ref / n), "bss": float(bss), "bss_ci_lo": float(lo),
              "bss_ci_hi": float(hi), "n_boot_valid": int(valid.sum()),
              "n_boot_excluded": int((~valid).sum())}

    # 양성·음성 사상의 평균 Brier와 전체 오차 기여율을 각각 기록한다.
    for label, name in ((1, "positive"), (0, "negative")):
        subset = per_storm[per_storm["label"].eq(label)]
        result[f"{name}_n_storms"] = len(subset)
        result[f"{name}_mean_brier"] = float(subset["mean_brier"].mean()) if len(subset) else np.nan
        result[f"{name}_sse_share"] = (float(subset["sse"].sum() / sse.sum()) if sse.sum() > 0 else np.nan)
    return result


def positive_storm_metrics(q: dict, y: dict, objects: dict, grid) -> pd.DataFrame:
    """양성 사상별 격자 AUC·상위 20% 포착·객체 1표 AUC를 계산한다."""
    # 동점은 grid_id 오름차순으로 끊고 기존 검증 함수를 호출한다.
    rows = []
    ids = grid["grid_id"].to_numpy()
    centers = grid.geometry.centroid
    for sid, label in y.items():
        score = np.asarray(q[sid], float)
        truth = np.asarray(label, bool)
        if len(score) != len(grid) or len(truth) != len(grid):
            raise ValueError(f"{sid}: 격자 수가 다르다")
        order = np.lexsort((ids, -score))
        take = max(1, int(np.ceil(0.2 * len(score))))
        capture = truth[order[:take]].sum() / truth.sum() if truth.any() else np.nan
        auc = V.cell_auc(truth, score, centers.x.to_numpy(), centers.y.to_numpy(), n_boot=2000,
                         seed=SEED)["observed-label_auc_cell"]
        polygons = objects[sid]
        object_auc = V.object_auc(score, grid, polygons)["observed-label_auc_object"] if len(polygons) else np.nan
        rows.append({"storm_id": sid, "n_positive_cells": int(truth.sum()), "cell_auc": auc,
                     "top20_capture": float(capture), "object_auc": object_auc,
                     "n_objects": len(polygons)})
    return pd.DataFrame(rows)


def primary_endpoint_2(summary: dict) -> dict:
    """V1·S1·common 주 판정의 BSS와 해석 문구를 고정한다."""
    # 신뢰구간 하한이 양수인 경우에만 결합 확률 개선으로 판정한다.
    lower = summary["bss_ci_lo"]
    improved = bool(summary["brier"] < summary["brier_ref"])
    return {"scheme": "V1_loso", "subset": "S1", "set": "common", "model": "M_fc24",
            "reference": "B_clim", "bss": summary["bss"], "bss_ci_lo": lower,
            "bss_ci_hi": summary["bss_ci_hi"], "brier_improved": improved,
            "lower_gt_zero": bool(np.isfinite(lower) and lower > 0),
            "pass": bool(improved and np.isfinite(lower) and lower > 0),
            "interpretation": "결합 확률의 Brier 개선이며 위치 예측 개선이 아님"}
