"""M2 사전 판정·보고 규칙 R2~R5 (docs/q1/M2_protocol.md §6)."""

from __future__ import annotations

import pandas as pd

GATE_AUC = 0.70
PRIMARY_PAIR = ("rf_F1_wf", "slope_neg")


def _pick(table: pd.DataFrame, **match) -> pd.DataFrame:
    """열 값이 모두 같은 행을 고른다."""
    mask = pd.Series(True, index=table.index)
    for column, value in match.items():
        mask &= table[column] == value
    return table[mask]


def gate_class(row: pd.Series | None) -> dict:
    """R2: 통합 격자 AUC 를 게이트 0.70 에 대해 사상 수준 통과·점추정만 통과·미달·통합 불가로 나눈다."""
    # 사상 수에 따라 통합 불가를 먼저 가르고, 구간 하한·점추정·예측구간 하한 순으로 본다
    if row is None:
        return {"k": 0, "class": "사상 없음"}
    out = {"k": int(row["k"]), "auc_mu": row["auc_mu"], "auc_ci": [row["auc_ci_lo"], row["auc_ci_hi"]],
           "auc_pi": [row["auc_pi_lo"], row["auc_pi_hi"]], "i2": row["i2"], "tau2": row["tau2"]}
    if row["k"] == 1:
        return out | {"class": "통합 불가", "prediction": "예측구간 없음"}
    cls = ("사상 수준 통과" if row["auc_ci_lo"] >= GATE_AUC else
           "점추정만 통과" if row["auc_mu"] >= GATE_AUC else "미달")
    if row["k"] < 3:
        pred = "예측구간 없음"
    else:
        pred = "새 사상에서도 게이트 위로 예측됨" if row["auc_pi_lo"] >= GATE_AUC else "새 사상에서 게이트 아래 가능"
    return out | {"class": cls, "prediction": pred}


def diff_class(row: pd.Series | None) -> str:
    """R3: 통합 logit 차이 구간이 0 을 포함하는지로 구분 불가·RF 높음·경사 높음을 가른다."""
    if row is None or row["k"] < 2:
        return "통합 불가"
    if row["ci_lo"] > 0:
        return "사상 수준에서 모델이 높다"
    if row["ci_hi"] < 0:
        return "사상 수준에서 기준선이 높다"
    return "사상 수준에서 구분되지 않는다"


def _one(table: pd.DataFrame, **match) -> pd.Series | None:
    """조건에 맞는 행이 정확히 하나면 그 행, 없으면 None."""
    rows = _pick(table, **match)
    if len(rows) > 1:
        raise ValueError(f"행이 여러 개다: {match}")
    return rows.iloc[0] if len(rows) else None


def _diff_summary(row: pd.Series | None) -> dict:
    """짝 비교 통합 행의 핵심 수치와 분류."""
    if row is None:
        return {"k": 0, "class": "통합 불가"}
    return {"k": int(row["k"]), "events": row["events"], "mu_logit": row["mu"], "ci_logit": [row["ci_lo"], row["ci_hi"]],
            "pi_logit": [row["pi_lo"], row["pi_hi"]], "i2": row["i2"], "median_auc_diff": row["median"],
            "class": diff_class(row)}


def decide(pooled: pd.DataFrame, pooled_diff: pd.DataFrame, loo: pd.DataFrame, transport: pd.DataFrame) -> dict:
    """R2(게이트)·R3(C-b 재표현)·R4(객체 AUC 서술)·R5(이전 가능성)와 한 사상 빼기 안정성을 묶는다."""
    # R2: 점수 × 개발·홀드아웃, 격자 AUC·전 격자·주 방법
    main = _pick(pooled, variant="main", unit="cell_gate", stratum="ALL")
    r2 = {score: {s: gate_class(_one(main, score=score, set=s)) for s in ("development", "holdout")}
          for score in pooled["score"].unique()}

    # R3: RF − 경사 격자 AUC, 합산(E*) 주 판정과 개발·홀드아웃 참고값, 한 사상 빼기
    model, base = PRIMARY_PAIR
    dmain = _pick(pooled_diff, variant="main", model=model, baseline=base, stratum="ALL")
    r3 = {s: _diff_summary(_one(dmain, unit="cell_gate", set=s)) for s in ("combined", "development", "holdout")}
    loo3 = _pick(loo, unit="cell_gate", set="combined")
    r3_loo = {str(r["omitted"]): diff_class(r) for _, r in loo3.iterrows()}

    # R4: RF − 경사 객체 AUC, 개발·홀드아웃 각각의 구간 하한과 점추정 부호
    r4 = {s: _diff_summary(_one(dmain, unit="object", set=s)) for s in ("development", "holdout")}
    rows = [_one(dmain, unit="object", set=s) for s in ("development", "holdout")]
    if all(r is not None and r["k"] >= 2 and r["ci_lo"] > 0 for r in rows):
        r4_text = "객체 AUC 에서 RF 가 경사보다 높다"
    elif all(r is not None and r["mu"] > 0 for r in rows):
        r4_text = "방향은 RF 쪽이나 사상 수준에서 구분되지 않는다"
    else:
        r4_text = "쓰지 않는다 (표에만 둔다)"
    loo4 = {s: {str(r["omitted"]): diff_class(r) for _, r in _pick(loo, unit="object", set=s).iterrows()}
            for s in ("development", "holdout")}

    # R5: 홀드아웃 사상별 AUC 가 개발 예측구간 안에 든 수
    r5 = {f"{score}|{unit}": {"n_inside": int(g["inside_dev_pi"].sum()), "n": int(len(g)),
                              "sides": dict(zip(g["test_event"].astype(str), g["side"]))}
          for (score, unit), g in transport.groupby(["score", "unit"], sort=False)}
    return {"R2_gate": r2,
            "R3_cb": {"rule": "rf_F1_wf − slope_neg, 격자 AUC, 전 격자, combined(E*), ρ=0, REML+수정 HKSJ",
                      "primary": r3["combined"], "by_set": r3, "loo_combined": r3_loo,
                      "loo_changes_class": any(c != r3["combined"]["class"] for c in r3_loo.values())},
            "R4_object": {"rule": "rf_F1_wf − slope_neg, 객체 AUC, 개발·홀드아웃 각각 구간 하한 > 0", "by_set": r4,
                          "statement": r4_text, "loo": loo4},
            "R5_transport": r5}
