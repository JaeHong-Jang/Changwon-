"""강수 노출 변수 산출과 IDW 공간보간 (ANALYSIS_PLAN §2-2).

관측지점의 강수 통계를 만들고, 그것을 100m 격자로 옮기는 것까지가 이 모듈의 일이다.
보간 지수(power)는 LOOCV RMSE 로 고른다. 반경 밖 격자는 외삽하지 않고 최근접 값으로
채운 뒤 플래그를 남긴다.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

# 노출 변수 정의 (이름 → 설명). Layer 1 문서·data_dictionary 가 이 표를 쓴다.
EXPOSURE_VARIABLES: dict[str, str] = {
    "rain_annual_max_1h": "연최대 시간강수의 분석기간 평균 (mm/h)",
    "rain_hours_over_30mm": "시간강수 30mm 이상 발생시간 수의 연평균 (시간/년)",
    "rain_top5_3h": "상위 5개 비중복 3시간 누적강수의 평균 (mm)",
    "rain_top5_24h": "상위 5개 비중복 24시간 누적강수의 평균 (mm)",
}
HEAVY_HOUR_MM = 30.0


def _top_k_non_overlapping(values: pd.Series, window_hours: int, k: int) -> float:
    """겹치지 않는 상위 k개 누적값의 평균. 같은 호우가 k번 뽑히는 것을 막는다."""
    ordered = values.dropna().sort_values(ascending=False)
    picked: list[float] = []
    times: list[pd.Timestamp] = []
    gap = pd.Timedelta(hours=window_hours)
    for t, v in ordered.items():
        if all(abs(t - p) >= gap for p in times):
            picked.append(float(v))
            times.append(t)
            if len(picked) == k:
                break
    return float(np.mean(picked)) if picked else float("nan")


def station_exposure(
    rain: pd.DataFrame,
    lo: pd.Timestamp,
    hi: pd.Timestamp,
    *,
    station_ids: Sequence[int] | None = None,
    top_k: int = 5,
) -> pd.DataFrame:
    """지점별 강수 노출 변수 4개. 입력은 canonical `rainfall_hourly` (quality_flag 포함).

    결측 시간은 0mm 로 채우지 않는다. 관측이 없는 것과 비가 오지 않은 것은 다르다.
    3·24시간 누적은 창이 온전히 관측된 구간에서만 계산한다.
    """
    df = rain[rain["quality_flag"] == "ok"]
    df = df[(df["obs_date"] >= lo) & (df["obs_date"] <= hi)]
    if station_ids is not None:
        df = df[df["station_id"].isin(list(station_ids))]
    if df.empty:
        raise ValueError("분석기간 안에 사용할 수 있는 강수 관측이 없다")

    df = df.assign(year=df["observed_at"].dt.year)
    annual_max = df.groupby(["station_id", "year"])["rainfall_mm"].max()
    heavy = df.assign(heavy=df["rainfall_mm"] >= HEAVY_HOUR_MM).groupby(["station_id", "year"])["heavy"].sum()

    rows = []
    for sid, g in df.groupby("station_id"):
        series = g.set_index("observed_at")["rainfall_mm"].sort_index()
        series = series[~series.index.duplicated()].asfreq("h")
        rows.append({
            "station_id": int(sid),
            "rain_top5_3h": _top_k_non_overlapping(series.rolling(3, min_periods=3).sum(), 3, top_k),
            "rain_top5_24h": _top_k_non_overlapping(series.rolling(24, min_periods=24).sum(), 24, top_k),
            "n_hours": int(series.notna().sum()),
            "n_years": int(g["year"].nunique()),
        })
    out = pd.DataFrame(rows).set_index("station_id")
    out["rain_annual_max_1h"] = annual_max.groupby("station_id").mean()
    out["rain_hours_over_30mm"] = heavy.groupby("station_id").mean()
    return out.reset_index()[["station_id", *EXPOSURE_VARIABLES, "n_hours", "n_years"]]


def idw(
    src_xy: np.ndarray,
    values: np.ndarray,
    dst_xy: np.ndarray,
    *,
    power: float = 2.0,
    k: int = 12,
    max_dist: float = 10_000.0,
) -> tuple[np.ndarray, np.ndarray]:
    """역거리가중 보간. (값, 반경 밖이라 최근접으로 대체했는지 여부) 를 돌려준다.

    반경 `max_dist` 안의 최근접 `k` 지점만 쓴다. 반경 안에 아무 지점도 없으면 외삽 대신
    최근접 지점 값을 그대로 쓰고 플래그를 세운다 (ANALYSIS_PLAN §2-2 '외삽 금지').
    """
    src_xy = np.asarray(src_xy, dtype=float)
    values = np.asarray(values, dtype=float)
    dst_xy = np.asarray(dst_xy, dtype=float)
    kk = int(min(k, len(src_xy)))
    dist, idx = cKDTree(src_xy).query(dst_xy, k=kk)
    if kk == 1:
        dist, idx = dist[:, None], idx[:, None]

    within = dist <= max_dist
    with np.errstate(divide="ignore"):
        weight = np.where(within, 1.0 / np.maximum(dist, 1e-6) ** power, 0.0)
    wsum = weight.sum(axis=1)
    out = np.full(len(dst_xy), np.nan)
    ok = wsum > 0
    out[ok] = (weight[ok] * values[idx[ok]]).sum(axis=1) / wsum[ok]
    fallback = ~ok
    out[fallback] = values[idx[fallback, 0]]
    return out, fallback


def loocv_rmse(xy: np.ndarray, values: np.ndarray, *, power: float, k: int, max_dist: float) -> float:
    """지점 하나씩 빼고 예측한 오차의 RMSE."""
    xy = np.asarray(xy, dtype=float)
    values = np.asarray(values, dtype=float)
    errors = []
    for j in range(len(values)):
        keep = np.ones(len(values), dtype=bool)
        keep[j] = False
        pred, _ = idw(xy[keep], values[keep], xy[[j]], power=power, k=k, max_dist=max_dist)
        errors.append(pred[0] - values[j])
    return float(np.sqrt(np.mean(np.square(errors))))


def choose_power(
    xy: np.ndarray,
    values: np.ndarray,
    *,
    powers: Iterable[float] = (1, 2, 3),
    k: int = 12,
    max_dist: float = 10_000.0,
) -> tuple[float, dict[str, float]]:
    """LOOCV RMSE 가 가장 작은 power 를 고른다. 동점이면 작은 power (더 매끄러운 쪽)."""
    scores = {float(p): loocv_rmse(xy, values, power=float(p), k=k, max_dist=max_dist) for p in powers}
    best = min(sorted(scores), key=lambda p: scores[p])
    return best, {str(p): round(v, 4) for p, v in scores.items()}


def interpolate_to_grid(
    stations: pd.DataFrame,
    exposure: pd.DataFrame,
    dst_xy: np.ndarray,
    *,
    variables: Iterable[str],
    powers: Iterable[float],
    k: int,
    max_dist: float,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """노출 변수별로 power 를 고르고 격자에 보간한다.

    `stations` 는 station_code·x·y 를 가진 표, `exposure` 는 station_id 별 변수 표다.
    """
    merged = stations.merge(exposure, left_on="station_code", right_on="station_id", how="inner")
    src_xy = merged[["x", "y"]].to_numpy(dtype=float)
    grids: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {"n_source_stations": int(len(merged)), "by_variable": {}}
    for name in variables:
        values = merged[name].to_numpy(dtype=float)
        usable = np.isfinite(values)
        if usable.sum() < 3:
            raise ValueError(f"{name}: 보간에 쓸 수 있는 지점이 {int(usable.sum())}개뿐이다")
        power, scores = choose_power(src_xy[usable], values[usable], powers=powers, k=k, max_dist=max_dist)
        grid, fallback = idw(src_xy[usable], values[usable], dst_xy, power=power, k=k, max_dist=max_dist)
        grids[name] = grid
        meta["by_variable"][name] = {
            "n_stations": int(usable.sum()),
            "power": power,
            "loocv_rmse": scores,
            "n_nearest_fallback": int(fallback.sum()),
            "station_mean": round(float(np.nanmean(values[usable])), 3),
            "grid_mean": round(float(np.nanmean(grid)), 3),
        }
    meta["min_stations_used"] = min(v["n_stations"] for v in meta["by_variable"].values())
    return grids, meta
