"""HAND 계산 단위 검사 (합성 DEM)."""

import unittest

import numpy as np
from rasterio import Affine
from shapely.geometry import LineString

from src.data import features as F
from src.data import hand as H


class HandTest(unittest.TestCase):
    """합성 계곡·평탄지에서 HAND 를 확인한다."""

    def valley(self) -> np.ndarray:
        """가운데 열이 가장 낮고 아래로 기우는 계곡."""
        rows, cols = np.indices((9, 9))
        return (np.abs(cols - 4) * 5.0 + (8 - rows) * 1.0).astype(float)

    def test_receivers_match_flow_accumulation(self):
        """d8_receivers 로 센 누적이 기존 flow_accumulation 과 같다."""
        # 싱크가 있는 무작위 DEM 에서 두 누적을 비교한다
        rng = np.random.default_rng(0)
        elev = rng.normal(50, 5, (12, 15))
        filled = F.fill_sinks(elev)
        acc = F.flow_accumulation(filled, 100.0)
        mine = H.accumulation_from_receivers(H.d8_receivers(filled, 100.0), filled)
        np.testing.assert_allclose(mine, acc)

    def test_valley_hand_is_height_above_channel(self):
        """하천 열 위 격자의 HAND 는 같은 행 하천 칸과의 표고차다."""
        # 가운데 열을 하천으로 두면 옆 칸은 하천으로 곧장 흐른다
        elev = self.valley()
        streams = np.zeros(elev.shape, bool)
        streams[:, 4] = True
        out, summary = H.hand(elev, streams, 100.0)
        self.assertTrue(np.allclose(out[:, 4], 0.0))
        self.assertAlmostEqual(out[3, 5], 5.0)
        self.assertAlmostEqual(out[3, 6], 10.0)
        self.assertEqual(summary["n_stream_cells"], 9)

    def test_flat_depression_drains_to_stream(self):
        """채운 웅덩이의 평탄 칸도 ε 방향으로 흘러 하천 기준을 얻는다."""
        # 계곡 안에 웅덩이를 파고 가장 아래 행만 하천으로 둔다
        elev = self.valley()
        elev[3:6, 1:3] = 0.0
        streams = np.zeros(elev.shape, bool)
        streams[8, 4] = True
        routed = H.fill_sinks_epsilon(elev)
        recv = H.d8_receivers(routed, 100.0).reshape(elev.shape)
        interior = np.zeros(elev.shape, bool)
        interior[1:-1, 1:-1] = True
        self.assertTrue((recv[interior] >= 0).all())
        out, summary = H.hand(elev, streams, 100.0)
        self.assertTrue((out >= 0).all())
        self.assertGreater(summary["n_reach_stream"], 1)
        self.assertLess(np.nanmax(routed - F.fill_sinks(elev)), 1e-9)

    def test_nan_cells_stay_nan(self):
        """DEM 결측 칸의 HAND 는 NaN 이다."""
        # 한 칸을 결측으로 두고 결과를 본다
        elev = self.valley()
        elev[0, 0] = np.nan
        out, _ = H.hand(elev, np.zeros(elev.shape, bool), 100.0)
        self.assertTrue(np.isnan(out[0, 0]))
        self.assertEqual(int(np.isnan(out).sum()), 1)

    def test_stream_mask_from_lines(self):
        """중심선이 지나는 칸이 하천으로 표시된다."""
        # 3×3 격자망 가운데 행을 가로지르는 선을 굽는다
        lat = F.Lattice(Affine(100, 0, 0, 0, -100, 300), (3, 3), 100.0)
        mask = H.stream_mask_from_lines([LineString([(0, 150), (300, 150)])], lat)
        self.assertTrue(mask[1].all())
        self.assertFalse(mask[0].any() or mask[2].any())


if __name__ == "__main__":
    unittest.main()
