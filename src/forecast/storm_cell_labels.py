"""연결된 침수흔적만으로 사상별 격자 라벨과 객체를 만든다."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from src.data.trace_labels import label_grid
from src.forecast.storm_labels import trace_keys

LABEL_COUNTS: dict = {}


def storm_objects(storms, trace_links, traces) -> dict[str, gpd.GeoDataFrame]:
    """양성 사상별 linked 침수 폴리곤만 원래 CRS로 반환한다."""
    # 격자화할 사상과 연결된 흔적의 유일 키를 준비한다.
    positive = storms.loc[pd.to_numeric(storms["label"], errors="coerce").eq(1),
                          ["storm_id", "role"]].copy()
    linked = trace_links.loc[trace_links["status"].eq("linked") & trace_links["storm_id"].notna(),
                             ["trace_key", "storm_id", "role"]].copy()
    if linked["trace_key"].isna().any() or linked.duplicated("trace_key").any():
        raise ValueError("한 흔적이 여러 사상에 연결됐다")
    if positive.duplicated("storm_id").any():
        raise ValueError("양성 storm_id가 중복됐다")

    # 전체 흔적에서 FC1 키를 재생성하고 역할과 사상 역할을 함께 검증한다.
    source = traces.drop(columns=["storm_id", "trace_key"], errors="ignore").copy()
    source.insert(0, "trace_key", trace_keys(traces).to_numpy())
    found = linked.merge(source, on=["trace_key", "role"], how="left", validate="one_to_one",
                         indicator=True)
    if not found["_merge"].eq("both").all():
        raise ValueError("연결 표의 trace_key 또는 역할이 흔적 표와 다르다")
    roles = positive.set_index("storm_id")["role"]
    if (found["storm_id"].map(roles).ne(found["role"])).any():
        raise ValueError("연결 흔적과 사상 역할이 다르다")
    result = {}
    polygon = found["geometry"].map(lambda geometry: geometry is not None and
                                    geometry.geom_type in {"Polygon", "MultiPolygon"})
    for row in positive.itertuples():
        chosen = found.loc[found["storm_id"].eq(row.storm_id) & found["role"].eq(row.role) &
                           polygon].drop(columns="_merge")
        result[str(row.storm_id)] = gpd.GeoDataFrame(chosen, geometry="geometry", crs=traces.crs)
    return result


def storm_labels(storms, trace_links, traces, grid, min_overlap: float = 0.10) -> dict[str, np.ndarray]:
    """linked 흔적만 겹침 규칙으로 격자화하고 빈 양성 사상도 보존한다."""
    # 양성 사상의 객체를 고르고 격자와 CRS를 대조한다.
    if grid.crs is None or traces.crs != grid.crs or grid.crs.to_epsg() != 5179:
        raise ValueError("격자와 흔적에 같은 EPSG:5179가 필요하다")
    objects = storm_objects(storms, trace_links, traces)
    result = {}

    # 연결 객체가 없는 양성 사상도 0 격자로 남겨 사상 수를 기록한다.
    for storm_id, polygons in objects.items():
        result[storm_id] = (np.zeros(len(grid), dtype=bool) if polygons.empty else
                            label_grid(grid, polygons, min_overlap=min_overlap)[0])
    LABEL_COUNTS.clear()
    LABEL_COUNTS.update({"n_positive_storms": len(result),
                         "n_positive_zero_cells": sum(not label.any() for label in result.values())})
    return result
