"""H02 정제 회귀 테스트.

코드 리뷰가 지적한 M1·M2·M3·M8·m2·m4·M4 를 고정한다. 각 테스트는 수정 전 코드에서
실패하도록 썼다 — 게이트가 "구조적으로 통과할 수밖에 없는" 상태로 되돌아가면 잡힌다.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data import normalize

CLIMATOLOGY = (pd.Timestamp("2015-01-01"), pd.Timestamp("2024-12-31"))


def write_csv(root: Path, name: str, header: list[str], rows: list[list]) -> Path:
    path = root / name
    lines = [",".join(header)] + [",".join(str(c) for c in r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="cp949")
    return path


def rain_header() -> list[str]:
    return ["지역코드", "지역명", "년월일"] + [f"{h}시강수량" for h in range(1, 25)]


def river_header() -> list[str]:
    return ["지역코드", "지역명", "년월일"] + [f"{h}시하천수위" for h in range(1, 25)]


def rain_row(sid: int, name: str, date: str, values) -> list:
    vals = list(values) if not isinstance(values, (int, float)) else [values] * 24
    return [sid, name, date, *vals]


class RowAccountingTest(unittest.TestCase):
    """M2 — 행 보존을 '개수 비교'가 아니라 'source_row 집합'으로 증명한다."""

    def test_accounting_detects_lost_row(self) -> None:
        """canonical 에도 quarantine 에도 없는 원행이 있으면 잡아야 한다."""
        ok, detail = normalize.row_accounting(rows_in=5, canonical_rows={0, 1, 2}, quarantine_rows={3})
        self.assertFalse(ok)
        self.assertIn(4, detail["missing"])

    def test_accounting_detects_double_counted_row(self) -> None:
        """같은 원행이 canonical 과 quarantine 양쪽에 있으면 잡아야 한다."""
        ok, detail = normalize.row_accounting(rows_in=3, canonical_rows={0, 1, 2}, quarantine_rows={2})
        self.assertFalse(ok)
        self.assertIn(2, detail["overlap"])

    def test_accounting_passes_on_exact_partition(self) -> None:
        ok, detail = normalize.row_accounting(rows_in=4, canonical_rows={0, 2}, quarantine_rows={1, 3})
        self.assertTrue(ok, detail)

    def test_real_cleaning_reports_partition_metric(self) -> None:
        """clean_rainfall 이 새 지표를 내야 한다 (수정 전에는 키 자체가 없다)."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_csv(root, "rain.csv", rain_header(), [
                rain_row(1, "가", "2015-01-01", 1),
                rain_row(1, "가", "2015-01-01", 1),          # R01 완전중복
                rain_row(2, "나", "2015-01-02", 2),
            ])
            _, _, m = normalize.clean_rainfall(path, climatology=CLIMATOLOGY)
        self.assertIn("row_partition_ok", m)
        self.assertTrue(m["row_partition_ok"])
        self.assertEqual(m["row_partition_detail"], {"missing": [], "overlap": []})


class RiverGateTest(unittest.TestCase):
    """M1 — 전 셀이 센티널인 쓰레기 파일이 통과하면 안 된다."""

    def test_all_sentinel_file_has_no_usable_station(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_csv(root, "river.csv", river_header(), [
                [1, "가", "2015-01-01", *([-47999] * 24)],
                [2, "나", "2015-01-02", *([9999] * 24)],
            ])
            _, _, m = normalize.clean_river(path, climatology=CLIMATOLOGY)
        self.assertEqual(m["usable_stations_in_period"], 0,
                         "센티널만 있는 파일에서 사용 가능 지점이 0이어야 한다")
        self.assertTrue(m["cell_accounting_ok"])

    def test_cell_accounting_catches_missing_quarantine_record(self) -> None:
        """센티널·범위밖 셀 수와 quarantine 셀 기록 수가 어긋나면 잡아야 한다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_csv(root, "river.csv", river_header(), [
                [1, "가", "2015-01-01", *([50] * 12 + [-47999] * 6 + [5000] * 6)],
            ])
            _, quarantine, m = normalize.clean_river(path, climatology=CLIMATOLOGY)
        cell_rows = quarantine[quarantine["reason"].isin(["H02-W01", "H02-W02"])]
        self.assertEqual(len(cell_rows), m["sentinel_cells"] + m["out_of_range_cells"])
        self.assertTrue(m["cell_accounting_ok"])

    def test_station_with_valid_values_is_usable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_csv(root, "river.csv", river_header(), [
                [1, "가", "2015-01-01", *([50] * 24)],
                [2, "나", "2015-01-02", *([-47999] * 24)],
            ])
            _, _, m = normalize.clean_river(path, climatology=CLIMATOLOGY)
        self.assertEqual(m["usable_stations_in_period"], 1)


class ObsDateTest(unittest.TestCase):
    """M3 — canonical 이 obs_date 를 실어야 하고, 24시 셀도 원본 날짜에 속해야 한다."""

    def test_obs_date_column_exists_and_uses_source_date(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_csv(root, "rain.csv", rain_header(), [
                rain_row(1, "가", "2015-01-01", 1),
                rain_row(1, "가", "2015-01-02", 1),
            ])
            canonical, _, _ = normalize.clean_rainfall(path, climatology=CLIMATOLOGY)

        self.assertIn("obs_date", canonical.columns)
        self.assertEqual(canonical["obs_date"].nunique(), 2,
                         "24시 셀이 다음날로 넘어가 3일로 세면 안 된다")

        h24 = canonical[canonical["hour_label"] == "24시강수량"]
        first = h24[h24["obs_date"] == pd.Timestamp("2015-01-01")].iloc[0]
        self.assertEqual(first["observed_at"], pd.Timestamp("2015-01-02"),
                         "observed_at 은 누적 종료 시각이므로 다음날 00시가 맞다")

    def test_river_canonical_also_has_obs_date(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_csv(root, "river.csv", river_header(), [
                [1, "가", "2015-01-01", *([50] * 24)],
            ])
            canonical, _, _ = normalize.clean_river(path, climatology=CLIMATOLOGY)
        self.assertIn("obs_date", canonical.columns)
        self.assertEqual(canonical["obs_date"].nunique(), 1)


class CoverageTest(unittest.TestCase):
    """M8 — 커버리지는 '행이 있는 날'이 아니라 '유효값이 있는 날'이어야 한다."""

    def test_station_with_rows_but_no_values_is_excluded(self) -> None:
        """행은 매일 있지만 값이 전부 비어 있는 지점은 cohort 에 들면 안 된다."""
        dates = pd.date_range("2015-01-01", "2015-12-31")
        rows = []
        for day in dates:
            d = day.strftime("%Y-%m-%d")
            rows.append(rain_row(1, "실측", d, 1))                 # 정상 지점
            rows.append(rain_row(2, "빈값", d, [""] * 24))          # 행만 있고 값 없음
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp), "rain.csv", rain_header(), rows)
            _, _, m = normalize.clean_rainfall(
                path, climatology=(pd.Timestamp("2015-01-01"), pd.Timestamp("2015-12-31"))
            )
        self.assertIn(1, m["cohort_station_ids"])
        self.assertNotIn(2, m["cohort_station_ids"],
                         "값이 하나도 없는 지점이 cohort 에 들어갔다 — 행 존재만 세고 있다")

    def test_out_of_range_cells_do_not_count_as_observation(self) -> None:
        """범위 밖 셀만 있는 날은 관측일로 세면 안 된다 (코드북 확인 전 제외 대상)."""
        dates = pd.date_range("2015-01-01", "2015-12-31")
        rows = []
        for day in dates:
            d = day.strftime("%Y-%m-%d")
            rows.append(rain_row(1, "실측", d, 1))
            rows.append(rain_row(3, "범위밖", d, [-5] * 24))
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp), "rain.csv", rain_header(), rows)
            _, _, m = normalize.clean_rainfall(
                path, climatology=(pd.Timestamp("2015-01-01"), pd.Timestamp("2015-12-31"))
            )
        self.assertNotIn(3, m["cohort_station_ids"])


class MetricNamingTest(unittest.TestCase):
    """m2 — 행 단위 격리와 셀 단위 격리를 이름으로 구분한다."""

    def test_row_and_cell_quarantine_counts_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_csv(root, "rain.csv", rain_header(), [
                rain_row(1, "가", "2015-01-01", 1),
                rain_row(1, "가", "2015-01-01", 1),           # R01 행 격리 1건
                rain_row(2, "나", "2015-01-02", [-5] * 24),   # R04 셀 격리 24건
            ])
            _, quarantine, m = normalize.clean_rainfall(path, climatology=CLIMATOLOGY)

        self.assertEqual(m["rows_quarantined"], 1)
        self.assertEqual(m["cells_quarantined"], 24)
        self.assertEqual(len(quarantine), m["rows_quarantined"] + m["cells_quarantined"])


class ClimatologyParamTest(unittest.TestCase):
    """M4 — 분석기간은 모듈 상수가 아니라 인자로 들어와야 한다."""

    def test_climatology_argument_changes_cohort(self) -> None:
        rows = []
        for day in pd.date_range("2010-01-01", "2010-12-31"):
            rows.append(rain_row(1, "가", day.strftime("%Y-%m-%d"), 1))
        with tempfile.TemporaryDirectory() as d:
            path = write_csv(Path(d), "rain.csv", rain_header(), rows)
            _, _, in_period = normalize.clean_rainfall(
                path, climatology=(pd.Timestamp("2010-01-01"), pd.Timestamp("2010-12-31"))
            )
            _, _, out_period = normalize.clean_rainfall(
                path, climatology=(pd.Timestamp("2015-01-01"), pd.Timestamp("2024-12-31"))
            )
        self.assertEqual(in_period["stations_in_cohort"], 1)
        self.assertEqual(out_period["stations_in_cohort"], 0,
                         "분석기간을 바꿔도 결과가 같다면 인자가 무시되고 있다")

    def test_module_has_no_hardcoded_climatology(self) -> None:
        self.assertFalse(hasattr(normalize, "CLIMATOLOGY"),
                         "분석기간이 모듈 상수로 남아 있으면 config 와 어긋날 수 있다")


class ZeroOnlyNoteTest(unittest.TestCase):
    """m4 — 주석과 코드가 같은 말을 해야 한다."""

    def test_zero_only_station_flagged_regardless_of_period(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_csv(root, "river.csv", river_header(), [
                [1, "영값만", "2015-01-01", *([0] * 24)],
                [2, "실측", "2015-01-02", *([50] * 24)],
            ])
            _, _, m = normalize.clean_river(path, climatology=CLIMATOLOGY)
        self.assertEqual(m["zero_only_stations"], [1])


if __name__ == "__main__":
    unittest.main()
