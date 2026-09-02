"""손으로 찍은 좌표를 검사한다. 채워 넣은 직후 돌려서 오타를 잡는 용도다.

    python -m src.data.check_coordinates

지도에서 좌표를 옮겨 적을 때 흔한 실수를 잡는다.
- 위도·경도를 바꿔 적음 (창원은 위도 35, 경도 128 이라 바로 드러난다)
- 소수점 자리 실수
- 창원시 경계 밖
- 여러 지점이 완전히 같은 좌표 (복사·붙여넣기 사고)
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.utils.config import PROJECT_ROOT

EXTERNAL = PROJECT_ROOT / "data" / "external"
BOUNDARY = PROJECT_ROOT / "data" / "processed" / "spatial" / "changwon_boundary.gpkg"

# 창원시를 넉넉히 감싸는 상자. 이보다 벗어나면 확실히 잘못 적은 것이다.
LAT_RANGE = (34.9, 35.5)
LON_RANGE = (128.3, 129.0)

FILES = {
    "stations.csv": ("station_name", "관측지점"),
    "pump_stations_geocoded.csv": ("pump_name", "배수펌프장"),
}


def check(path: Path, label_column: str, title: str) -> list[str]:
    problems: list[str] = []
    if not path.exists():
        return [f"{path.name}: 파일이 없다"]

    df = pd.read_csv(path, encoding="utf-8-sig")
    total = len(df)
    filled = df.dropna(subset=["lat", "lon"])
    print(f"\n[{title}] {path.name}  {len(filled)}/{total} 채움")

    empty = df[df["lat"].isna() | df["lon"].isna()]
    if len(empty):
        print(f"  아직 비어 있음 {len(empty)}개: {', '.join(empty[label_column].astype(str)[:8])}"
              + (" …" if len(empty) > 8 else ""))
    if filled.empty:
        return problems

    for _, row in filled.iterrows():
        name = row[label_column]
        lat, lon = float(row["lat"]), float(row["lon"])
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
            hint = " (위도·경도를 바꿔 적은 것 같다)" if LON_RANGE[0] <= lat <= LON_RANGE[1] else ""
            problems.append(f"{name}: 위도 {lat} 가 창원 범위 {LAT_RANGE} 밖{hint}")
        if not (LON_RANGE[0] <= lon <= LON_RANGE[1]):
            problems.append(f"{name}: 경도 {lon} 가 창원 범위 {LON_RANGE} 밖")

    duplicated = filled[filled.duplicated(subset=["lat", "lon"], keep=False)]
    for coords, group in duplicated.groupby(["lat", "lon"]):
        problems.append(f"좌표 {coords} 가 여러 지점에 중복: {', '.join(group[label_column].astype(str))}")

    not_reviewed = filled[filled["reviewed"].astype(str).str.upper() != "Y"]
    if len(not_reviewed):
        print(f"  reviewed=N 인 행 {len(not_reviewed)}개 — 지도에서 확인했으면 Y 로 바꾼다")

    if BOUNDARY.exists():
        si = gpd.read_file(BOUNDARY, layer="si")
        points = gpd.GeoDataFrame(
            filled[[label_column]],
            geometry=gpd.points_from_xy(filled["lon"], filled["lat"]),
            crs="EPSG:4326",
        ).to_crs(si.crs)
        inside = gpd.sjoin(points, si[["geometry"]], predicate="within", how="left")
        outside = inside[inside["index_right"].isna()]
        for name in outside[label_column]:
            problems.append(f"{name}: 좌표가 창원시 경계 밖이다")
        print(f"  창원시 경계 안 {len(inside) - len(outside)}/{len(points)}")

    return problems


def main() -> int:
    all_problems: list[str] = []
    for filename, (label_column, title) in FILES.items():
        all_problems += check(EXTERNAL / filename, label_column, title)

    if all_problems:
        print(f"\n문제 {len(all_problems)}건")
        for problem in all_problems:
            print(f"  - {problem}")
        return 1
    print("\n문제 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
