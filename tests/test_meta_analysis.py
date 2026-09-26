"""무작위효과 통합 단위 검사 (BCG 백신 13연구 자료, 참조값은 statsmodels·PyMARE 교차 계산)."""

import unittest

import numpy as np

from src.data.validation import meta_analysis as MA

# metafor dat.bcg 의 (백신 양성, 백신 음성, 대조 양성, 대조 음성)
BCG = np.array([[4, 119, 11, 128], [6, 300, 29, 274], [3, 228, 11, 209], [62, 13536, 248, 12619],
                [33, 5036, 47, 5761], [180, 1361, 372, 1079], [8, 2537, 10, 619], [505, 87886, 499, 87892],
                [29, 7470, 45, 7232], [17, 1699, 65, 1600], [186, 50448, 141, 27197], [5, 2493, 3, 2338],
                [27, 16886, 29, 17825]], float)


def bcg() -> tuple[np.ndarray, np.ndarray]:
    """BCG 자료의 로그 위험비와 표준오차."""
    a, b, c, d = BCG.T
    y = np.log((a / (a + b)) / (c / (c + d)))
    v = 1 / a - 1 / (a + b) + 1 / c - 1 / (c + d)
    return y, np.sqrt(v)


class MetaAnalysisTest(unittest.TestCase):
    """REML·DL·HKSJ·Q·I²·Q-profile 를 참조값과 맞추고 경계 사례를 본다."""

    def test_reml_hksj_matches_reference(self):
        """REML τ²·평균·HKSJ 구간·Q·I²·Q-profile 이 참조값과 같다."""
        # PyMARE REML 0.313243, Q 152.2330, I² 92.117%, Q-profile [0.119718, 1.111479]
        y, se = bcg()
        r = MA.random_effects(y, se, method="REML", ci="hksj")
        self.assertAlmostEqual(r["tau2"], 0.313243, places=5)
        self.assertAlmostEqual(r["mu"], -0.714532, places=5)
        self.assertAlmostEqual(r["q"], 152.2330, places=3)
        self.assertAlmostEqual(r["i2"], 0.921173, places=5)
        self.assertAlmostEqual(r["tau2_lo"], 0.119718, places=5)
        self.assertAlmostEqual(r["tau2_hi"], 1.111479, places=5)
        self.assertAlmostEqual(r["ci_lo"], -1.1084, places=4)
        self.assertAlmostEqual(r["ci_hi"], -0.3206, places=4)

    def test_dl_wald_matches_statsmodels(self):
        """DL τ²·평균·SE 가 statsmodels combine_effects 와 같다."""
        # statsmodels: τ² 0.308760, 평균 −0.714117, SE 0.178742
        y, se = bcg()
        r = MA.random_effects(y, se, method="DL", ci="wald")
        self.assertAlmostEqual(r["tau2"], 0.308760, places=5)
        self.assertAlmostEqual(r["mu"], -0.714117, places=5)
        self.assertAlmostEqual(r["se"], 0.178742, places=5)
        self.assertAlmostEqual(r["ci_hi"] - r["mu"], MA.Z975 * r["se"], places=10)

    def test_i2_consistent_with_dl_tau2(self):
        """DL τ² 를 s² 로 옮긴 I² 가 Higgins–Thompson I² 와 같다."""
        # 두 정의가 DL 에서 같은 값이 되는지 본다
        y, se = bcg()
        self.assertAlmostEqual(MA.i2_from_tau2(MA.tau2_dl(y, se ** 2), se ** 2),
                               MA.random_effects(y, se)["i2"], places=10)

    def test_modified_hksj_not_narrower(self):
        """사상 간 흩어짐이 작으면(q < 1) 수정 HKSJ 는 원래 HKSJ 보다 넓다."""
        # 거의 같은 효과 세 개
        y, se = np.array([1.0, 1.01, 0.99]), np.array([0.3, 0.3, 0.3])
        plain = MA.random_effects(y, se, ci="hksj")
        modified = MA.random_effects(y, se, ci="mhksj")
        self.assertEqual(plain["tau2"], 0.0)
        self.assertGreater(modified["ci_hi"] - modified["ci_lo"], plain["ci_hi"] - plain["ci_lo"])

    def test_small_k(self):
        """k=1 은 통합하지 않고, k=2 는 예측구간이 비고 t(1) 구간을 쓴다."""
        # 한 개·두 개 사상
        one = MA.random_effects(np.array([1.2]), np.array([0.2]))
        self.assertEqual(one["k"], 1)
        self.assertTrue(np.isnan(one["ci_lo"]) and np.isnan(one["pi_lo"]))
        two = MA.random_effects(np.array([1.0, 2.0]), np.array([0.2, 0.3]))
        self.assertTrue(np.isnan(two["pi_lo"]))
        self.assertGreater(two["ci_hi"] - two["ci_lo"], 2 * 12.7 * np.sqrt(1 / np.sum(1 / (np.array([0.04, 0.09])
                                                                                              + two["tau2"]))) - 1e-9)

    def test_se_from_ci_round_trip(self):
        """logit 대칭 구간에서 되돌린 SE 가 원래 SE 와 같다."""
        # AUC 0.8 에 logit SE 0.25 인 구간을 만든다
        mid, se = MA.logit(0.8), 0.25
        lo, hi = MA.expit(mid - MA.Z975 * se), MA.expit(mid + MA.Z975 * se)
        self.assertAlmostEqual(float(MA.se_from_ci(lo, hi)), se, places=12)

    def test_rejects_bad_input(self):
        """SE 가 0 이거나 길이가 다르면 멈춘다."""
        with self.assertRaises(ValueError):
            MA.random_effects(np.array([1.0, 2.0]), np.array([0.1, 0.0]))
        with self.assertRaises(ValueError):
            MA.random_effects(np.array([1.0, 2.0]), np.array([0.1]))


if __name__ == "__main__":
    unittest.main()
