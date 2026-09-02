"""판정 함수(src/data/quality.py) 단위 테스트.

quality.py 는 파일 I/O 도 그림도 없는 순수 함수라 합성 DataFrame 으로 전부 덮을 수 있다.
각 테스트는 코드 리뷰가 지적한 결함 하나에 대응하며, 수정 전에는 실패한다.
"""

from __future__ import annotations

import json
import math
import unittest

import pandas as pd

from src.data import quality
from src.data.quality import Thresholds

# 실제 분석과 같은 10년 창을 쓴다. 창이 길수록 "전체 커버리지는 90% 를 넘는데 특정
# 해만 거의 비어 있는" 지점이 가능해진다 — 이것이 중앙값 오염의 실제 위험이다.
LO = pd.Timestamp("2015-01-01")
HI = pd.Timestamp("2024-12-31")
YEARS = list(range(2015, 2025))
MM_PER_DAY = 4.0


def days_in(year: int) -> int:
    return 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365


def full_years(**overrides: int) -> dict[int, int]:
    """모든 해를 완전 관측으로 두고, 지정한 해만 관측일 수를 덮어쓴다."""
    days = {year: days_in(year) for year in YEARS}
    days.update({int(year[1:]): count for year, count in overrides.items()})
    return days


def rain_frame(specs: list[dict]) -> pd.DataFrame:
    """canonical 모양의 합성 표.

    specs 항목: {"station_id", "station_name"(선택), "days": {연도: 관측일 수}}
    각 관측일은 24시간이 아니라 하루 한 행으로 두고 강수량은 MM_PER_DAY 로 고정한다.
    """
    records = []
    for spec in specs:
        name = spec.get("station_name", f"지점{spec['station_id']}")
        for year, days in spec["days"].items():
            start = pd.Timestamp(year=year, month=1, day=1)
            for offset in range(days):
                records.append({
                    "station_id": spec["station_id"],
                    "station_name": name,
                    "obs_date": start + pd.Timedelta(days=offset),
                    "rainfall_mm": spec.get("mm_per_day", MM_PER_DAY),
                    "quality_flag": "ok",
                })
    return pd.DataFrame(records)


class RainfallMedianTest(unittest.TestCase):
    """M9 — 관측 중단 지점이 그 해 중앙값(분모)을 오염시키면 안 된다."""

    def test_year_median_excludes_coverage_gap_stations(self) -> None:
        # 6개 지점 모두 2019년은 완전 관측. 2020년에 지점 4~6 만 308일(84%)로 끊긴다.
        # 전체 기간 커버리지는 (365+308)/731 = 92% 라 여섯 지점 다 cohort 에 남지만,
        # 2020년은 비교 자격(95%)이 없다. 중앙값을 전체로 계산하면 끊긴 지점의 낮은
        # 연총량이 분모를 끌어내려 정상 지점의 비율이 부푼다.
        full = [{"station_id": i, "days": full_years()} for i in (1, 2, 3)]
        gaps = [{"station_id": i, "days": full_years(y2020=200)} for i in (4, 5, 6)]
        annual = quality.rainfall_table(rain_frame(full + gaps), LO, HI)

        self.assertEqual(len(annual.attrs["cohort_ids"]), 6, "여섯 지점 다 cohort 에 있어야 한다")

        median_2020 = float(annual.loc[annual["year"] == 2020, "year_median"].iloc[0])
        self.assertAlmostEqual(
            median_2020, 366 * MM_PER_DAY, places=6,
            msg="2020년 중앙값이 관측 중단 지점을 포함해 계산됐다",
        )

        metrics, anomalies = quality.check_rainfall(annual)
        self.assertEqual(metrics["rainfall_deviant_station_years"], 0)
        self.assertEqual(anomalies, [])
        gap_years = {(g["station"], g["year"]) for g in metrics["rainfall_coverage_gap_station_years"]}
        self.assertEqual(len(gap_years), 3)
        self.assertTrue(all(year == 2020 for _, year in gap_years))

    def test_contaminated_median_would_flip_the_verdict(self) -> None:
        """분모 오염이 실제로 판정을 뒤집을 수 있음을 고정한다.

        10년 중 2020년만 10일 관측인 지점 2개도 전체 커버리지는 90.3% 라 cohort 에 남는다.
        오염된 중앙값(40mm)으로 나누면 정상 지점의 비율이 36배가 되어 '이탈'로 오판된다.
        올바른 중앙값이면 1.0 이다.
        """
        full = [{"station_id": 1, "days": full_years()}]
        gaps = [{"station_id": i, "days": full_years(y2020=10)} for i in (2, 3)]
        annual = quality.rainfall_table(rain_frame(full + gaps), LO, HI)

        self.assertEqual(len(annual.attrs["cohort_ids"]), 3, "세 지점 다 cohort 에 있어야 한다")

        row = annual[(annual["station_id"] == 1) & (annual["year"] == 2020)].iloc[0]
        self.assertAlmostEqual(float(row["ratio"]), 1.0, places=6)

        contaminated = annual[annual["year"] == 2020]["rainfall_mm"].median()
        self.assertGreater(
            float(row["rainfall_mm"]) / float(contaminated), 2.0,
            "이 합성 입력은 오염된 중앙값에서 실제로 이탈 판정이 났어야 한다",
        )

        metrics, anomalies = quality.check_rainfall(annual)
        self.assertEqual(metrics["rainfall_deviant_station_years"], 0)
        self.assertEqual(anomalies, [])


class CohortGroupingTest(unittest.TestCase):
    """M10 — 지점명이 바뀌어도 같은 station_id 는 한 지점이어야 한다."""

    def test_cohort_not_split_by_station_name_change(self) -> None:
        # 같은 지점이 2019년엔 옛 이름, 2020년엔 새 이름으로 기록됐다.
        early = {year: days_in(year) for year in YEARS[:5]}
        late = {year: days_in(year) for year in YEARS[5:]}
        frame = pd.concat([
            rain_frame([{"station_id": 1, "station_name": "옛이름", "days": early}]),
            rain_frame([{"station_id": 1, "station_name": "새이름", "days": late}]),
        ], ignore_index=True)

        annual = quality.rainfall_table(frame, LO, HI)
        self.assertEqual(
            annual.attrs["cohort_ids"], [1],
            "지점명이 바뀌었다고 두 지점으로 쪼개져 cohort 에서 탈락했다",
        )
        self.assertEqual(len(annual.attrs["coverage"]), 1)


class GridPopulationTest(unittest.TestCase):
    """M7 — 분석격자가 없으면 인구 비교 자체를 하지 않는다."""

    @staticmethod
    def stats(pairs: list[tuple[str, float]]) -> pd.DataFrame:
        return pd.DataFrame(
            [{"spatial_id": sid, "variable": "to_in_001", "value": v} for sid, v in pairs]
        )

    def test_skips_comparison_without_analysis_grid(self) -> None:
        # 전국 도엽 합계(500만)를 창원 인구와 비교하면 499% 같은 무의미한 이상징후가 나온다.
        frame = self.stats([(f"라라{i:06d}", 5_000_000 / 10) for i in range(10)])
        metrics, anomalies, _ = quality.check_grid_population(frame, None)

        self.assertIsNone(metrics["sgis_pop_ratio_vs_registered"])
        codes = [a["metric"] for a in anomalies]
        self.assertNotIn("총인구 합계 / 주민등록인구", codes,
                         "자르지 않은 전국 합계를 창원 인구와 비교했다")
        self.assertEqual(len(anomalies), 1)

    def test_compares_when_analysis_grid_given(self) -> None:
        thresholds = Thresholds(changwon_registered_population=1000.0)
        frame = self.stats([("A", 600.0), ("B", 400.0), ("밖", 9_999.0)])
        metrics, anomalies, _ = quality.check_grid_population(frame, {"A", "B"}, thresholds)

        self.assertEqual(metrics["sgis_grid_population_sum"], 1000)
        self.assertAlmostEqual(metrics["sgis_pop_ratio_vs_registered"], 1.0)
        self.assertEqual(anomalies, [])


class RiverBoundaryTest(unittest.TestCase):
    """m3 — '유효값 10% 이상' 이라고 써놓고 코드가 초과로 판정하면 안 된다."""

    @staticmethod
    def river_frame(valid_ratio: float, n: int = 100) -> pd.DataFrame:
        valid = round(n * valid_ratio)
        return pd.DataFrame({
            "station_id": [1] * n,
            "station_name": ["차룡8교"] * n,
            "obs_date": [LO] * n,
            "level_cm": [50.0] * valid + [None] * (n - valid),
        })

    def test_exactly_at_threshold_counts_as_usable(self) -> None:
        metrics, anomalies, _ = quality.check_river(self.river_frame(0.10), LO, HI)
        self.assertEqual(metrics["river_usable_stations"], 1,
                         "정확히 10% 인 지점이 '10% 이상' 기준에서 탈락했다")
        self.assertEqual(anomalies, [])

    def test_below_threshold_is_not_usable(self) -> None:
        metrics, anomalies, _ = quality.check_river(self.river_frame(0.09), LO, HI)
        self.assertEqual(metrics["river_usable_stations"], 0)
        self.assertEqual(len(anomalies), 1)

    def test_sentinel_leak_is_reported(self) -> None:
        frame = self.river_frame(1.0)
        frame.loc[0, "level_cm"] = -47999.0
        metrics, anomalies, _ = quality.check_river(frame, LO, HI)
        self.assertEqual(metrics["river_sentinel_leaked_into_level"], 1)
        self.assertTrue(any("센티널" in a["metric"] for a in anomalies))


class JsonSafetyTest(unittest.TestCase):
    """m14 — metrics 에 NaN 이 들어가면 manifest 가 유효하지 않은 JSON 이 된다."""

    def test_empty_input_produces_serializable_metrics(self) -> None:
        empty = pd.DataFrame(
            columns=["station_id", "station_name", "obs_date", "rainfall_mm", "quality_flag"]
        ).astype({"obs_date": "datetime64[ns]", "rainfall_mm": "float64"})
        annual = quality.rainfall_table(empty, LO, HI)
        metrics, anomalies = quality.check_rainfall(annual)

        text = json.dumps(metrics, ensure_ascii=False, allow_nan=False)
        self.assertNotIn("NaN", text)
        self.assertIsNone(metrics["rainfall_annual_median_mm"])
        self.assertEqual(metrics["rainfall_cohort_stations"], 0)
        self.assertEqual(anomalies, [])

    def test_no_nan_in_real_shaped_metrics(self) -> None:
        annual = quality.rainfall_table(
            rain_frame([{"station_id": i, "days": full_years()} for i in (1, 2, 3)]),
            LO, HI,
        )
        metrics, _ = quality.check_rainfall(annual)
        for key, value in metrics.items():
            if isinstance(value, float):
                self.assertFalse(math.isnan(value), f"{key} 가 NaN")


class ThresholdsTest(unittest.TestCase):
    """m9 — 임계값은 config 가 단일 원천이고, 코드 기본값과 어긋나면 안 된다."""

    def test_from_params_reads_every_field(self) -> None:
        import dataclasses

        from src.utils.config import load_config

        config = load_config()["analysis"]
        params = {f"analysis.{key}": value for key, value in config.items()}
        thresholds = Thresholds.from_params(params)

        for field in dataclasses.fields(Thresholds):
            self.assertIn(
                Thresholds.CONFIG_KEYS[field.name], config,
                f"config.yaml 의 analysis 에 {Thresholds.CONFIG_KEYS[field.name]} 가 없다",
            )
            self.assertEqual(
                getattr(thresholds, field.name),
                config[Thresholds.CONFIG_KEYS[field.name]],
            )

    def test_pipeline_declares_the_params_it_uses(self) -> None:
        """YAML 에 선언하지 않은 param 을 쓰면 fingerprint 가 임계값 변경을 놓친다."""
        import dataclasses

        from src.pipeline.graph import Graph

        declared = set(Graph.load().nodes["h02_eda_data_check"].params)
        needed = {
            f"analysis.{Thresholds.CONFIG_KEYS[f.name]}" for f in dataclasses.fields(Thresholds)
        }
        self.assertTrue(
            needed <= declared,
            f"pipeline.yaml 에 선언되지 않은 임계값: {sorted(needed - declared)}",
        )


if __name__ == "__main__":
    unittest.main()
