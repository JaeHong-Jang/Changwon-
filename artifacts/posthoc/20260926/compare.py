"""post-hoc H 교체안 비교: H 후보마다 CDRI·TOP20 을 다시 만들고 개발·홀드아웃에서 잰다 (리더 전용 일회성)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from src.data import flood_traces as FT
from src.data import layers as L
from src.models.features import feature_frame
from src.models.gates import gate
from src.models.holdout_scores import build_scores
from src.models.provenance import git_state
from src.stages.h07_cdri import LAYER3_PATH
from src.stages.h08_policy import _suppress_neighbours
from src.utils.config import PROJECT_ROOT as ROOT

FLOOR, TOP_N, NMS_M, NEAR_M = 0.05, 20, 300.0, 300.0


def cdri_scores(h, comp, uni):
    """h07 과 같은 규칙(순위 대상 격자 안 재척도, 동일가중 기하평균)으로 CDRI 를 만든다."""
    m = np.column_stack([L.rescale_positive(h[uni], FLOOR)] + [L.rescale_positive(c[uni], FLOOR) for c in comp])
    return L.geometric_aggregate(m, np.full(4, 0.25))


def top20_hits(cells, polygons):
    """TOP20 격자가 흔적 폴리곤과 겹치는 수, 300 m 안에 드는 수, 300 m 안에 TOP20 이 있는 폴리곤 수."""
    poly = polygons[["geometry"]].reset_index(drop=True)
    inter = gpd.sjoin(cells[["geometry"]], poly, predicate="intersects").index.unique()
    near = gpd.sjoin(cells[["geometry"]].assign(geometry=cells.geometry.buffer(NEAR_M)), poly,
                     predicate="intersects")
    return {"top20_cells_touching_trace": int(len(inter)), "top20_cells_within_300m": int(near.index.nunique()),
            "polygons_within_300m_of_top20": int(near["index_right"].nunique()), "n_polygons": int(len(poly))}


def quintile_incidence(labels, score):
    """점수 5분위별 양성 격자 비율 (등급 역전 여부 확인용)."""
    q = pd.qcut(pd.Series(score).rank(method="first"), 5, labels=[f"Q{i}" for i in range(1, 6)])
    return {k: round(float(v), 5) for k, v in pd.Series(labels).groupby(q, observed=True).mean().items()}


def main(include_holdout: bool) -> dict:
    """개발(기본)과 홀드아웃(옵션)에서 H·CDRI·TOP20 을 비교한다."""
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT)
    run_id = f"posthoc_h_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"

    # holdout_eval 과 같은 순서로 격자·특징·개발 흔적을 읽고 H 후보 점수를 만든다
    layer = gpd.read_file(ROOT / "data/processed/layers/layer1_flood.gpkg").sort_values("grid_id").reset_index(drop=True)
    features = pd.read_parquet(ROOT / "data/processed/features/grid_features.parquet")
    frame = feature_frame(layer, features)
    development, _ = FT.load(FT.files_for("development"))
    scores, _ = build_scores(layer, frame, features, development)
    H = {"L1": scores["L1"], "z_sensitivity": scores["z_sensitivity"],
         "rf_to2019": scores["model_frozen_to2019"], "rf_frozen": scores["model_frozen"]}

    # Layer 3 의 E·V·D 와 순위 대상 격자를 붙이고, L1 로 기존 CDRI 가 재현되는지 확인한다
    l3 = pd.DataFrame(gpd.read_file(ROOT / LAYER3_PATH, layer="layer3_vuln").drop(columns="geometry"))
    df = layer[["grid_id", "geometry"]].merge(l3[["grid_id", "E", "V", "capacity_deficit", "universe"]],
                                              on="grid_id", how="left", validate="one_to_one")
    uni = df["universe"].fillna(0).astype(bool).to_numpy()
    comp = [df[c].to_numpy(float) for c in ("E", "V", "capacity_deficit")]
    saved = gpd.read_file(ROOT / "data/processed/layers/cdri.gpkg", layer="cdri", columns=["grid_id", "cdri_raw"])
    check = pd.DataFrame({"grid_id": df["grid_id"][uni], "mine": cdri_scores(H["L1"], comp, uni)}).merge(saved, on="grid_id")
    reproduce = {"n": int(len(check)), "n_universe": int(uni.sum()),
                 "max_abs_diff": float(np.abs(check["mine"] - check["cdri_raw"]).max())}

    # H 후보마다 CDRI 와 300 m NMS TOP20 을 만든다
    sub = df.loc[uni, ["grid_id", "geometry"]].reset_index(drop=True)
    cdri, tops = {}, {}
    for name, h in H.items():
        cdri[name] = cdri_scores(h, comp, uni)
        tops[name] = _suppress_neighbours(sub.assign(cdri=cdri[name]), NMS_M, TOP_N)
    overlap = {a: {b: len(set(tops[a].grid_id) & set(tops[b].grid_id)) for b in H} for a in H}

    # 개발 라벨(10% 규칙)과 흔적 폴리곤으로 H·CDRI·TOP20 을 잰다
    centers = layer.geometry.centroid
    points = np.column_stack([centers.x, centers.y])
    dev_y = layer["trace_label"].to_numpy().astype(bool)
    result = {"run_id": run_id, "started_utc": started.isoformat(), "git_head": head, "source_dirty": dirty,
              "command": f"PYTHONPATH=. python .omc/posthoc_h/compare.py{' --holdout' if include_holdout else ''}",
              "role": "post_hoc — 2022~2024 홀드아웃을 본 뒤 설계한 비교. 사전 게이트 결과(L1 탈락)를 대체하지 않는다",
              "reproduce_cdri_L1": reproduce, "top20_overlap": overlap, "development": {}, "holdout": {}}
    for name in H:
        result["development"][name] = {
            "H_gate_all_cells": gate(dev_y, H[name], points),
            "CDRI_gate_universe": gate(dev_y[uni], cdri[name], points[uni]),
            "CDRI_quintile_incidence": quintile_incidence(dev_y[uni], cdri[name]),
            "top20": top20_hits(tops[name], development),
        }
        print(f"dev {name} done", file=sys.stderr, flush=True)

    # 홀드아웃은 리더만 읽는다: 같은 10% 규칙 라벨과 폴리곤으로 잰다
    if include_holdout:
        holdout, _ = FT.load(FT.files_for("holdout"))
        ho_y, _ = FT.label_grid(layer, holdout, min_overlap=0.10)
        ho_y = np.asarray(ho_y).astype(bool)
        result["holdout_universe_positive_cells"] = int(ho_y[uni].sum())
        for name in H:
            result["holdout"][name] = {
                "H_gate_all_cells": gate(ho_y, H[name], points),
                "CDRI_gate_universe": gate(ho_y[uni], cdri[name], points[uni]),
                "CDRI_quintile_incidence": quintile_incidence(ho_y[uni], cdri[name]),
                "top20": top20_hits(tops[name], holdout),
            }
            print(f"holdout {name} done", file=sys.stderr, flush=True)

    # 실행별 폴더에 요약·TOP20·격자 점수를 남긴다
    out = ROOT / ".omc/posthoc_h" / run_id
    out.mkdir(parents=True, exist_ok=False)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    pd.concat([t.drop(columns="geometry").assign(H=k, order=range(1, len(t) + 1)) for k, t in tops.items()]).to_csv(
        out / "top20.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"grid_id": sub["grid_id"], **{f"cdri_{k}": v for k, v in cdri.items()}}).to_parquet(out / "cdri_variants.parquet")
    pd.DataFrame({"grid_id": layer["grid_id"], **{f"H_{k}": v for k, v in H.items()}}).to_parquet(out / "h_variants.parquet")
    return result


if __name__ == "__main__":
    r = main("--holdout" in sys.argv)
    print(json.dumps({k: r[k] for k in ("run_id", "reproduce_cdri_L1", "top20_overlap")}, ensure_ascii=False))
