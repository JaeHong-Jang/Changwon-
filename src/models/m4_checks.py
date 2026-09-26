"""M4 정합 확인: 참조 설정 결과가 M1 run 과 공식 홀드아웃 게이트를 재현하는지 (docs/q1/M4_protocol.md §8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

M1_RUN = "artifacts/q1/M1/m1_20260926T160821Z_a181f6c"
OFFICIAL_HOLDOUT = "artifacts/evaluation/holdout_2022_2024/holdout_20260924T100939Z_ae9c122-dirty_cf388a23"


def against_m1(long: pd.DataFrame, root: Path) -> dict[str, Any]:
    """참조 설정(f10·100 m)의 사상별 격자·객체 AUC 를 M1 metrics_long 과 비교한다."""
    # M1 의 전 격자 층 격자 AUC·객체 AUC 를 M4 이름으로 맞춘다
    path = root / M1_RUN / "metrics_long.csv"
    if not path.exists():
        return {"available": False}
    m1 = pd.read_csv(path, encoding="utf-8-sig", dtype={"test_event": str})
    m1 = m1[(m1["stratum"] == "ALL") & (m1["storm"] == "ALL") & (m1["metric"] == "observed-label_auc")
            & m1["unit"].isin(["cell_gate", "object"])]
    m1 = m1.assign(metric=m1["unit"].map({"cell_gate": "cell_auc", "object": "object_auc"}))

    # 참조 설정 행과 사상·점수·지표로 맞붙여 최대 절대차를 잰다
    ref = long[(long["rule"] == "f10") & (long["size_m"] == 100) & long["metric"].isin(["cell_auc", "object_auc"])]
    merged = ref.merge(m1[["test_event", "score", "metric", "value"]], on=["test_event", "score", "metric"],
                       suffixes=("", "_m1")).dropna(subset=["value", "value_m1"])
    diff = (merged["value"] - merged["value_m1"]).abs()
    return {"available": True, "m1_run": M1_RUN, "n_compared": int(len(merged)),
            "max_abs_diff": float(diff.max()) if len(diff) else np.nan,
            "by_metric": merged.assign(d=diff).groupby("metric")["d"].max().to_dict()}


def against_official(long: pd.DataFrame, root: Path) -> dict[str, Any]:
    """합동 홀드아웃·참조 설정의 L1 격자 AUC·포착을 공식 게이트(0.4357/0.0734)와 비교한다."""
    # 공식 run 요약의 L1 게이트 값을 읽는다
    path = root / OFFICIAL_HOLDOUT / "summary.json"
    ref = long[(long["test_event"] == "HOLDOUT_ALL") & (long["rule"] == "f10") & (long["size_m"] == 100)
               & (long["score"] == "L1")].set_index("metric")["value"]
    if not path.exists() or ref.empty:
        return {"available": False}
    gate = json.loads(path.read_text(encoding="utf-8"))["gates"]["L1"]

    # 공식 값은 소수 넷째 자리로 반올림돼 있어 5e-5 안이면 같다고 본다
    auc, cap = float(ref["cell_auc"]), float(ref["capture_0.2"])
    return {"available": True, "official_run": OFFICIAL_HOLDOUT, "official_auc": gate["auc_cell"],
            "official_capture": gate["top20_capture"], "m4_auc": auc, "m4_capture": cap,
            "same": bool(abs(auc - gate["auc_cell"]) <= 5e-5 and abs(cap - gate["top20_capture"]) <= 5e-5)}
