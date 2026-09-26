"""침수흔적 폴리곤이 격자 라벨로 옮겨질 때 어떤 객체가 사라지는지 추적한다. 점수는 쓰지 않는다."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.models.provenance import file_sha256

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/evaluation/label_audit"
THRESHOLD = 0.10
AREA_BINS = [0, 500, 1_000, 5_000, 20_000, np.inf]


def _land_class(value: Any) -> str:
    """토지이용 값을 도심·농업·미상으로 분류한다."""
    import pandas as pd

    # 결측을 빈 문자열로 바꾼 뒤 기존 접두어 규칙을 적용한다.
    text = "" if pd.isna(value) else str(value)
    if text.startswith("도심"):
        return "urban"
    if text.startswith("농"):
        return "agricultural"
    return "unknown"


def audit(grid, traces) -> Any:
    """폴리곤별: 면적, 교차 격자 수, 최대 격자 겹침 비율, 규칙별로 양성 격자를 하나라도 만드는지."""
    import geopandas as gpd
    import pandas as pd
    import shapely

    from src.data import flood_traces as FT

    # 현행 합집합 격자 라벨과 폴리곤별 교차 격자를 구한다.
    cells = grid[["geometry"]].reset_index(drop=True)
    polys = traces.reset_index(drop=True)
    labels, fractions = FT.label_grid(cells, polys, min_overlap=THRESHOLD)
    pairs = gpd.sjoin(polys[["geometry"]].reset_index(names="_poly"), cells.reset_index(names="_cell"),
                      predicate="intersects")[["_poly", "_cell"]]

    # 각 폴리곤과 격자의 교집합 비율 및 대표점 격자를 기록한다.
    own = shapely.intersection(polys.geometry.values[pairs["_poly"].to_numpy()],
                               cells.geometry.values[pairs["_cell"].to_numpy()])
    pairs = pairs.assign(own_frac=shapely.area(own) / cells.geometry.area.iloc[pairs["_cell"]].to_numpy(),
                         union_frac=fractions[pairs["_cell"]], positive=labels[pairs["_cell"]])
    point_cell = gpd.sjoin(polys.geometry.representative_point().to_frame("geometry").reset_index(names="_poly"),
                           cells.reset_index(names="_cell"), predicate="within").set_index("_poly")["_cell"]

    # 폴리곤별 최대 겹침과 현행 라벨 기여 여부를 집계한다.
    per = pairs.groupby("_poly").agg(n_cells=("_cell", "size"), max_own_frac=("own_frac", "max"),
                                     max_union_frac=("union_frac", "max"), any_positive=("positive", "any"))
    out = pd.DataFrame({
        "object_id": polys["object_id"], "storm_id": polys["storm_id"],
        "land_class": polys.get("land_use", pd.Series(None, index=polys.index)).map(_land_class),
        "area_m2": polys.geometry.area,
    }).join(per)

    # 대안 라벨 규칙과 면적 구간을 기존 순서로 추가한다.
    out["n_cells"] = out["n_cells"].fillna(0).astype(int)
    out["rule_any_overlap"] = out["n_cells"] > 0
    out["rule_own_10pct"] = out["max_own_frac"].fillna(0) > THRESHOLD
    out["rule_grid_10pct"] = out["any_positive"].fillna(False).astype(bool)
    out["rule_point_cell"] = out.index.isin(point_cell.index)
    out["area_bin"] = pd.cut(out["area_m2"], AREA_BINS, right=False,
                             labels=["<500", "500-1k", "1k-5k", "5k-20k", ">=20k"])
    return out


def summarise(table) -> dict[str, Any]:
    """토지이용·면적 구간별로 10% 격자 규칙에서 살아남는 폴리곤 비율."""
    def rates(frame):
        """한 그룹의 생존율과 중간 면적을 요약한다."""
        # 두 겹침 규칙의 생존율을 원래 정밀도로 반올림한다.
        return {"n": int(len(frame)), "survive_grid_10pct": round(float(frame["rule_grid_10pct"].mean()), 3),
                "survive_own_10pct": round(float(frame["rule_own_10pct"].mean()), 3),
                "median_area_m2": round(float(frame["area_m2"].median()), 1)}

    # 전체와 토지이용·면적·사상별 요약을 만든다.
    return {
        "all": rates(table),
        "by_land_class": {k: rates(g) for k, g in table.groupby("land_class")},
        "by_area_bin": {str(k): rates(g) for k, g in table.groupby("area_bin", observed=True)},
        "by_storm": {k: rates(g) for k, g in table.groupby("storm_id")},
    }


def run(role: str = "holdout") -> dict[str, Any]:
    """지정한 흔적 역할의 라벨 감사 표와 요약을 저장한다."""
    import geopandas as gpd

    from src.data import flood_traces as FT

    # 실행 시각과 코드 해시를 기록하고 지정한 역할의 흔적을 읽는다.
    started = datetime.now(timezone.utc)
    code_sha = file_sha256(Path(__file__))
    run_id = f"label_audit_{role}_{started:%Y%m%dT%H%M%SZ}_{code_sha[:8]}"
    grid = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg", columns=["grid_id"])
    traces, _ = FT.load(FT.files_for(role))

    # 폴리곤 감사 CSV와 역할별 요약 JSON을 기록한다.
    table = audit(grid, traces)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT / f"{role}_polygons.csv", index=False)
    result = {"run_id": run_id, "command": f"python -m src.models.label_audit {role}",
              "code_sha256": code_sha, "threshold": THRESHOLD, "role": role, **summarise(table)}
    (OUTPUT / f"{role}_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    import sys

    print(json.dumps(run(sys.argv[1] if len(sys.argv) > 1 else "holdout"), ensure_ascii=False, indent=1))
