"""결과 확인 EDA 의 판정 함수 검증 (src/stages/h08_review.py)."""

import unittest

import pandas as pd

from src.stages import h08_review as R

CONTRIBUTION_COLUMNS = ["h_contribution", "e_contribution", "v_contribution", "d_contribution"]


def contributions(rows: list[list[float]]) -> pd.DataFrame:
    """기여도 4성분만 담은 최소 표를 만든다."""
    return pd.DataFrame(rows, columns=CONTRIBUTION_COLUMNS)


def top20(neighborhoods: list[str]) -> pd.DataFrame:
    """행정동만 다른 TOP 20 표를 만든다. 구는 판정에 쓰이지 않으므로 하나로 둔다."""
    return pd.DataFrame({"neighborhood": neighborhoods,
                         "district": ["의창구"] * len(neighborhoods)})


class ContributionTest(unittest.TestCase):
    """기여도 4성분의 합은 1 이어야 한다 — 어긋나면 산식이나 저장이 깨진 것이다."""

    def test_sum_one_passes(self):
        result = R._check_contributions(contributions([[0.25, 0.25, 0.25, 0.25],
                                                       [0.40, 0.30, 0.20, 0.10]]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["n_off_by_more_than_tolerance"], 0)

    def test_sum_off_is_caught(self):
        result = R._check_contributions(contributions([[0.25, 0.25, 0.25, 0.25],
                                                       [0.40, 0.30, 0.20, 0.50]]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["n_off_by_more_than_tolerance"], 1)

    def test_tiny_rounding_is_tolerated(self):
        """부동소수 반올림 수준의 오차로 실패하면 안 된다."""
        result = R._check_contributions(contributions([[0.25, 0.25, 0.25, 0.2500001]]))
        self.assertTrue(result["ok"])


class DongConcentrationTest(unittest.TestCase):
    """TOP 20 이 한 행정동에 몰리면 지수가 위험이 아니라 그 동의 특성을 따라간 신호다."""

    def test_spread_passes(self):
        result = R._check_dong_concentration(top20([f"동{i}" for i in range(20)]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["n_dong"], 20)
        self.assertEqual(result["max_share"], 0.05)

    def test_over_half_in_one_dong_fails(self):
        result = R._check_dong_concentration(top20(["양덕동"] * 11 + [f"동{i}" for i in range(9)]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["top_dong"], "양덕동")
        self.assertEqual(result["top_dong_n"], 11)

    def test_exactly_half_still_passes(self):
        """기준은 '초과'다. 정확히 절반이면 통과시킨다."""
        result = R._check_dong_concentration(top20(["양덕동"] * 10 + [f"동{i}" for i in range(10)]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["max_share"], 0.5)


class FloodRiskStatusTest(unittest.TestCase):
    def test_missing_directory_is_reported_not_raised(self):
        """A7 미확보는 오류가 아니라 기록 대상이다."""
        status = R._flood_risk_status()
        self.assertIn("available", status)
        self.assertIn("note", status)


if __name__ == "__main__":
    unittest.main()
