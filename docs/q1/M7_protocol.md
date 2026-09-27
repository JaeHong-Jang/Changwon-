# M7 절차 — 원고 재구성 (초고 작성 전 고정)

> 과제 정의: `docs/CLOUD_TASKS.md` M7. 규칙: `AGENTS.md` §2·§8.
> 이 문서는 **주장 위계·금지 표현·인용 규칙·수치 출처 규칙·검토 기준을 초고 작성 전에 고정**하려고 커밋한다.
> 이 커밋 전에는 `docs/paper/` 에 아무 파일도 쓰지 않았다.

## 0. 지위

- 글쓰기 과제다. **새 분석을 하지 않는다.** 홀드아웃 원본과 그것을 읽는 코드는 실행하지 않는다.
- 원고의 모든 수치는 이미 저장된 공식 실행 산출에서 가져온다. 산출 파일을 읽어 값을 대조하는 일회성 확인만 한다 (저장소 밖 scratchpad).
- 근거 문서: `docs/q1/M1.md`, `M2.md`, `M3.md`, `M4.md`, `M4S.md`, `M6.md`, `M6_chronology.md`, `docs/METHODOLOGY.md` §3·§7.6,
  `docs/FORECAST_RESULTS.md`, `docs/research_reports/Q1_review.md`·`Q1_literature.md`·`Q1_verify.md`.
- 2026-09-27 사용자 지시: 중심 주장은 사전 고정 L1 게이트 탈락의 강건성(32 설정)과 격자 AUC 분해식(M4)·그 일반성(M4S).
  C-b 는 폐기. M5 는 생략. CDRI·예보는 부록.

## 1. 주장 위계

| 등급 | 주장 | 근거 run | 원고 위치 |
|---|---|---|---|
| 중심 1 | 동결 지수 L1 은 사후 확보 사상(2022~2024)에서 사전 게이트(격자 AUC ≥ 0.70, 상위 20% 포착 ≥ 0.50)를 탈락했다 (0.436 / 0.073) | `holdout_20260924T100939Z_ae9c122-dirty_cf388a23` (재실행 `holdout_20260926T164805Z_7f7968f_84ef30a7`) | 결과 4.1 |
| 중심 1′ | 합동 홀드아웃 게이트 탈락은 라벨 규칙 8 × 격자 4 = 32 설정 모두에서 유지된다. 사상별 중앙값 게이트(V2)는 참조 설정에서 통과한다는 것도 같이 쓴다 | `m4_20260926T170511Z_1edf87c` | 결과 4.1 |
| 중심 2 | 격자 AUC 는 객체 기여의 가중평균이다 (정확한 항등식). 격자–객체 차이는 크기 가중·객체 안·소실 세 항으로 나뉘고, 크기 가중 항은 공분산 형태를 가진다 | M4 (항등식), M4S (공분산 형태·Δ\*) | 방법 3.4, 결과 4.2 |
| 중심 3 | 0.1 이상의 격자–객체 차이는 크기 분산과 크기–탐지 결합이 함께 있을 때 생기며 Δ\* 로 방향·크기가 예측된다 (가상 자료 115 시나리오, 사전 판정 "일반성 지지") | `m4s_20260926T175809Z_3e8bc1c` | 결과 4.3 |
| 보조 | 자명 기준선(경사·HAND·TWI)이 학습 모델과 격자 AUC 로 구분되지 않는다 → C-b 폐기 | `m1_20260926T160821Z_a181f6c`, `m2_20260926T165115Z_1ffdde7`, `m3_20260926T164916Z_f383cb3` | 결과 4.4 |
| 보조 | 유효 표본은 사상이다. 홀드아웃 격자 AUC 는 k = 2 이고 한 사상이 양성 격자 1,254/1,272 를 차지한다 | M2 | 결과 4.4, 논의 |
| 보조 | 강수 기후 축은 역방향으로 순위를 매긴다 (현상 기술만, 원인 미확정) | 홀드아웃 run 의 `gates`·`development_gates` `z_exposure` | 결과 4.5 |
| 보조 | 재현성: 게이트 해시 동일 재실행, 사전 규칙상 불일치(1.8e-12), 동결 연대표 | M6 | 방법 3.6, 부록 |
| 부록 | CDRI (H·E·V·D) 의 거주 격자 결과 | `posthoc_h_20260926T134611Z_3d14fc1` | 부록 B |
| 부록 | 예보 조건부 예측: 주 판정 1·2 미충족 | `docs/FORECAST_RESULTS.md` 의 run 4개 | 부록 C |
| 폐기 | C-b (지형 학습 모델 우위) | M1 사전 판정 | 결과 4.4 에 폐기 사실만 |
| 생략 | M5 다도시 재현 | — | 한계에 "재현을 주장하지 않는다" |

## 2. 금지 표현 (`docs/research_reports/Q1_review.md` §5 + 과제 보고서의 리더 판단)

원고(영문·한국어)에서 **주장으로** 쓰지 않는다. 부정문("~이 아니다")으로 지위를 밝히는 문장은 허용하되, 검토 보고서에 그 위치를 모두 적는다.

| 한국어 | 영문 점검 문자열 (대소문자 무시) |
|---|---|
| 전향적·사전등록 검증 | `prospective`, `pre-registered`, `preregistered` |
| RF 가 (게이트를 통과해) 검증됐다 | `RF was validated`, `validated random forest`, `model is validated` |
| 10사상·20년 일관 | `consistent across (all )?(ten|10) events`, `20 years`, `two decades` |
| ML 이 지침형 지수보다 우월 | `outperform`, `superior` |
| 지침형 지수 일반이 역전 | `guideline indices (are|were) inverted`, `guideline-based indices fail` |
| 강수 역전 원인 확정 | `caused by`, `because of orographic`, `confirms that rainfall` |
| CDRI 가 우선순위를 식별 | `CDRI identifies`, `identifies priorit` |
| 예보가 침수 예측을 개선 | `forecasts? improve` |
| 도심 침수 88% 소실 (홀드아웃 57개 한정 없이) | `88 ?%` |
| 위치 모형이 거주 지역에서 잘 맞힘 | `performs well in (populated|residential)` |
| 평가 설계가 판정을 뒤집는다 (M4 리더 판단 1: 결과로는 약함) | `reverses? the verdict`, `overturn` |
| 홀드아웃 AUC 를 단일 통합값으로 (M2 리더 판단 1) | `holdout AUC of 0.8` |
| 객체 AUC 에서 RF 가 경사보다 높다 (M2 R4) | 문장 점검 |
| `rep_point` 를 편향 없는 대안으로 (M4S 리더 판단 2) | `unbiased` |
| 검증 단위가 AUC 를 바꾼다는 최초 발견 (PAPER_ROADMAP §1) | `first to show`, `for the first time`, `novel finding` |
| 미기록 침수 때문에 AUC 는 하한 (PAPER_ROADMAP §1) | `lower bound` |

- 확정적 기술어는 근거가 있을 때만 쓴다: "validated", "robust"(32 설정 탈락 유지에만), "general"(가상 시연 판정 문구 범위에서만).
- 2022~2024 로 채점한 새 설계는 모두 **post-hoc** 으로 표기한다 (M1~M4, M4S 기준점, M3).
- 홀드아웃 평가의 지위는 "evaluation of a pre-frozen index on independent events obtained after freezing" 로 쓴다
  (METHODOLOGY §7.6 "사전 동결 지수의 사후 확보 독립 사상 평가"). 사상 자체는 지수 설계 전에 일어났다는 점을 같이 쓴다.

## 3. 인용 규칙

- `docs/research_reports/doi_check.tsv` 에서 상태 200 인 DOI 만 인용한다.
- 서지(저자·제목·권호)는 (a) 저장소 문서에 적힌 것, 또는 (b) 이번 세션에서 웹 검색으로 출판사·색인 페이지를 확인한 것만 쓴다.
  확인 못 한 칸은 비워 두고 `[미확인]` 표시한다. 기억으로 채우지 않는다.
- 새 문헌: 과제 정의는 Crossref 확인을 요구한다. 이 세션에서 `api.crossref.org`·`doi.org` 는 네트워크 정책으로 막혀 있다 (403, 착수 시 확인).
  그래서 새 문헌은 참고문헌에 넣지 않는다. 방법 인용이 꼭 필요한 곳(예: 무작위효과 통합의 HKSJ 보정, Priority-Flood)은
  본문에 `[미확인: 저자 연도]` 로 남기고 보고서에 목록을 적는다.
- 인용 문장은 해당 문헌이 실제로 다루는 범위로 쓴다 (예: Ozturk 2021 은 산사태, Nobre 2011 은 도시 내수 검증이 아님).

## 4. 수치 출처 규칙

- 원고의 모든 수치는 `docs/paper/numbers_provenance.md` 에 (원고 위치, 값, run_id, 파일·키) 로 적는다.
- 표 주석에 run_id 를 적는다. 본문 수치는 표에 있는 값이거나 출처 표에 있는 값이다.
- 반올림은 근거 보고서와 같게 소수 셋째 자리까지 쓴다 (M4S 항등식 오차 등 과학 표기는 그대로).
- 근거 보고서끼리 값이 다르면(예: 사상 집합 차이로 경사 중앙값 0.872 대 0.885) 사상 집합을 명시해 구분한다. 한쪽을 고르지 않는다.
- 불리한 결과를 같이 싣는다: V2 참조 통과, 짝 차이 중앙값이 RF 쪽(+0.030), 평지·시가지 층의 약한 AUC, M6 사전 규칙상 불일치,
  M3 보조 비교(모델군 선택 −0.032), M4S S3 틀림.

## 5. 산출

| 파일 | 내용 |
|---|---|
| `docs/paper/README.md` | 폴더 안내, 파일 목록, 원고 지위 |
| `docs/paper/structure.md` | NHESS 형식 구성: 절별 목적·근거·그림·표 계획, 투고 요건 점검 |
| `docs/paper/manuscript_en.md` | 영문 초고 (NHESS: 제목·초록·짧은 요약·본문 6절·코드와 자료·기여·이해상충·참고문헌·부록) |
| `docs/paper/summary_ko.md` | 한국어 요약본 |
| `docs/paper/references.md` | 참고문헌 목록 (DOI, 서지 출처 표시) |
| `docs/paper/numbers_provenance.md` | 수치 출처 표 |
| `docs/q1/M7.md` | 과제 보고 (§4 형식) |
| `docs/q1/M7_review.md` | 교차 리뷰 원문과 조치 |

그림은 새로 그리지 않는다. 기존 산출 그림(`artifacts/q1/M4S/m4s_20260926T175809Z_3e8bc1c/gap_map_redrawn.png`,
`artifacts/q1/M2/m2_20260926T165115Z_1ffdde7/forest_grid_auc.png`)을 경로로 참조하고, 나머지 그림은 자료 출처를 적은 계획으로 둔다.

## 6. 검토 기준 (다른 모델 서브 에이전트, 읽기 전용)

검토자는 구현(이 세션)과 다른 모델의 Claude 서브 에이전트다. 홀드아웃 원본과 그것을 읽는 코드를 쓰지 않는다. 저장된 산출 파일은 읽어도 된다.

1. **수치:** 원고의 수치를 표본 추출이 아니라 표 단위로 산출 파일과 대조한다 (최소: 모든 표, 초록의 모든 수치).
2. **금지 표현:** §2 점검 문자열을 전수 검색하고, 걸린 문장이 부정문인지 확인한다.
3. **인용:** 참고문헌의 모든 DOI 가 `doi_check.tsv` 상태 200 인지, 본문 인용과 참고문헌 목록이 일대일인지.
4. **과잉 주장:** §1 위계를 넘는 문장 (예: 단일 도시 결과의 일반화, post-hoc 표기 누락, 사상 1개 지배를 숨긴 문장).
5. **일관성:** 영문 초고와 한국어 요약의 수치·주장이 같은지.

판정: PASS / PASS-with-fixes / FAIL. 수정은 리더가 하고, 수정 후 같은 검토자가 수정 부분을 다시 본다.
