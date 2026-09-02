"""창원 침수예상도(A1) 정규화. 원본은 수정하지 않고 canonical 레이어를 만든다.

원본 WFS 응답의 두 가지 문제를 여기서 고친다.

1. **좌표계가 EPSG:5181** 이다 (중부원점 GRS80, 분석 기준 EPSG:5179 아님).
   재투영하지 않고 격자와 겹치면 수백 미터가 어긋난다.
2. **한글 문자열 컬럼이 깨져 있다.** 서버가 cp949 바이트를 latin1 로 잘못 디코딩해
   내보낸다: `ÁøÇØ` → `진해`. `value.encode("latin1").decode("cp949")` 로 복원한다.

레이어 이름은 `L{종류}_{재현기간}` 이다. L200 내수침수, L210 복합, L220 외수범람,
L300 하천범람(재현기간 없음).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

SOURCE_CRS = "EPSG:5181"
TARGET_CRS = "EPSG:5179"

FLOOD_KINDS = {
    "L200": "내수침수",
    "L210": "복합",
    "L220": "외수범람",
    "L300": "하천범람",
}

# 침수심 구간 문자열 → 대표값(m). 순서를 비교할 수 있어야 위험도 비교가 된다.
DEPTH_MIDPOINT = {
    "~0.5": 0.25,
    "0.5~1.0": 0.75,
    "1.0~1.5": 1.25,
    "1.5~2.0": 1.75,
    "2.0~3.0": 2.5,
    "3.0~": 3.5,
}


def repair_cp949(value: Any) -> Any:
    """latin1 로 잘못 디코딩된 cp949 문자열을 되살린다. 이미 정상이면 그대로 둔다."""
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    # 복원 결과에 한글이 있으면 성공으로 본다.
    return repaired if any("가" <= ch <= "힣" for ch in repaired) else value


def parse_layer_name(name: str) -> tuple[str, int | None]:
    """`L210_100` → ("복합", 100). `L300` → ("하천범람", None)."""
    match = re.fullmatch(r"(L\d{3})(?:_(\d+))?", name)
    if not match:
        raise ValueError(f"레이어 이름 형식이 다릅니다: {name}")
    kind, period = match.group(1), match.group(2)
    if kind not in FLOOD_KINDS:
        raise ValueError(f"모르는 침수도 종류입니다: {kind}")
    return FLOOD_KINDS[kind], int(period) if period else None


def load_layer(path: Path) -> gpd.GeoDataFrame:
    """한 레이어를 읽어 재투영하고 문자열을 복원한 뒤 공통 스키마로 맞춘다."""
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        raise ValueError(f"{path.name}: CRS 정보가 없습니다")
    source_crs = gdf.crs.to_string()
    gdf = gdf.to_crs(TARGET_CRS)

    # pandas 3.0 의 문자열 컬럼은 Arrow 백엔드(dtype "str")라 `dtype == object` 로 걸리지
    # 않는다. 그 검사를 쓰면 복원이 조용히 건너뛰어진다.
    for column in gdf.columns:
        if column != "geometry" and pd.api.types.is_string_dtype(gdf[column]):
            gdf[column] = gdf[column].map(repair_cp949)

    kind, period = parse_layer_name(path.stem)
    gdf["flood_kind"] = kind
    gdf["return_period_years"] = period
    gdf["layer"] = path.stem
    gdf["source_crs"] = source_crs
    gdf["depth_m"] = gdf["F_SHIM"].map(DEPTH_MIDPOINT)
    # L300 은 행정구역 컬럼 이름이 AMD_CD, 나머지는 ADM_CD 다. 지구명(IDX_NM)도 L300 에만 있다.
    gdf["adm_cd"] = gdf.get("ADM_CD", gdf.get("AMD_CD"))
    gdf["district_name"] = gdf["IDX_NM"] if "IDX_NM" in gdf.columns else pd.NA

    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        from shapely import make_valid

        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].apply(make_valid)
    gdf.attrs["invalid_fixed"] = int(invalid.sum())
    return gdf


def combine(paths: list[Path]) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """모든 레이어를 하나의 표로 합치고 검증 지표를 함께 돌려준다."""
    frames = [load_layer(p) for p in sorted(paths)]
    if not frames:
        raise ValueError("침수예상도 파일이 없습니다")

    keep = ["layer", "flood_kind", "return_period_years", "F_SHIM", "depth_m",
            "F_AREA", "adm_cd", "district_name", "WRT_YR", "source_crs", "geometry"]
    merged = pd.concat([f[keep] for f in frames], ignore_index=True)
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=TARGET_CRS)
    merged = merged.rename(columns={"F_SHIM": "depth_class", "F_AREA": "area_m2", "WRT_YR": "written_year"})

    unmapped = merged.loc[merged["depth_m"].isna(), "depth_class"].dropna().unique()
    metrics = {
        "layers": len(frames),
        "features": int(len(merged)),
        "features_by_layer": {p.stem: int(len(f)) for p, f in zip(sorted(paths), frames)},
        "source_crs": sorted(merged["source_crs"].unique()),
        "target_crs": TARGET_CRS,
        "depth_classes": sorted(merged["depth_class"].dropna().unique()),
        "unmapped_depth_classes": sorted(unmapped),
        "invalid_geometry_fixed": sum(f.attrs.get("invalid_fixed", 0) for f in frames),
        "invalid_geometry_remaining": int((~merged.geometry.is_valid).sum()),
        "repaired_text_sample": _text_sample(frames),
    }
    return merged, metrics


def _text_sample(frames: list[gpd.GeoDataFrame]) -> dict[str, str]:
    """복원이 실제로 됐는지 눈으로 볼 수 있게 한글 값 몇 개를 보여준다."""
    sample: dict[str, str] = {}
    for frame in frames:
        for column in frame.columns:
            if column in sample or column == "geometry" or not pd.api.types.is_string_dtype(frame[column]):
                continue
            values = [v for v in frame[column].dropna().unique()[:5]
                      if isinstance(v, str) and any("가" <= ch <= "힣" for ch in v)]
            if values:
                sample[column] = values[0]
    return sample
