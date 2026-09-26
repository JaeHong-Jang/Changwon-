"""M6 실행 비교·라벨 감사 비교·연대표·기탁 목록 단위 검사 (합성 자료, 홀드아웃 없음)."""

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.repro import run_compare as RC
from src.repro.audit_check import compare_audit_summary, compare_polygon_tables
from src.repro.chronology import parse_time, resolve, resolve_all
from src.repro.deposit_manifest import build_manifest, classify, summarise


def metrics(values: list[float], roles: tuple[str, ...] = ("pre_registered", "post_hoc")) -> pd.DataFrame:
    """metrics.csv 모양의 두 행짜리 표를 만든다."""
    # 점수 두 개, 격자 게이트 AUC 한 지표씩 둔다
    return pd.DataFrame({
        "score": ["L1", "z"], "unit": "cell_gate", "stratum": "ALL", "storm": "ALL",
        "metric": "observed-label_auc", "value": values, "ci_lo": [0.1, 0.2], "ci_hi": [0.9, 0.95],
        "n_units": [1267, 1267], "polygon_subset": "all", "n_polygons": [196, 196],
        "score_role": list(roles), "post_hoc_design": [False, True], "confirmatory": [True, False],
        "run_id": "r"})


def summary(bg: int = 72953, auc: float = 0.4357) -> dict:
    """holdout_eval summary.json 의 판정 대상 키를 가진 작은 요약을 만든다."""
    # 게이트·메타 키만 채운다
    return {"run_id": "x", "gates": {"L1": {"evaluable": True, "auc_cell": auc}},
            "development_gates": {"L1": {"auc_cell": 0.7}}, "holdout": {"n_traces": 196},
            "polygons_by_storm": {"a": 1}, "polygons_by_subset": {"all": 196}, "n_background_cells": bg,
            "raw_sha256": {"h": {"f": "1"}}, "score_roles": {}, "gate_definition": {"auc_min": 0.7},
            "models": {"v2": {"model_sha256": "m"}}, "versions": {"python": "3.12"}, "code_sha256": {"a": "1"}}


class RunCompareTest(unittest.TestCase):
    """J1~J3 와 판정 규칙을 확인한다."""

    def test_identical_is_reproduced(self):
        """같은 표·요약은 재현이다."""
        # 기준 해시를 같은 요약에서 만든다
        s = summary()
        j2, rows = RC.compare_metrics(metrics([0.4357, 0.7348]), metrics([0.4357, 0.7348]))
        sums = RC.compare_summaries(s, s, RC.gate_hashes(s))
        self.assertEqual(RC.verdict(sums["J1"]["pass"], j2, sums["J3"]["pass"]), "reproduced")
        self.assertEqual(len(rows), 0)

    def test_float_noise_and_mismatch(self):
        """1e-9 이하 차이는 부동소수 차이, 그보다 크면 불일치다."""
        # 값 하나만 조금씩 바꾼다
        base = metrics([0.4357, 0.7348])
        j2, rows = RC.compare_metrics(metrics([0.4357 + 1e-12, 0.7348]), base)
        self.assertEqual(RC.verdict(True, j2, True), "float_noise")
        self.assertEqual(len(rows), 1)
        j2, _ = RC.compare_metrics(metrics([0.4400, 0.7348]), base)
        self.assertEqual(RC.verdict(True, j2, True), "mismatch")

    def test_structural_differences(self):
        """행 누락·범주 열 차이·게이트 해시 차이는 불일치다."""
        # 행을 하나 빼거나 역할 열을 바꾸거나 게이트 값을 바꾼다
        base = metrics([0.4357, 0.7348])
        j2, _ = RC.compare_metrics(base.iloc[:1], base)
        self.assertEqual((j2["only_new"], j2["only_ref"]), (0, 1))
        self.assertEqual(RC.verdict(True, j2, True), "mismatch")
        j2, _ = RC.compare_metrics(metrics([0.4357, 0.7348], ("reference", "post_hoc")), base)
        self.assertEqual(j2["mismatch_score_role"], 1)
        extra = pd.concat([base, base.iloc[:1].assign(score="extra")], ignore_index=True)
        j2, _ = RC.compare_metrics(extra, base)
        self.assertEqual((j2["only_new"], j2["mismatch_n_units"], j2["mismatch_n_polygons"]), (1, 0, 0))
        s = summary()
        sums = RC.compare_summaries(summary(auc=0.5), s, RC.gate_hashes(s))
        self.assertFalse(sums["J1"]["pass"])

    def test_j3_and_recorded(self):
        """판정 메타 차이는 J3 실패, 기록 전용 차이는 판정에 들지 않는다."""
        # 배경 격자 수와 파이썬 판만 바꾼다
        s = summary()
        other = summary(bg=1) | {"versions": {"python": "3.14"}}
        sums = RC.compare_summaries(other, s, RC.gate_hashes(s))
        self.assertIn("n_background_cells", sums["J3"]["differences"])
        self.assertEqual(sums["recorded_differences"]["versions"], {"python": {"new": "3.14", "ref": "3.12"}})
        same_meta = RC.compare_summaries(summary() | {"versions": {"python": "3.14"}}, s, RC.gate_hashes(s))
        self.assertTrue(same_meta["J3"]["pass"])

    def test_first_difference(self):
        """중첩 사전·목록의 첫 차이 경로를 찾는다."""
        # 같은 값은 빈 문자열이다
        self.assertEqual(RC.first_difference({"a": [1, 2]}, {"a": [1, 2]}), "")
        self.assertTrue(RC.first_difference({"a": [1, 2]}, {"a": [1, 3]}).startswith("$.a[1]"))
        self.assertIn("한쪽에만", RC.first_difference({"a": 1}, {"b": 1}))


class AuditCheckTest(unittest.TestCase):
    """라벨 감사 재실행 비교 규칙을 확인한다."""

    def test_summary_ignores_run_id(self):
        """run_id 만 다른 요약은 같다."""
        # 값 하나를 바꾸면 실패한다
        self.assertTrue(compare_audit_summary({"run_id": "a", "n": 1}, {"run_id": "b", "n": 1})["pass"])
        self.assertFalse(compare_audit_summary({"run_id": "a", "n": 2}, {"run_id": "b", "n": 1})["pass"])

    def test_polygon_tolerance(self):
        """실수 열은 1e-6 이내 차이를 허용하고, 문자·논리 열은 정확히 같아야 한다."""
        # 면적과 규칙 열을 가진 두 행짜리 표다
        base = pd.DataFrame({"object_id": ["a", "b"], "area_m2": [10.0, 20.0], "rule": [True, False]})
        self.assertTrue(compare_polygon_tables(base.assign(area_m2=[10.0 + 1e-7, 20.0]), base)["pass"])
        self.assertFalse(compare_polygon_tables(base.assign(area_m2=[10.001, 20.0]), base)["pass"])
        self.assertFalse(compare_polygon_tables(base.assign(rule=[True, True]), base)["pass"])
        self.assertFalse(compare_polygon_tables(base.iloc[:1], base)["pass"])
        nan = base.assign(area_m2=[float("nan"), float("nan")])
        self.assertTrue(compare_polygon_tables(nan, nan)["pass"])
        cells = base.assign(n_cells=[3, 4])
        upcast = compare_polygon_tables(cells.assign(n_cells=[3.0, 4.0]), cells)
        self.assertTrue(upcast["pass"], upcast)
        self.assertEqual(compare_polygon_tables(cells.assign(n_cells=[3.0, None]), cells)["mismatch_counts"],
                         {"n_cells": 1})


class ChronologyTest(unittest.TestCase):
    """시각 해석과 출처별 확정을 확인한다."""

    def test_parse_time(self):
        """run_id 시각과 오프셋 ISO 시각을 같은 UTC 로 읽는다."""
        # KST 21:08:17 은 UTC 12:08:17 이다
        self.assertEqual(parse_time("holdout_20260924T093854Z_ae9c122_85559f26").isoformat(),
                         "2026-09-24T09:38:54+00:00")
        self.assertEqual(parse_time("2026-09-24T21:08:17+09:00").isoformat(), "2026-09-24T12:08:17+00:00")
        self.assertEqual(parse_time("2026-09-24T09:49:16.224456+00:00").second, 16)

    def test_sources(self):
        """JSON 키·gpkg·문서 인용·미기록·없는 커밋을 출처별로 처리한다."""
        # 임시 폴더에 JSON·gpkg 흉내 SQLite·문서를 만든다
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.json").write_text(json.dumps({"x": {"t": "2026-09-24T09:18:20+00:00"}}), encoding="utf-8")
            with sqlite3.connect(root / "g.gpkg") as con:
                con.execute("create table gpkg_contents (table_name text, last_change text)")
                con.execute("insert into gpkg_contents values ('l', '2026-09-24T16:18:26.027Z')")
            (root / "d.md").write_text("지수 확정 뒤 받았다", encoding="utf-8")
            (root / "l.jsonl").write_text('{"x": "run 20260907T143417Z-40c24a6"}\n', encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            specs = [{"id": "j", "source": "json", "path": "a.json", "key": "x.t"},
                     {"id": "g", "source": "gpkg", "path": "g.gpkg"},
                     {"id": "d", "source": "doc", "path": "d.md", "quote": "확정 뒤", "date": "2026-09-24"},
                     {"id": "n", "source": "none", "evidence": "기록 없음"},
                     {"id": "c", "source": "git", "commit": "deadbeef"},
                     {"id": "r", "source": "run_id", "path": "l.jsonl", "run_id": "20260907T143417Z-40c24a6"},
                     {"id": "q", "source": "run_id", "path": "l.jsonl", "run_id": "20260907T000000Z-other"}]
            table = resolve_all(specs, root).set_index("id")
        self.assertEqual(table.loc["j", "kst"], "2026-09-24T18:18:20+09:00")
        self.assertEqual(table.loc["g", "utc"], "2026-09-24T16:18:26+00:00")
        self.assertEqual(table.loc["d", "kst"], "2026-09-24")
        self.assertTrue(table.loc["d", "verified"] and table.loc["n", "verified"])
        self.assertFalse(table.loc["c", "verified"])
        self.assertEqual(table.loc["r", "utc"], "2026-09-07T14:34:17+00:00")
        self.assertTrue(table.loc["r", "verified"])
        self.assertFalse(table.loc["q", "verified"])
        self.assertTrue(table.loc["c", "evidence"].startswith("해석 실패"))

    def test_doc_quote_missing(self):
        """문서에 없는 인용은 확인 실패다."""
        # 빈 문서를 만든다
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "d.md").write_text("", encoding="utf-8")
            row = resolve({"id": "d", "source": "doc", "path": "d.md", "quote": "없음"}, Path(tmp))
        self.assertFalse(row["verified"])


class DepositManifestTest(unittest.TestCase):
    """기탁 분류 규칙 순서를 확인한다."""

    def test_classify(self):
        """절차 §5 표의 대표 경로가 정해진 처리를 받는다."""
        # 규칙마다 한 경로씩 본다
        cases = {"data/raw/README.md": "open", "data/raw/rivers/osm_waterways.gpkg": "open",
                 "data/raw/flood_traces/changwon_info_disclosure_20260924/2023/a.shp": "hash_only",
                 "data/raw/flood_traces/safetydata_dssp_if_00117/x.gpkg": "hash_only",
                 "data/raw/dem/public_dem_2025/a.img": "hash_only", "data/external/stations.csv": "hash_only",
                 "data/external/README.md": "open", "artifacts/processed_snapshot/SHA256SUMS": "restricted",
                 "artifacts/frozen/benchmark/prespec.json": "open", "reports/tables/a.csv": "open",
                 "docs/q1/M6.md": "open", ".fablize/goals.json": "exclude", "src/repro/m6_run.py": "open"}
        for path, decision in cases.items():
            self.assertEqual(classify(path)[1], decision, path)
        self.assertEqual(classify("artifacts/frozen/x")[0], "frozen_models")
        self.assertEqual(classify("artifacts/q1/M1/x.csv")[0], "results")

    def test_build_and_summarise(self):
        """없는 파일은 크기·해시를 비우고 요약의 missing_files 에 적는다."""
        # 파일 하나만 실제로 만든다
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
            manifest = build_manifest(root, ["src/a.py", "docs/gone.md"])
            summary = summarise(manifest, root)
        self.assertEqual(summary["missing_files"], ["docs/gone.md"])
        self.assertEqual(summary["by_decision"]["open"]["n_files"], 2)
        self.assertEqual(summary["license_files"], [])
        self.assertEqual(len(manifest.loc[0, "sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
