v1 대비 선택 변경: random_forest/F1, {'n_estimators': 48, 'max_features': 'sqrt', 'class_weight': None, 'n_jobs': 2, 'random_state': 42, 'max_depth': 4, 'min_samples_leaf': 400}

## 결과 요약

- run_id: `P005_dev_20260924T094916Z`; `env -u CHANGWON_HOLDOUT_TESTS PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /home/data/.venv-changwon/bin/python -m src.models.benchmark` → 155.063초, 896행.
- 후보·특징·선택 규칙·고정 파라미터는 v1과 동일; 평균 게이트 탈락 3/32건.
- 이번 실행은 홀드아웃 미접근·미채점. v1의 접근 위반은 보존했으며 소급해 지우지 않았다.

## 변경 파일

- src/models/folds.py: LOEO 학습 사상별 그룹, 원본 폴리곤 거리.
- src/models/benchmark.py: 사상별 그룹 연결·개발 원본 로딩·v1 비교 이력 기록.
- tests/test_benchmark.py: 제외 사상 변경 불변성·원본 거리·공간 제외 검증.
- .omc/benchmark/: 새 산출물·로그·재현 스크립트; v1/에 기존 산출물 보존.

## 증거

공통 환경: `env -u CHANGWON_HOLDOUT_TESTS PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp PYTHONPATH=.`
`PY=/home/data/.venv-changwon/bin/python`

| 발견 | 재현 전 출력 → 수정 후 출력 | 명령/증거 |
|---|---|---|
| 1 | v1 `holdout_read=true`, `holdout: polygons=196 ... positive=1267` → 환경변수 없음, 벤치마크 테스트만 `OK`, 이번 `holdout_read=false` | `rg -n "holdout:|holdout_read" .omc/benchmark/v1/unittest.log .omc/benchmark/v1/prespec.json`; `$PY -m unittest tests.test_benchmark` |
| 2 | 검토 명령 `254 259`; 제외 사상 제거 시 변경 그룹 행 `807` → 공간·배경 그룹 변경 행 `0 0`; 회귀 테스트 `FAIL` → `OK` | `$PY .omc/benchmark/reproduce_review.py`; `reproduction_test_before.log`, `unittest.log` |
| 3 | `center_score -100.0 polygon_score -50.0` → `past_flood -50.0 polygon_score -50.0 inside -0.0` | `$PY .omc/benchmark/reproduce_review.py` |

단위 테스트 출력:
```
.............
----------------------------------------------------------------------
Ran 13 tests in 0.277s

OK
```

`$PY .omc/benchmark/verify_dev.py` → 지표 704개 재검산, 외부 23개 부분 fold·내부 69개 분할 확인. 덩어리 분리·버퍼 위반·학습 시험 중복 0. LOEO 6개 사상 모두 제외 라벨 반전에도 그룹 불변. 원본 폴리곤 거리 전수 후보 비교와 저장 예측 표본 일치. 코드·입력·v1 산출물 해시 일치.

모든 모델×특징×CV 평균 지표 (출처: 같은 run_id의 results_dev.csv; 생성: `$PY .omc/benchmark/summarize_dev.py`):

| 모델 | 특징 | CV | 격자 AUC | 덩어리 AUC | 관측 AP | 상위20% 포착 |
|---|---|---|---:|---:|---:|---:|
| L1 | baseline | loeo | 0.702902 | 0.709588 | 0.007277 | 0.497211 |
| L1 | baseline | spatial | 0.773423 | 0.748705 | 0.035057 | 0.609943 |
| city_depth | baseline | loeo | 0.684754 | 0.679244 | 0.012778 | 0.520235 |
| city_depth | baseline | spatial | 0.720174 | 0.681640 | 0.053222 | 0.588045 |
| frequency_ratio | F0 | loeo | 0.872481 | 0.827207 | 0.014578 | 0.750292 |
| frequency_ratio | F0 | spatial | 0.880832 | 0.820851 | 0.087445 | 0.780548 |
| frequency_ratio | F1 | loeo | 0.874255 | 0.835502 | 0.012528 | 0.784807 |
| frequency_ratio | F1 | spatial | 0.881506 | 0.826870 | 0.061368 | 0.784936 |
| frequency_ratio | F2 | loeo | 0.854886 | 0.812128 | 0.006027 | 0.749895 |
| frequency_ratio | F2 | spatial | 0.846247 | 0.798195 | 0.049279 | 0.689868 |
| past_flood | baseline | loeo | 0.742829 | 0.671302 | 0.183525 | 0.587940 |
| past_flood | baseline | spatial | 0.522335 | 0.675089 | 0.009223 | 0.097669 |
| random_forest | F0 | loeo | 0.885123 | 0.845126 | 0.009952 | 0.843130 |
| random_forest | F0 | spatial | 0.881295 | 0.836176 | 0.048097 | 0.797765 |
| random_forest | F1 | loeo | 0.877311 | 0.840981 | 0.010126 | 0.818642 |
| random_forest | F1 | spatial | 0.884788 | 0.841354 | 0.059848 | 0.791835 |
| random_forest | F2 | loeo | 0.865398 | 0.828954 | 0.009867 | 0.827214 |
| random_forest | F2 | spatial | 0.871307 | 0.815560 | 0.061919 | 0.761752 |
| ridge | F0 | loeo | 0.866874 | 0.825224 | 0.007197 | 0.820813 |
| ridge | F0 | spatial | 0.857749 | 0.808411 | 0.035092 | 0.755970 |
| ridge | F1 | loeo | 0.864260 | 0.822442 | 0.006931 | 0.818338 |
| ridge | F1 | spatial | 0.855853 | 0.809323 | 0.034856 | 0.753579 |
| ridge | F2 | loeo | 0.862561 | 0.816006 | 0.007618 | 0.794102 |
| ridge | F2 | spatial | 0.842457 | 0.793998 | 0.032646 | 0.668963 |
| xgboost | F0 | loeo | 0.873384 | 0.840796 | 0.009731 | 0.769846 |
| xgboost | F0 | spatial | 0.882790 | 0.835977 | 0.053220 | 0.797402 |
| xgboost | F1 | loeo | 0.876548 | 0.840678 | 0.012807 | 0.767515 |
| xgboost | F1 | spatial | 0.878516 | 0.831631 | 0.053024 | 0.776858 |
| xgboost | F2 | loeo | 0.855106 | 0.816535 | 0.011872 | 0.704811 |
| xgboost | F2 | spatial | 0.863199 | 0.811902 | 0.061294 | 0.779294 |
| z_sensitivity | baseline | loeo | 0.855349 | 0.836395 | 0.012604 | 0.664063 |
| z_sensitivity | baseline | spatial | 0.873481 | 0.836236 | 0.059836 | 0.730172 |

평균 게이트 탈락 항목 (기준 유지: AUC≥0.70, 포착≥0.50):

| 모델 | 특징 | CV | AUC | 포착 |
|---|---|---|---:|---:|
| past_flood | baseline | spatial | 0.522335 | 0.097669 |
| L1 | baseline | loeo | 0.702902 | 0.497211 |
| city_depth | baseline | loeo | 0.684754 | 0.520235 |

fold별 모든 값은 results_dev.csv, 개별 게이트는 gates_all_folds.csv에 기록했다.

## 한계·미확인

- 기존 홀드아웃 결과가 알려진 뒤의 post-hoc 검토 수정이며 최초 사전등록이 아니다.
- 폴리곤 1표 평가는 기존 비교 지표 범위에 없어 추가하지 않았다. 원본 폴리곤은 근접도 기준선에 사용했다.
- 공간 CV의 근접도는 학습·시험 영역을 함께 가로지르는 원본 폴리곤을 통째로 제외한다.
- 전체 테스트 및 홀드아웃 평가는 실행하지 않았다.

## 리더 판단 필요

- 수정 코드·새 동결 결과의 독립 검토 및 최종 승인. 과거 v1 접근 위반 이력은 계속 병기해야 한다.
