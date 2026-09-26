"""M6 실행: 홀드아웃 재실행 비교·라벨 감사 재확인·연대표·Zenodo 목록을 실행별 폴더에 남긴다."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.models.provenance import file_sha256, git_state, package_versions, write_json

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/q1/M6"
HOLDOUT_DIR = ROOT / "artifacts/evaluation/holdout_2022_2024"
LABEL_AUDIT_DIR = ROOT / "artifacts/evaluation/label_audit"
REFERENCE = ROOT / "config/holdout_reference.yaml"
SECONDARY_RUN = "holdout_20260924T104608Z_ae9c122-dirty_4af97d5d"
CHRONOLOGY_SPEC = ROOT / "config/m6_chronology.yaml"
STEPS = ("compare", "audit", "chronology", "zenodo")
CODE_FILES = ["src/repro/m6_run.py", "src/repro/run_compare.py", "src/repro/audit_check.py",
              "src/repro/chronology.py", "src/repro/deposit_manifest.py", "src/data/reproducibility.py",
              "src/models/label_audit.py", "src/models/provenance.py", "docs/q1/M6_protocol.md"]
# 문서가 인용하는 라벨 감사 값: (역할, 요약 경로, 항목) → (인용 값, 인용 정밀도의 절반)
CITED_AUDIT = {
    ("development", "all", "n"): (145, 0), ("development", "all", "survive_grid_10pct"): (0.952, 0.0005),
    ("development", "all", "median_area_m2"): (8750, 0.5),
    ("holdout", "all", "n"): (196, 0), ("holdout", "all", "survive_grid_10pct"): (0.663, 0.0005),
    ("holdout", "all", "median_area_m2"): (3590, 0.5),
    ("holdout", "by_land_class.urban", "n"): (57, 0),
    ("holdout", "by_land_class.urban", "survive_grid_10pct"): (0.123, 0.0005),
    ("holdout", "by_land_class.agricultural", "n"): (119, 0),
    ("holdout", "by_land_class.agricultural", "survive_grid_10pct"): (0.975, 0.0005),
}


def _load_run(run_id: str) -> tuple[dict[str, Any], Any]:
    """홀드아웃 평가 실행 폴더의 summary.json 과 metrics.csv 를 읽는다."""
    import pandas as pd

    # 실행 폴더 이름이 곧 run_id 다
    folder = HOLDOUT_DIR / run_id
    return json.loads((folder / "summary.json").read_text(encoding="utf-8")), pd.read_csv(folder / "metrics.csv")


def step_compare(out: Path, new_run_id: str) -> dict[str, Any]:
    """새 홀드아웃 실행을 주·보조 기준 실행과 J1~J3 로 비교하고 차이 행을 저장한다."""
    from src.repro import run_compare as RC

    # 새 실행과 고정 기준(홀드아웃 기준 YAML)·보조 기준 실행을 읽는다
    reference = yaml.safe_load(REFERENCE.read_text(encoding="utf-8"))
    new, new_metrics = _load_run(new_run_id)
    result: dict[str, Any] = {"new_run_id": new_run_id, "reference_yaml": reference, "references": {}}

    # 기준 실행마다 요약·지표표를 비교해 판정하고, 주 기준의 차이 행을 CSV 로 남긴다
    for role, ref_id in (("primary", reference["run_id"]), ("secondary", SECONDARY_RUN)):
        ref, ref_metrics = _load_run(ref_id)
        summaries = RC.compare_summaries(new, ref, reference)
        j2, diff_rows = RC.compare_metrics(new_metrics, ref_metrics)
        result["references"][role] = {"run_id": ref_id, **summaries, "J2": j2,
                                      "verdict": RC.verdict(summaries["J1"]["pass"], j2, summaries["J3"]["pass"])}
        if role == "primary":
            diff_rows.to_csv(out / "metrics_diff.csv", index=False)

    # 보고서 표에 쓸 게이트 값을 새 실행·주 기준 나란히 모은다
    ref = _load_run(reference["run_id"])[0]
    result["gate_table"] = {name: {"new": {k: g.get(k) for k in ("auc_cell", "auc_cluster", "top20_capture",
                                                                   "passes_auc", "passes_capture")},
                                   "ref": {k: ref["gates"][name].get(k) for k in ("auc_cell", "auc_cluster",
                                                                                   "top20_capture")}}
                            for name, g in new["gates"].items() if g.get("evaluable")}
    result["verdict"] = result["references"]["primary"]["verdict"]
    write_json(out / "holdout_compare.json", result)
    return {"new_run_id": new_run_id, "verdict": result["verdict"],
            "secondary_verdict": result["references"]["secondary"]["verdict"]}


def _pick(summary: dict[str, Any], path: str, item: str) -> Any:
    """요약 JSON 에서 점으로 이은 경로의 항목 값을 꺼낸다."""
    # 경로를 따라 내려간 뒤 항목을 읽는다
    node: Any = summary
    for part in path.split("."):
        node = node[part]
    return node[item]


def step_audit(out: Path) -> dict[str, Any]:
    """라벨 감사를 M6 폴더로 다시 실행해 저장본과 비교하고, 문서 인용 값을 저장본과 대조한다."""
    import pandas as pd

    from src.models import label_audit as A
    from src.repro.audit_check import compare_audit_summary, compare_polygon_tables

    # 문서 인용 값이 저장 요약과 인용 정밀도 안에서 같은지 본다
    stored = {role: json.loads((LABEL_AUDIT_DIR / f"{role}_summary.json").read_text(encoding="utf-8"))
              for role in ("development", "holdout")}
    cited = [{"role": role, "path": path, "item": item, "cited": value, "stored": _pick(stored[role], path, item),
              "pass": abs(_pick(stored[role], path, item) - value) <= half}
             for (role, path, item), (value, half) in CITED_AUDIT.items()]

    # 산출 폴더만 잠시 바꿔 두 역할을 다시 감사하고 저장본과 비교한 뒤 모듈 설정을 되돌린다 (저장본은 덮어쓰지 않는다)
    original, A.OUTPUT = A.OUTPUT, out / "label_audit"
    rerun = {}
    try:
        for role in ("development", "holdout"):
            summary = A.run(role)
            tables = [pd.read_csv(folder / f"{role}_polygons.csv") for folder in (A.OUTPUT, LABEL_AUDIT_DIR)]
            rerun[role] = {"summary": compare_audit_summary(summary, stored[role]),
                           "polygons": compare_polygon_tables(*tables)}
    finally:
        A.OUTPUT = original
    result = {"cited_vs_stored": cited, "cited_pass": all(c["pass"] for c in cited), "rerun_vs_stored": rerun,
              "rerun_pass": all(r["summary"]["pass"] and r["polygons"]["pass"] for r in rerun.values()),
              "stored_run_ids": {role: s["run_id"] for role, s in stored.items()}}
    write_json(out / "label_audit_compare.json", result)
    return {k: result[k] for k in ("cited_pass", "rerun_pass", "stored_run_ids")}


def step_chronology(out: Path) -> dict[str, Any]:
    """연대표 명세의 시각을 출처에서 읽어 chronology.csv 로 저장한다."""
    from src.repro.chronology import resolve_all

    # 명세 순서를 유지해 표를 만들고 확인 못 한 사건을 따로 적는다
    specs = yaml.safe_load(CHRONOLOGY_SPEC.read_text(encoding="utf-8"))["events"]
    table = resolve_all(specs, ROOT)
    table.to_csv(out / "chronology.csv", index=False)
    return {"n_events": int(len(table)), "n_verified": int(table["verified"].sum()),
            "unverified": table.loc[~table["verified"], "id"].tolist()}


def step_zenodo(out: Path) -> dict[str, Any]:
    """git 추적 파일의 기탁 후보 목록과 요약을 저장한다."""
    from src.repro.deposit_manifest import build_manifest, summarise, tracked_files

    # 인덱스의 추적 파일 전부를 분류하고 해시를 붙인다
    manifest = build_manifest(ROOT, tracked_files(ROOT))
    manifest.to_csv(out / "zenodo_manifest.csv", index=False)
    summary = summarise(manifest, ROOT)
    write_json(out / "zenodo_summary.json", summary)
    return {k: summary[k] for k in ("n_files", "bytes", "by_decision", "license_files", "missing_files")}


def run(steps: tuple[str, ...] = STEPS, holdout_run: str | None = None, out_dir: Path | None = None) -> dict[str, Any]:
    """지정한 단계를 실행하고 실행 폴더의 summary.json 에 단계별 결과를 덧붙인다."""
    # 실행 식별자를 만들거나 기존 폴더를 이어 쓰고, 단계별 출처(시각·git·코드 해시)를 기록한다
    started = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT)
    out = out_dir or OUTPUT / f"m6_{started:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"run_id": out.name, "steps": {}}

    # 요청한 단계를 정해진 순서로 실행한다
    new_run_id = holdout_run or json.loads((HOLDOUT_DIR / "latest.json").read_text(encoding="utf-8"))["run_id"]
    actions = {"compare": lambda: step_compare(out, new_run_id), "audit": lambda: step_audit(out),
               "chronology": lambda: step_chronology(out), "zenodo": lambda: step_zenodo(out)}
    for step in (s for s in STEPS if s in steps):
        begun = datetime.now(timezone.utc)
        command = f"python -m src.repro.m6_run --steps {step} --out-dir {out.relative_to(ROOT)}"
        command += f" --holdout-run {new_run_id}" if step == "compare" else ""
        summary["steps"][step] = {"started_utc": begun.isoformat(), "git_head": head, "source_dirty": dirty,
                                  "command": command, "result": actions[step]()}

    # 실행 환경과 코드 해시를 갱신해 저장한다
    summary |= {"versions": package_versions(), "code_sha256": {f: file_sha256(ROOT / f) for f in CODE_FILES},
                "protocol": "docs/q1/M6_protocol.md"}
    write_json(path, summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", default=",".join(STEPS), help="쉼표로 구분: " + ",".join(STEPS))
    parser.add_argument("--holdout-run", default=None, help="비교할 새 홀드아웃 run_id (기본: latest.json)")
    parser.add_argument("--out-dir", default=None, help="이어 쓸 기존 M6 실행 폴더 (기본: 새 폴더)")
    args = parser.parse_args()
    chosen = tuple(s.strip() for s in args.steps.split(",") if s.strip())
    unknown = set(chosen) - set(STEPS)
    if unknown:
        parser.error(f"알 수 없는 단계: {sorted(unknown)}")
    result = run(chosen, args.holdout_run, ROOT / args.out_dir if args.out_dir else None)
    print(json.dumps({k: v["result"] for k, v in result["steps"].items() if k in chosen}, ensure_ascii=False, indent=1))
