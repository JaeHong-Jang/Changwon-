"""대피장소·방재기관 포인트 (창원 도시침수정보시스템 `api/data/point`).

frequency=1 은 대피장소, frequency=2 는 방재기관이다. 두 파일 모두 위경도(WGS84)를 담은
JSON 배열이며, Layer 3 의 대응역량(접근성) 변수로 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SHELTER_KINDS = {
    "changwon_shelter_frequency1.json": "shelter",
    "changwon_facility_frequency2.json": "facility",
}


def load(paths: list[Path], *, crs: str = "EPSG:5179") -> tuple[Any, dict[str, Any]]:
    """JSON 배열들을 하나의 포인트 GeoDataFrame 으로. `kind` 열로 대피장소/방재기관을 구분한다."""
    import geopandas as gpd
    import pandas as pd

    rows = []
    per_file: dict[str, int] = {}
    for path in sorted(Path(p) for p in paths):
        records = json.loads(path.read_text(encoding="utf-8"))
        kind = SHELTER_KINDS.get(path.name, path.stem)
        kept = 0
        for record in records:
            coords = record.get("latLng") or {}
            lat, lon = coords.get("lat"), coords.get("lng")
            if lat is None or lon is None:
                continue
            rows.append({
                "kind": kind,
                "name": record.get("name"),
                "address": record.get("addr"),
                "dist_code": record.get("distCode"),
                "lat": float(lat),
                "lon": float(lon),
            })
            kept += 1
        per_file[path.name] = kept
    if not rows:
        raise ValueError("대피장소·방재기관 포인트를 하나도 읽지 못했다")

    frame = pd.DataFrame(rows)
    points = gpd.GeoDataFrame(
        frame, geometry=gpd.points_from_xy(frame["lon"], frame["lat"]), crs="EPSG:4326"
    ).to_crs(crs)
    metrics = {
        "rows_per_file": per_file,
        "n_points": int(len(points)),
        "by_kind": {k: int(v) for k, v in points["kind"].value_counts().items()},
        "crs": crs,
    }
    return points, metrics
