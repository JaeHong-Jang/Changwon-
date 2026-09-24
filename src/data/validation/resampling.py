"""사상·객체 단위 짝지은 재표본 신뢰구간."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import _interval


def paired_bootstrap(
    unit_values: dict[str, np.ndarray], storms: np.ndarray, *, reference: str | None = None,
    resample: str = "object", unit_weights: np.ndarray | dict[str, np.ndarray] | None = None,
    n_boot: int = 2000, seed: int = 42,
) -> pd.DataFrame:
    """폭우 안 객체 또는 폭우 자체를 짝지어 재표본하고 AUC 차이 구간을 구한다."""
    # 값과 가중치를 정리한 뒤 지정한 단위로 재표본한다.
    if resample not in ("object", "storm") or n_boot < 1:
        raise ValueError("재표본 단위 또는 횟수가 잘못됐다")
    names = list(unit_values)
    if reference is not None and reference not in names:
        raise ValueError("기준 점수가 없다")
    storm = np.asarray(storms)
    values = np.column_stack([np.asarray(unit_values[name], dtype=float) for name in names])
    if len(values) != len(storm):
        raise ValueError("객체 값과 사상 길이가 다르다")
    if isinstance(unit_weights, dict):
        weights = np.column_stack([np.asarray(unit_weights[name], dtype=float) for name in names])
    else:
        shared = np.ones(len(storm)) if unit_weights is None else np.asarray(unit_weights, dtype=float)
        weights = np.broadcast_to(shared[:, None], values.shape).copy()
    if weights.shape != values.shape or np.any(weights < 0):
        raise ValueError("객체 가중치가 잘못됐다")
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    weights = np.where(valid, weights, 0)
    values = np.where(valid, values, 0)
    keep = valid.any(axis=1)
    values, storm, weights = values[keep], storm[keep], weights[keep]
    if not len(values):
        return pd.DataFrame(columns=["score", "metric", "value", "ci_lo", "ci_hi", "n_units"])
    unique, inverse = np.unique(storm, return_inverse=True)
    rng = np.random.default_rng(seed)
    if resample == "storm":
        means = []
        for i in range(len(unique)):
            numerator = (values[inverse == i] * weights[inverse == i]).sum(axis=0)
            denominator = weights[inverse == i].sum(axis=0)
            means.append(np.divide(numerator, denominator, out=np.full(len(names), np.nan), where=denominator > 0))
        means = np.vstack(means)
        picks = rng.integers(0, len(unique), (n_boot, len(unique)))
        selected = means[picks]
        draw_count = np.isfinite(selected).sum(axis=1)
        draws = np.divide(np.nansum(selected, axis=1), draw_count,
                          out=np.full((n_boot, len(names)), np.nan), where=draw_count > 0)
        counts = np.isfinite(means).sum(axis=0)
        point = np.divide(np.nansum(means, axis=0), counts,
                          out=np.full(len(names), np.nan), where=counts > 0)
    else:
        picks = np.concatenate([rng.choice(np.flatnonzero(inverse == i), (n_boot, (inverse == i).sum()))
                                for i in range(len(unique))], axis=1)
        denominator = weights[picks].sum(axis=1)
        draws = np.divide((values[picks] * weights[picks]).sum(axis=1), denominator,
                          out=np.full((n_boot, len(names)), np.nan), where=denominator > 0)
        point = np.divide((values * weights).sum(axis=0), weights.sum(axis=0),
                          out=np.full(len(names), np.nan), where=weights.sum(axis=0) > 0)
        counts = (weights > 0).sum(axis=0)
    rows = []
    for j, name in enumerate(names):
        lo, hi = _interval(draws[:, j])
        rows.append({"score": name, "metric": "observed-label_auc", "value": float(point[j]),
                     "ci_lo": lo, "ci_hi": hi, "n_units": int(counts[j])})
        if reference is not None and name != reference:
            ref = names.index(reference)
            lo, hi = _interval(draws[:, j] - draws[:, ref])
            rows.append({"score": name, "metric": "observed-label_auc_diff", "value": float(point[j] - point[ref]),
                         "ci_lo": lo, "ci_hi": hi, "n_units": int(min(counts[j], counts[ref]))})
    return pd.DataFrame(rows)

