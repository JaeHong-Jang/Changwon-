"""M2 통합: 집합(개발·홀드아웃·합산)별 무작위효과 통합, 민감도 변형, 한 사상 빼기, 홀드아웃 이전 가능성."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.validation.meta_analysis import expit, random_effects
from src.models.m2_effects import GRID_UNITS, paired

SETS = {"development": ("development",), "holdout": ("holdout",), "combined": ("development", "holdout")}
MIN_CLUSTERS = 5
BASELINES = ("slope_neg", "relelev_neg", "twi", "impervious", "hand_neg", "hand_acc_neg")
PAIRS = [("rf_F1_wf", b) for b in BASELINES] + [(m, "slope_neg") for m in ("logit_F1_wf", "L1", "z_sensitivity")]
SCORE_VARIANTS = {"main": ("REML", "mhksj"), "S1_dl_wald": ("DL", "wald"), "S2_min5clusters": ("REML", "mhksj")}
DIFF_VARIANTS = {"main": ("REML", "mhksj", 0.0), "S1_dl_wald": ("DL", "wald", 0.0),
                 "S2_min5clusters": ("REML", "mhksj", 0.0), "S3_rho0.5": ("REML", "mhksj", 0.5),
                 "S3_rho0.8": ("REML", "mhksj", 0.8)}


def pool(sub: pd.DataFrame, *, method: str = "REML", ci: str = "mhksj", auc_scale: bool = True) -> dict:
    """사상 행들(y·se·auc·n_units)을 통합하고 유효 표본 열(가중치 비중·Kish k)을 붙인다."""
    # 무작위효과 통합과 AUC 척도 역변환
    sub = sub.sort_values("test_event")
    r = random_effects(sub["y"].to_numpy(float), sub["se"].to_numpy(float), method=method, ci=ci)
    events = sub["test_event"].astype(str).tolist()
    row = {k: r[k] for k in ("k", "mu", "se", "ci_lo", "ci_hi", "pi_lo", "pi_hi", "tau2", "tau2_lo", "tau2_hi",
                             "q", "q_p", "i2", "i2_lo", "i2_hi")}
    row["tau"] = float(np.sqrt(r["tau2"])) if np.isfinite(r["tau2"]) else np.nan
    row["tau2_outside_qprofile"] = bool(np.isfinite(r["tau2_lo"]) and not r["tau2_lo"] - 1e-9 <= r["tau2"]
                                        <= r["tau2_hi"] + 1e-9)
    if auc_scale:
        row |= {f"auc_{k}": float(expit(r[k])) if np.isfinite(r[k]) else np.nan
                for k in ("mu", "ci_lo", "ci_hi", "pi_lo", "pi_hi")}

    # 유효 표본: 고정효과·무작위효과 가중치의 최대 비중과 Kish 유효 사상 수
    for name in ("fe", "re"):
        w = np.asarray(r[f"weights_{name}"], float)
        row[f"{name}_max_share"] = float(w.max())
        row[f"{name}_max_event"] = events[int(w.argmax())]
        row[f"k_eff_{name}"] = float(w.sum() ** 2 / np.sum(w ** 2))

    # 비교용 요약: 사상 동일가중 평균, 단위 수 가중 평균, 중앙값 (원래 척도)
    value = sub["auc"].to_numpy(float) if auc_scale else (sub["auc_m"] - sub["auc_b"]).to_numpy(float)
    units = sub["n_units"].to_numpy(float)
    row |= {"mean_equal": float(value.mean()), "mean_unit_weighted": float(np.average(value, weights=units)),
            "median": float(np.median(value)), "events": ";".join(events),
            "n_units_total": int(units.sum()), "n_pos_cells_total": int(np.nansum(sub["n_pos_cells"])),
            "n_clusters_total": int(np.nansum(sub["n_clusters"])), "flag": "k=2: tau2 불안정, 예측구간 없음"
            if r["k"] == 2 else ("k=1: 통합 불가" if r["k"] == 1 else "")}
    return row


def _subsets(frame: pd.DataFrame, variant: str):
    """집합·단위·층별 포함 사상 묶음을 차례로 내준다 (S2 는 격자형 단위의 덩어리 ≥ 5 만)."""
    # 역할로 집합을 고르고, S2 이면 덩어리 수로 한 번 더 거른다
    for set_name, roles in SETS.items():
        part = frame[frame["role"].isin(roles)]
        if variant == "S2_min5clusters":
            part = part[part["unit"].isin(GRID_UNITS) & (part["n_clusters"] >= MIN_CLUSTERS)]
        for (unit, stratum), sub in part.groupby(["unit", "stratum"], sort=False):
            yield set_name, unit, stratum, sub


def pooled_table(effect_rows: pd.DataFrame) -> pd.DataFrame:
    """점수 × 단위 × 층 × 집합 × 변형(주·S1·S2)의 통합 표."""
    # 포함된 사상만으로 변형마다 통합한다
    included = effect_rows[effect_rows["included"]]
    rows = []
    for variant, (method, ci) in SCORE_VARIANTS.items():
        for score, frame in included.groupby("score", sort=False):
            for set_name, unit, stratum, sub in _subsets(frame, variant):
                rows.append({"score": score, "unit": unit, "stratum": stratum, "set": set_name, "variant": variant}
                            | pool(sub, method=method, ci=ci))
    return pd.DataFrame(rows)


def diff_frames(effect_rows: pd.DataFrame, rho: float) -> pd.DataFrame:
    """비교 쌍 전부의 사상별 logit 차이 표 (ρ 고정)."""
    return pd.concat([paired(effect_rows, m, b, rho=rho) for m, b in PAIRS], ignore_index=True)


def pooled_diff_table(effect_rows: pd.DataFrame) -> pd.DataFrame:
    """모델 − 기준선 × 단위 × 층 × 집합 × 변형(주·S1·S2·S3)의 통합 표 (logit 척도)."""
    # 변형마다 ρ 를 정해 짝 차이를 만들고 통합한다
    rows = []
    for variant, (method, ci, rho) in DIFF_VARIANTS.items():
        diffs = diff_frames(effect_rows, rho)
        for (model, baseline), frame in diffs.groupby(["model", "baseline"], sort=False):
            for set_name, unit, stratum, sub in _subsets(frame, variant):
                rows.append({"model": model, "baseline": baseline, "unit": unit, "stratum": stratum, "set": set_name,
                             "variant": variant, "rho": rho} | pool(sub, method=method, ci=ci, auc_scale=False))
    return pd.DataFrame(rows)


def leave_one_out(diffs: pd.DataFrame, model: str, baseline: str, unit: str, set_name: str,
                  stratum: str = "ALL") -> pd.DataFrame:
    """한 짝 비교에서 사상을 하나씩 뺀 주 방법 통합 (S5)."""
    # 해당 집합의 사상 행을 고른 뒤 하나씩 빼고 통합한다
    sub = diffs[(diffs["model"] == model) & (diffs["baseline"] == baseline) & (diffs["unit"] == unit)
                & (diffs["stratum"] == stratum) & diffs["role"].isin(SETS[set_name])]
    rows = []
    for event in sorted(sub["test_event"].astype(str)):
        rest = sub[sub["test_event"].astype(str) != event]
        if len(rest):
            rows.append({"model": model, "baseline": baseline, "unit": unit, "stratum": stratum, "set": set_name,
                         "omitted": event} | pool(rest, auc_scale=False))
    return pd.DataFrame(rows)


def transport(effect_rows: pd.DataFrame, pooled: pd.DataFrame, stratum: str = "ALL") -> pd.DataFrame:
    """홀드아웃 사상별 AUC 가 개발 통합 95% 예측구간 안에 드는지 (R5)."""
    # 개발 주 통합의 예측구간을 점수·단위별로 붙이고 홀드아웃 포함 행과 비교한다
    dev = pooled[(pooled["set"] == "development") & (pooled["variant"] == "main") & (pooled["stratum"] == stratum)]
    dev = dev.set_index(["score", "unit"])[["k", "auc_pi_lo", "auc_pi_hi"]]
    hold = effect_rows[(effect_rows["role"] == "holdout") & effect_rows["included"]
                       & (effect_rows["stratum"] == stratum) & effect_rows["unit"].isin(("cell_gate", "object"))]
    out = hold.join(dev, on=["score", "unit"], how="inner")
    side = np.select([~np.isfinite(out["auc_pi_lo"]), out["auc"] < out["auc_pi_lo"], out["auc"] > out["auc_pi_hi"]],
                     ["no_pi", "below", "above"], default="inside")
    out = out.assign(inside_dev_pi=side == "inside", side=side)
    return out[["score", "unit", "stratum", "test_event", "auc", "k", "auc_pi_lo", "auc_pi_hi", "inside_dev_pi",
                "side"]].rename(columns={"k": "k_dev"}).reset_index(drop=True)
