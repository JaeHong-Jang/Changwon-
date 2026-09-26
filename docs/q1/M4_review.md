# M4 독립 검토 (읽기 전용)

판정: **PASS-with-fixes**

> 검토자: 구현자(Claude Opus 5.5)와 다른 모델(Claude Sonnet 5, 독립 서브에이전트)이 읽기 전용으로 수행. 저장소 추적 파일은 수정·생성·삭제하지 않았다 (`git status --porcelain` 최종 확인 결과 없음). 스크래치 스크립트는 `.omc/review_m4/recompute.py`, `.omc/review_m4/recompute2.py` 에만 두었다. `data/raw/flood_traces/changwon_info_disclosure_20260924/` 를 열지 않았고, `FT.files_for("holdout")`·`FT.load_holdout`·`src.models.holdout_eval`·옵션 없는 `m4_run` 을 실행하지 않았다. `m4_run`(`--dev-only` 포함)도 전혀 실행하지 않았다 — 독립 경로(shapely/geopandas/sklearn 직접 계산)만으로 재계산했으므로 `artifacts/q1/M4/m4_devonly_*` 폴더는 생성되지 않았다. 공식 산출물 `artifacts/q1/M4/m4_20260926T164939Z_390f3fc/` 의 표만 읽었다.

## 확인한 것 (1~8)

**1. 시점.** `git log`: 절차 `docs/q1/M4_protocol.md` 는 커밋 `3a860c5` (2026-09-26 16:40:37Z), 구현 커밋 `390f3fc` (16:49:34Z, 절차 뒤), 산출물 커밋 `5d92955` 이 그 뒤. `M4_protocol.md` 를 건드린 커밋은 `3a860c5` 하나뿐 — 계산 후 절차를 고친 흔적 없음. 공식 `summary.json`: `"git_head": "390f3fc", "source_dirty": false` — 코드 커밋과 일치. **통과.**

**2. 코드 대 절차 일치.** 8개 규칙(`THRESHOLDS`={any:0,f01:.01,f10:.10,f25:.25,f50:.50}, center, rep_point, soft), `>` 비교(경계 테스트 `test_threshold_rules_are_strict`의 `exact` 케이스로 확인: 정확히 10%는 0), 굵은 칸 중심점(`coarse_grid.make_blocks`가 구성 100 m 칸 중심점의 면적가중 평균을 직접 계산해 `center_inside(polys, b.x, b.y)`에 넣음 — 100 m `center` 규칙을 집계한 게 아니라 굵은 칸 자체 중심으로 다시 판정), `rep_point` 경계 작은 번호(`np.minimum.at` 로 구현, `layer.sort_values("grid_id")` 순서 사용), 굵은 칸 정렬(`floor(minx/size + 1e-9)`, 100 m 정렬·크기 배수 검증 포함), 점수 평균 집계(`block_mean`, 결측 제외), 가중 AUC(`weighted_mid_cdf`/`weighted_auc`, 동점 절반), 포착(`capture_curve`, `soft`는 `p*area`, 이진은 `p`), 객체 AUC(비접촉 배경 `~block_any(touched,b)`, `touched`는 개발∪홀드아웃 흔적 전체), 생존(`survives`), 최소표본(`MIN_POS=5`, `MIN_OBJECTS=3`), 판정 3단계·관행 설정 `{any,center,f50}×100m`(`CONVENTIONAL`, `REFERENCE=("f10",100)`, `MATERIAL=0.02`) — 모두 절차 문서와 정확히 일치. `GATE={"auc_min":0.70,"top20_capture_min":0.50}`, `AREA_BINS`도 기존 모듈과 일치. **통과.**

**3. 해석적 분해의 수학.** 유도(A=Σp_iF(s_i)/Σp_i, π_ki 정규화, Σ_kW_kA_k=Σp_iF(s_i))를 직접 재유도해 확인 — 맞다. 세 항 분해는 임의의 중간값 X,Y에 대해 (A−X)+(X−Y)+(Y−Ã)=A−Ã 형태의 텔레스코핑이라 대수적으로 항상 성립하며, 실질은 X,Y(=mean A_k, mean Ã_k)를 어느 집합 S 위에서 잡느냐다. `decomposition.py:56`의 `S = (W > 0) & K`(K=Ã_k 유한)는 절차 §6 문면의 `S = {k: W_k>0}`보다 좁다(Ã_k가 NaN인 생존 객체를 제외). 공식 결과 3,456행 전부에서 `n_survive_no_At == 0`이므로 이 데이터에서는 두 정의가 동일해 수치에 영향 없음(확인: 아래 명령) — **낮은 심각도 지적**으로 아래에 기록. 반례(점수 결측 칸, 한 칸을 여러 폴리곤이 나눌 때, orphan)는 항목 아래 별도로 검토.

```
d = pd.read_csv(".../decomposition.csv"); (d["n_survive_no_At"]>0).sum() -> 0 / 3456
```

**4. 독립 재계산 (개발 사상만).** 아래 표. 100 m·500 m(독자 dissolve)·soft(쌍대 정의 직접 계산) 전부 부동소수 오차(≤9e-16) 안에서 공식 값과 일치. 객체 AUC는 배경 정의 차이(개발만 제외 vs 공식 개발+홀드아웃 제외)로 인한 설명 가능한 차이(1.65e-3)만 남음.

**5. 판정 재현.** `verdicts.csv`에서 decide() 규칙(참조 대비 flip, `|margin|≥0.02` 양쪽 material_flip)을 독립 pandas 코드로 재적용 → `flip`·`material_flip` 컬럼과 **불일치 0건**. 관행 설정(`{any,center,f50}×100m`) material_flip **0건**, 비관행/굵은 격자 **9건** → "C-c 부분 지지" 판정 재현 확인. **E* 축소 문제:** V2의 참조 설정 E*=7사상이지만, material flip 9건 중 4건(`center/1000, f25/1000, f50/500, f50/1000`)은 **n_events=1**(전부 `2024-09-20` 단일사상)로 줄어든 상태에서 나온 것이다. "중앙값"이 사실상 한 사상의 단일 관측값이며, 그 사상은 홀드아웃 양성 격자의 99%(1,254/1,267)를 차지하는 사상이라 강한 사상 특이적 편향(대규모 시가지 침수)을 반영할 수 있다. 이는 프로토콜 §7이 예견한 위험("V2 의 E* 는 설정마다 다를 수 있다")이 실제로 발현된 사례이며, `decide()`는 이를 구분하지 않고 그대로 "실질 뒤집힘"으로 센다. 코드가 틀린 건 아니지만(절차대로 정확히 구현됨), **판정 해석에 실질적 영향**을 준다 — 아래 지적 참조.

**6. 단위 검사.** `env -u CHANGWON_HOLDOUT_TESTS .venv/bin/python -m unittest discover -s tests` → **378개 전부 통과 (skipped=2, M4와 무관)**. `tests/test_m4.py` 단독 → **20/20 통과**. 항등식(`test_identity_all_rules_and_sizes`, 100/200/400 m × 8규칙), 규칙 경계(`test_threshold_rules_are_strict`의 정확히 10% 케이스), 판정 3단계(지지/부분지지/폐기 각각 별도 테스트) 전부 실제로 그 성질을 검사하는 실질 테스트다(트리비얼 assert 없음). **통과.**

**7. §6 코드 규칙.** AST로 10개 신규 파일 + 테스트의 모든 docstring을 검사 → 멀티라인 docstring **0건**(전부 한 줄). 코드 문단(빈 줄 구분 블록)마다 한 줄 주석 — 10개 파일 전부 수동 확인, 위반 없음. 파일 분리: 계산(`coarse_grid`, `trace_footprint`, `label_rules`, `weighted_auc`, `decomposition`, `m4_survival`, `m4_metrics`, `m4_decision`)과 실행(`m4_run.run()`)이 분리돼 있다. `AGENTS.md` §6 표에 M4 행이 정확히 추가됨. **통과.**

**8. 표현 규칙.** `M4_protocol.md`·M4 코드 8개 파일·`decision.json`·`summary.json` 에서 금지 표현(전향적·사전등록 검증·RF 가 검증됐다·10사상 일관·ML 우월·강수 역전 원인 확정·CDRI 우선순위 식별)을 grep — **0건**. 절차 §0의 "사전등록 검증이 아니다"는 부정문으로 금지 표현이 아니라 정직한 반박이다. **통과.**

## 지적

**[중간] `src/models/m4_decision.py:157`** — `decide()`의 `L1_material_flips`(`listing`) 이 `n_events`/`events` 열을 담지 않는다. `decision.json` 만 읽는 독자는 위 5번에서 지적한 n_events=1 단일사상 median(center/1000, f25/1000, f50/500, f50/1000)과 n_events=7~9의 견고한 median(any/500, any/1000, rep_point/500, rep_point/1000)을 구분할 수 없다. **고치는 법:** `listing = flipped[[..., "n_events", "events"]]` 로 두 열을 추가하고(둘 다 `table`에 이미 있음), `docs/q1/M4.md` 보고서에서 "부분 지지"의 9건 중 몇 건이 n_events=1인지 명시적으로 밝힐 것을 권고한다. 코드 버그는 아니고 출력 완성도 문제다.

**[낮음] `src/data/validation/decomposition.py:56`** — `S = (W > 0) & K` 가 절차 §6의 "S = {k: W_k>0}" 보다 좁다(Ã_k 유한 조건 추가). 공식 데이터에서 `n_survive_no_At=0`(3,456행 전부)이라 현재 수치에는 영향이 없지만, 다른 자료·설정에서 생존 객체 중 Ã_k가 NaN인 경우가 생기면 절차 문면과 코드 출력이 어긋난다. **고치는 법:** 절차 §6에 "S 는 W_k>0 이고 Ã_k 가 유한한 생존 객체(공정한 쌍대 비교를 위해)"라는 한 문장을 추가해 코드와 표기를 맞추면 충분하다(코드 쪽 변경은 불필요, 오히려 코드의 선택이 통계적으로 더 타당함).

**[낮음, 이론적 — 실발생 없음] `src/data/trace_footprint.py`·`decomposition.py`의 `center`/`rep_point` 규칙과 orphan 처리** — 굵은 칸의 `center` 판정은 구성 100 m 칸 중심점의 면적가중 평균이 실제 칸 합집합 기하 밖에 놓일 수 있는 비직선(L자형) 경계 칸에서, 그 폴리곤과 원래 겹치지 않는 칸을 양성으로 만들 수 있는 이론적 경우가 있다(`center_inside`가 footprint 겹침과 무관하게 임의의 점을 폴리곤에 직접 질의하기 때문). 코드는 이를 `orphan_mass`/`orphan_sum`으로 정확히 격리해 분해 항등식이 깨지지 않게 처리한다(반례를 만들어 원리 확인). 공식 결과에서는 8규칙×4크기×11사상×10점수(3,456행) 전부 `n_orphan_cells=0` — **실제로 발생하지 않음.** 지적이 아니라 확인 사항으로 남긴다.

**[낮음] `docs/q1/M4_protocol.md` §5 포착 정의** — "전체 양성 질량 합"이 점수 결측 칸의 양성 질량을 포함하는지 명시하지 않는다. 구현(`capture_curve`)은 결측 칸을 분자·분모 모두에서 제외한다(AUC와 같은 취급). 이 데이터에서는 결측 점수 칸이 극소수라 수치 영향은 미미할 것으로 보이나(직접 확인하지 않음, **미확인**), 절차 문서에 "AUC 와 같이 점수 결측 칸은 분모에서도 뺀다"는 한 문장을 추가하면 모호함이 없어진다.

**[문제 없음]** 격자 정렬 floor 연산의 부동소수 epsilon(`1e-9`)이 EPSG:5179 좌표(1e6~1e7)의 float64 상대오차(~2e-9) 대비 다소 좁을 수 있다는 이론적 우려를 확인했으나, 실제 굵은 칸 수(100/200/500/1000 m 각각 75400/19483/3393/942)가 절차 §3 표와 정확히 일치해 이 데이터에서는 문제가 없음을 실측으로 확인했다.

## 독립 재계산 표

| 항목 | 공식 값 | 재계산 값 | 차이 |
|---|---|---|---|
| 2012, f10, 100m, L1 cell_auc | 0.791091 | 0.791091 | 0 |
| 2012, f10, 100m, slope_neg cell_auc | 0.871715 | 0.871715 | 1.1e-16 |
| 2012, any, 100m, L1 cell_auc | 0.789444 | 0.789444 | 0 |
| 2012, any, 100m, slope_neg cell_auc | 0.844918 | 0.844918 | 1.1e-16 |
| 2012, f50, 100m, L1 cell_auc | 0.793407 | 0.793407 | 1.1e-16 |
| 2012, f50, 100m, slope_neg cell_auc | 0.904832 | 0.904832 | 2.2e-16 |
| 2014, f10, 100m, L1 cell_auc | 0.784220 | 0.784220 | 0 |
| 2014, any, 100m, L1 cell_auc | 0.782182 | 0.782182 | 2.2e-16 |
| 2014, f50, 100m, L1 cell_auc | 0.785159 | 0.785159 | 0 |
| 2019, f10, 100m, L1 cell_auc | 0.960892 | 0.960892 | 1.1e-16 |
| 2019, any, 100m, L1 cell_auc | 0.956407 | 0.956407 | 2.2e-16 |
| 2019, f50, 100m, L1 cell_auc | 0.971943 | 0.971943 | 0 |
| 2012, f10, **500m**(독자 dissolve/floor), L1 cell_auc | 0.778398 | 0.778398 | 1.1e-16 |
| 2019, f10, **500m**, L1 cell_auc (n_pos=3, 최소표본 미달) | 0.960177 | 0.960177 | 0 |
| 2012, **soft**, 100m, L1 cell_auc (쌍대 정의 Σp_iq_jH 직접) | 0.793526 | 0.793526 | 8.9e-16 |
| 2012, f10, 100m, L1 object_auc (공식: 개발+홀드아웃 접촉 제외 배경) | 0.803161 | — | — |
| 2012, f10, 100m, L1 object_auc (재계산: 개발 접촉만 제외 배경) | — | 0.804816 | **1.65e-3** (배경 정의 차이로 설명됨: 배경칸 74,550개 대 공식 값은 홀드아웃 접촉칸도 추가로 제외한 더 작은 배경) |
| 분해 항등식 (`identity_max_abs_diff`, 3,456행 전부) | ≤1e-9 요구 | 1.55e-15 (공식 report) | 통과 |
| n_orphan_cells (전 3,456행) | — | 0 (전부) | 이론적 우려 미발생 |
| decide() flip/material_flip 재현 (verdicts.csv 대비) | — | 0건 불일치 | 완전 재현 |

**한계·미확인:** 홀드아웃 자체는 규칙상 재계산하지 않았으므로(V1/`HOLDOUT_ALL`, 개발+홀드아웃 배경, 홀드아웃 사상 4개의 절대 수치) 이 부분은 공식 `against_official` 자체 검사(`m4_auc=0.435674.. == official 0.4357`, `same: true`)와 M1 정합성 체크(`max_abs_diff 7.8e-16`)만 신뢰했다 — 이는 코드 자체가 만든 자기검사이므로 완전한 독립 검증은 아니다. 절차 §5 포착 정의의 결측 칸 취급이 수치에 미치는 영향은 정량적으로 확인하지 않았다(미확인, 위 지적 참조). `center`/`rep_point` 규칙의 굵은 칸 orphan 이론적 가능성은 이 데이터셋에서만 부재를 확인했고 일반적 증명은 아니다.

---

## 리더 메모 (2026-09-26, 검토 원문 뒤에 덧붙임)

- 검토 대상 run `m4_20260926T164939Z_390f3fc` 는 리뷰 반영 뒤 `m4_20260926T170511Z_1edf87c` 로 대체했다. 두 run 의 차이는 `docs/q1/M4.md` 증거 절에 적었다.
- 검토 5번의 "2024-09-20 … (대규모 시가지 침수)"는 사실과 다르다. 이 사상의 격자 AUC 가중치는 97.6% 가 농업 폴리곤이고, 도심은 0.2% 다 (`docs/q1/M4.md` 분해 절). 결론(단일 사상 중앙값이라는 해석상 약점)은 그대로 받아들인다.
- 검토 5번은 1사상 뒤집힘을 4건으로 셌다. 3사상인 `center`·500 m 까지 넣으면 E\* ≤ 3 인 뒤집힘은 5건이다 (보고서 표기).
