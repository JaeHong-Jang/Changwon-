"""결합 평가의 누수 경계와 합성 격자 계산을 검증한다."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from src.forecast import combined_eval as CE
from src.forecast import combined_run as CR
from src.forecast import location_calibration as LC
from src.forecast import scenario_maps as SM
from src.forecast import spatial_refit as SR
from src.forecast import storm_cell_labels as SL
from src.forecast.storm_labels import trace_keys


def grid():
    """같은 면적의 EPSG:5179 격자 네 칸을 만든다."""
    # 합성 지도에서 겹침과 동점 순서를 명확히 한다.
    return gpd.GeoDataFrame({"grid_id": [2, 1, 3, 4]}, geometry=[box(i, 0, i + 1, 1) for i in range(4)],
                            crs="EPSG:5179")


class FakePipeline:
    """합집합 라벨의 양성 수를 확률로 돌려주는 가짜 파이프라인."""

    def get_params(self, deep=True):
        """sklearn clone에 필요한 생성자 매개변수를 반환한다."""
        # 가짜 모형에는 조정 매개변수가 없다.
        return {}

    def fit(self, X, y):
        """학습 격자 라벨을 기억한다."""
        # 합집합 결과를 예측에서 확인할 수 있게 둔다.
        self.y = np.asarray(y, bool)
        return self

    def predict_proba(self, X):
        """양성 격자에 높은 확률을 준다."""
        # 두 확률 열의 합을 1로 유지한다.
        score = np.where(self.y, 0.8, 0.2)
        return np.column_stack((1 - score, score))


class ForecastCombinedTest(unittest.TestCase):
    """합성 자료에서 공간 적합·보정·평가·실행 경계를 검증한다."""

    def test_fit_cache_and_union(self):
        """같은 사상 집합을 한 번만 적합하고 라벨 합집합을 쓴다."""
        # 특징과 사상 라벨 두 열을 만든다.
        layer = pd.DataFrame({"grid_id": [1, 2, 3], "trace_ev_2006": [1, 0, 0],
                              "trace_ev_2012": [0, 1, 0]})
        frame = pd.DataFrame({"grid_id": [1, 2, 3], "x": [1, 2, 3]})
        SR.clear_cache()
        with patch.object(SR, "load_frozen_pipeline", return_value=(FakePipeline(), ["x"])):
            first = SR.fit_scores(("2012", "2006"), layer, frame)
            second = SR.fit_scores(("2006", "2012"), layer, frame)
        self.assertIs(first, second)
        np.testing.assert_allclose(first, [0.8, 0.8, 0.2])
        self.assertEqual(len(SR.FIT_LOG), 1)

    def test_calibration_exclusions_and_clip(self):
        """V1 이중 제외와 V3 연도 경계 및 Platt 절단을 확인한다."""
        # 호출된 학습 사상을 기록해 평가 사상이 한 번도 섞이지 않는지 본다.
        calls = []
        def fit(years):
            """호출 연도를 남기고 합성 공간 점수를 반환한다."""
            # 세 격자에 변화하는 확률을 준다.
            calls.append(tuple(years))
            return np.array([0.2, 0.5, 0.8])
        labels = {year: np.array([0, 1, 1]) for year in ("2006", "2012", "2014", "2025")}
        score, params = LC.v1_positive("2006", ("2006", "2012", "2014", "2025"), fit, labels)
        self.assertEqual(len(score), 3)
        self.assertTrue(all("2006" not in call for call in calls))
        self.assertIn(("2014", "2025"), calls)
        self.assertEqual(params["n_events"], 3)
        calls.clear()
        LC.v3(("2006", "2012", "2014"), fit, labels)
        self.assertTrue(all("2025" not in call for call in calls))
        with self.assertRaises(ValueError):
            LC.v3(("2006", "2025"), fit, labels)
        fitted = LC.platt_fit([(np.array([0.2, 0.4, 0.6, 0.8]), np.array([0, 1, 0, 1]))] * 5)
        predicted = LC.platt_predict({"c": 0.0, "d": 1.0}, np.array([0.0, 1.0]))
        np.testing.assert_allclose(predicted, [1e-6, 1 - 1e-6])
        self.assertEqual(fitted["n_cells"], 20)
        self.assertTrue(fitted["converged"])
        self.assertGreater(fitted["d"], 0)

    def test_linked_labels_only(self):
        """ambiguous·undated 흔적은 사상 격자 라벨에 넣지 않는다."""
        # 세 도형 가운데 linked 한 개만 첫 격자에 둔다.
        grid_frame = grid()
        traces = gpd.GeoDataFrame({"source_id": ["s"] * 3, "object_id": ["a", "b", "c"],
                                   "role": ["development"] * 3, "storm_id": ["original"] * 3},
                                  geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)],
                                  crs="EPSG:5179")
        storms = pd.DataFrame({"storm_id": ["e", "n"], "role": ["development"] * 2, "label": [1, 0]})
        links = pd.DataFrame({"trace_key": ["s|a", "s|b", "s|c"],
                              "source_id": ["s"] * 3, "object_id": ["a", "b", "c"],
                              "role": ["development"] * 3, "storm_id": ["e", "e", "e"],
                              "status": ["linked", "ambiguous", "undated"]})
        labels = SL.storm_labels(storms, links, traces, grid_frame)
        np.testing.assert_array_equal(labels["e"], [1, 0, 0, 0])
        self.assertNotIn("n", labels)

        # 연결 도형이 있어도 겹침 10% 미만이면 양성 사상을 0 격자로 보존한다.
        tiny = gpd.GeoDataFrame({"source_id": ["s"], "object_id": ["d"], "role": ["development"]},
                                geometry=[box(3, 0, 3.05, 0.05)], crs="EPSG:5179")
        extended_storms = pd.concat([storms, pd.DataFrame({"storm_id": ["z"], "role": ["development"],
                                                          "label": [1]})], ignore_index=True)
        extended_links = pd.concat([links, pd.DataFrame({"trace_key": ["s|d"],
                                                        "source_id": ["s"], "object_id": ["d"],
                                                        "role": ["development"], "storm_id": ["z"],
                                                        "status": ["linked"]})], ignore_index=True)
        extended_traces = gpd.GeoDataFrame(pd.concat([traces, tiny], ignore_index=True),
                                           geometry="geometry", crs="EPSG:5179")
        extended = SL.storm_labels(extended_storms, extended_links, extended_traces, grid_frame)
        self.assertFalse(extended["z"].any())
        self.assertEqual(SL.LABEL_COUNTS["n_positive_zero_cells"], 1)

    def test_trace_key_disambiguation_and_role(self):
        """같은 기본 키의 원본 행을 따로 연결하고 역할 교차를 거부한다."""
        # 전체 흔적 표의 확장 키로 같은 객체 ID의 서로 다른 행을 구분한다.
        traces = gpd.GeoDataFrame({"source_id": ["s", "s"], "object_id": ["a", "a"],
                                   "source_record_id": ["r1", "r2"],
                                   "role": ["development", "development"]},
                                  geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs="EPSG:5179")
        storms = pd.DataFrame({"storm_id": ["e"], "role": ["development"], "label": [1]})
        links = pd.DataFrame({"trace_key": ["s|a|r1", "s|a|r2"], "storm_id": ["e", "e"],
                              "role": ["development", "development"], "status": ["linked", "linked"]})
        self.assertEqual(trace_keys(traces).tolist(), links.trace_key.tolist())
        np.testing.assert_array_equal(SL.storm_labels(storms, links, traces, grid())["e"], [1, 1, 0, 0])
        self.assertEqual(len(SL.storm_objects(storms, links, traces)["e"]), 2)

        # 링크와 원본 역할 또는 사상 역할이 다르면 객체를 선택하지 않는다.
        crossed = links.copy()
        crossed.loc[1, "role"] = "holdout"
        with self.assertRaisesRegex(ValueError, "역할"):
            SL.storm_objects(storms, crossed, traces)
        crossed = links.copy()
        crossed["role"] = "holdout"
        traces["role"] = "holdout"
        with self.assertRaisesRegex(ValueError, "역할"):
            SL.storm_objects(storms, crossed, traces)
        duplicated = pd.concat([links, links.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "여러 사상"):
            SL.storm_objects(storms, duplicated, traces)

    def test_brier_bootstrap_and_area(self):
        """음성 제곱오차·기여율·면적 오차·분모 0을 확인한다."""
        # 양성과 음성을 각각 두 격자로 평가한다.
        storms = pd.DataFrame({"storm_id": ["p", "n"], "label": [1, 0]})
        per = CE.evaluate_storms(storms, {"p": 0.5, "n": 0.5},
                                  {"p": np.array([0.8, 0.2]), "n": np.array([0.8, 0.2])},
                                  {"p": np.array([1, 0])}, {"p": 0.25, "n": 0.25})
        self.assertAlmostEqual(per.loc[1, "sse"], 0.17)
        self.assertAlmostEqual(per.loc[0, "area_error"], -0.5)
        summary = CE.summarize(per, n_boot=50)
        self.assertEqual(summary, CE.summarize(per, n_boot=50))
        self.assertAlmostEqual(summary["positive_sse_share"] + summary["negative_sse_share"], 1)
        zero = per.copy()
        zero["sse_ref"] = 0.0
        self.assertTrue(np.isnan(CE.summarize(zero, n_boot=10)["bss"]))
        self.assertEqual(CE.summarize(zero, n_boot=10)["n_boot_excluded"], 10)

    def test_invalid_combined_inputs_and_nonconverged_calibration(self):
        """비유한 격자 라벨·범위 밖 q와 비수렴 계수를 차단한다."""
        # 평가 입력의 q와 격자 라벨을 각각 독립적으로 검사한다.
        storms = pd.DataFrame({"storm_id": ["e"], "label": [1]})
        for score, label in (([np.nan, 0.2], [1, 0]), ([1.1, 0.2], [1, 0]),
                             ([0.2, 0.2], [np.nan, 0]), ([0.2, 0.2], [0.5, 0])):
            with self.assertRaises(ValueError):
                CE.evaluate_storms(storms, {"e": 0.5}, {"e": score}, {"e": label}, {"e": 0.25})
        for invalid_label in (2, np.nan):
            with self.assertRaises(ValueError):
                CE.evaluate_storms(storms.assign(label=invalid_label), {"e": 0.5}, {"e": [0.2, 0.2]},
                                   {"e": [1, 0]}, {"e": 0.25})

        # 최적화 실패가 유한 계수를 남겨도 예측 전부를 NA로 만든다.
        class Failed:
            """최적화 실패와 유한 계수를 가진 합성 결과다."""
            x = np.array([0.0, 1.0])
            success = False
            message = "synthetic nonconvergence"
        with patch.object(LC, "minimize", return_value=Failed()):
            params = LC.platt_fit([(np.array([0.2, 0.8]), np.array([0, 1]))])
        self.assertFalse(params["converged"])
        self.assertEqual(params["failure_reason"], "synthetic nonconvergence")
        self.assertTrue(np.isnan(LC.platt_predict(params, np.array([0.2, 0.8]))).all())

    def test_tied_capture_and_grade(self):
        """동점은 grid_id 순으로 자르고 0.01은 등급 1에 둔다."""
        # 다섯 격자 중 한 칸만 뽑을 때 작은 grid_id가 선택된다.
        cells = gpd.GeoDataFrame({"grid_id": [5, 1, 2, 3, 4]},
                                 geometry=[box(i, 0, i + 1, 1) for i in range(5)], crs="EPSG:5179")
        obj = gpd.GeoDataFrame({"object_id": ["a"]}, geometry=[box(1, 0, 2, 1)], crs="EPSG:5179")
        result = CE.positive_storm_metrics({"e": np.ones(5) * 0.5},
                                           {"e": np.array([0, 1, 0, 0, 0])}, {"e": obj}, cells)
        self.assertEqual(result.loc[0, "top20_capture"], 1.0)
        with patch.object(SM, "predict_raw", return_value=np.array([1.0])):
            frame = SM.scenario_probability({}, [0.009, 0.01, 0.05, 0.1, 0.2], range(5), (60,))
        self.assertEqual(frame["grade"].tolist(), [0, 1, 2, 3, 4])

    def test_development_run_does_not_load_holdout(self):
        """작은 합성 전 과정에서 홀드아웃 로더와 행을 배제한다."""
        # 개발 양성 세 사상과 음성 한 사상의 입력 파일을 만든다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            storms = pd.DataFrame({"storm_id": ["a", "b", "c", "n", "h"],
                                   "role": ["development"] * 4 + ["holdout"],
                                   "year": [2006, 2012, 2014, 2014, 2022],
                                   "event_key": ["2006", "2012", "2014", "", "h"],
                                   "label": [1, 1, 1, 0, 1]})
            storms.to_csv(root / "storms.csv", index=False)
            links = pd.DataFrame({"trace_key": ["s|a", "s|b", "s|c", "s|h"],
                                  "source_id": ["s"] * 4, "object_id": ["a", "b", "c", "h"],
                                  "role": ["development"] * 3 + ["holdout"],
                                  "storm_id": ["a", "b", "c", "h"], "status": ["linked"] * 4})
            links.to_csv(root / "links.csv", index=False)
            rows = [{"storm_id": sid, "role": role, "label": label, "model": model,
                     "scheme": "V1_loso" if role == "development" else "V3_frozen",
                     "set": "common", "subset": "S1",
                     "p": np.nan if sid == "b" and model == "M_fc24" else 0.5,
                     "p_ref": 0.25 if model == "M_fc24" else 0.5}
                    for sid, role, label in zip(storms.storm_id, storms.role, storms.label)
                    for model in ("M_fc24", "B_clim")]
            pd.DataFrame(rows).to_csv(root / "predictions.csv", index=False)
            (root / "frozen.json").write_text(json.dumps({"all_dev": {"M_fc24": {}}}))
            cells = grid()
            for year, values in ((2006, [1, 0, 0, 0]), (2012, [0, 1, 0, 0]), (2014, [0, 0, 1, 0])):
                cells[f"trace_ev_{year}"] = values
            frame = pd.DataFrame({"grid_id": cells.grid_id, "x": range(4)})
            traces = gpd.GeoDataFrame({"source_id": ["s"] * 3, "object_id": ["a", "b", "c"],
                                       "role": ["development"] * 3},
                                      geometry=[box(i, 0, i + 1, 1) for i in range(3)], crs="EPSG:5179")

            # 한 양성 사상의 보정 실패를 주입해 결합·위치 제외 기록을 검증한다.
            original_positive = LC.v1_positive
            def positive_with_failure(event, years, fit, labels):
                """2014년 합성 사상에 비수렴 보정을 주입한다."""
                # 다른 사상은 실제 합성 보정 절차를 그대로 쓴다.
                score, params = original_positive(event, years, fit, labels)
                if event == "2014":
                    params = {**params, "converged": False, "failure_reason": "synthetic failure"}
                return score, params

            # 실제 파일 입출력만 쓰고 공간 적합과 흔적 로더를 주입한다.
            with patch.object(CR.features, "load_development", return_value=(cells, frame, None, None, None)), \
                 patch.object(CR.features, "ROOT", root), \
                 patch.object(CR.FT, "files_for", return_value=[]), \
                 patch.object(CR.FT, "load", return_value=(traces, {})), \
                 patch.object(CR.FT, "load_holdout") as holdout, \
                 patch.object(CR.LC, "v1_positive", side_effect=positive_with_failure), \
                 patch.object(CR.SR, "fit_scores", return_value=np.array([0.2, 0.4, 0.6, 0.8])), \
                 patch.object(SM, "predict_raw", return_value=np.array([0.5])):
                out = CR.run(root / "storms.csv", root / "links.csv", root / "predictions.csv",
                             root / "frozen.json", root / "output", write_scenarios=True)
                # p_ref 열이 없는 구형 입력은 B_clim 행 확률로 기준을 되돌린다.
                pd.DataFrame(rows).drop(columns="p_ref").to_csv(root / "legacy.csv", index=False)
                legacy = CR.run(root / "storms.csv", root / "links.csv", root / "legacy.csv",
                                root / "frozen.json", root / "legacy_output", write_scenarios=False)
            holdout.assert_not_called()
            per = pd.read_csv(out / "per_storm.csv")
            self.assertEqual(set(per.storm_id), {"a", "b", "c", "n"})
            fc = per.loc[per.model.eq("M_fc24")].set_index("storm_id")
            self.assertAlmostEqual(fc.loc["a", "p_ref"], 0.25)
            legacy_fc = pd.read_csv(legacy / "per_storm.csv").query("model == 'M_fc24'").set_index("storm_id")
            self.assertAlmostEqual(legacy_fc.loc["a", "p_ref"], 0.5)
            self.assertIn("missing_prediction", fc.loc["b", "exclusion_reason"])
            self.assertIn("calibration_failed", fc.loc["c", "exclusion_reason"])
            positive = pd.read_csv(out / "positive_storm_metrics.csv")
            self.assertEqual(set(positive.storm_id), {"a", "b", "c"})
            self.assertTrue(np.isnan(positive.set_index("storm_id").loc["c", "cell_auc"]))
            self.assertEqual(positive.set_index("storm_id").loc["c", "exclusion_reason"], "calibration_failed")
            calibration = json.loads((out / "calibration.json").read_text())
            self.assertEqual(calibration["c"]["failure_reason"], "synthetic failure")
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["missing_prediction_counts"]["V1_loso/M_fc24"], 1)
            self.assertEqual(manifest["calibration_exclusion_counts"]["V1_loso/M_fc24"], 1)
            self.assertEqual(manifest["location_exclusion_counts"]["V1_loso"], 1)
            self.assertIn(CR.INTERPRETATION, manifest["interpretation"])
            self.assertTrue((out / "manifest.json").exists())
            self.assertEqual(len(list((out / "scenarios").glob("*.gpkg"))), 3)
            self.assertEqual(len(list((out / "scenarios").glob("*.png"))), 3)

    def test_empty_evaluation_csv_schema_after_readback(self):
        """모든 보정 실패와 예보 0건에서도 세 CSV의 지표 열과 유효 수를 보존한다."""
        # 양성·음성 개발 사상만 있는 합성 입력을 디스크에 준비한다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            storms = pd.DataFrame({"storm_id": ["e", "n"], "role": ["development"] * 2,
                                   "year": [2006, 2006], "event_key": ["2006", ""], "label": [1, 0]})
            storms.to_csv(root / "storms.csv", index=False)
            pd.DataFrame({"trace_key": ["s|e"], "source_id": ["s"], "object_id": ["e"],
                          "role": ["development"], "storm_id": ["e"], "status": ["linked"]}).to_csv(
                              root / "links.csv", index=False)
            (root / "frozen.json").write_text("{}", encoding="utf-8")
            cells = grid()
            frame = pd.DataFrame({"grid_id": cells.grid_id, "x": range(4)})
            traces = gpd.GeoDataFrame({"source_id": ["s"], "object_id": ["e"],
                                       "role": ["development"]}, geometry=[box(0, 0, 1, 1)],
                                      crs="EPSG:5179")
            rows = [{"storm_id": sid, "role": "development", "scheme": "V1_loso",
                     "set": "common", "subset": "S1", "model": model, "p": 0.5, "p_ref": 0.25}
                    for sid in ("e", "n") for model in CR.MODELS]
            failed = {"converged": False, "failure_reason": "synthetic failure"}
            succeeded = {"converged": True, "c": 0.0, "d": 1.0}

            # 각 경로를 실제 저장과 pandas 재읽기로 확인한다.
            for case, params, predictions in (("failed", failed, pd.DataFrame(rows)),
                                               ("no_predictions", succeeded, pd.DataFrame(rows).iloc[0:0])):
                with self.subTest(case=case):
                    predictions.to_csv(root / "predictions.csv", index=False)
                    with patch.object(CR.features, "load_development", return_value=(cells, frame, None, None, None)), \
                         patch.object(CR.features, "ROOT", root), \
                         patch.object(CR.FT, "files_for", return_value=[]), \
                         patch.object(CR.FT, "load", return_value=(traces, {})), \
                         patch.object(CR.FT, "load_holdout") as holdout, \
                         patch.object(CR.LC, "v1_positive", return_value=(np.full(4, 0.5), params)), \
                         patch.object(CR.LC, "v1_negative", return_value=(np.full(4, 0.5), params)), \
                         patch.object(CR.CE, "positive_storm_metrics", return_value=pd.DataFrame(
                             [{"storm_id": "e", "n_positive_cells": 1, "cell_auc": 0.5,
                               "top20_capture": 1.0, "object_auc": 0.5, "n_objects": 1}])):
                        out = CR.run(root / "storms.csv", root / "links.csv", root / "predictions.csv",
                                     root / "frozen.json", root / case, write_scenarios=False)
                    holdout.assert_not_called()
                    metrics = pd.read_csv(out / "combined_metrics.csv")
                    per = pd.read_csv(out / "per_storm.csv")
                    positive = pd.read_csv(out / "positive_storm_metrics.csv")
                    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual(list(metrics.columns), list(CR.SUMMARY_COLUMNS))
                    self.assertEqual(list(per.columns), list(CR.PER_STORM_COLUMNS))
                    self.assertEqual(list(positive.columns), list(CR.POSITIVE_COLUMNS))
                    self.assertEqual(set(metrics.model), set(CR.MODELS))
                    self.assertTrue(metrics.n_storms.eq(0).all())
                    self.assertTrue(metrics[["brier", "brier_ref", "bss", "positive_mean_brier",
                                             "negative_mean_brier"]].isna().all().all())
                    self.assertEqual(manifest["valid_storm_counts"],
                                     {f"V1_loso/{model}": 0 for model in CR.MODELS})
                    self.assertEqual(len(per), len(storms) * len(CR.MODELS))
                    self.assertTrue(per[["n_cells", "sse", "mean_brier", "area_error"]].isna().all().all())
                    self.assertEqual(len(positive), 1)
                    if case == "failed":
                        self.assertTrue(positive[["cell_auc", "top20_capture", "object_auc"]].isna().all().all())
                        self.assertEqual(positive.loc[0, "exclusion_reason"], "calibration_failed")
                    else:
                        self.assertTrue(positive.loc[0, "included"])


if __name__ == "__main__":
    unittest.main()
