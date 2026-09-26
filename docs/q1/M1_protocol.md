# M1 절차 — 자명한 기준선과 어려운 음성 (계산 전 고정)

> 과제 정의: `docs/CLOUD_TASKS.md` M1. 규칙: `AGENTS.md` §2·§6·§8.
> 이 문서는 **점수·배경·지표·판정 규칙을 계산 전에 고정**하려고 커밋한다. 이 커밋 전에는 M1 점수로 AUC 를 계산하지 않았다.
> 층화 임계를 고르려고 라벨 없이 본 분포는 경사·불투수율의 격자 수뿐이다 (아래 §3).

## 0. 지위

- **post-hoc.** 2022~2024 홀드아웃 결과(L1 탈락, 강수 축 역방향, 시간순 결과)를 이미 본 뒤에 설계했다.
  M1 은 홀드아웃을 채점에만 쓰지만, 이 설계 자체는 사전등록 검증이 아니다.
- RF-F1 의 특징집합·하이퍼파라미터는 개발 6사상 전체 CV 로 골랐다 (`.omc/benchmark/prespec.json`).
  시간순 재학습은 이 설정을 이전 사상에만 다시 맞춘 것이다. 설정 선택의 미래 정보는 M3 에서 다룬다.

## 1. 시험 사상과 라벨

- 시간순 구성은 `artifacts/posthoc/20260926/walkforward.py` 와 같다.
  - 개발: `event_date` 연도가 2006, 2012, 2014, 2016, 2019, 2025 인 개발 흔적. 날짜 없는 개발 흔적은 뺀다.
  - 홀드아웃: `storm_id` 별 4사상 (2022-09, 2023-08, 2024-07, 2024-09).
- 격자 라벨: `src.data.validation.evaluate` 의 10% 규칙 (`min_overlap=0.10`). 격자 1표.
- 학습 모델(RF·로지스틱)은 시험 사상 연도보다 이른 개발 사상만으로 학습한다. 2025 와 홀드아웃은 학습에 쓰지 않는다.
  학습 라벨은 `layer1_flood.gpkg` 의 `trace_ev_<연도>` 합집합이다. 이전 사상이 없는 2006 은 학습 모델을 비워 둔다.

## 2. 점수 (방향은 계산 전 고정, 부호를 뒤집어 "클수록 위험"으로 맞춘다)

| 이름 | 정의 | 방향 근거 |
|---|---|---|
| `slope_neg` | −`slope_deg` | 평지일수록 물이 모인다 |
| `relelev_neg` | −`rel_elev_m` | 주변보다 낮을수록 위험 |
| `twi` | `twi` | 습윤지수가 클수록 위험 |
| `impervious` | `impervious_frac` | 불투수일수록 위험 |
| `hand_neg` | −HAND (OSM 하천망, §2.1) | 배수로 위 높이가 낮을수록 위험 — **HAND 주 정의** |
| `hand_acc_neg` | −HAND (유량누적 하천망, §2.1) | 민감도 변형 |
| `L1` | 동결 지수 L1 | 비교 대상 |
| `z_sensitivity` | 동결 민감도 z | 비교 대상 |
| `rf_F1_wf` | RF-F1 (`MODELS["v2"]` 설정 그대로) 이전 사상 재학습 | 비교 대상 |
| `logit_F1_wf` | `make_model("ridge", {"C": 1.0})`, F1 특징, 이전 사상 재학습 | 비교 대상 (`robust_explain.py` 의 `logit_F1_C1`) |

지형 네 변수는 `grid_features.parquet` 의 값을 그대로 쓴다 (90 m DEM → 100 m 격자, H04).

### 2.1 HAND

- DEM: `data/raw/dem/public_dem_2025/*.img` 를 H04 와 같은 방식(`dem_to_lattice`, bilinear)으로 100 m 격자망에 올린다.
  재계산한 표고가 `grid_features.elev_m` 과 최대 절대차 1e-3 m 안에서 같지 않으면 실행을 멈춘다.
- 수문 보정: 기존 `fill_sinks` (priority-flood). 흐름 방향: `flow_accumulation` 과 같은 D8 최급경사 규칙.
- 하천망 (주 정의): OSM `waterway ∈ {river, stream, canal}` (H04 의 `river_dist_m` 과 같은 선택)을
  100 m 격자에 `all_touched` 로 래스터화한 칸.
- 하천망 (민감도): D8 유량누적 ≥ 100칸 (≈ 1 km²) 인 칸.
- HAND = 채운 표고(칸) − 채운 표고(D8 하류로 따라가 처음 만나는 하천 칸). 하천을 못 만나고 흐름이 끝나면
  (바다·자료 밖·격자 끝) 흐름이 끝나는 칸을 배수 기준으로 쓴다. 음수는 0 으로 자른다. DEM 결측 칸은 NaN.

## 3. 배경 (층)

모두 격자 속성으로만 정의한다. 토지피복 원본은 cloud-base 에 없어서 가공 특징으로 대신한다.

| 층 | 정의 | 격자 수 |
|---|---|---|
| `ALL` | 전 격자 | 75,400 |
| `FLAT` | `slope_deg ≤ 5` | 22,934 |
| `URBAN` (시가지) | `impervious_frac ≥ 0.5` | 9,695 |
| `AGRI` (농경지 대리) | `impervious_frac < 0.1` 이고 `slope_deg ≤ 5` 이고 `inland_water_frac < 0.5` | 10,433 |
| `UNIVERSE` | `universe == 1` (인구 거주 격자) | 10,202 |

- 경사 5° 는 라벨을 보지 않고, 전 격자 경사 분포(중앙값 11.35°, 25% 분위 3.28°)만 보고 고정했다.
- `AGRI` 는 "평탄하고 건물이 거의 없는 비수역"이다. 논·밭 외에 초지·나지·공사장이 섞일 수 있다. 토지피복으로 확인하지 않았다.
- `UNIVERSE` 층의 L1·`z_sensitivity`·RF 결과가 CDRI 의 H 단독 AUC 다.
- 각 층 안에서 `cell_gate` 배경은 그 층의 비양성 전 격자다 (`evaluate` 의 `strata`).

## 4. 지표

`V.evaluate(scores, layer, polys, strata=..., background_mask=~touched, min_overlap=0.10, n_boot=1000, seed=42)`.
`touched` 는 walkforward 와 같이 개발·홀드아웃 어느 흔적과도 닿은 격자다. 보고하는 행:

- 격자 AUC: `unit=cell_gate, metric=observed-label_auc` (95% 덩어리 재표본 구간 포함)
- 상위 20% 포착: `unit=cell_gate, metric=capture_0.2`
- 객체 AUC: `unit=object, metric=observed-label_auc` (폴리곤 1표)
- 덩어리 AUC: `unit=cluster_gate, metric=observed-label_auc` (참고)

최소 표본: 층×사상에서 양성 격자 < 5 이면 격자 지표는 표에 싣되 중앙값에서 뺀다. 객체 지표는 폴리곤 < 3 이면 뺀다.

## 5. 사전 판정 규칙

- **주 판정 (C-b):** 사상 집합 E\* = `ALL` 층에서 `rf_F1_wf` 가 있고 양성 격자가 5칸 이상인 시험 사상 (개발·홀드아웃 합산).
  - m_slope = E\* 에서 `slope_neg` 격자 AUC 의 중앙값.
  - m_rf = E\* 에서 `rf_F1_wf` 격자 AUC 의 중앙값.
  - **m_slope ≥ m_rf − 0.02 이면 C-b(지형 모형 우위) 주장을 폐기한다.** 경사가 RF 보다 높은 경우도 폐기다.
  - 그렇지 않으면 "C-b 가 이 자명 기준선 검사에서 탈락하지 않았다"고만 쓴다. 우위가 입증됐다고 쓰지 않는다.
- **보조 (판정에 쓰지 않는다, 그대로 보고):**
  - 같은 비교를 개발만·홀드아웃만, 객체 AUC, `FLAT` 층으로 반복한다.
  - 사상별 짝 차이(RF − 경사)의 중앙값.
  - 다른 자명 기준선(상대고도·TWI·불투수·HAND)과 RF 의 같은 비교.
  - 모든 점수의 사전 게이트(격자 AUC ≥ 0.70, 포착 ≥ 0.50) 통과 여부.
- 결과를 본 뒤 규칙·임계·층 정의를 바꾸면 `post-hoc` 으로 표기하고 이 규칙의 결과를 함께 싣는다.

## 6. 산출과 출처

- 코드: `src/data/hand.py`(HAND), `src/models/m1_scores.py`(기준선·시간순 모델 점수), `src/models/m1_strata.py`(층),
  `src/models/m1_decision.py`(판정), `src/models/m1_run.py`(실행).
- 실행: `PYTHONPATH=. .venv/bin/python -m src.models.m1_run` (클라우드 리더만, 홀드아웃을 읽는다).
- 산출: `artifacts/q1/M1/<run_id>/` — `metrics_long.csv`, `decision.json`, `summary.json`, `hand.parquet`.
- 보고: `docs/q1/M1.md` (AGENTS §4 형식).
