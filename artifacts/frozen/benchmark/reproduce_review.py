"""보존한 v1과 수정 코드를 같은 개발·합성 자료로 비교한다."""

import json
import os
import runpy
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point, box

from src.models.folds import loeo_groups, past_flood_score


output = Path('.omc/benchmark')
old = runpy.run_path(str(output / 'v1/source/src/models/folds.py'))
layer = gpd.read_file('data/processed/layers/layer1_flood.gpkg').sort_values('grid_id')
centers = layer.geometry.centroid
points = np.column_stack([centers.x, centers.y])
events = layer[[f'trace_ev_{year}' for year in (2006, 2012, 2014, 2016, 2019, 2025)]].to_numpy(bool)
held = events[:, 1]
print('RV1.1 before:', 'holdout_read=', json.loads((output / 'v1/prespec.json').read_text())['holdout_read'])
print('RV1.1 after:', 'CHANGWON_HOLDOUT_TESTS_present=', 'CHANGWON_HOLDOUT_TESTS' in os.environ,
      'test_module=tests.test_benchmark')
print('RV1.2 exact review diagnostic:',
      np.unique(old['block_groups'](points, events.any(axis=1))).size,
      np.unique(old['block_groups'](points, (~held) & events.any(axis=1))).size)
changed = events.copy()
changed[:, 1] = False
before_a = old['block_groups'](points, events.any(axis=1))
before_b = old['block_groups'](points, changed.any(axis=1))
after_a, background_a = loeo_groups(points, events, 1)
after_b, background_b = loeo_groups(points, changed, 1)
print('RV1.2 before: changed_group_rows=', int((before_a != before_b).sum()))
print('RV1.2 after: changed_group_rows=', int((after_a != after_b).sum()),
      'changed_background_rows=', int((background_a != background_b).sum()))
assert np.array_equal(after_a, after_b) and np.array_equal(background_a, background_b)
points = np.array([[50., 50.], [150., 50.]])
polygon = box(0, 0, 100, 100)
traces = gpd.GeoDataFrame({'event_year': ['2006'], 'role': ['development']}, geometry=[polygon], crs=5179)
before = old['past_flood_score'](points, np.array([0]), np.array([True]), np.array([1]))[0]
after = past_flood_score(points, traces, np.array([1]), ['2006'])[0]
inside = past_flood_score(points, traces, np.array([0]), ['2006'])[0]
expected = -Point(points[1]).distance(polygon)
print('RV1.3 before:', 'center_score', before, 'polygon_score', expected)
print('RV1.3 after:', 'past_flood', after, 'polygon_score', expected, 'inside', inside)
assert after == expected == -50 and inside == 0
