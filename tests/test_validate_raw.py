from __future__ import annotations

import tempfile
import unittest
import struct
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import yaml

from src.data.validate_raw import validate_contract


class ValidateRawTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_contract(self, datasets: dict) -> Path:
        path = self.root / "contracts.yaml"
        path.write_text(
            yaml.safe_dump(
                {"version": 1, "raw_root": "raw", "datasets": datasets},
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_headerless_csv_keeps_first_record(self) -> None:
        (self.raw / "grid.csv").write_text(
            "2024,가가000001,to_in_001,5\n2024,가가000002,to_in_001,7\n",
            encoding="utf-8",
        )
        contract = self.write_contract(
            {
                "grid": {
                    "kind": "csv",
                    "description": "headerless fixture",
                    "glob": "grid.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": False,
                    "columns": ["year", "spatial_id", "variable", "value"],
                    "exact_rows_per_file": 2,
                    "key_columns": ["year", "spatial_id", "variable"],
                    "allowed_values": {"year": [2024]},
                    "variable_column": "variable",
                    "variable_regex": "^to_in_001$",
                    "quality": {
                        "max_duplicate_key_rows": 0,
                        "duplicate_severity": "error",
                    },
                }
            }
        )

        report = validate_contract(contract, raw_root_override=self.raw)

        self.assertEqual("pass", report["status"])
        self.assertEqual(2, report["datasets"][0]["metrics"]["total_rows"])

    def test_warning_gate_is_stricter_than_structure_gate(self) -> None:
        (self.raw / "rain.csv").write_text(
            "station,date,1h\nA,2026-02-30,-1\nA,2026-02-30,-1\n",
            encoding="utf-8",
        )
        contract = self.write_contract(
            {
                "rain": {
                    "kind": "csv",
                    "description": "quality fixture",
                    "glob": "rain.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": True,
                    "required_columns": ["station", "date", "1h"],
                    "key_columns": ["station", "date"],
                    "quality": {
                        "max_exact_duplicate_rows": 0,
                        "max_duplicate_key_rows": 0,
                        "duplicate_severity": "warning",
                        "date_column": "date",
                        "date_format": "%Y-%m-%d",
                        "max_invalid_dates": 0,
                        "date_severity": "warning",
                        "numeric_columns_regex": "^1h$",
                        "min_numeric_value": 0,
                        "range_severity": "warning",
                    },
                }
            }
        )

        structure_report = validate_contract(contract, raw_root_override=self.raw, fail_on="error")
        strict_report = validate_contract(contract, raw_root_override=self.raw, fail_on="warning")

        self.assertEqual("pass", structure_report["status"])
        self.assertEqual("fail", strict_report["status"])
        codes = {finding["code"] for finding in strict_report["datasets"][0]["findings"]}
        self.assertTrue({"exact_duplicates", "duplicate_keys", "invalid_dates", "numeric_range"} <= codes)

    def test_lfs_pointer_is_a_structural_error(self) -> None:
        (self.raw / "tile.img").write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:0123456789abcdef\nsize 100\n",
            encoding="ascii",
        )
        contract = self.write_contract(
            {
                "dem": {
                    "kind": "raster",
                    "description": "pointer fixture",
                    "glob": "*.img",
                    "expected_files": 1,
                    "magic_ascii": "EHFA_HEADER_TAG",
                }
            }
        )

        report = validate_contract(contract, raw_root_override=self.raw, fail_on="error")

        self.assertEqual("fail", report["status"])
        self.assertEqual("lfs_pointer", report["datasets"][0]["findings"][0]["code"])

    def test_cross_file_duplicate_and_numeric_parse_failure_are_detected(self) -> None:
        (self.raw / "part1.csv").write_text("2024,a,value,1\n", encoding="utf-8")
        (self.raw / "part2.csv").write_text("2024,a,value,oops\n", encoding="utf-8")
        contract = self.write_contract(
            {
                "parts": {
                    "kind": "csv",
                    "description": "cross-file fixture",
                    "glob": "part*.csv",
                    "expected_files": 2,
                    "encoding": "utf-8",
                    "header": False,
                    "columns": ["year", "spatial_id", "variable", "value"],
                    "key_columns": ["year", "spatial_id", "variable"],
                    "quality": {
                        "max_duplicate_key_rows": 0,
                        "max_cross_file_duplicate_keys": 0,
                        "duplicate_severity": "error",
                        "numeric_columns_regex": "^value$",
                        "max_numeric_parse_failures": 0,
                        "numeric_parse_severity": "error",
                    },
                }
            }
        )

        report = validate_contract(contract, raw_root_override=self.raw)

        self.assertEqual("fail", report["status"])
        codes = {finding["code"] for finding in report["datasets"][0]["findings"]}
        self.assertIn("cross_file_duplicate_keys", codes)
        self.assertIn("numeric_parse", codes)

    def test_warning_fingerprint_waiver_must_match(self) -> None:
        (self.raw / "rain.csv").write_text(
            "station,date,1h\nA,2026-01-01,-1\n",
            encoding="utf-8",
        )
        contract = self.write_contract(
            {
                "rain": {
                    "kind": "csv",
                    "description": "waiver fixture",
                    "glob": "rain.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": True,
                    "quality": {
                        "numeric_columns_regex": "^1h$",
                        "min_numeric_value": 0,
                        "range_severity": "warning",
                    },
                }
            }
        )
        initial = validate_contract(
            contract,
            raw_root_override=self.raw,
            fail_on="warning",
        )
        finding = initial["datasets"][0]["findings"][0]
        waiver_path = self.root / "waivers.yaml"
        waiver_path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "waivers": [
                        {
                            "fingerprint": finding["fingerprint"],
                            "dataset": "rain",
                            "code": "numeric_range",
                            "owner": "test",
                            "reason": "fixture",
                            "cleaning_rule": "quarantine",
                            "expires_on": "2099-01-01",
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        waived = validate_contract(
            contract,
            raw_root_override=self.raw,
            fail_on="warning",
            waiver_path=waiver_path,
        )

        self.assertEqual("pass", waived["status"])
        self.assertEqual(1, waived["finding_counts"]["waived"])

        (self.raw / "rain.csv").write_text(
            "station,date,1h\nA,2026-01-01,-2\n",
            encoding="utf-8",
        )
        changed = validate_contract(
            contract,
            raw_root_override=self.raw,
            fail_on="warning",
            waiver_path=waiver_path,
        )
        self.assertEqual("fail", changed["status"])
        self.assertEqual(1, changed["finding_counts"]["waiver_errors"])

    def test_waiver_requires_complete_valid_metadata(self) -> None:
        (self.raw / "rain.csv").write_text(
            "station,date,1h\nA,2026-01-01,-1\n",
            encoding="utf-8",
        )
        contract = self.write_contract(
            {
                "rain": {
                    "kind": "csv",
                    "description": "invalid waiver fixture",
                    "glob": "rain.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": True,
                    "quality": {
                        "numeric_columns_regex": "^1h$",
                        "min_numeric_value": 0,
                        "range_severity": "warning",
                    },
                }
            }
        )
        initial = validate_contract(contract, raw_root_override=self.raw, fail_on="warning")
        fingerprint = initial["datasets"][0]["findings"][0]["fingerprint"]
        waiver_path = self.root / "waivers.yaml"
        waiver_path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "waivers": [
                        {
                            "fingerprint": fingerprint,
                            "dataset": "rain",
                            "code": "numeric_range",
                            "expires_on": "not-a-date",
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        report = validate_contract(
            contract,
            raw_root_override=self.raw,
            fail_on="warning",
            waiver_path=waiver_path,
        )

        self.assertEqual("fail", report["status"])
        self.assertEqual(1, report["finding_counts"]["waiver_errors"])
        self.assertIn("missing required fields", report["waivers"]["invalid"][0]["errors"][0])

    def test_duplicate_waiver_fingerprint_is_rejected(self) -> None:
        (self.raw / "rain.csv").write_text(
            "station,date,1h\nA,2026-01-01,-1\n",
            encoding="utf-8",
        )
        contract = self.write_contract(
            {
                "rain": {
                    "kind": "csv",
                    "description": "duplicate waiver fixture",
                    "glob": "rain.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": True,
                    "quality": {
                        "numeric_columns_regex": "^1h$",
                        "min_numeric_value": 0,
                        "range_severity": "warning",
                    },
                }
            }
        )
        initial = validate_contract(contract, raw_root_override=self.raw, fail_on="warning")
        finding = initial["datasets"][0]["findings"][0]
        entry = {
            "fingerprint": finding["fingerprint"],
            "dataset": "rain",
            "code": "numeric_range",
            "owner": "test",
            "reason": "fixture",
            "cleaning_rule": "quarantine",
            "expires_on": "2099-01-01",
        }
        waiver_path = self.root / "waivers.yaml"
        waiver_path.write_text(
            yaml.safe_dump({"version": 1, "waivers": [entry, entry]}, sort_keys=False),
            encoding="utf-8",
        )

        report = validate_contract(
            contract,
            raw_root_override=self.raw,
            fail_on="warning",
            waiver_path=waiver_path,
        )

        self.assertEqual("fail", report["status"])
        self.assertEqual(1, report["finding_counts"]["waiver_errors"])
        self.assertEqual("duplicate fingerprint", report["waivers"]["invalid"][0]["errors"][0])

    def test_null_waiver_expiry_is_rejected(self) -> None:
        (self.raw / "rain.csv").write_text("value\n-1\n", encoding="utf-8")
        contract = self.write_contract(
            {
                "rain": {
                    "kind": "csv",
                    "description": "null expiry fixture",
                    "glob": "rain.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": True,
                    "quality": {
                        "numeric_columns_regex": "^value$",
                        "min_numeric_value": 0,
                        "range_severity": "warning",
                    },
                }
            }
        )
        initial = validate_contract(contract, raw_root_override=self.raw, fail_on="warning")
        finding = initial["datasets"][0]["findings"][0]
        waiver = {
            "fingerprint": finding["fingerprint"],
            "dataset": "rain",
            "code": "numeric_range",
            "owner": "test",
            "reason": "fixture",
            "cleaning_rule": "quarantine",
            "expires_on": None,
        }
        waiver_path = self.root / "waivers.yaml"
        waiver_path.write_text(
            yaml.safe_dump({"version": 1, "waivers": [waiver]}, sort_keys=False),
            encoding="utf-8",
        )

        report = validate_contract(
            contract,
            raw_root_override=self.raw,
            fail_on="warning",
            waiver_path=waiver_path,
        )

        self.assertEqual("fail", report["status"])
        self.assertEqual(1, report["finding_counts"]["waiver_errors"])
        self.assertIn("non-empty ISO date", report["waivers"]["invalid"][0]["errors"][0])

    def test_expired_waiver_is_rejected(self) -> None:
        (self.raw / "rain.csv").write_text("value\n-1\n", encoding="utf-8")
        contract = self.write_contract(
            {
                "rain": {
                    "kind": "csv",
                    "description": "expired waiver fixture",
                    "glob": "rain.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": True,
                    "quality": {
                        "numeric_columns_regex": "^value$",
                        "min_numeric_value": 0,
                        "range_severity": "warning",
                    },
                }
            }
        )
        initial = validate_contract(contract, raw_root_override=self.raw, fail_on="warning")
        finding = initial["datasets"][0]["findings"][0]
        waiver = {
            "fingerprint": finding["fingerprint"],
            "dataset": "rain",
            "code": "numeric_range",
            "owner": "test",
            "reason": "fixture",
            "cleaning_rule": "quarantine",
            "expires_on": "2000-01-01",
        }
        waiver_path = self.root / "waivers.yaml"
        waiver_path.write_text(
            yaml.safe_dump({"version": 1, "waivers": [waiver]}, sort_keys=False),
            encoding="utf-8",
        )

        report = validate_contract(
            contract,
            raw_root_override=self.raw,
            fail_on="warning",
            waiver_path=waiver_path,
        )

        self.assertEqual("fail", report["status"])
        self.assertEqual(1, report["finding_counts"]["waiver_errors"])
        self.assertEqual([finding["fingerprint"]], report["waivers"]["expired"])

    def test_temporal_coverage_counts_only_days_with_valid_values(self) -> None:
        (self.raw / "level.csv").write_text(
            "station,date,1h,2h\nA,2026-01-01,9999,9999\nA,2026-01-02,1.2,9999\n",
            encoding="utf-8",
        )
        contract = self.write_contract(
            {
                "level": {
                    "kind": "csv",
                    "description": "valid-day coverage fixture",
                    "glob": "level.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": True,
                    "quality": {
                        "date_column": "date",
                        "date_format": "%Y-%m-%d",
                        "numeric_columns_regex": "^[12]h$",
                        "min_numeric_value": -100,
                        "max_numeric_value": 1000,
                        "sentinel_values": [9999],
                    },
                    "coverage": {
                        "group_columns": ["station"],
                        "date_column": "date",
                        "date_format": "%Y-%m-%d",
                        "numeric_columns_regex": "^[12]h$",
                        "sentinel_values": [9999],
                        "min_valid_values_per_day": 1,
                        "analysis_start": "2026-01-01",
                        "analysis_end": "2026-01-02",
                        "min_coverage_ratio": 1.0,
                        "min_groups_meeting_coverage": 1,
                        "severity": "warning",
                    },
                }
            }
        )

        report = validate_contract(
            contract,
            raw_root_override=self.raw,
            fail_on="warning",
        )

        coverage = report["datasets"][0]["metrics"]["coverage"]
        self.assertEqual("fail", report["status"])
        self.assertEqual(2, coverage["groups"][0]["row_days"])
        self.assertEqual(1, coverage["groups"][0]["valid_days"])
        self.assertEqual(0.5, coverage["groups"][0]["coverage_ratio"])
        self.assertEqual(0, report["datasets"][0]["metrics"]["values_above_max"])

    def test_aggregate_consistency_mismatch_is_rejected(self) -> None:
        (self.raw / "sgis.csv").write_text(
            "2024,A,total,10\n2024,A,male,4\n2024,A,female,5\n",
            encoding="utf-8",
        )
        contract = self.write_contract(
            {
                "sgis": {
                    "kind": "csv",
                    "description": "aggregate consistency fixture",
                    "glob": "sgis.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": False,
                    "columns": ["year", "spatial_id", "variable", "value"],
                    "consistency": {
                        "group_columns": ["year", "spatial_id"],
                        "variable_column": "variable",
                        "value_column": "value",
                        "total_variable": "total",
                        "part_variables": ["male", "female"],
                        "min_complete_ratio": 1.0,
                        "max_abs_difference": 0,
                        "severity": "error",
                    },
                }
            }
        )

        report = validate_contract(contract, raw_root_override=self.raw)

        self.assertEqual("fail", report["status"])
        codes = {finding["code"] for finding in report["datasets"][0]["findings"]}
        self.assertIn("aggregate_consistency", codes)

    def test_semantic_crs_mismatch_is_rejected(self) -> None:
        shp_header = bytearray(100)
        shp_header[:4] = struct.pack(">i", 9994)
        (self.raw / "shape.shp").write_bytes(shp_header)
        (self.raw / "shape.prj").write_text("FAKE_WKT", encoding="utf-8")
        contract = self.write_contract(
            {
                "shape": {
                    "kind": "shapefile",
                    "description": "semantic CRS fixture",
                    "glob": "*.shp",
                    "expected_files": 1,
                    "required_sidecars": [".prj"],
                    "crs_reader": "pyproj",
                    "expected_crs": "EPSG:5179",
                }
            }
        )

        class FakeParsedCrs:
            @staticmethod
            def to_epsg() -> int:
                return 5186

        class FakeCrs:
            @staticmethod
            def from_wkt(_: str) -> FakeParsedCrs:
                return FakeParsedCrs()

        with patch.dict(sys.modules, {"pyproj": types.SimpleNamespace(CRS=FakeCrs)}):
            report = validate_contract(contract, raw_root_override=self.raw)

        self.assertEqual("fail", report["status"])
        codes = {finding["code"] for finding in report["datasets"][0]["findings"]}
        self.assertIn("crs_semantic", codes)

    def test_lfs_pointer_in_shapefile_sidecar_is_rejected(self) -> None:
        shp_header = bytearray(100)
        shp_header[:4] = struct.pack(">i", 9994)
        (self.raw / "shape.shp").write_bytes(shp_header)
        (self.raw / "shape.dbf").write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:0123456789abcdef\nsize 100\n",
            encoding="ascii",
        )
        contract = self.write_contract(
            {
                "shape": {
                    "kind": "shapefile",
                    "description": "sidecar fixture",
                    "glob": "*.shp",
                    "expected_files": 1,
                    "required_sidecars": [".dbf"],
                }
            }
        )

        report = validate_contract(contract, raw_root_override=self.raw)

        self.assertEqual("fail", report["status"])
        codes = {finding["code"] for finding in report["datasets"][0]["findings"]}
        self.assertIn("lfs_pointer", codes)

    def test_raster_open_failure_becomes_finding(self) -> None:
        (self.raw / "tile.img").write_bytes(b"EHFA_HEADER_TAG" + b"\0" * 32)
        contract = self.write_contract(
            {
                "dem": {
                    "kind": "raster",
                    "description": "raster fixture",
                    "glob": "*.img",
                    "expected_files": 1,
                    "magic_ascii": "EHFA_HEADER_TAG",
                    "metadata_reader": "rasterio",
                }
            }
        )
        fake_rasterio = types.SimpleNamespace(
            open=lambda _: (_ for _ in ()).throw(RuntimeError("broken raster"))
        )

        with patch.dict(sys.modules, {"rasterio": fake_rasterio}):
            report = validate_contract(contract, raw_root_override=self.raw)

        self.assertEqual("fail", report["status"])
        codes = {finding["code"] for finding in report["datasets"][0]["findings"]}
        self.assertIn("raster_open", codes)

    def test_cli_writes_evidence_and_returns_zero(self) -> None:
        (self.raw / "ok.csv").write_text("key,value\na,1\n", encoding="utf-8")
        contract = self.write_contract(
            {
                "ok": {
                    "kind": "csv",
                    "description": "cli fixture",
                    "glob": "ok.csv",
                    "expected_files": 1,
                    "encoding": "utf-8",
                    "header": True,
                    "required_columns": ["key", "value"],
                }
            }
        )
        output = self.root / "evidence.json"

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.data.validate_raw",
                "--contracts",
                str(contract),
                "--raw-root",
                str(self.raw),
                "--output",
                str(output),
                "--fail-on",
                "error",
                "--waivers",
                str(self.root / "no-waivers.yaml"),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(output.exists())
        evidence = yaml.safe_load(output.read_text(encoding="utf-8"))
        self.assertEqual(64, len(evidence["validator_sha256"]))
        self.assertIn("git_dirty", evidence)
        self.assertIn("git_diff_sha256", evidence)
        self.assertIsNone(evidence["waiver_sha256"])


if __name__ == "__main__":
    unittest.main()
