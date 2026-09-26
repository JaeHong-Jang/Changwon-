"""합성 사상과 주입 격자로 예보 발생 모형의 고정 절차를 검증한다."""

import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.special import expit

from src.forecast import event_metrics as em
from src.forecast import logit_prior as lp
from src.forecast import forecast_features, trigger_eval, warning_features
from src.forecast.forecast_features import storm_forecast_features
from src.forecast.forecast_plan import block_of, issue_before
from src.forecast.time_utils import parse_time
from src.forecast.trigger_eval import (PREDICTION_COLUMNS, evaluate, frozen_parameters, primary_endpoint_1,
                                       reliability_table, summarize)
from src.forecast.trigger_run import main, run
from src.forecast.warning_features import storm_warning_features


def synthetic_storms():
    """서로 다른 연도·역할·양음성과 유일한 특징값을 만든다."""
    # 합성 홀드아웃은 실제 침수흔적이나 예보 파일을 전혀 참조하지 않는다.
    dates = ["2011-07-01 05:00", "2011-08-01 05:00", "2012-07-01 05:00", "2013-07-01 05:00",
             "2019-12-31 23:00", "2025-07-01 05:00", "2022-07-01 05:00"]
    return pd.DataFrame(dict(storm_id=list("abcdefh"), t0=dates, t1=dates,
                             role=["development"] * 6 + ["holdout"], label=[1, 0, 1, 0, 1, 0, 1],
                             active_year=[True, True, True, False, True, False, True],
                             r12max_fc24=np.arange(1, 8) * 10.0, r12max_fc6=np.arange(1, 8) * 10.0 + 1,
                             r12max_obs=np.arange(1, 8) * 10.0 + 2, warn_advisory=[1, 0, 1, 0, 1, 0, 1],
                             warn_warning=[0, 0, 1, 0, 0, 0, 1]))


def synthetic_forecast(issue="2014-07-01 05:00", var="R06", horizon=48):
    """예상 블록마다 한 대상시각과 서로 다른 두 격자 값을 만든다."""
    # 모든 격자 값은 메모리에서 생성하며 실제 예보 저장소를 사용하지 않는다.
    issue = pd.Timestamp(issue)
    rows, grids, seen = [], {}, set()
    for hour in range(horizon + 1):
        target = issue + pd.Timedelta(hours=hour)
        start, end = map(pd.Timestamp, block_of(var, target))
        if start < issue or end > issue + pd.Timedelta(hours=horizon) or (start, end) in seen:
            continue
        seen.add((start, end))
        path = f"{var}/{issue:%Y%m%d%H}/{target:%Y%m%d%H}.txt.gz"
        rows.append(dict(path=path, tmfc=issue, tmef=target, var=var, status="ok", n_valid=2))
        grid = np.full((253, 149), np.nan)
        grid[0, :2] = [len(rows), 2 * len(rows)]
        grids[path] = grid
    storms = pd.DataFrame([dict(storm_id="s", t0=issue + pd.Timedelta(hours=24), t1="2099-01-01")])
    cells = pd.DataFrame(dict(nx=[1, 2], ny=[1, 1], n_grid_cells=[10, 1]))
    return storms, pd.DataFrame(rows), cells, grids


class LogitTests(unittest.TestCase):
    """약한 정보 사전분포와 학습 척도 및 실패 전파를 확인한다."""

    def test_separation_scale_and_prediction(self):
        """완전 분리에서도 유한한 계수와 ddof=0 척도를 얻는다."""
        # 알려진 변환값으로 척도와 예측 식을 독립 계산한다.
        raw, y = np.array([0, 1, 2, 10, 30, 100]), np.array([0, 0, 0, 1, 1, 1])
        params = lp.fit(raw, y)
        self.assertTrue(params["converged"])
        self.assertTrue(np.isfinite([params["a"], params["b"]]).all())
        self.assertAlmostEqual(params["center"], np.log1p(raw).mean())
        self.assertAlmostEqual(params["scale"], 2 * np.log1p(raw).std(ddof=0))
        expected = expit(params["a"] + params["b"] * (np.log1p(raw) - params["center"]) / params["scale"])
        np.testing.assert_allclose(lp.predict_raw(params, raw), expected)
        self.assertGreater(expected[-1], expected[0])

    def test_zero_scale_intercept_and_zero_positive(self):
        """상수 특징 실패와 특징 무시 절편 모형을 구분한다."""
        # 절편 전용 모형은 결측·음수 특징에도 같은 확률을 반환한다.
        params = lp.fit([5, 5, 5], [0, 1, 0])
        self.assertEqual(params["reason"], "zero_scale")
        self.assertTrue(np.isnan(lp.predict_raw(params, [1, 2])).all())
        intercept = lp.fit_intercept_only([0, 1, 0, 1])
        self.assertEqual(intercept["b"], 0)
        np.testing.assert_allclose(lp.predict_raw(intercept, [np.nan, -5, 99]), [0.5] * 3)
        with self.assertRaisesRegex(ValueError, "no positive"):
            lp.fit([1, 2], [0, 0])
        with self.assertRaisesRegex(ValueError, "no positive"):
            lp.fit_intercept_only([0, 0])

    def test_failed_optimizer_and_gradient(self):
        """해석적 기울기를 수치 미분과 비교하고 최적화 실패를 전파한다."""
        # 실제 목적함수를 주입 최적화기에서 중앙차분으로 검증한다.
        def failed(fun, initial, **kwargs):
            """기울기를 검산한 뒤 의도적 실패 결과를 반환한다."""
            # 절편과 기울기를 모두 영점 밖에서 검사한다.
            point = np.array([0.3, -0.7])
            value, gradient = fun(point)
            numerical = [(fun(point + np.eye(2)[j] * 1e-6)[0] - fun(point - np.eye(2)[j] * 1e-6)[0]) / 2e-6 for j in range(2)]
            np.testing.assert_allclose(gradient, numerical, rtol=1e-6)
            return type("Result", (), dict(x=point, success=False, message="synthetic failure"))()

        # 실패 상태를 예측 함수가 무시하지 않는지 확인한다.
        with patch.object(lp, "minimize", side_effect=failed):
            params = lp.fit([1, 3, 8], [0, 1, 1])
        self.assertFalse(params["converged"])
        self.assertTrue(np.isnan(lp.predict_raw(params, [4])).all())


class MetricTests(unittest.TestCase):
    """손계산 지표와 사상 짝 재표집을 검증한다."""

    def test_scores_and_categories(self):
        """Brier·pooled BSS·동점 AUC·경보 분할표를 손계산과 비교한다."""
        # 서로 다른 사상 기준 확률의 제곱오차 합을 직접 계산한다.
        p, y, ref = [0.2, 0.7, 0.7, 0.1], [0, 1, 0, 1], [0.1, 0.3, 0.6, 0.8]
        self.assertAlmostEqual(em.brier(p, y), (0.04 + 0.09 + 0.49 + 0.81) / 4)
        self.assertAlmostEqual(em.bss_pooled(p, y, ref), 1 - 1.43 / 0.90)
        self.assertTrue(np.isnan(em.bss_pooled(y, y, y)))
        self.assertAlmostEqual(em.auc(p, y), 0.375)
        self.assertTrue(np.isnan(em.auc([0.1], [1])))
        result = em.categorical([1, 0, 1, 0], [1, 1, 0, 0])
        self.assertEqual([result[key] for key in ("hits", "misses", "false_alarms", "correct_negatives")], [1] * 4)
        self.assertEqual(result["pod"], 0.5)
        self.assertEqual(result["far"], 0.5)
        self.assertAlmostEqual(result["csi"], 1 / 3)
        self.assertTrue(np.isnan(em.categorical([0], [0])["pod"]))
        lo, hi = em.clopper_pearson(1, 2)
        self.assertAlmostEqual(lo, 1 - np.sqrt(0.975))
        self.assertAlmostEqual(hi, np.sqrt(0.975))
        self.assertEqual(em.clopper_pearson(0, 2)[0], 0)
        self.assertEqual(em.clopper_pearson(2, 2)[1], 1)

    def test_reliability_boundaries(self):
        """내부 경계는 다음 구간이고 마지막 1은 포함된다."""
        # 모든 고정 경계에 확률을 정확하게 배치한다.
        table = em.reliability([0, 0.1, 0.3, 0.6, 1], [0, 1, 0, 1, 1])
        self.assertEqual(table.n.tolist(), [1, 1, 1, 2])
        self.assertAlmostEqual(table.iloc[1].mean_p, 0.1)
        self.assertAlmostEqual(table.iloc[-1].mean_p, 0.8)

    def test_paired_bootstrap_and_undefined(self):
        """재표집 인덱스 짝과 재현성 및 정의 불가 횟수를 확인한다."""
        # 상수 배수 배열 관계는 어떤 사상 재표집에서도 유지되어야 한다.
        def paired(a, b, y):
            """배열 관계가 보존됐는지 확인한 뒤 평균을 반환한다."""
            # 양성 부재는 정의 불가로 처리해 제외 횟수를 검사한다.
            np.testing.assert_array_equal(b, 2 * a)
            np.testing.assert_array_equal(y, a % 2)
            return float(a.mean()) if y.sum() else np.nan

        # 같은 seed 결과와 정의 불가 반복을 독립 난수열로 대조한다.
        arrays = [np.arange(4), np.arange(4) * 2, np.arange(4) % 2]
        result = em.paired_bootstrap(paired, arrays, n=100)
        self.assertEqual(result, em.paired_bootstrap(paired, arrays, n=100))
        rng = np.random.default_rng(20260926)
        undefined = sum(not arrays[2][rng.integers(0, 4, 4)].sum() for _ in range(100))
        self.assertEqual(result["n_undefined"], undefined)
        self.assertEqual(result["n_valid"] + result["n_undefined"], 100)


class FeatureTests(unittest.TestCase):
    """합성 격자로 블록·자료 상태·발표본 규칙을 검증한다."""

    def calculate(self, fixture, **kwargs):
        """메모리 격자 로더를 주입해 한 사상의 특징을 계산한다."""
        # 디스크나 네트워크 자료는 로더에서 접근하지 않는다.
        storms, manifest, cells, grids = fixture
        return storm_forecast_features(storms, manifest, cells, leads=(24,),
                                       grid_loader=grids.__getitem__, block_of=block_of, **kwargs).iloc[0]

    def test_r06_containment_contiguity_and_t1(self):
        """완전 블록만 쓰고 격자별 연속 두 블록을 합하며 t1은 무시한다."""
        # 양끝 불완전 블록에 거대한 값을 넣어 선택 여부를 판별한다.
        storms, manifest, cells, grids = synthetic_forecast()
        self.assertEqual(self.calculate((storms, manifest, cells, grids)).r12max_fc, 26)
        extra = []
        for i, target in enumerate(["2014-07-01 06:00", "2014-07-03 03:00"]):
            path = f"outside{i}"
            grids[path] = np.full((253, 149), 99999.0)
            extra.append(dict(path=path, tmfc="2014-07-01 05:00", tmef=target, var="R06", status="ok", n_valid=2))
        manifest = pd.concat([manifest, pd.DataFrame(extra)], ignore_index=True)
        storms["t1"] = "1900-01-01"
        result = self.calculate((storms, manifest, cells, grids))
        self.assertEqual(result.r12max_fc, 26)
        self.assertEqual(result.n_blocks, 7)
        self.assertEqual(result.status, "ok")

    def test_r12_and_pcp(self):
        """R12는 한 블록이고 PCP는 정확히 연속 열두 시간을 합한다."""
        # 각 격자에서 마지막 유효 창의 손계산 합을 대조한다.
        self.assertEqual(self.calculate(synthetic_forecast("2012-07-01 05:00", "R12")).r12max_fc, 6)
        fixture = synthetic_forecast("2025-07-01 05:00", "PCP")
        self.assertEqual(self.calculate(fixture).r12max_fc, 2 * sum(range(37, 49)))
        storms, manifest, cells, grids = fixture
        manifest.loc[manifest.index[-1], "status"] = "all_missing"
        result = self.calculate(fixture)
        self.assertEqual(result.r12max_fc, 2 * sum(range(36, 48)))
        self.assertEqual(result.status, "partial_all_missing")

    def test_missing_blocks_and_no_substitution(self):
        """공식 미제공·파일 누락·수집 실패·발표본 누락을 구분한다."""
        # 같은 자료의 상태만 바꿔 다른 결측 사유가 보존되는지 검사한다.
        storms, manifest, cells, grids = synthetic_forecast()
        manifest["status"] = "all_missing"
        self.assertEqual(self.calculate((storms, manifest, cells, grids)).status, "all_missing")
        manifest.loc[0, "status"] = "error"
        self.assertEqual(self.calculate((storms, manifest, cells, grids)).status, "collection_error")
        manifest.loc[0, "status"] = "ok"

        def missing(path):
            """저장 파일 누락을 재현한다."""
            # 자료가 없는 경로를 실제로 열지 않는다.
            raise FileNotFoundError(path)

        # 로더 누락과 더 이른 발표본만 존재하는 경우를 구분한다.
        result = storm_forecast_features(storms, manifest, cells, leads=(24,), grid_loader=missing, block_of=block_of)
        self.assertEqual(result.iloc[0].status, "collection_error")
        manifest["tmfc"] -= pd.Timedelta(hours=3)
        result = self.calculate((storms, manifest, cells, grids))
        self.assertEqual(result.status, "missing_issue")
        self.assertTrue(np.isnan(result.r12max_fc))

    def test_gridwise_sum_and_gap(self):
        """격자 최댓값을 먼저 합하지 않고 끊어진 블록은 잇지 않는다."""
        # 서로 다른 격자의 피크를 합하면 틀리는 두 블록을 만든다.
        storms, manifest, cells, grids = synthetic_forecast(horizon=18)
        for i, path in enumerate(manifest.path):
            grids[path][0, :2] = [10, 0] if i == 0 else [0, 10]
        self.assertEqual(self.calculate((storms, manifest, cells, grids), horizon_h=18).r12max_fc, 10)
        manifest.loc[1, "status"] = "all_missing"
        self.assertTrue(np.isnan(self.calculate((storms, manifest, cells, grids), horizon_h=18).r12max_fc))

    def test_transition_priority_and_fallback(self):
        """전환일에는 날짜상 우선 변수를 쓰고 미제공일 때 인접 변수를 쓴다."""
        # 같은 발표본에 옛 변수와 새 변수 응답을 함께 제공한다.
        storms, new, cells, grids = synthetic_forecast("2021-06-29 05:00", "PCP")
        _, old, _, old_grids = synthetic_forecast("2021-06-29 05:00", "R06")
        grids.update(old_grids)
        result = self.calculate((storms, pd.concat([new, old]), cells, grids))
        self.assertEqual(result["var"], "PCP")
        new["status"] = "all_missing"
        result = self.calculate((storms, pd.concat([new, old]), cells, grids))
        self.assertEqual(result["var"], "R06")
        self.assertEqual(result.r12max_fc, 26)

    def test_pcp_missing_cell_and_duplicate_block(self):
        """시간 결측이 있는 격자 창과 같은 블록의 중복 대상을 처리한다."""
        # 한 격자의 한 시간 결측을 다른 격자 값으로 메우지 않는다.
        fixture = synthetic_forecast("2025-07-01 05:00", "PCP", horizon=12)
        storms, manifest, cells, grids = fixture
        grids[manifest.path.iloc[4]][0, 1] = np.nan
        self.assertEqual(self.calculate(fixture, horizon_h=12).r12max_fc, sum(range(1, 13)))
        manifest.loc[4, "status"] = "all_missing"
        self.assertTrue(np.isnan(self.calculate(fixture, horizon_h=12).r12max_fc))

        # 같은 R06 블록을 두 번 요청해도 누적량과 블록 수는 늘지 않는다.
        storms, manifest, cells, grids = synthetic_forecast()
        duplicate = manifest.iloc[[0]].copy()
        duplicate["tmef"] += pd.Timedelta(hours=1)
        result = self.calculate((storms, pd.concat([manifest, duplicate]), cells, grids))
        self.assertEqual(result.n_blocks, 7)
        self.assertEqual(result.r12max_fc, 26)

    def test_pop_and_coverage(self):
        """POP는 같은 발표 후 범위의 창원값만 쓰고 제공 시작 전은 건너뛴다."""
        # 전국 다른 격자의 큰 POP와 범위 밖 POP를 무시하는지 검사한다.
        storms, manifest, cells, grids = synthetic_forecast()
        extra = []
        for path, time, value in [("pop_in", "2014-07-01 08:00", 60), ("pop_out", "2014-07-03 06:00", 99)]:
            grid = np.full((253, 149), 100.0)
            grid[0, :2] = value
            grids[path] = grid
            extra.append(dict(path=path, tmfc="2014-07-01 05:00", tmef=time, var="POP", status="ok", n_valid=2))
        result = self.calculate((storms, pd.concat([manifest, pd.DataFrame(extra)]), cells, grids))
        self.assertEqual(result.pop_max, 60)
        storms["t0"] = "2009-07-01"
        self.assertEqual(self.calculate((storms, manifest, cells, grids)).status, "outside_coverage")

    def test_missing_manifest_block(self):
        """수집표에서 빠진 블록도 수집 실패로 기록한다."""
        # 다른 블록이 있더라도 불완전 최대 강수를 완전값으로 내보내지 않는다.
        storms, manifest, cells, grids = synthetic_forecast()
        result = self.calculate((storms, manifest.iloc[1:], cells, grids))
        self.assertEqual(result.status, "collection_error")
        self.assertEqual(result.n_error_blocks, 1)
        self.assertTrue(np.isnan(result.r12max_fc))

    def test_collection_errors_keep_na_and_count_blocks(self):
        """유효 연속창이 남아도 실패 블록은 NA와 중복 없는 개수로 기록한다."""
        # 같은 두 블록을 오류·파일 누락·요청 누락으로 각각 재현한다.
        for failure in ("error", "missing_file", "missing_request", "all_missing"):
            with self.subTest(failure=failure):
                storms, manifest, cells, grids = synthetic_forecast("2025-07-01 05:00", "PCP")
                missing_paths = set(manifest.path.iloc[:2])
                if failure == "missing_request":
                    manifest = manifest.iloc[2:]
                elif failure != "missing_file":
                    manifest.loc[:1, "status"] = failure
                    manifest = pd.concat([manifest, manifest.iloc[[0]]], ignore_index=True)

                def loader(path):
                    """선택한 합성 파일에만 저장 파일 누락을 재현한다."""
                    # 나머지 블록은 실제 파일 없이 메모리에서 읽는다.
                    if failure == "missing_file" and path in missing_paths:
                        raise FileNotFoundError(path)
                    return grids[path]

                # 공식 미제공은 남은 창으로 계산하지만 수집 실패는 최대값을 내보내지 않는다.
                result = storm_forecast_features(storms, manifest, cells, leads=(24,),
                                                 grid_loader=loader, block_of=block_of).iloc[0]
                self.assertEqual(result.n_blocks, 46)
                if failure == "all_missing":
                    self.assertEqual(result.n_error_blocks, 0)
                    self.assertEqual(result.status, "partial_all_missing")
                    self.assertEqual(result.r12max_fc, 1020)
                else:
                    self.assertEqual(result.n_error_blocks, 2)
                    self.assertEqual(result.status, "collection_error")
                    self.assertTrue(np.isnan(result.r12max_fc))

    def test_transition_uses_changwon_valid_values(self):
        """R12의 전국 유효값과 무관하게 창원 유효 R06의 20 mm를 쓴다."""
        # 날짜상 우선인 R12에는 창원 밖 유효값만 남긴다.
        storms, old, cells, grids = synthetic_forecast("2013-05-29 05:00", "R12")
        _, new, _, new_grids = synthetic_forecast("2013-05-29 05:00", "R06")
        for grid in grids.values():
            grid[0, :2] = np.nan
            grid[10, 10] = 999
        for grid in new_grids.values():
            grid[0, :2] = 10
        grids.update(new_grids)
        fixture = storms, pd.concat([old, new]), cells, grids
        result = self.calculate(fixture)
        self.assertEqual(result["var"], "R06")
        self.assertEqual(result.r12max_fc, 20)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.n_error_blocks, 0)

        # 두 변수 모두 창원 유효값이 있으면 날짜 규칙의 R12로 돌아간다.
        for path in old.path:
            grids[path][0, :2] = 7
        result = self.calculate(fixture)
        self.assertEqual(result["var"], "R12")
        self.assertEqual(result.r12max_fc, 7)


class TimeTests(unittest.TestCase):
    """공통 시각 함수의 기존 import 경로와 변환 결과를 검증한다."""

    def test_parse_time_reexports_and_formats(self):
        """기존 경로가 같은 함수를 재수출하고 KST·숫자·결측 처리를 유지한다."""
        # 복제 구현 없이 모든 기존 모듈이 공통 함수를 내보내야 한다.
        for module in (forecast_features, warning_features, trigger_eval):
            self.assertIs(module.parse_time, parse_time)
        expected = pd.Timestamp("2014-07-02 05:00")
        for value in (2014070205, 201407020500, 20140702050000, 201407020500.0,
                      "2014-07-02 05:00:00", "2014-07-01 20:00:00+00:00", expected):
            self.assertEqual(parse_time(value), expected)
        for value in (None, "", "  ", np.nan, pd.NaT):
            self.assertTrue(pd.isna(parse_time(value)))


class WarningTests(unittest.TestCase):
    """특보 발표창·명령·수준·구역과 자료 시작일을 검증한다."""

    def test_warning_rules(self):
        """양끝 발표는 포함하고 해제·다른 구역·미래 발표는 제외한다."""
        # 숫자 시각과 구분자 시각을 같은 입력에 섞는다.
        storms = pd.DataFrame(dict(storm_id=["s", "early"], t0=["2014-07-02 05:00", "2005-06-30"]))
        rows = []
        for time, cmd, level, region, kind in [("201407010500", 1, 2, "L1080600", "R"),
                                               ("2014-07-02 05:00:00", 6, 3, "L1080600", "T"),
                                               ("201407010400", 1, 3, "L1080600", "R"),
                                               ("201407020600", 1, 3, "L1080600", "R"),
                                               ("201407020400", 3, 3, "L1080600", "R"),
                                               ("201407020400", 1, 3, "elsewhere", "R"),
                                               ("201407020400", 1, 3, "L1080600", "S")]:
            rows.append(dict(TM_FC=time, TM_EF=time, TM_IN=time, CMD=cmd, LVL=level, REG_ID=region, WRN=kind))
        coverage = pd.DataFrame(dict(month=["2014-07"], status=["ok"]))
        result = storm_warning_features(storms, pd.DataFrame(rows), coverage)
        self.assertEqual(result.iloc[0].warn_advisory, 1)
        self.assertEqual(result.iloc[0].warn_warning, 1)
        self.assertEqual(result.iloc[0].first_warn_lead_h, 24)
        self.assertTrue(result.iloc[1][["warn_advisory", "warn_warning", "first_warn_lead_h"]].isna().all())
        self.assertEqual(result.warn_status.tolist(), ["ok", "outside_period"])
        result = storm_warning_features(storms, pd.DataFrame(rows[2:]), coverage)
        self.assertEqual(result.iloc[0].warn_advisory, 0)
        self.assertEqual(result.iloc[0].warn_status, "ok")
        self.assertTrue(np.isnan(result.iloc[0].first_warn_lead_h))

    def test_each_allowed_command_and_level(self):
        """발표·대치·연장·변경 각각과 수준별 이진 특보를 확인한다."""
        # 1단계는 주의보가 아니고 2단계는 경보가 아니다.
        storms = pd.DataFrame([dict(storm_id="s", t0="2014-07-02 05:00")])
        coverage = pd.DataFrame(dict(month=["2014-07"], status=["ok"]))
        for cmd in (1, 2, 5, 6):
            for level in (1, 2, 3):
                warning = pd.DataFrame([dict(TM_FC="201407020500", CMD=cmd, LVL=level, REG_ID="L1080600", WRN="R")])
                result = storm_warning_features(storms, warning, coverage).iloc[0]
                self.assertEqual(result.warn_advisory, int(level >= 2))
                self.assertEqual(result.warn_warning, int(level == 3))

    def test_coverage_required(self):
        """수집 근거를 생략하거나 None을 넘기면 특징 계산을 거절한다."""
        # 사상과 특보가 비어 있어도 coverage 전달 계약은 동일하다.
        for kwargs in ({}, {"coverage": None}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "coverage"):
                storm_warning_features(pd.DataFrame(), pd.DataFrame(), **kwargs)

    def test_missing_month_is_na_even_with_warning_rows(self):
        """월 오류·누락·표에서 빠진 월은 특보 유무와 관계없이 모두 NA다."""
        # 비정상 월에 일부 특보가 남아 있어도 완전한 수집으로 해석하지 않는다.
        storms = pd.DataFrame(dict(storm_id=["s"], t0=["2014-07-02 05:00"]))
        warnings = pd.DataFrame([dict(TM_FC="201407020500", CMD=1, LVL=3, REG_ID="L1080600", WRN="R")])
        for status in ("error", "missing", "absent", pd.NA):
            coverage = pd.DataFrame(dict(month=["2014-07"], status=[status]), dtype="string")
            if status is not pd.NA and status == "absent":
                coverage = coverage.iloc[:0]
            for rows in (warnings, warnings.iloc[:0]):
                with self.subTest(status=status, warning_rows=len(rows)):
                    result = storm_warning_features(storms, rows, coverage).iloc[0]
                    self.assertEqual(result.warn_status, "coverage_missing")
                    self.assertTrue(result[["warn_advisory", "warn_warning", "first_warn_lead_h"]].isna().all())

    def test_month_boundary_requires_both_months(self):
        """닫힌 발표창의 양끝 월을 검사하고 창 밖 월의 누락은 무시한다."""
        # 정확한 월초와 연초도 이전 월을 포함하며 다음 날 00시부터는 현재 월만 쓴다.
        for t0 in ("2014-07-01 00:00", "2014-07-01 05:00", "2015-01-01 00:00"):
            start = pd.Timestamp(t0) - pd.Timedelta(hours=24)
            months = pd.period_range(start, t0, freq="M").astype(str).tolist()
            storms = pd.DataFrame(dict(storm_id=["s"], t0=[t0]))
            warnings = pd.DataFrame([dict(TM_FC=start, CMD=1, LVL=3, REG_ID="L1080600", WRN="R")])
            for status in (["ok", "ok"], ["missing", "ok"], ["ok", "error"]):
                with self.subTest(t0=t0, status=status):
                    coverage = pd.DataFrame(dict(month=months, status=status))
                    result = storm_warning_features(storms, warnings, coverage).iloc[0]
                    if status == ["ok", "ok"]:
                        self.assertEqual(result.warn_status, "ok")
                        self.assertEqual(result.warn_advisory, 1)
                        self.assertEqual(result.warn_warning, 1)
                        self.assertEqual(result.first_warn_lead_h, 24)
                    else:
                        self.assertEqual(result.warn_status, "coverage_missing")
                        self.assertTrue(result[["warn_advisory", "warn_warning", "first_warn_lead_h"]].isna().all())

        # 하루 경계 밖의 누락은 정상 월의 무특보를 NA로 바꾸지 않는다.
        storms = pd.DataFrame(dict(storm_id=["s"], t0=["2014-07-02 00:00"]))
        coverage = pd.DataFrame(dict(month=["2014-06", "2014-07"], status=["missing", "ok"]))
        result = storm_warning_features(storms, warnings.iloc[:0], coverage).iloc[0]
        self.assertEqual(result.warn_status, "ok")
        self.assertEqual(result.warn_advisory, 0)
        self.assertEqual(result.warn_warning, 0)
        self.assertTrue(pd.isna(result.first_warn_lead_h))


class EvaluationTests(unittest.TestCase):
    """학습 분할·공통 집합·기후 기준·보고 지표를 검증한다."""

    def test_loso_injection_and_fold_climate(self):
        """각 평가 특징은 적합 입력에 없으며 기후값은 fold마다 달라진다."""
        # 예측 시점에 직전 적합 자료와 겹침을 검사하는 대역을 주입한다.
        def fit(raw, y):
            """학습값을 계보로 보관한다."""
            # 대역은 모든 계수를 고정하고 입력 목록만 남긴다.
            return dict(converged=True, raw=set(raw))

        def predict(params, raw):
            """각 예측값이 학습 자료에 없음을 검증한다."""
            # 절편 모형은 특징이 없으므로 별도로 전달한 빈 집합을 쓴다.
            self.assertFalse(params["raw"].intersection(raw))
            return np.full(len(raw), 0.4)

        # 전체·부분집합과 과거연도 검증에서도 동일 누수 검사를 적용한다.
        data = synthetic_storms()
        predictions = evaluate(data, fit_fn=fit, intercept_fit_fn=lambda y: dict(converged=True, raw=set()), predict_fn=predict)
        self.assertEqual(predictions.columns.tolist(), PREDICTION_COLUMNS)
        climate = predictions.query("model == 'B_clim' and scheme == 'V1_loso' and `set` == 'common' and subset == 'S1'")
        actual = climate.set_index("storm_id").p
        self.assertAlmostEqual(actual["a"], 2 / 5)
        self.assertAlmostEqual(actual["b"], 3 / 5)
        self.assertNotIn("h", set(predictions.storm_id))
        self.assertFalse(predictions.scheme.str.startswith("V3").any())

    def test_v2_v3_and_frozen_scale(self):
        """양성 둘 이후 연도만 평가하고 2020 이후 개발은 V3에서 제외한다."""
        # 미래 개발 극단값으로 동결 학습 척도가 달라지는 오류를 탐지한다.
        data = synthetic_storms()
        data.loc[data.storm_id.eq("f"), "r12max_fc24"] = 90000
        predictions = evaluate(data, include_holdout=True)
        yearly = predictions.query("model == 'M_fc24' and scheme == 'V2_retro_year' and `set` == 'common' and subset == 'S1'")
        self.assertEqual(set(yearly.storm_id), {"d", "e", "f"})
        params = frozen_parameters(data)
        self.assertEqual(params["V3"]["M_fc24"]["n"], 5)
        self.assertEqual(params["all_dev"]["M_fc24"]["n"], 6)
        self.assertAlmostEqual(params["V3"]["M_fc24"]["center"], np.log1p([10, 20, 30, 40, 50]).mean())
        frozen = predictions.query("model == 'M_fc24' and scheme == 'V3_frozen' and `set` == 'common' and subset == 'S1'")
        self.assertEqual(frozen.storm_id.tolist(), ["h"])
        self.assertAlmostEqual(frozen.p.iloc[0], lp.predict_raw(params["V3"]["M_fc24"], [70])[0])
        retro = predictions.query("model == 'M_fc24' and scheme == 'V3b_frozen_all' and `set` == 'common' and subset == 'S1'")
        self.assertAlmostEqual(retro.p.iloc[0], lp.predict_raw(params["all_dev"]["M_fc24"], [70])[0])

    def test_common_full_and_s2_training(self):
        """결측과 활동연도 제한을 평가·학습 양쪽에 적용한다."""
        # 한 음성 사상의 보조 예보를 지워 common 학습 발생률을 확인한다.
        data = synthetic_storms()
        data.loc[data.storm_id.eq("b"), "r12max_fc6"] = np.nan
        predictions = evaluate(data)
        common = predictions.query("scheme == 'V1_loso' and `set` == 'common' and subset == 'S1'")
        self.assertNotIn("b", set(common.storm_id))
        self.assertAlmostEqual(common.query("model == 'B_clim' and storm_id == 'a'").p.iloc[0], 2 / 4)
        full = predictions.query("model == 'M_obs' and scheme == 'V1_loso' and `set` == 'full' and subset == 'S1'")
        self.assertIn("b", set(full.storm_id))
        sensitivity = predictions.query("model == 'B_clim' and scheme == 'V1_loso' and `set` == 'full' and subset == 'S2'")
        self.assertEqual(set(sensitivity.storm_id), {"a", "b", "c", "e"})
        self.assertAlmostEqual(sensitivity.query("storm_id == 'a'").p.iloc[0], 2 / 3)

    def test_holdout_removed_before_parsing_and_fitting(self):
        """홀드아웃의 잘못된 시각도 기본 실행에서는 처리되지 않는다."""
        # 홀드아웃 행에 독성 입력을 넣어 조기 제거를 검증한다.
        data = synthetic_storms()
        data.loc[data.role.eq("holdout"), "t0"] = "MUST_NOT_PARSE"
        data.loc[data.role.eq("holdout"), "r12max_fc24"] = 1e99
        self.assertNotIn("h", set(evaluate(data).storm_id))
        self.assertLess(frozen_parameters(data)["all_dev"]["M_fc24"]["center"], 10)

    def test_summary_pooled_intervals_and_primary(self):
        """사상별 기준 짝과 두 경보 임계 및 주 판정 문구를 확인한다."""
        # 별도 B_clim 행과 다른 모형별 기준을 넣어 행별 기준 사용을 확인한다.
        rows = []
        for model, ids, p, warns in [("M_fc24", ["a", "b", "c"], [0.2, 0.8, 0.4], [1, 1, 0]),
                                     ("B_clim", ["c", "a", "b"], [0.6, 0.4, 0.3], [1, 1, 1])]:
            for sid, prob, warn in zip(ids, p, warns):
                rows.append(dict(storm_id=sid, role="development", label=int(sid == "b"), model=model,
                                 scheme="V1_loso", set="common", subset="S1", p=prob, warn=warn,
                                 p_ref={"a": 0.2, "b": 0.5, "c": 0.7}[sid] if model == "M_fc24" else prob))
        predictions = pd.DataFrame(rows)
        metrics = summarize(predictions, n_bootstrap=40)
        target = metrics[metrics.model.eq("M_fc24")]
        self.assertEqual(set(target.threshold), {"0.5", "train_rate"})
        expected = 1 - (0.04 + 0.04 + 0.16) / (0.04 + 0.25 + 0.49)
        self.assertAlmostEqual(target.bss.iloc[0], expected)

        # 독립 난수열로 같은 사상의 모형·기준 오차를 함께 재표집해 구간을 검산한다.
        rng = np.random.default_rng(20260926)
        model_errors, ref_errors = np.array([0.04, 0.04, 0.16]), np.array([0.04, 0.25, 0.49])
        samples = []
        for _ in range(40):
            indices = rng.integers(0, 3, 3)
            samples.append(1 - model_errors[indices].sum() / ref_errors[indices].sum())
        np.testing.assert_allclose(target.iloc[0][["bss_lo", "bss_hi"]].to_numpy(dtype=float), np.percentile(samples, [2.5, 97.5]))
        self.assertEqual(target.bss_n_valid.iloc[0], 40)
        self.assertEqual(target.bss_n_undefined.iloc[0], 0)
        without_climate = summarize(predictions[predictions.model.eq("M_fc24")], n_bootstrap=40)
        pd.testing.assert_frame_equal(target.reset_index(drop=True), without_climate)

        # 확률 경보 임계와 주 판정의 기존 보고 계약도 유지한다.
        self.assertEqual(target.query("threshold == 'train_rate'").false_alarms.iloc[0], 1)
        self.assertIn("auc_n_undefined", metrics.columns)
        self.assertIn("pod_cp_lo", metrics.columns)
        self.assertEqual(len(reliability_table(predictions)), 8)
        endpoint = primary_endpoint_1(metrics)
        self.assertEqual(endpoint["criterion"], "하한 > 0")
        metrics.loc[metrics.model.eq("M_fc24"), "bss_lo"] = -0.01
        self.assertIn("정보 없음의 증명이 아님", primary_endpoint_1(metrics)["statement"])

    def test_model_specific_reference_review_case(self):
        """RVFC3의 M_fc24 유효 학습 발생률 1/2를 행별 기준으로 보존한다."""
        # 마지막 음성의 주 예보만 지워 전체 사상 발생률 1/3과 구분한다.
        data = synthetic_storms().iloc[:4].copy()
        data["label"] = [1, 1, 0, 0]
        data.loc[data.storm_id.eq("d"), "r12max_fc24"] = np.nan
        predictions = evaluate(data)
        target = predictions.query("model == 'M_fc24' and scheme == 'V1_loso' and `set` == 'full' and subset == 'S1' and storm_id == 'a'").iloc[0]
        self.assertEqual(target.p_ref, 1 / 2)
        self.assertEqual(target.warn, float(target.p >= 1 / 2))
        climate = predictions.query("model == 'B_clim' and scheme == 'V1_loso' and `set` == 'common' and subset == 'S1' and storm_id == 'a'").iloc[0]
        self.assertEqual(climate.p, 1 / 2)
        self.assertEqual(climate.p_ref, climate.p)
        self.assertEqual(predictions.columns.tolist(), ["storm_id", "role", "label", "model", "scheme", "set", "subset", "p", "warn", "p_ref"])

    def test_reference_matches_each_scheme_set_subset_training(self):
        """모든 검증·집합·부분집합의 모형별 기준을 독립 학습집합으로 검산한다."""
        # 모형마다 유효 사상이 달라지고 S2에서만 빠지는 음성도 있게 만든다.
        data = synthetic_storms()
        data.loc[data.storm_id.eq("b"), "r12max_fc24"] = np.nan
        data.loc[data.storm_id.eq("d"), "r12max_fc6"] = np.nan
        data.loc[data.storm_id.eq("f"), "r12max_obs"] = np.nan
        data.loc[data.storm_id.eq("b"), "warn_advisory"] = np.nan
        data.loc[data.storm_id.eq("d"), "warn_warning"] = np.nan
        predictions = evaluate(data, include_holdout=True)
        dates = pd.to_datetime(data.t0)
        features = {"M_fc24": "r12max_fc24", "M_fc6": "r12max_fc6", "M_obs": "r12max_obs",
                    "B_rule110": "r12max_fc24", "B_rule180": "r12max_fc24",
                    "B_warn": "warn_advisory", "B_warn3": "warn_warning"}
        self.assertEqual(set(predictions.scheme), {"V1_loso", "V2_retro_year", "V3_frozen", "V3b_frozen_all"})
        self.assertEqual(set(predictions["set"]), {"common", "full"})
        self.assertEqual(set(predictions.subset), {"S1", "S2"})
        for row in predictions.itertuples():
            with self.subTest(model=row.model, scheme=row.scheme, set=row.set, subset=row.subset, storm=row.storm_id):
                keep = data.role.eq("development")
                if row.subset == "S2":
                    keep &= data.label.eq(1) | data.active_year
                required = ["r12max_fc24", "r12max_fc6", "r12max_obs"] if row.set == "common" else []
                if row.model in features:
                    required = [*required, features[row.model]]
                for feature in required:
                    keep &= np.isfinite(data[feature]) & data[feature].ge(0)
                if row.scheme == "V1_loso":
                    keep &= data.storm_id.ne(row.storm_id)
                elif row.scheme == "V2_retro_year":
                    year = dates[data.storm_id.eq(row.storm_id)].iloc[0].year
                    keep &= dates.lt(pd.Timestamp(year=year, month=1, day=1))
                    self.assertGreaterEqual(data.loc[keep, "label"].sum(), 2)
                elif row.scheme == "V3_frozen":
                    keep &= dates.lt(pd.Timestamp("2020-01-01"))
                self.assertAlmostEqual(row.p_ref, data.loc[keep, "label"].mean())
                if row.model == "B_clim":
                    self.assertEqual(row.p, row.p_ref)

    def test_fit_failure_reporting(self):
        """상수 특징 실패가 기준 예측으로 대체되지 않고 기록된다."""
        # 모든 개발 강수 특징을 상수로 만들어 모든 해당 fold를 실패시킨다.
        data = synthetic_storms()
        data["r12max_fc24"] = 1.0
        predictions = evaluate(data)
        self.assertTrue(predictions[predictions.model.eq("M_fc24")].p.isna().all())
        self.assertTrue(any(f["reason"] == "zero_scale" for f in predictions.attrs["fit_failures"]))

    def test_empty_evaluation_and_nan_intervals(self):
        """평가 사상이나 유효 재표집이 없을 때도 정의 불가를 보존한다."""
        # 빈 결과에 스키마가 남아 CSV 후속 읽기를 가능하게 한다.
        predictions = evaluate(synthetic_storms().iloc[0:0])
        metrics = summarize(predictions, n_bootstrap=5)
        self.assertIn("bss", metrics.columns)
        self.assertFalse(primary_endpoint_1(metrics)["passed"])
        result = em.paired_bootstrap(em.auc, [[0.2, 0.3], [0, 0]], n=10)
        self.assertEqual(result["n_undefined"], 10)
        self.assertTrue(np.isnan(result["lo"]))
        result = em.paired_bootstrap(em.brier, [[], []], n=3)
        self.assertEqual(result["n_undefined"], 3)


class RunTests(unittest.TestCase):
    """임시 합성 저장소로 기본 실행의 전체 산출물과 격리를 검증한다."""

    def test_missing_coverage_stops_before_inputs_and_fitting(self):
        """coverage 파일 부재는 입력 읽기·적합·저장 전에 API와 CLI를 중단한다."""
        # 경로만 합성하고 계산 진입 여부와 CLI의 오류 이유를 함께 확인한다.
        with tempfile.TemporaryDirectory(dir=".omc") as folder:
            root = Path(folder)
            paths = [root / name for name in ("storms.csv", "store", "cells.csv", "warnings.csv", "output")]
            argv = ["trigger_run"]
            for name, path in zip(("storms", "store", "cells", "warnings", "output"), paths):
                argv.extend(["--" + name, str(path)])
            with patch("src.forecast.trigger_run.pd.read_csv") as read, \
                 patch("src.forecast.trigger_run.evaluate") as evaluate_mock, \
                 patch("src.forecast.trigger_run.frozen_parameters") as frozen_mock:
                with self.assertRaisesRegex(FileNotFoundError, "coverage.csv"):
                    run(*paths)
                with patch("sys.argv", argv), patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    with self.assertRaises(SystemExit) as stopped:
                        main()
                    self.assertEqual(stopped.exception.code, 2)
                    self.assertIn("coverage.csv", stderr.getvalue())
                    self.assertIn("실행을 중단", stderr.getvalue())
                read.assert_not_called()
                evaluate_mock.assert_not_called()
                frozen_mock.assert_not_called()
            self.assertFalse(paths[-1].exists())

    def test_synthetic_run(self):
        """gzip 입력부터 JSON·CSV 저장까지 실제 실행 경로를 검증한다."""
        # 합성 원문만 임시 폴더에 쓰며 부트스트랩 반복은 이 통합시험에서 줄인다.
        with tempfile.TemporaryDirectory(dir=".omc") as folder:
            root = Path(folder)
            storms = synthetic_storms().drop(columns=["r12max_fc24", "r12max_fc6", "warn_advisory", "warn_warning"])
            storms.loc[storms.role.eq("holdout"), "t0"] = "MUST_NOT_PARSE"
            storms.to_csv(root / "storms.csv", index=False)
            store = root / "store"
            store.mkdir()
            manifests = []
            for i, storm in enumerate(storms[storms.role.eq("development")].itertuples()):
                for lead in (24, 6):
                    issue = issue_before(storm.t0, lead)
                    var = "R12" if issue.year < 2013 else "R06" if issue.year < 2021 else "PCP"
                    _, manifest, cells, grids = synthetic_forecast(issue, var)
                    manifests.append(manifest)
                    for relative in manifest.path:
                        path = store / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        raw = (",".join([str(i + 1)] * (253 * 149)) + ",").encode("ascii")
                        path.write_bytes(gzip.compress(raw))
            pd.concat(manifests).to_csv(store / "manifest.csv", index=False)
            cells.to_csv(root / "cells.csv", index=False)
            pd.DataFrame(columns=["TM_FC", "TM_EF", "TM_IN", "REG_ID", "WRN", "LVL", "CMD"]).to_csv(root / "warnings.csv", index=False)
            coverage = pd.DataFrame(dict(month=pd.period_range("2011-06", "2025-07", freq="M").astype(str), status="ok"))
            coverage.loc[coverage.month.eq("2011-06"), "status"] = "missing"
            coverage.to_csv(root / "coverage.csv", index=False)
            with patch("src.forecast.trigger_run.summarize", side_effect=lambda p: summarize(p, n_bootstrap=12)):
                output = run(root / "storms.csv", store, root / "cells.csv", root / "warnings.csv", root / "output")
            self.assertEqual({p.name for p in output.iterdir()}, {"features.csv", "predictions.csv", "metrics.csv", "reliability.csv",
                                                                 "primary_endpoint.json", "frozen_params.json", "manifest.json"})
            for filename in ("features.csv", "predictions.csv"):
                table = pd.read_csv(output / filename)
                self.assertNotIn("h", set(table.storm_id))
                self.assertFalse(table.role.eq("holdout").any())
                if filename == "features.csv":
                    self.assertIn("n_error_blocks", table.columns)
                    self.assertTrue(table.n_error_blocks.eq(0).all())
                    warning = table.drop_duplicates("storm_id").set_index("storm_id")
                    self.assertEqual(warning.loc["a", "warn_status"], "coverage_missing")
                    self.assertTrue(warning.loc["a", ["warn_advisory", "warn_warning", "first_warn_lead_h"]].isna().all())
                    self.assertTrue(warning.drop(index="a").warn_status.eq("ok").all())
                    self.assertTrue(warning.drop(index="a").warn_advisory.eq(0).all())
                    self.assertTrue(warning.drop(index="a").warn_warning.eq(0).all())
                else:
                    self.assertEqual(table.columns.tolist(), PREDICTION_COLUMNS)
                    self.assertTrue(table.p_ref.notna().all())
                    self.assertFalse((table.storm_id.eq("a") & table.model.isin(["B_warn", "B_warn3"])).any())
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["excluded_by_reason"]["holdout_disabled"], 1)
            self.assertEqual(manifest["protocol_version"], "v1.1")
            self.assertTrue(manifest["run_id"].startswith("trigger_"))
            self.assertTrue(manifest["inputs"])
            self.assertTrue(manifest["forecast_inputs"])
            self.assertEqual(manifest["inputs"][str(root / "coverage.csv")], hashlib.sha256((root / "coverage.csv").read_bytes()).hexdigest())
            self.assertEqual(manifest["n_warning_na_storms"], 1)
            self.assertEqual(manifest["warning_status_counts"], {"coverage_missing": 1, "ok": 5})
            params = json.loads((output / "frozen_params.json").read_text())
            self.assertEqual(set(params), {"V3", "all_dev"})
            self.assertEqual(params["V3"]["M_fc24"]["n"], 5)
            self.assertEqual(params["all_dev"]["M_fc24"]["n"], 6)


if __name__ == "__main__":
    unittest.main()
