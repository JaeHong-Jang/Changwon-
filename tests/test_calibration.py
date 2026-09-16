"""등급 경계 캘리브레이션 단위 검증 (src/data/calibration.py)."""

import unittest

import numpy as np

from src.data import calibration as C


class IsotonicTest(unittest.TestCase):
    """PAV 등온회귀가 단조 제약을 지키면서 자료에 최대한 붙는지 본다."""

    def test_already_monotone_is_unchanged(self):
        """이미 단조면 원자료를 그대로 돌려준다 — 평활이 아니라 제약 적합이다."""
        scores = np.array([1.0, 2.0, 3.0, 4.0])
        labels = np.array([0.0, 0.0, 1.0, 1.0])
        _, fitted = C.isotonic_incidence(scores, labels)
        np.testing.assert_allclose(fitted, labels)

    def test_violation_is_pooled_to_block_mean(self):
        """뒤집힌 구간은 블록 평균으로 묶인다. [0,1,0,1] → 가운데 둘이 0.5 로."""
        scores = np.array([1.0, 2.0, 3.0, 4.0])
        labels = np.array([0.0, 1.0, 0.0, 1.0])
        _, fitted = C.isotonic_incidence(scores, labels)
        np.testing.assert_allclose(fitted, [0.0, 0.5, 0.5, 1.0])

    def test_all_reversed_collapses_to_overall_mean(self):
        """완전히 역순이면 단조 해는 전체 평균 하나뿐이다."""
        scores = np.arange(4.0)
        labels = np.array([1.0, 1.0, 0.0, 0.0])
        _, fitted = C.isotonic_incidence(scores, labels)
        np.testing.assert_allclose(fitted, [0.5] * 4)

    def test_output_is_non_decreasing(self):
        """무작위 자료에서도 결과는 항상 비감소여야 한다."""
        rng = np.random.default_rng(0)
        scores = rng.random(500)
        labels = (rng.random(500) < 0.3).astype(float)
        _, fitted = C.isotonic_incidence(scores, labels)
        self.assertTrue(np.all(np.diff(fitted) >= -1e-12))

    def test_sorted_by_score_not_input_order(self):
        """입력 순서와 무관하게 점수 오름차순으로 정렬해 적합한다."""
        scores = np.array([3.0, 1.0, 2.0])
        labels = np.array([1.0, 0.0, 1.0])
        x, fitted = C.isotonic_incidence(scores, labels)
        np.testing.assert_allclose(x, [1.0, 2.0, 3.0])
        np.testing.assert_allclose(fitted, [0.0, 1.0, 1.0])


class TrendTest(unittest.TestCase):
    """Cochran-Armitage 추세검정."""

    def test_flat_incidence_gives_no_trend(self):
        """등급마다 발생률이 같으면 z 는 0 근처여야 한다."""
        grades = np.repeat(np.arange(1, 6), 200)
        labels = np.tile(np.array([1.0] * 20 + [0.0] * 180), 5)
        result = C.cochran_armitage(grades, labels)
        self.assertLess(abs(result["z"]), 1.0)
        self.assertGreater(result["p_value"], 0.05)

    def test_rising_incidence_is_detected(self):
        """등급이 오를수록 발생률이 오르면 z 가 크고 p 가 작아야 한다."""
        grades = np.repeat(np.arange(1, 6), 200)
        labels = np.concatenate([
            np.array([1.0] * k + [0.0] * (200 - k)) for k in (2, 10, 30, 70, 140)
        ])
        result = C.cochran_armitage(grades, labels)
        self.assertGreater(result["z"], 5.0)
        self.assertLess(result["p_value"], 0.01)

    def test_no_positives_is_not_an_error(self):
        """양성이 하나도 없으면 분산이 0이라 판정 불가로 돌려준다."""
        grades = np.repeat(np.arange(1, 6), 10)
        result = C.cochran_armitage(grades, np.zeros(50))
        self.assertEqual(result["p_value"], 1.0)


class BreaksTest(unittest.TestCase):
    """경계 탐색 절차."""

    def setUp(self):
        rng = np.random.default_rng(7)
        self.scores = rng.random(5000)
        # 점수가 높을수록 잘 잠기도록 만든다 (단조 관계를 심어 둔다).
        self.labels = (rng.random(5000) < self.scores**3).astype(float)

    def test_breaks_are_ascending_and_produce_five_grades(self):
        result = C.calibration_breaks(self.scores, self.labels)
        self.assertEqual(len(result["breaks"]), 4)
        self.assertTrue(all(a < b for a, b in zip(result["breaks"], result["breaks"][1:])))
        self.assertEqual(len(result["grade_sizes"]), 5)
        self.assertEqual(sum(result["grade_sizes"]), len(self.scores))

    def test_incidence_rises_with_grade(self):
        """단조 관계를 심어 둔 자료이므로 등급별 발생률이 올라야 한다."""
        result = C.calibration_breaks(self.scores, self.labels)
        rates = result["incidence_by_grade"]
        self.assertTrue(all(rates[i] <= rates[i + 1] for i in range(4)), rates)

    def test_moves_stay_within_tolerance(self):
        """경계 이동은 허용 범위(±tolerance)를 넘지 않아야 한다."""
        tolerance = 0.03
        result = C.calibration_breaks(self.scores, self.labels, tolerance=tolerance)
        for move in result["moves"]:
            self.assertLessEqual(abs(move["shift_pp"]), tolerance * 100 + 1e-6, move)

    def test_flat_labels_trigger_merge_recommendation(self):
        """등급 간 차이가 없으면 통합을 권고해야 한다 — 억지 경계를 만들지 않는다."""
        rng = np.random.default_rng(1)
        scores = rng.random(2000)
        labels = (rng.random(2000) < 0.1).astype(float)   # 점수와 무관
        result = C.calibration_breaks(scores, labels, min_ratio=1.3)
        self.assertTrue(result["merge_recommended"])


class IncidenceTableTest(unittest.TestCase):
    def test_lift_and_monotone_flag(self):
        grades = np.repeat(np.arange(1, 6), 100)
        labels = np.concatenate([
            np.array([1.0] * k + [0.0] * (100 - k)) for k in (1, 5, 10, 20, 40)
        ])
        table = C.incidence_table(grades, labels)
        self.assertTrue(table["monotone"])
        self.assertEqual(table["rows"][4]["positives"], 40)
        self.assertAlmostEqual(table["base_rate"], 0.152, places=3)
        self.assertGreater(table["rows"][4]["lift"], table["rows"][0]["lift"])
        self.assertEqual(table["top_over_bottom"], 40.0)

    def test_non_monotone_is_reported(self):
        grades = np.repeat(np.arange(1, 6), 100)
        labels = np.concatenate([
            np.array([1.0] * k + [0.0] * (100 - k)) for k in (1, 50, 10, 20, 40)
        ])
        self.assertFalse(C.incidence_table(grades, labels)["monotone"])


class SensitivityTest(unittest.TestCase):
    def test_grid_covers_all_parameter_pairs(self):
        rng = np.random.default_rng(3)
        scores = rng.random(1000)
        labels = (rng.random(1000) < scores**2).astype(float)
        rows = C.sensitivity(scores, labels)
        self.assertEqual(len(rows), len(C.TOLERANCE_GRID) * len(C.MIN_RATIO_GRID))
        self.assertTrue(all(len(r["breaks"]) == 4 for r in rows))


class LeaveOneEventOutTest(unittest.TestCase):
    """사상 단위 교차검증 — 모든 사상이 한 번씩 검증에 쓰이고 분모가 폴드 수만큼 쌓여야 한다."""

    def setUp(self):
        rng = np.random.default_rng(11)
        self.n = 3000
        self.scores = rng.random(self.n)
        self.x = np.arange(self.n) * 1000.0          # 서로 멀리 떨어뜨려 격자마다 한 덩어리
        self.y = np.zeros(self.n)
        self.events = {
            str(year): (rng.random(self.n) < self.scores**4 * 0.3).astype(np.int8)
            for year in (2001, 2002, 2003, 2004)
        }

    def test_every_event_is_held_out_once(self):
        out = C.leave_one_event_out(self.scores, self.events, self.x, self.y, n_boot=100)
        self.assertEqual([f["held_out"] for f in out["folds"]], sorted(self.events))
        self.assertEqual(sum(r["n"] for r in out["rows"]), self.n * len(self.events))

    def test_positives_are_pooled_from_held_out_events(self):
        out = C.leave_one_event_out(self.scores, self.events, self.x, self.y, n_boot=100)
        total = sum(int(v.sum()) for v in self.events.values())
        self.assertEqual(sum(r["positives"] for r in out["rows"]), total)
        self.assertEqual(out["n_cluster"], total)   # 격자가 모두 떨어져 있으니 양성 1칸 = 1덩어리

    def test_strong_signal_shows_upward_trend(self):
        out = C.leave_one_event_out(self.scores, self.events, self.x, self.y, n_boot=300)
        self.assertGreater(out["bootstrap"]["trend_slope"], 0)
        self.assertLess(out["bootstrap"]["p_slope_nonpositive"], 0.01)
        self.assertEqual(len(out["break_range"]), 4)


if __name__ == "__main__":
    unittest.main()
