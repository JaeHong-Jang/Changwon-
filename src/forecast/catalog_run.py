"""강우와 허용된 흔적을 읽어 호우 목록 및 실행 증거를 저장한다."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.data import flood_traces as FT
from src.forecast.storm_labels import COVERAGE, assign_roles, label_storms, link_traces, trace_key_columns
from src.forecast.storms import build_catalog, fixed_stations
from src.models.provenance import atomic_write_json, file_sha256, git_state, vector_manifest

ROOT = Path(__file__).resolve().parents[2]
RAIN_PATH = ROOT / "data/processed/canonical/rainfall_hourly.parquet"
STORM_COLUMNS = ["storm_id", "t0", "t1", "year", "n_heavy_hours", "n_stations_active",
                 "r12max_obs", "r3max_obs", "role", "label", "n_linked_traces", "linked_dates",
                 "event_key", "active_year"]


def _counts(storms: pd.DataFrame, traces: pd.DataFrame) -> dict:
    """목록의 역할·라벨·흔적 상태와 개발 연도 키 충돌을 집계한다."""
    # 미확인 라벨과 발생하지 않은 흔적 상태도 명시적으로 기록한다.
    positives = storms[storms.role.eq("development") & storms.label.eq(1).fillna(False)]
    years = positives.groupby("year").size()
    return {"n_storms": len(storms),
            "by_role": {role: int(storms.role.eq(role).sum()) for role in [*COVERAGE, "uncovered"]},
            "by_label": {"1": int(storms.label.eq(1).sum()), "0": int(storms.label.eq(0).sum()),
                         "<NA>": int(storms.label.isna().sum())},
            "development_positive_event_keys": sorted(positives.event_key.dropna().unique().tolist()),
            "development_positive_multiple_storms_by_year": {str(year): int(n) for year, n in years.items() if n > 1},
            "development_positive_missing_event_keys": positives.loc[positives.event_key.isna(), "storm_id"].tolist(),
            "trace_status": {status: int(traces.status.eq(status).sum())
                             for status in ["linked", "unlinked", "undated", "ambiguous",
                                            "role_mismatch", "uncovered_window"]}}


def run(output: Path, roles=("development",)) -> Path:
    """요청한 역할의 흔적만 읽고 고정 규칙의 목록과 manifest를 저장한다."""
    # 역할 인자를 검증하고 입력·저장 식별자를 준비한다.
    roles = tuple(roles)
    if not roles or len(set(roles)) != len(roles) or not set(roles) <= set(COVERAGE):
        raise ValueError("roles는 development·holdout의 중복 없는 비어 있지 않은 목록이어야 한다")
    created = datetime.now(timezone.utc)
    head, dirty = git_state(ROOT, paths=("src", "tests", "config", "docs/FORECAST_PROTOCOL.md"))
    run_id = f"catalog_{created:%Y%m%dT%H%M%SZ}_{head}{'-dirty' if dirty else ''}_{'+'.join(roles)}"
    rain = pd.read_parquet(RAIN_PATH, columns=["station_id", "observed_at", "rainfall_mm", "quality_flag"])
    frames, paths, load_metrics = [], [], {}

    # 명시적으로 요청한 역할만 로드하며 개발 실행에서는 홀드아웃 해시도 읽지 않는다.
    for role in roles:
        selected = FT.files_for(role)
        frame, metrics = FT.load(selected) if role == "development" else FT.load_holdout()
        if not frame.role.eq(role).all():
            raise ValueError(f"{role} 로더의 흔적 역할 불일치")
        frames.append(frame)
        paths.extend(selected)
        load_metrics[role] = metrics
    traces = pd.concat(frames, ignore_index=True)
    keys = trace_key_columns(traces)

    # 전체 지점과 고정 지점에 동일한 목록·연결·라벨 규칙을 적용한다.
    storms = assign_roles(build_catalog(rain))
    links, trace_links = link_traces(storms, traces)
    storms = label_storms(storms, links, roles)
    stations = fixed_stations(rain)
    fixed = assign_roles(build_catalog(rain, stations=stations))
    fixed_links, fixed_trace_links = link_traces(fixed, traces)
    fixed = label_storms(fixed, fixed_links, roles)
    counts = _counts(storms, trace_links)
    counts["n_fixed_stations"] = len(stations)
    counts["fixed_station_ids"] = stations
    counts["fixed_stations_catalog"] = _counts(fixed, fixed_trace_links) if stations else "분석 불가"

    # 실제 사용한 입력의 해시와 재현에 필요한 고정 파라미터를 남긴다.
    inputs = {str(RAIN_PATH.relative_to(ROOT)): file_sha256(RAIN_PATH), **vector_manifest(paths, ROOT)}
    manifest = {"run_id": run_id, "created_utc": created.isoformat(), "git_head": head, "git_dirty": dirty,
                "protocol": "docs/FORECAST_PROTOCOL.md v1.1", "inputs": inputs,
                "params": {"roles": list(roles), "r3_mm": 60.0, "r12_mm": 110.0, "gap_h": 72,
                           "rolling_hours": [3, 12], "feature_window": "[t0-12h,t1]",
                           "label_window_days": [-1, 1], "coverage": COVERAGE,
                           "fixed_station_years": list(range(2006, 2026)), "min_coverage": 0.95,
                           "coverage_end_2025": "2025-09-18 00:00", "timezone": "KST naive"},
                "counts": counts, "trace_key_columns": keys, "trace_load_metrics": load_metrics}
    folder = Path(output) / run_id
    folder.mkdir(parents=True, exist_ok=False)
    storms[STORM_COLUMNS].to_csv(folder / "storms.csv", index=False, date_format="%Y-%m-%d %H:%M")
    fixed[STORM_COLUMNS].to_csv(folder / "storms_fixed_stations.csv", index=False, date_format="%Y-%m-%d %H:%M")
    trace_links.to_csv(folder / "trace_links.csv", index=False, date_format="%Y-%m-%d")
    atomic_write_json(folder / "manifest.json", manifest)
    return folder


def main() -> None:
    """CLI 인자로 출력 경로와 허용된 흔적 역할을 받아 실행한다."""
    # 실행 폴더를 출력해 후속 단계가 저장 결과를 참조할 수 있게 한다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/forecast/catalog"))
    parser.add_argument("--roles", nargs="+", choices=list(COVERAGE), default=["development"])
    args = parser.parse_args()
    print(run(args.output, tuple(args.roles)))


if __name__ == "__main__":
    main()
