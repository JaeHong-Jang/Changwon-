"""개발 자료와 특징 집합을 읽고 고정 특징 변환을 적용한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


EVENTS = [2006, 2012, 2014, 2016, 2019, 2025]


F0 = ["rel_elev_m", "slope_deg", "twi", "impervious_frac", "river_proximity",
      "culvert_proximity", "pump_within_km"]


F1 = F0 + ["flood_l210_100_depth_m"]


FEATURES = {"F0": F0, "F1": F1, "F2": F1 + [
    "rain_annual_max_1h", "rain_hours_over_30mm", "rain_top5_3h", "rain_top5_24h",
]}


def feature_frame(layer: Any, features: Any) -> Any:
    """격자 키로 특징을 결합하고 고정 거리 변환을 적용한다."""
    # 원래 격자 순서를 유지해 지형·시설·강수 특징을 결합한다.
    columns = [c for c in F0 if c not in {"river_proximity", "culvert_proximity", "pump_within_km"}]
    columns += ["river_dist_m", "culvert_dist_m", "pump_dist_m", "flood_l210_100_depth_m"]
    rain = FEATURES["F2"][len(F1):]
    out = layer[["grid_id"] + rain].merge(features[["grid_id"] + columns],
                                          on="grid_id", how="left", validate="one_to_one", indicator=True)
    if not out["_merge"].eq("both").all():
        raise ValueError("특징이 없는 grid_id")
    # 거리 특징을 고정 범위로 변환하고 비유한 값을 결측으로 통일한다.
    out["river_proximity"] = np.maximum(0, 1 - out["river_dist_m"] / 300)
    out["culvert_proximity"] = np.maximum(0, 1 - out["culvert_dist_m"] / 300).fillna(0)
    out["pump_within_km"] = (out["pump_dist_m"] <= 1000).astype(float)
    out.loc[out["pump_dist_m"].isna(), "pump_within_km"] = np.nan
    return out.replace([np.inf, -np.inf], np.nan)


def load_development() -> tuple[Any, Any, np.ndarray, np.ndarray, np.ndarray]:
    """지정된 가공 자료 두 파일만 읽고 개발 사상 라벨의 일치를 확인한다."""
    # 개발 격자와 특징 파일을 읽는 라이브러리를 불러온다.
    import geopandas as gpd
    import pandas as pd

    # 좌표계와 사상별 라벨을 검증한 뒤 특징과 중심점 좌표를 반환한다.
    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    if layer.crs.to_epsg() != 5179:
        raise ValueError("EPSG:5179 자료가 필요하다")
    events = layer[[f"trace_ev_{year}" for year in EVENTS]].to_numpy()
    if not np.isin(events, [0, 1]).all():
        raise ValueError("사상 라벨은 결측 없는 0/1이어야 한다")
    events = events.astype(bool)
    labels = events.any(axis=1)
    if not np.array_equal(labels, layer["trace_label"].to_numpy().astype(bool)):
        raise ValueError("개발 사상 합집합과 trace_label 불일치: 실행 중단")
    features = pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet")
    frame = feature_frame(layer, features)
    centers = layer.geometry.centroid
    return layer, frame, np.column_stack([centers.x, centers.y]), labels, events


def load_development_traces():
    """개발 원본만 읽고 사상·역할·좌표계를 확인한다."""
    # 개발 자료만 선택하는 흔적 로더를 불러온다.
    from src.data import flood_traces

    # 개발 역할·좌표계·사상 범위를 검증한다.
    traces, metadata = flood_traces.load(flood_traces.files_for("development"))
    if not traces.role.eq("development").all() or traces.crs.to_epsg() != 5179:
        raise ValueError("EPSG:5179 개발 흔적만 허용한다")
    if not traces.event_year.astype(str).isin([str(year) for year in EVENTS]).all():
        raise ValueError("개발 사상 밖의 흔적")
    return traces, metadata
