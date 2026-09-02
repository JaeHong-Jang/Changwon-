"""python -m src.pipeline {plan,run,graph,status,approve} — docs/PIPELINE_DAG.md §6"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from src.pipeline import manifest as mf
from src.pipeline.graph import Graph
from src.pipeline.runner import run
from src.utils.config import load_config


def _pad(text: str, width: int) -> str:
    """한글(전각)을 2칸으로 세어 열을 맞춘다."""
    import unicodedata
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(1, width - w)


def cmd_plan(graph: Graph, args: argparse.Namespace) -> int:
    config = load_config()
    upstream: dict[str, dict[str, str]] = {}
    # --only 는 상류를 실행하지 않으므로 runner 와 같은 방식으로 저장된 출력을 빌려 쓴다.
    for dep_id in graph.ancestors(args.only) if args.only else ():
        state = mf.load_state(dep_id)
        upstream[dep_id] = state["outputs"] if state else {"__missing__": dep_id}
    print(f"{'단계':<4}{'이름':<30}{'게이트':<6}{'상태':<10}노드 id")
    for node_id in graph.select(target=args.target, only=args.only, phase=args.phase):
        node = graph.nodes[node_id]
        try:
            fp, _ = mf.node_fingerprint(node, config, upstream)
            cached = mf.is_cached(node, fp)
            status = "cached" if cached else "run"
            # 실행 전이라 출력 checksum을 모르면 하류는 모두 run으로 표시된다.
            upstream[node_id] = mf.load_state(node_id)["outputs"] if cached else {"__pending__": fp}
        except Exception as exc:  # noqa: BLE001
            status = f"error({type(exc).__name__})"
            upstream[node_id] = {"__error__": node_id}
        print(f"{node.phase:<4}{_pad(node.title, 30)}{node.gate:<6}{status:<10}{node_id}")
    return 0


def cmd_run(graph: Graph, args: argparse.Namespace) -> int:
    result = run(graph, target=args.target, only=args.only, phase=args.phase, force=args.force,
                 continue_past_approval=args.continue_past_approval, command=sys.argv)
    for node_id, rec in result["nodes"].items():
        line = f"{_pad(graph.nodes[node_id].title, 30)}{rec['status']:<18}{rec.get('duration_s', 0):>8.2f}s  {node_id}"
        if rec.get("error"):
            line += f"  {rec['error']}"
        print(line)
    if result.get("stopped_at"):
        rec = result["nodes"][result["stopped_at"]]
        if rec.get("next"):
            print(f"\n→ 다음: {rec['next']['goto'] or '분기'} | {rec['next']['action']} | 남은 시도 {rec['next']['attempts_left']}")
    pend = [n for n, r in result["nodes"].items() if r.get("approval_pending")]
    if pend:
        print(f"\n⚠ 승인 미완료 {len(pend)}개 (증거 아님): " + ", ".join(pend))
    print(f"\nrun_id={result['run_id']} status={result['status']} manifest={result['manifest_path']}")
    return 0 if result["status"] == "pass" else 1


def _node_states(graph: Graph) -> dict[str, str]:
    out = {}
    for node_id, node in graph.nodes.items():
        st = mf.load_state(node_id)
        if st is None:
            out[node_id] = "never"
            continue
        out[node_id] = st["status"]
        if node.approval and mf.approval_status(node, st["outputs"]) != "approved":
            out[node_id] = "awaiting_approval"
    return out


def cmd_graph(graph: Graph, args: argparse.Namespace) -> int:
    print(graph.to_mermaid(state=_node_states(graph) if args.with_state else None,
                           detail="overview" if args.overview else "full", phase=args.phase))
    return 0


def cmd_approve(graph: Graph, args: argparse.Namespace) -> int:
    node = graph.nodes.get(args.node)
    if node is None:
        print(f"알 수 없는 노드 {args.node}"); return 2
    if not node.approval:
        print(f"{args.node}에는 approval이 선언되어 있지 않음"); return 2
    st = mf.load_state(args.node)
    if st is None or st.get("status") != "pass":
        print(f"{args.node}가 아직 pass하지 않음 — 먼저 run"); return 1
    path = mf.write_approval(node, st["outputs"], by=args.by, note=args.note, decision=args.decision)
    print(f"{args.decision}: {path.relative_to(mf.PROJECT_ROOT)}  (요구: {node.approval['who']} — {node.approval['what']})")
    print("이 파일을 커밋하세요. outputs가 바뀌면 승인은 자동 무효가 됩니다.")
    return 0


def cmd_status(graph: Graph, args: argparse.Namespace) -> int:
    """노드별 최신 실행 상태. --pending 은 사람이 지금 봐야 할 승인만 추린다."""
    pending: list[tuple[str, str]] = []
    for node_id in graph.order:
        node = graph.nodes[node_id]
        state = mf.load_state(node_id)
        if state is None:
            if not args.pending:
                print(f"{_pad(node.title, 30)}{'미실행':<18}{node_id}")
            continue
        verdict = mf.approval_status(node, state["outputs"]) if node.approval else None
        if verdict and verdict != "approved":
            pending.append((node_id, verdict))
        mark = f" [{verdict}]" if verdict and verdict != "approved" else ""
        if not args.pending:
            print(f"{_pad(node.title, 30)}{state['status'] + mark:<24}{node_id}")

    if pending:
        print(f"\n사람이 봐야 할 승인 {len(pending)}건 — 이게 없으면 하류가 열리지 않는다\n")
        for node_id, verdict in pending:
            node = graph.nodes[node_id]
            print(f"  {node.title}  ({node_id})")
            print(f"    누가   {node.approval['who']}")
            print(f"    무엇을 {node.approval['what']}")
            print(f"    상태   {verdict}")
            for check in node.verify:
                if check["kind"] == "human":
                    print(f"    눈으로 {check['rule']}")
            outputs = mf.load_state(node_id)["outputs"]
            print(f"    근거   {', '.join(sorted(outputs)[:3])}")
            print(f"    승인   python -m src.pipeline approve {node_id} --by <이름> --note '...'")
            print(f"    거부   python -m src.pipeline approve {node_id} --by <이름> --note '...' --decision rejected")
            print()
    elif args.pending:
        print("대기 중인 승인 없음")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m src.pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("run", cmd_run), ("graph", cmd_graph), ("status", cmd_status)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        if name in ("plan", "run"):
            g = p.add_mutually_exclusive_group()
            g.add_argument("--target", help="이 노드와 그 상류까지만")
            g.add_argument("--only", help="이 노드만 (상류 fingerprint는 저장된 것 사용)")
            g.add_argument("--phase", help="이 큰 단계(P1~P4)까지 전부")
        if name == "run":
            p.add_argument("--force", action="store_true", help="캐시·시도 상한 무시하고 재실행")
            p.add_argument("--continue-past-approval", action="store_true",
                           help="개발용: 승인 대기 노드에서 멈추지 않고 계속. manifest 에 approval_bypassed=true 로 남아 증거로 쓸 수 없음")
        if name == "status":
            p.add_argument("--pending", action="store_true", help="사람이 봐야 할 승인만 표시")
        if name == "graph":
            p.add_argument("--with-state", action="store_true", help="노드별 현재 상태 색으로 표시")
            p.add_argument("--overview", action="store_true", help="규칙 문장 없이 한 장짜리 개요도")
            p.add_argument("--phase", help="이 단계(P1~P4)만 상세히")
    ap = sub.add_parser("approve", help="pass한 노드의 outputs에 대해 사람 승인/거부 기록")
    ap.set_defaults(fn=cmd_approve)
    ap.add_argument("node")
    ap.add_argument("--by", required=True, help="승인자 (R1/R2/R3 또는 이름)")
    ap.add_argument("--note", required=True, help="무엇을 확인했는지")
    ap.add_argument("--decision", choices=["approved", "rejected"], default="approved")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return args.fn(Graph.load(), args)


if __name__ == "__main__":
    sys.exit(main())
