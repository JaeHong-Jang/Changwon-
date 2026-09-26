"""공간 보정·결합 평가·보고용 지도를 한 실행 폴더에 기록한다."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import flood_traces as FT
from src.forecast import combined_eval as CE
from src.forecast import location_calibration as LC
from src.forecast import spatial_refit as SR
from src.forecast import storm_cell_labels as SL
from src.forecast.scenario_maps import scenario_probability, write_maps
from src.models import features
from src.models.provenance import file_sha256, git_state, vector_manifest, write_json

ROOT = Path(__file__).resolve().parents[2]
MODELS = ("M_fc24", "M_obs", "M_int", "B_clim")
HOLDOUT_NAME = "결과와 일부 예보값에 사전 노출된 post-hoc 설계의 후향 평가"
INTERPRETATION = "결합 확률의 Brier 개선이며 위치 예측 개선이 아님"
PER_STORM_COLUMNS = ("scheme", "model", "storm_id", "label", "n_cells", "sse", "sse_ref",
                     "mean_brier", "mean_brier_ref", "predicted_area", "observed_area", "area_error",
                     "included", "exclusion_reason", "p", "p_ref")
SUMMARY_COLUMNS = ("scheme", "set", "subset", "model", "n_storms", "n_cells", "brier",
                   "brier_ref", "bss", "bss_ci_lo", "bss_ci_hi", "n_boot_valid",
                   "n_boot_excluded", "positive_n_storms", "positive_mean_brier",
                   "positive_sse_share", "negative_n_storms", "negative_mean_brier",
                   "negative_sse_share")
POSITIVE_COLUMNS = ("scheme", "storm_id", "n_positive_cells", "cell_auc", "top20_capture",
                    "object_auc", "n_objects", "included", "exclusion_reason")


def _json_ready(value):
    """비유한 수를 JSON null로 바꾸고 numpy 스칼라를 정리한다."""
    # 중첩 결과의 수치와 목록을 재귀적으로 직렬화 가능하게 만든다.
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _positive_years(storms: pd.DataFrame, labels: dict) -> tuple[tuple[str, ...], dict]:
    """개발 양성 사상과 기존 학습 연도의 일대일 대응을 확인한다."""
    # 양성 사상의 event_key가 연도와 같고 유일한지 검사한다.
    rows = storms.loc[storms["role"].eq("development") & storms["label"].eq(1)].copy()
    rows["event_key"] = rows["event_key"].astype(str)
    if rows.empty or rows["event_key"].duplicated().any() or not rows["event_key"].eq(rows["year"].astype(str)).all():
        raise ValueError("개발 양성 사상과 연도가 1:1이 아니다")
    mapping = {}
    for row in rows.itertuples():
        sid = str(row.storm_id)
        if sid not in labels:
            raise ValueError(f"{sid}: 양성 격자 라벨이 없다")
        mapping[str(row.event_key)] = labels[sid]
    return tuple(sorted(mapping)), mapping


def _prediction_table(predictions: pd.DataFrame, scheme: str) -> pd.DataFrame:
    """주 분석 S1·common의 중복 없는 발생 확률만 고른다."""
    # 모델별 같은 사상 예측을 하나만 허용하고 결측도 제외 사유 집계에 남긴다.
    selected = predictions.loc[predictions["scheme"].eq(scheme) & predictions["set"].eq("common") &
                               predictions["subset"].eq("S1") & predictions["model"].isin(MODELS)].copy()
    if selected.duplicated(["storm_id", "model"]).any():
        raise ValueError("같은 사상·모델 예측이 중복됐다")
    selected["p"] = pd.to_numeric(selected["p"], errors="coerce")
    if "p_ref" in selected:
        selected["p_ref"] = pd.to_numeric(selected["p_ref"], errors="coerce")
    return selected


def run(storms_csv, trace_links_csv, predictions_csv, frozen_params_json, output, *,
        include_holdout: bool = False, write_scenarios: bool = True) -> Path:
    """개발 결합 평가와 선택적 리더 홀드아웃 평가를 산출물로 저장한다."""
    # 입력과 격자 순서를 읽고 역할이 없는 사상은 평가에서 제외한다.
    paths = [Path(path) for path in (storms_csv, trace_links_csv, predictions_csv, frozen_params_json)]
    storms = pd.read_csv(paths[0], dtype={"storm_id": str, "event_key": str})
    links = pd.read_csv(paths[1], dtype={"storm_id": str, "source_id": str, "object_id": str,
                                         "source_record_id": str, "trace_key": str})
    predictions = pd.read_csv(paths[2], dtype={"storm_id": str})
    frozen = json.loads(paths[3].read_text(encoding="utf-8"))
    allowed = {"development", "holdout"} if include_holdout else {"development"}
    storms = storms.loc[storms["role"].isin(allowed) & storms["label"].notna()].copy()
    if not np.isfinite(pd.to_numeric(storms["label"], errors="coerce")).all() or not storms["label"].isin([0, 1]).all():
        raise ValueError("사상 라벨은 유한한 0/1이어야 한다")
    storms["label"] = storms["label"].astype(int)
    links = links.loc[links["storm_id"].isin(storms["storm_id"])].copy()
    predictions = predictions.loc[predictions["role"].isin(allowed)].copy()
    layer, frame, _, _, _ = features.load_development()
    SR.clear_cache()

    # 개발 흔적만 읽고 요청받은 경우에만 홀드아웃 흔적을 추가한다.
    trace_files = list(FT.files_for("development"))
    development, _ = FT.load(trace_files)
    trace_parts = [development]
    if include_holdout:
        trace_files.extend(FT.files_for("holdout"))
        holdout, _ = FT.load_holdout()
        trace_parts.append(holdout)
    import geopandas as gpd

    # 동일한 원본 키 생성 규칙으로 사상별 라벨과 객체를 구성한다.
    traces = gpd.GeoDataFrame(pd.concat(trace_parts, ignore_index=True), geometry="geometry", crs=development.crs)
    labels = SL.storm_labels(storms, links, traces, layer)
    objects = SL.storm_objects(storms, links, traces)
    dev_years, labels_by_year = _positive_years(storms, labels)
    fit = lambda years: SR.fit_scores(tuple(years), layer, frame)

    # 개발 음성 보정을 한 번 만들고 양성은 각각 이중 제외 보정한다.
    q_by_storm = {}
    calibration = {}
    negative_score, negative_params = LC.v1_negative(dev_years, fit, labels_by_year)
    for row in storms.loc[storms["role"].eq("development")].itertuples():
        sid = str(row.storm_id)
        if row.label == 1:
            score, params = LC.v1_positive(str(row.event_key), dev_years, fit, labels_by_year)
        else:
            score, params = negative_score, negative_params
        estimate = LC.platt_predict(params, score)
        calibration[sid] = {"scheme": "V1_loso", "event_key": str(row.event_key), **params}
        if params["converged"] and np.isfinite(estimate).all():
            q_by_storm[sid] = estimate
        else:
            calibration[sid]["failure_reason"] = params.get("failure_reason", "보정 결과가 비유한이다")

    # 홀드아웃 평가는 명시 옵션에서만 2019년까지 점수와 보정을 재사용한다.
    if include_holdout:
        early = ("2006", "2012", "2014", "2016", "2019")
        score, params = LC.v3(early, fit, labels_by_year)
        for sid in storms.loc[storms["role"].eq("holdout"), "storm_id"]:
            estimate = LC.platt_predict(params, score)
            calibration[str(sid)] = {"scheme": "V3_frozen", **params}
            if params["converged"] and np.isfinite(estimate).all():
                q_by_storm[str(sid)] = estimate
            else:
                calibration[str(sid)]["failure_reason"] = params.get("failure_reason", "보정 결과가 비유한이다")

    # 예보 결측과 보정 실패를 모형별로 구분해 결합 평가의 분모를 기록한다.
    per_frames, metric_rows, positive_frames = [], [], []
    missing, calibration_missing, reference_missing, location_missing, valid_storms = {}, {}, {}, {}, {}
    for scheme, role in (("V1_loso", "development"), ("V3_frozen", "holdout")):
        if role == "holdout" and not include_holdout:
            continue
        candidate = storms.loc[storms["role"].eq(role)].copy()
        table = _prediction_table(predictions, scheme)
        probabilities = {model: dict(zip(part.loc[part["p"].between(0, 1), "storm_id"],
                                         part.loc[part["p"].between(0, 1), "p"]))
                         for model, part in table.groupby("model")}
        baseline = probabilities.get("B_clim", {})
        for model in MODELS:
            p = probabilities.get(model, {})
            rows = table.loc[table["model"].eq(model)]
            reference = (dict(zip(rows["storm_id"], rows["p_ref"])) if "p_ref" in table
                         else baseline)
            ids = set(candidate["storm_id"])
            missing[f"{scheme}/{model}"] = len(ids - set(p))
            calibration_missing[f"{scheme}/{model}"] = len(ids - set(q_by_storm))
            reference_missing[f"{scheme}/{model}"] = len(ids - set(reference)) + sum(
                not np.isfinite(reference[sid]) or not 0 <= reference[sid] <= 1
                for sid in ids & set(reference))
            included = {sid for sid in ids & set(p) & set(q_by_storm) & set(reference)
                        if np.isfinite(reference[sid]) and 0 <= reference[sid] <= 1}
            selected = candidate.loc[candidate["storm_id"].isin(included)]
            per = CE.evaluate_storms(selected, p, q_by_storm, labels, reference)
            valid_storms[f"{scheme}/{model}"] = len(per)
            metric_rows.append({"scheme": scheme, "set": "common", "subset": "S1", "model": model,
                                **CE.summarize(per)})

            # 누락 사상도 행으로 남겨 모형별 제외 이유와 기준 확률을 추적한다.
            excluded = []
            for row in candidate.itertuples():
                sid = str(row.storm_id)
                if sid in included:
                    continue
                reasons = []
                if sid not in p:
                    reasons.append("missing_prediction")
                if sid not in reference or not np.isfinite(reference[sid]) or not 0 <= reference[sid] <= 1:
                    reasons.append("missing_reference")
                if sid not in q_by_storm:
                    reasons.append("calibration_failed")
                excluded.append({"storm_id": sid, "label": row.label, "included": False,
                                 "exclusion_reason": ";".join(reasons), "p": p.get(sid, np.nan),
                                 "p_ref": reference.get(sid, np.nan)})
            if not per.empty:
                per["included"] = True
                per["exclusion_reason"] = ""
                per["p"] = per["storm_id"].map(p)
                per["p_ref"] = per["storm_id"].map(reference)
            report = pd.concat([per, pd.DataFrame(excluded)], ignore_index=True).reindex(columns=PER_STORM_COLUMNS[2:])
            report.insert(0, "model", model)
            report.insert(0, "scheme", scheme)
            per_frames.append(report)

        # 위치 지표는 보정된 모든 양성 사상에서 예보값 유무와 무관하게 계산한다.
        positive_ids = [sid for sid in candidate["storm_id"] if sid in labels and sid in q_by_storm]
        failed_positive = [sid for sid in candidate["storm_id"] if sid in labels and sid not in q_by_storm]
        location_missing[scheme] = len(failed_positive)
        if positive_ids:
            positive = CE.positive_storm_metrics({sid: q_by_storm[sid] for sid in positive_ids},
                                                 {sid: labels[sid] for sid in positive_ids},
                                                 {sid: objects[sid] for sid in positive_ids}, layer)
            positive["included"] = True
            positive["exclusion_reason"] = ""
        else:
            positive = pd.DataFrame()
        if failed_positive:
            excluded_location = pd.DataFrame({"storm_id": failed_positive, "included": False,
                                              "exclusion_reason": "calibration_failed"})
            positive = pd.concat([positive, excluded_location], ignore_index=True)
        if not positive.empty:
            positive.insert(0, "scheme", scheme)
            positive_frames.append(positive)

    # 출력 폴더와 기본 산출물을 만들고 주 판정이 없으면 이유를 남긴다.
    head, dirty = git_state(ROOT)
    run_id = f"combined_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{head}" + ("-dirty" if dirty else "")
    target = Path(output) / run_id
    target.mkdir(parents=True, exist_ok=False)
    per_storm = (pd.concat(per_frames, ignore_index=True) if per_frames else pd.DataFrame()).reindex(
        columns=PER_STORM_COLUMNS)
    metrics = pd.DataFrame(metric_rows).reindex(columns=SUMMARY_COLUMNS)
    positive = (pd.concat(positive_frames, ignore_index=True) if positive_frames else pd.DataFrame()).reindex(
        columns=POSITIVE_COLUMNS)
    per_storm.to_csv(target / "per_storm.csv", index=False)
    metrics.to_csv(target / "combined_metrics.csv", index=False)
    positive.to_csv(target / "positive_storm_metrics.csv", index=False)
    main = next((row for row in metric_rows if row["scheme"] == "V1_loso" and row["model"] == "M_fc24"), None)
    endpoint = (CE.primary_endpoint_2(main) if main is not None and main["n_storms"] > 0 else
                {"status": "unavailable", "reason": "주 모형 유효 사상 없음"})
    endpoint["interpretation"] = INTERPRETATION
    if include_holdout:
        endpoint["holdout_result_name"] = HOLDOUT_NAME
    write_json(target / "primary_endpoint.json", _json_ready(endpoint))

    # 지도는 개발 전체 점수·보정과 동결된 발생 모형으로만 만든다.
    if write_scenarios:
        score, params = LC.scenario(dev_years, fit, labels_by_year)
        q = LC.platt_predict(params, score)
        calibration["scenario"] = {"scheme": "development_all", **params}
        if params["converged"] and np.isfinite(q).all():
            scenarios = scenario_probability(frozen["all_dev"]["M_fc24"], q, layer["grid_id"].to_numpy())
            write_maps(scenarios, layer, target / "scenarios")
        else:
            calibration["scenario"]["failure_reason"] = params.get("failure_reason", "보정 결과가 비유한이다")
    write_json(target / "calibration.json", _json_ready(calibration))

    # 입력 해시와 공간 적합 횟수를 공통 provenance 함수로 기록한다.
    processed_paths = [features.ROOT / "data/processed/layers/layer1_flood.gpkg",
                       features.ROOT / "data/processed/features/grid_features.parquet"]
    inputs = {str(path): file_sha256(path) for path in paths}
    inputs.update({str(path.relative_to(ROOT)): file_sha256(path) for path in processed_paths if path.exists()})
    inputs.update(vector_manifest(trace_files, ROOT))
    manifest = {"run_id": run_id, "protocol": "FORECAST_PROTOCOL v1.1", "spatial_design": "post-hoc",
                "include_holdout": include_holdout,
                "interpretation": INTERPRETATION,
                "input_sha256": inputs,
                "frozen_model": SR.FROZEN_INFO, "spatial_fit_count": len(SR.FIT_LOG),
                "spatial_fits": SR.FIT_LOG, "storm_labels": SL.LABEL_COUNTS,
                "missing_prediction_counts": missing,
                "valid_storm_counts": valid_storms,
                "calibration_exclusion_counts": calibration_missing,
                "location_exclusion_counts": location_missing,
                "missing_reference_counts": reference_missing}
    if include_holdout:
        manifest["holdout_result_name"] = HOLDOUT_NAME
    write_json(target / "manifest.json", _json_ready(manifest))
    return target


def main() -> None:
    """CLI 입력 경로와 선택 옵션을 실행기에 전달한다."""
    # 사전 고정 입력과 출력 옵션을 파싱한다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storms", required=True)
    parser.add_argument("--trace-links", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--frozen-params", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--include-holdout", action="store_true")
    parser.add_argument("--no-scenarios", action="store_true")
    args = parser.parse_args()
    print(run(args.storms, args.trace_links, args.predictions, args.frozen_params, args.output,
              include_holdout=args.include_holdout, write_scenarios=not args.no_scenarios))


if __name__ == "__main__":
    main()
