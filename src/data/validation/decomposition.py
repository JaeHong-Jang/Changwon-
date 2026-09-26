"""격자 AUC 를 객체 기여의 가중평균으로 분해하고 객체 AUC 와의 차이를 세 항으로 나눈다 (docs/q1/M4_protocol.md §6)."""

from __future__ import annotations

from typing import Any

import numpy as np

from src.data.trace_footprint import Footprint
from ._common import _mid_cdf
from .weighted_auc import weighted_mid_cdf


def object_terms(score: np.ndarray, p: np.ndarray, fp: Footprint, background: np.ndarray) -> dict[str, Any]:
    """객체별 가중치 W_k, 게이트 기여 A_k, 객체 AUC 값 Ã_k 와 할당되지 않은 양성 질량을 구한다."""
    # 게이트 배경(음성 질량 1 − p) 대비 칸 점수의 중간 누적분포 F 를 구한다
    s = np.asarray(score, dtype=float)
    p = np.asarray(p, dtype=float)
    finite = np.isfinite(s)
    F = weighted_mid_cdf(s, s[finite], (1.0 - p)[finite])

    # 양성 칸 질량을 겹친 폴리곤들에 겹침 면적 비율로 나눠 W_k 와 A_k 를 모은다
    overlap = np.bincount(fp.cell, weights=fp.area, minlength=fp.n_cells)
    share = np.divide(fp.area, overlap[fp.cell], out=np.zeros(len(fp.area)), where=overlap[fp.cell] > 0)
    mass = np.where(finite[fp.cell], p[fp.cell] * share, 0.0)
    W = np.bincount(fp.obj, weights=mass, minlength=fp.n_obj)
    num = np.bincount(fp.obj, weights=mass * np.nan_to_num(F[fp.cell]), minlength=fp.n_obj)
    A = np.divide(num, W, out=np.full(fp.n_obj, np.nan), where=W > 0)

    # 어떤 폴리곤과도 겹치지 않은 양성 칸은 따로 센다 (정의상 없어야 한다)
    orphan = finite & (p > 0) & (overlap <= 0)

    # 비접촉 배경 대비 겹침 면적가중 객체 값 Ã_k (evaluate 의 객체 AUC 와 같은 정의)
    bg = np.asarray(background, dtype=bool) & finite
    G = _mid_cdf(s[fp.cell], s[bg])
    valid = np.isfinite(s[fp.cell]) & np.isfinite(G)
    g_num = np.bincount(fp.obj[valid], weights=fp.area[valid] * G[valid], minlength=fp.n_obj)
    g_den = np.bincount(fp.obj[valid], weights=fp.area[valid], minlength=fp.n_obj)
    At = np.divide(g_num, g_den, out=np.full(fp.n_obj, np.nan), where=g_den > 0)
    return {"W": W, "A": A, "At": At, "orphan_mass": float(p[orphan].sum()),
            "orphan_sum": float(np.dot(p[orphan], F[orphan])), "n_orphan_cells": int(orphan.sum())}


def decompose(terms: dict[str, Any]) -> dict[str, float]:
    """A = Σ w_k A_k 와 A − Ã = 크기 가중 + 객체 안 + 소실 세 항을 계산한다."""
    # 객체 가중치를 정규화해 격자 AUC 를 객체 기여의 가중평균으로 다시 만든다
    W, A, At = terms["W"], terms["A"], terms["At"]
    total = W.sum() + terms["orphan_mass"]
    if total <= 0:
        return {"auc_from_objects": np.nan, "n_objects": int(len(W)), "n_survive": 0}
    w = W / total
    auc = float((np.dot(W[W > 0], A[W > 0]) + terms["orphan_sum"]) / total)

    # 생존 객체 S(유한한 Ã 가 있는 것) 안의 동일가중 평균으로 세 항을 만든다
    K = np.isfinite(At)
    S = (W > 0) & K
    a_s = float(A[S].mean()) if S.any() else np.nan
    at_s = float(At[S].mean()) if S.any() else np.nan
    at_all = float(At[K].mean()) if K.any() else np.nan
    return {"auc_from_objects": auc, "object_auc": at_all, "mean_A_survivors": a_s, "mean_At_survivors": at_s,
            "term_size_weight": auc - a_s, "term_within_object": a_s - at_s, "term_erasure": at_s - at_all,
            "n_eff": float(1.0 / np.sum(w ** 2)) if np.any(w > 0) else np.nan,
            "n_objects": int(len(W)), "n_survive": int((W > 0).sum()), "n_survive_no_At": int(((W > 0) & ~K).sum()),
            "orphan_weight": float(terms["orphan_mass"] / total), "n_orphan_cells": terms["n_orphan_cells"]}
