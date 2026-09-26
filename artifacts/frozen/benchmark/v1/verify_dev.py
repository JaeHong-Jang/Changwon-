"""저장한 개발 예측과 분할을 원본 개발 격자에서 재검산한다."""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from threadpoolctl import threadpool_limits

from src.data.uncertainty import spatial_clusters
from src.models.benchmark import FEATURES, ROOT, load_development, score_metrics, sha256
from src.models.folds import crossfit_event, event_folds, outside_buffer, past_flood_score, spatial_folds


def main() -> None:
    """예측 재계산·분할 불변식·파일 무결성 결과를 기록한다."""
    output = ROOT / ".omc/benchmark"
    spec = json.loads((output / "prespec.json").read_text())
    for path, expected in (spec["code_sha256"] | spec["input_sha256"]).items():
        assert sha256(ROOT / path) == expected, path
    assert sha256(output / "final_model.joblib") == spec["final_model_sha256"]
    assert sha256(output / "results_dev.csv") == spec["results_sha256"]
    layer, frame, points, labels, events = load_development()
    assignments = pd.read_csv(output / "fold_assignments.csv")
    np.testing.assert_array_equal(assignments.grid_id.astype(str), layer.grid_id.astype(str))
    groups = assignments.atomic_group.to_numpy()
    cluster_ids = spatial_clusters(points[labels, 0], points[labels, 1])
    for cluster in np.unique(cluster_ids):
        assert np.ptp(assignments.spatial_fold.to_numpy()[labels][cluster_ids == cluster]) == 0
    spatial = spatial_folds(points, labels, groups=groups)
    loeo = event_folds(events, [str(year) for year in spec["development_events"]])
    table = pd.read_csv(output / "results_dev.csv", dtype={"fold": str})
    n_values = 0
    n_parts = 0
    counts = np.zeros(len(labels), dtype=int)
    for cv, folds in [("spatial", spatial), ("loeo", loeo)]:
        for fold in folds:
            if cv == "spatial":
                counts[fold.test] += 1
                assert outside_buffer(points[fold.train], points[fold.test]).all()
            parts = [fold] if cv == "spatial" else crossfit_event(fold, assignments.loeo_background_group.to_numpy())
            for part in parts:
                assert np.intersect1d(part.train, part.test).size == 0
                test = part.test[::max(1, len(part.test) // 101)]
                sources = part.train[part.train_y]
                expected = -cdist(points[test], points[sources]).min(axis=1)
                np.testing.assert_allclose(past_flood_score(points, part.train, part.train_y, test), expected)
                inner = spatial_folds(points[part.train], part.train_y, n_splits=3, groups=groups[part.train])
                for split in inner:
                    assert np.intersect1d(groups[part.train][split.train], groups[part.train][split.test]).size == 0
                    assert outside_buffer(points[part.train][split.train], points[part.train][split.test]).all()
                n_parts += 1
            with np.load(output / f"predictions_{cv}_{fold.name}.npz", allow_pickle=False) as saved:
                np.testing.assert_array_equal(saved["grid_id"], layer.grid_id.to_numpy(dtype=str)[fold.test])
                np.testing.assert_array_equal(saved["labels"], fold.test_y)
                subset = table[(table.cv == cv) & (table.fold == fold.name)]
                for (model, feature), metric_rows in subset.groupby(["model", "feature_set"]):
                    key = model if feature == "baseline" else f"{model}_{feature}"
                    values = score_metrics(fold.test_y, saved[key], points[fold.test])
                    for row in metric_rows.itertuples():
                        np.testing.assert_allclose(row.value, values[row.metric], rtol=1e-12, atol=1e-12)
                        n_values += 1
    np.testing.assert_array_equal(counts, 1)
    fitted = joblib.load(output / "final_model.joblib")
    selection = spec["selection"]
    predictions = fitted.predict_proba(frame[FEATURES[selection["feature_set"]]].to_numpy(dtype=float))[:, 1]
    assert len(predictions) == len(labels) and np.isfinite(predictions).all()
    gates = table[table.metric.isin(["grid_auc", "top20_capture"])].pivot(
        index=["model", "feature_set", "cv", "fold"], columns="metric", values="value"
    ).reset_index()
    gates["auc_gate_pass"] = gates.grid_auc >= spec["gates"]["grid_auc_min"]
    gates["capture_gate_pass"] = gates.top20_capture >= spec["gates"]["top20_capture_min"]
    gates.to_csv(output / "gates_all_folds.csv", index=False)
    summary = {"run_id": spec["run_id"], "verified_metric_values": n_values,
               "verified_outer_parts": n_parts, "verified_inner_splits": n_parts * 3,
               "spatial_test_coverage_min": int(counts.min()), "spatial_test_coverage_max": int(counts.max()),
               "cluster_split_violations": 0, "buffer_violations": 0, "train_test_overlap": 0,
               "model_reload_finite_predictions": len(predictions), "hashes_match": True,
               "result_rows": len(table), "elapsed_seconds": spec["elapsed_seconds"],
               "selected": selection, "self_verification_only": True}
    (output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(table[(table.model == selection["model"]) & (table.feature_set == selection["feature_set"])
                & table.fold.isin(["mean", "pooled_oof"])][["cv", "fold", "metric", "value"]].to_string(index=False))


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        main()
