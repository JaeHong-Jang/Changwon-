"""합성 강우·흔적으로 호우 목록 경계를 검증하고 개발 스모크를 제공한다."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.forecast import catalog_run as CR
from src.forecast.storm_labels import assign_roles, label_storms, label_window, link_traces, trace_key_columns, trace_keys
from src.forecast.storms import build_catalog, fixed_stations, group_storms, heavy_hours, rolling_totals, storm_features


def rainfall(start="2012-07-01 01:00", periods=24, value=0.0, station=1):
    """연속된 KST 종료시각을 가진 합성 시간강수를 만든다."""
    # 모든 값이 유효한 기준 강우 표를 만든다.
    return pd.DataFrame({"station_id": station, "observed_at": pd.date_range(start, periods=periods, freq="h"),
                         "rainfall_mm": value, "quality_flag": "ok"})


def storm_rows(times):
    """독립된 단일 시각 사상들의 라벨 검증 표를 만든다."""
    # 그룹 병합 없이 각 시각을 별개 사상으로 만들어 창 중첩도 시험한다.
    times = pd.to_datetime(times)
    return pd.DataFrame({"storm_id": "S" + times.strftime("%Y%m%d%H"), "t0": times, "t1": times,
                         "year": times.year})


def trace_rows(dates):
    """원본 행 식별자를 가진 개발 전용 합성 흔적을 만든다."""
    # 도형을 읽지 않고 날짜 연결에 필요한 속성만 구성한다.
    return pd.DataFrame({"source_id": "synthetic", "object_id": [f"object{i}" for i in range(len(dates))],
                         "source_record_id": [f"file#{i}" for i in range(len(dates))], "role": "development",
                         "event_date": pd.to_datetime(dates)})


class StormTests(unittest.TestCase):
    """누적·임계·연결성·특징·지점 가동률의 고정 경계를 확인한다."""

    def test_missing_and_complete_hours(self):
        """행 누락·품질 불량·NaN이 각 누적창을 무효화하는지 확인한다."""
        # 연속 관측에서 처음 완성되는 창과 서로 다른 결측 원인을 검증한다.
        rain = rainfall(periods=30, value=1.0)
        rain.loc[5, "quality_flag"] = "bad"
        rain.loc[20, "rainfall_mm"] = np.nan
        rain = rain.drop(index=10)
        totals = rolling_totals(rain).set_index("observed_at")
        self.assertEqual(len(totals), 30)
        self.assertEqual(totals.iloc[2].r3, 3)
        self.assertTrue(pd.isna(totals.iloc[1].r3))
        for index in [5, 6, 7, 10, 11, 12, 20, 21, 22]:
            self.assertTrue(pd.isna(totals.iloc[index].r3))
        self.assertTrue(totals.r12.isna().all())
        complete = rolling_totals(rainfall(periods=12, value=2.0))
        self.assertEqual(complete.iloc[-1].r12, 24)
        other = rainfall(periods=12, value=3.0, station=2)
        both = rolling_totals(pd.concat([rainfall(periods=12, value=2.0), other]))
        self.assertEqual(both.groupby("station_id").r12.max().tolist(), [24, 36])

    def test_thresholds_and_group_gap(self):
        """60·110mm 임계와 72·73시간 병합 경계를 확인한다."""
        # 한 지점에서만 임계에 도달해도 같은 시각은 한 번만 선택한다.
        times = pd.date_range("2012-07-01", periods=4, freq="h")
        totals = pd.DataFrame({"station_id": [1, 1, 2, 2], "observed_at": times,
                               "r3": [59.9, 60, 0, np.nan], "r12": [109.9, 0, 110, np.nan]})
        self.assertEqual(heavy_hours(totals), list(times[1:3]))
        start = times[0]
        hours = [start + pd.Timedelta(hours=h) for h in [145, 72, 0, 72]]
        storms = group_storms(hours)
        self.assertEqual(storms.n_heavy_hours.tolist(), [2, 1])
        self.assertEqual(storms.t1.iloc[0] - storms.t0.iloc[0], pd.Timedelta(hours=72))
        self.assertTrue(group_storms([]).empty)

    def test_feature_inclusive_boundary(self):
        """t0−12h와 t1을 포함하고 창 밖 관측은 제외하는지 확인한다."""
        # 경계 밖에 더 큰 값을 두어 닫힌 창 선택을 확인한다.
        start = pd.Timestamp("2012-07-02")
        totals = pd.DataFrame({"station_id": [1, 1, 2, 3, 4],
                               "observed_at": [start + pd.Timedelta(hours=h) for h in [-13, -12, 0, 1, 0]],
                               "r12": [999, 120, 100, 999, np.nan], "r3": [999, 60, 80, 999, 1]})
        out = storm_features(group_storms([start]), totals).iloc[0]
        self.assertEqual(out.r12max_obs, 120)
        self.assertEqual(out.r3max_obs, 80)
        self.assertEqual(out.n_stations_active, 2)
        self.assertEqual(out.storm_id, "S2012070200")

    def test_fixed_station_denominator(self):
        """예정 시간·윤년·2025년 마지막 24시와 빈 고정 목록을 확인한다."""
        # 실제 관측 길이를 분모로 쓰지 않으며 마지막 종료시각만 포함한다.
        full = rainfall("2025-01-01 01:00", periods=260 * 24)
        self.assertEqual(full.observed_at.iloc[-1], pd.Timestamp("2025-09-18"))
        self.assertEqual(fixed_stations(full, years=[2025], min_coverage=1), [1])
        self.assertEqual(fixed_stations(full.iloc[:-1], years=[2025], min_coverage=1), [])
        shifted = full.copy()
        shifted.loc[shifted.index[-1], "observed_at"] = pd.Timestamp("2025-01-01")
        self.assertEqual(fixed_stations(shifted, years=[2025], min_coverage=1), [])
        self.assertEqual(fixed_stations(full), [])
        self.assertEqual(fixed_stations(rainfall(periods=24), years=[2012]), [])
        leap = rainfall("2012-01-01 01:00", periods=366 * 24)
        self.assertEqual(fixed_stations(leap, years=[2012], min_coverage=1), [1])
        self.assertEqual(fixed_stations(leap.iloc[:365 * 24], years=[2012], min_coverage=1), [])
        self.assertEqual(fixed_stations(full.iloc[:5928], years=[2025]), [1])
        self.assertEqual(fixed_stations(full.iloc[:5927], years=[2025]), [])
        self.assertTrue(build_catalog(full, stations=[]).empty)

    def test_duplicate_rain_key_rejected(self):
        """중복 시간 키를 임의 집계하지 않고 거부하는지 확인한다."""
        # 같은 시간 관측을 복제해 입력 계약 위반을 만든다.
        rain = rainfall(periods=1)
        with self.assertRaises(ValueError):
            rolling_totals(pd.concat([rain, rain]))


class LabelTests(unittest.TestCase):
    """인벤토리 경계·흔적 제외·사상 라벨·재선택 키를 확인한다."""

    def test_role_window_boundaries(self):
        """개발 인벤토리 양끝을 넘는 날짜 창에 라벨 역할을 주지 않는다."""
        # 날짜 창 전체의 포함 여부로 경계 당일과 전날을 구별한다.
        storms = assign_roles(storm_rows(["2006-01-01", "2006-01-02", "2019-12-30", "2019-12-31",
                                         "2025-09-16", "2025-09-17", "2020-06-01"]))
        self.assertEqual(storms.role.tolist(), ["uncovered", "development", "development", "uncovered",
                                              "development", "uncovered", "uncovered"])
        self.assertEqual(label_window("2012-07-01 23:00", "2012-07-02 01:00"),
                         (pd.Timestamp("2012-06-30"), pd.Timestamp("2012-07-03")))

    def test_link_status_and_inclusive_dates(self):
        """양끝 날짜는 연결하고 미상·창 중첩·범위 밖 날짜는 제외한다."""
        # 두 단일 시각 사상의 중첩 날짜가 어느 사상에도 배정되지 않게 한다.
        storms = assign_roles(storm_rows(["2012-07-02 12:00", "2012-07-04 12:00"]))
        traces = trace_rows(["2012-07-01", "2012-07-05", "2012-07-03", None, "2012-07-06"])
        links, audit = link_traces(storms, traces)
        self.assertEqual(audit.status.tolist(), ["linked", "linked", "ambiguous", "undated", "unlinked"])
        self.assertEqual(len(links), 2)
        self.assertTrue(audit.loc[2:, "storm_id"].isna().all())
        self.assertEqual(audit.loc[2, "candidate_storms"], ";".join(storms.storm_id))

    def test_labels_event_keys_active_year(self):
        """읽은 역할만 0·1로 표시하고 양성 연도의 같은 역할 사상을 고른다."""
        # 양성 연도 음성·다른 연도 음성·미확보 범위·경계 연결을 함께 비교한다.
        storms = assign_roles(storm_rows(["2012-07-02", "2012-08-01", "2014-07-01", "2020-07-01",
                                         "2019-12-31", "2012-09-01"]))
        links, audit = link_traces(storms, trace_rows(["2012-07-02", "2019-12-31", "2012-09-01"]))
        out = label_storms(storms, links, ["development"])
        self.assertEqual(out.label.iloc[:3].tolist(), [1, 0, 0])
        self.assertTrue(out.label.iloc[3:5].isna().all())
        self.assertEqual(out.event_key.dropna().tolist(), ["2012", "2012"])
        self.assertEqual(out.active_year.tolist(), [True, True, False, False, False, True])
        self.assertEqual(out.linked_dates.iloc[0], "2012-07-02")
        self.assertEqual(CR._counts(out, audit)["development_positive_multiple_storms_by_year"], {"2012": 2})
        self.assertTrue(label_storms(storms, links, []).label.isna().all())

    def test_role_mismatch_and_uncovered_window(self):
        """개발 흔적이 홀드아웃 역할이나 미포괄 사상에 배정되지 않게 한다."""
        # 합성 날짜만으로 역할 교차와 인벤토리 경계 창의 제외 사유를 확인한다.
        storms = assign_roles(storm_rows(["2023-07-02", "2019-12-31"]))
        traces = trace_rows(["2023-07-02", "2019-12-31"])
        links, audit = link_traces(storms, traces)
        self.assertTrue(links.empty)
        self.assertEqual(audit.status.tolist(), ["role_mismatch", "uncovered_window"])
        self.assertEqual(audit.candidate_storms.tolist(), storms.storm_id.tolist())
        self.assertTrue(audit.storm_id.isna().all())
        out = label_storms(storms, links, ["development", "holdout"])
        self.assertEqual(out.label.iloc[0], 0)
        self.assertTrue(pd.isna(out.label.iloc[1]))
        self.assertEqual(out.n_linked_traces.tolist(), [0, 0])
        counts = CR._counts(out, audit)["trace_status"]
        self.assertEqual(counts["role_mismatch"], 1)
        self.assertEqual(counts["uncovered_window"], 1)

    def test_matching_role_candidates_only(self):
        """날짜 창이 겹쳐도 같은 역할의 유효 후보만 연결 판정에 쓴다."""
        # 합성 역할을 지정해 다른 역할과 미포괄 창이 연결을 방해하지 않게 한다.
        storms = storm_rows(["2012-07-02", "2012-07-03", "2012-07-04"])
        storms["role"] = ["development", "holdout", "uncovered"]
        links, audit = link_traces(storms, trace_rows(["2012-07-03"]))
        self.assertEqual(links.storm_id.tolist(), [storms.storm_id.iloc[0]])
        self.assertEqual(audit.candidate_storms.tolist(), [storms.storm_id.iloc[0]])
        storms.loc[0, "role"] = "uncovered"
        traces = trace_rows(["2012-07-01"])
        traces["role"] = "uncovered"
        links, audit = link_traces(storms, traces)
        self.assertTrue(links.empty)
        self.assertEqual(audit.status.tolist(), ["uncovered_window"])

    def test_unique_trace_keys(self):
        """기본 키 충돌 때 영속 원본 행 키로 정확히 다시 선택할 수 있다."""
        # 기본 키와 확장 키의 계약을 각각 확인한다.
        traces = trace_rows(["2012-07-02", "2012-07-02"])
        self.assertEqual(trace_key_columns(traces), ["source_id", "object_id"])
        traces.loc[1, "object_id"] = traces.loc[0, "object_id"]
        keys = trace_key_columns(traces)
        self.assertEqual(keys, ["source_id", "object_id", "source_record_id"])
        links, _ = link_traces(assign_roles(storm_rows(["2012-07-02"])), traces)
        self.assertEqual(len(links.merge(traces, on=keys, validate="one_to_one")), 2)
        with self.assertRaises(ValueError):
            trace_key_columns(traces.drop(columns="source_record_id"))

    def test_public_trace_keys_reselect_duplicate_objects(self):
        """중복 객체의 서로 다른 원본 행을 공개 키로 사상별 재선택한다."""
        # 비연속 색인과 고유 행의 결측 보조 키도 그대로 보존해야 한다.
        traces = trace_rows(["2012-07-02", "2012-08-02", "2012-09-02"])
        traces.loc[1, "object_id"] = traces.loc[0, "object_id"]
        traces.loc[2, "source_record_id"] = None
        traces.index = [7, 3, 9]
        keys = trace_keys(traces)
        self.assertEqual(keys.index.tolist(), [7, 3, 9])
        self.assertEqual(keys.tolist(), ["synthetic|object0|file#0", "synthetic|object0|file#1", "synthetic|object2"])
        storms = assign_roles(storm_rows(["2012-07-02", "2012-08-02", "2012-09-02"]))
        links, audit = link_traces(storms, traces)
        self.assertEqual(audit.trace_key.tolist(), keys.tolist())
        for index, storm in enumerate(storms.storm_id):
            selected = traces.loc[keys.isin(links.loc[links.storm_id.eq(storm), "trace_key"])]
            self.assertEqual(selected.index.tolist(), [traces.index[index]])

    def test_trace_key_collisions_rejected(self):
        """확장 후 중복과 문자열 구분자 충돌은 유일 키 오류로 거부한다."""
        # 보조 키 부재·중복과 서로 다른 기본 키의 문자열 충돌을 확인한다.
        traces = trace_rows(["2012-07-02", "2012-07-02"])
        traces["object_id"] = "same"
        with self.assertRaises(ValueError):
            trace_keys(traces.drop(columns="source_record_id"))
        traces["source_record_id"] = "same"
        with self.assertRaises(ValueError):
            trace_keys(traces)
        traces["source_id"] = ["a|b", "a"]
        traces["object_id"] = ["c", "b|c"]
        with self.assertRaises(ValueError):
            trace_keys(traces)


class CatalogRunTests(unittest.TestCase):
    """합성 실행 계약과 선택적으로 실제 개발 자료를 확인한다."""

    def test_run_outputs_and_manifest(self):
        """개발 전용 임시 실행의 열 순서·해시·집계·홀드아웃 미호출을 확인한다."""
        # 실제 자료 접근을 전부 합성 입력으로 바꾸고 저장 경로만 임시로 연다.
        rain = rainfall(periods=24, value=20)
        traces = trace_rows(["2012-07-01", None, "2012-08-01"])
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(CR.pd, "read_parquet", return_value=rain), \
                patch.object(CR.FT, "files_for", return_value=[]) as files, \
                patch.object(CR.FT, "load", return_value=(traces, {})), \
                patch.object(CR.FT, "load_holdout", side_effect=AssertionError("홀드아웃 접근")) as holdout, \
                patch.object(CR, "file_sha256", return_value="rainhash"), \
                patch.object(CR, "vector_manifest", return_value={"synthetic.shp": "tracehash"}), \
                patch.object(CR, "git_state", return_value=("abcdef0", True)):
            folder = CR.run(Path(temporary))
            self.assertEqual({p.name for p in folder.iterdir()},
                             {"storms.csv", "storms_fixed_stations.csv", "trace_links.csv", "manifest.json"})
            storms = pd.read_csv(folder / "storms.csv")
            fixed = pd.read_csv(folder / "storms_fixed_stations.csv")
            trace_links = pd.read_csv(folder / "trace_links.csv")
            manifest = json.loads((folder / "manifest.json").read_text())
            self.assertEqual(storms.columns.tolist(), CR.STORM_COLUMNS)
            self.assertEqual(fixed.columns.tolist(), CR.STORM_COLUMNS)
            self.assertTrue(fixed.empty)
            self.assertRegex(storms.t0.iloc[0], r"^2012-07-01 \d{2}:\d{2}$")
            self.assertEqual(manifest["counts"]["by_label"], {"1": 1, "0": 0, "<NA>": 0})
            self.assertEqual(manifest["counts"]["trace_status"],
                             {"linked": 1, "unlinked": 1, "undated": 1, "ambiguous": 0,
                              "role_mismatch": 0, "uncovered_window": 0})
            self.assertEqual(trace_links.columns.tolist(),
                             ["trace_key", "source_id", "object_id", "source_record_id", "role",
                              "event_date", "storm_id", "status", "candidate_storms"])
            self.assertEqual(trace_links.trace_key.tolist(), trace_keys(traces).tolist())
            self.assertEqual(manifest["counts"]["fixed_stations_catalog"], "분석 불가")
            self.assertEqual(manifest["inputs"]["synthetic.shp"], "tracehash")
            self.assertEqual(manifest["protocol"], "docs/FORECAST_PROTOCOL.md v1.1")
            self.assertEqual(manifest["params"]["gap_h"], 72)
            self.assertEqual(manifest["trace_key_columns"], ["source_id", "object_id"])
            self.assertRegex(folder.name, r"^catalog_\d{8}T\d{6}Z_abcdef0-dirty_development$")
            files.assert_called_once_with("development")
            holdout.assert_not_called()

    @unittest.skipUnless(os.environ.get("CHANGWON_SLOW_TESTS"), "실제 개발 실행은 CHANGWON_SLOW_TESTS 설정 시 검증")
    def test_real_development_smoke(self):
        """실제 개발 목록이 기존 공간 학습 사상 연도를 모두 포함하는지 확인한다."""
        # 입력이 있는 환경에서 개발 역할만 읽고 누락 키를 그대로 실패로 보고한다.
        if not CR.RAIN_PATH.exists():
            self.skipTest("canonical 강우 파일 없음")
        with tempfile.TemporaryDirectory() as temporary:
            folder = CR.run(Path(temporary), roles=("development",))
            manifest = json.loads((folder / "manifest.json").read_text())
            observed = set(manifest["counts"]["development_positive_event_keys"])
            expected = {"2006", "2012", "2014", "2016", "2019", "2025"}
            self.assertTrue(expected <= observed, f"개발 양성 누락={sorted(expected - observed)}; counts={manifest['counts']}")


if __name__ == "__main__":
    unittest.main()
