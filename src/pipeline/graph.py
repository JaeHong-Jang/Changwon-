"""config/pipeline.yaml을 읽어 DAG를 검증하고 실행 순서를 만든다."""

from __future__ import annotations

from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

import yaml

from src.utils.config import PROJECT_ROOT

NODE_FIELDS = {"gate", "phase", "title", "description", "runner", "depends_on", "inputs", "outputs", "params", "optional",
               "verify", "approval", "on_fail"}
VERIFY_KINDS = {"code", "external", "human"}
REQUIRED_FIELDS = {"gate", "phase", "runner", "outputs"}


class GraphError(ValueError):
    """DAG 선언 자체가 잘못됐을 때 (순환, 미정의 의존, 출력 중복 등)."""


@dataclass(frozen=True)
class Node:
    id: str
    gate: str
    phase: str
    runner: str
    title: str = ""          # 한글 이름 (없으면 id)
    description: str = ""
    depends_on: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    params: tuple[str, ...] = ()
    optional: bool = False
    verify: tuple[dict[str, str], ...] = ()          # [{kind, rule}]
    approval: dict[str, str] | None = None           # {who, what}
    on_fail: dict[str, Any] | None = None            # {goto?, max_iterations, action}

    @property
    def max_iterations(self) -> int | None:
        return (self.on_fail or {}).get("max_iterations")

    @property
    def spec(self) -> dict[str, Any]:
        """fingerprint에 들어가는 선언 내용."""
        return {
            "gate": self.gate,
            "phase": self.phase,
            "runner": self.runner,
            "depends_on": list(self.depends_on),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "params": list(self.params),
        }


@dataclass
class Graph:
    nodes: dict[str, Node]
    phases: dict[str, dict[str, str]] = field(default_factory=dict)  # 선언 순서 = 단계 순서
    source: Path | None = None
    order: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self._validate()
        try:
            # 동일 위상 내에서는 선언 순서를 유지해 실행 순서를 결정적으로 만든다.
            ts = TopologicalSorter({n.id: list(n.depends_on) for n in self.nodes.values()})
            self.order = list(ts.static_order())
        except CycleError as exc:
            raise GraphError(f"순환 의존: {' -> '.join(exc.args[1])}") from exc

    @classmethod
    def load(cls, path: Path | None = None) -> "Graph":
        path = path or PROJECT_ROOT / "config" / "pipeline.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        graph = cls.load_from_dict(raw)
        graph.source = path
        return graph

    @classmethod
    def load_from_dict(cls, raw: dict[str, Any]) -> "Graph":
        if raw.get("version") != 1:
            raise GraphError(f"지원하지 않는 pipeline.yaml version: {raw.get('version')}")
        phases = raw.get("phases") or {}
        nodes: dict[str, Node] = {}
        for node_id, spec in (raw.get("nodes") or {}).items():
            unknown = set(spec) - NODE_FIELDS
            if unknown:
                raise GraphError(f"{node_id}: 알 수 없는 필드 {sorted(unknown)}")
            missing = REQUIRED_FIELDS - set(spec)
            if missing:
                raise GraphError(f"{node_id}: 필수 필드 누락 {sorted(missing)}")
            nodes[node_id] = Node(
                id=node_id,
                gate=str(spec["gate"]),
                phase=str(spec["phase"]),
                runner=str(spec["runner"]),
                title=str(spec.get("title") or node_id),
                description=str(spec.get("description", "")),
                depends_on=tuple(spec.get("depends_on") or ()),
                inputs=tuple(spec.get("inputs") or ()),
                outputs=tuple(spec.get("outputs") or ()),
                params=tuple(spec.get("params") or ()),
                optional=bool(spec.get("optional", False)),
                verify=tuple(spec.get("verify") or ()),
                approval=spec.get("approval"),
                on_fail=spec.get("on_fail"),
            )
        return cls(nodes=nodes, phases=phases)

    def phase_index(self, phase: str) -> int:
        return list(self.phases).index(phase)

    def _validate(self) -> None:
        seen_outputs: dict[str, str] = {}
        for node in self.nodes.values():
            if self.phases and node.phase not in self.phases:
                raise GraphError(f"{node.id}: 선언되지 않은 phase '{node.phase}' (phases: {list(self.phases)})")
            for dep in node.depends_on:
                if self.phases and dep in self.nodes and self.phase_index(self.nodes[dep].phase) > self.phase_index(node.phase):
                    raise GraphError(f"{node.id}({node.phase}): 뒤 단계 노드 '{dep}'({self.nodes[dep].phase})에 의존할 수 없음")
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise GraphError(f"{node.id}: 정의되지 않은 의존 노드 '{dep}'")
                if dep == node.id:
                    raise GraphError(f"{node.id}: 자기 자신에 의존")
            if ":" not in node.runner:
                raise GraphError(f"{node.id}: runner는 '모듈:함수' 형식이어야 함 ({node.runner})")
            if not node.outputs:
                raise GraphError(f"{node.id}: outputs가 비어 있음 — 게이트 판정 불가")
            for v in node.verify:
                if v.get("kind") not in VERIFY_KINDS or not v.get("rule"):
                    raise GraphError(f"{node.id}: verify 항목은 kind∈{sorted(VERIFY_KINDS)}와 rule이 필요 ({v})")
            if node.approval is not None and not (node.approval.get("who") and node.approval.get("what")):
                raise GraphError(f"{node.id}: approval에는 who·what이 필요")
            if node.on_fail is not None:
                goto = node.on_fail.get("goto")
                if goto is not None and goto not in self.nodes:
                    raise GraphError(f"{node.id}: on_fail.goto가 정의되지 않은 노드 '{goto}'")
                if goto is not None and goto != node.id and goto not in self.ancestors(node.id):
                    raise GraphError(f"{node.id}: on_fail.goto '{goto}'는 자기 자신 또는 상류여야 함 (순방향 점프 금지)")
                if not isinstance(node.on_fail.get("max_iterations"), int):
                    raise GraphError(f"{node.id}: on_fail.max_iterations(int) 필요")
            for out in node.outputs:
                if out in seen_outputs:
                    raise GraphError(f"출력 중복: '{out}' ← {seen_outputs[out]}, {node.id}")
                seen_outputs[out] = node.id

    # ----- 부분 그래프 선택 -----
    def ancestors(self, node_id: str) -> set[str]:
        out: set[str] = set()
        stack = [node_id]
        while stack:
            for dep in self.nodes[stack.pop()].depends_on:
                if dep not in out:
                    out.add(dep)
                    stack.append(dep)
        return out

    def descendants(self, node_id: str) -> set[str]:
        out: set[str] = set()
        changed = True
        while changed:
            changed = False
            for node in self.nodes.values():
                if node.id not in out and (set(node.depends_on) & (out | {node_id})):
                    out.add(node.id)
                    changed = True
        return out

    def select(self, target: str | None = None, only: str | None = None, phase: str | None = None) -> list[str]:
        """실행할 노드를 위상 순서로 반환. target=해당 노드까지, only=그 노드만, phase=그 단계까지 전부."""
        if target and target not in self.nodes:
            raise GraphError(f"알 수 없는 노드 '{target}'")
        if only and only not in self.nodes:
            raise GraphError(f"알 수 없는 노드 '{only}'")
        if phase and phase not in self.phases:
            raise GraphError(f"알 수 없는 phase '{phase}'")
        if only:
            return [only]
        if phase:
            limit = self.phase_index(phase)
            return [n for n in self.order if self.phase_index(self.nodes[n].phase) <= limit]
        if target:
            wanted = self.ancestors(target) | {target}
            return [n for n in self.order if n in wanted]
        return list(self.order)

    def to_mermaid(self, **kwargs) -> str:
        """mermaid 그림 생성. 구현은 src/pipeline/mermaid.py 에 있다."""
        from src.pipeline.mermaid import render

        return render(self, **kwargs)
