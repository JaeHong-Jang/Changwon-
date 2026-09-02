"""로그인·인증키 없이 받을 수 있는 공개 데이터를 내려받는다 (접근신청 #17).

받은 파일은 `data/raw/` 아래에 저장하고 취득일·URL·sha256 을 `manifest` 로 남긴다.
H00 수집 확인 노드가 그 기록을 읽는다.

    python -m src.data.fetch_open_data            # 전체
    python -m src.data.fetch_open_data --only a1  # 하나만
    python -m src.data.fetch_open_data --list     # 목록만 보기

여기 없는 항목:
- A2 침수흔적도 PDF, A3 대피장소 PDF, A7 홍수위험지도 — 게시판이 JavaScript 로 첨부
  링크를 만들거나 폼 제출이 필요해 자동화하지 않았다.
- A9 환경부 하수도통계 — 이미 `data/raw/2025 하수도통계.xlsx` 로 보유 중이다.
  직접 링크는 `https://www.hasudoinfo.or.kr/bbs/fileDownload.do?atcmtFileId=usn7f8pi0anvmUBtUTfCjWsKZCLVboz6FJMGRGr7JJA%3D&fileSn=1`
`docs/data_acquisition_todo.md` 의 수동 절차를 따른다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.utils.config import PROJECT_ROOT

RAW = PROJECT_ROOT / "data" / "raw"
TIMEOUT = 180
CHUNK = 1 << 16

WFS = "https://bangjae.changwon.go.kr/geoserver/cw/wfs"
WFS_QUERY = "service=WFS&version=1.1.0&request=GetFeature&outputFormat=application/json&typeName=cw:"


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    dest: str
    description: str


# 창원 침수예상도: L200/L210/L220 은 강우 시나리오, 뒤 숫자는 재현기간(년).
# L300 은 하천 범람 예상도. 건수는 2026-08-22 확인값.
FLOOD_LAYERS = {
    "L200_050": "내수침수 50년", "L200_080": "내수침수 80년",
    "L200_100": "내수침수 100년 (28,544건)", "L200_200": "내수침수 200년",
    "L210_030": "복합 30년", "L210_050": "복합 50년",
    "L210_080": "복합 80년", "L210_100": "복합 100년 (41,130건)",
    "L220_050": "외수범람 50년", "L220_100": "외수범람 100년 (2,681건)",
    "L220_150": "외수범람 150년", "L220_200": "외수범람 200년",
    "L300": "하천 범람 예상도 (62,430건)",
}

SOURCES: list[Source] = [
    *(
        Source(
            key=f"a1_{layer.lower()}",
            url=f"{WFS}?{WFS_QUERY}{layer}",
            dest=f"flood_maps/changwon_wfs/{layer}.geojson",
            description=f"A1 창원 침수예상도 {label}",
        )
        for layer, label in FLOOD_LAYERS.items()
    ),
    Source(
        key="a5_shelter",
        url="https://bangjae.changwon.go.kr/api/api/data/point?frequency=1",
        dest="shelters/changwon_shelter_frequency1.json",
        description="A5 임시주거시설·학교 포인트",
    ),
    Source(
        key="a5_facility",
        url="https://bangjae.changwon.go.kr/api/api/data/point?frequency=2",
        dest="shelters/changwon_facility_frequency2.json",
        description="A5 경로당·경찰·소방·병원 포인트",
    ),
]


def download(source: Source) -> dict:
    """한 항목을 받아 sha256 과 함께 기록을 돌려준다."""
    path = RAW / source.dest
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0

    request = urllib.request.Request(source.url, headers={"User-Agent": "changwon-research/1.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, path.open("wb") as out:
        while chunk := response.read(CHUNK):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)

    return {
        "key": source.key,
        "description": source.description,
        "url": source.url,
        "path": str(path.relative_to(PROJECT_ROOT)),
        "bytes": size,
        "sha256": digest.hexdigest(),
        "collected_at": date.today().isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m src.data.fetch_open_data", description=__doc__)
    parser.add_argument("--only", action="append", help="이 key 만 받는다 (여러 번 지정 가능)")
    parser.add_argument("--list", action="store_true", help="받지 않고 목록만 출력")
    args = parser.parse_args()

    targets = [s for s in SOURCES if not args.only or s.key in args.only]
    if args.list:
        for s in targets:
            print(f"{s.key:22} {s.description}\n{'':22} → data/raw/{s.dest}")
        return 0

    records, failed = [], []
    for source in targets:
        print(f"받는 중  {source.key:22} {source.description}")
        try:
            record = download(source)
            records.append(record)
            print(f"  완료   {record['bytes'] / 1e6:8.2f} MB  {record['sha256'][:16]}…")
        except Exception as exc:  # noqa: BLE001 — 하나 실패해도 나머지는 계속
            failed.append({"key": source.key, "error": f"{type(exc).__name__}: {exc}"})
            print(f"  실패   {type(exc).__name__}: {exc}")

    manifest = RAW / "open_data_manifest.json"
    previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    merged = {r["key"]: r for r in previous} | {r["key"]: r for r in records}
    manifest.write_text(
        json.dumps(sorted(merged.values(), key=lambda r: r["key"]), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n성공 {len(records)} / 실패 {len(failed)}")
    print(f"기록  {manifest.relative_to(PROJECT_ROOT)}")
    if failed:
        for f in failed:
            print(f"  {f['key']}: {f['error']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
