"""침수흔적 역할 분리·날짜·합집합 라벨과 실제 자료 회귀 검증."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from src.data import flood_traces as FT
from src.data.trace_events import _derive_event_fields, _parse_dates


class EventFieldsTest(unittest.TestCase):
    def test_float_years_use_four_digit_identifiers(self):
        """날짜 없는 실수형 연도를 네 자리 연도와 호우 식별자로 맞춘다."""
        import pandas as pd

        for year in ("2024.0", 2024.0, "2024.00", " 2024.0 ", " 2024 ", 2024, "2024"):
            with self.subTest(year=year):
                frame = pd.DataFrame({"F_SAT_YMD": [None], "F_YR": [year],
                                      "role": ["development"]})
                result, _ = _derive_event_fields(frame)
                self.assertEqual(result.event_year.tolist(), ["2024"])
                self.assertEqual(result.storm_id.tolist(), ["Y2024"])

    def test_normalized_years_confirm_date_repairs(self):
        """연도 정규화와 시작·종료일의 세 자리 연도 복원은 같은 표기를 허용한다."""
        import pandas as pd

        for year in ("2024.0", "2024.00", 2024.0, " 2024 "):
            with self.subTest(year=year):
                frame = pd.DataFrame({"F_SAT_YMD": ["024-09-21"],
                                      "F_END_YMD": ["024-09-22"], "F_YR": [year],
                                      "role": ["development"]})
                result, meta = _derive_event_fields(frame)
                self.assertEqual(result.event_year.tolist(), ["2024"])
                self.assertEqual(result.event_date.tolist(), [pd.Timestamp("2024-09-21")])
                self.assertEqual(result.event_end_date.tolist(), [pd.Timestamp("2024-09-22")])
                self.assertEqual(result.storm_id.tolist(), ["2024-09-21"])
                self.assertEqual(meta["start_date_typo_repairs"], 1)
                self.assertEqual(meta["end_date_typo_repairs"], 1)
                self.assertEqual(meta["date_typo_repairs"], 2)

    def test_date_formats_and_confirmed_repairs(self):
        import pandas as pd

        dates = pd.Series(["20220906", "2024-09-20", "024-09-21", "024-09-21",
                           "024-09-21", "024-02-30", "20240230", None])
        years = pd.Series([2022, 2024, 2024, 2023, None, 2024, 2024, None])
        parsed, repairs = _parse_dates(dates, years)
        self.assertEqual(parsed.iloc[:3].dt.strftime("%Y-%m-%d").tolist(),
                         ["2022-09-06", "2024-09-20", "2024-09-21"])
        self.assertTrue(parsed.iloc[3:].isna().all())
        self.assertEqual(repairs, 1)

    def test_only_f_yr_can_confirm_typo(self):
        import pandas as pd

        frame = pd.DataFrame({"F_SAT_YMD": ["024-09-21"], "FLDN_YR": ["2024"],
                              "role": ["holdout"]})
        result, meta = _derive_event_fields(frame)
        self.assertTrue(result.event_date.isna().all())
        self.assertEqual(result.storm_id.tolist(), ["Y2024"])
        self.assertEqual(meta["date_typo_repairs"], 0)

    def test_end_date_repairs_do_not_change_storm_start(self):
        import pandas as pd

        frame = pd.DataFrame({"F_SAT_YMD": ["2024-09-20"], "F_END_YMD": ["024-09-21"],
                              "F_YR": ["2024"], "role": ["holdout"]})
        result, meta = _derive_event_fields(frame)
        self.assertEqual(result.event_end_date.dt.strftime("%Y-%m-%d").tolist(), ["2024-09-21"])
        self.assertEqual(result.storm_id.tolist(), ["2024-09-20"])
        self.assertEqual(meta["date_typo_repairs"], 1)
        self.assertEqual(meta["start_date_typo_repairs"], 0)
        self.assertEqual(meta["end_date_typo_repairs"], 1)

    def test_storms_use_adjacent_dates_within_each_role(self):
        import pandas as pd

        frame = pd.DataFrame({
            "F_SAT_YMD": ["20240926", "20240920", "20240923", "20240930",
                          "20240921", None, None],
            "F_YR": ["2024"] * 6 + [None],
            "role": ["holdout"] * 4 + ["development", "holdout", "holdout"],
            "source_id": ["a", "b", "c", "a", "a", "a", "a"],
        })
        result, _ = _derive_event_fields(frame)
        self.assertEqual(result.storm_id.iloc[:6].tolist(),
                         ["2024-09-20"] * 3 + ["2024-09-30", "2024-09-21", "Y2024"])
        self.assertTrue(pd.isna(result.storm_id.iloc[6]))


class RegistryTest(unittest.TestCase):
    def test_role_filter_and_metadata_exclusion(self):
        registry = {
            "dev": {"role": "development", "paths": ["dev/*"]},
            "hold": {"role": "holdout", "paths": ["hold/*"]},
        }
        with patch.object(Path, "glob", return_value=iter([
            Path("/synthetic/dev/trace.gpkg"), Path("/synthetic/dev/collection_metrics.json"),
        ])) as glob, patch.object(Path, "is_file", return_value=True):
            paths = FT.files_for("development", registry=registry, root=Path("/synthetic"))
        self.assertEqual(paths, [Path("/synthetic/dev/trace.gpkg")])
        glob.assert_called_once_with("dev/*")
        with patch.object(Path, "glob", return_value=iter([Path("/synthetic/hold/trace.shp")])):
            with patch.object(Path, "is_file", return_value=True):
                self.assertEqual(FT.files_for("holdout", registry=registry, root=Path("/synthetic")),
                                 [Path("/synthetic/hold/trace.shp")])

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(ValueError):
            FT.files_for("developmnt")

    def test_holdout_wrapper_uses_only_holdout_files(self):
        with patch.object(FT, "files_for", return_value=[Path("holdout.shp")]) as files:
            with patch.object(FT, "load", return_value=("traces", {})) as load:
                self.assertEqual(FT.load_holdout(), ("traces", {}))
        files.assert_called_once_with("holdout")
        load.assert_called_once_with([Path("holdout.shp")], crs="EPSG:5179")


class GeometryTest(unittest.TestCase):
    def test_dated_duplicate_survives_richer_undated_record(self):
        """속성이 많은 날짜 없는 중복보다 날짜와 호우 식별자를 보존한다."""
        from hashlib import sha256
        import geopandas as gpd
        import pandas as pd
        from shapely.geometry import box

        geometry = box(0, 0, 1, 1)
        frame = gpd.GeoDataFrame({
            "F_SAT_YMD": ["20250719", None], "F_YR": ["2025"] * 2,
            "role": ["development"] * 2, "depth": [None, 1],
            "landuse": [None, "도심"], "note": [None, "수심 레이어"],
        }, geometry=[geometry] * 2, crs=5179)
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                ordered = frame.iloc[::-1].copy() if reverse else frame.copy()
                derived, _ = _derive_event_fields(ordered.copy())
                result, dropped = FT._drop_duplicate_geometries(derived)
                self.assertEqual(dropped, 1)
                self.assertEqual(result.event_date.tolist(), [pd.Timestamp("2025-07-19")])
                self.assertEqual(result.storm_id.tolist(), ["2025-07-19"])
                with patch.object(FT, "_read_vectors", return_value=(ordered, {}, {})):
                    loaded, _ = FT.load([Path("/synthetic/duplicate.shp")])
                expected = sha256(b"development|2025-07-19|" + geometry.normalize().wkb).hexdigest()
                self.assertEqual(loaded.object_id.tolist(), [expected])

    def test_union_sum_and_nondefault_indices(self):
        import geopandas as gpd
        import numpy as np
        from shapely.geometry import box

        grid = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10)],
                                index=["a", "b"], crs=5179)
        traces = gpd.GeoDataFrame(geometry=[box(0, 0, 0.8, 10), box(0, 0, 0.8, 10)],
                                  index=[42, 42], crs=5179)
        union, union_area = FT.label_grid(grid, traces)
        summed, sum_area = FT.label_grid(grid, traces, mode="sum")
        np.testing.assert_array_equal(union, [False, False])
        np.testing.assert_array_equal(summed, [True, False])
        np.testing.assert_allclose(union_area, [0.08, 0])
        np.testing.assert_allclose(sum_area, [0.16, 0])

    def test_threshold_is_strict_and_empty_traces_are_negative(self):
        import geopandas as gpd
        from shapely.geometry import box

        grid = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=5179)
        traces = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 10)], crs=5179)
        self.assertFalse(FT.label_grid(grid, traces)[0][0])
        self.assertFalse(FT.label_grid(grid, traces.iloc[:0])[0][0])
        with self.assertRaises(ValueError):
            FT.label_grid(grid, traces, mode="invalid")

    def test_load_preserves_provenance_and_separate_events(self):
        import geopandas as gpd
        from shapely.geometry import Polygon, box

        dev, hold = Path("/synthetic/dev.shp"), Path("/synthetic/hold.shp")
        frame = gpd.GeoDataFrame({
            "F_SAT_YMD": ["20240920", "20240920", "20240724", "024-09-21"],
            "F_YR": ["2024"] * 4, "A_CHA_NM": ["도심_상업지"] * 4,
        }, geometry=[box(0, 0, 1, 1)] * 3 + [Polygon([(2, 0), (3, 1), (2, 1), (3, 0), (2, 0)])],
            crs=5179)
        with patch.object(FT, "registered_files", return_value=iter([
            (dev, "dev", "development"), (hold, "hold", "holdout"),
        ])), patch("geopandas.read_file", side_effect=[frame.copy(), frame.iloc[:1].copy()]):
            traces, meta = FT.load([dev, hold])
        self.assertEqual(len(traces), 4)
        self.assertEqual(meta["duplicate_geometries_dropped"], 1)
        self.assertEqual(meta["invalid_fixed"], 1)
        self.assertEqual(meta["date_typo_repairs"], 1)
        self.assertTrue(traces.geometry.is_valid.all())
        self.assertTrue(traces.object_id.is_unique)
        self.assertEqual(set(traces.source_record_id), {"dev.shp#1", "dev.shp#3", "dev.shp#4", "hold.shp#1"})
        self.assertEqual(set(traces.land_use), {"도심_상업지"})
        self.assertEqual(set(traces.role), {"development", "holdout"})
        self.assertEqual(set(traces.source_id), {"dev", "hold"})

    def test_undated_duplicate_requires_one_matching_storm(self):
        import geopandas as gpd
        from shapely.geometry import box

        frame = gpd.GeoDataFrame({
            "F_SAT_YMD": ["20250719", None, "20250920"],
            "F_YR": ["2025"] * 3, "role": ["development"] * 3,
        }, geometry=[box(0, 0, 1, 1)] * 3, crs=5179)
        single, _ = _derive_event_fields(frame.iloc[:2].copy())
        deduplicated, dropped = FT._drop_duplicate_geometries(single)
        self.assertEqual(dropped, 1)
        self.assertEqual(deduplicated.storm_id.tolist(), ["2025-07-19"])
        ambiguous, _ = _derive_event_fields(frame)
        deduplicated, dropped = FT._drop_duplicate_geometries(ambiguous)
        self.assertEqual(dropped, 0)
        self.assertEqual(len(deduplicated), 3)


class RealDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import geopandas as gpd

        registry = FT.load_registry()
        required = [FT.PROJECT_ROOT / pattern for source in registry.values()
                    if source["role"] == "development" for pattern in source["paths"]]
        grid_path = FT.PROJECT_ROOT / "data/processed/layers/layer1_flood.gpkg"
        if not grid_path.is_file() or not all(path.is_file() for path in required):
            raise unittest.SkipTest("실제 침수흔적 정본 또는 기존 격자 자료가 없다")
        cls.grid = gpd.read_file(grid_path)
        cls.development, cls.development_meta = FT.load(FT.files_for("development"))

    def test_development_files_match_original_sources(self):
        raw = FT.PROJECT_ROOT / "data/raw/flood_traces"
        original = []
        for directory in ["changwon_info_disclosure_20260916", "safetydata_dssp_if_00117"]:
            original.extend(FT.find_files(raw / directory)[0])
        self.assertEqual(FT.files_for("development"), sorted(original))
        self.assertEqual(set(self.development.role), {"development"})

    def test_development_labels_match_frozen_grid(self):
        import numpy as np

        labels, _ = FT.label_grid(self.grid, self.development, min_overlap=0.10, mode="union")
        self.assertEqual(int(labels.sum()), 642)
        np.testing.assert_array_equal(labels, self.grid.trace_label.to_numpy())
        print(f"\ndevelopment: polygons={len(self.development)}, positive={int(labels.sum())}, trace_label_mismatches=0")
        years = ["2006", "2012", "2014", "2016", "2019", "2025"]
        self.assertEqual(sorted(c for c in self.grid if c.startswith("trace_ev_")),
                         [f"trace_ev_{year}" for year in years])
        for year in years:
            with self.subTest(year=year):
                labels, _ = FT.label_grid(self.grid, self.development[self.development.event_year == year])
                np.testing.assert_array_equal(labels, self.grid[f"trace_ev_{year}"].to_numpy())
                print(f"trace_ev_{year}: positive={int(labels.sum())}, mismatches=0")


@unittest.skipUnless(os.environ.get("CHANGWON_HOLDOUT_TESTS") == "1",
                     "실제 홀드아웃 검증은 CHANGWON_HOLDOUT_TESTS=1일 때만 실행한다")
class HoldoutDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import geopandas as gpd

        registry = FT.load_registry()
        required = [FT.PROJECT_ROOT / pattern for source in registry.values()
                    if source["role"] == "holdout" for pattern in source["paths"]]
        grid_path = FT.PROJECT_ROOT / "data/processed/layers/layer1_flood.gpkg"
        if not grid_path.is_file() or not all(path.is_file() for path in required):
            raise unittest.SkipTest("실제 침수흔적 정본 또는 기존 격자 자료가 없다")
        cls.grid = gpd.read_file(grid_path)
        cls.holdout, cls.holdout_meta = FT.load_holdout()

    def test_holdout_inventory_and_labels(self):
        self.assertFalse(set(FT.files_for("development")) & set(FT.files_for("holdout")))
        expected = {"2022-09-06": 5, "2023-08-10": 3, "2024-07-24": 5, "2024-09-20": 183}
        counts = self.holdout.groupby("storm_id").size().to_dict()
        self.assertEqual(len(FT.files_for("holdout")), 7)
        self.assertEqual(len(self.holdout), 196)
        self.assertEqual(self.holdout_meta["n_polygons"], 196)
        self.assertEqual(self.holdout_meta["n_storms"], 4)
        self.assertEqual(counts, expected)
        self.assertEqual(self.holdout.crs.to_epsg(), 5179)
        self.assertEqual(set(self.holdout.role), {"holdout"})
        self.assertTrue(self.holdout.geometry.is_valid.all())
        self.assertTrue(self.holdout.object_id.is_unique)
        self.assertEqual(self.holdout_meta["date_typo_repairs"], 2)
        self.assertEqual(self.holdout_meta["start_date_typo_repairs"], 0)
        self.assertEqual(self.holdout_meta["end_date_typo_repairs"], 2)
        self.assertAlmostEqual(self.holdout_meta["union_area_km2"], 9.55, delta=0.01)
        labels, _ = FT.label_grid(self.grid, self.holdout, min_overlap=0.10, mode="union")
        self.assertEqual(int(labels.sum()), 1267)
        print(f"\nholdout: polygons={len(self.holdout)}, storms={counts}, "
              f"union_area_km2={self.holdout_meta['union_area_km2']}, positive={int(labels.sum())}, "
              f"invalid_fixed={self.holdout_meta['invalid_fixed']}, "
              f"date_typo_repairs={self.holdout_meta['date_typo_repairs']}")


if __name__ == "__main__":
    unittest.main()
