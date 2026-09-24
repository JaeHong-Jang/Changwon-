"""사전 게이트가 기존 격자 지표와 결측 처리 규칙을 따르는지 검증한다."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from src.data import layers as L
from src.models.gates import GATE, gate


class GateTest(unittest.TestCase):
    """합성 라벨과 점수로 게이트의 계산·예외 분기를 검사한다."""

    def test_matches_existing_auc_and_capture(self):
        """격자 AUC와 상위 20% 포착률에 기존 함수의 값을 쓴다."""
        # 양성·음성이 섞인 다섯 격자와 고정 구간 결과를 준비한다.
        labels = np.array([True, False, True, False, False])
        scores = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
        points = np.column_stack([np.arange(5), np.zeros(5)])
        ci = {"ci95": [0.1, 0.9], "auc_cluster_weighted": 0.6,
              "ci95_cluster_weighted": [0.2, 0.8], "n_cluster": 3, "n_boot": 4}

        # 게이트 결과와 기존 지표 함수의 값을 직접 비교한다.
        with patch("src.data.uncertainty.cluster_bootstrap_auc", return_value=ci):
            actual = gate(labels, scores, points)
        auc = L.roc_auc(labels, scores)
        capture = L.top_share_lift(labels, scores, 0.20)["capture_rate"]
        self.assertEqual(actual["auc_cell"], round(auc, 4))
        self.assertEqual(actual["top20_capture"], capture)
        self.assertEqual(actual["passes_auc"], auc >= GATE["auc_min"])
        self.assertEqual(actual["passes_capture"], capture >= GATE["top20_capture_min"])

    def test_nonfinite_scores_excluded_from_auc_and_bootstrap(self):
        """비유한 점수는 AUC와 재표본 입력에서 제외하고 개수를 기록한다."""
        # 결측·무한 점수를 포함하되 유효한 양성·음성을 남긴다.
        labels = np.array([True, False, True, False, False])
        scores = np.array([0.9, 0.8, np.nan, np.inf, 0.1])
        points = np.column_stack([np.arange(5), np.zeros(5)])
        ci = {"ci95": [0.1, 0.9], "auc_cluster_weighted": 0.6,
              "ci95_cluster_weighted": [0.2, 0.8], "n_cluster": 3, "n_boot": 4}

        # 재표본 함수가 유한한 행만 받고 AUC가 같은 행에서 계산되는지 확인한다.
        with patch("src.data.uncertainty.cluster_bootstrap_auc", return_value=ci) as bootstrap:
            actual = gate(labels, scores, points)
        self.assertEqual(actual["n_nonfinite"], 2)
        self.assertEqual(actual["auc_cell"], round(L.roc_auc(labels, scores), 4))
        np.testing.assert_array_equal(bootstrap.call_args.args[0], labels[np.isfinite(scores)])
        np.testing.assert_array_equal(bootstrap.call_args.args[1], scores[np.isfinite(scores)])

    def test_unevaluable_without_both_classes(self):
        """유효한 점수에 한 클래스만 남으면 평가 불가 이유를 반환한다."""
        # 양성의 점수만 결측으로 만들어 유효 행을 음성 하나로 제한한다.
        labels = np.array([True, False])
        scores = np.array([np.nan, 0.2])
        points = np.array([[0., 0.], [1., 0.]])

        # 재표본을 실행하지 않고 기존 평가 불가 키 구조를 반환하는지 확인한다.
        with patch("src.data.uncertainty.cluster_bootstrap_auc") as bootstrap:
            actual = gate(labels, scores, points)
        self.assertEqual(actual, {"evaluable": False, "reason": "유효 표본에 양성 또는 음성이 없다",
                                  "n_nonfinite": 1})
        bootstrap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
