# 아직 없는 데이터 — 그래프가 선언한 입력 기준

> 2026-08-22. `python -m src.pipeline` 의 노드가 **실제로 입력으로 선언한 파일** 중
> 존재하지 않는 것만 적는다. 카탈로그에 있으나 어느 노드도 쓰지 않는 자료는 여기 없다.
> 확보 경로와 링크는 `docs/data_acquisition_todo.md`.

## 요약

| 구분 | 건수 | 막는 것 |
|---|---:|---|
| 지금 당장 막는 것 | 2 | P2 완주 (관측지점 좌표, 펌프장 좌표) |
| 정보공개청구 회신을 기다리는 것 | 4 | Layer 2 Plan A, 민원 검증세트, TOP 20 정책카드 |
| 우리가 만들어야 하는 문서 | 2 | Layer 2 설계 결정, 민원 taxonomy |
| 대안이 있는 것 | 1 | Layer 1 검증(AUC) — 없으면 성능 주장 금지 |

---

## 1. 지금 당장 P2 를 막는 것

### `data/external/stations.csv` — 관측지점 좌표
- **막는 노드**: `h03_stations` → `h04_grid_features` → Layer 1 전체
- **필요한 것**: 강수 29지점 + 수위 2지점의 좌표
- **확인 결과**: 창원 공개 API(WFS·포인트)에는 관측소 레이어가 **없다**
- **경로**: ① 시에 직접 청구(정확) ② 행정동 18개는 보유 경계 중심점으로 근사 가능,
  시설명 11개는 지오코딩(V-World/카카오 키 필요)
- **대안 채택 시**: 동 중심점은 실제 우량계 위치가 아니므로 `docs/decisions/` 에 한계 기록 필수

### `data/external/pump_stations_geocoded.csv` — 펌프장 좌표
- **막는 노드**: `h03_pump_stations` → `h04_grid_features`(펌프장 거리 변수)
- **필요한 것**: 배수펌프장 9개 주소 → 좌표 + 사람 검수 플래그
- **원본 주소는 이미 보유**(`경상남도_창원시_배수펌프장 현황_20250801.csv`)
- **경로**: V-World 지오코더 또는 카카오 로컬 API 키 하나만 있으면 즉시 해결

---

## 2. 정보공개청구(#1, 접수 17369500) 회신을 기다리는 것 — 예상 9/2

| 파일 | 막는 노드 | 없으면 |
|---|---|---|
| `data/raw/complaints/*meta*.csv` | 민원 홀드아웃 동결 | 검증세트 분할 불가 |
| `data/raw/complaints/*dev*.csv` | 민원 LLM 구조화 | AI 기여(민원 구조화)가 통째로 빠짐 |
| `data/processed/canonical/complaints_development.parquet` | Layer 2 하수역류 | Plan A 불가 → **Plan B 로 진행 가능** |
| `data/raw/sewer/**/*` (관로 연도·좌표) | Layer 2 하수역류 | Plan A 불가 → **Plan B 로 진행 가능** |

**Layer 2 는 회신 없이도 진행된다.** 환경부 하수도통계 2025
(`data/raw/2025 하수도통계.xlsx`, 창원 관종별 784행·펌프장 173행·맨홀 3행)로
Plan B(인프라 지수)를 만들 수 있다.

---

## 3. 우리가 써야 하는 문서 (남에게 받는 것이 아님)

| 파일 | 막는 노드 | 내용 |
|---|---|---|
| `docs/decisions/001-layer2-design.md` | Layer 2 하수역류 | 회신 상태를 보고 Plan A/B/제외 중 무엇을 택했는지와 근거 |
| `docs/complaint_taxonomy.md` | 민원 LLM 구조화 | 민원 유형 분류 체계 (원문을 본 뒤 확정) |

---

## 4. 대안이 있는 것

### `data/raw/flood_traces/**/*` — 침수흔적도
- **쓰는 노드**: Layer 1 침수취약성 (검증 라벨, **선택 입력**)
- **없으면**: 노드는 돌지만 `label_available=false` 로 기록되고 AUC 검증을 못 한다.
  하네스 규칙상 그 경우 **예측 성능을 주장할 수 없다**
- **경로 3가지**: ① 정보공개청구 #1 의 SHP ② 행안부 API(#8, 회원가입 필요)
  ③ 창원 게시판 PDF 69건(수동 다운로드 — `docs/data_acquisition_todo.md`)

### `data/processed/spatial/evaluation_points.gpkg`
민원 구조화(`h05_complaint_extract`)의 산출물이다. 별도로 구할 것이 아니라
민원 원문을 받으면 자동으로 만들어진다.

---

## 5. 이미 해결된 것 (2026-08-22)

| | 상태 |
|---|---|
| A1 창원 침수예상도 13레이어 (690MB) | ✅ 받음 + EPSG:5181→5179 재투영·한글 복원 완료 (`h03_flood_maps`) |
| A5 대피시설·방재기관 포인트 (960건) | ✅ 받음 |
| A9 환경부 하수도통계 2025 | ✅ 이미 보유 중이었음 (`data/raw/2025 하수도통계.xlsx`) |
| 토지피복 16세트, DEM 6타일, SGIS 27파일+9경계 | ✅ 보유 |
| 강수 173,740행 / 수위 9,598행 / 펌프장 9행 | ✅ 보유·정제 완료 |

## 6. 아직 수동으로 받아야 하는 공개자료

게시판이 JavaScript 로 첨부 링크를 만들어 자동화하지 못했다. 브라우저로 받는다.

| 항목 | 페이지 | 쓰는 곳 |
|---|---|---|
| A2 침수흔적도 PDF 69건 | https://bangjae.changwon.go.kr/portal/bbs/list.do?ptIdx=114&mId=0802000000 | Layer 1 검증 라벨 |
| A3 대피장소 PDF 5개 | https://bangjae.changwon.go.kr/portal/bbs/view.do?mId=0803000000&ptIdx=115&bIdx=560 | Layer 3 적응역량 |
| A7 홍수위험지도 SHP | https://data.floodmap.go.kr/main/board/map_data_download | 결과 대조 (국가 시나리오) |
| A4 자연재해저감계획 | https://council.changwon.go.kr/svc/cmt/CmtBillView.do?cmmtCd=305015&billSn=245555 | 결과 대조 (지정 위험지구 115개소) |

A4 는 카탈로그에 적힌 직접 링크(`flSn=28864`)가 **404** 다. 페이지에서 첨부 번호를 다시 확인해야 한다.
