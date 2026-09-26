"""M3 안쪽 선택: 이전 사상 안의 LOEO 로 설정별 선택 점수를 구하고 순위를 매긴다 (docs/q1/M3_protocol.md §3)."""

from __future__ import annotations

import sys
import time
from typing import Any

import numpy as np
import pandas as pd

from src.models.estimators import make_model
from src.models.folds import Fold, crossfit_event, event_folds, loeo_groups
from src.models.scoring import score_metrics


def loeo_splits(points: np.ndarray, events: np.ndarray, names: list[str]) -> list[tuple[Fold, list[Fold]]]:
    """이전 사상 열만으로 뺀 사상별 LOEO 분할과 음성 교차 예측 부분을 만든다 (설정과 무관)."""
    # 이전 사상이 둘 이상인지 확인한다
    events = np.asarray(events, dtype=bool)
    if events.ndim != 2 or events.shape[1] < 2 or events.shape[1] != len(names):
        raise ValueError("이전 사상이 2개 미만이거나 이름 수가 다르다 (선택 불가)")

    # 뺀 사상마다 그 사상 라벨과 무관한 배경 3분할로 교차 예측 부분을 나눈다
    splits = []
    for i, fold in enumerate(event_folds(events, names)):
        if not fold.test_y.any() or fold.test_y.all():
            raise ValueError(f"{fold.name}: LOEO 시험에 양성 또는 음성이 없다")
        splits.append((fold, crossfit_event(fold, loeo_groups(points, events, i)[1])))
    return splits


def config_loeo(X: np.ndarray, points: np.ndarray, splits: list[tuple[Fold, list[Fold]]],
                model: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """한 설정을 LOEO 부분마다 적합해 뺀 사상별 지표를 구한다."""
    rows = []
    for fold, parts in splits:
        # 부분마다 학습하고 시험 격자 예측을 평균한다 (양성은 부분 수만큼, 음성은 한 번 예측된다)
        sums, counts = np.zeros(len(X)), np.zeros(len(X), dtype=int)
        for part in parts:
            fitted = make_model(model, params).fit(X[part.train], part.train_y)
            sums[part.test] += fitted.predict_proba(X[part.test])[:, 1]
            counts[part.test] += 1
        if np.any(counts[fold.test] == 0):
            raise ValueError("예측되지 않은 시험 격자")

        # 벤치마크와 같은 지표로 뺀 사상 하나를 채점한다
        prediction = sums[fold.test] / counts[fold.test]
        rows.append({"held_event": fold.name, "n_test": len(fold.test), "n_positive": int(fold.test_y.sum()),
                     **score_metrics(fold.test_y, prediction, points[fold.test])})
    return rows


def rank_configs(table: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    """설정별 뺀 사상 cluster_auc 비가중 평균으로 순위를 매긴다 (동점은 선언 순서)."""
    # 선언 순서대로 평균을 모으고 결측이 없는지 확인한다
    mean = table.groupby("config")["cluster_auc"].mean().reindex(order)
    if mean.isna().any():
        raise ValueError("선택 점수가 없는 설정이 있다")

    # 점수 내림차순, 같은 점수는 선언 순서로 정렬한다
    score = mean.to_numpy(float)
    index = np.lexsort((np.arange(len(order)), -score))
    return pd.DataFrame({"config": np.asarray(order)[index], "selection_score": score[index],
                         "declaration_order": index, "rank": np.arange(1, len(order) + 1)})


def select_for_prior(X: dict[str, np.ndarray], points: np.ndarray, labels: dict[int, np.ndarray],
                     prior: tuple[int, ...], configs: list[dict[str, Any]],
                     variants: dict[str, tuple[str, ...]]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """한 이전 사상 집합에서 모든 설정의 LOEO 지표를 구하고 변형별 순위표를 돌려준다."""
    # 이전 사상 열만으로 LOEO 분할을 한 번 만든다
    names = [str(y) for y in prior]
    splits = loeo_splits(points, np.column_stack([labels[y] for y in prior]), names)

    # 설정마다 같은 분할로 채점한다
    rows, started = [], time.monotonic()
    for config in configs:
        for row in config_loeo(X[config["feature_set"]], points, splits, config["model"], config["params"]):
            rows.append({"prior": ",".join(names), "config": config["id"], **row})
        print(f"  P={names} {config['id']} {time.monotonic() - started:.0f}s", file=sys.stderr, flush=True)

    # 변형별로 해당 모델군 설정만 모아 순위를 매긴다
    table = pd.DataFrame(rows)
    rankings = {variant: rank_configs(table, [c["id"] for c in configs if c["model"] in models])
                for variant, models in variants.items()}
    return table, rankings
