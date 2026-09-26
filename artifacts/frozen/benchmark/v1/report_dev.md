# P005 개발 비교 모델 결과 — W3

출처: `src/models/benchmark.py`, run_id `P005_dev_20260924T091820Z`. 실행 시간 `204.875`초.

## 결과 요약

개발 격자 75,400개, 양성 642개, 150m 연결 덩어리 46개. 전체 격자 사용(universe 필터 없음). 모델·특징은 사전 기록한 규칙에 따라 `random_forest / F0`로 선택했다. 최종 파라미터는 `prespec.json`에 동결하고 `final_model.joblib`에 전체 개발 자료로 fit한 파이프라인을 저장했다.

## 실행·검증

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /home/data/.venv-changwon/bin/python -m src.models.benchmark
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /home/data/.venv-changwon/bin/python .omc/benchmark/verify_dev.py
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /home/data/.venv-changwon/bin/python -m unittest discover -s tests
```

벤치마크: `result_rows=896`, `elapsed_seconds=204.875`. 재검산: `verified_metric_values=704`, `verified_outer_parts=23`, `verified_inner_splits=69`, 덩어리 분할·버퍼 위반·학습/시험 중복 모두 `0`, 재로드 모델 예측 `75400`개 유한값, 코드·입력·결과 해시 일치. 전체 테스트: `Ran 209 tests in 119.891s`, `OK`. 추가한 테스트 11건은 별도 실행에서도 통과했다. 독립 검토가 아닌 W3 자기 검증이다.

## 전체 테스트의 홀드아웃 접근 — 리더 확인 필요

전체 unittest를 실행하던 중 다른 작업자의 `tests/test_flood_traces.py` 통합 테스트 `setUpClass`가 `FT.load_holdout()`을 호출했다. 로그 확인 뒤 발견했으며, 이 세션 전체에 대해 홀드아웃 무접근이라고 주장할 수 없다. **벤치마크 프로세스는 지정된 개발 가공 파일만 읽었고, 홀드아웃 모델 점수는 계산하지 않았다.** 모델 후보·선택 규칙은 전체 테스트 시작 전에 `protocol_dev.json`에 기록했고 이후 바꾸지 않았다. 테스트 출력은 모델 선택에 쓰지 않았다. 동결 후 `prespec.json`에 검증 실행 사실만 추가하고 모델·특징·파라미터·선택 규칙은 유지했다. 증거: `unittest.log`, `validation_scope_note.json`. 전체 테스트 재실행 전에는 해당 통합 테스트와 홀드아웃 금지 지침의 충돌을 리더가 해결해야 한다.

## fold 평균 전체 결과

격자 AUC·덩어리 AUC·observed-label AP·상위 20% 포착률을 모두 기록한다. 공간 pooled OOF 값과 개별 사상 값은 `results_dev.csv`에 함께 있다. LOEO 공통 음성은 그룹 교차 예측하며 사상별 모든 영구 음성을 평가한다. 사상 간 음성 중복 때문에 LOEO 전체를 한 표본처럼 합친 pooled 값은 만들지 않는다.

| 모델 | 특징 | CV | 격자 AUC | 덩어리 AUC | 관측 라벨 AP | 상위 20% 포착 |
|---|---|---|---:|---:|---:|---:|
| L1 | baseline | loeo | 0.702902 | 0.709588 | 0.007277 | 0.497211 |
| L1 | baseline | spatial | 0.773423 | 0.748705 | 0.035057 | 0.609943 |
| city_depth | baseline | loeo | 0.684754 | 0.679244 | 0.012778 | 0.520235 |
| city_depth | baseline | spatial | 0.720174 | 0.681640 | 0.053222 | 0.588045 |
| frequency_ratio | F0 | loeo | 0.871690 | 0.826328 | 0.013754 | 0.790182 |
| frequency_ratio | F0 | spatial | 0.880832 | 0.820851 | 0.087445 | 0.780548 |
| frequency_ratio | F1 | loeo | 0.872967 | 0.834197 | 0.011086 | 0.780472 |
| frequency_ratio | F1 | spatial | 0.881506 | 0.826870 | 0.061368 | 0.784936 |
| frequency_ratio | F2 | loeo | 0.864554 | 0.824217 | 0.006701 | 0.800831 |
| frequency_ratio | F2 | spatial | 0.846247 | 0.798195 | 0.049279 | 0.689868 |
| past_flood | baseline | loeo | 0.683761 | 0.607975 | 0.011126 | 0.505677 |
| past_flood | baseline | spatial | 0.519100 | 0.667744 | 0.009199 | 0.103235 |
| random_forest | F0 | loeo | 0.883951 | 0.845310 | 0.009006 | 0.842505 |
| random_forest | F0 | spatial | 0.881295 | 0.836176 | 0.048097 | 0.797765 |
| random_forest | F1 | loeo | 0.874391 | 0.838509 | 0.008533 | 0.820809 |
| random_forest | F1 | spatial | 0.884788 | 0.841354 | 0.059848 | 0.791835 |
| random_forest | F2 | loeo | 0.864638 | 0.821272 | 0.007785 | 0.825933 |
| random_forest | F2 | spatial | 0.871307 | 0.815560 | 0.061919 | 0.761752 |
| ridge | F0 | loeo | 0.866657 | 0.825501 | 0.007167 | 0.825999 |
| ridge | F0 | spatial | 0.857749 | 0.808411 | 0.035092 | 0.755970 |
| ridge | F1 | loeo | 0.864257 | 0.822998 | 0.006936 | 0.821453 |
| ridge | F1 | spatial | 0.855853 | 0.809323 | 0.034856 | 0.753579 |
| ridge | F2 | loeo | 0.859751 | 0.815030 | 0.007525 | 0.788681 |
| ridge | F2 | spatial | 0.842457 | 0.793998 | 0.032646 | 0.668963 |
| xgboost | F0 | loeo | 0.874928 | 0.844122 | 0.010292 | 0.769132 |
| xgboost | F0 | spatial | 0.882790 | 0.835977 | 0.053220 | 0.797402 |
| xgboost | F1 | loeo | 0.872511 | 0.838226 | 0.011392 | 0.754814 |
| xgboost | F1 | spatial | 0.878516 | 0.831631 | 0.053024 | 0.776858 |
| xgboost | F2 | loeo | 0.865982 | 0.823679 | 0.010461 | 0.830931 |
| xgboost | F2 | spatial | 0.863199 | 0.811902 | 0.061294 | 0.779294 |
| z_sensitivity | baseline | loeo | 0.855349 | 0.836395 | 0.012604 | 0.664063 |
| z_sensitivity | baseline | spatial | 0.873481 | 0.836236 | 0.059836 | 0.730172 |

평균 기준 사전 게이트(격자 AUC ≥ 0.70, 포착 ≥ 0.50) 미달 조합: 4/32개. 개별 fold와 공간 pooled 게이트는 `gates_all_folds.csv`, 평균 게이트는 `gates_dev.csv`.

- `past_flood/baseline/spatial`: AUC `0.519100`, 포착 `0.103235`.
- `L1/baseline/loeo`: AUC `0.702902`, 포착 `0.497211`.
- `city_depth/baseline/loeo`: AUC `0.684754`, 포착 `0.520235`.
- `past_flood/baseline/loeo`: AUC `0.683761`, 포착 `0.505677`.

## 누수 점검

- preprocessing: 중앙값·평균·표준편차는 내부/외부 해당 학습 fold에서만 fit.
- frequency_bins: 분위 경계·빈도비·희소 구간 smoothing은 해당 학습 fold에서만 fit.
- hyperparameters: 외부 시험 점수와 무관하게 내부 3-fold cluster_auc로만 선택.
- proximity: 해당 학습 fold 양성 중심점만 사용; 시험 행과 원천 중복 시 오류.
- spatial_clusters: 150m 양성 연결 덩어리가 걸친 블록을 병합해 같은 fold에 배정.
- buffer: 시험 2km 블록과 학습 100m 격자 사각형 간 거리 >300m.
- loeo: 뺀 사상 양성 전부 제외; 모든 음성은 그룹 교차 예측으로 학습·시험 중복 0.
- holdout: 개발 가공 파일 2개만 읽음; 원본 흔적 로더 및 파이프라인 미사용.

## 한계와 리더 판단 필요

- 기존 홀드아웃 실패가 알려진 뒤 제안된 비교 설계다. 이번 실행은 홀드아웃 파일을 읽지 않지만 최초 사전등록 분석은 아니다.
- 고정 기준선 L1·z_sensitivity는 제공된 동결 값을 사용한다. 과거 전체 격자 정규화 이력은 재학습하지 않는다.
- 빈도비 sigmoid 출력은 보정된 발생 확률이 아니라 순위 점수다.
- 폴리곤 1표 평가는 개발 원본 폴리곤 식별자를 읽지 않아 이 단계에서 산출하지 않는다.
- LOEO 음성은 사상별로 반복 채점된다. 사상 간 통합 OOF 값 대신 사상별 값과 비가중 평균을 보고한다.
- 근접도는 라벨이 있는 100m 격자 중심점 대리값이며 원본 흔적 경계 거리가 아니다.
- 근접도 기준선은 지정된 입력의 사상별 양성 격자 중심점을 사용했다. 원본 흔적 폴리곤 경계 거리와 동일하지 않으므로 이 대리값의 허용 여부를 리더가 판정해야 한다.
- 독립 검토자가 코드·분할·선택 결과를 확인한 뒤 리더가 동결 모델로 홀드아웃을 한 번 채점해야 한다. 학습 시 사용한 특징 순서·거리 변환·결측 대치는 동결 설정 그대로 사용한다.
