"""동결 RF-F1을 개발 사상 집합별로 다시 적합한다."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from src.models.provenance import file_sha256

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / ".omc/benchmark/final_model.joblib"
PRESPEC_PATH = ROOT / ".omc/benchmark/prespec.json"
_CACHE: dict[tuple[int, int, tuple[str, ...]], np.ndarray] = {}
FIT_LOG: list[dict] = []
FROZEN_INFO: dict = {}


def clear_cache() -> None:
    """실행 사이의 공간 적합 캐시와 기록을 초기화한다."""
    # 실행 경계에서 이전 자료의 배열과 적합 기록을 버린다.
    _CACHE.clear()
    FIT_LOG.clear()


def load_frozen_pipeline():
    """prespec과 동결 모델의 해시·설정·특징 수를 확인한다."""
    import joblib

    # 저장된 prespec과 모델의 해시를 먼저 대조한다.
    prespec = json.loads(PRESPEC_PATH.read_text(encoding="utf-8"))
    if file_sha256(MODEL_PATH) != prespec["final_model_sha256"]:
        raise RuntimeError("동결 모델 해시가 prespec과 다르다")
    pipeline = joblib.load(MODEL_PATH)
    selection = prespec["selection"]
    estimator = pipeline.named_steps["model"]

    # 선택된 파라미터와 특징 수를 동결 명세와 대조한다.
    actual = estimator.get_params()
    if {key: actual[key] for key in selection["parameters"]} != selection["parameters"]:
        raise RuntimeError("동결 모델 파라미터가 prespec과 다르다")
    columns = selection["feature_columns"]
    if estimator.n_features_in_ != len(columns):
        raise RuntimeError("동결 모델 특징 수가 prespec과 다르다")
    FROZEN_INFO.clear()
    FROZEN_INFO.update({"model_sha256": prespec["final_model_sha256"],
                        "prespec_sha256": file_sha256(PRESPEC_PATH),
                        "prespec_run_id": prespec["run_id"]})
    return pipeline, columns


def fit_scores(train_years: tuple[str, ...], layer, frame) -> np.ndarray:
    """지정 개발 연도의 합집합 라벨로 RF를 재적합해 전 격자를 채점한다."""
    from sklearn.base import clone

    # 사상 집합을 정규화하고 같은 입력의 기존 적합 점수를 재사용한다.
    years = tuple(sorted({str(year) for year in train_years}))
    if not years:
        raise ValueError("공간 학습 사상이 비었다")
    key = (id(layer), id(frame), years)
    if key in _CACHE:
        return _CACHE[key]

    # 원래 격자 순서의 합집합 라벨과 동결 특징 행렬을 준비한다.
    columns = [f"trace_ev_{year}" for year in years]
    if len(layer) != len(frame) or not np.array_equal(layer["grid_id"], frame["grid_id"]):
        raise ValueError("layer와 frame의 격자 순서가 다르다")
    y = layer[columns].to_numpy().astype(bool).any(axis=1)
    if np.unique(y).size != 2:
        raise ValueError("공간 학습에 양성·음성 격자가 모두 필요하다")
    pipeline, feature_columns = load_frozen_pipeline()
    X = frame[feature_columns].to_numpy(float)

    # 동결 파이프라인 복제본을 적합하고 소요 시간과 점수를 기록한다.
    started = time.perf_counter()
    scores = clone(pipeline).fit(X, y).predict_proba(X)[:, 1]
    FIT_LOG.append({"train_years": list(years), "seconds": time.perf_counter() - started,
                    "n_cells": len(scores), "n_positive": int(y.sum())})
    _CACHE[key] = np.asarray(scores, dtype=float)
    return _CACHE[key]
