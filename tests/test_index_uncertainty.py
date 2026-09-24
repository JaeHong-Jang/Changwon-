"""복합지수 설계 불확실성의 합성 격자 검증."""

from __future__ import annotations

import unittest

import numpy as np

from src.data import index_uncertainty as U
from src.data import layers as L


class IndexUncertaintyTest(unittest.TestCase):
    """합성 격자로 설계 불확실성 계산과 입력 검증을 확인한다."""

    def _frame(self):
        """기준 산식과 가까운 격자 쌍이 있는 작은 자료를 만든다."""
        import geopandas as gpd
        from shapely.geometry import Point

        # 요소 점수와 기준 지수를 계산하고 가까운 격자를 배치한다.
        raw = np.array([
            [10, 10, 10, 10], [9, 9, 9, 9], [8, 3, 8, 3],
            [3, 8, 3, 8], [1, 1, 1, 1],
        ], dtype=float)
        scaled = np.column_stack([L.rescale_positive(raw[:, j]) for j in range(4)])
        cdri = L.minmax(L.geometric_aggregate(scaled, np.full(4, .25)))
        return gpd.GeoDataFrame({
            "grid_id": list("abcde"), "L1": raw[:, 0], "E": raw[:, 1],
            "V": raw[:, 2], "capacity_deficit": raw[:, 3],
            "cdri": cdri, "rank": U._rank_first(cdri),
            "in_robust_core": [1, 0, 0, 0, 0],
        }, geometry=[Point(x, 0) for x in (0, 100, 500, 900, 1300)], crs="EPSG:5179")

    def test_nms_suppresses_close_point_and_expands_window(self):
        """가까운 2위는 버리고 먼 후보를 차례대로 선택한다."""
        # 순위는 높지만 가까운 두 번째 점을 포함한 좌표를 만든다.
        scores = np.array([5., 4., 3., 2.])
        xy = np.array([[0., 0.], [100., 0.], [500., 0.], [900., 0.]])
        self.assertEqual(U._nms(scores, xy, limit=2).tolist(), [0, 2])
        self.assertEqual(U._nms(scores, xy, limit=4).tolist(), [0, 2, 3])

    def test_probabilities_ranks_and_factor_effects(self):
        """전 조합 포함 확률과 요인 분산분해가 설계 결과에 맞는다."""
        # 최소 반복 수로 모든 설계 조합의 결과를 계산한다.
        frame = self._frame()
        grid, rank90, robust, effects, designs, summary = U.analyse(frame, replicates=14, seed=7, top_n=2)

        # 설계 수와 격자별 포함 확률·순위 구간을 확인한다.
        self.assertEqual(summary["design_count"], 1008)
        self.assertEqual(summary["baseline"]["top20_grid_ids"], ["a", "c"])
        self.assertTrue(np.allclose(grid.top20_probability, grid.top20_count / 1008))
        self.assertEqual(int(grid.top20_count.sum()), 2 * 1008)
        self.assertEqual(len(designs), 1008)
        self.assertTrue(rank90.rank_p05.le(rank90.rank_p95).all())
        self.assertTrue(robust.top20_probability.ge(.8).all())

        # 요인별 일차 분산비가 계산 가능한 범위에 있는지 확인한다.
        for _, group in effects.groupby("metric"):
            self.assertEqual(len(group), 5)
            self.assertTrue(group.first_order_ratio.between(0, 1).all())
            self.assertLessEqual(group.first_order_ratio.sum(), 1.0000001)

    def test_mismatched_baseline_stops_before_simulation(self):
        """저장 기준 순위가 다르면 불확실성을 계산하지 않는다."""
        # 저장 순위 하나를 바꿔 기준 설계 재현 오류를 만든다.
        frame = self._frame()
        frame.loc[0, "rank"] = 2
        with self.assertRaisesRegex(ValueError, "정확히 재현하지 못한다"):
            U.analyse(frame, replicates=14, top_n=2)


if __name__ == "__main__":
    unittest.main()
