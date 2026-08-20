# data/processed — 전처리 데이터

전처리가 완료된 분석용 데이터를 이 폴더에 저장합니다.

## 규칙
- 재실행 가능한 변환 로직은 `src/`에 두고, `notebooks/03_preprocessing.ipynb`는 결과 설명과 smoke 실행에 사용합니다.
- 원본 오류 행은 `quarantine/`에 `source_file`, `source_row`, `reason`, `rule_id`와 함께 보존합니다.
- 분석 표는 가능하면 Parquet, 공간 레이어는 GeoPackage를 사용합니다.
- 산출물마다 생성한 `run_id`, 입력 checksum, 코드 commit을 아래 표와 run manifest에 기록합니다.

## 단계별 디렉터리

| 디렉터리 | 내용 |
|---|---|
| `quarantine/` | 원본 이상치·중복 충돌·날짜 오류와 제외 사유 |
| `canonical/` | 강수·수위 long 형식, SGIS 4컬럼 정규화 |
| `spatial/` | EPSG:5179로 통일한 격자·관측소·펌프장 |
| `features/` | 100m 격자별 지형·피복·인구·접근성 변수 |
| `layers/` | Layer 1~3와 최종 CDRI |

## 정규 산출물 경로 계약

| Gate | 정규 경로 |
|---|---|
| H02 | `canonical/rainfall_hourly.parquet`, `canonical/river_level_hourly.parquet`, `canonical/sgis_*.parquet`, `quarantine/` |
| H03 | `spatial/grid_base.gpkg`, `spatial/stations.gpkg`, `spatial/pump_stations.gpkg` |
| H04 | `features/grid_features.parquet` |
| H06~H07 | `layers/layer1_flood.gpkg`, `layers/layer2_sewer.gpkg`, `layers/layer3_vuln.gpkg`, `layers/cdri.gpkg` |

## 데이터 목록

| 파일명 | 원본/입력 | 변환 규칙 | run_id | 생성일 |
|--------|-----------|-----------|--------|--------|
| 아직 없음 | | | | |
