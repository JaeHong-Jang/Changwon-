from itertools import permutations
import unittest

import numpy as np

from src.data.explain import geometric_shapley
from src.data.layers import geometric_aggregate


class GeometricShapleyTest(unittest.TestCase):
    def setUp(self):
        self.background = np.array([[.05, .8, .2, .4], [.7, .2, .9, .6], [.3, .5, .4, 1.]])
        self.x = np.array([[.8, .7, .3, .5], [.1, .2, .8, .9]])
        self.weights = np.array([.1, .2, .3, .4])
        self.bounds = (.05, .9)

    def test_matches_direct_background_replacement_over_all_orders(self):
        expected = np.zeros_like(self.x)
        for row, x in enumerate(self.x):
            for order in permutations(range(4)):
                hybrid = self.background.copy()
                previous = geometric_aggregate(hybrid, self.weights).mean()
                for j in order:
                    hybrid[:, j] = x[j]
                    current = geometric_aggregate(hybrid, self.weights).mean()
                    expected[row, j] += (current - previous) / (24 * .85)
                    previous = current
        values, baseline = geometric_shapley(
            self.x, self.background, self.weights, output_bounds=self.bounds
        )
        np.testing.assert_allclose(values, expected, atol=1e-14)
        scores = (geometric_aggregate(self.x, self.weights) - .05) / .85
        np.testing.assert_allclose(baseline + values.sum(axis=1), scores, atol=1e-14)

    def test_zero_weight_has_zero_contribution(self):
        values, _ = geometric_shapley(
            self.x, self.background, [0, .2, .3, .5], output_bounds=self.bounds
        )
        np.testing.assert_allclose(values[:, 0], 0, atol=1e-14)

    def test_same_reference_and_observation_have_zero_contributions(self):
        values, _ = geometric_shapley(
            self.x[:1], self.x[:1], self.weights, output_bounds=self.bounds
        )
        np.testing.assert_allclose(values, 0, atol=1e-14)

    def test_invalid_inputs_fail(self):
        for bad in (np.zeros((1, 4)), np.full((1, 4), np.nan), np.ones((1, 3))):
            with self.assertRaises(ValueError):
                geometric_shapley(bad, self.background, self.weights, output_bounds=self.bounds)
        with self.assertRaises(ValueError):
            geometric_shapley(self.x, self.background, self.weights, output_bounds=(.5, .5))
        with self.assertRaises(ValueError):
            geometric_shapley(self.x, self.background[:0], self.weights, output_bounds=self.bounds)
        with self.assertRaises(ValueError):
            geometric_shapley(self.x, self.background, [.25, .25, .25, -.25], output_bounds=self.bounds)
        with self.assertRaises(ValueError):
            geometric_shapley(self.x, self.background, self.weights, output_bounds=(np.nan, 1))


if __name__ == "__main__":
    unittest.main()
