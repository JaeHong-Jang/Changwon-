"""H01 원본 계약: 기존 validate_raw.validate_contract를 DAG 노드로 감싼다."""

from __future__ import annotations

import json
from typing import Any

from src.data.validate_raw import validate_contract
from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT


# 파이프라인 묶음(h00_collect_<key>/h01_contract_<key>) → data_contracts dataset 이름
GROUPS: dict[str, list[str]] = {
    "rainfall": ["rainfall_hourly"],
    "river": ["river_level_hourly"],
    "small_tables": ["pump_stations", "river_metadata"],
    "sgis": [
        "sgis_aggregation_age", "sgis_aggregation_summary", "sgis_grid_statistics",
        "sgis_aggregation_boundaries", "sgis_grid_boundaries",
    ],
    "geo": ["land_cover_middle", "dem_tiles"],
}


def run_group(ctx: StageContext) -> dict[str, Any]:
    """묶음 하나만 strict 검증. 노드 id 끝부분(h01_contract_<key>)으로 묶음을 정한다."""
    key = ctx.node.id.removeprefix("h01_contract_")
    return _run(ctx, only=GROUPS[key])


def run(ctx: StageContext) -> dict[str, Any]:
    """전체 계약 strict 검증 (H02 의 단일 입구)."""
    return _run(ctx, only=None)


def _run(ctx: StageContext, *, only: list[str] | None) -> dict[str, Any]:
    report = validate_contract(
        PROJECT_ROOT / "config" / "data_contracts.yaml",
        fail_on="warning",
        waiver_path=PROJECT_ROOT / "config" / "raw_quality_waivers.yaml",
        only=only,
    )
    out = ctx.outputs[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = report["finding_counts"]
    if report["status"] != "pass":
        raise StageFailed(
            f"H01 실패: error={counts.get('error', 0)} 미승인 warning={counts.get('warning', 0)} "
            f"waiver 오류={counts.get('waiver_errors', 0)}",
            [
                {"dataset": d["name"], **f}
                for d in report["datasets"]
                for f in d["findings"]
                if not f.get("waived", False)
            ],
        )
    return {"finding_counts": counts, "datasets": len(report["datasets"])}
