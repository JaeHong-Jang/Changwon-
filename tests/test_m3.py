"""M3 설정 공간·안쪽 LOEO 선택·판정·재현 확인 단위 검사 (합성 자료, 홀드아웃 없음)."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.models import m1_scores, prior_fit
from src.models import m3_decision as D
from src.models.estimators import CANDIDATES, FIXED_PARAMS
from src.models.features import FEATURES
from src.models.m3_checks import match_reference
from src.models.m3_configs import FIXED_ID, VARIANTS, check_prespec, config_id, grid
from src.models.m3_run import status
from src.models.m3_select import config_loeo, loeo_splits, rank_configs, select_for_prior


def synthetic(seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """6 km 정사각 격자(100 m)에 사상 세 개의 덩어리 양성과 신호 특징 하나를 만든다."""
    # 격자 중심과 사상별 원형 양성 덩어리를 만든다
    rng = np.random.default_rng(seed)
    xs, ys = np.meshgrid(np.arange(60) * 100.0 + 50, np.arange(60) * 100.0 + 50)
    points = np.column_stack([xs.ravel(), ys.ravel()])
    centres = [(1000, 1000), (5000, 1500), (3000, 5000)]
    events = np.column_stack([np.hypot(*(points - c).T) < 300 for c in centres])

    # 양성 근처일수록 큰 신호와 잡음 특징
    signal = -np.min([np.hypot(*(points - c).T) for c in centres], axis=0) + rng.normal(0, 200, len(points))
    X = np.column_stack([signal, rng.normal(size=len(points))])
    return points, events, X


def long_rows(values: dict[str, list[float]], n_units: int = 10, unit: str = "cell_gate",
              metric: str = "observed-label_auc") -> pd.DataFrame:
    """점수별 사상 값 목록을 evaluate 긴 표 모양으로 만든다 (사상 이름 e0, e1 …)."""
    rows = [{"score": s, "unit": unit, "stratum": "ALL", "storm": "ALL", "metric": metric, "value": v,
             "n_units": n_units, "test_event": f"e{i}", "role": "development"}
            for s, vals in values.items() for i, v in enumerate(vals)]
    return pd.DataFrame(rows)


class M3ConfigTest(unittest.TestCase):
    """설정 공간의 크기·순서·prespec 확인."""

    def test_grid_sizes_and_order(self):
        """전체 24·RF 6 설정이고 특징집합 → 모델군 → 후보 순서이며 고정 구성을 포함한다."""
        # 두 변형의 설정 목록을 만든다
        full, rf = grid(), grid(VARIANTS["nested_rf"])
        self.assertEqual((len(full), len(rf)), (24, 6))
        self.assertIn(FIXED_ID, [c["id"] for c in full])
        self.assertIn(FIXED_ID, [c["id"] for c in rf])
        self.assertEqual(full[0]["id"], config_id("ridge", "F0", {"C": 0.1}))
        self.assertEqual([c["feature_set"] for c in rf], ["F0", "F0", "F1", "F1", "F2", "F2"])
        self.assertEqual(rf[3]["id"], FIXED_ID)

    def test_check_prespec(self):
        """코드 상수와 같은 prespec 은 통과하고, 후보나 동결 선택이 다르면 멈춘다."""
        # 코드 상수로 prespec 모양을 만든다
        good = {"features": FEATURES, "candidates": CANDIDATES, "fixed_parameters": FIXED_PARAMS,
                "selection": {"model": "random_forest", "feature_set": "F1",
                              "parameters": FIXED_PARAMS["random_forest"] | {"max_depth": 4, "min_samples_leaf": 400}}}
        bad_grid = good | {"candidates": CANDIDATES | {"ridge": [{"C": 10.0}]}}
        bad_pick = good | {"selection": good["selection"] | {"feature_set": "F0"}}

        # 임시 파일로 세 경우를 확인한다
        with tempfile.TemporaryDirectory() as tmp:
            for name, value in (("good", good), ("grid", bad_grid), ("pick", bad_pick)):
                path = Path(tmp) / f"{name}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                if name == "good":
                    self.assertEqual(check_prespec(path)["selection"]["feature_set"], "F1")
                else:
                    with self.assertRaises(ValueError):
                        check_prespec(path)


class M3SelectTest(unittest.TestCase):
    """이전 사상 LOEO 분할·채점·순위."""

    def test_splits_need_two_events(self):
        """이전 사상이 하나면 선택 불가로 멈춘다."""
        points, events, _ = synthetic()
        with self.assertRaises(ValueError):
            loeo_splits(points, events[:, :1], ["a"])

    def test_splits_exclude_held_positives_and_test_rows(self):
        """뺀 사상 양성은 어느 학습 부분에도 없고, 부분마다 학습·시험이 겹치지 않는다."""
        # 두 사상만 이전 사상으로 준다 (세 번째 사상 라벨은 넘기지 않는다)
        points, events, _ = synthetic()
        splits = loeo_splits(points, events[:, :2], ["a", "b"])
        self.assertEqual([f.name for f, _ in splits], ["a", "b"])
        for i, (fold, parts) in enumerate(splits):
            held = np.flatnonzero(events[:, i])
            self.assertEqual(set(fold.test[fold.test_y]), set(held))
            for part in parts:
                self.assertFalse(np.intersect1d(part.train, held).size)
                self.assertFalse(np.intersect1d(part.train, part.test).size)

    def test_future_positive_is_negative(self):
        """넘기지 않은 사상의 양성 격자는 학습 라벨에서 음성이다."""
        # 세 번째 사상에만 양성인 격자는 두 사상 LOEO 의 학습 부분에서 음성이어야 한다
        points, events, _ = synthetic()
        future_only = np.flatnonzero(events[:, 2] & ~events[:, :2].any(axis=1))
        for fold, parts in loeo_splits(points, events[:, :2], ["a", "b"]):
            for part in parts:
                in_train = np.isin(part.train, future_only)
                self.assertFalse(part.train_y[in_train].any())

    def test_config_loeo_scores_signal(self):
        """신호 특징으로 학습한 RF 는 뺀 사상마다 격자 AUC 가 0.8 을 넘는다."""
        # 세 사상 LOEO 에서 작은 RF 설정을 채점한다
        points, events, X = synthetic()
        splits = loeo_splits(points, events, ["a", "b", "c"])
        rows = config_loeo(X, points, splits, "random_forest", {"max_depth": 2, "min_samples_leaf": 20})
        self.assertEqual([r["held_event"] for r in rows], ["a", "b", "c"])
        for r in rows:
            self.assertGreater(r["grid_auc"], 0.8)
            self.assertEqual(r["n_positive"], int(events[:, "abc".index(r["held_event"])].sum()))

    def test_rank_ties_follow_declaration(self):
        """평균이 같으면 선언 순서가 앞선 설정이 이긴다."""
        # 세 설정 중 둘이 같은 평균을 갖는다
        table = pd.DataFrame({"config": ["x", "x", "y", "y", "z", "z"],
                              "cluster_auc": [0.7, 0.9, 0.6, 0.6, 0.8, 0.8]})
        ranking = rank_configs(table, ["z", "x", "y"])
        self.assertEqual(ranking["config"].tolist(), ["z", "x", "y"])
        ranking = rank_configs(table, ["x", "z", "y"])
        self.assertEqual(ranking["config"].tolist(), ["x", "z", "y"])
        self.assertEqual(ranking["rank"].tolist(), [1, 2, 3])

    def test_select_for_prior_variants(self):
        """변형별 순위표는 해당 모델군 설정만 담는다."""
        # 합성 자료를 사상 연도 라벨로 바꾸고 ridge·RF 두 설정만 준다
        points, events, X = synthetic()
        labels = {2001: events[:, 0], 2002: events[:, 1]}
        configs = [{"id": "ridge|F0|C=1.0", "model": "ridge", "feature_set": "F0", "params": {"C": 1.0}},
                   {"id": "random_forest|F0|d2", "model": "random_forest", "feature_set": "F0",
                    "params": {"max_depth": 2, "min_samples_leaf": 20}}]
        table, rankings = select_for_prior({"F0": X}, points, labels, (2001, 2002), configs,
                                           {"rf": ("random_forest",), "all": ("ridge", "random_forest")})
        self.assertEqual(len(table), 4)
        self.assertEqual(rankings["rf"]["config"].tolist(), ["random_forest|F0|d2"])
        self.assertEqual(len(rankings["all"]), 2)


class M3DecisionTest(unittest.TestCase):
    """판정 규칙·M1 재확인·재현 비교."""

    def test_optimism_margin(self):
        """중첩 중앙값이 고정 − 0.02 이상이면 낙관 아님, 미만이면 낙관이다."""
        # 차이가 정확히 0.02 인 경우와 0.03 인 경우
        close = long_rows({"nested_rf": [0.60, 0.70, 0.80], "rf_F1_wf": [0.62, 0.72, 0.82], "slope_neg": [0.7] * 3})
        far = long_rows({"nested_rf": [0.60, 0.70, 0.80], "rf_F1_wf": [0.63, 0.73, 0.83], "slope_neg": [0.7] * 3})
        self.assertEqual(D.decide(close)["verdict"], D.NOT_OPTIMISTIC)
        self.assertEqual(D.decide(far)["verdict"], D.OPTIMISTIC)
        self.assertAlmostEqual(D.decide(far)["primary"]["median_paired_diff"], 0.03)

    def test_nested_higher_flag(self):
        """중첩이 0.02 넘게 높으면 따로 표시한다."""
        high = long_rows({"nested_rf": [0.70, 0.80, 0.90], "rf_F1_wf": [0.60, 0.70, 0.80]})
        primary = D.decide(high)["primary"]
        self.assertEqual(primary["verdict"], D.NOT_OPTIMISTIC)
        self.assertTrue(primary["nested_higher_by_margin"])

    def test_m1_recheck_uses_e_nest(self):
        """M1 재확인은 E_nest 사상만 쓰고, 경사 ≥ 중첩 − 0.02 이면 유지다."""
        # e3 는 중첩 점수가 없어 E_nest 밖이다 (경사 값이 커도 영향이 없어야 한다)
        long = long_rows({"nested_rf": [0.80, 0.80, 0.80], "rf_F1_wf": [0.80, 0.80, 0.80],
                          "slope_neg": [0.70, 0.70, 0.70, 0.99]})
        result = D.decide(long)
        self.assertEqual(result["E_nest"], ["e0", "e1", "e2"])
        self.assertEqual(result["m1_recheck"]["slope_vs_nested"]["verdict"], D.M1_DEPENDS)
        long.loc[long["score"] == "slope_neg", "value"] = 0.79
        self.assertEqual(D.decide(long)["m1_recheck"]["slope_vs_nested"]["verdict"], D.M1_HOLDS)

    def test_match_reference(self):
        """같은 표는 통과하고, 값 차이·NaN 불일치·기준 누락은 실패한다."""
        # 기준 표와 세 가지 변형을 만든다
        ref = long_rows({"rf_F1_wf": [0.6, np.nan, 0.8], "slope_neg": [0.5, 0.5, 0.5]})
        self.assertTrue(match_reference(ref, ref, ("rf_F1_wf", "slope_neg"))["passes"])
        shifted = ref.assign(value=ref["value"] + 1e-6)
        self.assertFalse(match_reference(shifted, ref, ("rf_F1_wf",))["passes"])
        filled = ref.fillna(0.7)
        self.assertEqual(match_reference(filled, ref, ("rf_F1_wf",))["n_nan_mismatch"], 1)
        extra = pd.concat([ref, ref.iloc[[0]].assign(test_event="e9")])
        self.assertEqual(match_reference(extra, ref, ("rf_F1_wf",))["n_missing_in_reference"], 1)

        # units 를 주면 그 단위 행만 비교한다
        mixed = pd.concat([ref, long_rows({"rf_F1_wf": [0.1]}, unit="object")])
        moved = pd.concat([ref, long_rows({"rf_F1_wf": [0.9]}, unit="object")])
        self.assertFalse(match_reference(moved, mixed, ("rf_F1_wf",))["passes"])
        self.assertTrue(match_reference(moved, mixed, ("rf_F1_wf",), units=("cell_gate",))["passes"])

    def test_status_and_reexport(self):
        """이전 사상 수별 상태와 m1_scores 의 재학습 이름 유지."""
        self.assertEqual([status(()), status((2006,)), status((2006, 2012))], ["학습 불가", "선택 불가", "선택"])
        self.assertIs(m1_scores.trained_before, prior_fit.trained_before)
        self.assertIs(m1_scores.prior_years, prior_fit.prior_years)


if __name__ == "__main__":
    unittest.main()
