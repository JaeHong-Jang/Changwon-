"""H02 시간·통계 정규화. 원본은 수정하지 않고 오류 행은 quarantine에 원행 번호·사유와 함께 격리한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.data.normalize import clean_rainfall, clean_river
from src.data.sgis import load_group
from src.data.validate_raw import resolve_files
from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT

# 하네스 §2 기준선: 2015~2024 커버리지 90% 이상인 29지점이 IDW 의 기본 cohort 다.
# 이보다 줄면 이벤트별 정상지점 24개(min_idw_stations_per_event) 확보가 위태로워진다.
REQUIRED_COHORT = 29
# 분석기간에 유효값이 남은 지점이 하나도 없으면 그 자료로는 사례 분석조차 못 한다.
# 실측(2015~2024): 차룡8교·연덕교 2지점 — 나머지 6지점은 전 기간 0 뿐이다.
REQUIRED_USABLE_RIVER_STATIONS = 1


def _climatology(ctx: StageContext) -> tuple[pd.Timestamp, pd.Timestamp]:
    return (
        pd.Timestamp(ctx.params["analysis.climatology_start"]),
        pd.Timestamp(ctx.params["analysis.climatology_end"]),
    )


def _write(ctx: StageContext, canonical, quarantine) -> None:
    for out in ctx.outputs:
        out.parent.mkdir(parents=True, exist_ok=True)
    canonical.to_parquet(ctx.outputs[0], index=False)
    quarantine.to_csv(ctx.outputs[1], index=False, encoding="utf-8-sig")


def _partition_finding(m: dict[str, Any]) -> dict[str, Any] | None:
    """원본 행이 canonical·quarantine 중 정확히 한 곳에만 있는지 (실제로 깨질 수 있는 검사)."""
    if m["row_partition_ok"]:
        return None
    return {"code": "row_partition", "detail": m["row_partition_detail"]}


def rainfall_long(ctx: StageContext) -> dict[str, Any]:
    """강수 wide→long.

    통과: 원행 분할 무결(canonical ⊎ quarantine == 원본), 정제 후 키 유일,
    분석기간 cohort ≥ 29지점.
    """
    canonical, quarantine, m = clean_rainfall(
        ctx.inputs[0],
        climatology=_climatology(ctx),
        min_station_day_coverage=float(ctx.params["analysis.min_station_day_coverage"]),
    )
    _write(ctx, canonical, quarantine)

    findings = [f for f in [_partition_finding(m)] if f]
    if m["duplicate_keys_after_clean"]:
        findings.append({"code": "duplicate_keys", "detail": m["duplicate_keys_after_clean"]})
    if m["stations_in_cohort"] < REQUIRED_COHORT:
        findings.append({
            "code": "cohort_short",
            "detail": f"유효값 기준 cohort {m['stations_in_cohort']}지점 < 기준 {REQUIRED_COHORT}지점",
        })
    if findings:
        raise StageFailed("강수 정제 통과 기준 미달", findings, metrics=m)
    return m


def river_long(ctx: StageContext) -> dict[str, Any]:
    """하천수위 wide→long.

    통과 기준을 "센티널이 level_cm 에 없다"로 두면 안 된다 — level_cm 은 정의상
    플래그가 ok 인 셀만 담으므로 그 검사는 어떤 입력에도 참이고, 전 셀이 센티널인
    파일도 통과한다. 대신 실제로 깨질 수 있는 두 가지를 본다:
      1) 플래그가 붙은 셀마다 quarantine 기록이 하나씩 있는가 (회계)
      2) 분석기간에 유효값이 남은 지점이 있는가 (자료로서 쓸모)
    """
    canonical, quarantine, m = clean_river(ctx.inputs[0], climatology=_climatology(ctx))
    _write(ctx, canonical, quarantine)

    findings = [f for f in [_partition_finding(m)] if f]
    if not m["cell_accounting_ok"]:
        findings.append({
            "code": "cell_accounting",
            "detail": f"격리 기록 {m['cells_quarantined']}건 != 센티널 {m['sentinel_cells']} + 범위밖 {m['out_of_range_cells']}",
        })
    if m["usable_stations_in_period"] < REQUIRED_USABLE_RIVER_STATIONS:
        findings.append({
            "code": "no_usable_station",
            "detail": f"분석기간 유효값이 남은 지점 {m['usable_stations_in_period']}개 "
                      f"< {REQUIRED_USABLE_RIVER_STATIONS}개 — 센티널·범위밖만 남았다",
        })
    if findings:
        raise StageFailed("수위 정제 통과 기준 미달", findings, metrics=m)
    return m


def sgis_canonical(ctx: StageContext) -> dict[str, Any]:
    """헤더 없는 SGIS CSV를 계약 4컬럼으로 읽어 parquet 저장 (하네스 §6-3).

    통과: 파일 수가 계약의 expected_files 와 일치, 키(year+spatial_id+variable) 유일.
    metrics: 격자·집계구별 files/rows/variables/unique_spatial_ids.
    """
    contract = yaml.safe_load(
        (PROJECT_ROOT / "config" / "data_contracts.yaml").read_text(encoding="utf-8")
    )
    raw_root = PROJECT_ROOT / contract["raw_root"]

    plan = {
        "grid": (["sgis_grid_statistics"], ctx.outputs[0]),
        "aggregation": (["sgis_aggregation_age", "sgis_aggregation_summary"], ctx.outputs[1]),
    }
    metrics: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []

    for label, (dataset_names, out_path) in plan.items():
        paths: list[Path] = []
        expected = 0
        encoding = "utf-8-sig"
        for name in dataset_names:
            spec = contract["datasets"][name]
            paths.extend(resolve_files(raw_root, spec))
            expected += int(spec["expected_files"])
            encoding = spec.get("encoding", encoding)
        df, m = load_group(paths, encoding)
        m["expected_files"] = expected
        metrics[label] = m

        if m["files"] != expected:
            findings.append({"code": "file_count", "dataset": label,
                             "detail": f"{m['files']} != 계약 {expected}"})
        if m["duplicate_keys"]:
            findings.append({"code": "duplicate_keys", "dataset": label,
                             "detail": m["duplicate_keys"]})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)

    if findings:
        raise StageFailed("SGIS 표준화 통과 기준 미달", findings)
    return metrics
