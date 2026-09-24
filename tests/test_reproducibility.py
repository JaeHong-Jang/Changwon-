"""합성 산출물로 내용 비교와 H10 실행 흐름을 검증한다."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
import yaml
from shapely.geometry import Point

from src.data.reproducibility import canonical_hash, compare_file, compare_trees
from src.models import provenance
from src.pipeline.runner import StageFailed
from src.stages import h10_reproducibility as stage


class ComparisonTests(unittest.TestCase):
    """형식별 동일·내용 동일·불일치·누락을 검사한다."""

    def setUp(self):
        """각 시험의 합성 파일을 독립 임시 폴더에 준비한다."""
        # 비교 양쪽의 임시 루트를 만든다.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b = self.root / "a", self.root / "b"
        self.a.mkdir()
        self.b.mkdir()

    def test_bytes_and_missing_all_formats(self):
        """모든 확장자에서 바이트 일치와 양쪽 누락을 먼저 판정한다."""
        # 내용 파싱 전에 바이트 비교와 존재 여부가 우선됨을 검증한다.
        for suffix in (".parquet", ".gpkg", ".csv", ".json", ".txt"):
            with self.subTest(suffix=suffix):
                left, right = self.a / ("x" + suffix), self.b / ("x" + suffix)
                left.write_bytes(b"same")
                right.write_bytes(b"same")
                self.assertEqual(compare_file(left, right)["status"], "identical")
                right.unlink()
                self.assertEqual(compare_file(left, right)["status"], "missing")
                self.assertEqual(compare_file(right, left)["status"], "missing")
                left.unlink()
                self.assertEqual(compare_file(left, right)["status"], "missing")

    def test_parquet(self):
        """Parquet의 열 순서는 무시하되 미세한 수치 차이는 검출한다."""
        # 재정렬된 열은 같고 수정된 수치와 추가 열은 다르다.
        left, right = self.a / "x.parquet", self.b / "x.parquet"
        frame = pd.DataFrame({"grid_id": ["a", "b"], "score": [0.1, 0.2]})
        frame.to_parquet(left)
        frame[["score", "grid_id"]].to_parquet(right)
        self.assertEqual(compare_file(left, right)["status"], "content_identical")
        frame.loc[0, "score"] += 1e-12
        frame.to_parquet(right)
        self.assertIn("score", compare_file(left, right)["detail"])
        frame.assign(extra=1).to_parquet(right)
        self.assertIn("extra", compare_file(left, right)["detail"])

    def test_csv(self):
        """CSV의 명시된 실행 식별자 열만 제외하고 값 차이를 검출한다."""
        # 서로 다른 실행 식별자 열은 제외해도 실제 점수 변화는 보존한다.
        left, right = self.a / "x.csv", self.b / "x.csv"
        left.write_text("grid_id,score,evidence_run_id\na,0.1,old\n", encoding="utf-8")
        right.write_text("score,grid_id,run_id\n0.1,a,new\n", encoding="utf-8")
        self.assertEqual(compare_file(left, right)["status"], "content_identical")
        right.write_text("score,grid_id\n0.2,a\n", encoding="utf-8")
        self.assertEqual(compare_file(left, right)["status"], "different")
        self.assertIn("score", compare_file(left, right)["detail"])

    def test_json(self):
        """JSON 배열 내부까지 실행 메타데이터를 제외하고 첫 차이를 보고한다."""
        # 제거 규칙 모두와 중첩 값·키·배열 길이 차이를 시험한다.
        left, right = self.a / "x.json", self.b / "x.json"
        payload = {"nested": [{"score": 3, "evidence_run_id": "old", "source_run_id": "old",
                                "created_utc": "old", "started_utc": "old", "created_at_utc": 1,
                                "frozen_at_utc": 2, "run_id": "old"}]}
        left.write_text(json.dumps(payload), encoding="utf-8")
        right.write_text('{"nested": [{"score": 3}]}', encoding="utf-8")
        self.assertEqual(compare_file(left, right)["status"], "content_identical")
        for value, key in (({"nested": [{"score": 4}]}, "score"),
                           ({"nested": [{"other": 3}]}, "other"), ({"nested": []}, "nested")):
            right.write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(compare_file(left, right)["status"], "different")
            self.assertIn(key, compare_file(left, right)["detail"])

    def test_gpkg_all_layers_and_geometry(self):
        """GPKG의 모든 레이어·격자 정렬·도형 허용 오차를 검증한다."""
        # 둘째 레이어의 속성이나 도형 변화도 비교에 포함한다.
        left, right = self.a / "x.gpkg", self.b / "x.gpkg"
        frame = gpd.GeoDataFrame({"grid_id": ["b", "a"], "score": [2, 1]},
                                 geometry=[Point(1, 2), Point(3, 4)], crs="EPSG:5179")
        for layer in ("first", "second"):
            frame.to_file(left, layer=layer, driver="GPKG")
            frame.iloc[::-1].to_file(right, layer=layer, driver="GPKG")
        self.assertEqual(compare_file(left, right)["status"], "content_identical")
        shifted = frame.copy()
        shifted.loc[0, "geometry"] = Point(1 + 1e-7, 2)
        shifted.to_file(right, layer="second", driver="GPKG")
        self.assertEqual(compare_file(left, right)["status"], "content_identical")
        shifted.loc[0, "geometry"] = Point(1 + 1e-4, 2)
        shifted.to_file(right, layer="second", driver="GPKG")
        result = compare_file(left, right)
        self.assertEqual(result["status"], "different")
        self.assertIn("second", result["detail"])
        self.assertIn("geometry", result["detail"])
        frame.assign(score=9).to_file(right, layer="second", driver="GPKG")
        self.assertIn("score", compare_file(left, right)["detail"])
        frame.to_file(right, layer="extra", driver="GPKG")
        self.assertIn("extra", compare_file(left, right)["detail"])

    def test_gpkg_without_grid_id_and_crs(self):
        """격자 키가 없는 GPKG와 좌표계 불일치를 검증한다."""
        # 격자 식별자가 없는 도형도 원래 행 순서로 비교한다.
        left, right = self.a / "x.gpkg", self.b / "x.gpkg"
        frame = gpd.GeoDataFrame({"value": [1]}, geometry=[Point(1, 2)], crs="EPSG:5179")
        frame.to_file(left, layer="points", driver="GPKG")
        frame.set_crs("EPSG:5187", allow_override=True).to_file(right, layer="points", driver="GPKG")
        self.assertIn("CRS", compare_file(left, right)["detail"])

    def test_unknown_and_invalid_formats(self):
        """미지원 형식과 손상 파일은 내용 일치로 처리하지 않는다."""
        # 파싱 오류도 비교표의 불일치 상세에 남긴다.
        for suffix in (".txt", ".json", ".csv", ".parquet", ".gpkg"):
            left, right = self.a / ("x" + suffix), self.b / ("x" + suffix)
            left.write_bytes(b"bad")
            right.write_bytes(b"")
            self.assertEqual(compare_file(left, right)["status"], "different")

    def test_compare_trees_union(self):
        """glob별 한쪽 전용 파일과 공통 파일을 모두 비교한다."""
        # 중첩 폴더와 여러 패턴에서 상대 경로를 유지한다.
        (self.a / "sub").mkdir()
        (self.a / "sub/a.csv").write_text("v\n1\n", encoding="utf-8")
        (self.b / "b.csv").write_text("v\n2\n", encoding="utf-8")
        (self.a / "same.json").write_text("{}", encoding="utf-8")
        shutil.copy2(self.a / "same.json", self.b / "same.json")
        rows = compare_trees(self.a, self.b, ["**/*.csv", "*.json"])
        self.assertEqual({r["path"]: r["status"] for r in rows},
                         {"sub/a.csv": "missing", "b.csv": "missing", "same.json": "identical"})
        rows = compare_trees(self.a, self.b, ["required.json"])
        self.assertEqual(rows[0]["status"], "missing_pattern")

    def test_review_empty_pattern(self):
        """다른 패턴이 일치해도 양쪽 모두 빈 필수 패턴을 실패로 센다."""
        # 빈 CSV 묶음과 정상 JSON 묶음을 함께 비교한다.
        for root in (self.a, self.b):
            (root / "same.json").write_text("{}", encoding="utf-8")
        rows = compare_trees(self.a, self.b, ["*.json", "**/*.csv"])
        self.assertEqual([r["pattern"] for r in rows if r["status"] == "missing_pattern"], ["**/*.csv"])

    def test_review_real_values(self):
        """메타데이터와 이름이 비슷한 실제 값의 차이를 검출한다."""
        # 검토서의 JSON 점수와 CSV 점수를 그대로 비교한다.
        for suffix, left_text, right_text in (("json", '{"created_score":1}', '{"created_score":2}'),
                                              ("csv", "run_id_score\n0.1\n", "run_id_score\n0.9\n")):
            with self.subTest(suffix=suffix):
                left, right = self.a / ("x." + suffix), self.b / ("x." + suffix)
                left.write_text(left_text, encoding="utf-8")
                right.write_text(right_text, encoding="utf-8")
                self.assertEqual(compare_file(left, right)["status"], "different")

    def test_canonical_hash(self):
        """키 순서·한글·기본 문자열 변환의 해시 규약을 검증한다."""
        # 지정된 JSON 바이트와 직접 계산한 해시를 대조한다.
        first = {"나": [1, {"b": 2, "a": 3}], "가": Path("sample")}
        second = {"가": Path("sample"), "나": [1, {"a": 3, "b": 2}]}
        expected = hashlib.sha256(json.dumps(first, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":"), default=str).encode()).hexdigest()
        self.assertEqual(canonical_hash(first), expected)
        self.assertEqual(canonical_hash(first), canonical_hash(second))


class AtomicJsonTests(unittest.TestCase):
    """원자적 JSON 저장의 형식·동기화 순서·실패 보존을 검증한다."""

    def setUp(self):
        """독립 임시 폴더에 저장 대상과 기대 파일을 준비한다."""
        # 테스트가 만든 파일은 테스트 종료 때 함께 지운다.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "record.json"

    def test_write_and_cleanup_failure_preserves_original_exception(self):
        """쓰기와 정리가 함께 실패해도 원래 예외와 정리 실패 메모를 보존한다."""
        # 검토서의 쓰기 OSError와 정리 PermissionError를 메모리 모의로 재현한다.
        failure = OSError("write failed")
        cleanup_failure = PermissionError("cleanup failed")
        temporary = self.root / ".record.json.synthetic.tmp"
        with patch("tempfile.NamedTemporaryFile") as factory, \
                patch.object(Path, "unlink", autospec=True, side_effect=cleanup_failure) as unlink:
            output = factory.return_value.__enter__.return_value
            output.name = str(temporary)
            output.write.side_effect = failure
            with self.assertRaises(OSError) as caught:
                provenance.atomic_write_json(self.output, {"version": 2})

        # 정리 오류가 원래 예외를 대체하지 않고 경로와 함께 메모에 남아야 한다.
        self.assertIs(caught.exception, failure)
        self.assertEqual(caught.exception.__notes__,
                         [f"임시 파일 정리 실패: {temporary}: {cleanup_failure}"])
        unlink.assert_called_once_with(temporary, missing_ok=True)

    def test_format_and_invalid_json_preservation(self):
        """기존 JSON 형식을 유지하고 NaN 직렬화 실패 때 파일을 보존한다."""
        # 한글·들여쓰기·끝 줄바꿈을 기존 저장 함수의 바이트와 비교한다.
        expected = self.root / "expected.json"
        value = {"한글": [1, {"value": 2}], "valid": True}
        provenance.write_json(expected, value)
        provenance.atomic_write_json(self.output, value)
        self.assertEqual(self.output.read_bytes(), expected.read_bytes())
        before = self.output.read_bytes()
        with self.assertRaises(ValueError):
            provenance.atomic_write_json(self.output, {"value": float("nan")})
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), {expected, self.output})

    def test_sync_and_replace_failures_preserve_existing(self):
        """동기화·교체 오류도 기존 파일과 원래 예외를 보존한다."""
        # 실패 시 어느 단계에서도 임시 파일이 남아서는 안 된다.
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation):
                self.output.write_text('{"version":1}', encoding="utf-8")
                before = self.output.read_bytes()
                failure = OSError(f"synthetic {operation} failure")
                with patch.object(os, operation, side_effect=failure):
                    with self.assertRaises(OSError) as caught:
                        provenance.atomic_write_json(self.output, {"version": 2})
                self.assertIs(caught.exception, failure)
                self.assertEqual(self.output.read_bytes(), before)
                self.assertEqual(set(self.root.iterdir()), {self.output})

    def test_flush_and_sync_before_same_directory_replace(self):
        """완전한 JSON이 flush·fsync된 뒤 같은 폴더에서 교체되는지 검사한다."""
        # 실제 동기화와 교체를 감싸 순서와 교체 직전 파일 내용을 확인한다.
        self.output.write_text('{"version":1}', encoding="utf-8")
        before = self.output.read_bytes()
        expected = '{\n  "version": 2\n}\n'.encode("utf-8")
        events = []
        original_sync, original_replace = os.fsync, os.replace
        def sync(descriptor):
            """동기화 전에 버퍼가 비워졌는지 별도 읽기로 검사한다."""
            # 아직 교체되지 않은 임시 파일에서 완전한 JSON을 읽는다.
            temporary, = set(self.root.iterdir()) - {self.output}
            self.assertEqual(temporary.read_bytes(), expected)
            self.assertEqual(self.output.read_bytes(), before)
            original_sync(descriptor)
            events.append("fsync")

        # 교체는 동기화가 성공한 같은 폴더의 파일에만 수행한다.
        def replace(source, destination):
            """교체 시점의 동기화 완료와 경로를 검사한다."""
            # 모의 성공으로 끝내지 않고 실제 원자적 교체까지 수행한다.
            self.assertEqual(events, ["fsync"])
            self.assertEqual(Path(source).parent, self.output.parent)
            self.assertEqual(destination, self.output)
            original_replace(source, destination)
            events.append("replace")

        # 최종 바이트와 임시 파일 정리까지 저장 계약을 검증한다.
        with patch.object(os, "fsync", side_effect=sync), patch.object(os, "replace", side_effect=replace):
            provenance.atomic_write_json(self.output, {"version": 2})
        self.assertEqual(events, ["fsync", "replace"])
        self.assertEqual(self.output.read_bytes(), expected)
        self.assertEqual(set(self.root.iterdir()), {self.output})


class StageFlowTests(unittest.TestCase):
    """실제 파이프라인 없이 subprocess를 대체해 H10 흐름을 검사한다."""

    def setUp(self):
        """실제 자료와 분리된 합성 프로젝트를 준비한다."""
        # 모든 경로를 임시 루트로 제한한다.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ctx = SimpleNamespace(params={"h10.compare_patterns": ["data/processed/*.csv"]},
                                   run_dir=self.root / "logs", outputs=[self.root / "feedback.json"])
        self.ctx.run_dir.mkdir()
        self.metrics = {"checks": {"clean_rerun": False, "outputs_identical": False}, "rerun_run_id": None}
        self.patch = patch.object(stage, "PROJECT_ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def _fake_process(self, command, **kwargs):
        """가짜 작업 트리와 재실행 산출물만 생성한다."""
        # subprocess를 실행하지 않고 명령 계약과 합성 산출물을 검사한다.
        if command[0:3] == ["git", "worktree", "add"]:
            workspace = Path(command[4])
            self.assertEqual(kwargs["env"]["GIT_LFS_SKIP_SMUDGE"], "1")
            (workspace / "data/processed").mkdir(parents=True)
            (workspace / "data/processed/stale.csv").write_text("old", encoding="utf-8")
        elif "src.pipeline" in command:
            workspace = kwargs["cwd"]
            self.assertFalse((workspace / "data/processed/stale.csv").exists())
            self.assertEqual((workspace / "data/raw/input.txt").read_text(), "raw")
            self.assertEqual((workspace / "data/external/names.csv").read_text(), "names")
            self.assertEqual(command[-1], "h08_result_review")
            (workspace / "data/processed/result.csv").write_text("v\n1\n", encoding="utf-8")
            run = workspace / "artifacts/runs/fake"
            run.mkdir(parents=True)
            (run / "manifest.json").write_text('{"run_id":"fake"}', encoding="utf-8")
        elif command[0:3] == ["git", "worktree", "remove"]:
            shutil.rmtree(command[-1])
        output = " M src/example.py\n" if command[0:2] == ["git", "status"] else ""
        return subprocess.CompletedProcess(command, 0, output, "")

    def _prepare_rerun(self):
        """복사와 비교에 필요한 합성 입력·출력을 준비한다."""
        # 실제 원본 자료를 읽지 않도록 작은 텍스트 파일만 만든다.
        for folder in ("data/raw", "data/external", "data/processed"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "data/raw/input.txt").write_text("raw", encoding="utf-8")
        (self.root / "data/external/names.csv").write_text("names", encoding="utf-8")
        (self.root / "data/processed/result.csv").write_text("v\n1\n", encoding="utf-8")

    def test_clean_rerun_mocked(self):
        """가짜 재실행의 비교·dirty·run_id·정리를 확인한다."""
        # 실행기만 대체하고 파일 복사와 내용 비교는 합성 파일로 수행한다.
        self._prepare_rerun()
        with patch.object(stage.subprocess, "run", side_effect=self._fake_process) as process:
            stage._clean_rerun(self.ctx, self.metrics, {})
        self.assertTrue(self.metrics["checks"]["clean_rerun"])
        self.assertTrue(self.metrics["checks"]["outputs_identical"])
        self.assertTrue(self.metrics["source_dirty"])
        self.assertEqual(self.metrics["rerun_run_id"], "fake")
        self.assertFalse(Path(self.metrics["workspace"]).exists())
        self.assertEqual(process.call_args.args[0], ["git", "worktree", "list", "--porcelain"])

    def test_rerun_timeout_cleanup_and_keep(self):
        """시간 초과 후 정리와 작업 공간 유지 옵션을 검증한다."""
        # 가짜 실행기를 시간 초과시키고 finally의 정리 여부를 확인한다.
        self._prepare_rerun()
        for keep in (False, True):
            self.ctx.params["h10.keep_workspace"] = keep
            with patch.object(stage.subprocess, "run", side_effect=self._fake_process) as process:
                process.side_effect = self._timeout_process
                with self.assertRaises(subprocess.TimeoutExpired):
                    stage._clean_rerun(self.ctx, self.metrics, {})
            workspace = Path(self.metrics["workspace"])
            self.assertEqual(workspace.exists(), keep)
            if keep:
                shutil.rmtree(workspace)

    def _timeout_process(self, command, **kwargs):
        """가짜 파이프라인 명령에만 시간 초과를 발생시킨다."""
        # 나머지 git 명령은 기존 가짜 실행기로 처리한다.
        if "src.pipeline" in command:
            raise subprocess.TimeoutExpired(command, 1)
        return self._fake_process(command, **kwargs)

    def test_unit_tests_mocked(self):
        """테스트 실행 수와 실패 코드를 표준 오류 출력에서 읽는다."""
        # unittest 자식 프로세스는 실제로 시작하지 않는다.
        for code in (0, 1):
            result = subprocess.CompletedProcess([], code, "", "Ran 12 tests in 0.1s\n")
            with patch.object(stage.subprocess, "run", return_value=result):
                stage._unit_tests(self.ctx, self.metrics, {})
            self.assertEqual(self.metrics["unit_tests"]["ran"], 12)
            self.assertEqual(self.metrics["checks"]["unit_tests"], code == 0)

    def test_holdout_synthetic_reference(self):
        """합성 게이트로 기준 부재·일치·변경을 검증한다."""
        # 실제 홀드아웃을 열지 않고 기준 파일 계약만 확인한다.
        with self.assertRaisesRegex(ValueError, "리더가 기준을 고정해야 한다"):
            stage._holdout_checksum(self.metrics)
        summary = {"gates": {"pass": False}, "development_gates": {"pass": True}}
        reference = {"run_id": "fake", "gates_sha256": canonical_hash(summary["gates"]),
                     "development_gates_sha256": canonical_hash(summary["development_gates"])}
        (self.root / "config").mkdir()
        (self.root / "config/holdout_reference.yaml").write_text(yaml.safe_dump(reference), encoding="utf-8")
        folder = self.root / "artifacts/evaluation/holdout_2022_2024"
        (folder / "fake").mkdir(parents=True)
        (folder / "latest.json").write_text('{"run_id":"fake"}', encoding="utf-8")
        (folder / "fake/summary.json").write_text(json.dumps(summary), encoding="utf-8")
        stage._holdout_checksum(self.metrics)
        self.assertTrue(self.metrics["checks"]["holdout_checksum_unchanged"])
        summary["gates"]["pass"] = True
        (folder / "fake/summary.json").write_text(json.dumps(summary), encoding="utf-8")
        stage._holdout_checksum(self.metrics)
        self.assertFalse(self.metrics["checks"]["holdout_checksum_unchanged"])

    def test_notebook_error_cells(self):
        """가짜 nbconvert 출력의 오류 셀을 실패로 기록한다."""
        # 실행 결과 파일만 합성해 원본 노트북 불변을 확인한다.
        (self.root / "notebooks").mkdir()
        notebook = self.root / "notebooks/01_example.ipynb"
        notebook.write_text('{"cells": []}', encoding="utf-8")
        with patch.object(stage.subprocess, "run", side_effect=self._notebook_process):
            stage._notebooks(self.ctx, self.metrics, {})
        self.assertEqual(self.metrics["notebooks"]["error_cells"], 1)
        self.assertFalse(self.metrics["checks"]["notebooks"])
        self.assertEqual(notebook.read_text(), '{"cells": []}')

    def _notebook_process(self, command, **kwargs):
        """오류 출력 하나를 가진 실행 노트북을 합성한다."""
        # 지정된 임시 출력 폴더에만 결과를 기록한다.
        output = Path(command[command.index("--output-dir") + 1]) / "01_example.ipynb"
        self.assertEqual(command[command.index("--output") + 1], "01_example.ipynb")
        output.write_text('{"cells":[{"outputs":[{"output_type":"error"}]}]}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_stage_failures_collected_without_executing(self):
        """모든 작업을 대체해 실패 수집과 환경변수 제거를 검증한다."""
        # 실제 subprocess와 홀드아웃 접근 없이 집계 흐름만 실행한다.
        with patch.object(stage, "_unit_tests", side_effect=ValueError("fake")) as unit, \
                patch.object(stage, "_clean_rerun"), patch.object(stage, "_holdout_checksum"), \
                patch.object(stage, "_feedback") as feedback, patch.object(stage, "_notebooks"):
            with self.assertRaises(StageFailed) as caught:
                stage.reproducibility(self.ctx)
        self.assertNotIn("CHANGWON_HOLDOUT_TESTS", unit.call_args.args[2])
        feedback.assert_called_once()
        self.assertEqual(caught.exception.metrics["checks_passed"], 0)
        self.assertEqual(len(caught.exception.findings), 6)

    def test_review_feedback_failure(self):
        """다른 검사 실패 시 확정 기록을 보존하고 후보만 저장한다."""
        # 실제 검사와 자료 접근 없이 환류 저장 분기만 실행한다.
        self.ctx.outputs = [self.root / "artifacts/evaluation/feedback_manifest.json"]
        output = self.ctx.outputs[0]
        output.parent.mkdir(parents=True)
        output.write_text('{"version": 1}', encoding="utf-8")
        before = output.read_bytes()
        with patch.object(stage, "load_registry", return_value={}), \
                patch.object(stage, "build", return_value={"version": 2}), \
                patch.object(stage, "validate", return_value=[]):
            stage._feedback(self.ctx, self.metrics)
        self.assertEqual(output.read_bytes(), before)
        candidate = self.ctx.run_dir / "feedback_manifest.candidate.json"
        self.assertEqual(json.loads(candidate.read_text()), {"version": 2})

    def test_review_feedback_partial_write_preserves_existing(self):
        """환류 쓰기 도중 오류가 나도 최종·후보의 기존 바이트를 보존한다."""
        # 검토서의 잘린 JSON 쓰기를 실제 합성 파일에 주입한다.
        original_open = io.open
        failure = OSError("synthetic partial write")
        def partial_open(*args, **kwargs):
            """쓰기 스트림만 접두부를 저장한 뒤 실패하도록 바꾼다."""
            # 읽기와 파일 닫기는 실제 동작을 유지한다.
            stream = original_open(*args, **kwargs)
            if stream.writable():
                original_write = stream.write
                def partial_write(value):
                    """검토서와 같은 부분 JSON을 쓴 뒤 예외를 던진다."""
                    # 버퍼를 비워 디스크의 부분 쓰기를 확실히 재현한다.
                    original_write('{"version":')
                    stream.flush()
                    raise failure
                stream.write = partial_write
            return stream

        # 전체 성공과 선행 검사 실패의 저장 경로를 같은 오류로 검증한다.
        candidate = self.ctx.run_dir / "feedback_manifest.candidate.json"
        for checks_ok in (True, False):
            with self.subTest(checks_ok=checks_ok):
                self.ctx.outputs[0].write_text('{"version":1}', encoding="utf-8")
                candidate.write_text('{"version":0}', encoding="utf-8")
                before = {path: path.read_bytes() for path in (self.ctx.outputs[0], candidate)}
                files_before = set(self.root.rglob("*"))
                self.metrics["checks"] = {"notebooks": checks_ok}
                with patch.object(stage, "load_registry", return_value={}), \
                        patch.object(stage, "build", return_value={"version": 2}), \
                        patch.object(stage, "validate", return_value=[]), \
                        patch("io.open", side_effect=partial_open):
                    with self.assertRaises(OSError) as caught:
                        stage._feedback(self.ctx, self.metrics)
                self.assertIs(caught.exception, failure)
                for path, content in before.items():
                    self.assertEqual(path.read_bytes(), content)
                self.assertEqual(set(self.root.rglob("*")), files_before)

    def test_review_feedback_build_failure_creates_candidate(self):
        """빌드 삭제 오류는 후보에 원인을 남기고 최종 기록을 보존한다."""
        # 검토서의 이전 파일 삭제 오류를 빌드 예외로 합성한다.
        self.ctx.outputs[0].write_text('{"version":1}', encoding="utf-8")
        before = self.ctx.outputs[0].read_bytes()
        failure = ValueError("previous: missing file: deleted.yaml")
        started = datetime.now(timezone.utc)
        with patch.object(stage, "load_registry", return_value={}), \
                patch.object(stage, "build", side_effect=failure), \
                patch.object(stage, "validate") as validator:
            with self.assertRaises(ValueError) as caught:
                stage._feedback(self.ctx, self.metrics)
        self.assertIs(caught.exception, failure)
        validator.assert_not_called()
        self.assertEqual(self.ctx.outputs[0].read_bytes(), before)
        candidate = self.ctx.run_dir / "feedback_manifest.candidate.json"
        self.assertTrue(candidate.is_file())
        record = json.loads(candidate.read_text(encoding="utf-8"))
        self.assertEqual(set(record), {"status", "error", "created_utc"})
        self.assertEqual(record["status"], "build_failed")
        self.assertEqual(record["error"], "ValueError: previous: missing file: deleted.yaml")
        created = datetime.fromisoformat(record["created_utc"])
        self.assertEqual(created.utcoffset(), timezone.utc.utcoffset(created))
        self.assertLessEqual(started, created)
        self.assertLessEqual(created, datetime.now(timezone.utc))
        self.assertFalse(self.metrics["checks"]["feedback_manifest_valid"])
        self.assertEqual(self.metrics["feedback_errors"], [record["error"]])
        self.assertEqual(self.metrics["feedback_path"], str(candidate))

    def _remove_failure_process(self, command, **kwargs):
        """재실행 시간 초과와 git 제거 실패를 동시에 합성한다."""
        # 정리 예외가 원래 재실행 예외를 덮는 사례를 재현한다.
        if command[:3] == ["git", "worktree", "remove"]:
            raise subprocess.CalledProcessError(1, command)
        return self._timeout_process(command, **kwargs)

    def test_review_cleanup_failure(self):
        """git 제거 실패에도 폴더를 지우고 원래 시간 초과를 보존한다."""
        # 프로세스는 대체하고 실제 임시 폴더 정리만 확인한다.
        self._prepare_rerun()
        self.ctx.params["h10.workspace_parent"] = str(self.root / "workspaces")
        with patch.object(stage.subprocess, "run", side_effect=self._remove_failure_process):
            with self.assertRaises(subprocess.TimeoutExpired):
                stage._clean_rerun(self.ctx, self.metrics, {})
        self.assertTrue(self.metrics["cleanup_ok"])
        self.assertIsNone(self.metrics["leftover_path"])
        self.assertFalse(Path(self.metrics["workspace"]).exists())

    def test_review_add_timeout(self):
        """작업 트리 생성에도 시간 제한을 전달한다."""
        # subprocess 호출 인수만으로 무기한 대기 가능성을 검사한다.
        self._prepare_rerun()
        with patch.object(stage.subprocess, "run", side_effect=self._fake_process) as process:
            stage._clean_rerun(self.ctx, self.metrics, {})
        call = next(c for c in process.call_args_list if c.args[0][:3] == ["git", "worktree", "add"])
        self.assertEqual(call.kwargs.get("timeout"), 3600)

    def test_review_cleanup_terminal_failures(self):
        """대체 삭제·prune 실패를 별도 지표로 남기고 원래 오류를 보존한다."""
        # 실제 재실행 없이 정리 실패 두 종류와 잔여 경로를 검사한다.
        self._prepare_rerun()
        self.ctx.params["h10.workspace_parent"] = str(self.root / "workspaces")
        original_rmtree = shutil.rmtree
        for failure in ("rmtree", "prune"):
            with self.subTest(failure=failure):
                def process(command, **kwargs):
                    """선택한 정리 명령만 실패시키고 나머지는 모의 실행한다."""
                    # prune 실패에서도 remove 실패 후 대체 삭제를 먼저 거친다.
                    if failure == "prune" and command[:3] == ["git", "worktree", "prune"]:
                        raise RuntimeError("prune failed")
                    return self._remove_failure_process(command, **kwargs)

                # 초기 산출물 삭제는 허용하고 대체 rmtree만 실패시킨다.
                def remove(path, *args, **kwargs):
                    """대체 삭제의 ignore_errors 인수를 기준으로 실패를 합성한다."""
                    # TemporaryDirectory의 사후 정리에는 영향을 주지 않는다.
                    if failure == "rmtree" and "ignore_errors" in kwargs:
                        raise OSError("rmtree failed")
                    return original_rmtree(path, *args, **kwargs)

                # 두 정리 실패 모두 TimeoutExpired가 밖으로 유지되어야 한다.
                with patch.object(stage.subprocess, "run", side_effect=process), \
                        patch.object(stage.shutil, "rmtree", side_effect=remove):
                    with self.assertRaises(subprocess.TimeoutExpired):
                        stage._clean_rerun(self.ctx, self.metrics, {})
                self.assertFalse(self.metrics["cleanup_ok"])
                self.assertTrue(any(failure in e for e in self.metrics["cleanup_errors"]))
                self.assertEqual(self.metrics["leftover_path"] is not None, failure == "rmtree")

    def test_review_add_timeout_cleans_partial_tree(self):
        """생성 도중 시간 초과도 부분 작업 트리 정리 경로를 거친다."""
        # 생성 명령이 부분 파일을 만든 뒤 시간 초과했다고 가정한다.
        def process(command, **kwargs):
            """가짜 작업 트리 생성 직후 시간 초과를 일으킨다."""
            # git 명령을 실제 실행하지 않는다.
            result = self._fake_process(command, **kwargs)
            if command[:3] == ["git", "worktree", "add"]:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            return result

        # 생성 실패에도 경로와 등록 정리 결과가 남는다.
        with patch.object(stage.subprocess, "run", side_effect=process):
            with self.assertRaises(subprocess.TimeoutExpired):
                stage._clean_rerun(self.ctx, self.metrics, {})
        self.assertTrue(self.metrics["cleanup_ok"])
        self.assertIsNone(self.metrics["leftover_path"])

    def test_review_cleanup_finding(self):
        """정리 실패를 H10 실패 사유로 기록한다."""
        # 전체 함수는 모의 검사로 실패 종료하며 실제 재실행은 하지 않는다.
        def failed_cleanup(ctx, metrics, env):
            """원래 재실행 오류와 정리 실패 지표를 함께 합성한다."""
            # 원래 오류와 정리 오류가 모두 findings에 있어야 한다.
            metrics.update(cleanup_ok=False, cleanup_errors=["rmtree failed"], leftover_path="synthetic")
            raise subprocess.TimeoutExpired("synthetic", 1)

        # 실패 집계만 실행하고 파일·프로세스 검사는 모두 대체한다.
        with patch.object(stage, "_unit_tests"), \
                patch.object(stage, "_clean_rerun", side_effect=failed_cleanup), \
                patch.object(stage, "_holdout_checksum"), patch.object(stage, "_notebooks"), \
                patch.object(stage, "_feedback"):
            with self.assertRaises(StageFailed) as caught:
                stage.reproducibility(self.ctx)
        findings = {row["code"]: row["detail"] for row in caught.exception.findings}
        self.assertIn("TimeoutExpired", findings["clean_rerun"])
        self.assertIn("rmtree failed", findings["cleanup"])

    def test_review_feedback_commit_conditions(self):
        """모든 검사 통과에서만 확정하고 자체 검증·정리 실패는 후보로 남긴다."""
        # 실제 파일 검증은 대체하고 저장 조건과 previous 전달을 검증한다.
        for checks_ok, cleanup_ok, errors in ((True, True, []), (True, False, []), (True, True, ["invalid"])):
            with self.subTest(cleanup_ok=cleanup_ok, errors=errors):
                self.ctx.outputs[0].write_text('{"version": 1}', encoding="utf-8")
                self.metrics.update(checks={"notebooks": checks_ok}, cleanup_ok=cleanup_ok)
                with patch.object(stage, "load_registry", return_value={}), \
                        patch.object(stage, "build", return_value={"version": 2}), \
                        patch.object(stage, "validate", return_value=errors) as validator:
                    stage._feedback(self.ctx, self.metrics)
                validator.assert_called_once_with({"version": 2}, self.root, previous={"version": 1})
                expected = 2 if cleanup_ok and not errors else 1
                self.assertEqual(json.loads(self.ctx.outputs[0].read_text())["version"], expected)

    def test_review_notebook_failure_before_feedback(self):
        """늦게 실패하는 노트북 검사도 환류 확정을 막는다."""
        # 나머지 검사를 통과시키고 노트북만 실패시켜 저장 순서를 검증한다.
        self.ctx.outputs[0].write_text('{"version": 1}', encoding="utf-8")
        def unit(ctx, metrics, env):
            """모든 검사가 통과한 초기 합성 상태를 만든다."""
            # 후속 노트북 실패가 최종 상태를 바꾼다.
            metrics["checks"] = dict.fromkeys(metrics["checks"], True)

        # 실패 시에만 함수가 종료되며 subprocess와 홀드아웃은 실행하지 않는다.
        with patch.object(stage, "_unit_tests", side_effect=unit), patch.object(stage, "_clean_rerun"), \
                patch.object(stage, "_holdout_checksum"), \
                patch.object(stage, "_notebooks", side_effect=RuntimeError("notebook failed")), \
                patch.object(stage, "load_registry", return_value={}), \
                patch.object(stage, "build", return_value={"version": 2}), \
                patch.object(stage, "validate", return_value=[]):
            with self.assertRaises(StageFailed):
                stage.reproducibility(self.ctx)
        self.assertEqual(json.loads(self.ctx.outputs[0].read_text()), {"version": 1})
        self.assertTrue((self.ctx.run_dir / "feedback_manifest.candidate.json").is_file())
