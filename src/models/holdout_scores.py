"""홀드아웃 평가에서 사용할 동결 점수와 비교 점수를 구성한다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from src.models.features import FEATURES, feature_frame
from src.models.estimators import make_model
from src.models.provenance import file_sha256

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / ".omc/benchmark"
# 각 이름에 동결 모델과 사전 명세 파일을 연결한다.
MODELS = {
    "v2": (BENCHMARK / "final_model.joblib", BENCHMARK / "prespec.json"),        # 분할 누수 수정 후 선택
    "v1": (BENCHMARK / "v1/final_model.joblib", BENCHMARK / "v1/prespec.json"),  # 누수 있던 선택
}
PRE_HOLDOUT_EVENTS = (2006, 2012, 2014, 2016, 2019)  # 홀드아웃보다 늦은 2025년 개발 사상은 제외한다.
HOLDOUT_START = "2022-01-01"
# 역할과 사후 설계 여부, 확증 근거 여부를 점수별로 기록한다.
ROLES = {
    "L1": ("pre_registered", False, True),
    "model_frozen": ("frozen", True, False),
    "model_frozen_to2019": ("frozen_sensitivity", True, False),
    "rf_F0_v1": ("superseded", True, False),
    "rf_F0_v1_to2019": ("superseded", True, False),
    "city_flood_map": ("reference", False, False),
    "past_flood_pre2022": ("reference", False, False),
    "L1_without_flood_map": ("post_hoc", True, False),
    "z_sensitivity": ("post_hoc", True, False),
    "z_exposure": ("post_hoc", True, False),
}


def frozen_scores(name: str, frame, early: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """동결 모델 점수와, 같은 파이프라인을 clone 해 2019년까지 사상으로 다시 학습한 점수."""
    import joblib
    from sklearn.base import clone

    # 사전 명세와 저장 모델의 해시·설정·특징 수를 확인한다.
    model_path, prespec_path = MODELS[name]
    prespec = json.loads(prespec_path.read_text(encoding="utf-8"))
    selection = prespec["selection"]
    if file_sha256(model_path) != prespec["final_model_sha256"]:
        raise RuntimeError(f"{name}: 모델 해시가 prespec 과 다르다")
    model = joblib.load(model_path)
    estimator = model.named_steps["model"]
    params = estimator.get_params()
    if {k: params[k] for k in selection["parameters"]} != selection["parameters"]:
        raise RuntimeError(f"{name}: 저장 모델 파라미터가 prespec 과 다르다")
    columns = selection["feature_columns"]
    if estimator.n_features_in_ != len(columns):
        raise RuntimeError(f"{name}: 특징 수가 prespec 과 다르다")

    # 저장 모델과 2019년까지 사상으로 재학습한 복제 모델을 같은 특징으로 채점한다.
    X = frame[columns].to_numpy(float)
    refit = clone(model).fit(X, early)
    info = {"model_sha256": prespec["final_model_sha256"], "prespec_run_id": prespec["run_id"],
            "prespec_sha256": file_sha256(prespec_path), "selection": selection,
            "checked": "모델 파일 해시, selection.parameters 에 적힌 키, 특징 개수 (특징 순서는 prespec 목록을 따른다)"}
    return model.predict_proba(X)[:, 1], refit.predict_proba(X)[:, 1], info


def build_scores(layer, frame, features, dev_traces) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """채점할 점수를 격자 순서대로 만든다."""
    import geopandas as gpd

    from src.data import layers as L
    from src.stages.h06_layers import FLOOD_MAP_VARIABLES, SENSITIVITY_SPEC, _add_proximity

    # h06과 같은 입력·규칙으로 예상도 변수만 뺀 민감도를 계산한다.
    df = layer[["grid_id"]].merge(features, on="grid_id", how="left", validate="one_to_one")
    _add_proximity(df, 300.0)
    z_full, _ = L.composite(df, SENSITIVITY_SPEC, winsor_lo=0.01, winsor_hi=0.99)
    if not np.allclose(z_full, layer["z_sensitivity"].to_numpy(float)):
        raise RuntimeError("민감도 재계산이 저장된 z_sensitivity 와 다르다")
    without_map = {k: v for k, v in SENSITIVITY_SPEC.items() if k not in FLOOD_MAP_VARIABLES}
    z_reduced, _ = L.composite(df, without_map, winsor_lo=0.01, winsor_hi=0.99)

    # 격자 중심에서 2022년 이전 개발 흔적까지의 최단 거리를 구한다.
    past = dev_traces.loc[dev_traces["event_date"] < HOLDOUT_START, ["geometry"]]
    centers = layer[["geometry"]].assign(geometry=layer.geometry.centroid).reset_index(names="_row")
    nearest = gpd.sjoin_nearest(centers, past, distance_col="_d").groupby("_row")["_d"].min()
    distance = nearest.reindex(range(len(layer))).to_numpy(float)

    # 기존 두 동결 모델의 원래 점수와 2019년까지 재학습한 점수를 만든다.
    early = layer[[f"trace_ev_{y}" for y in PRE_HOLDOUT_EVENTS]].to_numpy().any(axis=1)
    v2, v2_early, v2_info = frozen_scores("v2", frame, early)
    v1, v1_early, v1_info = frozen_scores("v1", frame, early)

    # 지수·모델·지도·개발 흔적·사후 진단 점수를 원래 순서로 묶는다.
    scores = {
        "L1": layer["L1"].to_numpy(float),
        "model_frozen": v2, "model_frozen_to2019": v2_early,
        "rf_F0_v1": v1, "rf_F0_v1_to2019": v1_early,
        "city_flood_map": frame["flood_l210_100_depth_m"].to_numpy(float),
        "past_flood_pre2022": -distance,
        "L1_without_flood_map": L.minmax(layer["z_exposure"].to_numpy(float) + z_reduced),
        "z_sensitivity": layer["z_sensitivity"].to_numpy(float),
        "z_exposure": layer["z_exposure"].to_numpy(float),
    }
    return scores, {"v2": v2_info, "v1": v1_info, "n_past_polygons": int(len(past))}


_frozen_scores = frozen_scores
_scores = build_scores
