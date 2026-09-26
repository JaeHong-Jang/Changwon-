"""M4 판정: 설정별 V1(합동 홀드아웃)·V2(사상별 중앙값) 게이트, 뒤집힘·순위·주 판정 (docs/q1/M4_protocol.md §7)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.models.gates import GATE

SCORES = ("slope_neg", "relelev_neg", "twi", "impervious", "hand_neg", "hand_acc_neg",
          "L1", "z_sensitivity", "rf_F1_wf", "logit_F1_wf")
REFERENCE = ("f10", 100)
CONVENTIONAL = (("any", 100), ("center", 100), ("f50", 100))
POOLED = "HOLDOUT_ALL"
MATERIAL = 0.02
MIN_POS = 5
MIN_OBJECTS = 3
TARGET = "L1"


def config_class(rule: str, size: int) -> str:
    """참조 대비 설정 종류: 참조·규칙만·크기만·둘 다."""
    if (rule, size) == REFERENCE:
        return "reference"
    return "rule_only" if size == REFERENCE[1] else "size_only" if rule == REFERENCE[0] else "both"


def gate_margin(auc: float, capture: float) -> float:
    """게이트 여유 m = min(AUC − 0.70, 포착 − 0.50). 통과 ⇔ m ≥ 0."""
    return float(min(auc - GATE["auc_min"], capture - GATE["top20_capture_min"]))


def _wide(long: pd.DataFrame) -> pd.DataFrame:
    """사상·설정·점수마다 격자 AUC·포착·객체 AUC 를 열로 편다."""
    keep = long[long["metric"].isin(["cell_auc", "capture_0.2", "object_auc"])]
    index = ["test_event", "role", "rule", "size_m", "score", "metric"]
    return keep.set_index(index)["value"].unstack("metric").reset_index()


def verdict_table(long: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """V1·V2 의 설정 × 점수 표: AUC·포착·여유·통과·평가 사상."""
    # 사상 표본 크기를 붙이고 V1(합동 홀드아웃) 행을 만든다
    wide = _wide(long).merge(events[["test_event", "rule", "size_m", "n_pos_cells"]],
                             on=["test_event", "rule", "size_m"], how="left")
    rows = []
    for (rule, size), part in wide.groupby(["rule", "size_m"], sort=False):
        pooled = part[part["test_event"] == POOLED].set_index("score")
        for score in SCORES:
            if score in pooled.index:
                r = pooled.loc[score]
                ok = r["n_pos_cells"] >= MIN_POS and np.isfinite(r["cell_auc"]) and np.isfinite(r["capture_0.2"])
                rows.append({"verdict": "V1", "rule": rule, "size_m": size, "score": score, "auc": r["cell_auc"],
                             "capture": r["capture_0.2"], "evaluable": bool(ok), "n_events": 1, "events": POOLED})

        # V2: 10개 점수가 모두 유한하고 양성 칸이 5 이상인 사상 E* 에서 중앙값을 낸다
        per = part[part["test_event"] != POOLED]
        auc = per.pivot(index="test_event", columns="score", values="cell_auc").reindex(columns=list(SCORES))
        cap = per.pivot(index="test_event", columns="score", values="capture_0.2").reindex(columns=list(SCORES))
        n_pos = per.groupby("test_event")["n_pos_cells"].first().reindex(auc.index)
        star = auc.index[auc.notna().all(axis=1) & cap.notna().all(axis=1) & (n_pos >= MIN_POS)]
        for score in SCORES:
            rows.append({"verdict": "V2", "rule": rule, "size_m": size, "score": score,
                         "auc": float(auc.loc[star, score].median()) if len(star) else np.nan,
                         "capture": float(cap.loc[star, score].median()) if len(star) else np.nan,
                         "evaluable": bool(len(star)), "n_events": int(len(star)), "events": ",".join(sorted(star))})

    # 여유·통과와 참조 대비 뒤집힘·실질 뒤집힘을 붙인다
    table = pd.DataFrame(rows)
    table["config_class"] = [config_class(r, int(s)) for r, s in zip(table["rule"], table["size_m"])]
    table["margin"] = [gate_margin(a, c) if e else np.nan
                       for a, c, e in zip(table["auc"], table["capture"], table["evaluable"])]
    table["passes"] = table["margin"] >= 0
    ref = table[table["config_class"] == "reference"].set_index(["verdict", "score"])
    key = pd.MultiIndex.from_frame(table[["verdict", "score"]])
    table["ref_margin"] = ref["margin"].reindex(key).to_numpy()
    table["ref_passes"] = ref["passes"].reindex(key).to_numpy()
    both = table["evaluable"] & np.isfinite(table["ref_margin"])
    table["flip"] = both & (table["passes"] != table["ref_passes"])
    table["material_flip"] = table["flip"] & (table["margin"].abs() >= MATERIAL) & (table["ref_margin"].abs() >= MATERIAL)
    return table


def ranking(table: pd.DataFrame) -> pd.DataFrame:
    """설정마다 격자 AUC 순위의 참조 대비 Kendall τ_b 와 L1 순위."""
    from scipy.stats import kendalltau

    # 참조 설정의 점수 순서와 각 설정의 순서를 비교한다
    rows = []
    for (verdict, rule, size), part in table.groupby(["verdict", "rule", "size_m"], sort=False):
        ref = table[(table["verdict"] == verdict) & (table["config_class"] == "reference")].set_index("score")["auc"]
        cur = part.set_index("score")["auc"]
        both = ref.index[np.isfinite(ref) & np.isfinite(cur.reindex(ref.index))]
        tau = kendalltau(ref[both], cur[both]).statistic if len(both) >= 3 else np.nan
        rank = cur.rank(ascending=False, method="min")
        rows.append({"verdict": verdict, "rule": rule, "size_m": size, "kendall_tau_b": float(tau),
                     "n_scores": int(len(both)), "L1_rank": float(rank.get(TARGET, np.nan)),
                     "order": ">".join(cur.dropna().sort_values(ascending=False).index)})
    return pd.DataFrame(rows)


def pair_reversals(table: pd.DataFrame, target: str = TARGET) -> pd.DataFrame:
    """target 과 다른 점수의 격자 AUC 차이가 참조와 반대 부호이고 둘 다 |차| ≥ 0.02 인 설정."""
    # 설정·비교 점수마다 참조 차이와 현재 차이를 나란히 둔다
    rows = []
    for (verdict, rule, size), part in table.groupby(["verdict", "rule", "size_m"], sort=False):
        ref = table[(table["verdict"] == verdict) & (table["config_class"] == "reference")].set_index("score")["auc"]
        cur = part.set_index("score")["auc"]
        for other in SCORES:
            if other == target:
                continue
            d_ref, d_cur = ref.get(target) - ref.get(other), cur.get(target) - cur.get(other)
            material = bool(np.isfinite(d_ref) and np.isfinite(d_cur) and np.sign(d_ref) != np.sign(d_cur)
                            and abs(d_ref) >= MATERIAL and abs(d_cur) >= MATERIAL)
            rows.append({"verdict": verdict, "rule": rule, "size_m": size, "config_class": config_class(rule, int(size)),
                         "other": other, "diff_ref": d_ref, "diff": d_cur, "material_reversal": material})
    return pd.DataFrame(rows)


def cb_recheck(table: pd.DataFrame) -> pd.DataFrame:
    """M1 주 판정(경사 중앙값 ≥ RF 중앙값 − 0.02 이면 C-b 폐기)을 설정마다 V2 중앙값으로 다시 적용한다."""
    # V2 의 경사·RF 중앙값으로 설정별 판정을 낸다
    v2 = table[table["verdict"] == "V2"].pivot_table(index=["rule", "size_m"], columns="score", values="auc")
    out = pd.DataFrame({"median_slope": v2["slope_neg"], "median_rf": v2["rf_F1_wf"]}).reset_index()
    out["within_margin"] = out["median_slope"] >= out["median_rf"] - MATERIAL
    out["verdict"] = np.where(out["median_slope"].isna() | out["median_rf"].isna(), "판정 불가",
                              np.where(out["within_margin"], "C-b 폐기", "C-b 가 자명 기준선 검사에서 탈락하지 않음"))
    return out


def median_table(long: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """설정·점수·역할별 사상 중앙값 (격자 지표는 양성 칸 ≥ 5, 객체 AUC 는 폴리곤 ≥ 3 인 사상만)."""
    # 합동 홀드아웃을 빼고 최소 표본을 적용한다
    rows = long[(long["test_event"] != POOLED) & long["metric"].isin(["cell_auc", "capture_0.2", "object_auc"])]
    rows = rows.merge(events[["test_event", "rule", "size_m", "n_pos_cells"]], on=["test_event", "rule", "size_m"])
    enough = np.where(rows["metric"] == "object_auc", rows["n_units"] >= MIN_OBJECTS, rows["n_pos_cells"] >= MIN_POS)
    rows = rows[enough & rows["value"].notna()]

    # 역할별과 합산으로 중앙값·사상 수를 센다
    parts = [rows.assign(role_group=rows["role"]), rows.assign(role_group="all")]
    return pd.concat(parts).groupby(["rule", "size_m", "score", "metric", "role_group"]).agg(
        median=("value", "median"), n_events=("value", "size")).reset_index()


def decide(table: pd.DataFrame) -> dict[str, Any]:
    """L1 실질 뒤집힘의 위치로 C-c 주 판정을 내리고 보조 요약을 묶는다."""
    # 참조에서 L1 의 V1·V2 가 평가 가능한지 먼저 본다
    l1 = table[table["score"] == TARGET]
    ref = l1[l1["config_class"] == "reference"]
    if not ref["evaluable"].all() or len(ref) != 2:
        return {"verdict": "판정 불가", "reason": "참조 설정에서 L1 의 V1 또는 V2 를 평가할 수 없다"}

    # 관행 설정 → 그 밖 설정 순으로 실질 뒤집힘을 찾는다
    conventional = l1[[(r, int(s)) in CONVENTIONAL for r, s in zip(l1["rule"], l1["size_m"])]]
    flipped = l1[l1["material_flip"]]
    listing = flipped[["verdict", "rule", "size_m", "config_class", "auc", "capture", "margin", "ref_margin",
                       "n_events", "events"]]
    if conventional["material_flip"].any():
        verdict = "C-c 지지: 해상도를 그대로 두고 관행 래스터화 규칙만 바꿔도 L1 게이트 판정이 뒤집힌다"
    elif len(flipped):
        verdict = "C-c 부분 지지: 비관행 규칙 또는 격자 크기를 바꿔야 L1 게이트 판정이 뒤집힌다"
    else:
        verdict = "C-c 폐기(라벨 규칙·격자 크기 축): L1 의 사전 게이트 판정은 32 설정에서 실질적으로 뒤집히지 않는다"

    # 모든 점수의 뒤집힘 수를 설정 종류별로 센다
    counts = table[table["config_class"] != "reference"].groupby(["verdict", "score", "config_class"]).agg(
        n_configs=("flip", "size"), n_evaluable=("evaluable", "sum"), n_flip=("flip", "sum"),
        n_material_flip=("material_flip", "sum")).reset_index()
    return {"rule": "L1 의 V1·V2 실질 뒤집힘(|여유| ≥ 0.02 양쪽)이 관행 설정 {any, center, f50}×100 m 에 있으면 지지, "
                    "다른 설정에만 있으면 부분 지지, 없으면 폐기",
            "verdict": verdict, "reference": ref[["verdict", "auc", "capture", "margin", "passes", "n_events", "events"]]
            .to_dict("records"), "L1_material_flips": listing.to_dict("records"),
            "L1_conventional": conventional[["verdict", "rule", "size_m", "auc", "capture", "margin", "flip",
                                             "material_flip"]].to_dict("records"),
            "not_evaluable_configs": table[~table["evaluable"]][["verdict", "rule", "size_m"]].drop_duplicates()
            .to_dict("records"), "flip_counts": counts.to_dict("records")}
