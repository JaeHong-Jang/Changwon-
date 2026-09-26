"""개발 교차검증을 실행하고 비교 결과와 최종 모델을 동결한다."""

from __future__ import annotations

import json
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.data.uncertainty import spatial_clusters
from src.models.estimators import CANDIDATES, FIXED_PARAMS, FrequencyRatio, make_model
from src.models.features import (
    EVENTS, F0, F1, FEATURES, ROOT, feature_frame, load_development, load_development_traces,
)
from src.models.folds import (
    block_groups, crossfit_event, event_folds, loeo_groups, past_flood_score, spatial_folds,
)
from src.models.provenance import file_sha256, write_json
from src.models.scoring import METRICS, score_metrics
from src.models.tuning import tune_model

# 기존 호출자와 저장된 사용자 정의 모델의 import 경로를 유지한다.
sha256 = file_sha256
OUTPUT = ROOT / ".omc/benchmark"

SELECTION_RULE = (
    "모델·특징: 공간 5-fold 평균 cluster_auc와 LOEO 6-fold 평균 cluster_auc의 산술평균 최대. "
    "동점: FEATURES 및 CANDIDATES 선언 순서. 기준선은 후보에서 제외. "
    "하이퍼파라미터: 각 외부 학습 자료 안의 버퍼 적용 공간 그룹 3-fold 평균 cluster_auc 최대, "
    "동점은 후보 선언 순서. 최종 파라미터도 전체 개발 자료의 동일한 내부 CV로 결정. "
    "선택된 모델의 개발 CV 점수는 선택 편향이 있으므로 최종 성능 추정으로 해석하지 않는다."
)


def run(output: Path = OUTPUT) -> dict[str, Any]:
    """사전 설정을 먼저 기록한 뒤 개발 벤치마크와 최종 동결 파일을 만든다."""
    # 실행·직렬화·표 저장과 병렬도 제한 도구를 불러온다.
    import joblib
    import pandas as pd
    import sklearn
    import xgboost
    from threadpoolctl import threadpool_limits
    from src.data import flood_traces

    # 출력 덮어쓰기를 막고 코드·개발 입력의 해시 대상을 정한다.
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "prespec.json").exists():
        raise FileExistsError("동결된 prespec.json을 덮어쓸 수 없다")
    run_id = datetime.now(timezone.utc).strftime("P005_dev_%Y%m%dT%H%M%SZ")
    sources = ["src/models/folds.py", "src/models/benchmark.py", "tests/test_benchmark.py",
               "src/models/features.py", "src/models/estimators.py", "src/models/scoring.py",
               "src/models/tuning.py", "src/models/provenance.py",
               "src/data/uncertainty.py", "src/data/flood_traces.py", "src/data/spatial.py",
               "config/flood_traces.yaml"]
    inputs = ["data/processed/layers/layer1_flood.gpkg", "data/processed/features/grid_features.parquet"]
    for path in flood_traces.files_for("development"):
        parts = [path.with_suffix(suffix) for suffix in [".shp", ".shx", ".dbf", ".prj", ".cpg"]] if path.suffix == ".shp" else [path]
        inputs.extend(str(part.relative_to(ROOT)) for part in parts if part.exists())
    # 출력 위치와 무관하게 기존 v1 사전등록의 동결 설정을 확인한다.
    previous = json.loads((OUTPUT / "v1/prespec.json").read_text(encoding="utf-8"))
    for key, value in [("candidates", CANDIDATES), ("features", FEATURES),
                       ("selection_rule", SELECTION_RULE), ("fixed_parameters", FIXED_PARAMS)]:
        if previous[key] != value:
            raise ValueError(f"v1의 동결 설정 변경 금지: {key}")
    # 평가 전에 설정·자료 출처·한계와 고정 게이트를 기록한다.
    protocol = {
        "run_id": run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": "env -u CHANGWON_HOLDOUT_TESTS PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /home/data/.venv-changwon/bin/python -m src.models.benchmark"
                   + (f" --output {shlex.quote(str(output))}" if output != OUTPUT else ""),
        "code_sha256": {path: file_sha256(ROOT / path) for path in sources},
        "input_sha256": {path: file_sha256(ROOT / path) for path in inputs},
        "features": FEATURES, "candidates": CANDIDATES, "fixed_parameters": FIXED_PARAMS,
        "selection_rule": SELECTION_RULE, "versions": {"sklearn": sklearn.__version__, "xgboost": xgboost.__version__},
        "seed": 42, "population": "전체 격자; universe 필터 없음", "development_events": EVENTS,
        "outer_spatial": {"n_splits": 5, "block_m": 2000, "buffer_m": 300, "cell_m": 100,
                          "cluster_radius_m": 150, "block_origin": [0, 0]},
        "inner": {"n_splits": 3, "block_m": 2000, "buffer_m": 300, "metric": "cluster_auc"},
        "loeo": "시험=뺀 사상 양성+모든 영구 음성. 음성을 공간 그룹 3분할 교차 예측; 시험 양성은 3개 모델 예측 평균. 중복 사상 양성도 학습에서 제외.",
        "loeo_groups": "사상별로 뺀 열을 제거한 학습 사상 합집합으로 공간·배경 그룹을 구성; 내부 CV도 해당 그룹과 학습 라벨만 사용. 시험 라벨은 행 제외·평가에만 사용.",
        "top20_ties": "정확히 20% 예산, 경계 동점은 분수 가중", "class_weight": "없음",
        "preprocessing": "모든 모델 학습 fold 중앙값 결측 대치; ridge만 학습 fold 평균·표준편차",
        "past_flood": "개발 원본 중 학습 event_year 폴리곤까지 격자 중심점 최근접 거리 음수; 내부는 0. 공간 CV는 학습 격자와 겹치되 시험 격자와 겹치지 않는 원본만 사용.",
        "holdout_read": False, "holdout_scored": False,
        "revision": {"type": "post-hoc review correction; 최초 사전등록 아님",
                     "review": ".omc/review/RV1.md 발견 1~3",
                     "reasons": {"1": "v1 전체 테스트에서 홀드아웃 읽기 발생; 이번에는 환경변수 없이 tests.test_benchmark만 실행",
                                 "2": "LOEO 전역 그룹 누수를 학습 사상별 그룹으로 수정",
                                 "3": "양성 격자 중심점 대리값을 학습 사상 원본 폴리곤 거리로 수정"},
                     "v1_run_id": previous["run_id"], "v1_selection": previous["selection"],
                     "v1_holdout_read": previous["holdout_read"],
                     "v1_prespec_sha256": file_sha256(OUTPUT / "v1/prespec.json"),
                     "unchanged": ["CANDIDATES", "FEATURES", "SELECTION_RULE", "FIXED_PARAMS"]},
        "gates": {"grid_auc_min": 0.70, "top20_capture_min": 0.50},
        "limitations": [
            "기존 홀드아웃 실패가 알려진 뒤 제안된 비교 설계다. 이번 실행은 홀드아웃 파일을 읽지 않지만 최초 사전등록 분석은 아니다.",
            "고정 기준선 L1·z_sensitivity는 제공된 동결 값을 사용한다. 과거 전체 격자 정규화 이력은 재학습하지 않는다.",
            "빈도비 sigmoid 출력은 보정된 발생 확률이 아니라 순위 점수다.",
            "폴리곤 1표 평가는 기존 비교 지표 범위에 없어 산출하지 않는다; 이번 수정의 원본 폴리곤은 근접도 기준선에 사용한다.",
            "LOEO 음성은 사상별로 반복 채점된다. 사상 간 통합 OOF 값 대신 사상별 값과 비가중 평균을 보고한다.",
            "공간 CV에서 학습·시험 격자에 동시에 걸친 원본 폴리곤은 근접도 원천에서 통째로 제외한다.",
        ],
    }
    # 개발 자료를 읽어 공간·사상별 분할과 특징 행렬을 준비한다.
    write_json(output / "protocol_dev.json", protocol)
    layer, frame, points, labels, events = load_development()
    traces, trace_metadata = load_development_traces()
    groups = block_groups(points, labels)
    spatial = spatial_folds(points, labels, groups=groups)
    event = event_folds(events, [str(year) for year in EVENTS])
    event_grouping = {fold.name: loeo_groups(points, events, i) for i, fold in enumerate(event)}
    matrices = {feature: frame[columns].to_numpy(dtype=float) for feature, columns in FEATURES.items()}
    spatial_assignment = np.empty(len(labels), dtype=int)
    for i, fold in enumerate(spatial):
        spatial_assignment[fold.test] = i
    assignments = {"grid_id": layer.grid_id, "atomic_group": groups, "spatial_fold": spatial_assignment}
    for name, (event_groups, background) in event_grouping.items():
        assignments[f"loeo_{name}_atomic_group"] = event_groups
        assignments[f"loeo_{name}_background_group"] = background
    # 분할 배정을 저장하고 지표·감사·OOF 예측 버퍼를 초기화한다.
    pd.DataFrame(assignments).to_csv(output / "fold_assignments.csv", index=False)
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
        # 실행 식별자와 fold별 표본 수를 각 지표 행에 붙인다.
        for metric, value in values.items():
            rows.append({"run_id": run_id, "model": model, "feature_set": feature, "cv": cv,
                         "fold": fold, "metric": metric, "value": value,
                         "n_test": n_test, "n_positive": n_positive})

    # 정해진 병렬도로 외부 CV와 내부 후보 선택을 실행한다.
    with threadpool_limits(limits=2):
        for cv, fold in jobs:
            print(f"{run_id} {cv}/{fold.name} train={len(fold.train)} test={len(fold.test)} positives={int(fold.test_y.sum())}", flush=True)
            fold_groups = groups if cv == "spatial" else event_grouping[fold.name][0]
            parts = [fold] if cv == "spatial" else crossfit_event(fold, event_grouping[fold.name][1])
            train_events = [str(year) for year in EVENTS if cv == "spatial" or str(year) != fold.name]
            part_inner = []
            for part in parts:
                if np.intersect1d(part.train, part.test).size:
                    raise ValueError("외부 학습·시험 행 중복")
                inner = spatial_folds(points[part.train], part.train_y, n_splits=3, groups=fold_groups[part.train])
                part_inner.append(inner)
                fold_info.append({"cv": cv, "fold": part.name, "n_train": len(part.train),
                                  "n_train_positive": int(part.train_y.sum()), "n_test": len(part.test),
                                  "n_test_positive": int(part.test_y.sum()), "train_test_overlap": 0,
                                  "inner": [{"train": len(f.train), "positive_train": int(f.train_y.sum()),
                                             "test": len(f.test), "positive_test": int(f.test_y.sum())} for f in inner]})
            # 고정 지수와 학습 사상 원본 거리의 기준선 예측을 만든다.
            outputs = dict(frozen)
            sums, counts = np.zeros(len(labels)), np.zeros(len(labels), dtype=int)
            for part in parts:
                sums[part.test] += past_flood_score(points, traces, part.test, train_events,
                                                   train=part.train if cv == "spatial" else None)
                counts[part.test] += 1
            outputs["past_flood"] = sums / np.maximum(counts, 1)
            for name, prediction in outputs.items():
                values = score_metrics(fold.test_y, prediction[fold.test], points[fold.test])
                record(name, "baseline", cv, fold.name, values, len(fold.test), int(fold.test_y.sum()))
                if cv == "spatial":
                    oof[name][fold.test] = prediction[fold.test]
            saved = {"grid_id": layer.grid_id.to_numpy(dtype=str)[fold.test], "labels": fold.test_y}
            saved.update({name: prediction[fold.test] for name, prediction in outputs.items()})
            # 특징·모델별 내부 튜닝 후 외부 시험 예측과 감사 기록을 모은다.
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
            # 완료된 fold의 예측과 누적 결과를 저장한다.
            np.savez_compressed(output / f"predictions_{cv}_{fold.name}.npz", **saved)
            pd.DataFrame(rows).to_csv(output / "results_dev.csv", index=False)
            write_json(output / "tuning_audit.json", audit)

        # fold 평균과 공간 OOF 지표를 계산해 사전 규칙으로 모델을 선택한다.
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
        # 전체 개발 자료의 내부 CV로 최종 파라미터를 정하고 모델을 저장한다.
        final_inner = spatial_folds(points, labels, n_splits=3, groups=groups)
        params, trials = tune_model(chosen["model"], matrices[chosen["feature_set"]], labels, points, final_inner)
        fitted = make_model(chosen["model"], params).fit(matrices[chosen["feature_set"]], labels)
        joblib.dump(fitted, output / "final_model.joblib")
    # 실행 중 코드·입력 변경이 없음을 확인하고 최종 지표를 저장한다.
    for path, expected in (protocol["code_sha256"] | protocol["input_sha256"]).items():
        if file_sha256(ROOT / path) != expected:
            raise RuntimeError(f"실행 중 입력 또는 코드 변경: {path}")
    table = pd.DataFrame(rows)
    table.to_csv(output / "results_dev.csv", index=False)
    # 사전 게이트의 통과 여부를 모델·특징·CV별로 보존한다.
    gate_rows = []
    for (model, feature, cv), values in summaries.items():
        gate_rows.append({"model": model, "feature_set": feature, "cv": cv,
                          "mean_grid_auc": values["grid_auc"], "mean_top20_capture": values["top20_capture"],
                          "auc_gate_pass": values["grid_auc"] >= 0.70,
                          "capture_gate_pass": values["top20_capture"] >= 0.50})
    pd.DataFrame(gate_rows).to_csv(output / "gates_dev.csv", index=False)
    # 누수 방지 근거와 최종 선택·출력 해시를 동결 기록에 추가한다.
    leak_checks = {
        "preprocessing": "중앙값·평균·표준편차는 내부/외부 해당 학습 fold에서만 fit",
        "frequency_bins": "분위 경계·빈도비·희소 구간 smoothing은 해당 학습 fold에서만 fit",
        "hyperparameters": "외부 시험 점수와 무관하게 내부 3-fold cluster_auc로만 선택",
        "proximity": "학습 사상 원본 폴리곤 거리; 공간 CV는 학습 영역에서만 선택하고 시험 격자에 걸친 원본 제외",
        "spatial_clusters": "공간 전이는 전체 라벨 덩어리를 보존; LOEO는 학습 사상 라벨만으로 공간·배경·내부 CV 그룹 구성",
        "buffer": "시험 2km 블록과 학습 100m 격자 사각형 간 거리 >300m",
        "loeo": "뺀 사상 양성 전부 제외; 모든 음성은 그룹 교차 예측으로 학습·시험 중복 0",
        "holdout": "개발 가공 파일과 load(files_for('development'))만 사용; tests.test_benchmark만 실행",
    }
    protocol.update({"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                     "n_grid": len(labels), "n_positive": int(labels.sum()),
                     "n_clusters": int(len(np.unique(spatial_clusters(points[labels, 0], points[labels, 1])))),
                     "ranking": ranking, "selection": chosen | {"parameters": FIXED_PARAMS[chosen["model"]] | params,
                                                               "feature_columns": FEATURES[chosen["feature_set"]]},
                     "final_parameter_trials": trials, "leakage_checklist": leak_checks,
                     "development_trace_metadata": trace_metadata,
                     "elapsed_seconds": round(time.monotonic() - started, 3),
                     "final_model_sha256": file_sha256(output / "final_model.joblib"),
                     "results_sha256": file_sha256(output / "results_dev.csv"),
                     "holdout_evaluation": "동결 모델·특징·사전 게이트를 그대로 사용; 홀드아웃 평가 후 재튜닝 금지"})
    protocol["revision"]["selection_matches_v1"] = all(
        protocol["selection"][key] == previous["selection"][key]
        for key in ["model", "feature_set", "parameters", "feature_columns"]
    )
    # 분할 감사와 동결 기록을 저장하고 실행 요약을 반환한다.
    write_json(output / "fold_audit.json", fold_info)
    write_json(output / "prespec.json", protocol)
    print(json.dumps({"run_id": run_id, "selection": protocol["selection"],
                      "elapsed_seconds": protocol["elapsed_seconds"], "result_rows": len(table)}, ensure_ascii=False), flush=True)
    return protocol


if __name__ == "__main__":
    # CLI의 출력 위치를 파싱하고 import 가능한 모듈에서 실행한다.
    import argparse
    from src.models.benchmark import run as run_benchmark

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT, metavar="DIR")
    run_benchmark(output=parser.parse_args().output)
