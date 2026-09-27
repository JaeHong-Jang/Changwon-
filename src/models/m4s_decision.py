"""M4S 판정: 주 예측 P2·P3·P3′ 와 보조 예측 S1~S6 을 시나리오 요약에 적용한다 (docs/q1/M4S_protocol.md §6)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

P2_TOL = 0.03
DIVERGENT_ZONE = 0.15
STRONG_ZONE = 0.20
NULL_ZONE = 0.06
S1_NEFF = 20
S2_ERASED = 0.2
S2_TOL = 0.02
S3_TOL = 0.05
S4_TOL = 0.10
S5_SHARE = 0.5
S6_RHO = 0.5
S6_DELTA = -0.1


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    """판정 근거 행을 JSON 목록으로."""
    return frame[columns].replace({np.nan: None}).to_dict("records")


def p2(summary: pd.DataFrame) -> dict[str, Any]:
    """β = 0 (A·C·D) 에서 f10·soft 차이 중앙값 |·| < 0.03 이거나 중앙값 구간이 0 을 포함."""
    # 대상 행을 고르고 두 조건 중 하나를 요구한다
    part = summary[summary["block"].isin(["A", "C1", "C2", "D"]) & (summary["beta"] == 0)
                   & summary["rule"].isin(["f10", "soft"])].copy()
    part["ok"] = (part["gap_median"].abs() < P2_TOL) | ((part["gap_median_lo"] <= 0) & (part["gap_median_hi"] >= 0))
    return {"pass": bool(part["ok"].all()) and len(part) > 0, "n": int(len(part)), "n_fail": int((~part["ok"]).sum()),
            "fails": _records(part[~part["ok"]], ["scenario_no", "block", "rule", "shape", "n_obj", "gap_median",
                                                  "gap_median_lo", "gap_median_hi"])}


def _zone_rows(summary: pd.DataFrame, rule: str) -> pd.DataFrame:
    """P3·P3′ 대상: 묶음 A (n = 200, σ ≤ 2.0) 와 D 의 해당 규칙 행."""
    # 공식이 맞는 범위의 A 행과 D 행을 고른다
    a = (summary["block"] == "A") & (summary["n_obj"] == 200) & (summary["shape"] <= 2.0)
    return summary[(a | (summary["block"] == "D")) & (summary["rule"] == rule)].copy()


def p3(summary: pd.DataFrame, rule: str = "soft", strong: float | None = None) -> dict[str, Any]:
    """|Δ*| ≥ 0.15 → 부호 일치(와 벌어짐), |Δ*| < 0.06 → 벌어짐 아님. strong 이 있으면 벌어짐 요구는 |Δ*| ≥ strong 에만."""
    # 구역별로 요구 조건을 확인한다
    part = _zone_rows(summary, rule)
    size = part["delta_star"].abs()
    sign_ok = np.sign(part["gap_median"]) == np.sign(part["beta"])
    need_div = size >= (DIVERGENT_ZONE if strong is None else strong)
    part["zone"] = np.where(size >= DIVERGENT_ZONE, "divergent", np.where(size < NULL_ZONE, "null", "between"))
    part["ok"] = np.where(part["zone"] == "divergent", sign_ok & (~need_div | (part["class"] == "벌어짐")),
                          np.where(part["zone"] == "null", part["class"] != "벌어짐", True))
    tested = part[part["zone"] != "between"]
    return {"pass": bool(tested["ok"].all()) and len(tested) > 0, "rule": rule, "n_divergent_zone": int((part["zone"] == "divergent").sum()),
            "n_null_zone": int((part["zone"] == "null").sum()), "n_fail": int((~tested["ok"]).sum()),
            "rows": _records(tested, ["scenario_no", "block", "shape", "beta", "mu0", "delta_star", "zone", "gap_median",
                                      "p10", "class", "ok"])}


def verdict(p2r: dict[str, Any], p3r: dict[str, Any], p3pr: dict[str, Any]) -> str:
    """P2·P3·P3′ 가 모두 맞으면 지지, 일부면 부분 지지, 모두 틀리면 폐기."""
    # 맞은 예측 수로 절차 §6.1 문구를 고른다
    hits = [p2r["pass"], p3r["pass"], p3pr["pass"]]
    if all(hits):
        return ("일반성 지지: 격자 AUC 와 객체 AUC 의 0.1 이상 차이는 크기 분산과 크기–탐지 결합이 함께 있을 때 생기며, "
                "그 방향과 크기가 §5.3 공식으로 예측된다. 창원 고유의 성질이 아니다.")
    if any(hits):
        names = [n for n, h in zip(("P2", "P3", "P3′"), hits) if not h]
        return f"부분 지지: 틀린 예측 {', '.join(names)}"
    return "폐기: 가상 자료에서 분해의 차이가 예측대로 나타나지 않는다."


def secondary(summary: pd.DataFrame, events: pd.DataFrame, anchors: pd.DataFrame | None) -> dict[str, Any]:
    """보조 예측 S1~S6 의 맞음/틀림과 근거."""
    from scipy.stats import spearmanr

    from src.synth.tilt import lognormal_top_share

    # S1: β = 0 에서 우연 차이(P10 ≥ 0.1)는 n_eff 중앙값 < 20 일 때만
    f10 = summary[summary["rule"] == "f10"]
    s1 = f10[f10["block"].isin(["A", "C1", "C2", "D"]) & (f10["beta"] == 0) & (f10["p10"] >= 0.1)]
    out = {"S1": {"pass": bool((s1["n_eff_median"] < S1_NEFF).all()),
                  "rows": _records(s1, ["scenario_no", "block", "shape", "n_obj", "p10", "n_eff_median"])}}

    # S2: 소실 항의 부호와 β = 0 의 소실 항
    s2 = f10[f10["block"].isin(["A", "C1"])].copy()
    nz = s2[(s2["beta"] != 0) & (s2["erased_frac_median"] >= S2_ERASED)]
    zero = s2[s2["beta"] == 0]
    sign_ok = np.sign(nz["term_erasure_median"]) == np.sign(nz["beta"])
    zero_ok = (zero["term_erasure_median"].abs() < S2_TOL) | ((zero["erasure_median_lo"] <= 0) & (zero["erasure_median_hi"] >= 0))
    out["S2"] = {"pass": bool(sign_ok.all() and zero_ok.all()), "n_nonzero": int(len(nz)), "n_sign_fail": int((~sign_ok).sum()),
                 "n_zero": int(len(zero)), "n_zero_fail": int((~zero_ok).sum()),
                 "fails": _records(pd.concat([nz[~sign_ok], zero[~zero_ok]]),
                                   ["scenario_no", "block", "shape", "median", "beta", "n_obj", "erased_frac_median", "term_erasure_median"])}

    # S3: rep_point 규칙의 차이 중앙값 (n = 200)
    rp = summary[(summary["rule"] == "rep_point") & (summary["n_obj"] == 200) & summary["block"].isin(["A", "C1", "C2", "D"])]
    out["S3"] = {"pass": bool((rp["gap_median"].abs() < S3_TOL).all()), "n": int(len(rp)),
                 "max_abs_gap_median": float(rp["gap_median"].abs().max()),
                 "fails": _records(rp[rp["gap_median"].abs() >= S3_TOL], ["scenario_no", "block", "shape", "beta", "gap_median"])}

    # S4: soft 상위 10% 몫과 로그정규 이론값
    s4 = summary[(summary["rule"] == "soft") & (summary["block"] == "A") & (summary["n_obj"] == 200) & (summary["shape"] <= 1.5)].copy()
    s4["theory"] = [lognormal_top_share(s) for s in s4["shape"]]
    s4["ok"] = (s4["top10_share_median"] - s4["theory"]).abs() <= S4_TOL
    out["S4"] = {"pass": bool(s4["ok"].all()), "rows": _records(s4, ["scenario_no", "shape", "beta", "top10_share_median", "theory", "ok"])}

    # S5: 사상 최대 몫 (E = 4)
    b4 = summary[(summary["block"] == "B") & (summary["n_events"] == 4) & (summary["rule"] == "f10")].copy()
    b4["ok"] = np.where(b4["counts"] == "skewed", b4["max_event_share_median"] >= S5_SHARE, b4["max_event_share_median"] < S5_SHARE)
    out["S5"] = {"pass": bool(b4["ok"].all()), "rows": _records(b4, ["scenario_no", "counts", "upsilon", "beta", "max_event_share_median", "ok"])}

    # S6: 창원 기준점의 Δ̂* 와 관측 f10 차이
    if anchors is None or anchors.empty:
        out["S6"] = {"pass": None, "reason": "기준점 없음 (--no-anchor)"}
    else:
        a = anchors[(anchors["rule"] == "f10") & np.isfinite(anchors["delta_hat"]) & np.isfinite(anchors["gap"])]
        rho = float(spearmanr(a["delta_hat"], a["gap"]).statistic) if len(a) >= 3 else np.nan
        l1 = a[(a["test_event"] == "HOLDOUT_ALL") & (a["score"] == "L1")]["delta_hat"]
        l1_value = float(l1.iloc[0]) if len(l1) else np.nan
        out["S6"] = {"pass": bool(rho >= S6_RHO and l1_value <= S6_DELTA), "spearman": rho, "n_anchors": int(len(a)),
                     "L1_HOLDOUT_ALL_delta_hat": l1_value}
    return out


def decide(summary: pd.DataFrame, events: pd.DataFrame, anchors: pd.DataFrame | None, identity: dict[str, Any]) -> dict[str, Any]:
    """P1 을 확인한 뒤 주 예측·판정·보조 예측을 묶는다."""
    # P1 이 틀리면 판정하지 않는다
    p1 = bool(identity["max_identity_abs_diff"] <= 1e-9 and identity["max_sklearn_abs_diff"] <= 1e-9
              and identity["max_cov_abs_diff"] <= 1e-9)
    if not p1:
        return {"P1": identity | {"pass": False}, "verdict": "판정 안 함: P1 항등식 실패 (구현 오류)"}

    # 주 예측과 판정, 보조 예측
    p2r, p3r, p3pr = p2(summary), p3(summary, "soft"), p3(summary, "f10", strong=STRONG_ZONE)
    return {"P1": identity | {"pass": True}, "P2": p2r, "P3": p3r, "P3_prime": p3pr,
            "verdict": verdict(p2r, p3r, p3pr), "secondary": secondary(summary, events, anchors)}
