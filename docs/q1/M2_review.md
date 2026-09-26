# M2 독립 검토 (읽기 전용)

판정: PASS

> 검토자: Claude Sonnet 서브 에이전트 (구현 모델과 다른 모델, AGENTS.md §1·§8). 홀드아웃 원본
> (`data/raw/flood_traces/changwon_info_disclosure_20260924/`)은 열지 않았고, 홀드아웃을 읽는 코드(`src.models.m1_run`, 홀드아웃 평가)는 실행하지 않았다.
> 읽은 결과표는 M1 파생표 `metrics_long.csv` 와 M2 공식 산출(`artifacts/q1/M2/m2_20260926T165115Z_1ffdde7/`)이다.
> 저장소 파일은 수정하지 않았고, 재계산 스크립트는 저장소 밖 스크래치 폴더에 두었다. 아래는 검토자 보고를 옮긴 것이다.

## 확인한 것

### 1. 시간 순서 (git log, summary.json)

```
a0e7cd1 2026-09-26 16:56:22 +0000  results(q1/M2): 공식 실행 산출과 보고   ← 리뷰 도중 추가
1ffdde7 2026-09-26 16:51:10 +0000  feat(q1/M2): … 실행 모듈과 단위 검사    ← 코드 커밋
e8f5b03 2026-09-26 16:42:28 +0000  docs(q1/M2): 계산 전 절차 고정         ← 절차 커밋
```

- 절차(16:42:28Z) → 코드(16:51:10Z) → 공식 실행 시작 16:51:15.989Z(`summary.json.started_utc`) → 결과 커밋(16:56:22Z). 순서가 맞다.
- `summary.json`: `"git_head": "1ffdde7"`, `"source_dirty": false`.
- `git diff cloud-base..cloud/M2 --stat` 로 변경 파일 22개를 확인했다. 범위 밖 파일(`data/raw/**`, `data/processed/**`, 홀드아웃)은 없다.
  `AGENTS.md` 는 §6 표 2행 추가뿐이다.

### 2. 코드 대 절차 정합성

`meta_analysis.py`·`m2_effects.py`·`m2_pooling.py`·`m2_decision.py` 를 절차 §2~§6 과 한 줄씩 대조했다.
- SE 역산 `(logit(hi)−logit(lo))/(2×1.959964)` — 절차식과 같다.
- 포함 규칙 §3 의 다섯 조건이 `effects()` 의 `np.select` 에 그대로 있다.
- REML 음의 제한 로그우도가 표준식과 같다. 경계 τ² = 0 비교, 상한 U 가 절차식과 같다.
- 수정 HKSJ `SE_HK = √(max(1, q)/Σw*)`, `t_{k−1, 0.975}` — 절차와 같다. 원래 HKSJ 도 따로 구현돼 단위 검사로 서로 비교된다.
- 예측구간: k ≥ 3 에서 `t_{k−2}·√(τ̂² + 1/Σw*)`, k < 3 이면 비운다 — 같다.
- I² 는 Higgins–Thompson(Q 만의 함수)이다. 그래서 같은 부분집합의 주(REML)와 S1(DL) 행의 I² 가 같다. 정의상 맞다.
  구간은 Q-profile τ² 를 `τ²/(τ²+s²)` 로 옮긴다 — 절차와 같다.
- k 규칙(k = 1 통합 안 함, k = 2 예측구간 없음), 짝 분산 `SE_m² + SE_b² − 2ρSE_mSE_b`, 비교쌍 9개가 절차와 같다.
- 민감도 S1·S2·S3·S5 가 모두 구현돼 출력된다. 판정 R2~R5 의 부등호·문구가 절차 §6 과 같다.

### 3. 독립 재계산 (저장소 통합 코드를 쓰지 않은 자체 구현)

```
slope_neg  cell_gate development k=6 mu=2.163463 ci=(1.559206,2.767721) tau2=0.263083 i2=0.888244  |Δ|≤8e-9
slope_neg  cell_gate holdout     k=2 mu=2.010776 ci=(-3.610003,7.631555)                            |Δ|≤4e-10
rf_F1_wf   cell_gate development k=5 mu=1.953040 ci=(1.075986,2.830095)                             |Δ|≤1e-15
L1         cell_gate development k=6 mu=1.161014 ci=(-0.437966,2.759995) tau2=2.195803              |Δ|≤7e-8
DIFF rf−slope cell_gate combined(ρ=0)  k=7 mu=-0.140923 ci=(-0.906940,0.625095)                      |Δ|≤2e-8
DIFF rf−slope object    development    k=5 mu=-0.131156 ci=(-1.081049,0.818738)                      |Δ|≤7e-12
DIFF rf−slope object    holdout        k=4 mu=+0.186204 ci=(-0.095710,0.468118)                      |Δ|=0
```

모두 logit 척도 1e-6 안이다. 이 값으로 R2(경사 개발 "사상 수준 통과", 홀드아웃 "점추정만 통과"), R3("구분되지 않는다"),
R4("쓰지 않는다")를 규칙에 대입해 `decision.json` 과 같음을 확인했다.

### 4. S4 재현

- 개발 전용 점검을 다시 실행했다: `abs_diff_auc` 1.1e-16, `abs_diff_ci` 0.0 (`se_check.csv` 와 같다), `holdout_read: False`.
- 읽은 흔적 파일은 `changwon_info_disclosure_20260916/…L100·L110` 과 `safetydata_dssp_if_00117/…gpkg` 뿐이다. 홀드아웃 경로는 없다.
- S4 입력 5개 파일의 `sha256sum` 이 `summary.json.se_check.input_sha256` 과 같다.

### 5. §6 코드 규칙

여러 줄 docstring 0건(스크립트로 전수 검사). 문단별 한 줄 주석이 지켜진다. 파일 분리가 §6 표와 같다.
`meta_analysis.py` 는 M3 등에서도 쓸 공통 통계 모듈이라 §6-2 취지에 맞다.

### 6. 단위 검사

`env -u CHANGWON_HOLDOUT_TESTS PYTHONPATH=. .venv/bin/python -m unittest tests.test_m2 tests.test_meta_analysis` → 14개 통과.
BCG 참조값을 statsmodels(DL τ² 0.30876026, μ −0.71411722, SE 0.17874209)와 PyMARE(REML τ² 0.31324327, HKSJ 구간 (−1.108444, −0.320621))로
따로 재현했다. 검사의 참조값은 자기 참조가 아니다.

### 7. 통계적 사항

- `tau2_outside_qprofile` 5행: 추정량(REML·DL)과 Q-profile 구간이 어긋나는 알려진 현상이다. 버그가 아니다. 보고서 §2 각주에 공개돼 있다.
- 절차 §4.1 의 "ρ = 0 은 보수적" 가정: S4 실측 상관 2012 0.35, 2014 0.90, 2016 0.48, 2019 0.90, **2025 −0.59**. 한 사상에서 반증된다.
  보고서 §8·리더 판단 3 에 공개돼 있다. 짝지은 재표본 SE 로 다시 통합해도(−0.024 [−1.183, +1.135]) R3 분류는 같다.

## 지적

| 번호 | 심각도 | 위치 | 내용 | 제안 |
|---|---|---|---|---|
| 1 | 낮음 | `src/models/m2_effects.py: effects()` | 짝 `cell_gate` 행이 없어 `n_pos_cells` 가 NaN 인 격자형 행도 사유가 `positive_cells_lt_5` 로 찍힌다. 이번 자료에는 해당 사례가 없다 | 별도 사유(`cell_gate_missing`) |
| 2 | 낮음 | `src/models/m2_run.py: se_check()`, `s4_pooled()` | 실행 흐름 파일 안에 자료 병합·모델 로딩 같은 준비 로직이 꽤 있다. 통계 계산은 `m2_se_check.py`·`m2_pooling.py` 에 있어 위반은 아니다 | 다음 분리 때 준비 로직을 `m2_se_check.py` 로 옮기는 것을 고려 |
| 3 | 정보 | 보고서 §2 각주, `pooled.csv.tau2_outside_qprofile` | 추정량 불일치 5행. 공개돼 있고 원인이 타당하다 | 조치 불필요 |
| 4 | 정보 | 절차 §4.1 | ρ 가정 반증. 공개돼 있고 R3 에 영향 없음. 절차 문서는 고치지 않는 것이 맞다 | `V.evaluate` 가 재표본 값을 저장하면 근사와 ρ 가정이 필요 없어진다는 리더 판단 4 에 동의 |

## 한계

- 덩어리 재표본 알고리즘 자체는 독립 재구현하지 않았다. M1 저장값 재현과 `tests/test_m2.py::SeCheckTest`(기존 `uncertainty` 모듈과 대조)에 의존했다.
- Q-profile 상한 확장(`upper *= 10`)이 극단 자료에서 실패할 가능성은 코드로만 봤다. 이번 출력의 τ² 상한은 모두 유한했다.
- 리뷰 도중 브랜치 끝이 `1ffdde7` → `a0e7cd1` 로 움직였다. 추가된 산출·보고 커밋의 diff 도 함께 봤다. 공식 산출 자체는 바뀌지 않았다.
