"""M2 효과 크기: M1 긴 표의 사상별 AUC 를 logit·부트스트랩 SE 로 바꾸고 포함 규칙과 짝 차이를 만든다."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.validation.meta_analysis import logit, se_from_ci

UNITS = ("cell_gate", "cluster_gate", "object")
GRID_UNITS = ("cell_gate", "cluster_gate")
MIN_POSITIVE_CELLS = 5
MIN_POLYGONS = 3
KEYS = ["score", "unit", "stratum", "test_event"]


def effects(long: pd.DataFrame) -> pd.DataFrame:
    """점수·단위·층·사상마다 AUC·구간·logit·SE·표본 수와 포함 여부(이유)를 한 행으로 만든다."""
    # 사상 전체(storm=ALL) AUC 행만 고르고 같은 점수·층·사상의 양성 격자·덩어리 수를 붙인다
    auc = long[(long["storm"] == "ALL") & (long["metric"] == "observed-label_auc") & long["unit"].isin(UNITS)]
    grid = auc[auc["unit"] == "cell_gate"].set_index(["score", "stratum", "test_event"])["n_units"]
    clusters = auc[auc["unit"] == "cluster_gate"].set_index(["score", "stratum", "test_event"])["n_units"]
    key = pd.MultiIndex.from_frame(auc[["score", "stratum", "test_event"]])
    frame = auc[KEYS + ["role", "value", "ci_lo", "ci_hi", "n_units"]].rename(columns={"value": "auc"}).assign(
        n_pos_cells=grid.reindex(key).to_numpy(), n_clusters=clusters.reindex(key).to_numpy())

    # 포함 규칙: 유한한 0<AUC<1, 최소 표본, 0<ci_lo<ci_hi<1 (절차 §3)
    grid_unit = frame["unit"].isin(GRID_UNITS)
    reasons = np.select(
        [~np.isfinite(frame["auc"]) | (frame["auc"] <= 0) | (frame["auc"] >= 1),
         grid_unit & ~(frame["n_pos_cells"] >= MIN_POSITIVE_CELLS),
         ~grid_unit & ~(frame["n_units"] >= MIN_POLYGONS),
         ~(np.isfinite(frame["ci_lo"]) & np.isfinite(frame["ci_hi"])),
         ~((frame["ci_lo"] > 0) & (frame["ci_lo"] < frame["ci_hi"]) & (frame["ci_hi"] < 1))],
        ["auc_missing_or_boundary", "positive_cells_lt_5", "polygons_lt_3", "ci_missing", "ci_degenerate_or_boundary"],
        default="")
    frame = frame.assign(included=reasons == "", reason=reasons)

    # 포함된 행에만 logit AUC 와 구간에서 되돌린 SE 를 채운다
    ok = frame["included"].to_numpy()
    y, se = np.full(len(frame), np.nan), np.full(len(frame), np.nan)
    y[ok] = logit(frame.loc[ok, "auc"].to_numpy(float))
    se[ok] = se_from_ci(frame.loc[ok, "ci_lo"].to_numpy(float), frame.loc[ok, "ci_hi"].to_numpy(float))
    return frame.assign(y=y, se=se).reset_index(drop=True)


def paired(frame: pd.DataFrame, model: str, baseline: str, *, rho: float = 0.0) -> pd.DataFrame:
    """두 점수가 모두 포함된 사상에서 logit 차이와 상관 ρ 를 가정한 SE 를 만든다."""
    # 모델·기준선 행을 단위·층·사상으로 맞붙여 둘 다 포함된 행만 남긴다
    cols = ["unit", "stratum", "test_event"]
    keep = ["role", "auc", "y", "se", "n_units", "n_pos_cells", "n_clusters", "included"]
    a = frame[frame["score"] == model].set_index(cols)[keep]
    b = frame[frame["score"] == baseline].set_index(cols)[keep]
    both = a.join(b, how="inner", lsuffix="_m", rsuffix="_b")
    both = both[both["included_m"] & both["included_b"]]

    # 차이와 분산 SE_m² + SE_b² − 2ρ SE_m SE_b 를 계산한다
    var = both["se_m"] ** 2 + both["se_b"] ** 2 - 2 * rho * both["se_m"] * both["se_b"]
    return pd.DataFrame({"model": model, "baseline": baseline, "rho": rho, "role": both["role_m"],
                         "auc_m": both["auc_m"], "auc_b": both["auc_b"], "y": both["y_m"] - both["y_b"],
                         "se": np.sqrt(var), "n_units": both[["n_units_m", "n_units_b"]].min(axis=1),
                         "n_pos_cells": both["n_pos_cells_m"],
                         "n_clusters": both[["n_clusters_m", "n_clusters_b"]].min(axis=1)}).reset_index()
