"""관측지점·배수펌프장 좌표 표 → 분석 CRS 포인트 (H03).

좌표의 원천은 사람이 채우고 검수한 CSV(`data/external/`)와 창원시 배수펌프장 표준데이터다.
여기서는 표를 검사하고 포인트로 바꾸는 것만 한다. 지오코딩은 하지 않는다.
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from src.data.spatial import CANONICAL_CRS

STATION_COLUMNS = ["station_code", "station_name", "station_type", "lat", "lon", "source", "reviewed", "note"]
# 창원시를 넉넉히 감싸는 위경도 상자. 위도·경도가 뒤바뀐 행(lat=128.x)을 잡는 용도.
LAT_RANGE = (34.9, 35.6)
LON_RANGE = (128.3, 129.0)

OFFICIAL_PUMP_COLUMNS = {
    "시설명": "pump_name",
    "소재지도로명주소": "address_road",
    "소재지지번주소": "address_lot",
    "위도": "lat",
    "경도": "lon",
    "설치년도": "installed_year",
    "설치목적": "purpose",
    "데이터기준일자": "reference_date",
}


def to_points(df: pd.DataFrame, lat: str = "lat", lon: str = "lon") -> gpd.GeoDataFrame:
    """위경도(WGS84) 열을 분석 CRS(EPSG:5179) 포인트로 바꾼다."""
    g = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(df[lon], df[lat]), crs="EPSG:4326")
    return g.to_crs(CANONICAL_CRS)


def station_table(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """stations.csv 를 검사한다. 좌표가 빈 행은 남겨 두고(확보율 계산용) 문제는 metrics 로 돌려준다.

    reviewed=N 은 "실제 설치 위치가 비공개라 근사점을 썼다"는 뜻이므로 `is_proxy` 로 보존한다.
    """
    missing = [c for c in STATION_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"stations.csv 필수 열 누락: {missing}")
    df = df.copy()
    df["station_code"] = df["station_code"].astype(int)
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["reviewed"] = df["reviewed"].astype(str).str.strip().str.upper().eq("Y")
    df["is_proxy"] = ~df["reviewed"]
    df["note"] = df["note"].fillna("").astype(str)

    filled = df["lat"].notna() & df["lon"].notna()
    in_box = df["lat"].between(*LAT_RANGE) & df["lon"].between(*LON_RANGE)
    out_of_box = filled & ~in_box
    duplicates = df.loc[df["station_code"].duplicated(), "station_code"].tolist()
    metrics = {
        "n_stations": int(len(df)),
        "n_filled": int(filled.sum()),
        "coord_coverage": round(float(filled.mean()), 4) if len(df) else 0.0,
        "n_rain": int((df["station_type"] == "rain").sum()),
        "n_water_level": int((df["station_type"] == "water_level").sum()),
        "n_reviewed": int(df["reviewed"].sum()),
        "n_proxy": int(df["is_proxy"].sum()),
        "proxy_codes": df.loc[df["is_proxy"], "station_code"].tolist(),
        "out_of_box_codes": df.loc[out_of_box, "station_code"].tolist(),
        "duplicate_codes": duplicates,
    }
    return df, metrics


def merge_pump_sources(
    official: pd.DataFrame, geocoded: pd.DataFrame, match_m: float = 50.0
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """창원시 배수펌프장 표준데이터(공식 좌표)를 기본으로 하고, 공식 목록에 없는 지오코딩 펌프장을 보탠다.

    지오코딩 행은 가장 가까운 공식 펌프장까지 거리가 `match_m` 이하면 같은 시설로 보고 버린다
    (공식 좌표가 우선). 그보다 멀면 공식 목록에 없는 시설이므로 추가한다 — 이 행만 사람 검수(reviewed)가 필요하다.
    """
    off = official.rename(columns=OFFICIAL_PUMP_COLUMNS)
    missing = [c for c in ("pump_name", "lat", "lon") if c not in off.columns]
    if missing:
        raise ValueError(f"배수펌프장 표준데이터 필수 열 누락: {missing}")
    off = off.reindex(columns=list(OFFICIAL_PUMP_COLUMNS.values())).copy()
    off["lat"] = pd.to_numeric(off["lat"], errors="coerce")
    off["lon"] = pd.to_numeric(off["lon"], errors="coerce")
    off["source_kind"] = "official"
    off["source"] = "창원시 배수펌프장 표준데이터"
    off["reviewed"] = True
    off["note"] = ""

    go = geocoded.copy()
    go["lat"] = pd.to_numeric(go["lat"], errors="coerce")
    go["lon"] = pd.to_numeric(go["lon"], errors="coerce")
    go["reviewed"] = go["reviewed"].astype(str).str.strip().str.upper().eq("Y")
    go["note"] = go["note"].fillna("").astype(str)
    go = go.rename(columns={"address": "address_lot"})
    go["source_kind"] = "geocoded"

    off_pts = to_points(off.dropna(subset=["lat", "lon"]))
    go_pts = to_points(go.dropna(subset=["lat", "lon"]))
    off_xy = np.column_stack([off_pts.geometry.x, off_pts.geometry.y])
    go_xy = np.column_stack([go_pts.geometry.x, go_pts.geometry.y])
    dist, idx = cKDTree(off_xy).query(go_xy) if len(go_xy) else (np.array([]), np.array([], dtype=int))
    go_pts["nearest_official"] = off_pts["pump_name"].to_numpy()[idx] if len(idx) else []
    go_pts["nearest_official_m"] = np.round(dist, 1)
    matched = go_pts["nearest_official_m"] <= match_m
    added = go_pts[~matched].copy()

    columns = [
        "pump_name", "address_road", "address_lot", "installed_year", "purpose", "reference_date",
        "lat", "lon", "source_kind", "source", "reviewed", "note", "geometry",
    ]
    merged = pd.concat(
        [off_pts.reindex(columns=columns), added.reindex(columns=columns)], ignore_index=True
    )
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=CANONICAL_CRS)
    merged.insert(0, "pump_id", np.arange(1, len(merged) + 1))

    metrics = {
        "n_official": int(len(off_pts)),
        "n_official_without_coords": int(off[["lat", "lon"]].isna().any(axis=1).sum()),
        "n_geocoded": int(len(go_pts)),
        "n_matched_to_official": int(matched.sum()),
        "matched": [
            {"pump_name": r.pump_name, "official": r.nearest_official, "dist_m": float(r.nearest_official_m)}
            for r in go_pts[matched].itertuples()
        ],
        "n_added_from_geocoded": int(len(added)),
        "added_names": added["pump_name"].tolist(),
        "n_added_unreviewed": int((~added["reviewed"]).sum()),
        "n_pumps": int(len(merged)),
        "match_threshold_m": match_m,
    }
    return merged, metrics
