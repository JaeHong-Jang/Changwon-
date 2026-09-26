"""비교 모델의 공간 분할·사상 분할·학습 전처리 누수를 검증한다."""

import unittest

import numpy as np

from src.data.uncertainty import spatial_clusters
from src.models.benchmark import CANDIDATES, FrequencyRatio, feature_frame, make_model, score_metrics, tune_model
from src.models.folds import (
    block_groups, crossfit_event, event_folds, group_assignment, outside_buffer,
    past_flood_score, spatial_folds,
)


def synthetic() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """독립 블록마다 양성과 음성이 있는 작은 합성 자료를 만든다."""
    rng = np.random.default_rng(14)
    points = np.array([[b * 4000 + 200 + i * 100, 200 + j * 100]
                       for b in range(18) for i in range(5) for j in range(4)], dtype=float)
    labels = np.tile(np.arange(20) < 5, 18)
    X = rng.normal(size=(len(points), 7))
    X[:, 0] += labels * 3
    X[::23, 2] = np.nan
    return points, labels, X


class FoldTest(unittest.TestCase):
    def test_cluster_crossing_block_boundary_stays_in_one_fold(self):
        points, labels, _ = synthetic()
        points = np.vstack([points, [[1990, 1900], [2090, 1900]]])
        labels = np.r_[labels, True, True]
        folds = spatial_folds(points, labels)
        assignment = np.full(len(labels), -1)
        for i, fold in enumerate(folds):
            assignment[fold.test] = i
            self.assertEqual(np.intersect1d(fold.train, fold.test).size, 0)
        self.assertTrue((assignment >= 0).all())
        clusters = spatial_clusters(points[labels, 0], points[labels, 1])
        for cluster in np.unique(clusters):
            self.assertEqual(np.unique(assignment[labels][clusters == cluster]).size, 1)
        self.assertEqual(assignment[-1], assignment[-2])

    def test_buffer_is_from_block_edge_and_grid_footprint(self):
        test = np.array([[100., 100.]])
        points = np.array([[2300., 100.], [2350., 100.], [2351., 100.], [2200., 2200.]])
        np.testing.assert_array_equal(outside_buffer(points, test), [False, False, True, False])
        points, labels, _ = synthetic()
        for fold in spatial_folds(points, labels):
            self.assertTrue(outside_buffer(points[fold.train], points[fold.test]).all())

    def test_proximity_uses_training_positives_only(self):
        points = np.array([[0., 0.], [100., 0.], [101., 0.], [1000., 0.]])
        scores = past_flood_score(points, np.array([0, 3]), np.array([True, False]), np.array([1, 2]))
        np.testing.assert_allclose(scores, [-100, -101])
        with self.assertRaises(ValueError):
            past_flood_score(points, np.array([0, 1]), np.array([True, True]), np.array([1]))

    def test_empty_proximity_source_is_constant(self):
        points = np.array([[0., 0.], [100., 0.]])
        np.testing.assert_array_equal(past_flood_score(points, np.array([0]), np.array([False]), np.array([1])), [0])

    def test_loeo_excludes_overlap_and_crossfits_all_negatives(self):
        events = np.array([[1, 0], [1, 1], [0, 1], [0, 0], [0, 0], [0, 0]], dtype=bool)
        assignment = np.array([0, 1, 2, 0, 1, 2])
        for fold in event_folds(events, ["a", "b"]):
            self.assertEqual(np.intersect1d(fold.train, fold.test[fold.test_y]).size, 0)
            counts = np.zeros(6, dtype=int)
            for part in crossfit_event(fold, assignment):
                self.assertEqual(np.intersect1d(part.train, part.test).size, 0)
                counts[part.test] += 1
            np.testing.assert_array_equal(counts[fold.test[~fold.test_y]], 1)
            np.testing.assert_array_equal(counts[fold.test[fold.test_y]], 3)


class ModelTest(unittest.TestCase):
    def test_all_model_pipelines_work_on_synthetic_data(self):
        points, labels, X = synthetic()
        fold = spatial_folds(points, labels)[0]
        for name, candidates in CANDIDATES.items():
            with self.subTest(model=name):
                model = make_model(name, candidates[0]).fit(X[fold.train], labels[fold.train])
                scores = model.predict_proba(X[fold.test])[:, 1]
                self.assertEqual(scores.shape, (len(fold.test),))
                self.assertTrue(np.isfinite(scores).all())
                self.assertEqual(set(score_metrics(labels[fold.test], scores, points[fold.test])),
                                 {"grid_auc", "cluster_auc", "observed_label_ap", "top20_capture"})

    def test_preprocessing_uses_training_statistics(self):
        model = make_model("ridge", {"C": 0.1})
        X = np.array([[1., np.nan], [3., 4.], [5., 6.], [7., 8.]])
        model.fit(X, np.array([0, 0, 1, 1]))
        np.testing.assert_allclose(model.named_steps["impute"].statistics_, [4, 6])
        before = model.named_steps["scale"].mean_.copy()
        model.predict_proba(np.array([[10000., 20000.]]))
        np.testing.assert_array_equal(before, model.named_steps["scale"].mean_)

    def test_frequency_edges_and_smoothing_are_training_only(self):
        X = np.arange(20.).reshape(-1, 1)
        model = FrequencyRatio(n_bins=5, alpha=1).fit(X, np.arange(20) < 2)
        edges = model.edges_[0].copy()
        scores = model.predict_proba(np.array([[-10000.], [10000.]]))
        self.assertTrue(np.isfinite(scores).all())
        np.testing.assert_array_equal(edges, model.edges_[0])
        self.assertTrue(np.isfinite(model.log_ratios_[0]).all())

    def test_nested_group_tuning_on_synthetic_data(self):
        points, labels, X = synthetic()
        groups = block_groups(points, labels)
        outer = spatial_folds(points, labels, groups=groups)[0]
        inner = spatial_folds(points[outer.train], labels[outer.train], groups=groups[outer.train], n_splits=3)
        for split in inner:
            self.assertEqual(np.intersect1d(groups[outer.train][split.train], groups[outer.train][split.test]).size, 0)
        params, trials = tune_model("ridge", X[outer.train], labels[outer.train], points[outer.train], inner)
        self.assertIn(params, CANDIDATES["ridge"])
        self.assertEqual(len(trials), 2)
        self.assertTrue(all(len(trial["inner_cluster_auc"]) == 3 for trial in trials))

    def test_feature_join_and_fixed_distance_transforms(self):
        import pandas as pd
        from src.models.benchmark import FEATURES, F1

        layer = pd.DataFrame({"grid_id": [2, 1]})
        for name in FEATURES["F2"][len(F1):]:
            layer[name] = [1., 2.]
        features = pd.DataFrame({"grid_id": [1, 2], "rel_elev_m": [1, 2], "slope_deg": [1, 2],
                                 "twi": [1, 2], "impervious_frac": [0, 1], "river_dist_m": [150, 600],
                                 "culvert_dist_m": [np.nan, 0], "pump_dist_m": [1000, 1001],
                                 "flood_l210_100_depth_m": [0, 2]})
        out = feature_frame(layer, features)
        np.testing.assert_allclose(out.river_proximity, [0, 0.5])
        np.testing.assert_allclose(out.culvert_proximity, [1, 0])
        np.testing.assert_allclose(out.pump_within_km, [0, 1])
        with self.assertRaises(ValueError):
            feature_frame(layer, features.iloc[:1])

    def test_top20_ties_are_not_grid_order_dependent(self):
        labels = np.array([1, 1, 0, 0, 0], dtype=bool)
        points = np.column_stack([np.arange(5) * 1000., np.zeros(5)])
        result = score_metrics(labels, np.zeros(5), points)
        self.assertAlmostEqual(result["grid_auc"], 0.5)
        self.assertAlmostEqual(result["top20_capture"], 0.2)


if __name__ == "__main__":
    unittest.main()
