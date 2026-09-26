# Zenodo 기탁 목록 (M6, 클라우드 판)

> 절차: `docs/q1/M6_protocol.md` §5 (분류 규칙은 목록 생성 전에 고정).
> 명령: `PYTHONPATH=. .venv/bin/python -m src.repro.m6_run --steps zenodo --out-dir artifacts/q1/M6/m6_20260926T164903Z_7f7968f`
> 산출: `artifacts/q1/M6/m6_20260926T164903Z_7f7968f/zenodo_manifest.csv` (파일마다 경로·분류·처리·바이트·SHA256·근거),
> `zenodo_summary.json` (합계). 대상은 `cloud/M6` 트리의 git 추적 파일 전부다.
> **이 목록은 기탁 후보다.** 라이선스와 제3자 자료 공개 여부는 사용자가 정한다. OSF/Zenodo 등록도 사용자가 한다.

## 1. 합계 (목록 생성 시점)

| 처리 | 분류 | 파일 | 바이트 | 뜻 |
|---|---|---:|---:|---|
| open | code | 165 | 2,272,863 | 코드·설정·노트북·테스트 |
| open | docs | 59 | 941,829 | 절차·보고·연구 문서, 원본 설명(`data/raw/README.md`, `open_data_manifest.json`) |
| open | results | 71 | 14,846,944 | 평가·post-hoc·Q1 산출, `reports/` |
| open | frozen_models | 39 | 6,956,727 | 동결 RF(v1·v2)·사전 명세·분할 |
| open | raw_open | 1 | 389,120 | `data/raw/rivers/osm_waterways.gpkg` (ODbL) |
| restricted | derived_data | 5 | 62,259,225 | `artifacts/processed_snapshot/**` (격자 인구·흔적 라벨 포함) |
| hash_only | raw_restricted | 94 | 879,326 | 창원시 정보공개 흔적(2025·2022~2024), 행안부 API 흔적 |
| hash_only | raw_third_party | 17 | 17,395,643 | 강수·수위·펌프장 CSV, DEM, 대피시설, `data/external/*.csv` |
| exclude | internal | 2 | 17,624 | `.fablize/` 하네스 진행 기록 |
| **합계** | | **453** | **105,959,301** | |

- 라이선스 파일: **없음** (`zenodo_summary.json` → `license_files: []`).
- 간이 개인정보 검사: open 대상 문서·표에서 이메일·휴대전화 정규식에 걸린 것은 DOI·실수 값의 오탐뿐이었다.
- 해시는 목록 생성 시점 작업 트리 기준이다. 목록 뒤에 고친 파일(`docs/q1/M6.md`, 이 문서, M6 실행 폴더의 `summary.json`)은
  해시가 달라진다. **기탁 직전에 태그 커밋에서 같은 명령을 다시 실행해 목록을 새로 만든다.**

## 2. 기탁 구성 제안

| 기록 | 내용 | 접근 |
|---|---|---|
| A. 코드·결과 | open 전부 (code·docs·results·frozen_models·raw_open) + `zenodo_manifest.csv` | 공개 |
| B. 가공 자료 | restricted 5개 (`processed_snapshot`, SHA256SUMS 포함) | 제한 접근 (요청 시) — 원본 조건 확인 뒤 공개 전환 가능 |
| 해시 목록 | hash_only 111개는 올리지 않는다. A 에 넣는 목록의 경로·SHA256·출처로 받은 원본을 대조한다 | — |

- **GitHub–Zenodo 연동을 그대로 쓰면 안 된다.** `cloud-base` 는 원본을 일반 git 파일로 담는다.
  그래서 저장소 압축본에 hash_only 원본(홀드아웃 흔적 포함)이 들어간다. 연동을 쓰려면 `.gitattributes` 에
  `export-ignore` 를 걸거나, 목록의 open 파일만 골라 직접 올린다.
- 원본 받는 경로: `data/raw/README.md` 표(출처·URL·수집일)와 `docs/data_access_log.md`(신청 경로)를 A 에 함께 넣는다.
- `artifacts/processed_snapshot/SHA256SUMS` 는 해시 목록일 뿐이지만 규칙 6 에 따라 restricted 로 분류됐다. 공개해도 되는지 사용자가 정한다.

## 3. 사용자 결정이 필요한 것

1. **라이선스:** 저장소에 라이선스 파일이 없다. 예: 코드 MIT 또는 Apache-2.0, 문서·결과 CC BY 4.0.
   OSM 파생물은 ODbL(출처 표시·동일 조건)을 따른다.
2. **창원시 정보공개 흔적의 재배포:** 공공누리 유형 확인 전에는 hash_only 로 둔다 (`PAPER_ROADMAP.md` §7).
3. **재난안전데이터공유플랫폼 API 자료·공공데이터포털 CSV·DEM·대피시설:** 저장소에 이용 조건 기록이 없다. 확인 전에는 hash_only.
4. **가공 스냅샷:** SGIS 격자 인구와 흔적 라벨을 담는다. 제한 접근으로 둘지, 인구 열을 뺀 공개판을 따로 만들지 정한다.
5. **저장소 공개 여부:** GitHub 저장소가 공개면 hash_only 원본이 이미 배포되는 셈이다. 원본 조건과 함께 확인한다.
6. **저자·소속·키워드 등 메타데이터**는 사용자가 채운다.

## 4. 로컬에서 보완할 것

cloud-base 에 없는 LFS 전용 원본과 로컬 기록은 이 목록에 없다. 로컬에서 `git lfs pull` 뒤 같은 명령으로 목록을 다시 만든다
(LFS 포인터 파일 상태로 돌리면 포인터의 해시가 적힌다).

- `data/raw/sgis/**`, `data/raw/land_cover/**`, `data/raw/flood_maps/**`(해시는 `data/raw/open_data_manifest.json` 에도 있음),
  `data/raw/kma/**`, `data/raw/sewer/**`
- 예보 산출물, `data/processed` 전체(스냅샷 밖 파일), `.omc/` 의 리뷰·작업 보고서 가운데 기탁할 것
- `data/raw/`·`data/external/` 아래 새 원본은 규칙 5 에 따라 hash_only 가 된다. 그 밖의 새 경로는 마지막 규칙(code, open)으로
  떨어지므로, 원본이나 파생 자료를 다른 폴더에 두면 `src/repro/deposit_manifest.py` 의 `RULES` 부터 확인한다.
