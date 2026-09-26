"""사전 고정 발표창의 창원 호우·태풍 특보 특징을 계산한다."""

import numpy as np
import pandas as pd

from src.forecast.time_utils import parse_time


def storm_warning_features(storms, warnings, coverage=None):
    """사상 전 하루 동안 발표된 주의보·경보와 최초 발표 선행을 구한다."""
    # 수집 근거가 없거나 같은 월의 기록 중 하나라도 실패하면 무특보로 간주하지 않는다.
    if coverage is None:
        raise ValueError("특보 특징 계산에는 coverage가 필요합니다 (coverage.csv).")
    month_ok = coverage.status.eq("ok").fillna(False).groupby(coverage.month).all().to_dict()

    # 해제 및 다른 구역 특보는 발표 이력에 있어도 특징에서 제외한다.
    warnings = warnings.copy()
    warnings["TM_FC"] = warnings.TM_FC.map(parse_time)
    for column in ("CMD", "LVL"):
        warnings[column] = pd.to_numeric(warnings[column], errors="coerce")
    valid = warnings[warnings.REG_ID.eq("L1080600") & warnings.WRN.isin(["R", "T"]) &
                     warnings.CMD.isin([1, 2, 5, 6])]
    rows = []
    for storm in storms.itertuples():
        t0 = parse_time(storm.t0)
        row = dict(storm_id=storm.storm_id, warn_advisory=np.nan, warn_warning=np.nan,
                   first_warn_lead_h=np.nan, warn_status="outside_period")
        rows.append(row)
        if t0 < pd.Timestamp("2005-07-01"):
            continue
        start = t0 - pd.Timedelta(hours=24)
        months = pd.period_range(start, t0, freq="M")
        if any(not month_ok.get(str(month), False) for month in months):
            row["warn_status"] = "coverage_missing"
            continue
        row["warn_status"] = "ok"
        selected = valid[valid.TM_FC.between(start, t0) & valid.LVL.ge(2)]
        row.update(warn_advisory=int(not selected.empty), warn_warning=int(selected.LVL.eq(3).any()))
        if not selected.empty:
            row["first_warn_lead_h"] = (t0 - selected.TM_FC.min()).total_seconds() / 3600
    return pd.DataFrame(rows, columns=["storm_id", "warn_advisory", "warn_warning", "first_warn_lead_h", "warn_status"])
