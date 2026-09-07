from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.pipeline import manifest as mf
from src.pipeline.graph import Graph, GraphError
from src.pipeline.runner import StageContext, StageFailed, run

# 테스트용 runner — 모듈 수준 함수여야 "모듈:함수" 로 로드된다.
CALLS: list[str] = []


def ok_stage(ctx: StageContext) -> dict:
    CALLS.append(ctx.node.id)
    for out in ctx.outputs:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(ctx.node.id, encoding="utf-8")
    return {"wrote": len(ctx.outputs)}


def ok_stage_v2(ctx: StageContext) -> dict:
    CALLS.append(ctx.node.id)
    for out in ctx.outputs:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(ctx.node.id + "-v2", encoding="utf-8")
    return {}


def failing_stage(ctx: StageContext) -> dict:
    CALLS.append(ctx.node.id)
    ctx.metrics["seen"] = 7
    raise StageFailed("기준 미달", [{"code": "x"}], metrics={"why": 42})


def forgetful_stage(ctx: StageContext) -> dict:
    CALLS.append(ctx.node.id)
    return {}


def build(nodes: dict) -> Graph:
    return Graph.load_from_dict({"version": 1, "nodes": nodes})


class GraphTest(unittest.TestCase):
    def test_topological_order_and_select(self) -> None:
        g = build({
            "a": {"gate": "H01", "phase": "P1", "runner": "m:f", "outputs": ["o/a"]},
            "b": {"gate": "H02", "phase": "P1", "runner": "m:f", "outputs": ["o/b"], "depends_on": ["a"]},
            "c": {"gate": "H02", "phase": "P1", "runner": "m:f", "outputs": ["o/c"], "depends_on": ["a"]},
            "d": {"gate": "H03", "phase": "P1", "runner": "m:f", "outputs": ["o/d"], "depends_on": ["b", "c"]},
        })
        self.assertEqual(g.order[0], "a")
        self.assertEqual(g.order[-1], "d")
        self.assertEqual(g.select(target="b"), ["a", "b"])
        self.assertEqual(g.select(only="d"), ["d"])
        self.assertEqual(g.ancestors("d"), {"a", "b", "c"})
        self.assertEqual(g.descendants("b"), {"d"})

    def test_rejects_cycle_unknown_dep_and_duplicate_output(self) -> None:
        with self.assertRaises(GraphError):
            build({
                "a": {"gate": "H", "phase": "P1", "runner": "m:f", "outputs": ["o/a"], "depends_on": ["b"]},
                "b": {"gate": "H", "phase": "P1", "runner": "m:f", "outputs": ["o/b"], "depends_on": ["a"]},
            })
        with self.assertRaises(GraphError):
            build({"a": {"gate": "H", "phase": "P1", "runner": "m:f", "outputs": ["o/a"], "depends_on": ["zzz"]}})
        with self.assertRaises(GraphError):
            build({
                "a": {"gate": "H", "phase": "P1", "runner": "m:f", "outputs": ["same"]},
                "b": {"gate": "H", "phase": "P1", "runner": "m:f", "outputs": ["same"]},
            })
        with self.assertRaises(GraphError):
            build({"a": {"gate": "H", "phase": "P1", "runner": "no_colon", "outputs": ["o/a"]}})

    def test_fingerprint_covers_logic_modules_not_just_runner(self) -> None:
        """runner 가 import 하는 프로젝트 모듈이 바뀌면 fingerprint 도 바뀌어야 한다.

        임계값은 stage 가 아니라 src/data 에 있으므로, runner 파일만 해싱하면
        기준을 고쳐도 캐시가 살아남아 검증되지 않은 결과가 증거로 남는다.
        """
        node = Graph.load().nodes["h02_eda_data_check"]
        files = mf.runner_code_sha(node.runner)
        self.assertIn("src/stages/h02_eda.py", files)
        self.assertIn("src/data/quality.py", files, "임계값이 있는 모듈이 fingerprint 에 없다")

    def test_real_pipeline_yaml_loads(self) -> None:
        g = Graph.load()
        self.assertIn("h01_raw_contract", g.nodes)
        self.assertEqual(g.nodes[g.order[0]].phase, "P1")
        self.assertEqual(g.nodes[g.order[0]].gate, "H00")
        self.assertEqual(list(g.phases), ["P1", "P2", "P3", "P4"])
        self.assertTrue(g.nodes["h09_alert_draft"].optional)
        # 단계 선택: P1 까지 = 수집 확인 + 원본 계약
        p1 = g.select(phase="P1")
        self.assertEqual(len(p1), 12)  # 접근신청 1 + 수집 5 + 묶음검증 5 + 종합 1
        self.assertEqual(p1[-1], "h01_raw_contract")
        # 데이터 원인 루프는 '그 묶음의' 수집까지 되돌아간다
        self.assertEqual(g.nodes["h02_rainfall_long"].on_fail["goto"], "h00_collect_rainfall")
        self.assertEqual(g.nodes["h01_contract_sgis"].on_fail["goto"], "h00_collect_sgis")
        self.assertTrue(all(n.title and n.title != n.id for n in g.nodes.values()), "모든 노드에 한글 title")
        # 2026-09-01 회신으로 민원이 비공개가 되었다 (docs/decisions/001-layer2-design.md).
        # 민원 노드는 optional 이고, 어느 하류도 민원에 묶여 있으면 안 된다 — 정책카드까지 포함.
        complaint = {"h05_holdout_freeze", "h05_complaint_extract"}
        for nid in complaint:
            self.assertTrue(g.nodes[nid].optional, f"{nid} 는 optional 이어야 한다")
        for nid in ("h06_layer1_flood", "h06_layer2_sewer", "h06_layer3_vuln", "h07_cdri", "h08_top20_policy"):
            self.assertFalse(g.ancestors(nid) & complaint, f"{nid} 가 민원 노드에 묶여 있음")
        # Layer 2 도 관로 비공개로 optional 이며 CDRI 를 막지 않는다
        self.assertTrue(g.nodes["h06_layer2_sewer"].optional)
        self.assertNotIn("h06_layer2_sewer", g.ancestors("h07_cdri"))
        # 대신 CDRI 는 Layer 1·3 에 반드시 묶여 있어야 한다
        self.assertLessEqual({"h06_layer1_flood", "h06_layer3_vuln"}, g.ancestors("h07_cdri"))
        # 모든 goto 는 자기 자신 또는 상류 (Graph 검증이 보장) — 단계도 같거나 앞
        for n in g.nodes.values():
            goto = (n.on_fail or {}).get("goto")
            if goto:
                self.assertLessEqual(g.phase_index(g.nodes[goto].phase), g.phase_index(n.phase))

    def test_phase_order_is_enforced(self) -> None:
        with self.assertRaises(GraphError):
            Graph.load_from_dict({"version": 1, "phases": {"P1": {}, "P2": {}}, "nodes": {
                "late": {"gate": "H", "phase": "P2", "runner": "m:f", "outputs": ["o/l"]},
                "early": {"gate": "H", "phase": "P1", "runner": "m:f", "outputs": ["o/e"], "depends_on": ["late"]},
            }})
        with self.assertRaises(GraphError):
            Graph.load_from_dict({"version": 1, "phases": {"P1": {}}, "nodes": {
                "a": {"gate": "H", "phase": "P9", "runner": "m:f", "outputs": ["o/a"]}}})


class RunnerTest(unittest.TestCase):
    """PROJECT_ROOT와 artifacts 경로를 임시 디렉터리로 돌려 실제 실행 흐름을 검증."""

    def setUp(self) -> None:
        CALLS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "config").mkdir()
        (root / "config" / "config.yaml").write_text("analysis:\n  seed: 1\n", encoding="utf-8")
        (root / "in.txt").write_text("v1", encoding="utf-8")
        self.root = root
        self.patches = [
            patch.object(mf, "PROJECT_ROOT", root),
            patch.object(mf, "RUNS_DIR", root / "artifacts" / "runs"),
            patch.object(mf, "STATE_DIR", root / "artifacts" / "state"),
            patch.object(mf, "APPROVALS_DIR", root / "artifacts" / "approvals"),
            patch("src.pipeline.runner.PROJECT_ROOT", root),
            patch.object(mf, "git_commit", lambda: None),
            patch.object(mf, "git_worktree_provenance", lambda: {"git_dirty": None}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def graph(self, second_runner: str = "test_pipeline:ok_stage") -> Graph:
        g = build({
            "a": {"gate": "H01", "phase": "P1", "runner": "test_pipeline:ok_stage",
                  "inputs": ["in.txt"], "params": ["analysis.seed"], "outputs": ["out/a.txt"]},
            "b": {"gate": "H02", "phase": "P1", "runner": second_runner, "depends_on": ["a"], "outputs": ["out/b.txt"]},
            "c": {"gate": "H03", "phase": "P1", "runner": "test_pipeline:ok_stage", "depends_on": ["b"],
                  "outputs": ["out/c.txt"]},
        })
        g.source = None
        return g

    def execute(self, g: Graph, **kw) -> dict:
        return run(g, config_path=self.root / "config" / "config.yaml", **kw)

    def test_runs_then_caches_then_invalidates_downstream(self) -> None:
        m1 = self.execute(self.graph())
        self.assertEqual(m1["status"], "pass")
        self.assertEqual(CALLS, ["a", "b", "c"])
        self.assertTrue((self.root / m1["manifest_path"]).exists())

        CALLS.clear()
        m2 = self.execute(self.graph())
        self.assertEqual([r["status"] for r in m2["nodes"].values()], ["cached"] * 3)
        self.assertEqual(CALLS, [])

        # 입력 내용이 바뀌면 a는 재실행. a의 출력이 byte 동일하면 하류 b·c는 캐시 유지 (content-addressed)
        (self.root / "in.txt").write_text("v2", encoding="utf-8")
        self.execute(self.graph())
        self.assertEqual(CALLS, ["a"])

        # 출력 파일이 손상되면 fingerprint가 같아도 재실행. 재생성 결과가 byte 동일하면 하류 c는 캐시.
        CALLS.clear()
        (self.root / "out" / "b.txt").write_text("tampered", encoding="utf-8")
        self.execute(self.graph())
        self.assertEqual(CALLS, ["b"])

    def test_upstream_output_change_reruns_downstream(self) -> None:
        self.execute(self.graph())
        CALLS.clear()
        # b의 runner가 바뀌어 다른 내용을 쓰면 b와 하류 c 모두 재실행
        self.execute(self.graph("test_pipeline:ok_stage_v2"))
        self.assertEqual(CALLS, ["b", "c"])

    def test_param_change_invalidates(self) -> None:
        self.execute(self.graph())
        CALLS.clear()
        (self.root / "config" / "config.yaml").write_text("analysis:\n  seed: 2\n", encoding="utf-8")
        self.execute(self.graph())
        self.assertEqual(CALLS, ["a"])  # params를 선언한 a만 재실행; 출력 동일하므로 하류는 캐시

    def test_fail_fast_and_missing_output(self) -> None:
        m = self.execute(self.graph("test_pipeline:failing_stage"))
        self.assertEqual(m["status"], "fail")
        self.assertEqual(m["stopped_at"], "b")
        self.assertEqual(m["nodes"]["b"]["findings"], [{"code": "x"}])
        # 실패해도 왜 실패했는지 숫자가 남아야 한다
        self.assertEqual(m["nodes"]["b"]["metrics"], {"seen": 7, "why": 42})
        self.assertNotIn("c", m["nodes"])
        self.assertEqual(CALLS, ["a", "b"])

        m = self.execute(self.graph("test_pipeline:forgetful_stage"), force=True)
        self.assertEqual(m["nodes"]["b"]["status"], "fail")
        self.assertIn("missing_output", m["nodes"]["b"]["findings"][0]["code"])

    def test_optional_node_failure_is_skipped_not_fail(self) -> None:
        g = build({
            "a": {"gate": "H01", "phase": "P1", "runner": "test_pipeline:ok_stage", "outputs": ["out/a.txt"]},
            "opt": {"gate": "H09", "phase": "P1", "runner": "test_pipeline:failing_stage", "depends_on": ["a"],
                    "optional": True, "outputs": ["out/opt.txt"]},
            "c": {"gate": "H10", "phase": "P1", "runner": "test_pipeline:ok_stage", "depends_on": ["a"],
                  "outputs": ["out/c.txt"]},
        })
        g.source = None
        m = self.execute(g)
        self.assertEqual(m["status"], "pass")
        self.assertEqual(m["nodes"]["opt"]["status"], "skipped")
        self.assertEqual(m["nodes"]["c"]["status"], "pass")

    def test_approval_gate_blocks_downstream_until_approved_and_invalidates_on_change(self) -> None:
        def g():
            gr = build({
                "a": {"gate": "H01", "phase": "P1", "runner": "test_pipeline:ok_stage", "inputs": ["in.txt"], "outputs": ["out/a.txt"],
                      "approval": {"who": "R1", "what": "확인"}},
                "b": {"gate": "H02", "phase": "P1", "runner": "test_pipeline:ok_stage", "depends_on": ["a"], "outputs": ["out/b.txt"]},
            })
            gr.source = None
            return gr
        m = self.execute(g())
        self.assertEqual(m["status"], "awaiting_approval")
        self.assertEqual(m["stopped_at"], "a")
        self.assertEqual(m["nodes"]["a"]["approval"], "awaiting_approval")
        self.assertNotIn("b", m["nodes"])
        self.assertEqual(CALLS, ["a"])

        st = mf.load_state("a")
        mf.write_approval(g().nodes["a"], st["outputs"], by="R1", note="ok")
        CALLS.clear()
        m = self.execute(g())
        self.assertEqual(m["status"], "pass")
        self.assertEqual(m["nodes"]["a"]["status"], "cached")
        self.assertEqual(m["nodes"]["a"]["approval"], "approved")
        self.assertEqual(CALLS, ["b"])

        # a의 출력이 바뀌면 기존 승인은 stale → 다시 멈춤
        CALLS.clear()
        (self.root / "out" / "a.txt").write_text("changed", encoding="utf-8")
        m = self.execute(g())  # a 재실행 → 출력 다시 "a" → digest 같음 → approved
        self.assertEqual(m["status"], "pass")
        gr = g(); gr.nodes["a"] = type(gr.nodes["a"])(**{**gr.nodes["a"].__dict__, "runner": "test_pipeline:ok_stage_v2"})
        m = self.execute(gr)
        self.assertEqual(m["nodes"]["a"]["approval"], "stale_approval")
        self.assertEqual(m["status"], "awaiting_approval")

    def test_continue_past_approval_is_marked_not_evidence(self) -> None:
        gr = build({
            "a": {"gate": "H01", "phase": "P1", "runner": "test_pipeline:ok_stage", "outputs": ["out/a.txt"],
                  "approval": {"who": "R1", "what": "확인"}},
            "b": {"gate": "H02", "phase": "P1", "runner": "test_pipeline:ok_stage", "depends_on": ["a"], "outputs": ["out/b.txt"]},
        }); gr.source = None
        m = self.execute(gr, continue_past_approval=True)
        self.assertEqual(m["status"], "pass")
        self.assertTrue(m["approval_bypassed"])
        self.assertTrue(m["nodes"]["a"]["approval_pending"])
        self.assertEqual(CALLS, ["a", "b"])

    def test_rejected_approval_blocks_and_cannot_be_bypassed(self) -> None:
        """사람이 거부하면 하류가 열리면 안 되고, 개발용 우회 플래그로도 못 넘어야 한다."""
        def g():
            gr = build({
                "a": {"gate": "H01", "phase": "P1", "runner": "test_pipeline:ok_stage",
                      "outputs": ["out/a.txt"], "approval": {"who": "R1", "what": "확인"}},
                "b": {"gate": "H02", "phase": "P1", "runner": "test_pipeline:ok_stage",
                      "depends_on": ["a"], "outputs": ["out/b.txt"]},
            })
            gr.source = None
            return gr

        self.execute(g())  # a 실행 → 승인 대기
        mf.write_approval(g().nodes["a"], mf.load_state("a")["outputs"],
                          by="R1", note="이 결과는 못 쓴다", decision="rejected")
        CALLS.clear()
        m = self.execute(g())
        self.assertEqual(m["nodes"]["a"]["approval"], "rejected")
        self.assertEqual(m["nodes"]["a"]["status"], "rejected")
        self.assertNotIn("b", m["nodes"])
        m = self.execute(g(), continue_past_approval=True)
        self.assertEqual(m["nodes"]["a"]["status"], "rejected", "거부는 우회 플래그로도 못 넘는다")
        self.assertNotIn("b", m["nodes"])

    def test_max_iterations_exhausts_then_force_overrides(self) -> None:
        def g():
            gr = build({
                "a": {"gate": "H01", "phase": "P1", "runner": "test_pipeline:failing_stage", "outputs": ["out/a.txt"],
                      "on_fail": {"goto": "a", "max_iterations": 2, "action": "고쳐라"}},
            })
            gr.source = None
            return gr
        self.assertEqual(self.execute(g())["nodes"]["a"]["next"], {"goto": "a", "action": "고쳐라", "attempts_left": 1})
        self.assertEqual(self.execute(g())["nodes"]["a"]["next"]["attempts_left"], 0)
        m = self.execute(g())
        self.assertEqual(m["status"], "exhausted")
        self.assertEqual(CALLS, ["a", "a"])  # 3번째는 실행 자체를 안 함
        m = self.execute(g(), force=True)
        self.assertEqual(m["nodes"]["a"]["status"], "fail")
        self.assertEqual(CALLS, ["a", "a", "a"])

    def test_graph_rejects_bad_orchestration_fields(self) -> None:
        base = {"gate": "H", "phase": "P1", "runner": "m:f", "outputs": ["o/a"]}
        with self.assertRaises(GraphError):
            build({"a": {**base, "verify": [{"kind": "magic", "rule": "x"}]}})
        with self.assertRaises(GraphError):
            build({"a": {**base, "approval": {"who": "R1"}}})
        with self.assertRaises(GraphError):
            build({"a": {**base, "on_fail": {"goto": "zzz", "max_iterations": 1}}})
        with self.assertRaises(GraphError):  # 순방향 점프 금지
            build({"a": {**base, "on_fail": {"goto": "b", "max_iterations": 1}},
                   "b": {**base, "outputs": ["o/b"], "depends_on": ["a"]}})

    def test_real_yaml_mermaid_has_all_three_orchestration_elements(self) -> None:
        mm = Graph.load().to_mermaid()
        self.assertIn("__v{", mm)          # 검증 마름모
        self.assertIn("__a{{", mm)         # 승인 육각형
        self.assertIn(".-> h00_collect_rainfall", mm)   # 수집까지 되돌아가는 루프백 점선
        self.assertNotIn("|pass|", mm)                   # 라벨은 한글
        self.assertEqual(mm.count("subgraph P"), 4)      # 큰 단계 4개

    def test_mermaid_labels_never_contain_raw_quotes_or_angle_brackets(self) -> None:
        """YAML 설명에 따옴표가 들어가면 mermaid 파서가 깨진다(got 'STR'). 라벨 이스케이프 회귀 테스트."""
        g = Graph.load_from_dict({"version": 1, "phases": {"P1": {}}, "nodes": {
            "a": {"gate": "H", "phase": "P1", "runner": "m:f", "outputs": ["o/a"],
                  "description": '그는 "써도 되는가"를 묻는다; x > 5 & y < 3',
                  "verify": [{"kind": "code", "rule": '"분석 가능" 판정'}],
                  "approval": {"who": "R1", "what": 'TOP 20 "확정"'},
                  "on_fail": {"goto": "a", "max_iterations": 1, "action": 'action "quoted"'}}}})
        mm = g.to_mermaid()
        for line in mm.splitlines():
            if line.startswith("%%"):  # init 디렉티브는 JSON이라 따옴표가 정상
                continue
            for inner in re.findall(r'\["(.*?)"\]|\{\{"(.*?)"\}\}|\{"(.*?)"\}|-\. "(.*?)" \.->', line):
                text = next(x for x in inner if x)
                self.assertNotIn('"', text, line)
                self.assertNotIn(";", text.replace("#59;", "").replace("#quot;", "").replace("#lt;", "").replace("#gt;", "").replace("#amp;", ""), line)
                self.assertNotRegex(re.sub(r"</?(br/?|b|i|small)>", "", text), r"[<>]", line)
        self.assertIn("#quot;", mm)


if __name__ == "__main__":
    unittest.main()
