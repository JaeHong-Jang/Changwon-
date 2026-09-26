from __future__ import annotations

import unittest

import pandas as pd

from src.data.stations import merge_pump_sources, station_table


def _stations(**overrides) -> pd.DataFrame:
    base = {
        "station_code": [1, 2, 3],
        "station_name": ["가", "나", "다"],
        "station_type": ["rain", "rain", "water_level"],
        "lat": [35.2, 35.3, None],
        "lon": [128.6, 128.7, None],
        "source": ["카카오맵"] * 3,
        "reviewed": ["Y", "N", "N"],
        "note": ["", "근사점", None],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class StationTableTest(unittest.TestCase):
    def test_coverage_proxy_and_counts(self) -> None:
        table, m = station_table(_stations())
        self.assertEqual(m["n_stations"], 3)
        self.assertEqual(m["n_filled"], 2)
        self.assertAlmostEqual(m["coord_coverage"], 0.6667, places=4)
        self.assertEqual(m["proxy_codes"], [2, 3])
        self.assertTrue(table.loc[0, "reviewed"] and not table.loc[0, "is_proxy"])
        self.assertEqual(table.loc[2, "note"], "")

    def test_swapped_lat_lon_is_flagged(self) -> None:
        _, m = station_table(_stations(lat=[128.6, 35.3, None], lon=[35.2, 128.7, None]))
        self.assertEqual(m["out_of_box_codes"], [1])

    def test_duplicate_code_is_flagged(self) -> None:
        _, m = station_table(_stations(station_code=[1, 1, 3]))
        self.assertEqual(m["duplicate_codes"], [1])

    def test_missing_column_raises(self) -> None:
        with self.assertRaises(ValueError):
            station_table(_stations().drop(columns=["reviewed"]))


class MergePumpSourcesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.official = pd.DataFrame({
            "시설명": ["A배수장", "B배수장"],
            "소재지도로명주소": ["도로1", "도로2"],
            "소재지지번주소": ["지번1", "지번2"],
            "위도": [35.2000, 35.2100],
            "경도": [128.6000, 128.6100],
            "설치년도": [1999, 2005],
            "설치목적": ["침수예방", "침수예방"],
            "데이터기준일자": ["2026-07-31"] * 2,
        })

    def test_official_wins_and_far_geocoded_is_added(self) -> None:
        geocoded = pd.DataFrame({
            "pump_name": ["A펌프장", "C펌프장"],
            "address": ["지번1", "지번3"],
            "lat": [35.20001, 35.2500],     # A: 공식 좌표와 ~1 m, C: 공식 목록에 없음
            "lon": [128.60001, 128.6500],
            "source": ["카카오맵"] * 2,
            "reviewed": ["Y", "Y"],
            "note": ["", ""],
        })
        merged, m = merge_pump_sources(self.official, geocoded)
        self.assertEqual(m["n_official"], 2)
        self.assertEqual(m["n_matched_to_official"], 1)
        self.assertEqual(m["added_names"], ["C펌프장"])
        self.assertEqual(m["n_pumps"], 3)
        self.assertEqual(merged["pump_id"].tolist(), [1, 2, 3])
        self.assertEqual(merged["source_kind"].tolist(), ["official", "official", "geocoded"])
        self.assertEqual(merged.crs.to_string(), "EPSG:5179")

    def test_unreviewed_addition_is_counted(self) -> None:
        geocoded = pd.DataFrame({
            "pump_name": ["C펌프장"], "address": ["지번3"], "lat": [35.25], "lon": [128.65],
            "source": ["카카오맵"], "reviewed": ["N"], "note": [""],
        })
        _, m = merge_pump_sources(self.official, geocoded)
        self.assertEqual(m["n_added_unreviewed"], 1)

    def test_missing_official_column_raises(self) -> None:
        with self.assertRaises(ValueError):
            merge_pump_sources(self.official.drop(columns=["위도"]), pd.DataFrame(columns=["pump_name", "lat", "lon", "reviewed", "note"]))


if __name__ == "__main__":
    unittest.main()
