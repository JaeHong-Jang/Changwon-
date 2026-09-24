"""2022~2024 홀드아웃의 점수와 게이트를 실행하고 결과를 기록한다."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.models.gates import GATE, gate, gate as _gate
from src.models.holdout_scores import (HOLDOUT_START, MODELS, PRE_HOLDOUT_EVENTS, ROLES, build_scores,
                                       build_scores as _scores, feature_frame, frozen_scores as _frozen_scores)
from src.models.provenance import file_sha256, git_state, package_versions, vector_manifest

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/evaluation/holdout_2022_2024"
CODE_FILES = [  # 이 평가의 결과에 영향을 주는 코드 전부
    "src/models/holdout_eval.py", "src/models/holdout_scores.py", "src/models/gates.py", "src/models/provenance.py",
    "src/data/validation/__init__.py", "src/data/validation/_common.py", "src/data/validation/auc.py",
    "src/data/validation/curves.py", "src/data/validation/resampling.py", "src/data/validation/evaluate.py",
    "src/data/flood_traces.py", "src/data/trace_registry.py", "src/data/trace_events.py", "src/data/trace_labels.py",
    "src/data/layers.py", "src/data/uncertainty.py", "src/data/spatial.py", "src/stages/h06_layers.py",
    "src/models/features.py", "src/models/estimators.py", "config/flood_traces.yaml",
]
PROCESSED_FILES = ["data/processed/layers/layer1_flood.gpkg", "data/processed/features/grid_features.parquet"]


def run() -> dict[str, Any]:
    """홀드아웃을 채점하고 실행별 폴더에 결과·manifest 를 남긴다."""
    import geopandas as gpd
    import pandas as pd

    from src.data import flood_traces as FT
    from src.data import validation as V

    # 코드·가공 자료의 실행 출처를 기록할 식별자를 만든다.
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT)
    code_sha = {f: file_sha256(ROOT / f) for f in CODE_FILES}
    run_id = (f"holdout_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}_"
              f"{hashlib.sha256(json.dumps(code_sha, sort_keys=True).encode()).hexdigest()[:8]}")

    # 격자·특징·개발 및 홀드아웃 흔적을 기존 순서로 읽는다.
    layer = gpd.read_file(ROOT / PROCESSED_FILES[0]).sort_values("grid_id").reset_index(drop=True)
    features = pd.read_parquet(ROOT / PROCESSED_FILES[1])
    frame = feature_frame(layer, features)
    dev_files, holdout_files = FT.files_for("development"), FT.files_for("holdout")
    holdout, holdout_meta = FT.load(holdout_files)
    development, dev_meta = FT.load(dev_files)
    for meta in (holdout_meta, dev_meta):
        if meta["skipped_files"]:
            raise RuntimeError(f"읽지 못한 흔적 파일: {meta['skipped_files']}")
    scores, model_info = build_scores(layer, frame, features, development)
    centers = layer.geometry.centroid
    points = np.column_stack([centers.x, centers.y])

    # 홀드아웃과 개발 라벨에 동일한 게이트를 적용한다.
    labels, _ = FT.label_grid(layer, holdout, min_overlap=0.10)
    gates = {name: gate(labels, score, points) for name, score in scores.items()}
    dev_labels = layer["trace_label"].to_numpy().astype(bool)
    dev_gates = {name: gate(dev_labels, scores[name], points)
                 for name in ("L1", "z_sensitivity", "z_exposure", "city_flood_map")}

    # 개발·홀드아웃 흔적 어느 쪽에도 닿지 않은 격자를 배경으로 잡는다.
    touched = np.zeros(len(layer), bool)
    for traces in (holdout, development):
        touched[gpd.sjoin(layer[["geometry"]], traces[["geometry"]], predicate="intersects").index.unique()] = True
    land = holdout["land_use"].fillna("")
    subsets = {
        "all": holdout,
        "urban": holdout[land.str.startswith("도심")],
        "agricultural": holdout[land.str.startswith("농")],
        "no_landuse_attr": holdout[land.eq("")],
    }
    tables = []
    for name, subset in subsets.items():
        table = V.evaluate(scores, layer, subset.reset_index(drop=True), background_mask=~touched,
                           reference="city_flood_map", n_boot=2000, seed=42)
        tables.append(table.assign(polygon_subset=name, n_polygons=len(subset)))
    table = pd.concat(tables, ignore_index=True)
    roles = pd.DataFrame([(k, *v) for k, v in ROLES.items()],
                         columns=["score", "score_role", "post_hoc_design", "confirmatory"])
    table = table.merge(roles, on="score", how="left").assign(run_id=run_id)

    # 원래 JSON 키와 CSV 컬럼으로 실행별 평가 산출물을 저장한다.
    out_dir = OUTPUT / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    result = {
        "run_id": run_id,
        "command": "python -m src.models.holdout_eval",
        "started_utc": started.isoformat(),
        "git_head": head, "source_dirty": dirty,
        "versions": package_versions(),
        "code_sha256": code_sha,
        "processed_sha256": {f: file_sha256(ROOT / f) for f in PROCESSED_FILES},
        "raw_sha256": {"development": vector_manifest(dev_files, ROOT), "holdout": vector_manifest(holdout_files, ROOT)},
        "models": model_info,
        "score_roles": {k: {"role": v[0], "post_hoc_design": v[1], "confirmatory": v[2]} for k, v in ROLES.items()},
        "holdout": {k: holdout_meta[k] for k in ("n_traces", "n_storms", "union_area_km2", "invalid_fixed",
                                                  "date_typo_repairs", "skipped_files")},
        "polygons_by_storm": holdout["storm_id"].value_counts().sort_index().to_dict(),
        "polygons_by_subset": {k: int(len(v)) for k, v in subsets.items()},
        "n_background_cells": int((~touched).sum()),
        "gate_definition": GATE | {"unit": "격자 1표, 10% 합집합 겹침 라벨, 음성 = 나머지 격자 (h06 과 동일 함수)",
                                   "ci": "gates 는 덩어리 재표본 4000회, metrics.csv 는 2000회 — 구간이 조금 다를 수 있다"},
        "gates": gates,
        "development_gates": dev_gates,
        "note": ("확증 근거는 L1 의 사전 게이트뿐이다. model_frozen 은 개발 자료로 동결한 v2 선택(분할 누수 수정 후)이지만 "
                 "특징 후보군은 리더가 홀드아웃 진단을 본 뒤 정했다(post_hoc_design). rf_F0_v1 은 분할 누수가 있던 "
                 "v1 선택으로 홀드아웃을 먼저 채점했기에 기록으로만 남긴다"),
    }
    table.to_csv(out_dir / "metrics.csv", index=False)
    (out_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str),
                                          encoding="utf-8")
    (OUTPUT / "latest.json").write_text(json.dumps({"run_id": run_id}, ensure_ascii=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    out = run()
    print(json.dumps({k: out[k] for k in ("run_id", "holdout", "polygons_by_subset")}, ensure_ascii=False))
    for name, g in out["gates"].items():
        if g["evaluable"]:
            print(f"{name:22s} cell {g['auc_cell']:.4f} cluster {g['auc_cluster']:.4f} "
                  f"top20 {g['top20_capture']:.4f} pass={g['passes_auc'] and g['passes_capture']}")
