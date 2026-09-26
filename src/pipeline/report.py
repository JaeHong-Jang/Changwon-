"""노트북에서 그래프 상태와 실행 지표를 꺼내 보는 헬퍼."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from src.pipeline import manifest as mf
from src.pipeline.graph import Graph


def node_table(*node_ids: str) -> pd.DataFrame:
    """노드의 선언(검증·승인·복구)과 최신 실행 상태를 한 표로."""
    graph = Graph.load()
    rows = []
    for node_id in node_ids:
        node = graph.nodes[node_id]
        state = mf.load_state(node_id) or {}
        rows.append({
            "이름": node.title,
            "게이트": node.gate,
            "상태": state.get("status", "미실행"),
            "검증": " / ".join(v["kind"] for v in node.verify) or "-",
            "승인": (node.approval or {}).get("who", "-"),
            "실패 시": (node.on_fail or {}).get("goto", "분기"),
            "node_id": node_id,
        })
    return pd.DataFrame(rows)


def node_metrics(node_id: str) -> dict[str, Any]:
    """이 노드의 metrics 가 담긴 가장 최근 run manifest 를 찾아 돌려준다."""
    for path in sorted(mf.RUNS_DIR.glob("*/manifest.json"), reverse=True):
        run = json.loads(path.read_text(encoding="utf-8"))
        node = run.get("nodes", {}).get(node_id)
        if node and node.get("metrics"):
            return node["metrics"]
    return {}
