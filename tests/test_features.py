from __future__ import annotations

import unittest

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio import Affine
from shapely.geometry import box

from src.data import features as F


def _lattice(rows: int = 4, cols: int = 5, res: float = 100.0) -> F.Lattice:
    return F.Lattice(Affine(res, 0, 1000.0, 0, -res, 2000.0), (rows, cols), res)


class LatticeTest(unittest.TestCase):
    def test_lattice_from_grid_maps_rowcol(self) -> None:
        cells = [box(1000, 1900, 1100, 2000), box(1400, 1600, 1500, 1700)]  # 좌상단, 우하단
        grid = gpd.GeoDataFrame({"grid_id": ["a", "b"]}, geometry=cells, crs="EPSG:5179")
        lat, row, col = F.lattice_from_grid(grid)
        self.assertEqual(lat.shape, (4, 5))
        self.assertEqual((row.tolist(), col.tolist()), ([0, 3], [0, 4]))

    def test_misaligned_grid_raises(self) -> None:
        grid = gpd.GeoDataFrame({"grid_id": ["a"]}, geometry=[box(1010, 1900, 1110, 2000)], crs="EPSG:5179")
        with self.assertRaises(ValueError):
            F.lattice_from_grid(grid)


class TerrainTest(unittest.TestCase):
    def test_slope_of_tilted_plane(self) -> None:
        elev = np.tile(np.arange(6, dtype=float) * 10.0, (6, 1))  # x 방향으로 100m 당 10m 상승
        slope = F.slope_deg(elev, 100.0)
        self.assertAlmostEqual(float(slope[2, 2]), np.degrees(np.arctan(0.1)), places=6)

    def test_relative_elevation_negative_in_pit(self) -> None:
        elev = np.full((7, 7), 50.0)
        elev[3, 3] = 20.0
        rel = F.relative_elevation(elev, 100.0, 300.0)
        self.assertLess(rel[3, 3], 0)
        self.assertGreater(rel[0, 0], 0)  # 구덩이를 포함한 창에서 평균이 낮아져 양수

    def test_fill_sinks_raises_pit_to_spill_level(self) -> None:
        elev = np.full((5, 5), 10.0)
        elev[2, 2] = 1.0
        filled = F.fill_sinks(elev)
        self.assertEqual(float(filled[2, 2]), 10.0)
        self.assertTrue(np.allclose(filled, 10.0))

    def test_flow_accumulation_collects_into_valley(self) -> None:
        # 가운데 열이 골짜기인 V 자 단면, 아래쪽으로 기울어진 판
        x = np.abs(np.arange(5) - 2) * 10.0
        y = np.arange(5)[::-1] * 5.0
        elev = x[None, :] + y[:, None]
        acc = F.flow_accumulation(F.fill_sinks(elev), 100.0)
        self.assertEqual(float(acc[4, 2]), 25.0)  # 출구 셀에 전부 모인다
        self.assertEqual(float(acc[0, 0]), 1.0)

    def test_twi_is_higher_at_outlet(self) -> None:
        x = np.abs(np.arange(5) - 2) * 10.0
        y = np.arange(5)[::-1] * 5.0
        elev = x[None, :] + y[:, None]
        twi, _ = F.twi(elev, 100.0)
        self.assertGreater(float(twi[4, 2]), float(twi[0, 0]))

    def test_nan_cells_stay_nan(self) -> None:
        elev = np.full((5, 5), 10.0)
        elev[0, :] = np.nan
        twi, acc = F.twi(elev, 100.0)
        self.assertTrue(np.isnan(acc[0, 0]) and np.isnan(twi[0, 0]))
        self.assertFalse(np.isnan(acc[4, 4]))


class RasterFractionTest(unittest.TestCase):
    def test_area_fraction_of_half_cell(self) -> None:
        lat = _lattice()
        poly = box(1000, 1950, 1100, 2000)  # 좌상단 셀의 위쪽 절반
        frac = F.area_fraction([poly], lat, sub=10)
        self.assertAlmostEqual(float(frac[0, 0]), 0.5, places=6)
        self.assertEqual(float(frac[1, 1]), 0.0)

    def test_value_fraction_and_mean_takes_deeper_polygon(self) -> None:
        lat = _lattice()
        gdf = gpd.GeoDataFrame(
            {"depth_m": [0.25, 1.25]},
            geometry=[box(1000, 1900, 1100, 2000), box(1000, 1950, 1100, 2000)],
            crs="EPSG:5179",
        )
        frac, mean = F.value_fraction_and_mean(gdf, "depth_m", lat, sub=10)
        self.assertAlmostEqual(float(frac[0, 0]), 1.0, places=6)
        self.assertAlmostEqual(float(mean[0, 0]), 0.5 * 0.25 + 0.5 * 1.25, places=6)

    def test_distance_to_polygon(self) -> None:
        lat = _lattice()
        dist = F.distance_to([box(1000, 1900, 1100, 2000)], lat, sub=10)
        self.assertEqual(float(dist[0, 0]), 0.0)
        self.assertAlmostEqual(float(dist[0, 2]), 155.0, delta=10.0)  # 중심(1250) − 폴리곤 오른쪽 경계(1100) ≈ 150

    def test_nearest_point_distance(self) -> None:
        lat = _lattice()
        pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy([1050.0], [1950.0]), crs="EPSG:5179")
        d = F.nearest_point_distance(lat, pts)
        self.assertEqual(float(d[0, 0]), 0.0)
        self.assertAlmostEqual(float(d[0, 1]), 100.0, places=6)


class SgisWideTest(unittest.TestCase):
    def test_pivot_and_rename(self) -> None:
        stats = pd.DataFrame({
            "year": [2024, 2024, 2023],
            "spatial_id": ["g1", "g1", "g1"],
            "variable": ["to_in_001", "to_ho_001", "to_in_001"],
            "value": [10, 3, 99],
        })
        wide = F.sgis_wide(stats, 2024, {"to_in_001": "pop_total", "to_ho_001": "houses"})
        self.assertEqual(wide.columns.tolist(), ["grid_id", "pop_total", "houses"])
        self.assertEqual(wide.loc[0, "pop_total"], 10)


if __name__ == "__main__":
    unittest.main()
