from __future__ import annotations

import unittest

import pandas as pd

from src.data import sgis


class AgeCodebookTest(unittest.TestCase):
    def test_age_columns_bands(self) -> None:
        self.assertEqual(sgis.age_columns(sgis.AGE_BLOCK_TOTAL)[:3], ["in_age_001", "in_age_002", "in_age_003"])
        self.assertEqual(sgis.age_columns(sgis.AGE_BLOCK_TOTAL, min_age=65)[0], "in_age_014")
        self.assertEqual(sgis.age_columns(sgis.AGE_BLOCK_TOTAL, max_age=14), ["in_age_001", "in_age_002", "in_age_003"])
        self.assertEqual(sgis.age_columns(sgis.AGE_BLOCK_MALE, min_age=65)[0], "in_age_044")

    def _long(self, values: dict[str, float]) -> pd.DataFrame:
        return pd.DataFrame([
            {"year": 2024, "spatial_id": "A", "variable": k, "value": v} for k, v in values.items()
        ])

    def test_elderly_ratio_uses_age_sum_as_denominator(self) -> None:
        # 0~4 세 30명, 65~69 세 10명, 70~74 세 10명 → 65+ 20 / 연령합 50
        frame = self._long({"in_age_001": 30, "in_age_014": 10, "in_age_015": 10, "to_in_001": 100})
        out = sgis.elderly_ratio(frame, 2024)
        self.assertEqual(float(out.loc[0, "pop_elderly"]), 20.0)
        self.assertEqual(float(out.loc[0, "pop_age_total"]), 50.0)
        self.assertAlmostEqual(float(out.loc[0, "elderly_ratio"]), 0.4)

    def test_zero_population_gives_na(self) -> None:
        out = sgis.elderly_ratio(self._long({"in_age_001": 0, "in_age_014": 0, "to_in_001": 0}), 2024)
        self.assertTrue(pd.isna(out.loc[0, "elderly_ratio"]))

    def test_missing_age_columns_raises(self) -> None:
        """연령 계급이 하나도 없으면 코드북이 틀린 것이다. 조용히 0을 만들지 않는다."""
        with self.assertRaises(ValueError):
            sgis.elderly_ratio(self._long({"to_in_001": 100}), 2024)


if __name__ == "__main__":
    unittest.main()
