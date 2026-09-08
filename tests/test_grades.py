from __future__ import annotations

import unittest

import numpy as np

from src.data import grades as G


class SchemeChoiceTest(unittest.TestCase):
    def test_calibration_needs_labels_and_time_split(self) -> None:
        self.assertEqual(G.choose_scheme(150, True)[0], "calibration")
        self.assertEqual(G.choose_scheme(150, False)[0], "jenks")   # 시간 분할 불가
        self.assertEqual(G.choose_scheme(99, True)[0], "jenks")     # 양성 격자 부족
        self.assertEqual(G.choose_scheme(0, False)[0], "jenks")

    def test_reason_names_the_blocker(self) -> None:
        self.assertIn("0개", G.choose_scheme(0, False)[1])
        self.assertIn("시간 분할", G.choose_scheme(150, False)[1])


class GradingTest(unittest.TestCase):
    def test_direction_is_ascending(self) -> None:
        """5 가 가장 위험해야 한다. 국토부 지침 I~IV 와 방향이 반대다."""
        values = np.linspace(0, 1, 1000)
        jenks, _ = G.jenks_grades(values)
        self.assertEqual(jenks[0], 1)
        self.assertEqual(jenks[-1], 5)
        self.assertTrue(np.all(np.diff(jenks) >= 0))

    def test_percentile_grades_hit_target_share(self) -> None:
        values = np.random.default_rng(0).gamma(2.0, 1.0, size=10_000)
        g = G.percentile_grades(values)
        for grade, target in G.TARGET_SHARE.items():
            self.assertAlmostEqual((g == grade).mean(), target, delta=0.01)

    def test_balica_uses_fixed_breaks(self) -> None:
        g = G.balica_grades(np.array([0.005, 0.1, 0.4, 0.6, 0.9]))
        self.assertEqual(g.tolist(), [1, 2, 3, 4, 5])

    def test_all_schemes_cover_five_grades(self) -> None:
        values = np.linspace(0, 1, 5000)
        for g in (G.jenks_grades(values)[0], G.percentile_grades(values), G.balica_grades(values)):
            self.assertEqual(sorted(set(g.tolist())), [1, 2, 3, 4, 5])


class RuleTest(unittest.TestCase):
    def _flat(self, n: int, value: float) -> np.ndarray:
        return np.full(n, value)

    def test_rule_a_lifts_one_step_and_floors_at_r3(self) -> None:
        raw = np.array([1, 2, 4])
        final, _, m = G.apply_rules(
            raw, l1_percentile=self._flat(3, 0.995),
            v_percentile=self._flat(3, 0.0), h_percentile=self._flat(3, 0.0),
        )
        # R1 → +1 = R2 이지만 하한 R3 까지 끌어올린다. R4 → R5
        self.assertEqual(final.tolist(), [3, 3, 5])
        self.assertEqual(m["rule_a_matched"], 3)

    def test_rule_b_needs_both_conditions(self) -> None:
        raw = np.array([2, 2, 2])
        final, _, m = G.apply_rules(
            raw,
            l1_percentile=self._flat(3, 0.0),
            v_percentile=np.array([0.95, 0.95, 0.50]),   # 상위 10% / 상위 10% / 아님
            h_percentile=np.array([0.80, 0.50, 0.80]),   # 상위 30% / 아님    / 상위 30%
        )
        self.assertEqual(final.tolist(), [3, 2, 2])
        self.assertEqual(m["rule_b_matched"], 1)

    def test_uplift_is_capped_at_two_steps(self) -> None:
        raw = np.array([1])
        final, _, m = G.apply_rules(
            raw, l1_percentile=self._flat(1, 1.0),
            v_percentile=self._flat(1, 1.0), h_percentile=self._flat(1, 1.0),
        )
        self.assertEqual(int(final[0]), 3)          # 1 + 2 = 3, 하한 R3 과도 일치
        self.assertEqual(m["rule_a_and_b"], 1)

    def test_grade_never_exceeds_five(self) -> None:
        final, _, _ = G.apply_rules(
            np.array([5]), l1_percentile=self._flat(1, 1.0),
            v_percentile=self._flat(1, 1.0), h_percentile=self._flat(1, 1.0),
        )
        self.assertEqual(int(final[0]), 5)

    def test_rule_c_flags_but_does_not_change_grade(self) -> None:
        raw = np.array([1, 2, 4])
        final, review, m = G.apply_rules(
            raw, l1_percentile=self._flat(3, 0.0),
            v_percentile=self._flat(3, 0.0), h_percentile=self._flat(3, 0.0),
            designated_near=np.array([True, True, True]),
        )
        self.assertEqual(final.tolist(), raw.tolist())      # 등급 불변
        self.assertEqual(review.tolist(), [1, 1, 0])        # R1·R2 만 재검토
        self.assertTrue(m["rule_c_available"])

    def test_overuse_is_detected(self) -> None:
        n = 100
        _, _, m = G.apply_rules(
            np.full(n, 2), l1_percentile=self._flat(n, 1.0),
            v_percentile=self._flat(n, 0.0), h_percentile=self._flat(n, 0.0),
        )
        self.assertTrue(m["overused"])          # 100% 변경
        _, _, m2 = G.apply_rules(
            np.full(n, 2),
            l1_percentile=np.where(np.arange(n) < 2, 1.0, 0.0),
            v_percentile=self._flat(n, 0.0), h_percentile=self._flat(n, 0.0),
        )
        self.assertFalse(m2["overused"])         # 2% 변경


class KappaTest(unittest.TestCase):
    def test_identical_is_one(self) -> None:
        g = np.array([1, 2, 3, 4, 5, 5, 3])
        self.assertAlmostEqual(G.weighted_kappa(g, g), 1.0)

    def test_near_agreement_beats_far_disagreement(self) -> None:
        a = np.array([1, 2, 3, 4, 5] * 20)
        near = np.clip(a + 1, 1, 5)
        far = 6 - a
        self.assertGreater(G.weighted_kappa(a, near), G.weighted_kappa(a, far))


class SummaryTest(unittest.TestCase):
    def test_summary_reports_share_and_target_gap(self) -> None:
        out = G.grade_summary(np.array([5] * 10 + [1] * 90))
        self.assertEqual(out["R5"]["n"], 10)
        self.assertAlmostEqual(out["R5"]["share"], 0.10)
        self.assertAlmostEqual(out["R5"]["diff"], 0.08)
        self.assertEqual(out["R5"]["name"], "R5 최우선 대응")


if __name__ == "__main__":
    unittest.main()
