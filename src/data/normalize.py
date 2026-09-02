"""H02 강수·하천수위 정제 (docs/RESEARCH_HARNESS.md §6-1, §6-2).

원본은 수정하지 않는다. 오류 행은 quarantine 표에 원행 번호·사유를 남기고,
셀 단위 이상값은 0으로 치환하지 않고 quality_flag 로 표시한다.

**시각 두 가지를 구분한다.**
- `observed_at` — 누적이 끝난 시각. `24시강수량` 은 23~24시 누적이므로 다음날 00:00 이다.
- `obs_date`   — 그 관측이 속한 **원본 년월일**. 커버리지·cohort·연총량은 전부 이것으로 센다.

둘을 섞으면 24시 셀 때문에 하루가 밀린다. 그래서 canonical parquet 에 `obs_date` 를
직접 실어 보내 하류(EDA·피처)가 재계산하지 않게 한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

KEY_COLS = ["지역코드", "지역명", "년월일"]
RIVER_SENTINELS = {-47999, -8383, 9321, 9999}
RIVER_RANGE = (-100, 1000)
RAIN_RANGE = (0, 300)
MIN_DATE = pd.Timestamp("2000-01-01")

QUARANTINE_COLS = ["source_file", "source_row", "station_id", "date", "reason", "detail"]

# 행 단위로 통째로 격리되는 규칙과, 셀 단위로 플래그만 붙는 규칙을 구분한다.
ROW_LEVEL_RULES = {"H02-R01", "H02-R02", "H02-R03", "H02-R05"}
CELL_LEVEL_RULES = {"H02-R04", "H02-W01", "H02-W02"}


def read_wide(raw_path: Path) -> pd.DataFrame:
    df = pd.read_csv(raw_path, encoding="cp949")
    df.insert(0, "source_row", np.arange(len(df), dtype=int))
    return df


def value_columns(df: pd.DataFrame, value_prefix_regex: str) -> list[str]:
    cols = [c for c in df.columns if re.match(value_prefix_regex, str(c))]
    return sorted(cols, key=lambda c: int(re.match(r"(\d+)", c).group(1)))


def wide_to_long(df: pd.DataFrame, value_prefix_regex: str, value_name: str) -> pd.DataFrame:
    """`지역코드, 지역명, 년월일, 1시xxx..24시xxx` → station_id, station_name, date, hour, <value> (source_row 보존)."""
    vcols = value_columns(df, value_prefix_regex)
    if "source_row" not in df.columns:
        df = df.copy()
        df.insert(0, "source_row", np.arange(len(df), dtype=int))
    long = df.melt(
        id_vars=["source_row", *KEY_COLS], value_vars=vcols, var_name="hour_label", value_name=value_name
    )
    long["hour"] = long["hour_label"].str.extract(r"(\d+)").astype(int)
    long = long.rename(columns={"지역코드": "station_id", "지역명": "station_name", "년월일": "date"})
    long["station_id"] = long["station_id"].astype(int)
    return long.sort_values(["source_row", "hour"]).reset_index(drop=True)


def row_accounting(
    rows_in: int, canonical_rows: set[int], quarantine_rows: set[int]
) -> tuple[bool, dict[str, list[int]]]:
    """원본 행이 정확히 한 곳으로만 갔는지 증명한다.

    개수만 비교하는 `rows_in == kept + quarantined` 는 정제 코드가 서로소 부분집합을
    차례로 덜어내는 구조라 **항상 참**이어서 아무것도 증명하지 못한다. 여기서는 실제
    산출물의 `source_row` 집합을 본다:

    - 두 집합이 겹치면(overlap) 같은 행이 살아남으면서 격리도 됐다는 뜻이다.
    - 합집합이 `range(rows_in)` 에 못 미치면(missing) 행이 조용히 사라진 것이다.

    wide_to_long 이나 melt 가 행을 흘리면 여기서 잡힌다.
    """
    overlap = sorted(canonical_rows & quarantine_rows)
    missing = sorted(set(range(rows_in)) - canonical_rows - quarantine_rows)
    return (not overlap and not missing), {"overlap": overlap, "missing": missing}


def _q(rows: list[dict], source_file: str, df: pd.DataFrame, reason: str, detail: str) -> None:
    for r in df.itertuples(index=False):
        rows.append(
            {
                "source_file": source_file,
                "source_row": int(r.source_row),
                "station_id": r.지역코드,
                "date": str(r.년월일),
                "reason": reason,
                "detail": detail,
            }
        )


def _observed_at(long: pd.DataFrame) -> pd.Series:
    """누적이 끝난 시각. 24시 셀은 다음날 00:00 이 된다."""
    return pd.to_datetime(long["date"], format="%Y-%m-%d") + pd.to_timedelta(long["hour"], unit="h")


def _flag_cells(long: pd.DataFrame, value: str, lo: float, hi: float) -> pd.Series:
    v = pd.to_numeric(long[value], errors="coerce")
    return (v < lo) | (v > hi)


def _quarantine_counts(quarantine: pd.DataFrame) -> tuple[int, int]:
    """(행 단위 격리 건수, 셀 단위 격리 건수)."""
    if quarantine.empty:
        return 0, 0
    reasons = quarantine["reason"]
    return int(reasons.isin(ROW_LEVEL_RULES).sum()), int(reasons.isin(CELL_LEVEL_RULES).sum())


def observation_cohort(
    long: pd.DataFrame, valid: pd.Series, climatology: tuple[pd.Timestamp, pd.Timestamp], min_cov: float
) -> tuple[list[int], list[int]]:
    """분석기간 cohort. 커버리지는 **유효값이 하나라도 있는 날** 기준이다.

    하네스 §6-1-6 / §2: "완전연도 2015-01-01~2024-12-31 에서 일수 커버리지 90% 이상".
    long 은 wide 1행마다 24행을 반드시 만들기 때문에, 행 존재만 세면 24셀이 전부
    결측이거나 범위 밖인 날도 관측일로 잡힌다. 하천수위는 이미 유효값 기준으로 세고
    있어 강수만 달랐다 — 여기서 통일한다.

    반환: (기간 전체 커버리지 기준 cohort, 매 연도 개별 기준 cohort — 참고값)
    """
    lo, hi = climatology
    in_period = (long["obs_date"] >= lo) & (long["obs_date"] <= hi)
    sub = long[in_period & valid]
    total_days = (hi - lo).days + 1

    period = sub.groupby("station_id")["obs_date"].nunique() / total_days
    cohort = sorted(int(s) for s in period[period >= min_cov].index)

    strict: list[int] = []
    if not sub.empty:
        per_year = sub.groupby(["station_id", sub["obs_date"].dt.year])["obs_date"].nunique().unstack(fill_value=0)
        for sid, row in per_year.iterrows():
            if all(
                row.get(y, 0) / (366 if pd.Timestamp(year=y, month=12, day=31).dayofyear == 366 else 365) >= min_cov
                for y in range(lo.year, hi.year + 1)
            ):
                strict.append(int(sid))
    return cohort, sorted(strict)


# ---------------------------------------------------------------- 강수
def clean_rainfall(
    raw_path: Path,
    *,
    climatology: tuple[pd.Timestamp, pd.Timestamp],
    min_station_day_coverage: float = 0.90,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """하네스 §6-1 규칙 R01~R05 를 적용한다. 값을 임의로 0 으로 바꾸지 않는다."""
    src = raw_path.name
    wide = read_wide(raw_path)
    vcols = value_columns(wide, r"^\d+시강수량$")
    rows_in = len(wide)
    q: list[dict] = []

    # R01 완전중복: 1건 유지
    dup_all = wide.duplicated(subset=[*KEY_COLS, *vcols], keep="first")
    _q(q, src, wide[dup_all], "H02-R01", "완전중복 행, 첫 행만 유지")
    kept = wide[~dup_all]

    # R02 키 중복에서 값이 다른 행: 전부 quarantine (자동 선택 금지)
    key_dup = kept.duplicated(subset=["지역코드", "년월일"], keep=False)
    _q(q, src, kept[key_dup], "H02-R02", "지점-일자 충돌, 값 불일치 — 코드북 전 선택 금지")
    kept = kept[~key_dup]

    # R03 잘못된 날짜
    parsed = pd.to_datetime(kept["년월일"], format="%Y-%m-%d", errors="coerce")
    bad_date = parsed.isna()
    _q(q, src, kept[bad_date], "H02-R03", "달력에 없는 날짜")
    kept, parsed = kept[~bad_date], parsed[~bad_date]

    # R05 2000년 이전
    early = parsed < MIN_DATE
    _q(q, src, kept[early], "H02-R05", "2000-01-01 이전 고립 관측")
    kept = kept[~early]

    long = wide_to_long(kept, r"^\d+시강수량$", "rainfall_mm")
    long["rainfall_mm"] = pd.to_numeric(long["rainfall_mm"], errors="coerce")

    # R04 범위 밖 셀: 값 보존 + 플래그 + quarantine 표에 셀 단위 기록
    oor = _flag_cells(long, "rainfall_mm", *RAIN_RANGE)
    long["quality_flag"] = np.where(oor, "out_of_range", "ok")
    for r in long[oor].itertuples(index=False):
        q.append(
            {
                "source_file": src,
                "source_row": int(r.source_row),
                "station_id": r.station_id,
                "date": r.date,
                "reason": "H02-R04",
                "detail": f"{r.hour_label}={r.rainfall_mm} 범위 {RAIN_RANGE} 밖, 원값 보존·이벤트 분석 제외",
            }
        )

    long["observed_at"] = _observed_at(long)
    long["obs_date"] = pd.to_datetime(long["date"], format="%Y-%m-%d")

    # 유효값 = 숫자로 읽히고 물리범위 안. 범위 밖 셀은 코드북 확인 전까지 관측으로 치지 않는다.
    valid = long["rainfall_mm"].notna() & ~oor
    cohort, cohort_strict = observation_cohort(long, valid, climatology, min_station_day_coverage)

    canonical = pd.DataFrame(
        {
            "station_id": long["station_id"].astype(int),
            "station_name": long["station_name"],
            "obs_date": long["obs_date"],
            "observed_at": long["observed_at"],
            "hour_label": long["hour_label"],
            "rainfall_mm": long["rainfall_mm"].astype(float),
            "quality_flag": long["quality_flag"],
            "source_file": src,
            "source_row": long["source_row"].astype(int),
            "cleaning_rule": "H02-R01..R05",
        }
    )
    quarantine = pd.DataFrame(q, columns=QUARANTINE_COLS)
    rows_quarantined, cells_quarantined = _quarantine_counts(quarantine)
    partition_ok, partition_detail = row_accounting(
        rows_in,
        set(canonical["source_row"].unique().tolist()),
        set(quarantine[quarantine["reason"].isin(ROW_LEVEL_RULES)]["source_row"].tolist()),
    )

    metrics = {
        "rows_in": int(rows_in),
        "rows_out_wide": int(len(kept)),
        "rows_quarantined": rows_quarantined,
        "cells_quarantined": cells_quarantined,
        "row_partition_ok": bool(partition_ok),
        "row_partition_detail": {k: v[:20] for k, v in partition_detail.items()},
        "quarantine_by_rule": {k: int(v) for k, v in quarantine["reason"].value_counts().sort_index().items()},
        "cells_out_of_range": int(oor.sum()),
        "rows_out_long": int(len(canonical)),
        "climatology": [str(climatology[0].date()), str(climatology[1].date())],
        "stations_in_cohort": len(cohort),
        "cohort_station_ids": cohort,
        # 참고: 매 연도 개별로 90% 를 요구하는 더 엄격한 해석 (기본 cohort 아님)
        "stations_in_cohort_every_year": len(cohort_strict),
        "cohort_station_ids_every_year": cohort_strict,
        "duplicate_keys_after_clean": int(canonical.duplicated(["station_id", "observed_at"]).sum()),
    }
    return canonical, quarantine, metrics


# ---------------------------------------------------------------- 하천수위
def clean_river(
    raw_path: Path, *, climatology: tuple[pd.Timestamp, pd.Timestamp]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """하네스 §6-2 규칙 W01~W02 를 적용한다. 센티널은 원값을 raw_value 에 남기고 level_cm 에서 뺀다."""
    src = raw_path.name
    wide = read_wide(raw_path)
    vcols = value_columns(wide, r"^\d+시하천수위$")
    rows_in = len(wide)
    q: list[dict] = []

    dup_all = wide.duplicated(subset=[*KEY_COLS, *vcols], keep="first")
    _q(q, src, wide[dup_all], "H02-R01", "완전중복 행, 첫 행만 유지")
    kept = wide[~dup_all]
    key_dup = kept.duplicated(subset=["지역코드", "년월일"], keep=False)
    _q(q, src, kept[key_dup], "H02-R02", "지점-일자 충돌")
    kept = kept[~key_dup]
    parsed = pd.to_datetime(kept["년월일"], format="%Y-%m-%d", errors="coerce")
    bad_date = parsed.isna()
    _q(q, src, kept[bad_date], "H02-R03", "달력에 없는 날짜")
    kept = kept[~bad_date]

    long = wide_to_long(kept, r"^\d+시하천수위$", "raw_value")
    long["raw_value"] = pd.to_numeric(long["raw_value"], errors="coerce")
    sentinel = long["raw_value"].isin(RIVER_SENTINELS)
    oor = ~sentinel & _flag_cells(long, "raw_value", *RIVER_RANGE)
    flag = pd.Series(np.select([sentinel, oor], ["sentinel", "out_of_range"], default="ok"), index=long.index)
    level = long["raw_value"].where(flag == "ok")  # W01/W02: 값은 NaN, 원값은 raw_value 에 보존

    for r in long[sentinel | oor].itertuples(index=False):
        code = "H02-W01" if r.raw_value in RIVER_SENTINELS else "H02-W02"
        q.append(
            {
                "source_file": src,
                "source_row": int(r.source_row),
                "station_id": r.station_id,
                "date": r.date,
                "reason": code,
                "detail": f"{r.hour_label}={r.raw_value} ({'센티널' if code == 'H02-W01' else '범위 밖'}), 원값 보존",
            }
        )

    long["observed_at"] = _observed_at(long)
    long["obs_date"] = pd.to_datetime(long["date"], format="%Y-%m-%d")

    # 관측 전 기간에 걸쳐 값이 0 뿐인 지점 (코드북 확인 전까지 실제 수위로 쓰지 않는다)
    zero_only = long.groupby("station_id")["raw_value"].apply(
        lambda s: bool(s.notna().any() and (s.fillna(0) == 0).all())
    )
    note = long["station_id"].map(lambda s: "zero_only_pre_codebook" if zero_only.get(s, False) else "")

    lo, hi = climatology
    in_period = (long["obs_date"] >= lo) & (long["obs_date"] <= hi)
    valid = flag == "ok"
    total_days = (hi - lo).days + 1
    valid_days = long[in_period & valid].groupby("station_id")["obs_date"].nunique()
    coverage = {int(k): round(float(v) / total_days, 4) for k, v in valid_days.items()}

    canonical = pd.DataFrame(
        {
            "station_id": long["station_id"].astype(int),
            "station_name": long["station_name"],
            "obs_date": long["obs_date"],
            "observed_at": long["observed_at"],
            "hour_label": long["hour_label"],
            "level_cm": level.astype(float),
            "raw_value": long["raw_value"].astype(float),
            "quality_flag": flag.values,
            "station_note": note.values,
            "source_file": src,
            "source_row": long["source_row"].astype(int),
            "cleaning_rule": "H02-W01..W02",
        }
    )
    quarantine = pd.DataFrame(q, columns=QUARANTINE_COLS)
    rows_quarantined, cells_quarantined = _quarantine_counts(quarantine)
    partition_ok, partition_detail = row_accounting(
        rows_in,
        set(canonical["source_row"].unique().tolist()),
        set(quarantine[quarantine["reason"].isin(ROW_LEVEL_RULES)]["source_row"].tolist()),
    )

    sentinel_cells = int(sentinel.sum())
    out_of_range_cells = int(oor.sum())
    metrics = {
        "rows_in": int(rows_in),
        "rows_out_wide": int(len(kept)),
        "rows_quarantined": rows_quarantined,
        "cells_quarantined": cells_quarantined,
        "row_partition_ok": bool(partition_ok),
        "row_partition_detail": {k: v[:20] for k, v in partition_detail.items()},
        "sentinel_cells": sentinel_cells,
        "out_of_range_cells": out_of_range_cells,
        # 플래그가 붙은 셀마다 quarantine 기록이 정확히 하나씩 있는지. 기록이 누락되면 깨진다.
        "cell_accounting_ok": cells_quarantined == sentinel_cells + out_of_range_cells,
        "zero_only_stations": sorted(int(k) for k, v in zero_only.items() if v),
        "climatology": [str(lo.date()), str(hi.date())],
        # 분석기간에 유효값이 하나라도 남은 지점. 0 이면 이 자료로는 아무것도 못 한다.
        "usable_stations_in_period": int(len(valid_days)),
        "valid_day_coverage_by_station": coverage,
        "rows_out_long": int(len(canonical)),
    }
    return canonical, quarantine, metrics
