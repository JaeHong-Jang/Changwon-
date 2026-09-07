"""fingerprint 계산과 run manifest 기록 (docs/RESEARCH_HARNESS.md §4의 완료 증거 규격)."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data.validate_raw import git_commit, git_worktree_provenance, sha256_file
from src.pipeline.graph import Graph, Node
from src.utils.config import PROJECT_ROOT

ARTIFACTS = PROJECT_ROOT / "artifacts"
RUNS_DIR = ARTIFACTS / "runs"
STATE_DIR = ARTIFACTS / "state"  # 노드별 최신 성공 fingerprint (캐시 판정용)
APPROVALS_DIR = ARTIFACTS / "approvals"  # 사람 승인 기록 — Git 추적 대상 (거부권 행사 증거)


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_paths(patterns: tuple[str, ...] | list[str]) -> list[Path]:
    """프로젝트 루트 기준 glob을 펼쳐 정렬된 파일 목록으로. 없는 파일은 그냥 빠진다."""
    found: set[Path] = set()
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            found.update(p for p in PROJECT_ROOT.glob(pattern) if p.is_file())
        else:
            p = PROJECT_ROOT / pattern
            if p.is_file():
                found.add(p)
    return sorted(found)


def checksum_paths(paths: list[Path]) -> dict[str, str]:
    return {str(p.relative_to(PROJECT_ROOT)): sha256_file(p) for p in paths}


def config_params(config: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        cur: Any = config
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                raise KeyError(f"config.yaml에 없는 param: {key}")
            cur = cur[part]
        out[key] = cur
    return out


def runner_code_sha(runner: str) -> dict[str, str]:
    """runner 가 (간접적으로라도) 끌어오는 프로젝트 내부 모듈 전부의 sha256.

    runner 모듈 하나만 해싱하면 임계값이 있는 src/data/quality.py 를 고쳐도
    fingerprint 가 그대로여서, 새 기준으로 검증하지 않은 결과가 캐시로 통과한다.
    임계치 완화가 승인 없이 반영되는 경로이기도 해서 반드시 막아야 한다.
    """
    module_name = runner.split(":", 1)[0]
    importlib.import_module(module_name)
    files: dict[str, str] = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("src."):
            continue
        path = getattr(module, "__file__", None)
        if not path:
            continue
        resolved = Path(path).resolve()
        if resolved.is_relative_to(PROJECT_ROOT) and resolved.exists():
            files[str(resolved.relative_to(PROJECT_ROOT))] = sha256_file(resolved)
    return dict(sorted(files.items()))


def node_fingerprint(
    node: Node, config: dict[str, Any], upstream: dict[str, dict[str, str]]
) -> tuple[str, dict[str, Any]]:
    """노드 fingerprint와 그 근거를 반환.

    upstream은 {dep_id: 그 노드 outputs의 checksum}. 상류가 재실행돼도 결과 파일이
    byte 단위로 같으면 하류는 재실행하지 않고, 결과가 달라지면 반드시 재실행한다.
    """
    inputs = checksum_paths(resolve_paths(node.inputs))
    basis = {
        "spec": node.spec,
        "code_sha256": runner_code_sha(node.runner),
        "params": config_params(config, node.params),
        "inputs": inputs,
        # optional 상류가 실패(skipped)하면 그 노드의 outputs 가 없다. 하류를 KeyError 로
        # 죽이지 않고 "없음"을 fingerprint 에 남긴다 — 나중에 그 상류가 성공하면 값이 바뀌어
        # 하류가 자동으로 다시 돈다.
        "upstream": {dep: upstream.get(dep, {"__unavailable__": True}) for dep in node.depends_on},
    }
    return _sha_text(json.dumps(basis, sort_keys=True, ensure_ascii=False)), basis


def load_state(node_id: str) -> dict[str, Any] | None:
    path = STATE_DIR / f"{node_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(node_id: str, record: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{node_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_cached(node: Node, fingerprint: str) -> bool:
    """fingerprint가 같고 기록된 outputs가 그대로 있으면 캐시 적중."""
    state = load_state(node.id)
    if state is None or state.get("status") != "pass" or state.get("fingerprint") != fingerprint:
        return False
    for rel, sha in state.get("outputs", {}).items():
        p = PROJECT_ROOT / rel
        if not p.exists() or sha256_file(p) != sha:
            return False
    return True


def new_run_id(config_path: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    commit = (git_commit() or "nogit")[:7]
    return f"{stamp}-{commit}-{sha256_file(config_path)[:8]}"


def environment_provenance(config_path: Path, graph: Graph, command: list[str]) -> dict[str, Any]:
    req = PROJECT_ROOT / "requirements.txt"
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        **git_worktree_provenance(),
        "command": command,
        "python": sys.version,
        "platform": platform.platform(),
        "config_sha256": sha256_file(config_path),
        "pipeline_sha256": sha256_file(graph.source) if graph.source else None,
        "requirements_sha256": sha256_file(req) if req.exists() else None,
    }


def write_manifest(run_dir: Path, manifest: dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ----- 사람 승인 -----
def outputs_digest(outputs: dict[str, str]) -> str:
    """승인은 '이 outputs 묶음'에 대해서만 유효하다."""
    return _sha_text(json.dumps(outputs, sort_keys=True))


def load_approval(node_id: str) -> dict[str, Any] | None:
    path = APPROVALS_DIR / f"{node_id}.yaml"
    if not path.exists():
        return None
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def approval_status(node: Node, outputs: dict[str, str]) -> str:
    """'approved' | 'awaiting_approval' | 'stale_approval' | 'rejected'.

    rejected 는 사람이 명시적으로 거부한 상태다. 승인 없음(awaiting)과 구분해야
    --continue-past-approval 같은 개발용 우회로도 뚫지 못하게 막을 수 있다.
    """
    rec = load_approval(node.id)
    if rec is None:
        return "awaiting_approval"
    if rec.get("decision") != "approved":
        return "rejected"
    if rec.get("outputs_digest") != outputs_digest(outputs):
        return "stale_approval"
    return "approved"


def write_approval(node: Node, outputs: dict[str, str], *, by: str, note: str, decision: str = "approved") -> Path:
    import yaml

    APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    path = APPROVALS_DIR / f"{node.id}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "node": node.id,
                "gate": node.gate,
                "decision": decision,
                "required_from": node.approval["who"] if node.approval else None,
                "approved_by": by,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "note": note,
                "git_commit": git_commit(),
                "outputs_digest": outputs_digest(outputs),
                "outputs": outputs,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


# ----- 실패 시도 횟수 (fingerprint 단위: 입력이 바뀌면 0부터) -----
def _attempts_path(node_id: str) -> Path:
    return STATE_DIR / f"{node_id}.attempts.json"


def load_attempts(node_id: str, fingerprint: str) -> int:
    path = _attempts_path(node_id)
    if not path.exists():
        return 0
    rec = json.loads(path.read_text(encoding="utf-8"))
    return rec.get("failures", 0) if rec.get("fingerprint") == fingerprint else 0


def record_attempt(node_id: str, fingerprint: str) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    n = load_attempts(node_id, fingerprint) + 1
    _attempts_path(node_id).write_text(
        json.dumps({"fingerprint": fingerprint, "failures": n,
                    "last_failed_at": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )
    return n
