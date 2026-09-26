"""M2 효과 크기·통합·판정·재표본 점검 단위 검사 (합성 자료, 홀드아웃 없음)."""

import unittest

import numpy as np
import pandas as pd

from src.data import uncertainty
from src.data.validation.meta_analysis import Z975, expit, logit
from src.models import m2_decision as D
from src.models.m2_effects import effects, paired
from src.models.m2_pooling import pool, transport
from src.models.m2_se_check import cluster_draws


def long_row(score, unit, event, value, lo, hi, n, role="development", stratum="ALL"):
    """M1 긴 표 한 행."""
    return {"score": score, "unit": unit, "stratum": stratum, "storm": "ALL", "metric": "observed-label_auc",
            "value": value, "ci_lo": lo, "ci_hi": hi, "n_units": n, "test_event": event, "role": role}


def sym_ci(auc: float, se: float) -> tuple[float, float]:
    """logit 척도에서 대칭인 95% 구간."""
    return float(expit(logit(auc) - Z975 * se)), float(expit(logit(auc) + Z975 * se))


class EffectsTest(unittest.TestCase):
    """포함 규칙과 짝 차이 분산을 확인한다."""

    def test_inclusion_rules(self):
        """양성 격자 < 5, 폴리곤 < 3, 구간 퇴화·경계, AUC 결측을 이유와 함께 뺀다."""
        # 사상 다섯 개에 각기 다른 탈락 사유를 넣는다
        rows = [long_row("s", "cell_gate", "ok", 0.8, *sym_ci(0.8, 0.2), 10),
                long_row("s", "cluster_gate", "ok", 0.78, *sym_ci(0.78, 0.3), 3),
                long_row("s", "cell_gate", "few", 0.8, *sym_ci(0.8, 0.2), 4),
                long_row("s", "cluster_gate", "few", 0.8, *sym_ci(0.8, 0.2), 2),
                long_row("s", "cell_gate", "flat", 0.8, 0.8, 0.8, 30),
                long_row("s", "cell_gate", "edge", 0.99, 0.95, 1.0, 30),
                long_row("s", "cell_gate", "none", np.nan, np.nan, np.nan, 0),
                long_row("s", "object", "ok", 0.7, *sym_ci(0.7, 0.1), 3),
                long_row("s", "object", "few", 0.7, *sym_ci(0.7, 0.1), 2)]
        e = effects(pd.DataFrame(rows)).set_index(["unit", "test_event"])
        self.assertTrue(e.loc[("cell_gate", "ok"), "included"])
        self.assertTrue(e.loc[("cluster_gate", "ok"), "included"])
        self.assertEqual(e.loc[("cluster_gate", "ok"), "n_pos_cells"], 10)
        self.assertEqual(e.loc[("cell_gate", "ok"), "n_clusters"], 3)
        self.assertAlmostEqual(e.loc[("cell_gate", "ok"), "se"], 0.2, places=10)
        self.assertEqual(e.loc[("cell_gate", "few"), "reason"], "positive_cells_lt_5")
        self.assertEqual(e.loc[("cluster_gate", "few"), "reason"], "positive_cells_lt_5")
        self.assertEqual(e.loc[("cell_gate", "flat"), "reason"], "ci_degenerate_or_boundary")
        self.assertEqual(e.loc[("cell_gate", "edge"), "reason"], "ci_degenerate_or_boundary")
        self.assertEqual(e.loc[("cell_gate", "none"), "reason"], "auc_missing_or_boundary")
        self.assertTrue(e.loc[("object", "ok"), "included"])
        self.assertEqual(e.loc[("object", "few"), "reason"], "polygons_lt_3")

    def test_paired_variance_and_intersection(self):
        """짝 차이는 둘 다 포함된 사상만 쓰고 분산은 SE_m² + SE_b² − 2ρ SE_m SE_b 다."""
        # 모델은 사상 a·b, 기준선은 a·c 에 있다
        rows = [long_row("m", "cell_gate", "a", 0.85, *sym_ci(0.85, 0.3), 10),
                long_row("m", "cell_gate", "b", 0.85, *sym_ci(0.85, 0.3), 10),
                long_row("b", "cell_gate", "a", 0.75, *sym_ci(0.75, 0.4), 10),
                long_row("b", "cell_gate", "c", 0.75, *sym_ci(0.75, 0.4), 10)]
        e = effects(pd.DataFrame(rows))
        d0, d5 = paired(e, "m", "b", rho=0.0), paired(e, "m", "b", rho=0.5)
        self.assertEqual(d0["test_event"].tolist(), ["a"])
        self.assertAlmostEqual(d0["y"].iloc[0], logit(0.85) - logit(0.75), places=10)
        self.assertAlmostEqual(d0["se"].iloc[0], 0.5, places=10)
        self.assertAlmostEqual(d5["se"].iloc[0], np.sqrt(0.09 + 0.16 - 0.12), places=10)


class PoolingTest(unittest.TestCase):
    """유효 표본 열과 이전 가능성 표를 확인한다."""

    def test_effective_sample_columns(self):
        """SE 가 아주 작은 사상 하나가 고정효과 가중치를 거의 다 가진다."""
        # 세 사상 중 하나의 SE 를 매우 작게 둔다
        sub = pd.DataFrame({"test_event": ["x", "y", "z"], "auc": [0.9, 0.7, 0.8], "y": logit([0.9, 0.7, 0.8]),
                            "se": [0.02, 0.4, 0.4], "n_units": [1000, 10, 10], "n_pos_cells": [1000, 10, 10],
                            "n_clusters": [50, 3, 3]})
        r = pool(sub)
        self.assertEqual(r["fe_max_event"], "x")
        self.assertGreater(r["fe_max_share"], 0.99)
        self.assertLess(r["k_eff_fe"], 1.05)
        self.assertGreater(r["k_eff_re"], r["k_eff_fe"])
        self.assertAlmostEqual(r["mean_equal"], 0.8, places=12)
        self.assertAlmostEqual(r["mean_unit_weighted"], (0.9 * 1000 + 0.7 * 10 + 0.8 * 10) / 1020, places=12)
        self.assertEqual((r["k"], r["n_clusters_total"], r["events"]), (3, 56, "x;y;z"))

    def test_transport_sides(self):
        """홀드아웃 AUC 가 개발 예측구간 아래·안·위인지 가른다."""
        # 개발 예측구간 [0.6, 0.9] 에 홀드아웃 세 사상
        e = pd.DataFrame({"score": "s", "unit": "cell_gate", "stratum": "ALL", "role": "holdout", "included": True,
                          "test_event": ["h1", "h2", "h3"], "auc": [0.5, 0.7, 0.95]})
        p = pd.DataFrame([{"score": "s", "unit": "cell_gate", "stratum": "ALL", "set": "development",
                           "variant": "main", "k": 5, "auc_pi_lo": 0.6, "auc_pi_hi": 0.9}])
        t = transport(e, p)
        self.assertEqual(t["side"].tolist(), ["below", "inside", "above"])
        self.assertEqual(t["inside_dev_pi"].tolist(), [False, True, False])


class DecisionTest(unittest.TestCase):
    """R2 게이트 분류와 R3 구분 규칙을 확인한다."""

    def test_gate_class(self):
        """하한 ≥ 0.70 은 사상 수준 통과, 평균만 넘으면 점추정만 통과, k=1 은 통합 불가."""
        # 경계값 0.70 을 포함해 본다
        base = {"k": 4, "auc_mu": 0.8, "auc_ci_hi": 0.9, "auc_pi_lo": 0.72, "auc_pi_hi": 0.9, "i2": 0.1, "tau2": 0.1}
        self.assertEqual(D.gate_class(pd.Series(base | {"auc_ci_lo": 0.70}))["class"], "사상 수준 통과")
        self.assertEqual(D.gate_class(pd.Series(base | {"auc_ci_lo": 0.69}))["class"], "점추정만 통과")
        self.assertEqual(D.gate_class(pd.Series(base | {"auc_ci_lo": 0.5, "auc_mu": 0.69}))["class"], "미달")
        self.assertEqual(D.gate_class(pd.Series(base | {"k": 1, "auc_ci_lo": np.nan}))["class"], "통합 불가")
        self.assertEqual(D.gate_class(pd.Series(base | {"auc_ci_lo": 0.71}))["prediction"],
                         "새 사상에서도 게이트 위로 예측됨")
        self.assertEqual(D.gate_class(pd.Series(base | {"k": 2, "auc_ci_lo": 0.71}))["prediction"], "예측구간 없음")

    def test_diff_class(self):
        """구간이 0 을 포함하면 구분되지 않는다."""
        # 세 경우와 k=1
        row = {"k": 5, "mu": 0.1}
        self.assertEqual(D.diff_class(pd.Series(row | {"ci_lo": -0.1, "ci_hi": 0.3})), "사상 수준에서 구분되지 않는다")
        self.assertEqual(D.diff_class(pd.Series(row | {"ci_lo": 0.01, "ci_hi": 0.3})), "사상 수준에서 모델이 높다")
        self.assertEqual(D.diff_class(pd.Series(row | {"ci_lo": -0.3, "ci_hi": -0.01})), "사상 수준에서 기준선이 높다")
        self.assertEqual(D.diff_class(pd.Series({"k": 1, "ci_lo": 0.1, "ci_hi": 0.2})), "통합 불가")


class SeCheckTest(unittest.TestCase):
    """재표본 재현이 기존 덩어리 재표본과 같은지 본다."""

    def test_cluster_draws_match_existing_bootstrap(self):
        """점값과 백분위 구간이 uncertainty.cluster_bootstrap_auc 와 같다."""
        # 격자 20×20 에 양성 덩어리 셋을 두고 점수를 무작위로 준다
        rng = np.random.default_rng(0)
        gx, gy = np.meshgrid(np.arange(20) * 100.0, np.arange(20) * 100.0)
        x, y = gx.ravel(), gy.ravel()
        labels = np.zeros(400, bool)
        labels[[0, 1, 20, 150, 151, 300, 301, 302]] = True
        score = rng.normal(size=400) + labels
        score[5] = np.nan
        r = cluster_draws(labels, score, x, y, n_boot=500, seed=42)
        keep = np.isfinite(score)
        ref = uncertainty.cluster_bootstrap_auc(labels[keep], score[keep], x[keep], y[keep], n_boot=500, seed=42)
        self.assertAlmostEqual(round(r["auc"], 4), ref["auc"], places=10)
        self.assertEqual(list(np.round(np.percentile(r["draws"], [2.5, 97.5]), 4)), ref["ci95"])
        self.assertEqual(r["n_cluster"], ref["n_cluster"])


if __name__ == "__main__":
    unittest.main()
