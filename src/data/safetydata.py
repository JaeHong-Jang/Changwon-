"""행정안전부 재난안전데이터공유플랫폼 침수흔적도 수집."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

ENDPOINT = "https://www.safetydata.go.kr/V2/api/DSSP-IF-00117"
SOURCE_CRS = "EPSG:3857"
PAGE_SIZE = 1000
# 창원 5개 구의 행정안전부 시군구 코드
CHANGWON_SGG = {"48121", "48123", "48125", "48127", "48129"}
SGG_NAMES = {
    "48121": "의창구", "48123": "성산구", "48125": "마산합포구",
    "48127": "마산회원구", "48129": "진해구",
}
# 내수 침수 원인 토큰.
INLAND_TOKENS = ("내수", "배수", "우수", "관거", "맨홀", "저지대")


def _api_key() -> str:
    key = os.environ.get("SAFETYDATA_API_KEY")
    if not key:
        env = Path(".env")
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("SAFETYDATA_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise RuntimeError(
            "SAFETYDATA_API_KEY 가 없다. .env 에 넣거나 환경변수로 준다. "
            "키는 https://www.safetydata.go.kr 회원가입 후 활용신청으로 받는다"
        )
    return key


def fetch_page(page: int, *, rows: int = PAGE_SIZE, timeout: int = 120) -> dict[str, Any]:
    """한 페이지를 받는다. 실패하면 예외를 던진다 (조용히 빈 결과로 넘어가지 않는다)."""
    query = urllib.parse.urlencode({
        "serviceKey": _api_key(), "pageNo": page, "numOfRows": rows, "returnType": "json",
    })
    request = urllib.request.Request(
        f"{ENDPOINT}?{query}",
        headers={"User-Agent": "changwon-flood-research/1.0 (academic)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("header", {})
    if result.get("resultCode") != "00":
        raise RuntimeError(f"API 오류 {result.get('resultCode')}: {result.get('resultMsg')}")
    return payload


def iter_records(*, sleep: float = 0.3, max_pages: int | None = None) -> Iterator[list[dict[str, Any]]]:
    """전건을 페이지 단위로 흘려보낸다. 첫 페이지에서 총건수를 읽어 페이지 수를 정한다."""
    first = fetch_page(1)
    total = int(first.get("totalCount", 0))
    pages = -(-total // PAGE_SIZE)
    if max_pages:
        pages = min(pages, max_pages)
    yield first.get("body") or []
    for page in range(2, pages + 1):
        time.sleep(sleep)
        yield fetch_page(page).get("body") or []


def collect_changwon(*, sleep: float = 0.3, max_pages: int | None = None,
                     progress: bool = True) -> tuple[Any, dict[str, Any]]:
    """전건을 훑어 창원 5개 구 레코드만 GeoDataFrame 으로 모은다."""
    import geopandas as gpd
    import pandas as pd
    from shapely import wkt

    from src.data.spatial import CANONICAL_CRS, fix_geometry

    kept: list[dict[str, Any]] = []
    seen = 0
    by_sido: dict[str, int] = {}
    for page_index, batch in enumerate(iter_records(sleep=sleep, max_pages=max_pages), start=1):
        seen += len(batch)
        for row in batch:
            sido = str(row.get("STDG_CTPV_CD", ""))
            by_sido[sido] = by_sido.get(sido, 0) + 1
            if str(row.get("STDG_SGG_CD", "")) in CHANGWON_SGG:
                kept.append(row)
        if progress and page_index % 5 == 0:
            print(f"  {page_index}페이지 · 누적 {seen:,}건 · 창원 {len(kept)}건", flush=True)

    metrics: dict[str, Any] = {
        "endpoint": ENDPOINT,
        "records_scanned": seen,
        "records_changwon": len(kept),
        "by_sido_top": dict(sorted(by_sido.items(), key=lambda kv: -kv[1])[:5]),
    }
    if not kept:
        metrics["note"] = "창원 레코드가 없다. 시군구 코드 체계를 다시 확인할 것"
        return gpd.GeoDataFrame(geometry=[], crs=CANONICAL_CRS), metrics

    frame = pd.DataFrame(kept)
    frame["geometry"] = frame["GEOM"].apply(wkt.loads)
    gdf = gpd.GeoDataFrame(frame.drop(columns=["GEOM"]), geometry="geometry", crs=SOURCE_CRS)
    gdf = gdf.to_crs(CANONICAL_CRS)
    gdf, fixed = fix_geometry(gdf)

    gdf["sgg_name"] = gdf["STDG_SGG_CD"].astype(str).map(SGG_NAMES)
    gdf["event_date"] = pd.to_datetime(gdf["FLDN_BGNG_YMD"].astype(str), format="%Y%m%d", errors="coerce")
    gdf["cause"] = gdf["FLDN_CS_DTL_NM"].astype(str)
    gdf["event_name"] = gdf["FLDN_DST_NM"].astype(str)
    gdf["is_inland"] = gdf["cause"].str.contains("|".join(INLAND_TOKENS), na=False)

    metrics.update({
        "invalid_fixed": fixed,
        "area_km2": round(float(gdf.geometry.area.sum() / 1e6), 4),
        "by_sgg": {SGG_NAMES.get(k, k): int(v) for k, v in gdf["STDG_SGG_CD"].astype(str).value_counts().items()},
        "years": sorted(gdf["FLDN_YR"].astype(str).unique().tolist()),
        "n_events": int(gdf["event_name"].nunique()),
        "events": sorted(gdf["event_name"].dropna().unique().tolist()),
        "n_inland": int(gdf["is_inland"].sum()),
        "source_crs": SOURCE_CRS,
        "crs": CANONICAL_CRS,
    })
    return gdf, metrics
