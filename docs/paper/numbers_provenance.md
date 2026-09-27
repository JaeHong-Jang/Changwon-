# 원고 수치 출처 표 (M7)

> 규칙: `docs/q1/M7_protocol.md` §4. 원고 `docs/paper/manuscript_en.md` 와 한국어 요약 `docs/paper/summary_ko.md` 의 모든 수치가 여기에 있다.
> 새 계산은 없다. 값은 아래 run 의 저장 산출에서 읽었고, 리더가 일회성 확인으로 대조했다 (저장소 밖 scratchpad).
> 약어: HO = 홀드아웃(2022~2024), DEV = 개발 사상, `f10` = 10% 초과 겹침 규칙, 100 m 참조 설정.

## 0. run 목록

| 약칭 | run_id | 경로 | 명령 |
|---|---|---|---|
| HO | `holdout_20260924T100939Z_ae9c122-dirty_cf388a23` | `artifacts/evaluation/holdout_2022_2024/<run_id>/summary.json`, `metrics.csv` | `python -m src.models.holdout_eval` |
| HO-rerun | `holdout_20260926T164805Z_7f7968f_84ef30a7` | 같은 폴더 | 같음 (M6) |
| AUDIT | `label_audit_development_20260924T104040Z_1b8106ba`, `label_audit_holdout_20260924T104628Z_1b8106ba` | `artifacts/evaluation/label_audit/*_summary.json` | `python -m src.models.label_audit` |
| M1 | `m1_20260926T160821Z_a181f6c` | `artifacts/q1/M1/<run_id>/` | `PYTHONPATH=. .venv/bin/python -m src.models.m1_run --n-boot 1000` |
| M2 | `m2_20260926T165115Z_1ffdde7` | `artifacts/q1/M2/<run_id>/` | `… -m src.models.m2_run --n-boot 1000` |
| M3 | `m3_20260926T164916Z_f383cb3` | `artifacts/q1/M3/<run_id>/` | `… -m src.models.m3_run --n-boot 1000` |
| M4 | `m4_20260926T170511Z_1edf87c` | `artifacts/q1/M4/<run_id>/` | `… -m src.models.m4_run` |
| M4S | `m4s_20260926T175809Z_3e8bc1c` | `artifacts/q1/M4S/<run_id>/` | `… -m src.models.m4s_run` |
| M6 | `m6_20260926T164903Z_7f7968f` | `artifacts/q1/M6/<run_id>/` | `… -m src.repro.m6_run` |
| CDRI | `posthoc_h_20260926T134611Z_3d14fc1` | `artifacts/posthoc/20260926/<run_id>/summary.json` | `python .omc/posthoc_h/compare.py --holdout` |
| FC | `trigger_20260926T125638548044Z_684161e`, `combined_20260926T125729Z_684161e` | `docs/FORECAST_RESULTS.md` | 같은 문서 표 |

## 1. 자료·연구 지역 (원고 §2)

| 원고 위치 | 값 | 출처 |
|---|---|---|
| §2.1, 초록 | 75 400 칸, 100 m, EPSG:5179 | M4 절차 §3 표 (100 m 칸 수), `docs/research_reports/00_context_brief.md` |
| §2.1 | 약 747 km² | `00_context_brief.md` 첫 줄 |
| §2.1 | 90 m DEM (2025 판) | `docs/q1/M6_chronology.md` I3, CLOUD_TASKS 공통 배경 |
| §2.2 | 관측소 29곳, 2015~2024, 지표 4개, 민감도 8개와 부호 | `docs/METHODOLOGY.md` §3.2·§3.4, `src/stages/h06_layers.py` `SENSITIVITY_SPEC` |
| §2.2, 부록 D | 게이트 기록 2026-08-19, 코드 상수 2026-09-07, L1 마지막 변경 2026-09-08, 개발 게이트 2026-09-16 | M6 `chronology.csv` F1·F3·F4·F5 (`docs/q1/M6_chronology.md`) |
| §2.2 | 개발 L1 0.750 [0.633, 0.863], 포착 0.544 | HO `summary.json` → `development_gates.L1` (0.7504, [0.633, 0.8625], 0.5436) |
| §2.3 | API 125 폴리곤(2006~2019), 2025 18개, 날짜 있는 143개 중 142개 영역 안, 날짜 없는 2개 | M4 `events.csv` (n_polygons), `survival_summary.csv` (development n 142, n_outside_domain 1), AUDIT 개발 145 |
| §2.3 | HO 5·3·5·183 = 196, 합집합 9.55 km², 도심 57·농업 119·미상 20 | `docs/METHODOLOGY.md` §7.6 (HO run), M4 보고 가중치 몫 표 |
| 표 1 | 사상별 폴리곤·양성 칸·덩어리 | M4 `events.csv` (`f10`, 100 m) |
| §2.3 | 1 254 / 1 267 | M4 `events.csv` |
| §2.4 | 연대표 순서, 18:18·18:38 KST, RF 재선택 10분 뒤 | M6 `chronology.csv` S1·S2·D1 |

## 2. 결과 4.1 (게이트)

| 원고 위치 | 값 | 출처 |
|---|---|---|
| 초록, §4.1 | L1 격자 0.436 [0.386, 0.596], 덩어리 0.603 [0.544, 0.661], 포착 0.073 | HO `summary.json` → `gates.L1` |
| §4.1 | 시 예상도 0.450 / 0.026, 과거 흔적 근접도 0.532 / 0.205 | HO `gates.city_flood_map`, `gates.past_flood_pre2022` |
| 표 2 상단, 초록 | 32 설정 V1 AUC / 포착, 전부 탈락, 여유 −0.088 ~ −0.500, 포착 최대 0.412 | M4 `verdicts.csv` (verdict V1, score L1) |
| 표 2 하단 | V2 여유와 사상 수 | M4 `verdicts.csv` (verdict V2, score L1) |
| §4.1 | V2 참조 0.791 / 0.558 (7사상) | `docs/q1/M4.md` 주 판정 절 (M4 `decision.json`) |
| §4.1 | 실질 뒤집힘 9개, 그중 5개는 1~3사상 | M4 `verdicts.csv` `material_flip` (V2, L1) = 9, `decision.json` `n_events` |
| §4.1 | 10개 점수의 규칙만·크기만 실질 뒤집힘 0 | M4 `verdicts.csv` `config_class` 별 `material_flip` 합 (V1: rule_only 0, size_only 0; V2: rule_only 0, size_only 0) |
| §4.1 | 100 m 규칙 사이 L1 0.394~0.694 (범위 0.300), 32 설정 0.339~0.694, RF 범위 0.023, L1 순위 8~10위 | `docs/q1/M4.md` AUC 범위 표·순위 문장 (M4 `verdicts.csv`, `ranking.csv`) |

## 3. 결과 4.2 (분해)

| 원고 위치 | 값 | 출처 |
|---|---|---|
| §4.2 | 항등식 2 828 조합, 최대 오차 1.6e-15 | M4 `summary.json` → `checks` (`docs/q1/M4.md` 재현 표) |
| 표 3, 초록 | 규칙별 격자 AUC·세 항·n_eff·생존 객체, 객체 0.712 | M4 `decomposition.csv` (test_event HOLDOUT_ALL, score L1, size 100) |
| 표 4, 초록 | 가중치 몫 0.988·0.976·0.002, 도심 생존 7, 객체 값 Ã 평균 | `docs/q1/M4.md` 가중치 몫 표 (M4 `object_contrib.parquet`) |
| §4.2 | ≥ 20 000 m² 몫 0.898, 상위 10개 0.533, `any` 도심 몫 0.043 | `docs/q1/M4.md` 분해 절 |
| §4.2 | 도심 0.910 [0.879, 0.938], 농업 0.608 [0.574, 0.642] (폴리곤 1표 AUC) | HO `metrics.csv` (`docs/METHODOLOGY.md` §7.6 표) |
| §4.2 | 다른 점수 크기 가중 항 +0.046 ~ +0.085, 개발 L1 격자−객체 −0.012 ~ +0.053 | `docs/q1/M4.md` 분해 절 (M4 `decomposition.csv`) |
| 표 5, §4.2 | 면적 구간·크기별 생존율, HO 0.663, 도심 0.123, 개발 0.958 → 0.479 | M4 `survival_summary.csv` |
| 표 5 주석 | 66.3 %, 도심 12.3 % | AUDIT 홀드아웃 요약 |

## 4. 결과 4.3 (가상 자료)

| 원고 위치 | 값 | 출처 |
|---|---|---|
| §3.5, 초록 | 115 시나리오 × 복제 200 | M4S `scenarios.csv`, `summary.json` |
| §4.3 | 항등식 7.0e-15, 공분산 형태 1.4e-12 (150 396 행) | M4S `summary.json` → `identity`, `decision.json` → `P1` |
| §4.3 | P2: β = 0 21개, 최대 0.006 (`f10`)·0.009 (`soft`) | M4S `decision.json` → `P2` |
| §4.3 | P3·P3′: 15개 벌어짐·부호 일치, 8개 없음 | M4S `decision.json` → `P3`, `P3_prime` |
| §4.3 | 실현/Δ\* `soft` 0.94 (0.86~1.06, 24개), `f10` 0.74 (0.63~0.83) | `docs/q1/M4S.md` 결과 요약 |
| 표 6 | σ × β 차이 중앙값·P10, Δ\* | M4S `summary_by_scenario.csv` (묶음 A, n = 200, `f10`), Δ\* 는 M4S 절차 §5.3 표 |
| §4.3 | C1 합계 −0.12 ~ −0.17 | `docs/q1/M4S.md` 묶음 C1 표 |
| §4.3 | 묶음 D: μ0 1.45 β −1 통과 0 %·뒤집힘 1.00, β −0.5 0.62, μ0 0.55 β +0.5 95.5 % | `docs/q1/M4S.md` 게이트 뒤집힘 절 |
| §4.3 | S3 틀림: 시나리오 59 −0.0505, 61개 중 60개 맞음 | M4S `decision.json` → `secondary` |
| §4.3 | |V1 − V2| ≤ 0.012 | `docs/q1/M4S.md` 묶음 B 절 (`event_aggregation.csv`) |
| §4.3 | V2 0.791 | M4 (위 2절) |
| §4.3 | 2024-09-20 L1 β̂ −0.83, 개발 |β̂| ≤ 0.17 | M4S `anchors.csv` |
| §4.3 | Spearman 0.885 (50쌍), σ̂ 2.46, β̂ −0.80, Δ̂\* −0.406, 관측 −0.276, 상위 10% 몫 0.73 (가상 0.74), ρ −0.48, sd 0.21, 집중 인수 2.02, 불투수 −0.434 대 −0.194 | M4S `anchors.csv`, `docs/q1/M4S.md` 창원 기준점 절 |

## 5. 결과 4.4 (기준선·사상 통합·중첩 선택)

| 원고 위치 | 값 | 출처 |
|---|---|---|
| 표 7, 초록 | 사상별 경사·RF, 중앙값 0.872 / 0.855, 짝 차이 중앙값 +0.030 | M1 `decision.json` → `primary` (0.8717, 0.8546, 0.0298) |
| §4.4 | 경사·HAND·TWI 8/8 게이트, L1 AUC 5/8·포착 4/8 | M1 `median_table.csv` (`n_pass_gate`, stratum ALL) |
| §4.4 | RF − 경사 logit −0.141 [−0.907, +0.625], 객체 개발 −0.131 [−1.081, +0.819], HO +0.186 [−0.096, +0.468] | M2 `pooled_diff.csv`, `decision.json` → `R3_cb`, `R4` |
| §4.4 | RF − 상대고도만 0 제외 | `docs/q1/M2.md` §5 |
| §4.4, 표 E2 | 개발 통합 AUC·예측구간·I² | M2 `pooled.csv` (unit cell_gate, stratum ALL, set development, variant main) |
| §4.4 | HO k = 2: 경사 [0.026, 1.000], RF [0.326, 0.987] | M2 `pooled.csv` (set holdout) |
| §4.4 | L1 HO 요약 0.438 / 0.648 / 0.632 | `docs/q1/M2.md` §1 요약 방식 표 |
| §4.4, 표 E1 | 층별 중앙값, 2024-09 양성 1 112/1 254 AGRI | M1 `median_table.csv`, `docs/q1/M1.md` 층별 절 |
| §4.4 | 중첩 0.865, 고정 0.873 (차 0.008), 모델군 0.841 (−0.032), 포착 0.902 → 0.761, F0 4번, 경사 0.892 | M3 `decision.json`, `median_table.csv`, `selected.json` |
| §4.4 | 짝 상관 가정: 2025 에서 음의 상관 | `docs/q1/M2.md` §8 (`se_check_pairs.csv`) |

## 6. 결과 4.5·4.6

| 원고 위치 | 값 | 출처 |
|---|---|---|
| §4.5, 초록 | 노출 축 개발 0.389 [0.267, 0.528], HO 0.147 [0.086, 0.341] | HO `development_gates.z_exposure`, `gates.z_exposure` |
| §4.5 | 민감도 축 0.869 / 0.735 | HO `development_gates.z_sensitivity`, `gates.z_sensitivity` |
| §4.6 | 게이트 값 동일 (L1 0.4357 / 0.6025 / 0.0734), 1 966 / 5 670 행, 1.8e-12, 2.0e-13 km², EPSG:5186/5187 | M6 `holdout_compare.json`, `docs/q1/M6.md` A 절 |

## 7. 논의·부록

| 원고 위치 | 값 | 출처 |
|---|---|---|
| §5.3 | RF-F1 (2019까지) 0.843 / 0.763 | HO `gates.model_frozen_to2019` |
| §5.3 | 시간·사상 검증 문헌 AUC 0.73~0.88 | `docs/research_reports/Q1_literature.md` 검증 관행 절 (Mobley 2021, Lee 2017 등) |
| 부록 B | 거주 격자 10 202, HO 양성 102, CDRI AUC 0.340 / 0.392 / 0.480 / 0.496, 개발 0.539 / 0.732, TOP20 중첩 5/20 | CDRI `summary.json` → `holdout.*.CDRI_gate_universe`, `development.*`, `top20_overlap.L1.rf_to2019` |
| 부록 C | 84 호우, 72 라벨(양성 10), V1 44사상·양성 5, BSS 0.055 [−0.249, 0.210], AUC 0.723, HO BSS 0.219 [−0.179, 0.468], 경보 FAR 0.50~0.58, 결합 BSS 0.0002 [−0.0038, 0.0017], 위치 AUC 0.84~0.97 | FC (`docs/FORECAST_RESULTS.md` §1~§4) |
| 부록 D | 연대표 11행 | M6 `chronology.csv` |
| 코드와 자료 | Zenodo 후보 458 (open 340, restricted 5, hash_only 111, exclude 2) | M6 `zenodo_summary.json` (`docs/q1/M6.md` 결과 요약) |
