from __future__ import annotations

import itertools
import unittest

import numpy as np
import pandas as pd

from src.data import interpolate as I
from src.data import layers as L


def _brute_force_jenks(x: np.ndarray, k: int) -> float:
    """모든 분할을 다 해보고 최소 급간내 편차제곱합을 돌려준다 (작은 입력 전용)."""
    x = np.sort(x)
    n = len(x)
    best = np.inf
    for cuts in itertools.combinations(range(1, n), k - 1):
        bounds = (0, *cuts, n)
        total = 0.0
        for i in range(k):
            seg = x[bounds[i]:bounds[i + 1]]
            total += float(np.sum((seg - seg.mean()) ** 2))
        best = min(best, total)
    return best


def _within_class_ss(x: np.ndarray, breaks: list[float], k: int) -> float:
    cls = L.classify(x, breaks)
    return float(sum(np.sum((x[cls == c] - x[cls == c].mean()) ** 2) for c in range(1, k + 1) if (cls == c).any()))


class JenksTest(unittest.TestCase):
    def test_matches_brute_force_on_small_samples(self) -> None:
        rng = np.random.default_rng(42)
        for _ in range(8):
            x = np.round(rng.normal(size=14) * 10, 2)
            for k in (2, 3, 4):
                breaks = L.jenks_breaks(x, k)
                self.assertAlmostEqual(_within_class_ss(x, breaks, k), _brute_force_jenks(x, k), places=6)

    def test_separates_obvious_clusters(self) -> None:
        x = np.array([1.0, 1.1, 1.2, 10.0, 10.1, 20.0, 20.2, 30.0])
        breaks = L.jenks_breaks(x, 4)
        cls = L.classify(x, breaks)
        self.assertEqual(cls.tolist(), [1, 1, 1, 2, 2, 3, 3, 4])

    def test_breaks_are_sorted_and_end_at_max(self) -> None:
        x = np.random.default_rng(0).gamma(2.0, 3.0, size=500)
        breaks = L.jenks_breaks(x, 4)
        self.assertEqual(len(breaks), 4)
        self.assertEqual(breaks, sorted(breaks))
        self.assertAlmostEqual(breaks[-1], float(x.max()))

    def test_fewer_unique_values_than_classes(self) -> None:
        breaks = L.jenks_breaks(np.array([5.0, 5.0, 7.0]), 4)
        self.assertEqual(len(breaks), 4)
        self.assertEqual(L.classify(np.array([5.0, 7.0]), breaks).tolist(), [1, 2])

    def test_classify_covers_full_range(self) -> None:
        x = np.linspace(0, 100, 1000)
        cls = L.classify(x, L.jenks_breaks(x, 4))
        self.assertEqual(sorted(set(cls.tolist())), [1, 2, 3, 4])


class ScalingTest(unittest.TestCase):
    def test_winsorize_clips_outlier(self) -> None:
        x = np.array([*range(100), 10_000.0])
        self.assertLess(L.winsorize(x).max(), 200)

    def test_zscore_constant_is_zero(self) -> None:
        self.assertTrue(np.allclose(L.zscore(np.full(10, 3.0)), 0.0))

    def test_composite_sign_flips_direction(self) -> None:
        frame = pd.DataFrame({"low_is_bad": [1.0, 2.0, 3.0], "high_is_bad": [1.0, 2.0, 3.0]})
        total, detail = L.composite(frame, {"low_is_bad": -1, "high_is_bad": +1}, winsor_lo=0.0, winsor_hi=1.0)
        self.assertTrue(np.allclose(total, 0.0))  # 서로 상쇄
        self.assertEqual(detail["low_is_bad"]["sign"], -1)


class MatrixTest(unittest.TestCase):
    def test_both_high_is_grade_one(self) -> None:
        v = L.vulnerability_class(np.array([4, 4, 1, 1]), np.array([4, 3, 1, 4]))
        self.assertEqual(v.tolist(), [1, 1, 4, 3])


class MetricTest(unittest.TestCase):
    def test_auc_perfect_and_random(self) -> None:
        labels = np.array([0, 0, 1, 1])
        self.assertAlmostEqual(L.roc_auc(labels, np.array([0.1, 0.2, 0.8, 0.9])), 1.0)
        self.assertAlmostEqual(L.roc_auc(labels, np.array([0.9, 0.8, 0.2, 0.1])), 0.0)
        self.assertAlmostEqual(L.roc_auc(labels, np.array([0.5, 0.5, 0.5, 0.5])), 0.5)

    def test_auc_requires_both_classes(self) -> None:
        with self.assertRaises(ValueError):
            L.roc_auc(np.array([1, 1]), np.array([0.1, 0.2]))

    def test_lift_when_mask_is_in_top(self) -> None:
        scores = np.arange(100, dtype=float)
        mask = scores >= 90
        out = L.top_share_lift(mask, scores, 0.1)
        self.assertEqual(out["capture_rate"], 1.0)
        self.assertEqual(out["lift"], 10.0)


class IdwTest(unittest.TestCase):
    def setUp(self) -> None:
        self.xy = np.array([[0.0, 0.0], [1000.0, 0.0], [0.0, 1000.0], [1000.0, 1000.0]])
        self.values = np.array([10.0, 20.0, 30.0, 40.0])

    def test_exact_at_station_location(self) -> None:
        out, fallback = I.idw(self.xy, self.values, self.xy, power=2, k=4, max_dist=5000)
        self.assertTrue(np.allclose(out, self.values))
        self.assertFalse(fallback.any())

    def test_center_is_average(self) -> None:
        out, _ = I.idw(self.xy, self.values, np.array([[500.0, 500.0]]), power=2, k=4, max_dist=5000)
        self.assertAlmostEqual(float(out[0]), 25.0, places=6)

    def test_outside_radius_falls_back_to_nearest(self) -> None:
        out, fallback = I.idw(self.xy, self.values, np.array([[50_000.0, 0.0]]), power=2, k=4, max_dist=1000)
        self.assertTrue(bool(fallback[0]))
        self.assertEqual(float(out[0]), 20.0)  # 최근접은 (1000, 0) 의 20

    def test_choose_power_prefers_lower_rmse(self) -> None:
        rng = np.random.default_rng(1)
        xy = rng.uniform(0, 10_000, size=(12, 2))
        values = xy[:, 0] / 1000.0
        power, scores = I.choose_power(xy, values, powers=(1, 2, 3), k=6, max_dist=20_000)
        self.assertIn(power, (1.0, 2.0, 3.0))
        self.assertEqual(scores[str(power)], min(scores.values()))


class StationExposureTest(unittest.TestCase):
    def _rain(self) -> pd.DataFrame:
        """호우 6번을 30시간 간격으로 둔다 (24시간 창이 겹치지 않는 간격)."""
        times = pd.date_range("2020-01-01", periods=200, freq="h")
        mm = np.zeros(200)
        for hour, amount in zip(range(10, 200, 30), [40.0, 12.0, 20.0, 8.0, 29.0, 5.0]):
            mm[hour] = amount
        return pd.DataFrame({
            "station_id": 1,
            "obs_date": times.normalize(),
            "observed_at": times,
            "rainfall_mm": mm,
            "quality_flag": "ok",
        })

    def test_variables(self) -> None:
        out = I.station_exposure(self._rain(), pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"))
        row = out.iloc[0]
        expected_top5 = (40.0 + 29.0 + 20.0 + 12.0 + 8.0) / 5  # 5mm 짜리 여섯 번째는 빠진다
        self.assertEqual(row["rain_annual_max_1h"], 40.0)
        self.assertEqual(row["rain_hours_over_30mm"], 1.0)
        self.assertAlmostEqual(row["rain_top5_3h"], expected_top5, places=6)
        self.assertAlmostEqual(row["rain_top5_24h"], expected_top5, places=6)
        self.assertEqual(row["n_hours"], 200)

    def test_fewer_events_than_k_pads_with_dry_windows(self) -> None:
        """호우가 5번 미만이면 나머지는 무강수 창(0mm)이 뽑힌다 — 평균이 그만큼 내려간다."""
        times = pd.date_range("2020-01-01", periods=100, freq="h")
        mm = np.zeros(100)
        mm[10] = 40.0
        rain = pd.DataFrame({
            "station_id": 1, "obs_date": times.normalize(), "observed_at": times,
            "rainfall_mm": mm, "quality_flag": "ok",
        })
        out = I.station_exposure(rain, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"))
        self.assertAlmostEqual(out.iloc[0]["rain_top5_3h"], 40.0 / 5, places=6)

    def test_quality_filter_and_empty_range(self) -> None:
        bad = self._rain().assign(quality_flag="quarantined")
        with self.assertRaises(ValueError):
            I.station_exposure(bad, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"))


if __name__ == "__main__":
    unittest.main()
