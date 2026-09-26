"""사상 특징·검증·동결 매개변수와 실행 근거를 저장한다."""

import argparse
from datetime import datetime, timezone
import gzip
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from src.forecast.forecast_features import storm_forecast_features
from src.forecast.forecast_plan import block_of
from src.forecast.kma_grid import parse_grid
from src.forecast.trigger_eval import (COMMON_FEATURES, evaluate, frozen_parameters, prepare_table,
                                       primary_endpoint_1, reliability_table, summarize)
from src.forecast.warning_features import storm_warning_features
from src.models.provenance import file_sha256, git_state, write_json


def _json_safe(value):
    """JSON에서 정의 불가 실수는 null로 바꾼다."""
    # 중첩 매개변수에서도 비표준 NaN 토큰을 저장하지 않는다.
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def run(storms_csv, store, cells_csv, warnings_csv, output, *, include_holdout=False):
    """라벨 사상 입력부터 특징·검증·실행 manifest까지 새 폴더에 저장한다."""
    # 월별 수집 근거가 없으면 다른 입력을 읽거나 모형을 적합하기 전에 중단한다.
    coverage_path = Path(warnings_csv).parent / "coverage.csv"
    if not coverage_path.is_file():
        raise FileNotFoundError(f"특보 수집 범위를 확인할 coverage.csv가 없어 실행을 중단합니다: {coverage_path}")
    coverage = pd.read_csv(coverage_path, dtype=str)

    # 홀드아웃은 CSV 입력 직후 제거하며 이후 모든 흐름에 같은 자료만 넘긴다.
    storms = pd.read_csv(storms_csv, dtype={"storm_id": str})
    excluded = {"holdout_disabled": int(storms.role.eq("holdout").sum()) if not include_holdout else 0}
    if not include_holdout:
        storms = storms.loc[storms.role.ne("holdout")].copy()
    covered = storms.role.isin(["development", "holdout"])
    labeled = pd.to_numeric(storms.label, errors="coerce").isin([0, 1])
    excluded.update(uncovered=int((~covered).sum()), unlabeled=int((covered & ~labeled).sum()))
    storms = storms.loc[covered & labeled].copy()
    store = Path(store)
    manifest_path = store / "manifest.csv"
    manifest = pd.read_csv(manifest_path, dtype={"tmfc": str, "tmef": str, "path": str})
    cells = pd.read_csv(cells_csv)
    warnings = pd.read_csv(warnings_csv, dtype=str)
    loaded = {}

    def grid_loader(relative):
        """실제로 쓰는 gzip 예보를 읽고 그 입력 해시를 기록한다."""
        # 파일 누락은 특징 계산에서 수집 실패로 처리하도록 전달한다.
        path = Path(relative)
        path = path if path.is_absolute() else store / path
        with gzip.open(path, "rb") as source:
            grid = parse_grid(source.read())
        loaded[str(path)] = file_sha256(path)
        return grid

    # 읽기·계산·저장을 분리한 계산 모듈로 모든 사상 산출물을 만든다.
    forecast = storm_forecast_features(storms, manifest, cells, grid_loader=grid_loader, block_of=block_of)
    warning = storm_warning_features(storms, warnings, coverage=coverage)
    data = prepare_table(storms, forecast, warning, include_holdout=include_holdout)
    predictions = evaluate(data, include_holdout=include_holdout)
    metrics = summarize(predictions)
    reliability = reliability_table(predictions)
    endpoint = primary_endpoint_1(metrics)
    frozen = frozen_parameters(data)
    root = Path(__file__).resolve().parents[2]
    head, dirty = git_state(root)
    run_id = "trigger_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + (head or "unknown") + ("-dirty" if dirty else "")
    destination = Path(output) / run_id
    destination.mkdir(parents=True, exist_ok=False)
    features = forecast.merge(storms, on="storm_id", how="left", validate="many_to_one").merge(warning, on="storm_id", how="left", validate="many_to_one")
    for name, table in (("features", features), ("predictions", predictions), ("metrics", metrics), ("reliability", reliability)):
        table.to_csv(destination / f"{name}.csv", index=False)
    write_json(destination / "primary_endpoint.json", _json_safe(dict(endpoint, run_id=run_id)))
    write_json(destination / "frozen_params.json", _json_safe(frozen))

    # 제외 사유와 실패 fold를 수치와 함께 남겨 결측이나 수렴 실패를 숨기지 않는다.
    common = np.isfinite(data[COMMON_FEATURES]).all(axis=1) & data[COMMON_FEATURES].ge(0).all(axis=1)
    excluded["missing_common_features"] = int((~common).sum())
    metadata = dict(run_id=run_id, protocol_version="v1.1", include_holdout=include_holdout,
                    command=" ".join(sys.argv), git=head, dirty=dirty,
                    inputs={str(path): file_sha256(Path(path)) for path in (storms_csv, manifest_path, cells_csv, warnings_csv, coverage_path)},
                    forecast_inputs=loaded, protocol_sha256=file_sha256(root / "docs/FORECAST_PROTOCOL.md"),
                    n_input_excluded=sum(excluded[key] for key in ("holdout_disabled", "uncovered", "unlabeled")),
                    n_common_excluded=int((~common).sum()), excluded_by_reason=excluded,
                    feature_status_counts={str(key): int(value) for key, value in forecast.status.value_counts().items()},
                    n_warning_na_storms=int(warning.warn_status.ne("ok").sum()),
                    warning_status_counts={str(key): int(value) for key, value in warning.warn_status.value_counts().items()},
                    convergence_failure_folds=predictions.attrs["convergence_failure_folds"],
                    failed_fit_folds=len(predictions.attrs["fit_failures"]), fit_failures=predictions.attrs["fit_failures"],
                    frozen_fit_failures={name: {model: params.get("reason") for model, params in models.items()
                                               if isinstance(params, dict) and not params["converged"]} for name, models in frozen.items()},
                    bootstrap=dict(n=2000, seed=20260926, unit="storm", refit=False),
                    forecast_status_policy="collection_error => NA; all_missing blocks excluded; partial availability flagged",
                    prediction_warn="M_* and B_clim: p >= fold training prevalence; rules: original binary warning",
                    frozen_training="S1 common development; V3 before 2020-01-01; all_dev includes all development")
    write_json(destination / "manifest.json", _json_safe(metadata))
    return destination


def main():
    """명령행 입력 경로와 리더 전용 홀드아웃 선택을 읽어 실행한다."""
    # 기본 실행은 개발 사상만 사용하고 홀드아웃은 명시적 선택으로 제한한다.
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("storms", "store", "cells", "warnings", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--include-holdout", action="store_true")
    args = parser.parse_args()
    try:
        destination = run(args.storms, args.store, args.cells, args.warnings, args.output, include_holdout=args.include_holdout)
    except FileNotFoundError as error:
        parser.error(str(error))
    print(destination)


if __name__ == "__main__":
    main()
