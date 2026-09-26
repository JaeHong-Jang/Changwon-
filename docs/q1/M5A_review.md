# M5 단계 A 독립 검토 (읽기 전용)

판정: PASS-with-fixes

> 검토자: Claude Sonnet 서브 에이전트. 구현(리더, Claude Opus)과 다른 모델이다 (AGENTS.md §1·§8).
> 대상: 초안 `docs/q1/M5_protocol.md` (커밋 `365bcc2`).
> 다음 파일은 열지 않았다:
> - `artifacts/posthoc/20260926/api_scan_summary.json`
> - `.omc/api_scan*`
> - 홀드아웃 원본 `data/raw/flood_traces/changwon_info_disclosure_20260924/**`
> 네트워크 접속과 파일 쓰기는 하지 않았다. 아래는 검토자 보고를 리더가 옮긴 것이다.

## 확인한 것

- 전독한 문서:
  - `M5_protocol.md`
  - `CLOUD_TASKS.md` M5 절
  - `M1_protocol.md`, `M1.md`
  - `Q1_review.md` §1·§2·§5
- 코드와 절차 서술을 대조했다:
  - `features.py`: `dem_to_lattice`·`slope_deg`·`relative_elevation`·`twi`·`_block_mean`·`distance_to`·`Lattice.refined`
  - `hand.py`
  - `trace_events.py`: `_parse_dates`·`_storm_ids`, `F_YR` 의존
  - `flood_traces._drop_duplicate_geometries`, `trace_labels.label_grid`
  - `validation/evaluate.py` 전문
  - `layers.py`: `composite`·`winsorize`·`zscore`·`top_share_lift`
  - `estimators.make_model`
  - `m1_strata`·`m1_decision`
  - `label_audit.AREA_BINS`
  - `safetydata.py`
- `evaluate()`:
  - `min_overlap=0` → `label_area > 0` 이다. `any`(f > 0) 규칙과 정확히 같다.
  - `cell_gate` 배경은 그 설정의 비양성 전체다.
  - 객체 AUC·`cell_bg` 배경은 호출자가 준 `~touched` 다. 절차 서술과 일치한다.
- `.omc/benchmark/prespec.json` 의 `selection.parameters` 가 §5 의 RF 고정값과 완전히 같다.
- 가설 근거 수치를 `artifacts/q1/M1/m1_20260926T160821Z_a181f6c/median_table.csv`·`decision.json` 으로 다시 조회했다. 모두 일치한다.
  - H1: 경사 0.8717, RF 0.8546 (7사상)
  - H2: 경사 ALL 0.8850 / FLAT 0.6932, RF ALL 0.8546 / FLAT 0.6540
  - H3: 불투수 격자 0.7078 / 객체 0.8213, 경사 격자 0.8850 / 객체 0.8353, 차이 +0.163
- 금지 표현: "전향적/사전등록 검증", "ML 우월"은 "쓰지 않는다"는 방어적 문장에만 나온다. 긍정 사용은 없다.

## 지적과 조치

| # | 심각도 | 절 | 지적 | 조치 (확정 커밋 `f80f736`) |
|---|---|---|---|---|
| 1 | 중간 | §7.1 H3 | 서술("경사는 그렇지 않다")이 판정식(Δ_imp − Δ_slope ≥ 0.02)보다 강하다 | 서술을 "상대적으로 0.02 이상 더 얻는다"로 낮췄다. 두 Δ 의 부호를 따로 보고하게 했다 |
| 2 | 중간 | §3.6 | `river_proximity` 결측 처리 규칙이 없다 (하천이 없으면 `distance_to` 가 전 칸 NaN) | 결측을 0 으로 하는 규칙을 추가했다. `zsens_pub` 의 z 가 0 이 되는 점과 `hand_neg` 의 처리를 명시했다 |
| 3 | 중간 | §1 S2 | 시군구 코드 대응표가 없고 B 단계로 미뤄졌다 | 대응표를 API 를 훑기 **전에** 출처·SHA256 과 함께 따로 커밋하게 했다 (S8-0). 예시 대응은 [미확인]으로 표기했다 |
| 4 | 낮음 | §7.1 H4 | 문턱 근처 0.001 차이도 성립으로 잡힌다 | "강한 뒤집힘"(바뀐 지표가 문턱을 0.02 이상 가로지름)을 정의했다. 도시 간 요약은 성립(강)만 센다 |
| 5 | 낮음 | §0.1/S5 | 세 도시 수치를 알고 문턱을 정했다 | S5 근거에 공개 문장을 추가했다: 그 수치가 문턱에서 멀다는 점, `FLDN_YR` 레코드 수라는 점, 광역시 합산·시도 제한 결과는 모른다는 점 |
| 6 | 낮음 | §5 | `rf_P_cw` 하이퍼파라미터가 명시되지 않았다 | `_wf` 와 같은 `make_model` 호출이라고 명시했다 |
| 7 | 확인 | §2 | 자료원·행정코드 사실은 검토자가 [미확인]으로 남겼다 | §2 에 확인 상태를 추가했다 (HEAD 로 확인한 것과 [미확인] 항목). [미확인] 항목은 B2 수집 전에 제공처 문서로 확인한다 |

추가 권고도 반영했다. `soft` AUC 에 0/1 가중치를 주면 표준 AUC 로 환원되는지 보는 합성 자료 검사를 B3 검사 목록에 넣었다 (§9-4).

## 확인하지 못한 것 (검토자)

- VWorld `LT_C_ADSIGG_INFO` 의 존재와 필드명, 도엽 SHA256. 네트워크에 접속하지 않았다.
- `src/replication/*` 는 아직 없다. 구현이 절차와 일치하는지는 B3 에서 확인한다.
