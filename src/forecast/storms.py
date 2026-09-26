"""관측 시간강수로 고정 규칙의 호우 목록과 특징을 계산한다."""

from __future__ import annotations

import pandas as pd


def _rain_frame(rain: pd.DataFrame) -> pd.DataFrame:
    """시간 키를 검증하고 품질 불량 강수를 결측으로 바꾼다."""
    # 필요한 열만 복사하고 KST 정시·고유 지점 시간 키를 확인한다.
    out = rain[["station_id", "observed_at", "rainfall_mm", "quality_flag"]].copy()
    out["observed_at"] = pd.to_datetime(out["observed_at"])
    times = out["observed_at"]
    if times.dt.tz is not None or times.isna().any() or not times.eq(times.dt.floor("h")).all():
        raise ValueError("observed_at은 결측 없는 KST naive 정시여야 한다")
    if out.station_id.isna().any() or out.duplicated(["station_id", "observed_at"]).any():
        raise ValueError("station_id와 observed_at은 결측 없는 고유 키여야 한다")
    out["rainfall_mm"] = pd.to_numeric(out.rainfall_mm, errors="coerce").where(out.quality_flag.eq("ok"))
    return out


def rolling_totals(rain: pd.DataFrame) -> pd.DataFrame:
    """지점별 완전 시간 색인에서 결측 없는 3·12시간 합을 구한다."""
    # 관측 구간 안 누락된 정시를 결측으로 보충해 오른쪽 닫힌 창을 계산한다.
    frames = []
    for station, group in _rain_frame(rain).groupby("station_id", sort=True):
        values = group.set_index("observed_at").rainfall_mm.sort_index()
        values = values.reindex(pd.date_range(values.index.min(), values.index.max(), freq="h"))
        frames.append(pd.DataFrame({"station_id": station, "observed_at": values.index,
                                    "r3": values.rolling(3, min_periods=3).sum().to_numpy(),
                                    "r12": values.rolling(12, min_periods=12).sum().to_numpy()}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["station_id", "observed_at", "r3", "r12"])


def heavy_hours(totals: pd.DataFrame, r3_mm: float = 60.0, r12_mm: float = 110.0) -> list:
    """한 지점이라도 호우 임계에 도달한 시각을 정렬해 반환한다."""
    # 두 누적 임계의 합집합에서 중복 시각을 제거한다.
    selected = totals.loc[totals.r3.ge(r3_mm) | totals.r12.ge(r12_mm), "observed_at"]
    return sorted(pd.to_datetime(selected).drop_duplicates().tolist())


def group_storms(hours, gap_h: int = 72) -> pd.DataFrame:
    """이웃 호우 시각의 간격이 지정 시간 이하인 연결성분을 만든다."""
    # 중복 시각을 제거하고 임계보다 큰 간격에서만 새 사상을 시작한다.
    times = pd.Series(pd.to_datetime(list(hours)), dtype="datetime64[ns]").drop_duplicates().sort_values()
    if times.empty:
        return pd.DataFrame({"t0": pd.Series(dtype="datetime64[ns]"),
                             "t1": pd.Series(dtype="datetime64[ns]"),
                             "n_heavy_hours": pd.Series(dtype="int64")})
    groups = times.diff().gt(pd.Timedelta(hours=gap_h)).cumsum()
    return times.groupby(groups).agg(t0="min", t1="max", n_heavy_hours="size").reset_index(drop=True)


def storm_features(storms: pd.DataFrame, totals: pd.DataFrame) -> pd.DataFrame:
    """사상 시작 전 12시간을 포함한 관측 최대량과 가동 지점 수를 붙인다."""
    # 사상별 닫힌 특징 창의 관측값을 모으고 시작시각에서 식별자를 만든다.
    out = storms.copy()
    features = []
    for row in out.itertuples(index=False):
        window = totals[totals.observed_at.between(row.t0 - pd.Timedelta(hours=12), row.t1)]
        features.append((window.r12.max(), window.r3.max(), window.loc[window.r12.notna(), "station_id"].nunique()))
    out[["r12max_obs", "r3max_obs", "n_stations_active"]] = pd.DataFrame(
        features, index=out.index, columns=["r12max_obs", "r3max_obs", "n_stations_active"])
    out["n_stations_active"] = out.n_stations_active.astype(int)
    out["storm_id"] = "S" + out.t0.dt.strftime("%Y%m%d%H")
    out["year"] = out.t0.dt.year
    return out


def fixed_stations(rain: pd.DataFrame, years=range(2006, 2026), min_coverage: float = 0.95) -> list:
    """매해 예정 시간 대비 유효 시간 비율을 만족한 고정 지점을 고른다."""
    # 누적 종료시각을 기준으로 각 해 첫날 01시부터 마지막 날 24시까지 센다.
    frame = _rain_frame(rain)
    stations = pd.Index(sorted(frame.station_id.unique()))
    valid = frame[frame.rainfall_mm.notna()]
    for year in years:
        start = pd.Timestamp(year=int(year), month=1, day=1)
        end = pd.Timestamp("2025-09-18") if year == 2025 else pd.Timestamp(year=int(year) + 1, month=1, day=1)
        expected = int((end - start) / pd.Timedelta(hours=1))
        counts = valid.loc[valid.observed_at.gt(start) & valid.observed_at.le(end)].groupby("station_id").size()
        stations = stations[(counts.reindex(stations, fill_value=0) / expected).ge(min_coverage)]
    return stations.tolist()


def build_catalog(rain: pd.DataFrame, stations=None) -> pd.DataFrame:
    """전체 또는 지정 지점으로 동일한 호우 규칙의 목록을 계산한다."""
    # 빈 지점 목록도 그대로 적용해 전체 지점으로 대체하지 않는다.
    selected = rain if stations is None else rain[rain.station_id.isin(stations)]
    totals = rolling_totals(selected)
    return storm_features(group_storms(heavy_hours(totals)), totals)
