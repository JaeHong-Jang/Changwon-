"""M4S 창원 기준점: M4 공식 산출에서 (시험 사상, 점수)마다 σ̂·β̂·Δ̂* 와 관측 차이·공분산 형태를 구한다 (docs/q1/M4S_protocol.md §7, post-hoc)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

M4_RUN = "artifacts/q1/M4/m4_20260926T170511Z_1edf87c"
RULES = ("f10", "soft")
SIZE = 100
MIN_OBJECTS = 20
CLIP = 0.005


def fit_anchor(area: np.ndarray, object_value: np.ndarray) -> dict[str, float]:
    """σ̂ = sd(ln a), μ̂_k = √2 Φ⁻¹(Ã_k) 를 ζ̂ 에 OLS 로 맞춘 μ̂0·β̂·τ̂ 와 Δ̂*."""
    from src.synth.tilt import tilted_gap

    # 로그 면적을 표준화하고 객체 값을 탐지력 척도로 바꾼다
    log_a = np.log(np.asarray(area, dtype=float))
    sigma = float(log_a.std())
    zeta = (log_a - log_a.mean()) / sigma
    mu = np.sqrt(2.0) * norm.ppf(np.clip(np.asarray(object_value, dtype=float), CLIP, 1.0 - CLIP))

    # 최소제곱으로 절편·기울기를 구하고 잔차 모표준편차를 τ̂ 로 둔다
    X = np.column_stack([np.ones_like(zeta), zeta])
    (mu0, beta), *_ = np.linalg.lstsq(X, mu, rcond=None)
    tau = float((mu - X @ np.array([mu0, beta])).std())
    return {"sigma_hat": sigma, "mu0_hat": float(mu0), "beta_hat": float(beta), "tau_hat": tau,
            "delta_hat": tilted_gap(sigma, float(beta), float(mu0), tau)}


def anchors(root: Path) -> pd.DataFrame:
    """유한한 Ã 가 20개 이상인 (시험 사상, 점수, 규칙)의 기준점 표."""
    from src.data.validation.weight_concentration import covariance_form, top_share

    # M4 객체 기여 표와 분해 표에서 100 m·f10/soft 행만 읽는다
    objects = pd.read_parquet(root / M4_RUN / "object_contrib.parquet")
    objects = objects[(objects["size_m"] == SIZE) & objects["rule"].isin(RULES)]
    decomposition = pd.read_csv(root / M4_RUN / "decomposition.csv", encoding="utf-8-sig", dtype={"test_event": str})
    decomposition = decomposition[(decomposition["size_m"] == SIZE) & decomposition["rule"].isin(RULES)].set_index(
        ["test_event", "score", "rule"])

    # 묶음마다 기준점을 맞추고 관측 분해·공분산 형태를 붙인다
    rows = []
    for (event, score, rule), part in objects.groupby(["test_event", "score", "rule"], sort=True):
        ok = part[np.isfinite(part["A_object"]) & (part["area_m2"] > 0)]
        if len(ok) < MIN_OBJECTS or (event, score, rule) not in decomposition.index:
            continue
        d = decomposition.loc[(event, score, rule)]
        cov = covariance_form(part["W"].to_numpy(), part["A_gate"].to_numpy(), part["A_object"].to_numpy())
        exact = d["orphan_weight"] == 0 and d["n_survive_no_At"] == 0
        rows.append({"test_event": event, "role": part["role"].iloc[0], "score": score, "rule": rule, "n_objects": len(ok),
                     **fit_anchor(ok["area_m2"].to_numpy(), ok["A_object"].to_numpy()),
                     "cell_auc": d["cell_auc"], "object_auc": d["object_auc"], "gap": d["cell_auc"] - d["object_auc"],
                     "term_size_weight": d["term_size_weight"], "term_within_object": d["term_within_object"],
                     "term_erasure": d["term_erasure"], "n_eff": d["n_eff"], "n_survive": d["n_survive"],
                     "top10_share": top_share(part["W"].to_numpy(), 0.1), "sd_A": cov["sd_A"], "rho_wA": cov["rho_wA"],
                     "concentration_factor": cov["concentration_factor"], "size_term_product": cov["size_term_product"],
                     "cov_abs_diff": abs(cov["size_term_product"] - d["term_size_weight"]) if exact else np.nan})
    return pd.DataFrame(rows)
