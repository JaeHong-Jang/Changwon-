"""공간 군집과 덩어리 단위 부트스트랩 검증 (src/data/uncertainty.py)."""

import unittest

import numpy as np

from src.data import uncertainty as U


def line(n: int, x0: float = 0.0, spacing: float = 100.0):
    """가로로 spacing 간격으로 늘어선 격자 중심점 n 개."""
    return np.arange(n) * spacing + x0, np.zeros(n)


class ClusterTest(unittest.TestCase):
    """붙어 있는 격자는 한 덩어리, 떨어진 격자는 다른 덩어리여야 한다."""

    def test_adjacent_grids_form_one_cluster(self):
        x, y = line(5)                       # 100m 간격 → 전부 이어진다
        self.assertEqual(len(np.unique(U.spatial_clusters(x, y))), 1)

    def test_far_apart_grids_are_separate(self):
        x = np.array([0.0, 100.0, 5000.0, 5100.0])
        y = np.zeros(4)
        self.assertEqual(len(np.unique(U.spatial_clusters(x, y))), 2)

    def test_diagonal_neighbour_is_connected(self):
        """100m 격자의 대각선 이웃은 141m 라 기본 반경 150m 안에 든다."""
        x = np.array([0.0, 100.0])
        y = np.array([0.0, 100.0])
        self.assertEqual(len(np.unique(U.spatial_clusters(x, y))), 1)

    def test_gap_beyond_radius_splits(self):
        x = np.array([0.0, 200.0])           # 200m > 150m
        y = np.zeros(2)
        self.assertEqual(len(np.unique(U.spatial_clusters(x, y))), 2)

    def test_single_point_is_one_cluster(self):
        self.assertEqual(len(U.spatial_clusters(np.array([0.0]), np.array([0.0]))), 1)


class EffectiveSampleTest(unittest.TestCase):
    def test_counts_clusters_not_grids(self):
        """양성 20칸이 두 덩어리면 유효 표본은 2 다."""
        x = np.concatenate([np.arange(10) * 100.0, np.arange(10) * 100.0 + 9000.0])
        y = np.zeros(20)
        labels = np.ones(20, bool)
        result = U.effective_sample(labels, x, y)
        self.assertEqual(result["n_positive_grid"], 20)
        self.assertEqual(result["n_cluster"], 2)
        self.assertEqual(result["cluster_size_max"], 10)

    def test_ignores_negative_grids(self):
        """음성 격자는 군집에 들어가면 안 된다."""
        x, y = line(6)
        labels = np.array([True, True, False, False, True, True])
        self.assertEqual(U.effective_sample(labels, x, y)["n_positive_grid"], 4)

    def test_no_positive_is_not_an_error(self):
        x, y = line(3)
        self.assertEqual(U.effective_sample(np.zeros(3, bool), x, y)["n_cluster"], 0)


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        # 양성 40칸을 4덩어리로, 음성 400칸을 멀리 둔다.
        self.x = np.concatenate([
            np.concatenate([np.arange(10) * 100.0 + c * 20000.0 for c in range(4)]),
            rng.random(400) * 1000.0 + 200000.0,
        ])
        self.y = np.zeros(len(self.x))
        self.labels = np.concatenate([np.ones(40, bool), np.zeros(400, bool)])
        # 실제 자료에서 붙어 있는 격자는 점수가 거의 같다. 그 상관을 넣어야 유사복제를
        # 재현할 수 있다. 덩어리마다 하나의 값을 뽑아 10칸에 그대로 쓴다.
        per_cluster = rng.normal(1.0, 0.8, 4)
        self.scores = np.concatenate([
            np.repeat(per_cluster, 10),
            rng.normal(0.0, 0.5, 400),
        ])

    def test_resamples_by_cluster(self):
        out = U.cluster_bootstrap_auc(self.labels, self.scores, self.x, self.y, n_boot=200)
        self.assertEqual(out["n_cluster"], 4)
        self.assertLess(out["ci95"][0], out["auc"])
        self.assertGreater(out["ci95"][1], out["auc"])

    def test_cluster_interval_is_wider_than_grid_level(self):
        """덩어리 안에서 점수가 상관되면 격자 단위 구간이 과도하게 좁아진다.

        이게 이 모듈의 존재 이유다. 실제 자료에서 격자 단위 폭 0.035, 덩어리 단위
        0.228 로 6.5배 차이였다.
        """
        from src.data.layers import roc_auc

        cluster = U.cluster_bootstrap_auc(self.labels, self.scores, self.x, self.y, n_boot=400)
        rng = np.random.default_rng(1)
        positive = np.flatnonzero(self.labels)
        negative = np.flatnonzero(~self.labels)
        draws = []
        for _ in range(400):
            idx = positive[rng.integers(0, positive.size, positive.size)]
            truth = np.concatenate([np.ones(idx.size, bool), np.zeros(negative.size, bool)])
            draws.append(roc_auc(truth, np.concatenate([self.scores[idx], self.scores[negative]])))
        grid_width = float(np.diff(np.percentile(draws, [2.5, 97.5]))[0])
        self.assertGreater(cluster["ci_width"], grid_width)

    def test_reproducible_with_same_seed(self):
        a = U.cluster_bootstrap_auc(self.labels, self.scores, self.x, self.y, n_boot=100, seed=7)
        b = U.cluster_bootstrap_auc(self.labels, self.scores, self.x, self.y, n_boot=100, seed=7)
        self.assertEqual(a["ci95"], b["ci95"])

    def test_missing_class_is_reported(self):
        out = U.cluster_bootstrap_auc(np.zeros(10, bool), np.arange(10.0),
                                      np.arange(10.0), np.zeros(10))
        self.assertIsNone(out["auc"])


class GradeBootstrapTest(unittest.TestCase):
    """등급 검증의 불확실성 — 양성이 한 덩어리에 몰리면 단조성을 확신할 수 없어야 한다."""

    def _layout(self, n_per_grade: int = 50):
        """등급 1~5 격자를 멀리 떨어진 줄로 놓는다. 같은 등급 안에서는 10칸마다 끊는다."""
        xs, grades = [], []
        for g in range(1, 6):
            for i in range(n_per_grade):
                xs.append(g * 100000.0 + (i // 10) * 5000.0 + (i % 10) * 100.0)
                grades.append(g)
        return np.array(xs), np.zeros(len(xs)), np.array(grades)

    def test_counts_clusters_per_grade(self):
        x, y, grades = self._layout()
        labels = np.zeros(len(x), bool)
        labels[(grades == 5)] = True             # R5 50칸 = 5덩어리
        out = U.cluster_bootstrap_grades(grades, labels, x, y, n_boot=50)
        self.assertEqual(out["clusters_by_grade"]["R5"], 5)
        self.assertEqual(out["clusters_by_grade"]["R1"], 0)

    def test_single_cluster_in_top_grade_gives_wide_interval(self):
        """최상위 등급 양성이 한 덩어리면 구간 하한이 0 이어야 한다 — 창원 R5 의 상황이다."""
        x, y, grades = self._layout()
        labels = np.zeros(len(x), bool)
        labels[np.flatnonzero(grades == 5)[:9]] = True     # R5 에 9칸, 한 덩어리
        for g in (1, 2, 3, 4):                              # 다른 등급에 흩어진 양성
            labels[np.flatnonzero(grades == g)[::10][:3]] = True
        out = U.cluster_bootstrap_grades(grades, labels, x, y, n_boot=500)
        self.assertEqual(out["top_grade_lift_ci95"][0], 0.0)
        self.assertLess(out["monotone_share"], 0.95)

    def test_strong_gradient_is_mostly_monotone(self):
        """등급마다 덩어리가 많고 발생률이 뚜렷이 오르면 단조 비율이 높아야 한다."""
        x, y, grades = self._layout(n_per_grade=200)
        labels = np.zeros(len(x), bool)
        for g, step in zip(range(1, 6), (200, 20, 8, 4, 2)):
            labels[np.flatnonzero(grades == g)[::step]] = True
        out = U.cluster_bootstrap_grades(grades, labels, x, y, n_boot=300)
        self.assertGreater(out["monotone_share"], 0.8)


class FractionTest(unittest.TestCase):
    """양성별 분율의 평균이 ROC-AUC 와 같아야 한다 (Mann-Whitney 항등식)."""

    def test_mean_equals_roc_auc_with_ties(self):
        from src.data.layers import roc_auc

        rng = np.random.default_rng(5)
        scores = rng.integers(0, 6, 300).astype(float)      # 동점을 일부러 많이 만든다
        labels = rng.random(300) < 0.2
        self.assertAlmostEqual(U.auc_fractions(labels, scores).mean(), roc_auc(labels, scores), places=12)

    def test_cluster_weighting_gives_each_flood_one_vote(self):
        """큰 덩어리 하나가 잘 맞고 작은 덩어리 둘이 틀리면, 덩어리 가중 AUC 가 더 낮아야 한다."""
        x = np.concatenate([np.arange(8) * 100.0, [50000.0], [90000.0], np.arange(20) * 100.0 + 200000.0])
        y = np.zeros(x.size)
        labels = np.concatenate([np.ones(10, bool), np.zeros(20, bool)])
        scores = np.concatenate([np.full(8, 10.0), [-10.0, -10.0], np.zeros(20)])
        from src.data.layers import roc_auc

        self.assertAlmostEqual(roc_auc(labels, scores), 0.8)
        self.assertAlmostEqual(U.cluster_weighted_auc(labels, scores, x, y), 1 / 3)


class PairedTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.x = np.concatenate([np.arange(60) * 100.0 // 10 * 1000 + np.arange(60) % 10 * 100,
                                 rng.random(600) * 1000 + 500000])
        self.y = np.zeros(self.x.size)
        self.labels = np.concatenate([np.ones(60, bool), np.zeros(600, bool)])
        self.base = np.concatenate([rng.normal(0.5, 1, 60), rng.normal(0, 1, 600)])

    def test_identical_scores_have_zero_difference(self):
        out = U.paired_cluster_bootstrap(self.labels, {"a": self.base, "b": self.base.copy()},
                                         "a", self.x, self.y, n_boot=200)
        self.assertEqual(out["b"]["diff"], 0.0)
        self.assertEqual(out["b"]["diff_ci95"], [0.0, 0.0])

    def test_clearly_better_score_is_detected(self):
        better = self.base + np.concatenate([np.full(60, 2.0), np.zeros(600)])
        out = U.paired_cluster_bootstrap(self.labels, {"a": self.base, "b": better},
                                         "a", self.x, self.y, n_boot=500)
        self.assertGreater(out["b"]["diff"], 0)
        self.assertGreater(out["b"]["diff_ci95"][0], 0)
        self.assertEqual(out["b"]["prob_better"], 1.0)


class GradeTrendTest(unittest.TestCase):
    def test_rising_rates_give_positive_slope(self):
        # 등급마다 덩어리 20개, 위 등급일수록 덩어리당 양성이 많다
        units = np.vstack([np.eye(5)[k] * (k + 1) for k in range(5) for _ in range(20)])
        sizes = np.full(5, 1000.0)
        out = U.grade_incidence_bootstrap(units, sizes, n_boot=500)
        self.assertGreater(out["trend_slope"], 0)
        self.assertLess(out["p_slope_nonpositive"], 0.01)

    def test_flat_rates_do_not_pass(self):
        units = np.vstack([np.eye(5)[k] for k in range(5) for _ in range(20)])
        out = U.grade_incidence_bootstrap(units, np.full(5, 1000.0), n_boot=500)
        self.assertGreater(out["p_slope_nonpositive"], 0.05)


if __name__ == "__main__":
    unittest.main()
