"""M2 S4 표준오차 점검: M1 과 같은 덩어리 재표본을 다시 뽑아 구간 재현·SE 근사·점수 간 상관을 잰다 (개발만)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data import layers
from src.data.uncertainty import _ClusteredPositives, _resample, auc_fractions
from src.data.validation.meta_analysis import logit, se_from_ci


def cluster_draws(labels: np.ndarray, score: np.ndarray, x: np.ndarray, y: np.ndarray, *, n_boot: int = 1000,
                  seed: int = 42) -> dict:
    """cell_gate 격자 AUC 의 점값·재표본값·덩어리 수 (V.cell_auc 와 같은 계산 순서)."""
    # 점수가 유한한 격자만 남기고 비양성 전부를 배경으로 둔다 (cell_gate)
    labels, score = np.asarray(labels, bool), np.asarray(score, float)
    keep = np.isfinite(score)
    truth = labels[keep]
    if not truth.any() or truth.all():
        return {"auc": np.nan, "draws": np.array([]), "n_cluster": 0, "positive_keep": keep & labels}

    # 양성 덩어리를 같은 seed 로 복원추출해 격자 가중 AUC 를 다시 뽑는다
    fractions = auc_fractions(truth, score[keep])
    cp = _ClusteredPositives(truth, np.asarray(x)[keep], np.asarray(y)[keep])
    picks = _resample(cp.n_cluster, n_boot, seed)
    draws = cp.sums(fractions)[picks].sum(axis=1) / cp.counts[picks].sum(axis=1)
    return {"auc": layers.roc_auc(truth, score[keep]), "draws": draws, "n_cluster": cp.n_cluster,
            "positive_keep": keep & labels}


def _logit_draws(draws: np.ndarray) -> tuple[np.ndarray, int]:
    """재표본 AUC 의 logit 과 무한(0 또는 1) 개수."""
    with np.errstate(divide="ignore"):
        z = logit(draws)
    return z, int((~np.isfinite(z)).sum())


def check_event(event: str, labels: np.ndarray, scores: dict[str, np.ndarray], x: np.ndarray, y: np.ndarray,
                pairs: list[tuple[str, str]], *, reference: str = "slope_neg", n_boot: int = 1000,
                seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """한 사상의 점수별 재표본 요약과 짝(모델 − 기준선)별 logit 차이 SE·상관."""
    # 점수마다 재표본을 뽑아 점값·백분위 구간·logit SD 를 기록한다
    result = {name: cluster_draws(labels, s, x, y, n_boot=n_boot, seed=seed) for name, s in scores.items()}
    rows = []
    for name, r in result.items():
        z, bad = _logit_draws(r["draws"])
        finite = z[np.isfinite(z)]
        lo, hi = (np.round(np.percentile(r["draws"], [2.5, 97.5]), 4) if len(r["draws"]) else (np.nan, np.nan))
        rows.append({"test_event": event, "score": name, "auc_recomputed": r["auc"], "ci_lo_recomputed": lo,
                     "ci_hi_recomputed": hi, "n_clusters": r["n_cluster"], "n_pos_cells": int(r["positive_keep"].sum()),
                     "se_draw": float(np.std(finite, ddof=1)) if len(finite) > 1 else np.nan,
                     "n_nonfinite_draws": bad})

    # 양성 격자 집합이 같아 재표본이 짝지어지는 경우에만 logit 차이 SD 와 상관을 잰다
    pair_rows = []
    for model, base in pairs + [(n, reference) for n in scores if n != reference and (n, reference) not in pairs]:
        a, b = result.get(model), result.get(base)
        if a is None or b is None or not len(a["draws"]) or not len(b["draws"]):
            continue
        aligned = np.array_equal(a["positive_keep"], b["positive_keep"])
        za, zb = _logit_draws(a["draws"])[0], _logit_draws(b["draws"])[0]
        ok = aligned & np.isfinite(za) & np.isfinite(zb)
        pair_rows.append({"test_event": event, "model": model, "baseline": base, "aligned": bool(aligned),
                          "se_diff_draw": float(np.std(za[ok] - zb[ok], ddof=1)) if np.sum(ok) > 1 else np.nan,
                          "corr_draw": float(np.corrcoef(za[ok], zb[ok])[0, 1]) if np.sum(ok) > 1 else np.nan})
    return pd.DataFrame(rows), pd.DataFrame(pair_rows).drop_duplicates(["test_event", "model", "baseline"])


def compare_with_m1(check: pd.DataFrame, effect_rows: pd.DataFrame) -> pd.DataFrame:
    """재계산 점값·구간을 M1 저장값과 맞대고 SE_draw / SE_ci 비를 붙인다."""
    # M1 전 격자 cell_gate 행을 점수·사상으로 붙인다
    m1 = effect_rows[(effect_rows["unit"] == "cell_gate") & (effect_rows["stratum"] == "ALL")]
    m1 = m1.set_index(["score", "test_event"])[["auc", "ci_lo", "ci_hi", "se", "included"]]
    out = check.join(m1, on=["score", "test_event"], how="left")
    se_ci = se_from_ci(out["ci_lo"].to_numpy(float), out["ci_hi"].to_numpy(float))
    return out.assign(se_ci=se_ci, se_ratio=out["se_draw"] / se_ci,
                      abs_diff_auc=(out["auc_recomputed"] - out["auc"]).abs(),
                      abs_diff_ci=np.maximum((out["ci_lo_recomputed"] - out["ci_lo"]).abs(),
                                             (out["ci_hi_recomputed"] - out["ci_hi"]).abs()))
