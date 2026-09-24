"""침수흔적의 일자·원인·사상·연도를 공통 필드로 정규화한다."""

from __future__ import annotations

from typing import Any

# 사상 일자·원인으로 쓸 컬럼 이름 후보.
DATE_COLUMN_CANDIDATES = (
    "F_SAT_YMD", "FLDN_BGNG_YMD", "침수일자", "발생일자", "사상일자", "피해일자", "일자",
    "OCCUR_DE", "FLUD_DE", "date",
)
CAUSE_COLUMN_CANDIDATES = (
    "F_RSN_DTL", "FLDN_CS_DTL_NM", "침수원인", "원인", "재해원인", "F_RSN_CD", "CAUSE", "cause",
)
EVENT_COLUMN_CANDIDATES = ("F_DISA_NM", "FLDN_DST_NM", "사상명", "재해명", "EVENT")
YEAR_COLUMN_CANDIDATES = ("FLDN_YR", "F_YR", "INV_YR", "연도")
# 내수 침수 원인 토큰.
INLAND_CAUSE_TOKENS = ("내수", "배수", "우수", "관거", "맨홀", "저지대")


def _coalesce(gdf, candidates: tuple[str, ...]):
    """후보 컬럼들을 행 단위로 합친다. 앞선 후보의 값이 비면 다음 후보로 채운다."""
    # 결측값과 날짜를 처리할 도구를 준비한다.
    import pandas as pd

    # 후보 순서대로 빈 값을 채우고 사용한 컬럼을 반환한다.
    present = [c for c in candidates if c in gdf.columns]
    if not present:
        return None, None
    merged = gdf[present[0]].replace("", pd.NA)
    for column in present[1:]:
        merged = merged.fillna(gdf[column].replace("", pd.NA))
    return merged, present


def _normalize_years(raw_year: Any) -> Any:
    """네 자리 연도의 공백과 소수부 0을 정리하고 빈 값은 결측으로 맞춘다."""
    # 결측값과 날짜를 처리할 도구를 준비한다.
    import pandas as pd

    # 공백과 소수부 0을 제거하고 빈 문자열을 결측값으로 바꾼다.
    return (raw_year.astype("string").str.strip()
            .str.replace(r"^(\d{4})\.0+$", r"\1", regex=True).replace("", pd.NA))


def _parse_dates(raw_date: Any, f_year: Any) -> tuple[Any, int]:
    """일자를 파싱하고 F_YR과 일치하는 세 자리 연도만 복원한다."""
    # 결측값과 날짜를 처리할 도구를 준비한다.
    import pandas as pd

    # F_YR로 확인된 연도 오타만 복원하고 두 날짜 형식을 파싱한다.
    text = raw_date.astype("string").str.strip()
    year = _normalize_years(f_year)
    short = text.str.fullmatch(r"\d{3}-\d{2}-\d{2}", na=False)
    confirmed = (short & year.str.fullmatch(r"\d{4}", na=False)
                 & text.str[:3].eq(year.str[1:]).fillna(False))
    text = text.mask(confirmed, year.str[0] + text)
    compact = pd.to_datetime(text.where(text.str.fullmatch(r"\d{8}", na=False)),
                             format="%Y%m%d", errors="coerce")
    dashed = pd.to_datetime(text.where(text.str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False)),
                            format="%Y-%m-%d", errors="coerce")
    parsed = compact.fillna(dashed)
    return parsed, int((confirmed & parsed.notna()).sum())


def _storm_ids(gdf: Any) -> Any:
    """역할별로 인접 발생일 간격이 3일 이내인 호우를 최초 날짜로 묶는다."""
    # 결측값과 날짜를 처리할 도구를 준비한다.
    import pandas as pd

    # 일자가 없는 행은 연도로 표시하고 역할별 인접 일자를 호우로 묶는다.
    result = "Y" + gdf["event_year"].astype("string")
    for _, group in gdf.groupby("role", dropna=False):
        dates = sorted(group["event_date"].dropna().unique())
        mapping, first, previous = {}, None, None
        for date in dates:
            if previous is None or date - previous > pd.Timedelta(days=3):
                first = date
            mapping[date] = pd.Timestamp(first).strftime("%Y-%m-%d")
            previous = date
        dated = group.index[group["event_date"].notna()]
        result.loc[dated] = group.loc[dated, "event_date"].map(mapping)
    return result


def _derive_event_fields(gdf):
    """자료원마다 다른 컬럼명에서 일자·원인·사상·연도를 뽑아 공통 이름으로 맞춘다."""
    # 결측값과 날짜를 처리할 도구를 준비한다.
    import pandas as pd

    # 자료원별 후보 컬럼에서 공통 필드의 원본 값을 모은다.
    raw_date, date_cols = _coalesce(gdf, DATE_COLUMN_CANDIDATES)
    raw_cause, cause_cols = _coalesce(gdf, CAUSE_COLUMN_CANDIDATES)
    raw_event, event_cols = _coalesce(gdf, EVENT_COLUMN_CANDIDATES)
    raw_year, year_cols = _coalesce(gdf, YEAR_COLUMN_CANDIDATES)

    # 발생일·종료일을 복원하고 원인·사상·연도·호우 필드를 만든다.
    date_repairs, end_date_repairs = 0, 0
    f_year = gdf.get("F_YR", pd.Series(pd.NA, index=gdf.index))
    if raw_date is None:
        gdf["event_date"] = pd.NaT
    else:
        gdf["event_date"], date_repairs = _parse_dates(raw_date, f_year)
    gdf["event_end_date"] = pd.NaT
    if "F_END_YMD" in gdf:
        gdf["event_end_date"], end_date_repairs = _parse_dates(gdf["F_END_YMD"], f_year)
    gdf["cause"] = raw_cause.astype("string") if raw_cause is not None else None
    gdf["event_name"] = raw_event.astype("string") if raw_event is not None else None
    # 연도 컬럼이 비는 행은 일자에서 채운다.
    from_date = gdf["event_date"].dt.year.astype("Int64").astype("string")
    gdf["event_year"] = (
        _normalize_years(raw_year).fillna(from_date)
        if raw_year is not None else from_date
    )
    gdf["is_inland"] = (
        gdf["cause"].str.contains("|".join(INLAND_CAUSE_TOKENS), na=False)
        if raw_cause is not None else pd.NA
    )
    gdf["storm_id"] = _storm_ids(gdf)
    gdf["land_use"] = gdf.get("A_CHA_NM", pd.Series(pd.NA, index=gdf.index)).astype("string")
    return gdf, {"date_columns": date_cols, "cause_columns": cause_cols,
                 "event_columns": event_cols, "year_columns": year_cols,
                 "date_typo_repairs": date_repairs + end_date_repairs,
                 "start_date_typo_repairs": date_repairs,
                 "end_date_typo_repairs": end_date_repairs}
