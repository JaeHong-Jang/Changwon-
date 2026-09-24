"""H10 단위 테스트·깨끗한 재실행·홀드아웃 불변·환류·노트북 검증 흐름."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.data.feedback_manifest import build, validate
from src.data.reproducibility import canonical_hash, compare_trees
from src.data.trace_registry import load_registry
from src.models.provenance import atomic_write_json
from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT

DEFAULT_PATTERNS = ["data/processed/**/*.gpkg", "data/processed/**/*.parquet",
                    "data/processed/**/*.csv", "reports/tables/*.csv",
                    "artifacts/evaluation/primary_formula_manifest.json"]
MODEL_FILES = ["config/pipeline.yaml", "config/config.yaml", "config/flood_traces.yaml",
               "config/raw_quality_waivers.yaml", "artifacts/evaluation/primary_formula_manifest.json"]


def _unit_tests(ctx, metrics, env):
    """홀드아웃 활성화 변수를 제거한 환경에서 단위 테스트를 실행한다."""
    # unittest의 표준 오류 출력을 포함해 실행 수와 성공 여부를 보존한다.
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    output = result.stdout + result.stderr
    (ctx.run_dir / "unit_tests.log").write_text(output, encoding="utf-8")
    matched = re.search(r"Ran (\d+) tests?", output)
    ran = int(matched.group(1)) if matched else 0
    ok = result.returncode == 0 and ran > 0
    metrics["unit_tests"] = {"ran": ran, "ok": ok, "returncode": result.returncode, "command": command}
    metrics["checks"]["unit_tests"] = ok


def _remove_directory(path):
    """임시 작업 트리 안의 기존 디렉터리 또는 링크를 제거한다."""
    # 심볼릭 링크의 대상을 따라가 원본을 지우지 않는다.
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _clean_rerun(ctx, metrics, env):
    """HEAD 작업 트리에서 빈 산출물로 재실행하고 비교 후 정리한다."""
    # 현재 소스 변경 여부와 재현 대상 커밋을 명시한다.
    params = ctx.params
    status = subprocess.run(["git", "status", "--porcelain", "--", "src", "config"],
                            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    metrics["source_dirty"] = bool(status.stdout.strip())
    metrics["rerun_source"] = "HEAD (uncommitted src/config changes are excluded)"
    parent = params.get("h10.workspace_parent")
    if parent is not None:
        parent = PROJECT_ROOT / parent
        parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="changwon_h10_", dir=parent))
    metrics["workspace"] = str(workspace)
    git_env = {**env, "GIT_LFS_SKIP_SMUDGE": "1"}
    timeout = params.get("h10.rerun_timeout_s", 3600)

    # 독립 작업 트리에 원본과 외부 CSV를 복사하고 캐시·산출물을 비운다.
    try:
        subprocess.run(["git", "worktree", "add", "--detach", str(workspace), "HEAD"],
                       cwd=PROJECT_ROOT, env=git_env, capture_output=True, text=True, check=True, timeout=timeout)
        for relative in ("data/raw", "data/processed", "artifacts/state", "artifacts/runs"):
            _remove_directory(workspace / relative)
        shutil.copytree(PROJECT_ROOT / "data/raw", workspace / "data/raw")
        (workspace / "data/processed").mkdir(parents=True, exist_ok=True)
        (workspace / "data/external").mkdir(parents=True, exist_ok=True)
        for csv in sorted((PROJECT_ROOT / "data/external").glob("*.csv")):
            shutil.copy2(csv, workspace / "data/external" / csv.name)

        # 전체 실행은 H08 검토까지 수행하고 명령·로그·실행 식별자를 남긴다.
        command = [sys.executable, "-m", "src.pipeline", "run", "--continue-past-approval",
                   "--target", "h08_result_review"]
        metrics["rerun_command"] = command
        try:
            result = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True,
                                    timeout=params.get("h10.rerun_timeout_s", 3600))
            metrics["rerun_returncode"] = result.returncode
            metrics["checks"]["clean_rerun"] = result.returncode == 0
            (ctx.run_dir / "clean_rerun.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        finally:
            manifests = sorted((workspace / "artifacts/runs").glob("*/manifest.json"))
            if manifests:
                manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
                metrics["rerun_run_id"] = manifest.get("run_id")
            patterns = params.get("h10.compare_patterns", DEFAULT_PATTERNS)
            rows = compare_trees(workspace, PROJECT_ROOT, patterns)
            metrics["file_comparisons"] = rows
            metrics["unmatched_patterns"] = [r["pattern"] for r in rows if r["status"] == "missing_pattern"]
            metrics["checks"]["outputs_identical"] = bool(rows) and all(
                row["status"] in {"identical", "content_identical"} for row in rows)
    finally:
        # 정리 중 예상하지 못한 예외도 원래 재실행 오류를 가리지 않는다.
        try:
            _cleanup_workspace(workspace, params, metrics, timeout)
        except Exception as exc:
            metrics["cleanup_ok"] = False
            metrics["leftover_path"] = str(workspace)
            metrics.setdefault("cleanup_errors", []).append(f"cleanup: {type(exc).__name__}: {exc}")


def _cleanup_workspace(workspace, params, metrics, timeout):
    """작업 트리 제거·대체 삭제·등록 정리의 결과를 별도 지표로 보존한다."""
    # 정리 실패는 별도로 보존해 원래 재실행 예외가 가려지지 않게 한다.
    metrics["workspace_kept"] = bool(params.get("h10.keep_workspace", False))
    metrics["cleanup_errors"] = []
    metrics["cleanup_ok"] = True
    metrics["leftover_path"] = str(workspace) if workspace.exists() else None
    if not metrics["workspace_kept"]:
        try:
            subprocess.run(["git", "worktree", "remove", "--force", str(workspace)],
                           cwd=PROJECT_ROOT, capture_output=True, text=True, check=True, timeout=timeout)
        except Exception as exc:
            metrics["cleanup_errors"].append(f"remove: {type(exc).__name__}: {exc}")
            try:
                if workspace.exists():
                    shutil.rmtree(workspace, ignore_errors=False)
            except Exception as fallback_exc:
                metrics["cleanup_ok"] = False
                metrics["cleanup_errors"].append(f"rmtree: {type(fallback_exc).__name__}: {fallback_exc}")
        try:
            subprocess.run(["git", "worktree", "prune"], cwd=PROJECT_ROOT,
                           capture_output=True, text=True, check=True, timeout=timeout)
            listing = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=PROJECT_ROOT,
                                     capture_output=True, text=True, check=True, timeout=timeout)
            if f"worktree {workspace}" in listing.stdout.splitlines():
                metrics["cleanup_ok"] = False
                metrics["cleanup_errors"].append("worktree registration remains")
        except Exception as exc:
            metrics["cleanup_ok"] = False
            metrics["cleanup_errors"].append(f"prune/list: {type(exc).__name__}: {exc}")
        metrics["leftover_path"] = str(workspace) if workspace.exists() else None
        metrics["cleanup_ok"] = metrics["cleanup_ok"] and metrics["leftover_path"] is None

def _holdout_checksum(metrics):
    """리더가 고정한 기준과 최신 홀드아웃·개발 게이트 해시를 비교한다."""
    # 기준 파일은 읽기만 하며 부재 시 리더의 기준 고정을 요구한다.
    reference_path = PROJECT_ROOT / "config/holdout_reference.yaml"
    if not reference_path.is_file():
        raise ValueError("config/holdout_reference.yaml 없음: 리더가 기준을 고정해야 한다")
    reference = yaml.safe_load(reference_path.read_text(encoding="utf-8"))
    for key in ("run_id", "gates_sha256", "development_gates_sha256"):
        if not isinstance(reference, dict) or key not in reference:
            raise ValueError(f"holdout_reference: missing {key}")
    metrics["holdout_reference"] = reference
    folder = PROJECT_ROOT / "artifacts/evaluation/holdout_2022_2024"
    latest = json.loads((folder / "latest.json").read_text(encoding="utf-8"))
    run_id = latest["run_id"]
    if not isinstance(run_id, str) or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("holdout latest.json: invalid run_id")
    summary = json.loads((folder / run_id / "summary.json").read_text(encoding="utf-8"))
    actual = {"run_id": run_id, "gates_sha256": canonical_hash(summary["gates"]),
              "development_gates_sha256": canonical_hash(summary["development_gates"])}
    metrics["holdout_actual"] = actual

    # 실행 식별자 일치는 참고로 남기고 결과 불변은 두 게이트 해시로만 판정한다.
    metrics["holdout_same_run"] = actual["run_id"] == reference["run_id"]
    metrics["checks"]["holdout_checksum_unchanged"] = all(
        actual[key] == reference[key] for key in ("gates_sha256", "development_gates_sha256"))


def _feedback(ctx, metrics):
    """이전 환류 기록을 검증하고 전체 검사 성공 때만 확정 출력에 저장한다."""
    # 기준 파일 내용과 등록부를 사용해 버전별 환류 이력을 만든다.
    previous_path = ctx.outputs[0]
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.is_file() else None
    reference_path = PROJECT_ROOT / "config/holdout_reference.yaml"
    reference = yaml.safe_load(reference_path.read_text(encoding="utf-8")) if reference_path.is_file() else None
    try:
        manifest = build(previous, root=PROJECT_ROOT,
                         registry=load_registry(PROJECT_ROOT / "config/flood_traces.yaml"),
                         model_files=MODEL_FILES, holdout_reference=reference)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        metrics["feedback_errors"] = [error]
        metrics["checks"]["feedback_manifest_valid"] = False
        candidate = ctx.run_dir / "feedback_manifest.candidate.json"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(candidate, {"status": "build_failed", "error": error,
                                      "created_utc": datetime.now(timezone.utc).isoformat()})
        metrics["feedback_path"] = str(candidate)
        raise

    # 빌드 성공 뒤 검증 결과에 따라 최종 또는 후보 기록을 원자적으로 저장한다.
    errors = validate(manifest, PROJECT_ROOT, previous=previous)
    metrics["feedback_errors"] = errors
    metrics["feedback_version"] = manifest["version"]
    metrics["checks"]["feedback_manifest_valid"] = not errors
    destination = (ctx.outputs[0] if all(metrics["checks"].values()) and metrics.get("cleanup_ok", True)
                   else ctx.run_dir / "feedback_manifest.candidate.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, manifest)
    metrics["feedback_path"] = str(destination)


def _notebooks(ctx, metrics, env):
    """노트북을 임시 출력 폴더에 실행하고 오류 셀과 종료 상태를 기록한다."""
    # 선택적으로 생략한 경우에도 생략 이유를 명시한다.
    if not ctx.params.get("h10.run_notebooks", True):
        metrics["notebooks"] = {"skipped": True, "reason": "h10.run_notebooks=false", "error_cells": 0}
        metrics["checks"]["notebooks"] = True
        return

    # 오류 셀을 저장하도록 실행한 뒤 출력 노트북의 오류를 직접 센다.
    records = []
    with tempfile.TemporaryDirectory(prefix="changwon_h10_notebooks_") as folder:
        for notebook in sorted((PROJECT_ROOT / "notebooks").glob("0*.ipynb")):
            command = [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute",
                       "--allow-errors", "--output-dir", folder, "--output", notebook.name, str(notebook)]
            result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
            (ctx.run_dir / f"{notebook.stem}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            output = Path(folder) / notebook.name
            content = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
            errors = sum(out.get("output_type") == "error" for cell in content.get("cells", [])
                         for out in cell.get("outputs", []))
            records.append({"path": str(notebook.relative_to(PROJECT_ROOT)), "error_cells": errors,
                            "returncode": result.returncode, "output_exists": output.is_file()})
    metrics["notebooks"] = {"skipped": False, "files": records,
                            "error_cells": sum(row["error_cells"] for row in records)}
    metrics["checks"]["notebooks"] = all(
        row["returncode"] == 0 and row["output_exists"] and row["error_cells"] == 0 for row in records)


def reproducibility(ctx: StageContext) -> dict:
    """독립 검사를 모두 기록하고 하나라도 실패하면 H10 실패를 보고한다."""
    # 모든 자식 실행에서 홀드아웃 테스트 활성화 변수를 제거한다.
    env = os.environ.copy()
    env.pop("CHANGWON_HOLDOUT_TESTS", None)
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    metrics = {"checks": dict.fromkeys(("unit_tests", "clean_rerun", "outputs_identical",
                                       "holdout_checksum_unchanged", "feedback_manifest_valid", "notebooks"), False),
               "source_dirty": False, "rerun_run_id": None, "file_comparisons": []}
    findings = []

    # 한 검사 실패가 다른 검사의 진단과 기록을 막지 않게 수행한다.
    for name, operation, args in (
        ("unit_tests", _unit_tests, (ctx, metrics, env)),
        ("clean_rerun", _clean_rerun, (ctx, metrics, env)),
        ("holdout_checksum_unchanged", _holdout_checksum, (metrics,)),
        ("notebooks", _notebooks, (ctx, metrics, env)),
        ("feedback_manifest_valid", _feedback, (ctx, metrics)),
    ):
        try:
            operation(*args)
        except Exception as exc:
            metrics["checks"][name] = False
            findings.append({"code": name, "detail": f"{type(exc).__name__}: {exc}"})

    # 실패 검사와 파일별 차이를 runner가 보존할 지표로 전달한다.
    if metrics.get("cleanup_ok") is False:
        findings.append({"code": "cleanup", "detail": "; ".join(metrics.get("cleanup_errors", []))
                         or f"workspace remains: {metrics.get('leftover_path')}"})
    metrics["checks_passed"] = sum(metrics["checks"].values())
    for name, passed in metrics["checks"].items():
        if not passed and not any(f["code"] == name for f in findings):
            findings.append({"code": name, "detail": "H10 check failed; see metrics"})
    if findings:
        raise StageFailed("H10 재현성 기준 미달", findings, metrics=metrics)
    return metrics
