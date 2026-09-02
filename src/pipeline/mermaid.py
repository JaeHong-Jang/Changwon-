"""Graph 를 mermaid flowchart 로 그린다. DAG 로직과 렌더링을 분리해 둔 파일이다.

라벨 안 자유 텍스트는 반드시 `escape()` 를 거쳐야 한다. YAML 설명에 따옴표가 들어가면
mermaid 파서가 그 지점에서 멈추고 그림 전체가 원문 텍스트로 떨어진다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.pipeline.graph import Graph

KIND_ICONS = {"code": "⚙ 코드검사", "external": "🧪 외부증거", "human": "👁 사람검수"}

INIT = '%%{init: {"flowchart": {"useMaxWidth": false, "htmlLabels": true, "curve": "basis"}}}%%'

STYLES = [
    "    classDef verify fill:#fff4d6,stroke:#c98a00,color:#000",
    "    classDef approval fill:#ffe0e0,stroke:#c00000,stroke-width:2px,color:#000",
    "    classDef branch fill:#eee,stroke:#888,stroke-dasharray:4 2,color:#000",
    "    classDef stub fill:#f0f0f0,stroke:#aaa,stroke-dasharray:2 2,color:#666",
    "    classDef st_pass fill:#d9f2d9,stroke:#2e7d32,color:#000",
    "    classDef st_cached fill:#e3f2fd,stroke:#1565c0,color:#000",
    "    classDef st_fail fill:#ffcdd2,stroke:#b71c1c,color:#000",
    "    classDef st_awaiting_approval fill:#ffe0b2,stroke:#e65100,color:#000",
    "    classDef st_exhausted fill:#ef9a9a,stroke:#b71c1c,stroke-width:3px,color:#000",
]


def escape(text: str) -> str:
    """mermaid 라벨용 이스케이프. 세미콜론을 먼저 바꿔야 뒤 엔티티가 망가지지 않는다."""
    return (
        str(text)
        .replace(";", "#59;")
        .replace("&", "#amp;")
        .replace('"', "#quot;")
        .replace("<", "#lt;")
        .replace(">", "#gt;")
        .replace("\n", " ")
    )


def render(
    graph: "Graph",
    *,
    state: dict[str, str] | None = None,
    detail: str = "full",
    phase: str | None = None,
) -> str:
    """detail="overview" 는 라벨을 줄인 한 장짜리, "full" 은 규칙까지 적은 상세도.

    phase 를 주면 그 단계만 그리고, 다른 단계로 가는 엣지는 회색 stub 으로 표시한다.
    useMaxWidth=false 로 원래 크기에 그린다 — 화면 폭에 맞춰 축소되면 글자가 사라진다.
    """
    state = state or {}
    full = detail == "full"
    members = [n for n in graph.nodes.values() if phase is None or n.phase == phase]
    member_ids = {n.id for n in members}
    lines = [INIT, "flowchart TD"]

    # ── 노드: 사각형 + 검증 마름모 + 승인 육각형 ──────────────────────────
    by_phase: dict[str, list] = {}
    for node in members:
        by_phase.setdefault(node.phase, []).append(node)

    for ph, group in by_phase.items():
        wrap = ph and phase is None
        if wrap:
            lines.append(f'    subgraph {ph}["{ph} {graph.phases.get(ph, {}).get("title", "")}"]')
            lines.append("    direction TB")
        for n in group:
            opt = " (옵션)" if n.optional else ""
            head = f"<b>{escape(n.title)}</b>"
            body = f"<br/><small>{n.id} · {n.gate}{opt}</small><br/><i>{escape(n.description)}</i>" if full \
                else f"<br/><small>{n.gate}{opt}</small>"
            lines.append(f'    {n.id}["{head}{body}"]')

            if n.verify:
                rules = (
                    "<br/>".join(f'{KIND_ICONS[v["kind"]].split()[0]} {escape(v["rule"])}' for v in n.verify)
                    if full
                    else "<br/>".join(dict.fromkeys(KIND_ICONS[v["kind"]] for v in n.verify))
                )
                lines += [
                    f'    {n.id}__v{{"검증<br/>{rules}"}}',
                    f"    {n.id} --> {n.id}__v",
                    f"    class {n.id}__v verify",
                ]

            if n.approval:
                who = escape(n.approval["who"])
                label = f'✋ {who} 승인<br/>{escape(n.approval["what"])}' if full else f"✋ {who}"
                lines += [
                    f'    {n.id}__a{{{{"{label}"}}}}',
                    f"    {f'{n.id}__v' if n.verify else n.id} -->|통과| {n.id}__a",
                    f"    class {n.id}__a approval",
                ]
        if wrap:
            lines.append("    end")

    # ── 단계 밖으로 나가는 노드는 회색 stub ────────────────────────────────
    outside = {
        other
        for n in members
        for other in list(n.depends_on) + [(n.on_fail or {}).get("goto")]
        if other and other not in member_ids
    }
    for other in sorted(outside):
        node = graph.nodes[other]
        lines += [
            f'    {other}(["{escape(node.title)}<br/>{node.phase} 단계"])',
            f"    class {other} stub",
        ]

    # ── 엣지: 의존은 그 노드의 마지막 게이트(승인 > 검증 > 노드)에서 나간다 ──
    def exit_of(node_id: str) -> str:
        if node_id not in member_ids:
            return node_id
        node = graph.nodes[node_id]
        return f"{node_id}__a" if node.approval else (f"{node_id}__v" if node.verify else node_id)

    for n in members:
        lines += [f"    {exit_of(dep)} --> {n.id}" for dep in n.depends_on]

    # ── 실패 시 되돌아가는 점선 (goto 없으면 분기 상자) ─────────────────────
    for n in members:
        if not n.on_fail:
            continue
        src = f"{n.id}__v" if n.verify else n.id
        limit = n.on_fail["max_iterations"]
        action = escape(n.on_fail.get("action", ""))
        if goto := n.on_fail.get("goto"):
            label = f"실패 시 (최대 {limit}회): {action}" if full else f"실패 시 (최대 {limit}회)"
            lines.append(f'    {src} -. "{label}" .-> {goto}')
        else:
            lines += [
                f'    {n.id}__branch["{f"↳ 분기: {action}" if full else "분기"}"]',
                f'    {src} -. "실패 시 (최대 {limit}회)" .-> {n.id}__branch',
                f"    class {n.id}__branch branch",
            ]

    lines += [f"    class {nid} st_{st}" for nid, st in state.items() if nid in member_ids]
    lines += STYLES
    return "\n".join(lines)
