"""개발 자료만으로 공간·사상 교차검증을 실행하고 최종 설정을 동결한다."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin

from src.data.uncertainty import cluster_weighted_auc, spatial_clusters
from src.models.folds import (
    block_groups, crossfit_event, event_folds, group_assignment, past_flood_score, spatial_folds,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".omc/benchmark"
EVENTS = [2006, 2012, 2014, 2016, 2019, 2025]
F0 = ["rel_elev_m", "slope_deg", "twi", "impervious_frac", "river_proximity",
      "culvert_proximity", "pump_within_km"]
F1 = F0 + ["flood_l210_100_depth_m"]
FEATURES = {"F0": F0, "F1": F1, "F2": F1 + [
    "rain_annual_max_1h", "rain_hours_over_30mm", "rain_top5_3h", "rain_top5_24h",
]}
# 실행 전에 고정한 소규모 후보 집합; 모든 모델의 클래스 가중은 없다.
CANDIDATES = {
    "ridge": [{"C": 0.1}, {"C": 1.0}],
    "frequency_ratio": [{"n_bins": 5, "alpha": 1.0}, {"n_bins": 10, "alpha": 1.0}],
    "random_forest": [{"max_depth": 2, "min_samples_leaf": 200},
                      {"max_depth": 4, "min_samples_leaf": 400}],
    "xgboost": [{"max_depth": 1}, {"max_depth": 3}],
}
FIXED_PARAMS = {
    "ridge": {"solver": "lbfgs", "max_iter": 500, "class_weight": None, "random_state": 42},
    "frequency_ratio": {},
    "random_forest": {"n_estimators": 48, "max_features": "sqrt", "class_weight": None,
                      "n_jobs": 2, "random_state": 42},
    "xgboost": {"n_estimators": 80, "learning_rate": 0.05, "reg_lambda": 20.0,
                "reg_alpha": 1.0, "min_child_weight": 10, "subsample": 1.0,
                "colsample_bytree": 1.0, "scale_pos_weight": 1.0, "tree_method": "hist",
                "n_jobs": 2, "random_state": 42, "eval_metric": "logloss"},
}
METRICS = ["grid_auc", "cluster_auc", "observed_label_ap", "top20_capture"]
SELECTION_RULE = (
    "모델·특징: 공간 5-fold 평균 cluster_auc와 LOEO 6-fold 평균 cluster_auc의 산술평균 최대. "
    "동점: FEATURES 및 CANDIDATES 선언 순서. 기준선은 후보에서 제외. "
    "하이퍼파라미터: 각 외부 학습 자료 안의 버퍼 적용 공간 그룹 3-fold 평균 cluster_auc 최대, "
    "동점은 후보 선언 순서. 최종 파라미터도 전체 개발 자료의 동일한 내부 CV로 결정. "
    "선택된 모델의 개발 CV 점수는 선택 편향이 있으므로 최종 성능 추정으로 해석하지 않는다."
)


class FrequencyRatio(ClassifierMixin, BaseEstimator):
    """학습 분위 구간의 양성 비율과 면적 비율을 평활화해 로그 비율을 합산한다."""

    def __init__(self, n_bins: int = 5, alpha: float = 1.0):
        self.n_bins = n_bins
        self.alpha = alpha

    def fit(self, X: np.ndarray, y: np.ndarray) -> FrequencyRatio:
        """학습 자료에서만 구간 경계와 평활 빈도비를 구한다."""
        X, y = np.asarray(X), np.asarray(y, dtype=bool)
        self.classes_ = np.array([False, True])
        self.n_features_in_ = X.shape[1]
        self.edges_, self.log_ratios_ = [], []
        for column in X.T:
            edges = np.unique(np.quantile(column, np.linspace(0, 1, self.n_bins + 1)[1:-1]))
            bins = np.searchsorted(edges, column, side="right")
            k = len(edges) + 1
            total = np.bincount(bins, minlength=k)
            positive = np.bincount(bins[y], minlength=k)
            ratio = ((positive + self.alpha) / (y.sum() + self.alpha * k)
                     / ((total + self.alpha) / (len(y) + self.alpha * k)))
            self.edges_.append(edges)
            self.log_ratios_.append(np.log(ratio))
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """로그 빈도비를 단조 변환한 비교 점수를 반환한다."""
        from scipy.special import expit

        score = np.zeros(len(X))
        for column, edges, ratios in zip(np.asarray(X).T, self.edges_, self.log_ratios_):
            score += ratios[np.searchsorted(edges, column, side="right")]
        probability = expit(score)
        return np.column_stack([1 - probability, probability])


def make_model(name: str, params: dict[str, Any]) -> Any:
    """결측 대치와 로지스틱 표준화를 학습 fold 안에서 수행하는 모델을 만든다."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    config = FIXED_PARAMS[name] | params
    if name == "ridge":
        estimator = LogisticRegression(**config)
    elif name == "frequency_ratio":
        estimator = FrequencyRatio(**config)
    elif name == "random_forest":
        estimator = RandomForestClassifier(**config)
    elif name == "xgboost":
        from xgboost import XGBClassifier

        estimator = XGBClassifier(**config)
    else:
        raise ValueError(name)
    steps = [("impute", SimpleImputer(strategy="median", keep_empty_features=True))]
    if name == "ridge":
        steps.append(("scale", StandardScaler()))
    return Pipeline(steps + [("model", estimator)])


def feature_frame(layer: Any, features: Any) -> Any:
    """격자 키로 특징을 결합하고 고정 거리 변환을 적용한다."""
    columns = [c for c in F0 if c not in {"river_proximity", "culvert_proximity", "pump_within_km"}]
    columns += ["river_dist_m", "culvert_dist_m", "pump_dist_m", "flood_l210_100_depth_m"]
    rain = FEATURES["F2"][len(F1):]
    out = layer[["grid_id"] + rain].merge(features[["grid_id"] + columns],
                                          on="grid_id", how="left", validate="one_to_one", indicator=True)
    if not out["_merge"].eq("both").all():
        raise ValueError("특징이 없는 grid_id")
    out["river_proximity"] = np.maximum(0, 1 - out["river_dist_m"] / 300)
    out["culvert_proximity"] = np.maximum(0, 1 - out["culvert_dist_m"] / 300).fillna(0)
    out["pump_within_km"] = (out["pump_dist_m"] <= 1000).astype(float)
    out.loc[out["pump_dist_m"].isna(), "pump_within_km"] = np.nan
    return out.replace([np.inf, -np.inf], np.nan)


def load_development() -> tuple[Any, Any, np.ndarray, np.ndarray, np.ndarray]:
    """지정된 가공 자료 두 파일만 읽고 개발 사상 라벨의 일치를 확인한다."""
    import geopandas as gpd
    import pandas as pd

    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    if layer.crs.to_epsg() != 5179:
        raise ValueError("EPSG:5179 자료가 필요하다")
    events = layer[[f"trace_ev_{year}" for year in EVENTS]].to_numpy()
    if not np.isin(events, [0, 1]).all():
        raise ValueError("사상 라벨은 결측 없는 0/1이어야 한다")
    events = events.astype(bool)
    labels = events.any(axis=1)
    if not np.array_equal(labels, layer["trace_label"].to_numpy().astype(bool)):
        raise ValueError("개발 사상 합집합과 trace_label 불일치: 실행 중단")
    features = pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet")
    frame = feature_frame(layer, features)
    centers = layer.geometry.centroid
    return layer, frame, np.column_stack([centers.x, centers.y]), labels, events


def score_metrics(labels: np.ndarray, scores: np.ndarray, points: np.ndarray) -> dict[str, float]:
    """격자·덩어리 AUC와 관측 라벨 AP 및 동점 분할 상위 20% 포착률을 구한다."""
    from sklearn.metrics import average_precision_score, roc_auc_score

    labels = np.asarray(labels, dtype=bool)
    if not np.isfinite(scores).all():
        raise ValueError("예측에 비유한 값이 있다")
    if not labels.any() or labels.all():
        return dict.fromkeys(METRICS, float("nan"))
    budget = 0.2 * len(labels)
    threshold = np.sort(scores)[-int(np.ceil(budget))]
    above, tied = scores > threshold, scores == threshold
    fraction = (budget - above.sum()) / tied.sum()
    capture = (labels[above].sum() + fraction * labels[tied].sum()) / labels.sum()
    return {"grid_auc": float(roc_auc_score(labels, scores)),
            "cluster_auc": cluster_weighted_auc(labels, scores, points[:, 0], points[:, 1]),
            "observed_label_ap": float(average_precision_score(labels, scores)),
            "top20_capture": float(capture)}


def tune_model(
    name: str, X: np.ndarray, labels: np.ndarray, points: np.ndarray, inner: list[Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """외부 학습 자료의 내부 공간 그룹 CV로만 파라미터를 선택한다."""
    trials = []
    for params in CANDIDATES[name]:
        values = []
        for fold in inner:
            if np.unique(labels[fold.train]).size != 2 or np.unique(labels[fold.test]).size != 2:
                raise ValueError("내부 fold에 양성 또는 음성이 없어 사전 지정 CV를 수행할 수 없다")
            model = make_model(name, params).fit(X[fold.train], labels[fold.train])
            scores = model.predict_proba(X[fold.test])[:, 1]
            p = points[fold.test]
            values.append(cluster_weighted_auc(labels[fold.test], scores, p[:, 0], p[:, 1]))
        trials.append({"params": params, "inner_cluster_auc": values, "mean": float(np.mean(values))})
    best = int(np.argmax([trial["mean"] for trial in trials]))
    return dict(CANDIDATES[name][best]), trials


def sha256(path: Path) -> str:
    """파일 내용을 스트리밍 SHA256으로 기록한다."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    """비표준 NaN 없이 UTF-8 JSON을 저장한다."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    """사전 설정을 먼저 기록한 뒤 개발 벤치마크와 최종 동결 파일을 만든다."""
    import joblib
    import pandas as pd
    import sklearn
    import xgboost
    from threadpoolctl import threadpool_limits

    started = time.monotonic()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if (OUTPUT / "prespec.json").exists():
        raise FileExistsError("동결된 prespec.json을 덮어쓸 수 없다")
    run_id = datetime.now(timezone.utc).strftime("P005_dev_%Y%m%dT%H%M%SZ")
    sources = ["src/models/folds.py", "src/models/benchmark.py", "tests/test_benchmark.py",
               "src/data/uncertainty.py"]
    inputs = ["data/processed/layers/layer1_flood.gpkg", "data/processed/features/grid_features.parquet"]
    protocol = {
        "run_id": run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": "PYTHONDONTWRITEBYTECODE=1 /home/data/.venv-changwon/bin/python -m src.models.benchmark",
        "code_sha256": {path: sha256(ROOT / path) for path in sources},
        "input_sha256": {path: sha256(ROOT / path) for path in inputs},
        "features": FEATURES, "candidates": CANDIDATES, "fixed_parameters": FIXED_PARAMS,
        "selection_rule": SELECTION_RULE, "versions": {"sklearn": sklearn.__version__, "xgboost": xgboost.__version__},
        "seed": 42, "population": "전체 격자; universe 필터 없음", "development_events": EVENTS,
        "outer_spatial": {"n_splits": 5, "block_m": 2000, "buffer_m": 300, "cell_m": 100,
                          "cluster_radius_m": 150, "block_origin": [0, 0]},
        "inner": {"n_splits": 3, "block_m": 2000, "buffer_m": 300, "metric": "cluster_auc"},
        "loeo": "시험=뺀 사상 양성+모든 영구 음성. 음성을 공간 그룹 3분할 교차 예측; 시험 양성은 3개 모델 예측 평균. 중복 사상 양성도 학습에서 제외.",
        "top20_ties": "정확히 20% 예산, 경계 동점은 분수 가중", "class_weight": "없음",
        "preprocessing": "모든 모델 학습 fold 중앙값 결측 대치; ridge만 학습 fold 평균·표준편차",
        "past_flood": "학습 사상의 양성 격자 중심점 최근접 거리 음수; 원본 흔적 폴리곤 거리의 대리값",
        "holdout_read": False, "holdout_scored": False,
        "gates": {"grid_auc_min": 0.70, "top20_capture_min": 0.50},
        "limitations": [
            "기존 홀드아웃 실패가 알려진 뒤 제안된 비교 설계다. 이번 실행은 홀드아웃 파일을 읽지 않지만 최초 사전등록 분석은 아니다.",
            "고정 기준선 L1·z_sensitivity는 제공된 동결 값을 사용한다. 과거 전체 격자 정규화 이력은 재학습하지 않는다.",
            "빈도비 sigmoid 출력은 보정된 발생 확률이 아니라 순위 점수다.",
            "폴리곤 1표 평가는 개발 원본 폴리곤 식별자를 읽지 않아 이 단계에서 산출하지 않는다.",
            "LOEO 음성은 사상별로 반복 채점된다. 사상 간 통합 OOF 값 대신 사상별 값과 비가중 평균을 보고한다.",
            "근접도는 라벨이 있는 100m 격자 중심점 대리값이며 원본 흔적 경계 거리가 아니다.",
        ],
    }
    write_json(OUTPUT / "protocol_dev.json", protocol)
    layer, frame, points, labels, events = load_development()
    groups = block_groups(points, labels)
    spatial = spatial_folds(points, labels, groups=groups)
    event = event_folds(events, [str(year) for year in EVENTS])
    background = group_assignment(labels, groups, 3)
    matrices = {feature: frame[columns].to_numpy(dtype=float) for feature, columns in FEATURES.items()}
    spatial_assignment = np.empty(len(labels), dtype=int)
    for i, fold in enumerate(spatial):
        spatial_assignment[fold.test] = i
    pd.DataFrame({"grid_id": layer.grid_id, "atomic_group": groups, "spatial_fold": spatial_assignment,
                  "loeo_background_group": background}).to_csv(OUTPUT / "fold_assignments.csv", index=False)
    rows, audit = [], []
    fold_info = []
    summaries: dict[tuple[str, str, str], dict[str, float]] = {}
    frozen = {"L1": layer.L1.to_numpy(), "z_sensitivity": layer.z_sensitivity.to_numpy(),
              "city_depth": frame.flood_l210_100_depth_m.to_numpy()}
    frozen = {name: np.nan_to_num(values, nan=0.0) for name, values in frozen.items()}
    jobs = [(cv, fold) for cv, folds in [("spatial", spatial), ("loeo", event)] for fold in folds]
    oof = {name: np.full(len(labels), np.nan) for name in list(frozen) + ["past_flood"]
           + [f"{model}_{feature}" for feature in FEATURES for model in CANDIDATES]}

    def record(model: str, feature: str, cv: str, fold: str, values: dict[str, float],
               n_test: int, n_positive: int) -> None:
        """각 지표를 재계산할 수 있는 긴 표 형식으로 기록한다."""
        for metric, value in values.items():
            rows.append({"run_id": run_id, "model": model, "feature_set": feature, "cv": cv,
                         "fold": fold, "metric": metric, "value": value,
                         "n_test": n_test, "n_positive": n_positive})

    with threadpool_limits(limits=2):
        for cv, fold in jobs:
            print(f"{run_id} {cv}/{fold.name} train={len(fold.train)} test={len(fold.test)} positives={int(fold.test_y.sum())}", flush=True)
            parts = [fold] if cv == "spatial" else crossfit_event(fold, background)
            part_inner = []
            for part in parts:
                if np.intersect1d(part.train, part.test).size:
                    raise ValueError("외부 학습·시험 행 중복")
                inner = spatial_folds(points[part.train], part.train_y, n_splits=3, groups=groups[part.train])
                part_inner.append(inner)
                fold_info.append({"cv": cv, "fold": part.name, "n_train": len(part.train),
                                  "n_train_positive": int(part.train_y.sum()), "n_test": len(part.test),
                                  "n_test_positive": int(part.test_y.sum()), "train_test_overlap": 0,
                                  "inner": [{"train": len(f.train), "positive_train": int(f.train_y.sum()),
                                             "test": len(f.test), "positive_test": int(f.test_y.sum())} for f in inner]})
            outputs = dict(frozen)
            sums, counts = np.zeros(len(labels)), np.zeros(len(labels), dtype=int)
            for part in parts:
                sums[part.test] += past_flood_score(points, part.train, part.train_y, part.test)
                counts[part.test] += 1
            outputs["past_flood"] = sums / np.maximum(counts, 1)
            for name, prediction in outputs.items():
                values = score_metrics(fold.test_y, prediction[fold.test], points[fold.test])
                record(name, "baseline", cv, fold.name, values, len(fold.test), int(fold.test_y.sum()))
                if cv == "spatial":
                    oof[name][fold.test] = prediction[fold.test]
            saved = {"grid_id": layer.grid_id.to_numpy(dtype=str)[fold.test], "labels": fold.test_y}
            saved.update({name: prediction[fold.test] for name, prediction in outputs.items()})
            for feature, X in matrices.items():
                for name in CANDIDATES:
                    sums, counts = np.zeros(len(labels)), np.zeros(len(labels), dtype=int)
                    for part, inner in zip(parts, part_inner):
                        params, trials = tune_model(name, X[part.train], part.train_y, points[part.train], inner)
                        fitted = make_model(name, params).fit(X[part.train], part.train_y)
                        sums[part.test] += fitted.predict_proba(X[part.test])[:, 1]
                        counts[part.test] += 1
                        audit.append({"cv": cv, "fold": part.name, "model": name, "feature_set": feature,
                                      "selected_params": params, "trials": trials})
                    if np.any(counts[fold.test] == 0):
                        raise ValueError("예측되지 않은 시험 격자")
                    prediction = sums[fold.test] / counts[fold.test]
                    values = score_metrics(fold.test_y, prediction, points[fold.test])
                    record(name, feature, cv, fold.name, values, len(fold.test), int(fold.test_y.sum()))
                    saved[f"{name}_{feature}"] = prediction
                    if cv == "spatial":
                        oof[f"{name}_{feature}"][fold.test] = prediction
                    print(f"  {feature}/{name} cluster_auc={values['cluster_auc']:.6f} elapsed={time.monotonic() - started:.1f}s", flush=True)
            np.savez_compressed(OUTPUT / f"predictions_{cv}_{fold.name}.npz", **saved)
            pd.DataFrame(rows).to_csv(OUTPUT / "results_dev.csv", index=False)
            write_json(OUTPUT / "tuning_audit.json", audit)

        table = pd.DataFrame(rows)
        for (model, feature, cv), subset in table.groupby(["model", "feature_set", "cv"], sort=False):
            values = subset.groupby("metric").value.mean().to_dict()
            summaries[model, feature, cv] = values
            record(model, feature, cv, "mean", values, 0, 0)
            if cv == "spatial":
                key = model if feature == "baseline" else f"{model}_{feature}"
                record(model, feature, cv, "pooled_oof", score_metrics(labels, oof[key], points), len(labels), int(labels.sum()))
        ranking = []
        for feature in FEATURES:
            for model in CANDIDATES:
                selection_score = np.mean([summaries[model, feature, cv]["cluster_auc"] for cv in ["spatial", "loeo"]])
                ranking.append({"model": model, "feature_set": feature, "selection_score": float(selection_score)})
        ranking.sort(key=lambda item: -item["selection_score"])
        chosen = ranking[0]
        final_inner = spatial_folds(points, labels, n_splits=3, groups=groups)
        params, trials = tune_model(chosen["model"], matrices[chosen["feature_set"]], labels, points, final_inner)
        fitted = make_model(chosen["model"], params).fit(matrices[chosen["feature_set"]], labels)
        joblib.dump(fitted, OUTPUT / "final_model.joblib")
    for path, expected in (protocol["code_sha256"] | protocol["input_sha256"]).items():
        if sha256(ROOT / path) != expected:
            raise RuntimeError(f"실행 중 입력 또는 코드 변경: {path}")
    table = pd.DataFrame(rows)
    table.to_csv(OUTPUT / "results_dev.csv", index=False)
    gate_rows = []
    for (model, feature, cv), values in summaries.items():
        gate_rows.append({"model": model, "feature_set": feature, "cv": cv,
                          "mean_grid_auc": values["grid_auc"], "mean_top20_capture": values["top20_capture"],
                          "auc_gate_pass": values["grid_auc"] >= 0.70,
                          "capture_gate_pass": values["top20_capture"] >= 0.50})
    pd.DataFrame(gate_rows).to_csv(OUTPUT / "gates_dev.csv", index=False)
    leak_checks = {
        "preprocessing": "중앙값·평균·표준편차는 내부/외부 해당 학습 fold에서만 fit",
        "frequency_bins": "분위 경계·빈도비·희소 구간 smoothing은 해당 학습 fold에서만 fit",
        "hyperparameters": "외부 시험 점수와 무관하게 내부 3-fold cluster_auc로만 선택",
        "proximity": "해당 학습 fold 양성 중심점만 사용; 시험 행과 원천 중복 시 오류",
        "spatial_clusters": "150m 양성 연결 덩어리가 걸친 블록을 병합해 같은 fold에 배정",
        "buffer": "시험 2km 블록과 학습 100m 격자 사각형 간 거리 >300m",
        "loeo": "뺀 사상 양성 전부 제외; 모든 음성은 그룹 교차 예측으로 학습·시험 중복 0",
        "holdout": "개발 가공 파일 2개만 읽음; 원본 흔적 로더 및 파이프라인 미사용",
    }
    protocol.update({"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                     "n_grid": len(labels), "n_positive": int(labels.sum()),
                     "n_clusters": int(len(np.unique(spatial_clusters(points[labels, 0], points[labels, 1])))),
                     "ranking": ranking, "selection": chosen | {"parameters": FIXED_PARAMS[chosen["model"]] | params,
                                                               "feature_columns": FEATURES[chosen["feature_set"]]},
                     "final_parameter_trials": trials, "leakage_checklist": leak_checks,
                     "elapsed_seconds": round(time.monotonic() - started, 3),
                     "final_model_sha256": sha256(OUTPUT / "final_model.joblib"),
                     "results_sha256": sha256(OUTPUT / "results_dev.csv"),
                     "holdout_evaluation": "동결 모델·특징·사전 게이트를 그대로 사용; 홀드아웃 평가 후 재튜닝 금지"})
    write_json(OUTPUT / "fold_audit.json", fold_info)
    write_json(OUTPUT / "prespec.json", protocol)
    print(json.dumps({"run_id": run_id, "selection": protocol["selection"],
                      "elapsed_seconds": protocol["elapsed_seconds"], "result_rows": len(table)}, ensure_ascii=False), flush=True)
    return protocol


if __name__ == "__main__":
    # 직렬화된 사용자 정의 모델도 다른 프로세스에서 불러올 수 있게 한다.
    from src.models.benchmark import run as run_benchmark

    run_benchmark()
