# M1 독립 검토 (읽기 전용)

판정: PASS-with-fixes

> 검토자: Claude 서브 에이전트 (구현과 다른 세션, AGENTS.md §1·§8). 홀드아웃 원본
> (`data/raw/flood_traces/changwon_info_disclosure_20260924/`)은 열지 않았고,
> `src.models.m1_run` 은 `--dev-only` 로만 실행했다(실행 뒤 산출 폴더 삭제). 그 외에는
> 이미 만들어진 공식 산출물(`artifacts/q1/M1/m1_20260926T160821Z_a181f6c/`)의 표만 읽었다.

## 확인한 것

### 1. 절차·시점

```
git log --format='%h %ad %s' --date=iso -10
e27a363 2026-09-26 16:12:11 +0000 results(q1/M1): 공식 실행 ... 보고
a181f6c 2026-09-26 16:08:20 +0000 fix(q1/M1): 판정 표 정렬 ...
225ef98 2026-09-26 16:06:27 +0000 feat(q1/M1): 자명 기준선·층·사전 판정·실행 모듈과 단위 검사
788ab0b 2026-09-26 16:02:53 +0000 feat(q1/M1): HAND 계산과 절차 보정 (AUC 계산 전)
b2b9cdc 2026-09-26 16:00:35 +0000 docs(q1/M1): 계산 전 절차 고정
33087c3 2026-09-27 00:45:04 +0900 cloud-base: ...
```
- 절차 문서 커밋(`b2b9cdc`)이 HAND·점수·판정 코드 커밋(`788ab0b`, `225ef98`, `a181f6c`) 전부보다 먼저다. 통과.
- `git diff b2b9cdc 788ab0b -- docs/q1/M1_protocol.md` 로 "보정" 절이 정확히 이 커밋에서 추가됐음을 확인했다.
  AUC를 계산하는 첫 코드(225ef98의 m1_run.py)는 그 뒤에 나온다 — "AUC 계산 전 보정" 서술이 사실과 맞는다.
- `git diff 33087c3 e27a363 -- AGENTS.md` 로 §6 표에 M1 행 1개만 추가됐음을 확인했다 (다른 절 변경 없음).
- `docs/CLOUD_TASKS.md` M1 정의(목표·점수·배경·판정 규칙·산출)와 `M1_protocol.md`를 대조: 점수 10개(§2), 층 5개(§3),
  주 판정 규칙(§5)이 과제 정의 요약과 일치한다.
- 표현 규칙 점검: `M1_protocol.md`·`M1.md`에서 금지 문구 6개("전향적", "RF 가 검증됐다", "10사상 일관",
  "ML 이 지침보다 우월", "강수 역전 원인 확정", "CDRI 가 우선순위를 식별한다") 모두 없음. `M1_protocol.md` 10행의
  "이 설계 자체는 사전등록 검증이 아니다"는 금지 문구의 부정(정직한 disclosure)이라 문제 없음.

### 2. 코드 대 절차 일치

- `src/models/m1_scores.py` `BASELINES`의 부호(경사·상대고도 `-1`, TWI·불투수 `+1`)와 `hand_neg`/`hand_acc_neg`의
  음수 부호가 절차 §2 표와 정확히 일치. `tests/test_m1.py::test_baseline_signs`로도 재확인됨.
- `src/models/m1_strata.py`의 임계(`FLAT_SLOPE_DEG=5.0`, `URBAN_IMPERVIOUS=0.5`, `AGRI_IMPERVIOUS=0.1`,
  `AGRI_WATER=0.5`)가 절차 §3 표와 일치, 경계값 포함 여부(`<=`, `>=`, `<`)도 `test_strata_thresholds`와 일치.
- `src/models/m1_decision.py`의 `MARGIN=0.02`, 주 판정식(`m_slope >= m_rf - MARGIN`), `MIN_UNITS={"cell_gate":5,
  "object":3}`가 절차 §5와 일치. `test_decision_within_margin_discards`·`test_min_units_and_missing_model`로
  경계값(gap=0.02 포함/미포함, 표본 부족 사상 배제, RF 결측 사상 배제)이 코드 그대로 재확인됨.
- `src/models/m1_run.py`의 시험 사상 나열(`DEV_YEARS`, `holdout.groupby("storm_id")`)과 훈련 라벨
  (`layer[[trace_ev_{y}...]].any()`)이 절차 §1과 일치.
- `E*` 이벤트 집합을 코드로 재현(아래 "재계산 결과" 참조): 7개 사상(2012·2014·2016·2019·2025·2023-08-10·2024-09-20),
  2006(RF 모델 없음)과 2022-09-06·2024-07-24(양성 격자 0)가 제외된 이유가 요약(§CLOUD_TASKS.md)의 사전 서술과 맞는다.

### 3. HAND 정확성 (`src/data/hand.py`)

- `d8_receivers`의 8방향·거리·"더 큰 하강"(`drop > best`) 규칙이 `src/data/features.py::flow_accumulation`과
  코드 구조상 동일함을 줄 단위로 대조했다. `tests/test_hand.py::test_receivers_match_flow_accumulation`이
  무작위 DEM에서 두 누적을 `assert_allclose`로 검사하며, 직접 재실행해 통과를 확인했다.
- `fill_sinks_epsilon`은 `fill_sinks`(features.py)와 같은 시작 규칙(경계·NaN 인접)을 쓰고, 이웃에
  `max(원표고, nextafter(z))`를 대입해 평탄칸에도 단조증가 하강 경로를 만든다 — Barnes 2014 Priority-Flood+ε의
  표준 형태와 일치한다.
- `hand()`는 흐름 방향에 `routed`(ε 채움), 높이에 `z = fill_sinks(elev)`(ε 없음)를 쓰고, `order_z=routed`
  기준으로 오름차순 처리해 "receiver가 donor보다 먼저 처리된다"를 보장하려 한다. 아래 적대적 시험으로 이 불변식을
  직접 검사했다(스크래치패드, 홀드아웃 미사용):
  - 합성 DEM 4종(경쟁하는 두 낮은 경계를 가진 평탄 평원, 벽에 갇힌 내부 함몰지+단일 출구, 하천이 전혀 없는
    무작위 DEM, 내부 NaN 블록)에서 `recv[i]>=0 → routed[recv[i]] < routed[i]` 위반 0건, 순환(cycle) 0건.
  - 대칭 코너(북·서 경계 모두 0)에서도 내부 미배정(`recv=-1`) 칸 0건 — 동률로 인한 교착 없음.
  - NaN은 `routed`·`HAND` 양쪽에서 정확히 원래 NaN 위치에만 남는다 (`test_nan_cells_stay_nan`과 일치하는 결과를
    더 큰 격자·NaN 블록에서도 재확인).
  - 하천이 전혀 없는 경우 전 칸이 `n_reach_flow_end`로 떨어지고 HAND ≥ 0 유지 확인.
  - 부작용: NaN이 있는 DEM에서 `RuntimeWarning: invalid value encountered in subtract`가 뜬다(inf−inf).
    결과에는 영향 없음(비교 연산이 NaN을 항상 False로 처리) — §"문제" 낮음 항목 참조.
- `hand_layers()`(m1_run.py)에서 재계산 표고 = `elev_m`(최대차 0.0, `elev_max_abs_diff` 필드로 실행이 멈추는
  검사가 있음)와 ε 없는 방향 규칙의 유량누적 = `flow_acc_cells`(protocol §2.1 서술)를 공식 실행의
  `summary.json`에서 확인했다(`elev_max_abs_diff: 0.0`).

### 4. 학습 데이터 누수·정렬

- `prior_years(year) = [y for y in DEV_YEARS if y < year and y != 2025]` — 홀드아웃 연도(2022~2024)에 대해서도
  `y < year` 조건만으로 2025가 자동 배제되고, 훈련 라벨은 항상 `DEV_YEARS`의 `trace_ev_<y>`만 사용해 홀드아웃
  라벨이 훈련에 들어갈 경로가 없다. `summary.json`의 `train_events`를 확인: 모든 홀드아웃 사상의 훈련 연도가
  `[2006, 2012, 2014, 2016, 2019]`로 2025·홀드아웃 자체가 빠져 있음 — 절차 §1과 일치.
- `rf_columns`(`.omc/benchmark/prespec.json` → `feature_columns`)에 `L1`·`z_sensitivity`·흔적 라벨이 없음을
  확인 — RF-F1이 비교 대상 점수를 스스로 학습에 쓰는 순환은 없다.
- 정렬: `layer`를 `grid_id`로 정렬(`sort_values("grid_id").reset_index(drop=True)`)한 뒤 `features`를
  `layer[["grid_id"]].merge(...)`로 재정렬하고, `feature_frame`도 `grid_id` 키 merge(검증 `validate="one_to_one"`)
  라 위치가 아니라 키로 맞춰진다. HAND는 같은 `layer`로 만든 `lattice_from_grid`의 `row,col`로
  `hand_osm[row,col]`을 뽑아 같은 순서가 된다 — 층·기준선·HAND·RF 점수가 모두 같은 `layer` 순서를 공유함을
  코드 추적으로 확인했다(별도 산출물 없이 진행한 코드 리딩; 표 대조는 아래 §3 재계산으로 간접 검증됨).

### 5. AGENTS.md §6 코드 스타일

- 검토 대상 5개 파일(`hand.py`, `m1_scores.py`, `m1_strata.py`, `m1_decision.py`, `m1_run.py`) 모두 모듈·함수
  docstring이 한 줄이고, 빈 줄로 나뉜 문단마다 그 문단의 동작을 설명하는 한 줄 주석이 붙어 있다 (예:
  `hand.py::hand()`의 3개 문단, `m1_run.py::run()`의 4개 문단).
- 파일 분리는 `M1_protocol.md` §6에 미리 선언된 배치(HAND/점수/층/판정/실행 5분리)와 정확히 일치하고,
  `AGENTS.md` §6 표에도 그대로 등록됐다.

### 6. 테스트

```
env -u CHANGWON_HOLDOUT_TESTS .venv/bin/python -m unittest discover -s tests
Ran 358 tests in 24.958s
OK (skipped=2)
```
`M1.md`가 보고한 "358개 통과(2개 skip)"와 일치.

### 7. 산출물 청결성

`artifacts/q1/M1/`에는 공식 실행 폴더 하나(`m1_20260926T160821Z_a181f6c`)만 있다. `M1.md`가 언급한
개발 전용 점검 실행(`--dev-only --n-boot 50`)과 폐기된 `m1_20260926T160628Z_225ef98`는 저장소에 없음 —
"산출물은 저장소에 넣지 않았다"는 서술과 일치.

## 재계산 결과

### 주 판정 재계산 (m1_decision.py 를 쓰지 않고 pandas 로 직접)

`metrics_long.csv`에서 `unit=cell_gate, stratum=ALL, metric=observed-label_auc, storm=ALL,
role∈{development,holdout}, score∈{slope_neg, rf_F1_wf}`만 뽑아 `rf_F1_wf`의 `n_units`(양성 격자 수) ≥ 5인
사상만 남겨 중앙값을 계산했다:

```
events kept: ['2012', '2014', '2016', '2019', '2023-08-10', '2024-09-20', '2025']
median slope_neg: 0.8717
median rf_F1_wf:  0.8546
gap (rf - slope): -0.0171
within_margin (slope >= rf - 0.02): True
paired diff median: 0.0298
```

`decision.json`의 `primary` 블록(`median_slope_neg=0.8717`, `median_rf_F1_wf=0.8546`, `median_gap=-0.0171`,
`median_paired_diff=0.0298`, `within_margin=true`, `verdict="C-b 폐기"`)과 완전히 일치.

### 독립 격자 AUC 재계산 (개발 흔적만, `src.models.m1_decision` 미사용)

`src.data.flood_traces.files_for("development")`로 읽은 개발 흔적만으로 10% 규칙 라벨(합집합 면적 처리 포함)을
직접 만들고 `sklearn.metrics.roc_auc_score`로 계산(배경 = 그 층의 비양성 전 격자, `cell_gate` 정의와 동일):

| 점수 | 사상 | 양성 격자 | 독립 재계산 AUC | `metrics_long.csv` 값 |
|---|---|---:|---:|---:|
| `slope_neg` | 2014 | 132 | 0.8132 | 0.813158 |
| `impervious` | 2019 | 56 | 0.9417 | 0.941698 |
| `twi` | 2016 | 170 | 0.8332 | 0.833233 |

세 경우 모두 소수 4자리까지 일치. `evaluate.py`의 `cell_gate` AUC가 실제로 "그 층의 비양성 전 격자"를 배경으로
쓴다는 점(주어진 `background_mask=~touched`와 무관하게 `("gate", ~labels)`를 쓰는 코드, `evaluate.py:126`)도
코드로 확인했다.

## 문제

1. **[낮음] `src/data/hand.py`의 `fill_sinks_epsilon`/`d8_receivers`에서 NaN이 있는 DEM에 대해
   `RuntimeWarning: invalid value encountered in subtract`가 발생한다** (`z - shifted`에서 `inf - inf`).
   결과값에는 영향이 없음을 적대적 시험으로 확인했지만(비교식이 NaN을 항상 False로 처리), 로그를 지저분하게
   만들고 향후 실수(예: 경고를 오류로 격상하는 CI 설정)에 취약하다.
   제안: `np.errstate(invalid="ignore")`로 해당 블록을 감싼다. (이 패턴은 `features.py::flow_accumulation`에도
   이미 있어 M1이 새로 만든 문제는 아니다.)

2. **[낮음] `src/models/m1_scores.py`가 "고정 기준선 점수"와 "이전 사상 재학습 모델 점수" 두 가지 다른 성격의
   계산을 한 파일에 담는다.** `AGENTS.md` §6 원칙("실행 흐름과 계산 함수는 다른 파일에", "기능마다 파일을
   나눈다")의 정신에는 살짝 어긋나지만, `M1_protocol.md` §6에 이 파일 배치가 계산 전에 이미 선언돼 있어
   사후 회피는 아니다. 리팩터링이 필요하면 `m1_baselines.py`/`m1_retrain.py`로 더 쪼갤 수 있다는 정도의 참고
   사항이다.

3. **[낮음] `m1_decision.compare()`의 최소 표본 검사가 `units[model]`(비교 모델 쪽 점수의 n_units)만 본다.**
   절차 §5는 "양성 격자가 5칸 이상인 시험 사상"이라고만 쓰여 있어 어느 점수 기준인지 명시하지 않는다. 이번
   공식 실행에서는 같은 사상·층에서 점수 간 양성 격자 수가 실질적으로 같아 결과에 영향이 없었지만(재계산으로
   확인), 두 점수의 `finite` 마스크가 크게 다른 경우(예: 결측이 많은 새 점수)에는 트리비얼 쪽 표본이 실제로는
   5칸 미만인데도 통과할 수 있다. M2/M3에서 점수를 늘릴 때 주의가 필요하다는 정도로 남긴다.

4. **[정보, 결함 아님] `median_table.csv`는 최소 표본 미달 행을 완전히 제거하지만 `metrics_long.csv`(원 표)는
   모든 사상·점수 조합을 남긴다** (예: `slope_neg, cell_gate, ALL, 2022-09-06` 행이 값 없이 `n_units=0`으로
   존재). 절차 §4의 "표에 싣되 중앙값에서 뺀다"는 서술은 `metrics_long.csv` 기준으로는 맞고 `median_table.csv`
   기준으로는 (의도적으로) 다르다. AGENTS §2 규칙5(불리한 결과를 숨기지 않는다)는 원 표가 지키고 있으므로
   위반은 아니지만, 두 표의 성격 차이를 protocol 문서에 한 줄 더 밝혀두면 오해를 줄일 수 있다.

높음·중간 등급 문제는 발견하지 못했다. 주 판정("C-b 폐기")과 그 근거 수치는 독립적으로 재현됐고,
HAND 구현은 적대적 시험을 통과했으며, 학습 데이터에 홀드아웃·2025·비교 대상 점수(L1 등)가 섞여 들어가는
경로를 찾지 못했다.

## 한계·미확인 (검토자 측)

- `src/data/validation/evaluate.py`·`curves.py`·`resampling.py`의 `object`/`cluster_gate` 단위, Boyce 지수,
  포착곡선 자체의 정확성은 이번 검토 범위(M1이 새로 만든 5개 파일 + 테스트)를 벗어나 재검증하지 않았다.
  다만 `cell_gate` AUC는 두 가지 독립 방법(§재계산)으로 확인했다.
- 폴리곤(`object`) 단위 AUC, 덩어리(`cluster_gate`) 재표본, Boyce 지수는 별도로 재계산하지 않았다 — 지시문의
  "한 두 개 사상 cell AUC" 요구는 충족했지만 시간 제약상 object 단위까지는 독립 재현하지 않았다.
- `hand_layers()`가 재계산 표고 검사(`diff <= 1e-3`)에 실패하면 `RuntimeError`로 실행이 멈추는 것은 코드로
  확인했지만, 실제로 그 경로를 강제로 트리거해보지는 않았다(홀드아웃 없이도 가능했으나 시간상 생략).
- HAND 적대적 시험은 검토자가 새로 작성한 합성 DEM 4~5종에 한정된다. 실제 창원 90m DEM의 23,501개 평탄칸
  전체에 대한 전수 검사는 하지 않았고, 공식 실행의 `summary.json` 요약 수치(흐름끝 2,525칸 등)를 그대로
  신뢰했다.
