"""M1 기준선·층·판정 단위 검사 (합성 자료, 홀드아웃 없음)."""

import unittest

import numpy as np
import pandas as pd

from src.models import m1_decision as D
from src.models.m1_scores import baseline_scores, prior_years
from src.models.m1_strata import strata


def long_rows(values: dict[str, list[float]], n_units: int = 10, unit: str = "cell_gate", stratum: str = "ALL",
              role: str = "development") -> pd.DataFrame:
    """점수별 사상 AUC 목록을 evaluate 긴 표 모양으로 만든다."""
    # 사상 이름은 e0, e1 … 로 둔다
    rows = [{"score": s, "unit": unit, "stratum": stratum, "storm": "ALL", "metric": "observed-label_auc",
             "value": v, "n_units": n_units, "test_event": f"e{i}", "role": role}
            for s, vals in values.items() for i, v in enumerate(vals)]
    return pd.DataFrame(rows)


class M1Test(unittest.TestCase):
    """기준선 부호, 층 임계, 판정 규칙을 확인한다."""

    def test_baseline_signs(self):
        """경사·상대고도·HAND 는 뒤집고 TWI·불투수는 그대로다."""
        # 두 격자 특징표로 부호를 본다
        f = pd.DataFrame({"slope_deg": [1.0, 10.0], "rel_elev_m": [-2.0, 3.0], "twi": [8.0, 4.0],
                          "impervious_frac": [0.9, 0.1]})
        s = baseline_scores(f, np.array([0.0, 20.0]), np.array([1.0, 5.0]))
        for name in ("slope_neg", "relelev_neg", "twi", "impervious", "hand_neg", "hand_acc_neg"):
            self.assertGreater(s[name][0], s[name][1], name)

    def test_prior_years_excludes_2025(self):
        """2025 와 시험 연도 이후 사상은 학습에서 빠진다."""
        # 개발 첫 사상·중간·홀드아웃 연도를 본다
        self.assertEqual(prior_years(2006), [])
        self.assertEqual(prior_years(2016), [2006, 2012, 2014])
        self.assertEqual(prior_years(2025), [2006, 2012, 2014, 2016, 2019])
        self.assertEqual(prior_years(2024), [2006, 2012, 2014, 2016, 2019])

    def test_strata_thresholds(self):
        """경사 5° 이하·불투수 0.5 이상·농경 대리·거주 격자를 정의대로 고른다."""
        # 경계값을 포함한 네 격자로 층을 만든다
        f = pd.DataFrame({"slope_deg": [5.0, 5.1, 1.0, 1.0], "impervious_frac": [0.5, 0.0, 0.05, 0.05],
                          "inland_water_frac": [0.0, 0.0, 0.6, np.nan], "universe": [1, 0, np.nan, 1]})
        m = strata(f)
        np.testing.assert_array_equal(m["FLAT"], [True, False, True, True])
        np.testing.assert_array_equal(m["URBAN"], [True, False, False, False])
        np.testing.assert_array_equal(m["AGRI"], [False, False, False, True])
        np.testing.assert_array_equal(m["UNIVERSE"], [True, False, False, True])

    def test_decision_within_margin_discards(self):
        """경사 중앙값이 RF 중앙값 − 0.02 이상이면 폐기한다 (경계 포함)."""
        # 중앙값 차이가 정확히 0.02 인 경우와 0.03 인 경우
        close = long_rows({"slope_neg": [0.60, 0.70, 0.80], "rf_F1_wf": [0.62, 0.72, 0.82]})
        far = long_rows({"slope_neg": [0.60, 0.70, 0.80], "rf_F1_wf": [0.63, 0.73, 0.83]})
        self.assertEqual(D.decide(close)["verdict"], "C-b 폐기")
        self.assertNotEqual(D.decide(far)["verdict"], "C-b 폐기")
        self.assertEqual(D.decide(far)["primary"]["median_gap"], 0.03)

    def test_decision_slope_better_discards(self):
        """경사가 RF 보다 높아도 폐기다."""
        # 경사가 모든 사상에서 앞선다
        rows = long_rows({"slope_neg": [0.9, 0.9], "rf_F1_wf": [0.6, 0.6]})
        self.assertEqual(D.decide(rows)["verdict"], "C-b 폐기")

    def test_min_units_and_missing_model(self):
        """양성 5칸 미만 사상과 RF 가 없는 사상은 중앙값에서 빠진다."""
        # e0 은 RF 결측, 표본 부족 표는 판정 불가
        rows = long_rows({"slope_neg": [0.5, 0.6, 0.7], "rf_F1_wf": [np.nan, 0.9, 0.9]})
        self.assertEqual(D.compare(rows, "slope_neg", "rf_F1_wf")["events"], ["e1", "e2"])
        few = long_rows({"slope_neg": [0.5], "rf_F1_wf": [0.9]}, n_units=4)
        self.assertEqual(D.decide(few)["verdict"], "판정 불가")

    def test_median_table_counts_gate(self):
        """중앙값 표는 사전 게이트 통과 사상 수를 센다."""
        # 두 사상 중 하나만 0.70 이상
        rows = long_rows({"slope_neg": [0.65, 0.75]})
        t = D.median_table(rows)
        r = t[(t["score"] == "slope_neg") & (t["role_group"] == "all")].iloc[0]
        self.assertEqual((r["n_events"], r["n_pass_gate"], r["median"]), (2, 1, 0.70))


if __name__ == "__main__":
    unittest.main()
