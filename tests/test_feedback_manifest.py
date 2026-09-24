"""합성 등록부·모델로 환류 manifest의 버전과 검증 오류를 검사한다."""

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from src.data.feedback_manifest import REQUIRED_KEYS, build, validate
from src.models.provenance import file_sha256


class FeedbackTests(unittest.TestCase):
    """자료·모델 변경과 파일 무결성 오류를 검증한다."""

    def setUp(self):
        """등록부의 벡터·부속 파일과 모델 파일을 합성한다."""
        # 원본 자료를 사용하지 않고 파일 해시만 시험한다.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("trace.shp", "trace.dbf", "trace.shx", "trace.prj", "trace.cpg", "model.yaml"):
            (self.root / name).write_text(name, encoding="utf-8")
        self.registry = {"synthetic": {"role": "development", "paths": ["trace.shp"]}}
        (self.root / "config").mkdir()
        (self.root / "config/flood_traces.yaml").write_text(
            yaml.safe_dump({"sources": self.registry}), encoding="utf-8")
        self.kwargs = {"root": self.root, "registry": self.registry, "model_files": ["model.yaml"],
                       "holdout_reference": {"run_id": "synthetic"}}

    def test_versions_and_sidecars(self):
        """초기·동일·자료 변경·모델 변경·삭제 버전 전환을 검증한다."""
        # 모든 부속 파일의 실제 SHA256과 최초 버전을 검사한다.
        first = build(None, **self.kwargs)
        self.assertEqual(first["version"], 1)
        self.assertIsNone(first["previous_version"])
        files = first["data_versions"]["synthetic"]["files"]
        self.assertEqual(len(files), 5)
        self.assertEqual(files["trace.prj"], file_sha256(self.root / "trace.prj"))
        self.assertEqual(validate(first, self.root), [])

        # 동일 파일에서는 유지하고 자료·모델 변화가 있으면 한 단계 증가한다.
        same = build(first, **self.kwargs)
        self.assertEqual((same["version"], same["previous_version"], same["changed"]), (1, 1, []))
        (self.root / "trace.dbf").write_text("updated", encoding="utf-8")
        updated = build(same, **self.kwargs)
        self.assertEqual((updated["version"], updated["previous_version"]), (2, 1))
        self.assertEqual(updated["changed"], ["data_versions.synthetic"])
        (self.root / "model.yaml").write_text("new model", encoding="utf-8")
        model = build(updated, **self.kwargs)
        self.assertEqual(model["version"], 3)
        self.assertEqual(model["changed"], ["model_versions.model.yaml"])
        removed = build(model, **{**self.kwargs, "registry": {}, "model_files": []})
        self.assertEqual(removed["version"], 4)
        self.assertEqual(removed["changed"], ["data_versions.synthetic", "model_versions.model.yaml"])
        (self.root / "config/flood_traces.yaml").write_text("sources: {}", encoding="utf-8")
        self.assertEqual(validate(removed, self.root, previous=model), [])

    def test_registry_loading_and_role_change(self):
        """기본 등록부 로딩과 자료 역할 변경을 기록한다."""
        # root 기준 등록부를 사용하며 합성 역할 변경도 버전을 증가시킨다.
        first = build(None, **{**self.kwargs, "registry": None})
        self.registry["synthetic"]["role"] = "holdout"
        second = build(first, **self.kwargs)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["data_versions"]["synthetic"]["role"], "holdout")

    def test_missing_required_keys(self):
        """각 필수키의 누락을 오류로 보고한다."""
        # 누락 키를 하나씩 제거해 오류에 키 이름이 포함되는지 확인한다.
        manifest = build(None, **self.kwargs)
        for key in REQUIRED_KEYS:
            candidate = copy.deepcopy(manifest)
            candidate.pop(key)
            self.assertIn(f"missing required key: {key}", validate(candidate, self.root))

    def test_file_mismatch_and_missing(self):
        """자료·모델의 해시 변경과 파일 부재를 모두 검출한다."""
        # 두 파일 영역에서 해시 불일치와 누락을 동시에 만든다.
        manifest = build(None, **self.kwargs)
        (self.root / "trace.dbf").write_text("changed", encoding="utf-8")
        (self.root / "model.yaml").write_text("changed", encoding="utf-8")
        errors = validate(manifest, self.root)
        self.assertEqual(sum("sha256 mismatch" in e for e in errors), 2)
        (self.root / "trace.dbf").unlink()
        (self.root / "model.yaml").unlink()
        errors = validate(manifest, self.root)
        self.assertEqual(sum("missing file" in e for e in errors), 2)

    def test_invalid_versions_and_transition(self):
        """불리언·실수·음수 버전과 잘못된 증가 규칙을 거부한다."""
        # 정수 타입과 changed 유무에 따른 전환식을 별도로 검증한다.
        manifest = build(None, **self.kwargs)
        for value in (0, -1, True, 1.0, "1", None):
            self.assertIn("version must be an integer >= 1", validate({**manifest, "version": value}, self.root))
        previous = {**manifest, "version": 2}
        for version, valid in ((2, True), (3, False)):
            candidate = {**manifest, "previous_version": 2, "version": version, "changed": []}
            self.assertEqual(not validate(candidate, self.root, previous=previous), valid)
        for previous in (0, True, "1"):
            errors = validate({**manifest, "previous_version": previous}, self.root)
            self.assertTrue(any("previous_version must" in error for error in errors))

    def test_invalid_mappings_and_paths(self):
        """손상 목록과 루트 밖 경로를 오류 목록으로 반환한다."""
        # 잘못된 구조도 예외 대신 검증 오류로 반환한다.
        manifest = build(None, **self.kwargs)
        for key in ("data_versions", "model_versions"):
            self.assertTrue(validate({**manifest, key: []}, self.root))
        self.assertTrue(validate({**manifest, "data_versions": {"bad": {}}}, self.root))
        errors = validate({**manifest, "model_versions": {"../outside": "bad"}}, self.root)
        self.assertTrue(any("relative to root" in error for error in errors))

    def test_review_missing_patterns(self):
        """등록 경로 하나라도 비면 빌드를 거부한다."""
        # 다른 경로가 존재해도 없는 정확 경로와 glob을 각각 검사한다.
        for pattern in ("nothing_ever_here.shp", "missing/*.shp"):
            with self.subTest(pattern=pattern):
                registry = copy.deepcopy(self.registry)
                registry["synthetic"]["paths"].append(pattern)
                with self.assertRaisesRegex(ValueError, "missing registered pattern"):
                    build(None, **{**self.kwargs, "registry": registry})

    def test_review_deleted_sidecar(self):
        """현재 목록에서 빠진 이전 부속 파일의 삭제를 거부한다."""
        # 주 벡터 파일이 남아 있어도 삭제를 오류로 처리한다.
        first = build(None, **self.kwargs)
        (self.root / "trace.dbf").unlink()
        with self.assertRaisesRegex(ValueError, "previous.*missing file"):
            build(first, **self.kwargs)

    def test_review_version_schema(self):
        """최초 버전 99와 문자열 또는 비문자열 changed를 거부한다."""
        # 검토서의 위조 입력을 독립적으로 검증한다.
        first = build(None, **self.kwargs)
        for overrides in ({"version": 99}, {"changed": "arbitrary"}, {"changed": [1]}):
            with self.subTest(overrides=overrides):
                self.assertTrue(validate({**first, **overrides}, self.root))

    def test_review_validate_missing_patterns_and_inventory(self):
        """빈 등록 패턴과 manifest에서 지운 등록 파일을 검증 오류로 잡는다."""
        # 빌드 이후 등록부가 바뀌거나 파일 목록이 위조된 경우를 검사한다.
        first = build(None, **self.kwargs)
        candidate = copy.deepcopy(first)
        candidate["data_versions"]["synthetic"]["files"] = {}
        self.assertTrue(any("registered files missing" in e for e in validate(candidate, self.root)))
        for pattern in ("nothing_ever_here.shp", "missing/*.shp"):
            registry = copy.deepcopy(self.registry)
            registry["synthetic"]["paths"].append(pattern)
            (self.root / "config/flood_traces.yaml").write_text(
                yaml.safe_dump({"sources": registry}), encoding="utf-8")
            self.assertTrue(any("missing registered pattern" in e for e in validate(first, self.root)))

    def test_review_validate_previous_deletion(self):
        """새 기록에서 빠진 이전 원본과 모델의 물리적 삭제도 검출한다."""
        # 현재 목록을 새로 만들어도 이전 파일의 부재는 사라지지 않는다.
        first = build(None, **self.kwargs)
        (self.root / "trace.dbf").unlink()
        candidate = build(None, **self.kwargs)
        errors = validate(candidate, self.root, previous=first)
        self.assertTrue(any("previous: missing file: trace.dbf" in e for e in errors))
        (self.root / "model.yaml").unlink()
        with self.assertRaisesRegex(ValueError, "previous: missing file"):
            build(first, **{**self.kwargs, "model_files": []})

    def test_review_recomputed_changes(self):
        """재계산한 변경 목록과 버전으로 위조·은폐·중복 변경을 거부한다."""
        # 정상 전환을 기준으로 changed와 버전 값을 각각 변조한다.
        first = build(None, **self.kwargs)
        same = build(first, **self.kwargs)
        self.assertEqual(validate(same, self.root, previous=first), [])
        self.assertTrue(validate({**same, "changed": ["arbitrary"], "version": 2}, self.root, previous=first))
        (self.root / "model.yaml").write_text("new", encoding="utf-8")
        changed = build(first, **self.kwargs)
        self.assertEqual(validate(changed, self.root, previous=first), [])
        for keys in ([], ["arbitrary"], changed["changed"] * 2):
            errors = validate({**changed, "changed": keys, "version": 1}, self.root, previous=first)
            self.assertTrue(any("changed" in e for e in errors))
            self.assertTrue(any("version transition" in e for e in errors))
        self.assertTrue(validate({**changed, "previous_version": 8}, self.root, previous=first))
