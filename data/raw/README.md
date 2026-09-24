# data/raw — 원본 데이터

수집한 원본 데이터를 이 폴더에 저장합니다.

## 규칙
- **원본 데이터는 절대 수정하지 않습니다.**
- 파일명 형식: `{출처}_{데이터명}_{수집일}.{확장자}`
  - 예: `datagokr_창원시_교통사고_20260701.csv`
- 원본 데이터는 Git LFS로 공유합니다. 새로 clone한 뒤 `git lfs pull`로 실제 파일을 받으세요.
- 데이터 출처와 다운로드 URL을 아래 표에 기록해 주세요.

## 다운로드

```bash
brew install git-lfs  # macOS에서 최초 1회
git lfs install
git lfs pull
```

## 데이터 목록

| 파일명 | 출처 | URL | 수집일 | 비고 |
|--------|------|-----|--------|------|
| `경상남도 창원시_시간별 강수량_20250923.csv` | 창원시·공공데이터포털 | https://www.data.go.kr/data/15150315/fileData.do | 2026-08-19 | 173,740행; 지점별 집중호우·공간보간 분석 |
| `경상남도 창원시_하천수위 통계_20250922.csv` | 창원시·공공데이터포털 | https://www.data.go.kr/data/15150319/fileData.do | 2026-08-19 | 9,598행; 강수 후 수위 반응·시간차 보조 검증 |
| `경상남도_창원시_배수펌프장 현황_20250801.csv` | 창원시·공공데이터포털 | https://www.data.go.kr/data/15047868/fileData.do | 2026-08-19 | 9건; 주소 지오코딩 후 격자별 최근접 펌프장 거리 산정 |
| `sgis/aggregation_boundaries_2025_2Q/` | SGIS 통계지리정보서비스 | https://sgis.kostat.go.kr/ | 2026-08-19 | 창원시 5개 구 집계구 경계(38111~38115) |
| `sgis/aggregation_statistics_2024/` | SGIS 통계지리정보서비스 | https://sgis.kostat.go.kr/ | 2026-08-19 | 성·연령별 인구, 총인구, 노령화지수 |
| `sgis/grid_boundaries_100m_2025/` | SGIS 통계지리정보서비스 | https://sgis.kostat.go.kr/ | 2026-08-19 | 100m 격자경계(라라·라마·마라·마마) |
| `sgis/grid_statistics_100m_2024/` | SGIS 통계지리정보서비스 | https://sgis.kostat.go.kr/ | 2026-08-19 | 100m 격자 인구·가구·주택 통계 |
| `dem/public_dem_2025/` | 국토지리정보원 국토정보플랫폼 | http://map.ngii.go.kr/ms/map/NlipMap.do?tabGb=total | 2026-08-19 | HFA 6개 도엽(35810·35811·35812·35814·35815·35816); `rasterio 1.5.1` 확인 결과 EPSG:5179, 90m, NoData -9999 |
| `land_cover/middle_2025/` | 기후에너지환경부 환경공간정보서비스 | https://aid.mcee.go.kr/ | 2026-08-19 | 2025 중분류 16개 도엽, EPSG:5186; 불투수면비율 및 내륙수(`L2_CODE=710`) 하천 공간대체 산정 |
| `river/경상남도_창원시_하천_20250203.csv` | 창원시·공공데이터포털 | https://www.data.go.kr/ | 2026-08-19 | 53개 하천 명칭·시종점 주소·길이; 좌표는 전체 결측이므로 보조 메타데이터로만 사용 |
| `rivers/osm_waterways.gpkg` | OpenStreetMap (Overpass API) | https://overpass-api.de/api/interpreter | 2026-09-08 | 창원 bbox(35.05~35.40N, 128.35~128.95E) `waterway=river\|stream\|canal\|drain` 728개(창원 경계 교차), 총연장 501km, 복개(tunnel=culvert) 191개. ODbL — 출처표시·동일조건 재배포. md5 `66b928a7f27200954a9de3b35f6a4fce`. 재취득: `.cache_ingest` 삭제 후 취득 스크립트 재실행 |
| `flood_traces/changwon_info_disclosure_20260916/` | 창원시 정보공개청구 회신 | 정부24 정보공개청구 접수번호 17369500 | 2026-09-16 | 2025-07-16~20 침수흔적도 SHP; `L100_침수심` 19건, `L110_침수위` 18건, 총 37개 폴리곤; 원본 CRS Korea 2000 Central Belt 2010 |
| `flood_traces/changwon_info_disclosure_20260924/2023/` | 창원시 침수흔적도 제공자료 | 다운로드 파일 `2023년 침수흔적도(창원).zip` | 2026-09-24 | 동부원점(EPSG:5187)·중부원점(EPSG:5186) 각 L100 17건·L110 8건; 16개 파일. 폴더 연도는 제공 ZIP 기준이며 L110 발생일에 2022-09-06·2023-08-10이 함께 존재 |
| `flood_traces/changwon_info_disclosure_20260924/2024_mirae/` | 창원시 침수흔적도 제공자료(미래) | 다운로드 파일 `2024년 침수흔적도 1(창원)미래.zip` | 2026-09-24 | `05_침수흔적도 NDMS DB` 압축 해제본; EPSG:5186, L100 18건·L110 12건; 8개 파일, 발생일 2024-07-24·2024-09-21 |
| `flood_traces/changwon_info_disclosure_20260924/2024_ido/` | 창원시 침수흔적도 제공자료(이도) | 다운로드 파일 `2024년 침수흔적도 2(창원)이도.zip` | 2026-09-24 | 5개 구별 SHP 및 CPG·QMD 원본; EPSG:5187, L100·L110 각각 176건; 60개 파일, 발생일 2024-09-20~21 |

### 2026-09-24 추가 침수흔적도

- Downloads의 압축 해제본 3종을 복사했으며, 전체 84개 파일을 제공 ZIP 내용 및 복사 후 SHA-256으로 대조했다. Downloads 원본은 유지했다.
- 2023 자료의 동부·중부원점은 속성과 위치가 동일한 좌표계별 제공본이다. 분석 시 한쪽만 사용해 중복 집계를 방지한다. 파일명에 포함된 `2024` 대신 발생일 속성을 확인한다.
- 이도 자료는 원본 `.cpg`의 인코딩을 사용한다. 의창구 L110의 `F_END_YMD`에는 `024-09-21` 값이 있으며 원본 그대로 보존했다.
- 이번 추가는 원본 보관이며, 분석 파이프라인 입력 변경·재계산은 수행하지 않았다.

## 미보유·제외 데이터

- `창원시 교통량`: 현재 로컬 파일 없음. 폭우·침수 취약성 핵심 변수가 아니므로 현 분석 범위에서 제외한다.
- 별도 하천 SHP: 현재 보유하지 않음. 토지피복지도의 내륙수(`L2_CODE=710`)로 하천 인접도를 근사한다.

## 공개데이터 자동 수집분 (접근신청 #17)

`python -m src.data.fetch_open_data` 로 받았다. sha256 전체는 `open_data_manifest.json`.

| 항목 | 파일 | 크기 | 취득일 |
|---|---|---|---|
| A1 창원 침수예상도 내수침수 50년 | `flood_maps/changwon_wfs/L200_050.geojson` | 86.2 MB | 2026-08-22 |
| A1 창원 침수예상도 내수침수 80년 | `flood_maps/changwon_wfs/L200_080.geojson` | 92.7 MB | 2026-08-22 |
| A1 창원 침수예상도 내수침수 100년 (28,544건) | `flood_maps/changwon_wfs/L200_100.geojson` | 94.7 MB | 2026-08-22 |
| A1 창원 침수예상도 내수침수 200년 | `flood_maps/changwon_wfs/L200_200.geojson` | 101.4 MB | 2026-08-22 |
| A1 창원 침수예상도 복합 30년 | `flood_maps/changwon_wfs/L210_030.geojson` | 35.0 MB | 2026-08-22 |
| A1 창원 침수예상도 복합 50년 | `flood_maps/changwon_wfs/L210_050.geojson` | 36.6 MB | 2026-08-22 |
| A1 창원 침수예상도 복합 80년 | `flood_maps/changwon_wfs/L210_080.geojson` | 37.7 MB | 2026-08-22 |
| A1 창원 침수예상도 복합 100년 (41,130건) | `flood_maps/changwon_wfs/L210_100.geojson` | 38.3 MB | 2026-08-22 |
| A1 창원 침수예상도 외수범람 50년 | `flood_maps/changwon_wfs/L220_050.geojson` | 9.8 MB | 2026-08-22 |
| A1 창원 침수예상도 외수범람 100년 (2,681건) | `flood_maps/changwon_wfs/L220_100.geojson` | 13.5 MB | 2026-08-22 |
| A1 창원 침수예상도 외수범람 150년 | `flood_maps/changwon_wfs/L220_150.geojson` | 19.5 MB | 2026-08-22 |
| A1 창원 침수예상도 외수범람 200년 | `flood_maps/changwon_wfs/L220_200.geojson` | 22.2 MB | 2026-08-22 |
| A1 창원 침수예상도 하천 범람 예상도 (62,430건) | `flood_maps/changwon_wfs/L300.geojson` | 135.2 MB | 2026-08-22 |
| A5 경로당·경찰·소방·병원 포인트 | `shelters/changwon_facility_frequency2.json` | 0.1 MB | 2026-08-22 |
| A5 임시주거시설·학교 포인트 | `shelters/changwon_shelter_frequency1.json` | 0.1 MB | 2026-08-22 |
| A9 환경부 하수도통계 2025 (읍면동·매설연도별 관로) — Layer 2 Plan B 핵심 입력 | `sewer/환경부_하수도통계_2025.xlsx` | 25.6 MB | 2026-08-22 |

### 사용 전 주의

- **A1 침수예상도는 EPSG:5181** 이다. 분석 기준 EPSG:5179 로 재투영해야 한다.
- A1 의 `FEXMP_NM` 컬럼은 WFS 응답에서 cp949 가 latin1 로 잘못 인코딩돼 깨져 있다.
  `value.encode('latin1').decode('cp949')` 로 복원한다 (예: `³»¼öÄ§¼ö ¿¹»óµµ` → `내수침수 예상도`).
- A9 하수도통계는 시트 37개다. 관로 관련은 `2-3. 관종별현황`·`2-5. 맨홀현황`·`3-1. 하수관로 개보수`·`5. 펌프장`.
