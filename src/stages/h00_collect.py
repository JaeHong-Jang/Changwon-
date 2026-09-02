"""H00 데이터 수집 확인. 수집 자체는 수동(다운로드·정보공개청구)이므로 이 노드들은 '다 모였는가'를 판정한다."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from src.data.validate_raw import is_lfs_pointer, resolve_files, sha256_file
from src.pipeline.runner import StageContext, StageFailed
from src.stages.h01_contract import GROUPS
from src.utils.config import PROJECT_ROOT

# 이모지/문구 → 정규화된 상태. docs/data_access_log.md 의 "상태 범례"와 같다.
STATUS_MAP = {
    "⬜": "미신청",
    "🟡": "대기",
    "✅": "수령",
    "❌": "거부",
    "🔁": "재청구",
}
STATUS_WORDS = {"미신청", "대기", "수령", "거부", "재청구", "미착수"}

# 필요성 등급은 docs/data_access_log.md 의 "필요성" 열에서 읽는다. 코드에 번호를
# 하드코딩하면 문서와 코드가 갈라지고, 어느 쪽이 맞는지 알 수 없게 된다.
NEED_LEVELS = {"필수", "대체가능", "선택"}


def _parse_access_log(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not cells[0].isdigit():
            continue
        raw_status = cells[6]
        need_cell = cells[7] if len(cells) > 7 else ""
        need = next((n for n in NEED_LEVELS if n in need_cell), None)
        status = next((v for k, v in STATUS_MAP.items() if k in raw_status), None)
        if status is None:
            status = next((w for w in STATUS_WORDS if w in raw_status), None)
        if status == "미착수":
            status = "미신청"
        rows.append(
            {
                "no": int(cells[0]),
                "target": cells[1],
                "office": cells[2],
                "requested_at": cells[3] or None,
                "receipt": cells[4] or None,
                "expected_reply": cells[5] or None,
                "status": status,
                "status_raw": raw_status,
                "note": cells[7] if len(cells) > 7 else "",
                "need": need,
                "need_reason": cells[8] if len(cells) > 8 else "",
                "required": need == "필수",
            }
        )
    return rows


def access_requests(ctx: StageContext) -> dict[str, Any]:
    """docs/data_access_log.md 표를 파싱해 access_requests.json 생성.
    통과: 모든 행에 상태가 있고, REQUIRED_REQUESTS 중 '미신청' 0개 (대기는 통과).
    미달이면 StageFailed(findings=상태 없음/미신청 필수 항목). metrics: total, received, pending, not_requested."""
    log_path = ctx.path("docs/data_access_log.md")
    rows = _parse_access_log(log_path.read_text(encoding="utf-8"))
    findings: list[dict[str, Any]] = []
    for r in rows:
        if r["status"] is None:
            findings.append({"code": "missing_status", "no": r["no"], "target": r["target"]})
        elif r["need"] is None:
            findings.append({"code": "need_unjudged", "no": r["no"], "target": r["target"]})
        elif r["required"] and r["status"] == "미신청":
            findings.append({"code": "required_not_requested", "no": r["no"], "target": r["target"]})

    metrics = {
        "total": len(rows),
        "received": sum(r["status"] == "수령" for r in rows),
        "pending": sum(r["status"] == "대기" for r in rows),
        "not_requested": [r["no"] for r in rows if r["status"] == "미신청"],
        "required_pending": [r["no"] for r in rows if r["required"] and r["status"] == "대기"],
        # 필요성 판단이 비어 있는 행. 판단하지 않은 것을 "필수 아님"으로 넘기면 안 된다.
        "need_unjudged": [r["no"] for r in rows if r["need"] is None],
    }
    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"source": "docs/data_access_log.md",
             "rows": rows, "metrics": metrics, "findings": findings},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    if not rows:
        raise StageFailed("data_access_log.md 에서 표를 읽지 못함", [{"code": "empty_table"}])
    if findings:
        raise StageFailed(f"접근신청 기준 미달 {len(findings)}건", findings)
    return metrics


def _readme_mentions(readme: str, spec: dict[str, Any], name: str) -> bool:
    if name in readme:
        return True
    patterns = spec.get("globs") or [spec["glob"]]
    for pat in patterns:
        stem = re.split(r"[*?\[]", Path(pat).name)[0].rstrip("_ ")
        parent = Path(pat).parent.name
        if (stem and stem in readme) or (parent and parent not in (".", "") and parent in readme):
            return True
    return False


def inventory(ctx: StageContext) -> dict[str, Any]:
    """노드 id 의 묶음(h00_collect_<key>)에 해당하는 dataset 들에 대해 collection_<key>.json 생성:
    파일 존재·LFS 포인터 여부·크기·sha256, 계약의 취득 메타데이터, data/raw/README.md 언급 여부.
    통과: 파일 수 == expected_files, 포인터 0, collected_at·source_url 존재. README 미기록은 metrics 로만 기록.
    metrics: files, bytes, lfs_pointers, missing_metadata, readme_unrecorded."""
    key = ctx.node.id.removeprefix("h00_collect_")
    if key not in GROUPS:
        raise StageFailed(f"알 수 없는 수집 묶음 '{key}'", [{"code": "unknown_group", "key": key}])
    contract = yaml.safe_load(ctx.path("config/data_contracts.yaml").read_text(encoding="utf-8"))
    raw_root = PROJECT_ROOT / contract["raw_root"]
    readme_path = ctx.path("data/raw/README.md")
    readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    datasets: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    total_files = total_bytes = pointers = 0
    missing_metadata: list[str] = []
    readme_unrecorded: list[str] = []

    for name in GROUPS[key]:
        spec = contract["datasets"][name]
        paths = resolve_files(raw_root, spec)
        for suffix in spec.get("required_sidecars", []):
            for p in list(paths):
                side = p.with_suffix(suffix)
                if not side.exists():
                    findings.append({"code": "missing_sidecar", "dataset": name, "path": str(p.relative_to(raw_root)), "suffix": suffix})
        files = []
        for p in paths:
            pointer = is_lfs_pointer(p)
            size = p.stat().st_size
            files.append({"path": str(p.relative_to(raw_root)), "bytes": size, "sha256": sha256_file(p), "lfs_pointer": pointer})
            total_bytes += size
            if pointer:
                pointers += 1
                findings.append({"code": "lfs_pointer", "dataset": name, "path": str(p.relative_to(raw_root))})
        total_files += len(paths)
        expected = spec.get("expected_files")
        if expected is not None and len(paths) != expected:
            findings.append({"code": "file_count", "dataset": name, "expected": expected, "found": len(paths)})
        meta_missing = [k for k in ("collected_at", "source_url") if not spec.get(k)]
        if meta_missing:
            missing_metadata.append(name)
            findings.append({"code": "missing_metadata", "dataset": name, "fields": meta_missing})
        recorded = _readme_mentions(readme, spec, name)
        if not recorded:
            readme_unrecorded.append(name)
        datasets.append(
            {
                "name": name,
                "description": spec.get("description", ""),
                "source_url": spec.get("source_url"),
                "collected_at": str(spec.get("collected_at")) if spec.get("collected_at") else None,
                "expected_files": expected,
                "found_files": len(paths),
                "readme_recorded": recorded,
                "files": files,
            }
        )

    metrics = {
        "files": total_files,
        "bytes": total_bytes,
        "lfs_pointers": pointers,
        "missing_metadata": missing_metadata,
        "readme_unrecorded": readme_unrecorded,
    }
    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"group": key, "datasets": datasets, "metrics": metrics, "findings": findings}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if findings:
        raise StageFailed(f"{key} 수집 확인 실패 {len(findings)}건", findings)
    return metrics
