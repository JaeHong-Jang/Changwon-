"""M4S 가상 인벤토리·점수·집중·공식·복제 채점·요약·판정 단위 검사 (합성 자료, 홀드아웃 없음)."""

import math
import unittest

import numpy as np
import pandas as pd
from scipy.stats import norm

from src.data.trace_footprint import Footprint
from src.data.validation.weight_concentration import covariance_form, group_share, top_share
from src.models import m4s_decision as D
from src.models import m4s_summary as S
from src.models.m4s_anchor import fit_anchor
from src.models.m4s_measure import make_landscape, replicate
from src.synth.detectability import assemble, dominant_object
from src.synth.inventory import AREA_MAX, AREA_MIN, draw_areas, ellipses, event_counts
from src.synth.landscape import background, bounds, lattice
from src.synth.scenarios import Scenario, grid
from src.synth.tilt import lognormal_top_share, tilted_gap


class ScenarioGridTest(unittest.TestCase):
    """절차 §2 의 시나리오 수·순서."""

    def test_counts_and_order(self):
        """115개, 묶음별 60·24·12·9·10개, 번호는 연속이고 첫 행은 σ=0.5·β=−1·n=30."""
        # 묶음별 수와 첫 두 행의 고리 순서를 확인한다
        scenarios = grid()
        self.assertEqual(len(scenarios), 115)
        counts = pd.Series([s.block for s in scenarios]).value_counts().to_dict()
        self.assertEqual(counts, {"A": 60, "B": 24, "C1": 12, "D": 10, "C2": 9})
        self.assertEqual([s.no for s in scenarios], list(range(115)))
        self.assertEqual((scenarios[0].shape, scenarios[0].beta, scenarios[0].n_obj), (0.5, -1.0, 30))
        self.assertEqual((scenarios[1].shape, scenarios[1].beta, scenarios[1].n_obj), (0.5, -1.0, 200))
        b = [s for s in scenarios if s.block == "B"]
        self.assertTrue(all(s.n_obj == 50 and s.shape == 1.5 for s in b))


class InventoryTest(unittest.TestCase):
    """크기 분포 절단·ζ·타원 넓이·사상별 객체 수."""

    def test_lognormal_truncation_and_zeta(self):
        """절단 범위를 지키고 ζ = (ln a − ln m)/σ 다."""
        # 넓은 분산으로 절단이 일어나게 한다
        area, zeta = draw_areas(np.random.default_rng(1), 5000, "lognormal", 5000.0, 3.0)
        self.assertTrue((area >= AREA_MIN).all() and (area <= AREA_MAX).all())
        np.testing.assert_allclose(zeta, (np.log(area) - np.log(5000.0)) / 3.0)

    def test_pareto_median_and_zeta(self):
        """Pareto 의 표본 중앙값이 m 에 가깝고 ζ = α ln(a/x_m) − 1 이다."""
        # 큰 표본에서 중앙값과 ζ 평균·표준편차를 본다
        area, zeta = draw_areas(np.random.default_rng(2), 200_000, "pareto", 5000.0, 1.5)
        self.assertAlmostEqual(np.median(area) / 5000.0, 1.0, delta=0.02)
        x_m = 5000.0 * 2 ** (-1 / 1.5)
        np.testing.assert_allclose(zeta, 1.5 * np.log(area / x_m) - 1)
        self.assertAlmostEqual(zeta.mean(), 0.0, delta=0.02)

    def test_ellipse_area_exact_and_inside(self):
        """다각형 넓이가 정확히 a 이고 영역 안에 든다."""
        # 큰 객체와 작은 객체를 섞는다
        import shapely

        box = bounds(200)
        area = np.array([60.0, 5000.0, 1e6, 9e6])
        polys = ellipses(np.random.default_rng(3), area, box)
        np.testing.assert_allclose(shapely.area(polys), area, rtol=1e-9)
        b = shapely.bounds(polys)
        self.assertTrue((b[:, 0] >= box[0]).all() and (b[:, 2] <= box[2]).all())
        self.assertTrue((b[:, 1] >= box[1]).all() and (b[:, 3] <= box[3]).all())

    def test_event_counts(self):
        """equal 은 모두 n̄, skewed 는 최소 1 이고 합이 E·n̄ 근처다."""
        # 두 방식의 수를 본다
        np.testing.assert_array_equal(event_counts(np.random.default_rng(4), 4, 50, "equal"), [50] * 4)
        c = event_counts(np.random.default_rng(4), 10, 50, "skewed")
        self.assertTrue((c >= 1).all())
        self.assertLessEqual(abs(c.sum() - 500), 10)
        with self.assertRaises(ValueError):
            event_counts(np.random.default_rng(4), 4, 50, "other")


class ScoreTest(unittest.TestCase):
    """배경 잡음·칸 주인 객체·점수 조립."""

    def test_background_standardized_and_seeded(self):
        """평균 0·표준편차 1 이고 같은 시드면 같은 값이다."""
        # 같은 시드로 두 번 만든다
        a = background(np.random.default_rng(5), 50)
        b = background(np.random.default_rng(5), 50)
        np.testing.assert_array_equal(a, b)
        self.assertAlmostEqual(a.mean(), 0.0, places=12)
        self.assertAlmostEqual(a.std(), 1.0, places=12)

    def test_dominant_object_and_assemble(self):
        """칸마다 겹침 면적이 가장 큰 객체, 동점이면 번호가 작은 객체의 μ 를 더한다."""
        # 칸 0 은 객체 1 이 더 크고, 칸 1 은 두 객체가 동점, 칸 2 는 겹침 없음
        fp = Footprint(obj=np.array([0, 1, 1, 0]), cell=np.array([0, 0, 1, 1]), area=np.array([10.0, 30.0, 5.0, 5.0]),
                       flooded=np.zeros(3), cell_area=np.full(3, 1e4), rep_cell=np.array([0, 1]))
        np.testing.assert_array_equal(dominant_object(fp), [1, 0, -1])
        np.testing.assert_allclose(assemble(np.zeros(3), fp, np.array([2.0, 5.0])), [5.0, 2.0, 0.0])


class ConcentrationTest(unittest.TestCase):
    """공분산 형태·상위 몫·묶음 몫."""

    def test_covariance_form_matches_direct(self):
        """ρ · sd · √(n/n_eff − 1) = Σ w̃A − Ā (무작위 가중치·기여)."""
        # 소실(W = 0)과 Ã 결측 객체를 섞는다
        rng = np.random.default_rng(6)
        W = np.exp(2 * rng.standard_normal(300))
        W[:20] = 0.0
        A = rng.uniform(0.3, 1.0, 300)
        At = rng.uniform(0.3, 1.0, 300)
        At[20:25] = np.nan
        c = covariance_form(W, A, At)
        self.assertAlmostEqual(c["size_term_product"], c["size_term_direct"], places=12)
        self.assertEqual(c["n_S"], 275)

    def test_covariance_form_equal_weights(self):
        """같은 가중치면 크기 가중 항은 0 이고 집중 인수도 0 이다."""
        # 가중치가 모두 같다
        c = covariance_form(np.ones(5), np.arange(5.0), np.ones(5))
        self.assertAlmostEqual(c["size_term_direct"], 0.0)
        self.assertAlmostEqual(c["concentration_factor"], 0.0)
        self.assertEqual(c["size_term_product"], 0.0)

    def test_shares(self):
        """상위 10% 몫은 ⌈0.1 n⌉ 개의 몫, 묶음 몫은 최대 묶음 합 / 전체."""
        # 가중치 10개 중 가장 큰 1개와 두 묶음
        W = np.array([10.0] + [1.0] * 9)
        self.assertAlmostEqual(top_share(W), 10 / 19)
        self.assertAlmostEqual(top_share(W, extra_mass=1.0), 10 / 20)
        self.assertAlmostEqual(group_share(W, np.array([0] * 5 + [1] * 5)), 14 / 19)


class TiltTest(unittest.TestCase):
    """§5.3 공식."""

    def test_zero_and_sign(self):
        """β = 0 또는 σ = 0 이면 0, 부호는 β 의 부호다."""
        self.assertEqual(tilted_gap(2.0, 0.0, 0.95, 0.5), 0.0)
        self.assertEqual(tilted_gap(0.0, 1.0, 0.95, 0.5), 0.0)
        self.assertGreater(tilted_gap(1.5, 0.5, 0.95, 0.5), 0)
        self.assertLess(tilted_gap(1.5, -0.5, 0.95, 0.5), 0)
        self.assertAlmostEqual(tilted_gap(1.5, -1.0, 0.95, 0.5), -0.321, places=3)

    def test_formula_against_monte_carlo(self):
        """면적(e^{σζ}) 가중 평균 − 단순 평균이 Δ* 와 0.005 안에서 같다."""
        # 큰 표본에서 객체 값 Φ(μ/√2) 의 두 평균을 비교한다
        rng = np.random.default_rng(7)
        zeta, eps = rng.standard_normal(2_000_000), rng.standard_normal(2_000_000)
        sigma, beta, mu0, tau = 1.0, -0.5, 0.95, 0.5
        value = norm.cdf((mu0 + beta * zeta + tau * eps) / math.sqrt(2))
        w = np.exp(sigma * zeta)
        self.assertAlmostEqual(np.average(value, weights=w) - value.mean(), tilted_gap(sigma, beta, mu0, tau), delta=0.005)

    def test_lognormal_top_share(self):
        """σ = 1.5 의 상위 10% 몫 0.586."""
        self.assertAlmostEqual(lognormal_top_share(1.5), 0.586, places=3)


class ReplicateTest(unittest.TestCase):
    """작은 격자에서 복제 채점 전 과정."""

    @classmethod
    def setUpClass(cls):
        """40 × 40 격자."""
        cls.land = make_landscape(40)

    def test_rules_identity_and_determinism(self):
        """8개 규칙 행, 항등식·sklearn·공분산 오차 ≤ 1e-9, 같은 복제는 같은 값, 규칙과 무관한 객체 AUC."""
        # 복제 0 을 두 번 채점한다
        sc = Scenario(no=999, block="A", shape=1.0, beta=-0.5, n_obj=12, median=30000.0)
        rows, events = replicate(sc, 0, self.land)
        again, _ = replicate(sc, 0, self.land)
        self.assertEqual([r["rule"] for r in rows], ["any", "f01", "f10", "f25", "f50", "center", "rep_point", "soft"])
        self.assertEqual(events, [])
        table = pd.DataFrame(rows)
        pd.testing.assert_frame_equal(table, pd.DataFrame(again))
        self.assertLessEqual(table["identity_abs_diff"].max(), 1e-9)
        self.assertLessEqual(table["sklearn_abs_diff"].max(), 1e-9)
        self.assertLessEqual(np.nanmax(table["cov_abs_diff"]), 1e-9)
        self.assertEqual(table["object_auc"].nunique(), 1)
        np.testing.assert_allclose(table["gap"], table["cell_auc"] - table["object_auc"])
        soft = table.set_index("rule").loc["soft"]
        self.assertEqual(soft["n_survive"], soft["n_K"])

    def test_event_block(self):
        """B 묶음은 합동 f10 한 행과 사상마다 한 행을 낸다."""
        # 사상 2개짜리 작은 시나리오
        sc = Scenario(no=998, block="B", shape=1.0, n_obj=5, n_events=2, median=30000.0, upsilon=0.5)
        rows, events = replicate(sc, 1, self.land)
        self.assertEqual([r["rule"] for r in rows], ["f10"])
        self.assertEqual(sorted(e["event"] for e in events), [0, 1])
        self.assertTrue(np.isfinite(rows[0]["max_event_share"]))


class SummaryTest(unittest.TestCase):
    """중앙값 구간·분류·뒤집힘·요약."""

    def test_median_interval_ranks(self):
        """R = 200 이면 86번째·115번째 값."""
        values = np.arange(1.0, 201.0)
        self.assertEqual(S.median_interval(values), (86.0, 115.0))

    def test_classify(self):
        """P10 경계 0.1·0.5."""
        self.assertEqual([S.classify(v) for v in (0.5, 0.49, 0.1, 0.09)], ["벌어짐", "가끔", "가끔", "없음"])

    def test_annotate_and_summary(self):
        """게이트·단위 뒤집힘·규칙 뒤집힘과 시나리오 요약의 P10."""
        # 복제 둘, 규칙 둘: f10 은 격자 통과, soft 는 격자 탈락
        base = dict(scenario_no=0, n_pos_cells=10, n_K=10, object_auc=0.72, object_capture=0.6, capture=0.6,
                    term_size_weight=0.0, term_within_object=0.0, term_erasure=0.0, n_eff=5.0, n_survive=8,
                    top10_share=0.5, max_event_share=1.0, sd_A=0.1, rho_wA=0.0, concentration_factor=1.0, n_polygons=10)
        rows = [base | dict(replicate=j, rule="f10", cell_auc=0.75, gap=0.03) for j in range(2)]
        rows += [base | dict(replicate=j, rule="soft", cell_auc=0.55, gap=-0.17) for j in range(2)]
        rep = S.annotate(pd.DataFrame(rows))
        soft = rep[rep["rule"] == "soft"]
        self.assertTrue(soft["unit_flip"].all() and soft["auc_unit_flip"].all() and soft["rule_flip"].all())
        self.assertFalse(rep[rep["rule"] == "f10"]["rule_flip"].any())
        summary = S.scenario_summary(rep, pd.DataFrame([{"no": 0, "block": "A"}]))
        self.assertEqual(summary.set_index("rule").loc["soft", "p10"], 1.0)
        self.assertEqual(summary.set_index("rule").loc["soft", "class"], "벌어짐")


class DecisionTest(unittest.TestCase):
    """P3 구역 판정과 종합 판정."""

    def _summary(self, rule: str, gap: float, cls: str, beta: float, delta: float) -> pd.DataFrame:
        """묶음 A n = 200 한 행."""
        return pd.DataFrame([{"scenario_no": 0, "block": "A", "n_obj": 200, "shape": 1.5, "rule": rule, "beta": beta,
                              "mu0": 0.95, "delta_star": delta, "gap_median": gap, "p10": 0.9, "class": cls}])

    def test_p3_zones(self):
        """구역 안 부호·분류 조건과 f10 의 강한 구역 조건."""
        # soft 는 |Δ*| ≥ 0.15 에서 벌어짐을 요구하고 f10 은 |Δ*| ≥ 0.20 에서만 요구한다
        self.assertTrue(D.p3(self._summary("soft", -0.2, "벌어짐", -1.0, -0.3))["pass"])
        self.assertFalse(D.p3(self._summary("soft", -0.05, "가끔", -1.0, -0.17))["pass"])
        self.assertTrue(D.p3(self._summary("f10", -0.05, "가끔", -1.0, -0.17), "f10", strong=0.2)["pass"])
        self.assertFalse(D.p3(self._summary("f10", 0.05, "가끔", -1.0, -0.17), "f10", strong=0.2)["pass"])
        self.assertFalse(D.p3(self._summary("soft", 0.0, "벌어짐", 0.0, 0.0))["pass"])

    def test_verdict(self):
        """세 예측의 맞음 수에 따른 판정 문구."""
        ok, bad = {"pass": True}, {"pass": False}
        self.assertTrue(D.verdict(ok, ok, ok).startswith("일반성 지지"))
        self.assertEqual(D.verdict(ok, bad, ok), "부분 지지: 틀린 예측 P3")
        self.assertTrue(D.verdict(bad, bad, bad).startswith("폐기"))


class AnchorTest(unittest.TestCase):
    """창원 기준점 맞춤."""

    def test_fit_recovers_parameters(self):
        """잡음 없는 모형 값에서 σ̂·β̂·μ̂0 를 되찾고 τ̂ ≈ 0 이다."""
        # 로그정규 면적과 Ã = Φ((μ0 + βζ)/√2)
        rng = np.random.default_rng(8)
        zeta = rng.standard_normal(500)
        zeta = (zeta - zeta.mean()) / zeta.std()
        area = np.exp(np.log(5000) + 1.2 * zeta)
        value = norm.cdf((0.8 - 0.6 * zeta) / math.sqrt(2))
        fit = fit_anchor(area, value)
        self.assertAlmostEqual(fit["sigma_hat"], 1.2, places=9)
        self.assertAlmostEqual(fit["beta_hat"], -0.6, delta=0.01)
        self.assertAlmostEqual(fit["mu0_hat"], 0.8, delta=0.01)
        self.assertLess(fit["tau_hat"], 0.05)
        self.assertAlmostEqual(fit["delta_hat"], tilted_gap(1.2, fit["beta_hat"], fit["mu0_hat"], fit["tau_hat"]))


if __name__ == "__main__":
    unittest.main()
