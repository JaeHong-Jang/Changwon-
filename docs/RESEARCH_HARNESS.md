# 창원 폭우·침수 연구 하네스 운영 명세

> 기준 브랜치/커밋: `main` / `2629d68` (2026-08-19 동기화)
> 목적: 원본 데이터부터 TOP 20 정책 제안과 최종 보고서까지, 누구나 같은 입력으로
> 같은 결과를 재실행하고 실패 지점을 즉시 찾을 수 있게 한다.

## 1. 이번 연구의 확정 범위

핵심 연구 질문은 다음 다섯 가지다.

1. 실제 민원에서 반복되는 침수·역류의 위치·원인·시민요구·행정조치는 무엇인가?
2. 창원시 100m 격자 중 집중호우 때 물리적으로 침수에 취약한 곳은 어디인가?
3. 그중 인구와 고령인구가 집중되어 피해가 커질 가능성이 높은 곳은 어디인가?
4. 예상 피해가 크고 대응역량이 부족한 TOP 20에서 언제·누가·무엇을 해야 하는가?
5. 실제 침수·새 민원·조치결과를 어떻게 다음 분석과 정책에 환류할 것인가?

CDRI는 국제 표준 공식이 아니라 본 연구가 정의한 **창원형 정책 우선순위 지수**다.
침수 이력 또는 민원 라벨이 충분히 확보되기
전에는 이를 확률 예측 모델이라고 부르지 않는다. AI의 필수 역할은 민원 원문 구조화와
조건 충족 시의 비교모델이다. 알림 초안은 일정에 여유가 있을 때만 고정된 결과를 조회하는
선택적 출력이며, 연구의 타당성이나 공식 통제·대피 판단을 대신하지 않는다.

## 2. 2026-08-19 현재 데이터 기준선

아래 수치는 Git LFS 원본을 내려받아 `config/data_contracts.yaml`과
`src/data/validate_raw.py`로 직접 확인한 값이다.

| 데이터 | 실측 상태 | 바로 사용 가능한 부분 | 분석 전 차단 조건 |
|---|---:|---|---|
| 시간별 강수량 | 173,740행, 전체 36지점, 1958-01-27~2025-09-17 | 2015~2024 완전연도에서 일수 90% 이상인 29지점 cohort | 완전중복 2,067행, 키 중복 2,093행, 잘못된 날짜 3행, 1958년 9행, 음수 144셀, 300 초과 1셀의 처리 근거 필요 |
| 하천수위 | 9,598행, 지역코드 8개 | 차룡8교는 2015~2024 행 존재 일수 92.3%이나, 센티널 제외 후 유효일 커버리지는 85.6%; 연덕교는 2024-10 시작 | 90% 유효일 기준을 충족한 지점 0개. 나머지 6개는 2007~2010 전부 0이며 센티널·광범위 물리범위 밖 후보를 격리. 도시 전체 공간 검증자료로 사용 금지 |
| 배수펌프장 | 9행 | 명칭·주소·설치연도·설비 설명 | 주소 지오코딩과 위치 검수 전 거리 변수 생성 금지 |
| 하천 메타데이터 | 53행 | 하천명·시종점 주소·길이 | 위·경도 전부 결측이므로 공간선형 자료로 사용 금지 |
| SGIS 100m 통계 | 12파일, 1,224,893행 | 총인구·성별인구·총가구·총주택 | CSV에 헤더가 없으므로 반드시 `header=None`과 4개 계약 컬럼 사용 |
| SGIS 집계구 통계 | 15파일, 121,374행 | 성·연령별 인구·총인구·노령화지수 | 연령 코드북 확정 전 65세 이상 파생 금지; 1인가구 자료는 현재 없음 |
| SGIS 경계 | 집계구 5세트, 100m 격자 4세트 | 폴리곤·조인키, EPSG:5179 | 전국 도엽을 창원 행정경계로 clip할 별도 전체 경계 필요 |
| 토지피복도 | 16세트, EPSG:5186 | `L2_CODE`, `L2_NAME`, 내륙수·시가화 후보 | 분류 코드북 확정 후 불투수 분류; EPSG:5179로 재투영 |
| DEM | HFA 6개, 각 596,749 bytes, EPSG:5179, 90m, NoData -9999 | 경사·상대고도 후보 | 실행 환경마다 `rasterio`로 동일 메타데이터 재검증; 100m 격자 정렬 규칙 필요 |

이 기준선은 기존 계획의 “강수 약 50지점·191,340행”, “수위 50지점”, “DEM 5m”
가정을 각각 실제 36지점·173,740행, 8지점·9,598행, 90m로 대체한다. 특히 현재
100m 자료에는 1인가구와 연령별 인구가 없으므로,
집계구 고령인구를 100m 격자에 배분할 때 별도의 불확실성 표기가 필요하다.

## 3. 하네스의 단일 진실 원천

| 대상 | 원천 파일 | 역할 |
|---|---|---|
| 연구 질문·방법·일정 | `docs/RESEARCH_PLAN.md` | 무엇을 왜 분석하는지 |
| 단계별 실행·중단 규칙 | 이 문서 | 언제 진행하고 언제 멈추는지 |
| 분석기간·공간 기준 | `config/config.yaml` | 2015~2024, coverage 90%, IDW 24지점, EPSG:5179·100m |
| 원본 스키마·품질 한계 | `config/data_contracts.yaml` | 입력이 어떤 조건을 만족해야 하는지 |
| 원본 warning 한시 승인 | `config/raw_quality_waivers.yaml` | finding fingerprint·승인자·정제규칙·만료일 |
| 원본 검증 실행 | `src/data/validate_raw.py` | 계약 판정과 checksum 증거 생성 |
| 분석 분기 결정 | `docs/decisions/NNN-*.md` | 데이터 부족 때 선택한 대안과 영향 |
| 실행 증거 | `artifacts/validation/`, `artifacts/runs/<run_id>/` | 설정·로그·지표·checksum |
| 제출용 확정 산출물 | `reports/` | 표·지도·최종 보고서 |

원본은 수정하지 않는다. 오류 행은 `data/processed/quarantine/`에 원본 행 번호와
사유를 남기고, 정제된 표에는 `source_file`, `source_row`, `cleaning_rule`을 보존한다.

## 4. 실행 구조

현재 저장소에 **실행 구현이 끝난 범위는 H00~H01**이다. H02~H10은 이 문서에
입·출력 계약과 통과 기준을 고정했으며, 각 단계의 변환 코드와 run orchestrator는
해당 스토리에서 순차 구현한다. 따라서 아직 생성되지 않은 산출물을 완료된 것처럼
checkpoint하지 않는다.

```text
H00 동기화/LFS
  └─ H01 구조 계약 + warning fingerprint 승인 ── fail ──▶ 중단
         │ pass (raw를 정상값으로 인정한 것이 아니라 H02 정제로 이관)
         ▼
H02 시간·통계 정규화 ─▶ H03 공간기반 구축 ─▶ H04 피처 생성
                                                │
                                                ▼
H05 검증세트 동결 ─▶ H06 Layer 1~3 ─▶ H07 CDRI·민감도
                                                │
                                                ▼
H08 TOP 20 정책화 ─▶ H09 선택적 알림 출력 ─▶ H10 최종 재현성 검증
```

H02 실행기부터 각 실행은 `run_id = UTC시각 + Git short SHA + config SHA 앞 8자리`로 식별한다.
완료 증거에는 최소한 Git commit, dirty worktree 여부와 diff hash, 계약/config checksum,
입력 checksum, 실행 명령, Python·OS·패키지 lock hash, 종료 코드, 핵심 지표, 출력 checksum을
기록한다. 노트북은 탐색과 설명에만 쓰고,
최종 표·지도 생성 로직은 `src/` 함수로 승격한다.

## 5. 단계별 게이트

| Gate | 입력과 실행 | 필수 산출물 | 통과 기준 | 실패 시 행동 |
|---|---|---|---|---|
| H00 동기화 | `git pull --ff-only`, `git lfs pull`, `git lfs fsck` | 현재 commit·LFS 상태 | 포인터 0개, LFS 무결성 통과, worktree에 원본 존재 | LFS 설치/재다운로드 후 재검사 |
| H01 원본 계약 | 구조 검사 + `config/raw_quality_waivers.yaml` 적용 | `artifacts/validation/raw_validation.json` | error 0, 승인되지 않은 warning 0, waiver schema 유효·fingerprint 일치·미만료 | warning별 owner·사유·H02 규칙·만료일 작성; 임계치 완화 금지 |
| H02 정규화 | 강수·수위 wide→long, SGIS 4컬럼 부여, 별도 processed strict validator | `data/processed/canonical/rainfall_hourly.parquet`, `data/processed/canonical/river_level_hourly.parquet`, `data/processed/canonical/sgis_*.parquet`, `data/processed/quarantine/` 품질표 | 키 유일, 날짜 유효, 센티널 0, 행수 보존식 일치, 2015~2024 강수 29지점 coverage 유지 | 원본 행 단위 격리; 임의 0 대체 금지 |
| H03 공간기반 | 행정경계·SGIS 격자 clip, CRS 통일 | `data/processed/spatial/grid_base.gpkg`, `data/processed/spatial/stations.gpkg`, `data/processed/spatial/pump_stations.gpkg` | 전 레이어 EPSG:5179, geometry valid 100%, 분석 격자 창원 내부 | 좌표 확보율 미달이면 공간보간 중단 |
| H04 피처 | DEM·토지피복·하천·펌프·인구 결합 | `data/processed/features/grid_features.parquet`, `docs/data_dictionary.md` | 변수별 출처·방향·단위 존재, 핵심 결측 <5%, 누수 점검 | 결측 5% 초과 변수 제외/대체 근거 기록 |
| H05 민원 위험지식·검증세트 | 원문 접근 전에 메타데이터만으로 개발/최종 홀드아웃을 분리하고 checksum 동결. 개발 원문만 LLM 구조화한 뒤 추출기 코드·프롬프트·모델·taxonomy 동결 | `complaints_development.parquet`, `complaint_taxonomy.md`, `complaint_extractor_manifest.json`, `evaluation_points.gpkg`, `holdout_manifest.json`, `evaluation_protocol.md` | 개발세트에 근거문장·신뢰도·표본정확도·사람검수율·공간오차 명시, 최종 홀드아웃 원문 접근 0회, 분할·추출기 checksum 고정 | 분할 또는 추출오류 수정; 라벨 부족 시 예측 성능 주장 금지 |
| H06 레이어·호우 시나리오 | 정적 baseline 우선, 조건 충족 시 ML challenger. 과거 지점관측은 IDW, 동적 입력은 기상청 단기예보 5km 격자 PCP로 분리 | 정적 `layer1_flood.gpkg`·`layer2_sewer.gpkg`·`layer3_vuln.gpkg`, `artifacts/scenarios/<scenario_id>/forecast_manifest.json`, `scenario_risk.gpkg` | 정적 baseline 항상 산출. PCP는 1~48시간 lead의 시간별 값만 허용; 6h/24h 누적·최대시간강수 산출. 숫자 mm와 `강수없음=0`만 primary 점수에 사용하고, 범주는 하·상한 민감도만, 상한 없는 범주는 정밀 TOP N 중단. 전 시각은 timezone-aware ISO-8601이며 원천/저장 timezone·UTC↔KST 변환, 상품·원해상도·공간 support·부모격자 매핑·checksum·최대경과시간을 기록. 과거 발표예보가 없으면 조건부 시나리오로만 명명 | 누락·노후·단위/lead/timezone 불일치에는 `시나리오 사용 불가`; 조건 미달 시 규칙기반 지수로 명명 |
| H07 통합 | 개발세트 내부에서 equal/entropy·곱셈/가중합 primary 산식 선택과 입력 오차 시나리오 수행. Capacity는 높을수록 좋게 정규화하고 `capacity_deficit=1-capacity_norm`으로 변환 | `data/processed/layers/cdri.gpkg`, `reports/tables/sensitivity.csv`, primary 산식 manifest | **강건성**: 중위 Spearman ρ≥0.8, TOP20 중첩≥70%; `capacity_deficit_contribution` 출력. Capacity 결측은 0 대체 없이 제외·재가중하고 신뢰등급 하향. 최종 홀드아웃 접근 0건 | 정밀 순위 대신 위험군(tier)으로 보고 |
| H08 정책화·최종평가 | 개발 결과로 위험도·기여도·관할·민원 근거·공식 행정수단을 결합하고 지수식·가중치·TOP 20·추출기를 고정한 뒤 최종 민원 원문 1회 평가 | `top20.csv`, `policy_cards/`, `artifacts/evaluation/final_holdout_evaluation.json` | 격자마다 트리거·시간·근거 3개·신뢰등급·담당·조치·자원/비용·KPI·사람 승인 지점. 평가 파일에 primary manifest SHA·extractor SHA·최초 접근시각·평가횟수 1·지표·`retuning_prohibited=true`. `24시간 전·6시간 전` 등은 공식 SOP 확인 전 시범 시나리오로 표시 | 행동 트리거·실행 주체 없는 항목은 최종 TOP20 제외; 평가 후 공식·가중치 재조정 금지 |
| H09 선택적 알림 출력 | G010 완료·일정 여유 시 유효한 예보와 고정 TOP 20·정책카탈로그로 내부 검토용 문안 1건 생성 | 실행 로그·assertion·화면 1장·소요시간 또는 `skipped: 일정` 증거 | 계산값 일치 100%, 만료·누락·단위/timezone 불일치 예보 차단, 자동발송 0건. Streamlit·시민 챗봇·대피경로·자동대피 없음 | 실패하거나 일정이 부족하면 텍스트 예시로 축소하고 핵심 분석 일정은 유지 |
| H10 재현성·환류 | 빈 processed 환경에서 전체 재실행하고 새 민원·침수·조치결과의 버전별 환류 검증 | run manifest, `feedback_manifest.json`, 최종 PDF, 표·지도 checksum | 테스트·노트북·보고서 체크 전부 통과. feedback manifest 필수키·checksum·version 증가와 다음 모델 버전 전환을 검사하고, 기존 홀드아웃 결과 checksum은 불변 | 마지막 성공 run으로 복귀, 실패 원인 기록 |

## 6. 데이터별 정제 계약

### 6-1. 강수량

1. `지역코드 + 년월일`과 24개 시각 컬럼을 long 형식의
   `station_id, observed_at, rainfall_mm`로 변환한다.
2. `2022-02-29/30/31` 세 행과 현대 관측망에서 고립된 1958년 9행은 자동 보정하지 않고 quarantine한다.
3. 완전중복 2,067행은 원본 행 번호를 기록한 뒤 한 건만 유지한다.
4. 완전중복을 제외하고 남는 지점-일자 충돌은 26개 추가 중복 행 수준이다.
   셀별 값이 같은지 비교하고, 다르면 공급기관 코드북 또는 최신 수정본 없이는 선택하지 않는다.
5. 음수 144셀과 300mm 초과 1셀은 0으로 치환하지 않는다. 별도 품질 플래그를 두고
   코드북 확인 전 이벤트 분석에서 제외한다.
6. 주 분석기간은 완전연도 2015-01-01~2024-12-31로 고정하고, 일수 커버리지 90% 이상인
   29지점을 기본 cohort로 쓴다. 각 IDW 이벤트는 이 cohort 중 좌표·정상값이 있는 지점이
   80%(24개) 미만이면 생성하지 않는다. 2025년은 불완전연도이므로 본 지수 climatology에서 제외한다.
7. 학습·검증 분리는 행 랜덤 분할이 아니라 **호우 이벤트/연도 단위 시간 분할**로 한다.

### 6-2. 하천수위

1. 강수와 동일한 long 형식으로 변환한다.
2. `-47999`, `-8383`, `9321`, `9999`는 센티널 후보로 분리한다.
3. 단위·코드북을 확보하기 전에는 보수적인 후보범위 `-100~1000` 밖의 18셀
   (`-35760` 14셀, `-300` 1셀, `1990`·`2100`·`3219` 각 1셀)도 quarantine한다.
   이 범위는 정상값 확정선이 아니라 명백한 극단값을 분석에서 차단하는 임시 안전선이다.
4. 코드북 확인 전 센티널·범위 밖 후보를 실제 수위로 사용하지 않으며, 결측 전환 시 원값과 규칙을 보존한다.
5. 행 존재만 세면 차룡8교의 2015~2024 커버리지는 92.3%지만, 하루 24셀 중
   센티널 제외 유효값이 하나 이상인 날짜는 3,128/3,653일(85.6%)이다. 90% 기준을
   충족한 수위 지점은 0개다. 연덕교는 2024-10 이후 사례 분석에만 쓰고,
   나머지 6개 0-only 코드는 코드북 전 제외한다.
6. 따라서 수위는 특정 호우의 시간 반응을 확인하는 보조 사례이며 창원 전역 공간 타당성
   또는 음성 라벨로 사용하지 않는다.

### 6-3. SGIS

1. 모든 통계 CSV는 헤더가 없으므로 `year, spatial_id, variable, value`를 명시한다.
2. 100m 격자 자료는 총인구/남/여, 총가구, 총주택까지만 현재 확인됐다.
3. 65세 이상 인구는 집계구 연령 코드북을 확정한 뒤 계산하고, 집계구→100m 배분은
   거주인구 비례 방식과 균등배분 방식을 모두 돌려 순위 민감도를 보고한다.
4. 1인가구는 현재 미보유다. 추가 확보하지 못하면 Layer 3 수식에서 제외하고 결측을
   0으로 간주하지 않는다.
5. SGIS의 비밀보호 처리값 가능성을 확인하고, 작은 값의 합계가 실제 총인구와 다를 수
   있음을 불확실성에 반영한다.

### 6-4. 공간자료

1. 기준 CRS는 EPSG:5179다. 토지피복도 EPSG:5186만 재투영한다.
2. 100m 전국 도엽은 창원 전체 행정경계로 먼저 clip한 뒤 통계를 결합한다.
3. DEM은 검증된 90m 원본을 EPSG:5179 100m 분석 격자에 맞춘 뒤 mosaic/resample하며,
   기준점·resampling 방식·NoData 보존 여부를 run manifest에 기록한다.
4. 하천 CSV는 위치 좌표가 없으므로 하천선 대체 자료가 아니다. 토지피복 `L2_CODE=710`
   사용은 물 영역 proxy라는 한계를 명시한다.
5. 펌프장은 자동 지오코딩 뒤 수동 지도 검수를 거치며, 주소 정확도 등급을 보존한다.

## 7. 분석·검증 설계

### Baseline과 challenger

- Layer 1 baseline: 방향을 사전 고정한 지표의 robust scaling + 동일가중 합산.
- Layer 1 challenger: 충분한 침수 라벨이 있을 때만 로지스틱/XGBoost를 비교한다.
- Layer 2 Plan A: 관로 좌표·연도·재질과 날짜·위치가 확인된 양·음성 역류/침수 라벨이 여러 호우에 충분할 때만 ML. 민원 부재를 음성으로 만들지 않는다.
- Layer 2 Plan B: 동 단위 관로 집계가 있으면 합류식비율·관로밀도·저지대만으로
  **역류 우선점검 지수**를 만든다. 민원은 입력에서 제외하고 개발세트 내부검증과 H08의
  최종 1회 평가에만 사용한다.
  관로 집계도 없으면 Layer 2 점수를 만들지 않고 CDRI 제외 민감도만 보고한다.
- Layer 3: 총인구·건물 노출, 고령·지하층·노후건물 취약성, 대피소·긴급대응·단순 펌프거리 대응역량을 구분한다. 펌프 용량·서비스권역을 Layer 1 배수능력으로 채택하면 대응역량에서는 제외한다. 대응역량은 높을수록 좋은 방향으로 정규화한 뒤 `capacity_deficit = 1 - capacity_norm`으로 바꾸어 우선순위에 사용한다.
- CDRI: Hazard·Exposure·Vulnerability·Capacity 부족도의 곱셈형과 가중합형을 baseline/challenger로 비교한다. Layer 2 또는 Capacity 변수가 없으면 0을 대입하지 않고 해당 항목을 제외해 남은 가중치를 재정규화하며 신뢰등급을 낮춘다.

### 검증 규칙

- 양성 라벨만 있을 때 AUC를 보고하지 않는다. `상위 10/20% 포함률`과 무작위 배치 대비
  lift를 쓴다.
- 양·음성 라벨이 충분하면 공간 block CV 또는 연도별 forward validation을 사용한다.
- 동일 호우 이벤트의 관측을 train/test 양쪽에 나누지 않는다.
- 민원·침수 라벨은 원문 또는 LLM 결과를 보기 전에 메타데이터만으로 개발/최종 홀드아웃을
  나누고 checksum을 고정한다. 개발 원문만으로 EDA·taxonomy·추출기를 확정하고, 최종
  홀드아웃 원문은 지수식·가중치·TOP 20·추출기를 고정한 뒤 한 번만 연다. 동일 데이터를
  입력과 평가에 동시에 쓰지 않는다.
- 선행연구 사례지는 독립 성능검증이 아니라 face-validity 점검으로만 보고한다.
- 모델 채택 기준은 baseline 대비 지표 개선뿐 아니라, 구별 편향과 순위 안정성을 포함한다.
- 외부 검증점의 위치 오차가 100m보다 크면 단일 격자 적중 대신 300m buffer 적중을 함께 보고한다.

### 최종 TOP 20 스키마

`rank, grid_id, district, neighborhood, cdri, risk_tier, hazard_contribution,
exposure_contribution, vulnerability_contribution, capacity_deficit_contribution,
confidence_grade, trigger, action_timing, recommended_action, owner_department,
required_resource, cost_band, kpi, human_approval_required, forecast_issued_at,
forecast_valid_to, evidence_run_id`

신뢰등급은 A(직접 관측+검증), B(proxy+교차검증), C(배분/지오코딩 의존)로 구분한다.
정책 카드는 “왜 위험한가 → 어떤 조건에서 언제 움직일까 → 무엇을 누가 할까 → 어떻게
성과를 잴까 → 누가 최종 승인할까”를 반드시 포함한다. 공식 SOP 확인 전 시간기준은
운영규칙이 아니라 공모전 시범 시나리오로 표시한다.

## 8. 즉시 실행 순서

### 8월 19일

- H01 보고서와 fingerprint waiver 8건을 고정하고 강수/수위 이상치 원행을 quarantine 목록으로 만든다.
- SGIS 변수 코드북, 강수·수위 오류 코드북, DEM 메타데이터를 확보한다.
- 창원 전체 행정경계와 관측지점 좌표의 확보 경로를 확정한다.

### 8월 20일

- headerless SGIS 로더와 강수·수위 long 변환을 구현한다.
- 원본→정제 행수 보존식과 키 유일성 테스트를 추가한다.
- 배수펌프장 9개 주소를 지오코딩하고 수동 검수한다.
- 민원 원문 열람 전에 메타데이터만으로 개발/최종 기간을 분리·checksum 동결한다. 이후 개발
  원문만으로 LLM taxonomy와 구조화 스키마를 확정하고 추출기 manifest를 고정한다.

### 8월 21~22일

- EPSG:5179 창원 분석 격자를 만들고 DEM/토지피복/인구 결합 smoke test를 수행한다.
- 결측률·공간 커버리지·조인 성공률 표를 제출해 H03을 닫는다.
- 정보공개청구 회신 상태에 따라 Layer 2 Plan A/B 결정을 기록한다.

## 9. 실행 명령

```bash
# 1) 실제 LFS 원본과 구조만 확인
git lfs pull
git lfs fsck
python3 -m src.data.validate_raw --fail-on error

# 2) 분석 투입 전 엄격 게이트: raw warning은 fingerprint waiver로 H02에 이관
# rasterio·pyproj가 설치된 프로젝트 가상환경에서 실행
python3 -m src.data.validate_raw --fail-on warning

# 3) 검증기 회귀 테스트
python3 -m unittest discover -s tests -v
```

H01 통과는 raw 이상값이 해결됐다는 뜻이 아니다. 현재 raw warning은
`config/raw_quality_waivers.yaml`의 정확한 fingerprint·dataset·code·owner·reason·정제 규칙·만료일이 모두 있고,
중복 fingerprint가 없으며 날짜가 유효할 때만
H02로 이관된다. H01 JSON은 contract·validator·waiver SHA-256과 Git commit,
dirty 여부·tracked diff 및 untracked 내용 hash를 함께 기록해 실행 당시 코드에 결속한다.
H02 완료에는 waiver가 아니라 정제 데이터의 별도 strict 검증 통과가 필요하다.
