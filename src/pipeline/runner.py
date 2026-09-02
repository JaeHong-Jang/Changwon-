"""노드를 위상 순서로 실행한다. fail-fast, 캐시 건너뛰기, run manifest 기록."""

from __future__ import annotations

import importlib
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.pipeline import manifest as mf
from src.pipeline.graph import Graph, Node
from src.utils.config import PROJECT_ROOT, load_config

log = logging.getLogger("pipeline")


class StageFailed(RuntimeError):
    """runner가 게이트 통과 기준을 못 맞췄을 때 던진다. findings에 근거를 남긴다."""

    def __init__(
        self,
        message: str,
        findings: list[dict[str, Any]] | None = None,
        metrics: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.findings = findings or []
        # 실패해도 "왜"를 설명하는 숫자는 manifest 에 남긴다.
        self.metrics = metrics or {}


@dataclass
class StageContext:
    """runner 함수가 받는 유일한 인자."""

    node: Node
    run_id: str
    run_dir: Path                 # artifacts/runs/<run_id>/<node_id>/ — 로그·중간 지표 저장처
    config: dict[str, Any]
    params: dict[str, Any]        # node.params를 config에서 뽑은 값
    inputs: list[Path]            # 존재하는 입력 파일 (glob 해제됨)
    outputs: list[Path]           # 생성해야 할 출력 파일 (절대경로)
    metrics: dict[str, Any] = field(default_factory=dict)

    def path(self, rel: str) -> Path:
        return PROJECT_ROOT / rel


def _load_runner(spec: str) -> Callable[[StageContext], dict[str, Any] | None]:
    module_name, func_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, func_name)


def _missing_outputs(node: Node) -> list[str]:
    return [o for o in node.outputs if not (PROJECT_ROOT / o).exists()]


def run(
    graph: Graph,
    *,
    target: str | None = None,
    only: str | None = None,
    phase: str | None = None,
    force: bool = False,
    continue_past_approval: bool = False,
    config_path: Path | None = None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    """선택된 노드를 실행하고 manifest dict를 반환. 실패 노드 이후는 실행하지 않는다."""
    config_path = config_path or PROJECT_ROOT / "config" / "config.yaml"
    config = load_config(config_path)
    run_id = mf.new_run_id(config_path)
    run_dir = mf.RUNS_DIR / run_id
    selected = graph.select(target=target, only=only, phase=phase)

    manifest: dict[str, Any] = {
        **mf.environment_provenance(config_path, graph, command or []),
        "run_id": run_id,
        "selected": selected,
        "approval_bypassed": continue_past_approval,  # true 면 이 run 은 완료 증거가 아니다 (개발용 dry run)
        "status": "pass",
        "nodes": {},
    }
    upstream: dict[str, dict[str, str]] = {}
    # only 모드에서는 상류를 실행하지 않으므로 저장된 출력 checksum을 빌려 쓴다.
    for dep_id in graph.ancestors(only) if only else ():
        state = mf.load_state(dep_id)
        upstream[dep_id] = state["outputs"] if state else {"__missing__": dep_id}

    for node_id in selected:
        node = graph.nodes[node_id]
        record: dict[str, Any] = {"gate": node.gate, "status": None}
        ctx_ref: StageContext | None = None  # 실패해도 ctx.metrics 를 증거로 남기기 위해
        started = time.perf_counter()
        try:
            fingerprint, basis = mf.node_fingerprint(node, config, upstream)
            record["fingerprint"] = fingerprint
            record["inputs"] = basis["inputs"]
            record["params"] = basis["params"]

            attempts = mf.load_attempts(node_id, fingerprint)
            record["attempt"] = attempts + 1
            if node.max_iterations is not None and attempts >= node.max_iterations and not force:
                record["status"] = "exhausted"
                record["error"] = (
                    f"같은 입력으로 {attempts}회 실패 — on_fail.max_iterations={node.max_iterations} 초과. "
                    f"{node.on_fail.get('action', '')} / 상한 넘겨 재시도하려면 --force"
                )
                log.error("[%s] %s", node_id, record["error"])
            elif not force and mf.is_cached(node, fingerprint):
                record["status"] = "cached"
                record["outputs"] = mf.load_state(node_id)["outputs"]
                log.info("[%s] 캐시 적중 — 건너뜀", node_id)
            else:
                ctx = ctx_ref = StageContext(
                    node=node,
                    run_id=run_id,
                    run_dir=run_dir / node_id,
                    config=config,
                    params=basis["params"],
                    inputs=[PROJECT_ROOT / p for p in basis["inputs"]],
                    outputs=[PROJECT_ROOT / o for o in node.outputs],
                )
                ctx.run_dir.mkdir(parents=True, exist_ok=True)
                record["started_at"] = datetime.now(timezone.utc).isoformat()
                log.info("[%s] 실행 시작 (%s)", node_id, node.gate)
                metrics = _load_runner(node.runner)(ctx) or {}
                record["metrics"] = {**ctx.metrics, **metrics}
                missing = _missing_outputs(node)
                if missing:
                    raise StageFailed(
                        f"선언된 출력이 생성되지 않음: {missing}",
                        [{"code": "missing_output", "path": m} for m in missing],
                    )
                record["outputs"] = mf.checksum_paths([PROJECT_ROOT / o for o in node.outputs])
                record["status"] = "pass"
                mf.save_state(
                    node_id,
                    {
                        "run_id": run_id,
                        "status": "pass",
                        "fingerprint": fingerprint,
                        "outputs": record["outputs"],
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            if record["status"] in ("pass", "cached") and node.approval:
                verdict = mf.approval_status(node, record["outputs"])
                record["approval"] = verdict
                if verdict != "approved" and continue_past_approval and verdict != "rejected":
                    record["approval_pending"] = True
                    log.warning("[%s] 승인 미완료지만 --continue-past-approval 로 계속 (증거 아님)", node_id)
                elif verdict != "approved":
                    record["status"] = "rejected" if verdict == "rejected" else "awaiting_approval"
                    if verdict == "rejected":
                        record["error"] = (
                            f"{node.approval['who']} 가 거부했다: artifacts/approvals/{node_id}.yaml 의 "
                            f"note 를 보고 문제를 고친 뒤 다시 승인받아야 한다 (--continue-past-approval 로도 못 넘긴다)"
                        )
                    else:
                        record["error"] = (
                            f"{node.approval['who']} 승인 필요: {node.approval['what']} → "
                            f"python -m src.pipeline approve {node_id} --by <이름> --note '...'"
                            + (" (outputs가 바뀌어 기존 승인 무효)" if verdict == "stale_approval" else "")
                        )
                    log.warning("[%s] %s", node_id, record["error"])
            if record["status"] in ("pass", "cached"):
                upstream[node_id] = record["outputs"]
        except StageFailed as exc:
            record["status"] = "skipped" if node.optional else "fail"
            record["error"] = str(exc)
            record["findings"] = exc.findings
            if exc.metrics or (ctx_ref and ctx_ref.metrics):
                record["metrics"] = {**(ctx_ref.metrics if ctx_ref else {}), **exc.metrics}
            log.error("[%s] 게이트 실패: %s", node_id, exc)
        except NotImplementedError as exc:
            record["status"] = "skipped" if node.optional else "fail"
            record["error"] = f"미구현: {exc}"
            log.error("[%s] 미구현 단계", node_id)
        except Exception as exc:  # noqa: BLE001 — 무엇이든 manifest에 남기고 중단
            record["status"] = "skipped" if node.optional else "fail"
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = traceback.format_exc()
            log.exception("[%s] 예외", node_id)
        finally:
            record["duration_s"] = round(time.perf_counter() - started, 3)
            if record["status"] in ("fail", "skipped") and "fingerprint" in record:
                mf.record_attempt(node_id, record["fingerprint"])
                if node.on_fail:
                    record["next"] = {
                        "goto": node.on_fail.get("goto"),
                        "action": node.on_fail.get("action"),
                        "attempts_left": (
                            None if node.max_iterations is None else max(0, node.max_iterations - record["attempt"])
                        ),
                    }
            manifest["nodes"][node_id] = record

        if record["status"] in ("fail", "exhausted", "awaiting_approval", "rejected"):
            manifest["status"] = record["status"]
            manifest["stopped_at"] = node_id
            break

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["manifest_path"] = str(mf.write_manifest(run_dir, manifest).relative_to(PROJECT_ROOT))
    return manifest
