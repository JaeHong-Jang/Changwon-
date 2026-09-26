# M3 독립 검토 (읽기 전용)

판정: PASS

> 검토자: 구현과 다른 모델의 Claude 서브 에이전트 (다른 세션, AGENTS.md §1·§8). 홀드아웃 원본
> (`data/raw/flood_traces/changwon_info_disclosure_20260924/`)은 열지도 나열하지도 않았고, 그것을 읽는
> 코드도 실행하지 않았다. `src.models.m3_run`은 지시된 대로 `--dev-only --n-boot 50`으로 **1회만** 실행했고
> (산출 `artifacts/q1/M3/m3_devonly_20260926T170104Z_f53c243/`), 확인 후 그 폴더를 삭제했다. 그 외에는
> 이미 만들어진 공식 산출물(`artifacts/q1/M3/m3_20260926T164916Z_f383cb3/`)과 M1 공식 산출물
> (`artifacts/q1/M1/m1_20260926T160821Z_a181f6c/`)의 표만 읽었다. 저장소에는 `docs/q1/M3_review.md`
> 하나만 새로 썼고, 재계산용 스크립트는 모두 저장소 밖 스크래치패드에 두었다.

## 확인한 것

### 1. 시점·출처

```
git log --format='%h %ad %s' --date=iso -8
f53c243 2026-09-26 16:58:29 +0000 M3 보고 초안: 공식 run m3_20260926T164916Z_f383cb3 결과 (교차 리뷰 전)
682f61a 2026-09-26 16:54:26 +0000 M3 공식 실행 산출: run m3_20260926T164916Z_f383cb3
039685f 2026-09-26 16:50:00 +0000 AGENTS §6: 시간순 재학습 공통·M3 파일 배치 행 추가
f383cb3 2026-09-26 16:49:11 +0000 M3 코드: 이전 사상 LOEO 설정 선택, 재현 확인, 판정, 실행
0cc9360 2026-09-26 16:40:16 +0000 M3 절차: 중첩 시간순 교차검증 (계산 전 고정)
8f0daa8 2026-09-27 01:29:07 +0900 cloud-base: M1 결과 반영 + 설정 스크립트 수정
```

- 절차 커밋(`0cc9360`)이 코드(`f383cb3`)·공식 실행(`682f61a`)·보고서(`f53c243`) 전부보다 먼저다. `git diff 0cc9360 HEAD --
  docs/q1/M3_protocol.md`는 빈 diff — 계산이 시작된 뒤 절차 문서를 고치지 않았다.
- `summary.json`의 `git_head: "f383cb3"`, `source_dirty: false` — 공식 실행이 코드 커밋 바로 다음 clean 상태에서 됐다.
- **특이사항.** 검토를 시작한 시각에는 `docs/q1/M3.md`(공식 보고서, 프로토콜 §6이 요구하는 산출물)가 저장소에
  없었다 — 처음 `git log`를 봤을 때 최상단이 `682f61a`였다. 검토 중간에 `f53c243` 커밋으로 보고서가 추가됐다.
  아래 "재계산 결과"·"확인한 것 §7"에서 이 보고서의 수치를 뒤늦게 대조했다.

### 2. 코드 대 절차 일치

- **설정 공간.** `src/models/m3_configs.py::grid()`가 `FEATURES`(F0→F1→F2) 바깥 루프, `CANDIDATES` 딕셔너리
  순서(`ridge→frequency_ratio→random_forest→xgboost`, `estimators.py`의 선언 순서 그대로) 안 루프, 후보 리스트
  순서 안 루프로 짠다 — 절차 §2의 선언 순서와 글자 그대로 같다. `VARIANTS = {"nested_rf": ("random_forest",),
  "nested_all": tuple(CANDIDATES)}`로 주 6설정·보조 24설정을 만들고, `FIXED_ID`는
  `random_forest|F1|max_depth=4,min_samples_leaf=400` — 동결 모델과 같다. `check_prespec()`이
  `.omc/benchmark/prespec.json`의 `features`·`candidates`·`fixed_parameters`·동결 선택을 코드 상수와 비교해
  다르면 `ValueError`를 던진다. `test_grid_sizes_and_order`·`test_check_prespec`이 이를 검사하고, 공식 실행이
  통과했다(`n_configs: {"nested_rf": 6, "nested_all": 24}`).
- **안쪽 선택이 홀드아웃·미래 사상을 보지 않는다.** `m3_select.py`·`m3_configs.py`·`m3_checks.py`·`m3_decision.py`
  네 파일에는 `FT`·`holdout`·`files_for` 참조가 전혀 없다(`grep`으로 확인). `m3_run.py`에서 `FT.files_for("holdout")`은
  `if include_holdout:` 블록 안 한 줄에만 있고, 안쪽 LOEO에 넘기는 `labels` 딕셔너리는
  `{y: layer[f"trace_ev_{y}"] ... for y in DEV_YEARS}`로 `DEV_YEARS = (2006, 2012, 2014, 2016, 2019, 2025)`에만
  한정된다 — 홀드아웃 사상은 이 딕셔너리에 애초에 없다. `prior_years(year) = [y for y in DEV_YEARS if y < year and
  y != 2025]`가 2025를 모든 이전 사상 집합에서 명시적으로 뺀다.
- **이전 사상 집합.** `selected.json`의 `by_test_event`를 절차 §1 표와 대조: 2006 학습 불가(prior `[]`), 2012 선택 불가
  (prior `[2006]`, 길이 1), 2014~2025·홀드아웃 4사상 모두 선택(길이 2~5) — 표와 정확히 같다. 2025와 홀드아웃 4사상은
  모두 prior `[2006, 2012, 2014, 2016, 2019]`를 써 같은 설정을 받는다(절차가 예상한 대로).
- **선택 지표·동점 처리.** `m3_select.rank_configs`가 `cluster_auc`의 뺀 사상 비가중 평균으로 점수를 매기고
  (`groupby("config")["cluster_auc"].mean()`), `np.lexsort((declaration_index, -score))`로 점수 내림차순·동점은
  선언 순서로 정렬한다. `test_rank_ties_follow_declaration`이 이 규칙을 직접 검사한다.
- **바깥 재학습·평가.** `trained_before`(`prior_fit.py`, M1 리뷰 후 `m1_scores.py`에서 분리)가 이전 사상 라벨
  합집합으로 `clone(model).fit(...)`한다 — M1의 정의와 같다. `V.evaluate(scores, layer, polys, strata=masks,
  background_mask=~touched, n_boot=n_boot, seed=42)` 호출에 `min_overlap`을 넘기지 않아 기본값 0.10을 쓴다(절차 §4.2와
  일치). `KEEP` 집합이 `m1_run.py`의 `KEEP`과 리터럴로 동일하다(격자 AUC·상위 20% 포착·덩어리 AUC·객체 AUC·객체 포착).
- **판정 규칙.** `m3_decision.py`가 `m1_decision.MARGIN`(0.02)·`compare()`를 그대로 재사용한다. 주 판정은
  `optimism(long, "nested_rf")` → `compare(long, "nested_rf", "rf_F1_wf")`이고, `within_margin`은
  `median_nested_rf >= median_rf_F1_wf - 0.02` — 절차 §5의 "m_nested < m_fixed − 0.02" 규칙의 정확한 부정이다.
  M1 재확인은 같은 `E_nest`로 자른 표에서 `compare(long, "slope_neg", "nested_rf")`를 쓴다.
- **M1 재학습 함수 분리.** `m1_scores.py`가 `from src.models.prior_fit import DEV_YEARS, prior_years,
  trained_before  # noqa: F401`로 이름을 유지하고, `m1_run.py`의 `from src.models.m1_scores import DEV_YEARS,
  baseline_scores, prior_years, trained_before` 줄은 손대지 않았다(AGENTS §6-3). `test_status_and_reexport`가
  `m1_scores.trained_before is prior_fit.trained_before`를 직접 검사한다.

### 3. AGENTS §6 코드 스타일

- `prior_fit.py`·`m3_configs.py`·`m3_select.py`·`m3_checks.py`·`m3_decision.py`·`m3_run.py` 6개 파일 모두
  모듈·함수 docstring이 한 줄이고, 빈 줄로 나뉜 문단마다 그 문단의 동작을 설명하는 한 줄 주석이 있다(예:
  `m3_run.py::run()`의 6개 문단, `m3_select.py::config_loeo()`의 두 문단, `m3_decision.py::decide()`의 두 문단).
- 파일 분리는 "실행 흐름"(`m3_run.py`)과 "계산"(`m3_select.py`·`m3_decision.py`·`m3_configs.py`) 원칙을 지킨다.
  `m3_checks.py`는 절차 §6이 계산 전에 선언한 5개 파일 목록에 없던 6번째 파일이다 — §"지적 1" 참조(낮음, 방법론
  영향 없음).

### 4. 테스트

```
env -u CHANGWON_HOLDOUT_TESTS .venv/bin/python -m unittest discover -s tests
Ran 371 tests in 48.591s
OK (skipped=2)
```

M1 리뷰가 보고한 358개(2 skip)에 M3의 새 검사 13개를 더하면 371 — 정확히 일치한다. `tests/test_m3.py`를 다 읽었다:
경계값(짝 차이 정확히 0.02일 때 낙관 아님/0.03일 때 낙관, `test_optimism_margin`), 누수 성질(뺀 사상 양성이 학습에
없음·미래 사상 양성이 학습에서 음성임, `test_splits_exclude_held_positives_and_test_rows`·
`test_future_positive_is_negative`), 동점 처리(`test_rank_ties_follow_declaration`), 재현 비교의 실패 경로(값 이동·
NaN 불일치·기준 누락·단위 필터, `test_match_reference`), 재export 항등성(`test_status_and_reexport`)까지 검사해
공허하게 통과하는 테스트는 찾지 못했다.

### 5. `--dev-only` 실행 (검토자 실행, 홀드아웃 미접근)

```
env -u CHANGWON_HOLDOUT_TESTS PYTHONPATH=. .venv/bin/python -m src.models.m3_run --dev-only --n-boot 50
...
P=[2006, 2012] chosen {'nested_rf': 'random_forest|F0|max_depth=2,min_samples_leaf=200', 'nested_all': 'frequency_ratio|F0|n_bins=10,alpha=1.0'}
P=[2006, 2012, 2014] chosen {'nested_rf': 'random_forest|F0|max_depth=4,min_samples_leaf=400', 'nested_all': 'random_forest|F0|max_depth=4,min_samples_leaf=400'}
P=[2006, 2012, 2014, 2016] chosen {'nested_rf': 'random_forest|F0|max_depth=4,min_samples_leaf=400', 'nested_all': 'xgboost|F0|max_depth=3'}
P=[2006, 2012, 2014, 2016, 2019] chosen {'nested_rf': 'random_forest|F0|max_depth=4,min_samples_leaf=400', 'nested_all': 'xgboost|F0|max_depth=3'}
{"run_id": "m3_devonly_20260926T170104Z_f53c243", "verdict": "설정 선택의 미래 정보가 격자 AUC 중앙값을 0.02 넘게 올리지 않았다", "m1_recheck": "M1 의 C-b 폐기 판정은 중첩 선택에서도 유지된다"}
```

4개 이전 사상 집합 모두 공식 실행(`selected.json`)과 정확히 같은 설정을 골랐다. `include_holdout=False`일 때
`FT.files_for("holdout")`을 부르는 코드 경로는 실행되지 않는다(코드에 그 호출이 `if include_holdout:` 블록 한
곳에만 있음을 읽어서 확인했고, 이 실행이 그 분기를 타지 않고 끝났다). 실행 뒤
`artifacts/q1/M3/m3_devonly_20260926T170104Z_f53c243/`를 삭제했다.

### 6. 표현 규칙

```
grep -n "전향적\|사전등록 검증\|RF 가 검증\|10사상 일관\|ML 이 지침보다 우월\|강수 역전 원인 확정\|CDRI 가 우선순위를 식별" \
  docs/q1/M3_protocol.md docs/q1/M3.md src/models/m3_*.py src/models/prior_fit.py tests/test_m3.py
(no matches, exit 1)
```

금지 문구 6개 모두 없음.

### 7. `docs/q1/M3.md` 보고서 대조

보고서에 실린 수치를 표별로 원 산출물과 대조했다(모두 일치, 반올림 차이만 있음):

- "결과 요약"의 E_nest 중앙값(0.865/0.873, 차 0.008), 짝 차이(−0.002), 상위 20% 포착(0.761/0.902, 짝 0.021) —
  `decision.json`의 `primary`·`secondary.capture_0.2`와 일치.
- "안쪽 선택" 표의 P별 1위 설정·선택 점수·고정 구성 순위 — `selected.json`의 `by_prior`와 일치.
- "주 판정" 표의 사상 10개 × 점수 4개 — `metrics_long.csv`(`cell_gate`, `ALL`, `observed-label_auc`)와 일치
  (예: 2014 고정 0.852/중첩 0.839/전체 0.814/경사 0.813, 2022-09·2024-07 양성 0으로 결측 표기).
- "M1 판정 재확인"·"보조 비교"(8행) — `decision.json`의 `m1_recheck`·`secondary`(각 `dev_only`·`holdout_only`·
  `object_auc`·`capture_0.2`·`flat_stratum`·`nested_all_vs_fixed`·`nested_all_object_auc`)와 일치.
- "층별 격자 AUC 중앙값"(4점수 × 5층 = 20칸) — `median_table.csv`(`cell_gate`, `observed-label_auc`,
  `role_group="all"`)와 일치.
- "선택 낙관" 표(6행) — `decision.json`의 `secondary.selection_gap`과 일치.

보고서가 스스로 밝힌 한계(§"공식 run 전 실행 1번"의 개발 전용 모드 배경 차이, §"선택이 불안정하다"의 1·2위 점수차
0.0001~0.0057, §"F0 대 F1"의 특징집합 선택 차이)도 코드·산출물로 재확인된다.

## 재계산 결과

독립 스크립트(`src/models/folds.py`·`scoring.py`·`estimators.py`·`features.py`만 쓰고 `m3_select`·`m3_decision`·
`m3_checks`·`m3_run`은 쓰지 않음, 스크래치패드에 저장)로 4개 항목을 다시 계산했다.

| 항목 | 공식 값 | 재계산 값 | 차이 |
|---|---|---|---|
| P=(2006,2012,2014) LOEO `cluster_auc`, RF/F0/(4,400), held 2006/2012/2014 | 0.865847 / 0.730898 / 0.819012 | 0.865847 / 0.730898 / 0.819012 | 0.0 (최대) |
| 〃, RF/F1/(4,400), held 2006/2012/2014 | 0.866972 / 0.726956 / 0.818175 | 0.866972 / 0.726956 / 0.818175 | 0.0 (최대) |
| 4개 이전 사상 집합 × 2변형 선택 설정·점수 (`selection_loeo.csv`만으로 재계산) | `selected.json`의 `by_prior` 8개 항목 | 8/8 동일 config, 점수차 ≤1.11e-16 | ≤1.11e-16 |
| 바깥 `cell_gate` ALL 격자 AUC, `nested_rf`, 2016 (P=2006,2012,2014 로 재학습) | 0.910601 | 0.910601 | 1.11e-16 |
| 〃, 2019 (P=2006,2012,2014,2016 로 재학습) | 0.968227 | 0.968227 | 1.11e-16 |
| n_positive(2016)=170, n_positive(2019)=56 vs `metrics_long.csv`의 `n_units` | 170 / 56 | 170 / 56 | 0 |
| 주 판정: E_nest, `median_nested_rf`/`median_rf_F1_wf`/`median_gap`/`median_paired_diff`/판정문 (`metrics_long.csv`만으로 재계산) | 0.8653 / 0.8732 / 0.0079 / −0.0021 / "…올리지 않았다" | 0.8653 / 0.8732 / 0.0079 / −0.0021 / "…올리지 않았다" | 0.0 |
| M1 재확인: `median_slope_neg`/`median_nested_rf`/판정문 (E_nest, `metrics_long.csv`만으로) | 0.8921 / 0.8653 / "…유지된다" | 0.8921 / 0.8653 / "…유지된다" | 0.0 |

## 지적

1. **[낮음] `docs/q1/M3_protocol.md` §6의 사전 파일 목록에 `src/models/m3_checks.py`가 없다.** 절차는 계산 전에
   `prior_fit.py`·`m3_configs.py`·`m3_select.py`·`m3_decision.py`·`m3_run.py` 5개만 선언했는데, 실제 구현은 재현
   확인(§4.3)을 별도 파일로 뺐다. `AGENTS.md` §6 표에는 사후에 등록됐고, `docs/q1/M3.md` §한계·미확인에서도
   스스로 이 사실을 밝히며 "분석 내용의 변경은 아니다"라고 적었다. 실패 시나리오: 이런 사전 목록과 실제 파일의
   불일치가 누적되면, 다음 과제(M4 이후) 검토자가 "계산 전 선언"과 "실제 코드"를 맞춰볼 때 무엇이 사전 선언이고
   무엇이 사후 추가인지 헷갈릴 수 있다. 다만 이번 건은 재현 확인 코드일 뿐 선택·판정 산식에 영향이 없어 연구
   무결성(§2) 위반은 아니다. 제안: 절차 문서의 파일 목록에 "필요시 재현 확인용 파일을 추가할 수 있다" 같은 한
   줄을 미리 넣거나, M4부터는 재현 확인 파일을 처음부터 §6에 포함한다.
2. **[정보, 결함 아님] 검토 시작 시점에 `docs/q1/M3.md`가 아직 없었다.** 공식 실행 커밋(`682f61a`, 16:54)과 보고서
   커밋(`f53c243`, 16:58) 사이에 몇 분의 간격이 있었고, 검토는 그 사이에 시작됐다. 최종적으로는 보고서가 존재하고
   (§"확인한 것 7"·"재계산 결과") 수치가 전부 정확하므로 판정에는 영향이 없다.

높음·중간 등급 문제는 발견하지 못했다.

## 판정 근거

- **시점**: 절차(`0cc9360`) → 코드(`f383cb3`) → 공식 실행(`682f61a`) → 보고서(`f53c243`) 순서가 커밋 시각으로
  확인되고, 절차 문서는 그 뒤로 바뀌지 않았다(`git diff` 빈 결과).
- **코드-절차 일치**: 설정 공간(6/24, 선언 순서)·이전 사상 정의·안쪽 LOEO 지표·동점 규칙·바깥 재학습·평가·판정
  규칙·최소 표본 규칙이 모두 절차 문서와 글자 단위로 일치함을 코드 읽기와 8개 이전 사상×변형 조합의 독립
  재계산으로 확인했다.
- **누수 없음**: 안쪽 선택 코드 4개 파일 어디에도 홀드아웃·2025 참조가 없고(grep), `labels` 딕셔너리 자체가
  `DEV_YEARS`에 한정되며, `--dev-only` 실행이 공식 실행과 같은 설정을 고르면서도 홀드아웃 분기를 타지 않음을
  직접 실행으로 확인했다.
- **독립 재계산**: LOEO 지표(6값)·선택 순위(8조합)·바깥 격자 AUC(2사상)·주 판정·M1 재확인을 모두 공식 코드
  (`m3_select`·`m3_decision`)를 쓰지 않고 다시 계산해 기계 정밀도(≤1.11e-16) 안에서 일치시켰다.
- **테스트**: 371개 전체 통과(2 skip), 새 검사 13개가 경계값·누수 성질·동점 규칙·재export·비교 실패 경로를 실제로
  검사한다.
- **코드 스타일**: AGENTS §6의 한 줄 docstring·문단별 한 줄 주석·기능별 파일 분리·이름 유지 규칙을 모두 지켰다
  (파일 목록 사전 선언과의 미세한 어긋남 1건, 낮음).
- **표현 규칙**: 금지 문구 없음.
- **보고서**: 뒤늦게 나타난 `docs/q1/M3.md`의 모든 수치 표를 원 산출물과 대조해 일치를 확인했다.

=> 재계산이 전부 일치하고, 누수·재튜닝·표현 규칙 위반을 찾지 못했으며, 발견한 문제가 낮음 등급 1건(방법론에
영향 없음)과 정보성 1건뿐이므로 **PASS**로 판정한다.
