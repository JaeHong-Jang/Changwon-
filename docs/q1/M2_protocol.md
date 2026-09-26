# M2 절차 — 사상 단위 보고: 유효 표본과 무작위효과 통합 (계산 전 고정)

> 과제 정의: `docs/CLOUD_TASKS.md` M2. 규칙: `AGENTS.md` §2·§6·§8.
> 이 문서는 **효과 크기·표준오차·포함 규칙·통합 모형·판정 규칙을 통합 계산 전에 고정**하려고 커밋한다.
> 이 커밋 전에 M2 의 어떤 통합값(무작위효과 평균·τ²·I²·예측구간)도 계산하지 않았다.
> 커밋 전에 본 것: M1 보고서(`docs/q1/M1.md`)의 사상별 표·중앙값, `metrics_long.csv` 의 열 구조와
> `slope_neg` 전 격자 행(사상별 AUC·95% 구간·양성 격자 수·덩어리 수).

## 0. 지위와 입력

- **post-hoc.** M1 의 사상별 결과(홀드아웃 포함)를 이미 본 뒤에 설계했다. M2 는 새 점수를 만들지 않고
  M1 사상별 결과를 다시 요약한다. M1 의 사전 판정(C-b 폐기)은 M2 결과로 바꾸지 않는다.
- **입력 (주 분석):** `artifacts/q1/M1/m1_20260926T160821Z_a181f6c/metrics_long.csv` 만 읽는다. SHA256 을 실행 기록에 남긴다.
  홀드아웃 원본은 읽지 않는다.
- **입력 (표준오차 점검, §5 S4):** 개발 흔적 원본, 가공 스냅샷(`layer1_flood.gpkg`, `grid_features.parquet`),
  M1 `hand.parquet`, 동결 모델 설정. 홀드아웃 원본은 읽지 않는다.
- 대상 점수는 M1 과 같은 10개다 (`M1_protocol.md` §2).

## 1. 사상과 집합

- 사상 = M1 의 `test_event`. 개발 6개(2006, 2012, 2014, 2016, 2019, 2025), 홀드아웃 4개(2022-09-06, 2023-08-10, 2024-07-24, 2024-09-20).
- **유효 표본은 사상이다.** 모든 통합 행에 사상 수 k 를 적고, 격자·덩어리·폴리곤 수는 참고 열로만 둔다.
- 통합 집합:
  - `development`: 개발 사상만 (주)
  - `holdout`: 홀드아웃 사상만 (주)
  - `combined`: 둘 다 (참고). 해석은 `development`·`holdout` 을 따로 한다. 단, §6 R3 은 M1 주 판정과 같은 사상 집합(E\*)을 쓰려고 `combined` 를 쓴다.

## 2. 효과 크기와 표준오차

- 효과 크기: y = logit(AUC). logit 척도는 C 통계량 통합에서 사상 간 정규성을 더 잘 맞춘다 (Snell et al. 2018; Debray et al. 2017).
- 표준오차: M1 은 재표본 분포 대신 95% 백분위 구간(`ci_lo`, `ci_hi`, n_boot = 1000, seed 42)만 저장했다. 그래서
  **SE = (logit(ci_hi) − logit(ci_lo)) / (2 × 1.959964)** 로 되돌려 구한다. 이 SE 는 M1 재표본 구간에서 나온 부트스트랩 SE 의 정규 근사다.
  - 격자 AUC(`cell_gate`) 구간: 양성 덩어리(150 m 연결) 재표본. 음성 격자는 고정된다.
  - 객체 AUC(`object`) 구간: 사상 안 폴리곤 재표본.
  - 덩어리 AUC(`cluster_gate`) 구간: 양성 덩어리 재표본, 덩어리 1표.
- 백분위 구간이 logit 척도에서 비대칭이면 이 근사는 틀린다. 그 크기를 §5 S4 에서 개발 사상으로 잰다.
- 상위 20% 포착률은 M1 에 구간이 없어 통합하지 않는다.

## 3. 포함 규칙 (점수 × 단위 × 층 × 사상)

한 사상의 효과 크기는 다음을 모두 만족할 때만 통합에 넣는다. 빠진 행은 이유와 함께 `effects.csv` 에 남긴다.

1. `storm == "ALL"`, `metric == "observed-label_auc"`, 값이 유한하고 0 < AUC < 1.
2. 최소 표본 (M1 과 같다): 격자형 단위(`cell_gate`, `cluster_gate`)는 같은 점수·층·사상의 `cell_gate` 양성 격자 ≥ 5,
   `object` 는 폴리곤 ≥ 3.
3. 구간이 유한하고 0 < `ci_lo` < `ci_hi` < 1 (logit 이 유한하고 SE > 0).

## 4. 통합 모형

y_e = μ + u_e + ε_e, u_e ~ N(0, τ²), ε_e ~ N(0, SE_e²).

- **주 방법:** τ² 는 REML (Veroniki et al. 2016; Debray et al. 2017). μ 의 95% 구간은 수정 HKSJ
  (Hartung–Knapp–Sidik–Jonkman, IntHout et al. 2014; 수정은 Röver et al. 2015):
  q = Σ w\*(y − μ̂)² / (k − 1), SE_HK = √(max(1, q) / Σ w\*), 구간 μ̂ ± t_{k−1, 0.975} × SE_HK, w\* = 1 / (SE² + τ̂²).
  - REML: 제한 로그우도를 τ² ∈ [0, U] 에서 최대화한다 (U = max(1, 10 × 분산(y), 10 × max SE²); 경계 τ² = 0 도 비교).
- **민감도 방법 (S1):** DerSimonian–Laird τ² (DerSimonian & Laird 1986), μ 의 Wald z 구간.
- **예측구간 (k ≥ 3):** μ̂ ± t_{k−2, 0.975} × √(τ̂² + 1/Σ w\*) (Riley et al. 2011). k ≤ 2 이면 비운다.
- **이질성:** Cochran Q (고정효과 가중치 1/SE²), 자유도 k − 1, p 값. I² = max(0, (Q − (k − 1)) / Q) (Higgins & Thompson 2002).
  I² 의 95% 구간은 τ² 의 Q-profile 구간(Viechtbauer 2007)을 I² = τ² / (τ² + s²), s² = (k − 1) Σw / ((Σw)² − Σw²) 로 옮긴다.
  τ̂ (logit 척도)도 함께 싣는다.
- **k 규칙:** k = 1 이면 통합하지 않고 그 사상 값만 싣는다. k = 2 는 계산하되 "k = 2: τ² 불안정, 예측구간 없음" 으로 표시한다.
- **역변환:** μ̂·구간·예측구간은 expit 로 AUC 척도에 싣는다.
- **유효 표본 보고 (기술 통계):** 각 통합 행에 k, 양성 격자·덩어리·폴리곤 합, 고정효과(1/SE²)·무작위효과(w\*) 가중치 각각의
  최대 비중과 그 사상, Kish 유효 사상 수 (Σw)² / Σw². 비교용으로 사상 동일가중 평균, 양성 격자 수 가중 평균("격자 1표" 근사),
  사상 중앙값(M1 방식)을 함께 싣는다.

### 4.1 짝 비교 (모델 − 기준선)

- d_e = logit(AUC_모델,e) − logit(AUC_기준,e). 두 점수 모두 §3 을 통과한 사상만 쓴다.
- M1 은 짝지은 재표본을 저장하지 않았다. 그래서 v_e = SE_모델² + SE_기준² − 2ρ SE_모델 SE_기준 으로 두고
  **주 분석은 ρ = 0** 이다. 같은 덩어리 재표본을 쓰는 두 AUC 는 양의 상관이므로 ρ = 0 은 사상 안 분산을 크게 잡는다.
  민감도 S3: ρ = 0.5, 0.8. S4 의 개발 사상 재표본에서 실제 상관을 잰다.
- 비교 쌍: `rf_F1_wf` − 기준선 6개, `logit_F1_wf`·`L1`·`z_sensitivity` − `slope_neg`.
- 통합은 §4 와 같다 (REML + 수정 HKSJ, 민감도 DL + Wald).

## 5. 민감도·점검 (결과를 보고 고르지 않는다, 전부 싣는다)

- **S1** DL + Wald z 구간.
- **S2** 격자형 단위에서 양성 덩어리 < 5 인 사상을 뺀 통합 (같은 점수·층·사상의 `cluster_gate` `n_units`).
- **S3** 짝 비교의 ρ = 0.5, 0.8.
- **S4 표준오차 점검 (개발 사상만, 홀드아웃을 읽지 않는다):** 개발 6사상 × 10점수, 전 격자, 격자 AUC 에 대해
  M1 과 같은 라벨(10% 규칙, 합집합 면적)·점수(기준선은 특징표·`hand.parquet`, RF·로지스틱은 `m1_scores.trained_before`)·
  덩어리 재표본(n_boot = 1000, seed 42)을 다시 만든다.
  - 점 AUC 와 95% 구간이 `metrics_long.csv` 와 같은지 (최대 절대차).
  - 재표본 logit 값의 표준편차(SE_draw, ddof = 1)와 §2 의 SE_ci 의 비.
  - SE_draw 로 개발 집합을 다시 통합한 μ̂·구간 (주 분석과 나란히).
  - 각 점수와 `slope_neg` 의 재표본 logit 값 상관 (§4.1 ρ 의 실제값).
  - logit 이 무한인 재표본(AUC = 0 또는 1)은 빼고 그 수를 적는다.
- **S5 한 사상 빼기:** §6 R3·R4 의 짝 비교에서 사상을 하나씩 뺀 통합과 판정.

## 6. 사전 판정·보고 규칙

- **R1 유효 표본 명시.** 보고서의 모든 통합 수치 옆에 "k 사상"을 적는다. 격자 수를 표본 크기로 쓰지 않는다.
- **R2 게이트의 사상 수준 표현** (격자 AUC, 전 격자, 점수 × {`development`, `holdout`}). 게이트 0.70 은 낮추지 않는다.
  - 통합 95% 구간 하한 ≥ 0.70 → "사상 수준 통과"
  - μ̂ ≥ 0.70 이고 하한 < 0.70 → "점추정만 통과"
  - μ̂ < 0.70 → "미달"
  - k = 1 → "통합 불가" (그 사상 값만 보고)
  - 예측구간 하한 ≥ 0.70 이면 "새 사상에서도 게이트 위로 예측됨"을 덧붙인다. 아니면 "새 사상에서 게이트 아래 가능".
- **R3 C-b 의 사상 수준 재표현** (`rf_F1_wf` − `slope_neg`, 격자 AUC, 전 격자, `combined` = M1 의 E\*, ρ = 0, 주 방법).
  - 95% 구간이 0 을 포함 → "RF 와 경사는 사상 수준에서 구분되지 않는다" (M1 판정 C-b 폐기와 같은 방향).
  - 구간 전체 > 0 → "사상 수준에서 RF 가 높다". M1 사전 판정(폐기)과 충돌하므로 둘 다 싣고 판정은 바꾸지 않는다.
  - 구간 전체 < 0 → "사상 수준에서 경사가 높다".
  - `development`·`holdout` 따로 한 값도 싣는다 (판정에 쓰지 않는다).
- **R4 객체 AUC 의 RF 쪽 결과를 따로 쓸지** (M1 보고 "리더 판단 필요" 3번). `rf_F1_wf` − `slope_neg`, 객체 AUC, 전 격자, ρ = 0, 주 방법.
  - `development` 와 `holdout` **각각**에서 구간 하한 > 0 이면 → "객체 AUC 에서 RF 가 경사보다 높다"를 결과로 쓴다.
  - 아니고 두 집합 μ̂ 가 모두 > 0 이면 → "방향은 RF 쪽이나 사상 수준에서 구분되지 않는다"로만 쓴다.
  - 그 밖 → 쓰지 않는다 (표에만 둔다).
- **R5 이전 가능성 (기술).** 점수마다 홀드아웃 사상별 AUC(격자·객체)가 `development` 통합의 95% 예측구간 안에 드는지 센다.
- 결과를 본 뒤 규칙·방법·포함 기준을 바꾸면 `post-hoc` 으로 표기하고 이 절차의 결과를 함께 싣는다.

## 7. 산출과 출처

- 코드: `src/data/validation/meta_analysis.py`(무작위효과 통합), `src/models/m2_effects.py`(효과 크기·포함 규칙·짝 비교),
  `src/models/m2_pooling.py`(집합별 통합·민감도·한 사상 빼기), `src/models/m2_decision.py`(R2~R5),
  `src/models/m2_se_check.py`(S4, 개발만), `src/models/m2_forest.py`(숲 그림), `src/models/m2_run.py`(실행).
- 실행: `PYTHONPATH=. .venv/bin/python -m src.models.m2_run` (클라우드 리더).
- 산출: `artifacts/q1/M2/<run_id>/` — `effects.csv`, `pooled.csv`, `pooled_diff.csv`, `loo.csv`, `transport.csv`,
  `se_check.csv`, `decision.json`, `summary.json`, `forest_grid_auc.png`.
- 보고: `docs/q1/M2.md` (AGENTS §4 형식).

## 8. 문헌 (DOI 는 출판사·PubMed 쪽 URL 로 확인, 2026-09-26. Crossref API 는 클라우드 네트워크에서 막혀 쓰지 못했다)

- Debray T.P.A. et al. (2017) A guide to systematic review and meta-analysis of prediction model performance. BMJ 356:i6460. doi:10.1136/bmj.i6460
- Snell K.I.E. et al. (2018) Meta-analysis of prediction model performance across multiple studies: which scale helps ensure between-study normality for the C-statistic and calibration measures? Stat Methods Med Res. doi:10.1177/0962280217705678
- DerSimonian R., Laird N. (1986) Meta-analysis in clinical trials. Control Clin Trials 7:177–188. doi:10.1016/0197-2456(86)90046-2
- Higgins J.P.T., Thompson S.G. (2002) Quantifying heterogeneity in a meta-analysis. Stat Med 21:1539–1558. doi:10.1002/sim.1186
- IntHout J., Ioannidis J.P.A., Borm G.F. (2014) The Hartung-Knapp-Sidik-Jonkman method for random effects meta-analysis is straightforward and considerably outperforms the standard DerSimonian-Laird method. BMC Med Res Methodol 14:25. doi:10.1186/1471-2288-14-25
- Röver C., Knapp G., Friede T. (2015) Hartung-Knapp-Sidik-Jonkman approach and its modification for random-effects meta-analysis with few studies. BMC Med Res Methodol 15:99. doi:10.1186/s12874-015-0091-1
- Viechtbauer W. (2007) Confidence intervals for the amount of heterogeneity in meta-analysis. Stat Med 26:37–52. doi:10.1002/sim.2514
- Veroniki A.A. et al. (2016) Methods to estimate the between-study variance and its uncertainty in meta-analysis. Res Synth Methods 7:55–79. doi:10.1002/jrsm.1164
- Riley R.D., Higgins J.P.T., Deeks J.J. (2011) Interpretation of random effects meta-analyses. BMJ 342:d549. doi:10.1136/bmj.d549
