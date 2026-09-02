from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src.pipeline.graph import Node
from src.pipeline.runner import StageContext, StageFailed
from src.stages import h00_collect


def make_ctx(root: Path, node_id: str, output: str) -> StageContext:
    node = Node(id=node_id, gate="H00", phase="P1", runner="src.stages.h00_collect:x", outputs=(output,))
    return StageContext(node=node, run_id="t", run_dir=root / "run", config={}, params={}, inputs=[], outputs=[root / output])


class AccessRequestsTest(unittest.TestCase):
    HEADER = ("| # | 대상 | 신청처 | 신청일 | 접수번호/증빙 | 예상 회신 | 상태 | 필요성 | 없으면 | 비고 |\n"
              "|---|---|---|---|---|---|---|---|---|---|\n")

    def run_with(self, table: str) -> tuple[dict, dict]:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs").mkdir()
            (root / "docs" / "data_access_log.md").write_text(self.HEADER + table, encoding="utf-8")
            ctx = make_ctx(root, "h00_access_requests", "out/access.json")
            with patch("src.pipeline.runner.PROJECT_ROOT", root):
                metrics = h00_collect.access_requests(ctx)
            return metrics, json.loads((root / "out" / "access.json").read_text(encoding="utf-8"))

    def test_pass_with_required_pending(self) -> None:
        table = (
            "| 1 | 민원 | 정부24 | 2026-08-19 | 접수 123 | ~09-02 | 🟡 대기 | **필수** | Layer2 불가 | |\n"
            "| 2 | 토지피복 | EGIS | 2026-08-19 | 경로 | — | ✅ 수령 | **필수** | 불투수면 없음 | |\n"
            "| 3 | DEM | NGII | 2026-08-19 | 경로 | — | ✅ 수령 | **필수** | 경사 없음 | |\n"
            "| 4 | API키 | sgis | | | 즉시 | ⬜ 미신청 | **대체가능** | 이미 확보 | |\n"
        )
        metrics, out = self.run_with(table)
        self.assertEqual(metrics["total"], 4)
        self.assertEqual(metrics["received"], 2)
        self.assertEqual(metrics["pending"], 1)
        self.assertEqual(metrics["not_requested"], [4])
        self.assertEqual(metrics["required_pending"], [1])
        rows = out["rows"]
        self.assertEqual(rows[0]["receipt"], "접수 123")

    def test_fail_when_required_not_requested(self) -> None:
        table = (
            "| 1 | 민원 | 정부24 | | | +10일 | ⬜ 미신청 | **필수** | Layer2 불가 | |\n"
            "| 2 | 토지피복 | EGIS | 2026-08-19 | 경로 | — | ✅ 수령 | **필수** | 불투수면 없음 | |\n"
        )
        with self.assertRaises(StageFailed) as cm:
            self.run_with(table)
        self.assertEqual(cm.exception.findings[0]["code"], "required_not_requested")

    def test_need_level_comes_from_document_not_code(self) -> None:
        """필요성 판단은 문서의 '필요성' 열에서 읽는다. 코드에 번호를 박으면 둘이 갈라진다."""
        table = (
            "| 1 | 민원 | 정부24 | 2026-08-19 | 접수 | ~09-02 | 🟡 대기 | **대체가능** | 다른 자료로 | |\n"
            "| 9 | 좌표 | 기상청 | | | 즉시 | ⬜ 미신청 | **필수** | IDW 불가 | |\n"
        )
        with self.assertRaises(StageFailed) as cm:
            self.run_with(table)
        finding = cm.exception.findings[0]
        self.assertEqual(finding["code"], "required_not_requested")
        self.assertEqual(finding["no"], 9, "문서에서 9번이 필수로 읽혀야 한다")

    def test_missing_need_column_blocks(self) -> None:
        """필요성이 비어 있으면 아무도 판단하지 않은 것이다. '필수 아님' 으로 넘기지 않고 막는다."""
        table = "| 1 | 민원 | 정부24 | | | +10일 | ⬜ 미신청 | | | |\n"
        with self.assertRaises(StageFailed) as cm:
            self.run_with(table)
        self.assertEqual(cm.exception.findings[0]["code"], "need_unjudged")

    def test_fail_when_status_missing(self) -> None:
        table = "| 5 | 키 | x | | | 즉시 | ??? | **선택** | 영향 없음 | |\n"
        with self.assertRaises(StageFailed) as cm:
            self.run_with(table)
        self.assertEqual(cm.exception.findings[0]["code"], "missing_status")


class InventoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "data" / "raw").mkdir(parents=True)
        (self.root / "data" / "raw" / "README.md").write_text("| rain | 강수_ |", encoding="utf-8")
        self.patches = [
            patch("src.pipeline.runner.PROJECT_ROOT", self.root),
            patch.object(h00_collect, "PROJECT_ROOT", self.root),
            patch.object(h00_collect, "GROUPS", {"rainfall": ["rain"], "geo": ["tiles"]}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write_contract(self, datasets: dict) -> None:
        (self.root / "config" / "data_contracts.yaml").write_text(
            yaml.safe_dump({"version": 1, "raw_root": "data/raw", "datasets": datasets}, allow_unicode=True),
            encoding="utf-8",
        )

    def test_pass(self) -> None:
        (self.root / "data" / "raw" / "강수_2025.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.write_contract({"rain": {"kind": "csv", "glob": "강수_*.csv", "expected_files": 1,
                                      "collected_at": "2026-08-19", "source_url": "https://x"}})
        ctx = make_ctx(self.root, "h00_collect_rainfall", "out/collection_rainfall.json")
        metrics = h00_collect.inventory(ctx)
        self.assertEqual(metrics["files"], 1)
        self.assertEqual(metrics["lfs_pointers"], 0)
        self.assertEqual(metrics["missing_metadata"], [])
        self.assertEqual(metrics["readme_unrecorded"], [])
        data = json.loads((self.root / "out" / "collection_rainfall.json").read_text(encoding="utf-8"))
        self.assertTrue(data["datasets"][0]["readme_recorded"])

    def test_fail_on_pointer_count_and_metadata(self) -> None:
        (self.root / "data" / "raw" / "t1.img").write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\n")
        self.write_contract({"tiles": {"kind": "raster", "glob": "*.img", "expected_files": 2}})
        ctx = make_ctx(self.root, "h00_collect_geo", "out/collection_geo.json")
        with self.assertRaises(StageFailed) as cm:
            h00_collect.inventory(ctx)
        codes = {f["code"] for f in cm.exception.findings}
        self.assertEqual(codes, {"lfs_pointer", "file_count", "missing_metadata"})
        self.assertTrue((self.root / "out" / "collection_geo.json").exists())

    def test_unknown_group(self) -> None:
        self.write_contract({})
        ctx = make_ctx(self.root, "h00_collect_zzz", "out/x.json")
        with self.assertRaises(StageFailed):
            h00_collect.inventory(ctx)


if __name__ == "__main__":
    unittest.main()
