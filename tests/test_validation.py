"""관측라벨 검증 프로토콜의 합성·실자료 회귀 테스트."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from src.data import layers as L, validation as V


class ArrayMetricTest(unittest.TestCase):
    def test_cell_auc_extremes_and_random(self) -> None:
        labels = np.r_[np.ones(30, bool), np.zeros(70, bool)]
        x = np.arange(100, dtype=float) * 200
        y = np.zeros(100)
        perfect = np.r_[np.ones(30), np.zeros(70)]
        self.assertEqual(V.cell_auc(labels, perfect, x, y, n_boot=20)["observed-label_auc_cell"], 1)
        self.assertEqual(V.cell_auc(labels, -perfect, x, y, n_boot=20)["observed-label_auc_cell"], 0)
        random = np.random.default_rng(42).random(100)
        self.assertLess(abs(V.cell_auc(labels, random, x, y, n_boot=20)["observed-label_auc_cell"] - 0.5), 0.15)

    def test_capture_and_ap(self) -> None:
        score = np.arange(10, dtype=float)
        weight = np.r_[np.zeros(8), np.ones(2)]
        curve = V.capture_curve(score, weight, fractions=(0.2,))
        self.assertAlmostEqual(curve.iloc[0]["capture"], 1)
        self.assertAlmostEqual(V.average_precision_observed(weight > 0, score), 1)

    def test_boyce_increases_and_constant_is_undefined(self) -> None:
        bg = np.linspace(0, 1, 1001)
        pos = np.linspace(0.5, 1, 100)
        self.assertGreater(V.continuous_boyce(pos, np.ones(100), bg)["boyce"], 0)
        self.assertTrue(np.isnan(V.continuous_boyce(np.ones(4), np.ones(4), np.ones(10))["boyce"]))

    def test_boyce_expected_area_weights(self) -> None:
        bg = np.array([0.0, 0.5, 1.0])
        area = np.array([1, 2, 3])
        weighted = V.continuous_boyce(np.array([0.5, 1.0]), np.ones(2), bg, bg_weights=area)
        repeated = V.continuous_boyce(np.array([0.5, 1.0]), np.ones(2), np.repeat(bg, area))
        np.testing.assert_allclose(weighted["curve"].pe, repeated["curve"].pe)

    def test_paired_object_and_storm_difference(self) -> None:
        base = np.array([0.2, 0.3, 0.4, 0.5])
        better = base + 0.2
        storms = np.array(["a", "a", "b", "b"])
        for scheme in ("object", "storm"):
            out = V.paired_bootstrap({"base": base, "better": better}, storms,
                                     reference="base", resample=scheme, n_boot=100)
            diff = out[(out.score == "better") & (out.metric == "observed-label_auc_diff")].iloc[0]
            self.assertGreater(diff.value, 0)
            self.assertGreater(diff.ci_lo, 0)


class GeometryMetricTest(unittest.TestCase):
    @staticmethod
    def fixture():
        import geopandas as gpd
        from shapely.geometry import box

        grid = gpd.GeoDataFrame(geometry=[box(i, 0, i + 1, 1) for i in range(12)], crs="EPSG:5179")
        traces = gpd.GeoDataFrame({"storm_id": ["a", "b"], "object_id": [1, 1]},
                                  geometry=[box(0, 0, 10, 1), box(11, 0, 12, 1)], crs=grid.crs)
        return grid, traces

    def test_object_one_vote_and_area_weight(self) -> None:
        grid, traces = self.fixture()
        score = np.r_[np.ones(10), 0, -1.0]
        out = V.object_auc(score, grid, traces)
        self.assertAlmostEqual(out["observed-label_auc_object"], 0.5)
        self.assertAlmostEqual(V.area_weighted_auc(score, grid, traces), 10 / 11)
        self.assertEqual(out["per_object"].tolist(), [1.0, 0.0])

    def test_evaluate_tidy_storm_and_macro(self) -> None:
        grid, traces = self.fixture()
        score = np.r_[np.ones(10), 0, -1.0]
        out = V.evaluate({"base": score, "reverse": -np.abs(score)}, grid, traces,
                         reference="base", n_boot=20)
        self.assertEqual(list(out.columns), V.COLUMNS)
        self.assertTrue({"ALL", "a", "b", "MACRO"}.issubset(set(out.storm)))
        row = out[(out.score == "base") & (out.unit == "object") &
                  (out.storm == "ALL") & (out.metric == "observed-label_auc")].iloc[0]
        self.assertAlmostEqual(row.value, 0.5)
        diff = out[(out.score == "reverse") & (out.unit == "object") &
                   (out.storm == "ALL") & (out.metric == "observed-label_auc_diff")].iloc[0]
        self.assertLess(diff.value, 0)
        cell_diff = out[(out.score == "reverse") & (out.unit == "cell_gate") &
                        (out.storm == "ALL") & (out.metric == "observed-label_auc_diff")].iloc[0]
        self.assertLess(cell_diff.value, 0)

    def test_overlap_label_uses_polygon_union(self) -> None:
        import geopandas as gpd
        from shapely.geometry import box

        grid = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)], crs="EPSG:5179")
        traces = gpd.GeoDataFrame({"storm_id": ["a", "a"], "object_id": [1, 2]},
                                  geometry=[box(0, 0, 0.6, 10), box(0, 0, 0.6, 10)], crs=grid.crs)
        out = V.evaluate({"s": np.array([1.0, 0.0])}, grid, traces, n_boot=10)
        row = out[(out.unit == "cell_gate") & (out.storm == "ALL") &
                  (out.metric == "observed-label_auc")].iloc[0]
        self.assertTrue(np.isnan(row.value))

    @staticmethod
    def review_grid(n):
        import geopandas as gpd
        from shapely.geometry import box

        return gpd.GeoDataFrame(geometry=[box(i * 200, 0, i * 200 + 100, 100)
                                          for i in range(n)], crs=5179)

    @staticmethod
    def review_traces(geometries, storms):
        import geopandas as gpd

        return gpd.GeoDataFrame({"object_id": range(len(geometries)), "storm_id": storms},
                                geometry=geometries, crs=5179)

    @staticmethod
    def review_value(out, unit, storm="ALL", metric="observed-label_auc"):
        return out[(out.unit == unit) & (out.storm == storm) & (out.metric == metric)].value.iloc[0]

    def test_review_r1_gate_and_background(self) -> None:
        from shapely.geometry import box

        grid = self.review_grid(3)
        score = np.array([0.5, 1.0, 0.0])
        traces = self.review_traces([box(0, 0, 100, 100), box(200, 0, 205, 100)], ["a", "a"])
        out = V.evaluate({"s": score}, grid, traces, n_boot=20)
        self.assertEqual(L.roc_auc([1, 0, 0], score), 0.5)
        self.assertEqual(self.review_value(out, "cell_gate"), 0.5)
        self.assertEqual(self.review_value(out, "cell_bg"), 1.0)
        self.assertTrue(np.isfinite(self.review_value(out, "cluster_gate")))
        self.assertEqual(self.review_value(out, "cell_gate", metric="capture_0.2"), 0.0)

    def test_cell_gate_capture_uses_whole_cells(self) -> None:
        grid = self.review_grid(3)
        score = np.array([1.0, 0.5, 0.0])
        traces = self.review_traces([grid.geometry.iloc[0]], ["a"])
        out = V.evaluate({"s": score}, grid, traces, n_boot=20)
        self.assertEqual(self.review_value(out, "cell_gate", metric="capture_0.2"), 1.0)
        self.assertEqual(self.review_value(out, "area", metric="capture_0.2"), 0.6)
        self.assertEqual(self.review_value(out, "cell_gate", metric="capture_0.2"),
                         L.top_share_lift(np.array([1, 0, 0]), score, 0.2)["capture_rate"])

    def test_review_r2_macro_matches_storm_rows(self) -> None:
        grid = self.review_grid(3)
        score = np.array([1.0, 0.5, 0.0])
        traces = self.review_traces(list(grid.geometry.iloc[:2]), ["a", "b"])
        out = V.evaluate({"s": score}, grid, traces, n_boot=20)
        for unit in ("cell_gate", "cell_bg", "cluster_gate", "cluster_bg",
                     "object", "representative", "area"):
            a = self.review_value(out, unit, "a")
            b = self.review_value(out, unit, "b")
            macro = self.review_value(out, unit, "MACRO")
            self.assertAlmostEqual(macro, (a + b) / 2, msg=unit)
        self.assertEqual(self.review_value(out, "object", "MACRO"), 0.75)
        macro = out[(out.unit == "object") & (out.storm == "MACRO") &
                    (out.metric == "observed-label_auc")].iloc[0]
        self.assertEqual((macro.ci_lo, macro.ci_hi, macro.n_units), (0.5, 1.0, 2))

    def test_review_r3_boyce_uses_whole_grid(self) -> None:
        grid = self.review_grid(10)
        score = np.arange(10) / 9
        traces = self.review_traces(list(grid.geometry.iloc[5:]), ["a"] * 5)
        out = V.evaluate({"s": score}, grid, traces, n_boot=20)
        boyce = self.review_value(out, "area", metric="boyce")
        self.assertGreater(boyce, 0)
        self.assertAlmostEqual(boyce, V.continuous_boyce(score[5:], np.ones(5), score)["boyce"])

    def test_review_r4_missing_area_and_excluded_fraction(self) -> None:
        from shapely.geometry import box

        grid = self.review_grid(4)
        score = np.array([1.0, np.nan, 0.0, 0.5])
        traces = self.review_traces([box(0, 0, 300, 100), grid.geometry.iloc[2]], ["a", "a"])
        out = V.evaluate({"s": score}, grid, traces, n_boot=20)
        self.assertEqual(V.area_weighted_auc(score, grid, traces), 0.5)
        self.assertEqual(self.review_value(out, "area"), 0.5)
        self.assertEqual(self.review_value(out, "cell_gate", metric="excluded_area_fraction"), 0.25)

    def test_review_r5_inputs_are_unchanged(self) -> None:
        grid = self.review_grid(3)
        traces = self.review_traces([grid.geometry.iloc[0]], ["a"])
        score = np.array([1.0, np.nan, 0.0])
        mask = np.array([False, True, True])
        stratum = np.array([True, True, True])
        score_before, mask_before, stratum_before = score.copy(), mask.copy(), stratum.copy()
        V.object_auc(score, grid, traces, background_mask=mask)
        V.evaluate({"s": score}, grid, traces, background_mask=mask,
                   strata={"subset": stratum}, n_boot=20)
        np.testing.assert_array_equal(mask, mask_before)
        np.testing.assert_array_equal(stratum, stratum_before)
        np.testing.assert_array_equal(score, score_before)


class ExistingDataTest(unittest.TestCase):
    def test_l1_cell_and_cluster_regression(self) -> None:
        path = Path("data/processed/layers/layer1_flood.gpkg")
        if not path.exists():
            self.skipTest("기존 L1 자료가 없다")
        import geopandas as gpd

        frame = gpd.read_file(path, layer="layer1_flood", columns=["L1", "trace_label"])
        centers = frame.geometry.centroid
        out = V.cell_auc(frame.trace_label.to_numpy().astype(bool), frame.L1.to_numpy(),
                         centers.x.to_numpy(), centers.y.to_numpy(), n_boot=20)
        self.assertEqual(round(out["observed-label_auc_cell"], 4), 0.7504)
        self.assertEqual(round(out["observed-label_auc_cluster"], 4), 0.7044)
        positive = frame.trace_label.to_numpy().astype(bool)
        traces = gpd.GeoDataFrame({"storm_id": ["original"] * int(positive.sum()),
                                   "object_id": np.arange(positive.sum())},
                                  geometry=frame.geometry[positive].reset_index(drop=True), crs=frame.crs)
        table = V.evaluate({"L1": frame.L1.to_numpy()}, frame, traces, n_boot=20)
        for unit, expected in (("cell_gate", 0.7504), ("cluster_gate", 0.7044)):
            value = table[(table.unit == unit) & (table.storm == "ALL") &
                          (table.metric == "observed-label_auc")].value.iloc[0]
            self.assertEqual(round(value, 4), expected)


if __name__ == "__main__":
    unittest.main()
