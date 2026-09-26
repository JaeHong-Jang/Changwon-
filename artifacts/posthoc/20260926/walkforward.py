"""시간 순 검증: 사상마다 그 이전 개발 사상으로만 학습해 그 사상을 채점한다 (리더 전용 일회성, post-hoc)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone

from src.data import flood_traces as FT
from src.data import validation as V
from src.models.features import feature_frame
from src.models.holdout_scores import MODELS
from src.models.provenance import git_state
from src.utils.config import PROJECT_ROOT as ROOT

DEV_YEARS = (2006, 2012, 2014, 2016, 2019, 2025)
KEEP = {("cell_gate", "observed-label_auc"), ("cell_gate", "capture_0.2"), ("cluster_gate", "observed-label_auc"),
        ("object", "observed-label_auc"), ("object", "capture_0.2")}


def rf_trained_before(frame, layer, year, model, columns):
    """동결 RF-F1 설정을 year 이전 개발 사상(2025 제외, 홀드아웃 제외)으로만 다시 학습한 점수."""
    prior = [y for y in DEV_YEARS if y < year and y != 2025]
    if not prior:
        return None, prior
    y_train = layer[[f"trace_ev_{y}" for y in prior]].to_numpy().any(axis=1)
    X = frame[columns].to_numpy(float)
    return clone(model).fit(X, y_train).predict_proba(X)[:, 1], prior


def main() -> dict:
    """개발 6사상과 홀드아웃 4사상을 시간 순으로 채점한다."""
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT)
    run_id = f"walkforward_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"

    # 격자·특징·흔적과 동결 RF-F1 설정을 읽는다
    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    features = pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet")
    frame = feature_frame(layer, features)
    development, _ = FT.load(FT.files_for("development"))
    holdout, _ = FT.load(FT.files_for("holdout"))
    model_path, prespec_path = MODELS["v2"]
    model = joblib.load(model_path)
    columns = json.loads(prespec_path.read_text(encoding="utf-8"))["selection"]["feature_columns"]

    # 어떤 흔적과도 닿지 않은 격자를 배경으로 잡는다 (holdout_eval 과 같은 정의)
    touched = np.zeros(len(layer), bool)
    for traces in (holdout, development):
        touched[gpd.sjoin(layer[["geometry"]], traces[["geometry"]], predicate="intersects").index.unique()] = True

    # 시험 사상 목록: 개발은 연도, 홀드아웃은 호우 단위 (날짜 없는 흔적은 제외)
    tests = []
    for y in DEV_YEARS:
        polys = development[development["event_date"].dt.year == y]
        tests.append((str(y), "development", y, polys))
    for storm, polys in holdout.groupby("storm_id"):
        tests.append((str(storm), "holdout", int(polys["event_date"].dt.year.iloc[0]), polys))
    n_undated = int(development["event_date"].isna().sum())

    # 사상마다 고정 점수와 이전 사상 학습 RF 를 같은 평가 함수로 채점한다
    fixed = {"L1": layer["L1"].to_numpy(float), "z_sensitivity": layer["z_sensitivity"].to_numpy(float),
             "city_flood_map": frame["flood_l210_100_depth_m"].to_numpy(float)}
    rows, train_sets = [], {}
    for name, role, year, polys in tests:
        scores = dict(fixed)
        rf, prior = rf_trained_before(frame, layer, year, model, columns)
        if rf is not None:
            scores["rf_walkforward"] = rf
        train_sets[name] = prior
        table = V.evaluate(scores, layer, polys.reset_index(drop=True), background_mask=~touched,
                           n_boot=1000, seed=42)
        table = table[(table["storm"] == "ALL") & table[["unit", "metric"]].apply(tuple, axis=1).isin(KEEP)]
        rows.append(table.assign(test_event=name, role=role, year=year, n_polygons=len(polys)))
        print(f"{name} done ({len(polys)} polygons, RF trained on {prior})", file=sys.stderr, flush=True)

    # 실행별 폴더에 긴 표와 요약을 남긴다
    out = ROOT / ".omc/posthoc_h" / run_id
    out.mkdir(parents=True, exist_ok=False)
    long = pd.concat(rows, ignore_index=True).assign(run_id=run_id)
    long.to_csv(out / "metrics_long.csv", index=False, encoding="utf-8-sig")
    result = {"run_id": run_id, "started_utc": started.isoformat(), "git_head": head, "source_dirty": dirty,
              "command": "PYTHONPATH=. python .omc/posthoc_h/walkforward.py",
              "role": ("post_hoc — 시간 순 재평가. RF-F1 특징·하이퍼파라미터는 개발 6사상 CV 로 골랐고 특징 후보군은 "
                       "홀드아웃 진단 뒤 정했다. 홀드아웃은 학습에 쓰지 않았다 (AGENTS §2-2)"),
              "rf_train_events": train_sets, "n_undated_dev_polygons_excluded": n_undated}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
