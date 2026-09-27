"""M4S 실행: 가상 시나리오 115개 × 복제 200 을 병렬로 채점하고 요약·판정·창원 기준점·그림을 기록한다."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.models.provenance import file_sha256, git_state, package_versions

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/q1/M4S"
CODE_FILES = ["src/models/m4s_run.py", "src/models/m4s_measure.py", "src/models/m4s_summary.py", "src/models/m4s_decision.py",
              "src/models/m4s_anchor.py", "src/models/m4s_figure.py", "src/synth/landscape.py", "src/synth/inventory.py",
              "src/synth/detectability.py", "src/synth/scenarios.py", "src/synth/tilt.py",
              "src/data/validation/weight_concentration.py", "src/data/validation/decomposition.py",
              "src/data/validation/weighted_auc.py", "src/data/validation/_common.py", "src/data/validation/curves.py",
              "src/data/trace_footprint.py", "src/data/label_rules.py", "src/models/m4_metrics.py", "docs/q1/M4S_protocol.md"]
ANCHOR_FILES = ["artifacts/q1/M4/m4_20260926T170511Z_1edf87c/object_contrib.parquet",
                "artifacts/q1/M4/m4_20260926T170511Z_1edf87c/decomposition.csv"]
_LAND = None


def _init() -> None:
    """작업자마다 가상 격자를 한 번 만든다."""
    from src.models.m4s_measure import make_landscape

    # 작업자 전역에 격자를 둔다
    global _LAND
    _LAND = make_landscape()


def _work(task: tuple[Any, int]) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], float]:
    """시나리오 하나의 모든 복제를 채점한다."""
    from src.models.m4s_measure import run_scenario

    # 걸린 시간과 함께 행을 돌려준다
    scenario, replicates = task
    start = time.time()
    rows, events = run_scenario(scenario, replicates, _LAND)
    return scenario.no, rows, events, time.time() - start


def scenario_table(scenarios: list[Any]):
    """시나리오 표에 로그정규 시나리오의 공식 Δ* 와 모집단 객체 AUC 를 붙인다."""
    import pandas as pd

    from src.synth.tilt import lognormal_neff_ratio, lognormal_top_share, object_auc_limit, tilted_gap

    # Pareto 는 공식이 없어 비운다
    table = pd.DataFrame([s.row() for s in scenarios])
    logn = table["dist"] == "lognormal"
    table["delta_star"] = [tilted_gap(r.shape, r.beta, r.mu0, r.tau) if ok else np.nan for r, ok in zip(table.itertuples(), logn)]
    table["object_auc_limit"] = [object_auc_limit(r.beta, r.mu0, r.tau) for r in table.itertuples()]
    table["top10_share_theory"] = [lognormal_top_share(r.shape) if ok else np.nan for r, ok in zip(table.itertuples(), logn)]
    table["neff_ratio_theory"] = [lognormal_neff_ratio(r.shape) if ok else np.nan for r, ok in zip(table.itertuples(), logn)]
    return table


def run(replicates: int | None = None, workers: int = 4, anchor: bool = True, blocks: tuple[str, ...] | None = None) -> dict[str, Any]:
    """시나리오를 병렬 채점해 실행별 폴더에 복제 표·요약·판정·기준점·그림·출처를 남긴다."""
    import pandas as pd

    from src.models import m4s_decision, m4s_summary
    from src.models.m4s_anchor import anchors
    from src.models.m4s_figure import gap_map
    from src.synth.scenarios import REPLICATES, grid

    # 실행 식별자와 시나리오 목록을 만든다
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT, ("src", "config", "docs/q1"))
    replicates = replicates or REPLICATES
    official = replicates == REPLICATES and blocks is None
    run_id = f"m4s{'' if official else '_partial'}_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"
    scenarios = [s for s in grid() if blocks is None or s.block in blocks]
    table = scenario_table(scenarios)

    # 비싼 시나리오부터 작업자에게 나눠 복제 행을 모은다
    rows, event_rows, seconds = [], [], {}
    order = sorted(scenarios, key=lambda s: -(s.n_obj * s.n_events * (1 + s.shape if s.dist == "lognormal" else 2)))
    with mp.get_context("fork").Pool(workers, initializer=_init) as pool:
        for k, (no, r, e, sec) in enumerate(pool.imap_unordered(_work, [(s, replicates) for s in order]), 1):
            rows += r
            event_rows += e
            seconds[no] = sec
            print(f"[{k}/{len(order)}] scenario {no} {sec:.0f}s", file=sys.stderr, flush=True)

    # 복제 표를 정렬하고 게이트·뒤집힘을 붙인 뒤 요약한다
    rep = m4s_summary.annotate(pd.DataFrame(rows).sort_values(["scenario_no", "replicate", "rule"]).reset_index(drop=True))
    events = pd.DataFrame(event_rows)
    events = events.sort_values(["scenario_no", "replicate", "event"]).reset_index(drop=True) if len(events) else events
    summary = m4s_summary.scenario_summary(rep, table)
    flips = m4s_summary.flip_conditions(rep)
    aggregation = m4s_summary.event_aggregation(rep, events) if len(events) else pd.DataFrame()
    event_summary = m4s_summary.event_summary(aggregation) if len(aggregation) else pd.DataFrame()
    summary = summary.merge(event_summary.add_prefix("B_").rename(columns={"B_scenario_no": "scenario_no"}),
                            on="scenario_no", how="left") if len(event_summary) else summary

    # 항등식 오차를 모으고 창원 기준점을 붙여 판정한다
    identity = {"max_identity_abs_diff": float(np.nanmax(np.r_[rep["identity_abs_diff"], events.get("identity_abs_diff", [])])),
                "max_sklearn_abs_diff": float(np.nanmax(rep["sklearn_abs_diff"])),
                "n_sklearn_checked": int(np.isfinite(rep["sklearn_abs_diff"]).sum()),
                "max_cov_abs_diff": float(np.nanmax(rep["cov_abs_diff"])),
                "n_cov_checked": int(np.isfinite(rep["cov_abs_diff"]).sum()), "n_rows": int(len(rep))}
    anchor_table = anchors(ROOT) if anchor else None
    decision = m4s_decision.decide(summary, event_summary, anchor_table, identity)

    # 실행별 폴더에 산출물을 쓴다
    out = OUTPUT / run_id
    out.mkdir(parents=True, exist_ok=False)
    table.to_csv(out / "scenarios.csv", index=False, encoding="utf-8-sig")
    rep.to_parquet(out / "replicates.parquet", compression="zstd")
    if len(events):
        events.to_parquet(out / "events.parquet", compression="zstd")
        aggregation.to_csv(out / "event_aggregation.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(out / "summary_by_scenario.csv", index=False, encoding="utf-8-sig")
    flips.to_csv(out / "flip_conditions.csv", index=False, encoding="utf-8-sig")
    if anchor_table is not None:
        anchor_table.to_csv(out / "anchors.csv", index=False, encoding="utf-8-sig")
    if "A" in set(table["block"]):
        gap_map(summary, out / "gap_map.png")
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # 출처와 실행 조건을 요약에 남긴다
    command = "PYTHONPATH=. .venv/bin/python -m src.models.m4s_run" + ("" if anchor else " --no-anchor") + \
        ("" if replicates == REPLICATES else f" --replicates {replicates}") + ("" if blocks is None else f" --blocks {','.join(blocks)}")
    summary_json = {"run_id": run_id, "started_utc": started.isoformat(), "finished_utc": datetime.now(timezone.utc).isoformat(),
                    "git_head": head, "source_dirty": dirty, "command": command, "official": official,
                    "role": "가상 자료 시연. 새 자료·홀드아웃 원본 없음. 창원 기준점(anchors)은 M4 공식 산출을 읽는 post-hoc 보조 분석",
                    "protocol": "docs/q1/M4S_protocol.md", "replicates": replicates, "n_scenarios": len(scenarios),
                    "workers": workers, "anchor": anchor, "identity": identity, "scenario_seconds": seconds,
                    "code_sha256": {p: file_sha256(ROOT / p) for p in CODE_FILES},
                    "input_sha256": {p: file_sha256(ROOT / p) for p in ANCHOR_FILES} if anchor else {},
                    "packages": package_versions(), "verdict": decision["verdict"]}
    (out / "summary.json").write_text(json.dumps(summary_json, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return summary_json


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=None, help="복제 수 (기본 200, 다르면 partial run)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--blocks", default=None, help="쉼표로 묶음 제한 (예: A,B). 지정하면 partial run")
    parser.add_argument("--no-anchor", action="store_true", help="M4 산출(홀드아웃 유래 표)을 읽지 않는다")
    args = parser.parse_args()
    result = run(args.replicates, args.workers, not args.no_anchor, tuple(args.blocks.split(",")) if args.blocks else None)
    print(json.dumps({k: result[k] for k in ("run_id", "verdict", "identity")}, ensure_ascii=False, default=str))
