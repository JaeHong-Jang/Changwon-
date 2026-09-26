"""M4 굵은 격자·라벨 규칙·가중 AUC·분해·생존·판정 단위 검사 (합성 자료, 홀드아웃 없음)."""

import unittest

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from src.data import layers
from src.data.coarse_grid import block_any, block_mean, make_blocks
from src.data.label_rules import RULES, positive_mass
from src.data.trace_footprint import center_inside, coarsen, footprint
from src.data.validation import object_auc
from src.data.validation.decomposition import decompose, object_terms
from src.data.validation.weighted_auc import weighted_auc
from src.models import m4_decision as D
from src.models.m4_metrics import score_config, sklearn_auc
from src.models.m4_survival import survives


def lattice(nx: int = 6, ny: int = 4, x0: float = 1_000_200.0, y0: float = 1_800_000.0) -> gpd.GeoDataFrame:
    """좌하단이 200 m 배수에 정렬된 nx × ny 개 100 m 칸 (행 우선)."""
    # 칸 번호는 아래 행부터 왼쪽→오른쪽 순서다
    cells = [box(x0 + 100 * i, y0 + 100 * j, x0 + 100 * (i + 1), y0 + 100 * (j + 1)) for j in range(ny) for i in range(nx)]
    return gpd.GeoDataFrame({"grid_id": np.arange(len(cells))}, geometry=cells, crs="EPSG:5179")


def traces(*geoms) -> gpd.GeoDataFrame:
    """사상 폴리곤 묶음 (storm_id·object_id 포함)."""
    return gpd.GeoDataFrame({"storm_id": "s", "object_id": [f"o{i}" for i in range(len(geoms))]},
                            geometry=list(geoms), crs="EPSG:5179")


class CoarseGridTest(unittest.TestCase):
    """굵은 칸 번호·면적·중심점·평균 집계."""

    def test_blocks_area_centroid(self):
        """200 m 칸은 4개 100 m 칸을 묶고, 부분 칸의 중심점은 구성 칸 중심점 평균이다."""
        # 6×4 격자에서 한 칸을 빼 부분 칸을 만든다
        grid = lattice().drop(index=0).reset_index(drop=True)
        b = make_blocks(grid, 200)
        self.assertEqual(b.n, 6)
        self.assertEqual(sorted(np.bincount(b.code).tolist()), [3, 4, 4, 4, 4, 4])
        partial = np.flatnonzero(b.area == 3e4)[0]
        members = grid.geometry.centroid[b.code == partial]
        self.assertAlmostEqual(b.x[partial], members.x.mean())
        self.assertAlmostEqual(b.y[partial], members.y.mean())

    def test_100m_blocks_are_cells(self):
        """100 m 크기는 칸마다 굵은 칸 하나이고 평균 집계는 값을 바꾸지 않는다."""
        # 칸 수와 값 보존을 본다
        grid = lattice()
        b = make_blocks(grid, 100)
        self.assertEqual(b.n, len(grid))
        v = np.arange(len(grid), dtype=float)
        np.testing.assert_array_equal(block_mean(v, b)[b.code], v)

    def test_block_mean_ignores_nan(self):
        """결측은 평균에서 빠지고 모두 결측이면 NaN 이다."""
        # 첫 200 m 칸 구성 값 중 하나만 유한하게 둔다
        grid = lattice(2, 2)
        b = make_blocks(grid, 200)
        self.assertEqual(block_mean(np.array([np.nan, 2.0, np.nan, 4.0]), b)[0], 3.0)
        self.assertTrue(np.isnan(block_mean(np.full(4, np.nan), b)[0]))
        self.assertTrue(block_any(np.array([False, False, True, False]), b)[0])

    def test_misaligned_size_rejected(self):
        """100 m 의 배수가 아닌 크기는 거부한다."""
        with self.assertRaises(ValueError):
            make_blocks(lattice(), 150)


class LabelRuleTest(unittest.TestCase):
    """겹침 면적·합집합·규칙별 양성 질량."""

    def setUp(self):
        """첫 칸 60%·둘째 칸 3% 를 덮는 폴리곤과, 첫 칸 안에서 겹치는 작은 폴리곤."""
        # 첫 행 칸 0(1_000_200~300), 칸 1(…300~400)
        self.grid = lattice(4, 2)
        x0, y0 = 1_000_200.0, 1_800_000.0
        self.polys = traces(box(x0, y0, x0 + 105, y0 + 60), box(x0 + 10, y0 + 10, x0 + 20, y0 + 20))
        self.fp = footprint(self.grid, self.polys)

    def test_union_counts_overlap_once(self):
        """겹친 두 폴리곤의 칸 침수 면적은 합집합 면적이다."""
        # 큰 폴리곤이 작은 폴리곤을 덮으므로 칸 0 침수 면적 = 100 × 60
        self.assertAlmostEqual(self.fp.flooded[0], 100 * 60, places=6)
        self.assertAlmostEqual(self.fp.flooded[1], 5 * 60, places=6)

    def test_threshold_rules_are_strict(self):
        """any 는 칸 1(3%)을 켜고 f10 은 끄며, soft 는 비율 그대로다."""
        # 칸 1 침수 비율 = 300 / 10000 = 0.03
        self.assertEqual(positive_mass("any", self.fp)[1], 1.0)
        self.assertEqual(positive_mass("f01", self.fp)[1], 1.0)
        self.assertEqual(positive_mass("f10", self.fp)[1], 0.0)
        self.assertEqual(positive_mass("f50", self.fp)[0], 1.0)
        self.assertAlmostEqual(positive_mass("soft", self.fp)[1], 0.03)
        exact = footprint(self.grid, traces(box(1_000_200.0, 1_800_000.0, 1_000_300.0, 1_800_010.0)))
        self.assertEqual(positive_mass("f10", exact)[0], 0.0)

    def test_center_and_rep_point(self):
        """중심점 규칙은 중심이 폴리곤 안인 칸만, 대표점 규칙은 폴리곤마다 대표점 칸만 켠다."""
        # 칸 0 중심(50, 50)은 큰 폴리곤(높이 60) 안이다
        c = self.grid.geometry.centroid
        inside = center_inside(self.polys, c.x.to_numpy(), c.y.to_numpy())
        np.testing.assert_array_equal(np.flatnonzero(positive_mass("center", self.fp, inside)), [0])
        self.assertEqual(set(np.flatnonzero(positive_mass("rep_point", self.fp))), {0})
        with self.assertRaises(ValueError):
            positive_mass("center", self.fp)

    def test_coarsen_sums_areas(self):
        """200 m 로 합치면 칸 0·1 이 한 칸이 되고 겹침·침수 면적이 더해진다."""
        # 두 폴리곤 모두 굵은 칸 하나에 들어간다
        b = make_blocks(self.grid, 200)
        fp = coarsen(self.fp, b)
        block = b.code[0]
        self.assertAlmostEqual(fp.flooded[block], 100 * 60 + 5 * 60, places=6)
        self.assertEqual(fp.n_obj, 2)
        self.assertTrue((fp.cell == block).all())
        self.assertAlmostEqual(positive_mass("soft", fp)[block], 6300 / 40000)
        self.assertTrue(set(RULES) >= {"any", "soft", "center", "rep_point"})


class WeightedAucTest(unittest.TestCase):
    """가중 AUC 두 경로와 분해 항등식."""

    def test_binary_matches_roc_auc(self):
        """이진 라벨의 가중 AUC 는 layers.roc_auc·sklearn 과 같다 (동점 포함)."""
        # 동점이 많은 정수 점수를 쓴다
        rng = np.random.default_rng(0)
        s = rng.integers(0, 5, 300).astype(float)
        y = rng.random(300) < 0.2
        self.assertAlmostEqual(weighted_auc(s, y.astype(float)), layers.roc_auc(y, s), places=12)
        self.assertAlmostEqual(sklearn_auc(s, y.astype(float)), layers.roc_auc(y, s), places=12)

    def test_soft_matches_pairwise_definition(self):
        """연성 AUC 는 Σ p_i q_j H(s_i − s_j) / (Σp Σq) 정의와 같다."""
        # 작은 표본에서 모든 쌍을 직접 더한다
        rng = np.random.default_rng(1)
        s = rng.integers(0, 4, 40).astype(float)
        p = np.where(rng.random(40) < 0.4, rng.random(40), 0.0)
        q = 1 - p
        h = (s[:, None] > s[None, :]) + 0.5 * (s[:, None] == s[None, :])
        direct = (p[:, None] * q[None, :] * h).sum() / (p.sum() * q.sum())
        self.assertAlmostEqual(weighted_auc(s, p), direct, places=12)
        self.assertAlmostEqual(sklearn_auc(s, p), direct, places=12)

    def test_nan_scores_are_dropped(self):
        """점수 결측 칸은 양성·음성 모두에서 빠진다."""
        # 결측 칸이 양성이어도 AUC 가 바뀌지 않는다
        s = np.array([3.0, 2.0, 1.0, np.nan])
        p = np.array([1.0, 0.0, 0.0, 1.0])
        self.assertEqual(weighted_auc(s, p), 1.0)


class DecompositionTest(unittest.TestCase):
    """격자 AUC = 객체 기여의 가중평균, 객체 AUC 와의 세 항 분해."""

    def setUp(self):
        """무작위 폴리곤 여섯 개와 점수가 있는 8×6 격자."""
        # 크기가 다른 폴리곤을 흩뿌린다
        rng = np.random.default_rng(3)
        self.grid = lattice(8, 6)
        x0, y0 = 1_000_200.0, 1_800_000.0
        geoms = []
        for _ in range(6):
            cx, cy, r = x0 + rng.uniform(0, 800), y0 + rng.uniform(0, 600), rng.uniform(5, 150)
            geoms.append(box(cx - r, cy - r, cx + r, cy + r))
        self.polys = traces(*geoms)
        self.score = rng.normal(size=len(self.grid))
        self.score[5] = np.nan
        self.fp = footprint(self.grid, self.polys)
        self.bg = self.fp.flooded == 0

    def test_identity_all_rules_and_sizes(self):
        """모든 규칙·크기에서 Σ w_k A_k 가 직접 계산한 격자 AUC 와 1e-12 안에서 같다."""
        # 크기 100·200·400 m 와 8개 규칙을 모두 돈다
        for size in (100, 200, 400):
            b = make_blocks(self.grid, size)
            fp = coarsen(self.fp, b)
            s = block_mean(self.score, b)
            bg = ~block_any(~self.bg, b)
            inside = center_inside(self.polys, b.x, b.y)
            for rule in RULES:
                p = positive_mass(rule, fp, inside)
                if not (p > 0).any():
                    continue
                parts = decompose(object_terms(s, p, fp, bg))
                self.assertAlmostEqual(parts["auc_from_objects"], weighted_auc(s, p), places=12, msg=(size, rule))
                total = parts["term_size_weight"] + parts["term_within_object"] + parts["term_erasure"]
                self.assertAlmostEqual(total, parts["auc_from_objects"] - parts["object_auc"], places=12)

    def test_object_auc_matches_validation(self):
        """100 m 객체 값 평균은 validation.object_auc 와 같다."""
        # 같은 비접촉 배경을 준다
        terms = object_terms(self.score, positive_mass("f10", self.fp), self.fp, self.bg)
        expected = object_auc(self.score, self.grid, self.polys, background_mask=self.bg)
        np.testing.assert_allclose(terms["At"], expected["per_object"], equal_nan=True)

    def test_score_config_rows(self):
        """score_config 는 점수마다 네 지표 행과 분해 행을 만들고 항등식을 통과한다."""
        # f10 규칙과 두 점수로 채점한다
        b = make_blocks(self.grid, 100)
        fp = coarsen(self.fp, b)
        p = positive_mass("any", fp)
        metrics, decomposition, objects = score_config({"a": block_mean(self.score, b), "b": -block_mean(self.score, b)},
                                                       p, p, fp, b, ~block_any(~self.bg, b))
        self.assertEqual(len(metrics), 8)
        self.assertEqual({d["score"] for d in decomposition}, {"a", "b"})
        self.assertLessEqual(max(d["identity_abs_diff"] for d in decomposition), 1e-9)
        self.assertEqual(len(objects), 2 * fp.n_obj)

    def test_survival_small_polygon(self):
        """칸의 5% 만 덮는 폴리곤은 f10 에서 사라지고 any 에서 산다."""
        # 칸 하나 안의 작은 정사각형
        grid = lattice(2, 2)
        fp = footprint(grid, traces(box(1_000_210.0, 1_800_010.0, 1_000_210.0 + 22.4, 1_800_010.0 + 22.4)))
        self.assertFalse(survives(positive_mass("f10", fp), fp)[0])
        self.assertTrue(survives(positive_mass("any", fp), fp)[0])
        self.assertTrue(survives(positive_mass("soft", fp), fp)[0])


class DecisionTest(unittest.TestCase):
    """게이트 여유·뒤집힘·주 판정."""

    def long_table(self, l1_auc: dict, l1_cap: dict, n_pos: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
        """합동 홀드아웃과 사상 둘에 대해 L1 만 설정별 값이 다르고 나머지 점수는 0.8 인 긴 표."""
        # 설정은 참조(f10,100)·any 100·f10 1000 세 개
        rows, events = [], []
        for rule, size in (("f10", 100), ("any", 100), ("f10", 1000)):
            for event in ("HOLDOUT_ALL", "e1", "e2"):
                role = "holdout_pooled" if event == "HOLDOUT_ALL" else "development"
                events.append({"test_event": event, "rule": rule, "size_m": size, "n_pos_cells": n_pos})
                for score in D.SCORES:
                    auc = l1_auc[(rule, size)] if score == "L1" else 0.8
                    cap = l1_cap[(rule, size)] if score == "L1" else 0.6
                    for metric, value in (("cell_auc", auc), ("capture_0.2", cap), ("object_auc", 0.7)):
                        rows.append({"test_event": event, "role": role, "rule": rule, "size_m": size,
                                     "score": score, "metric": metric, "value": value, "n_units": n_pos})
        return pd.DataFrame(rows), pd.DataFrame(events)

    def test_margin(self):
        """여유는 두 게이트 여유 중 작은 값이다."""
        self.assertAlmostEqual(D.gate_margin(0.75, 0.52), 0.02)
        self.assertAlmostEqual(D.gate_margin(0.60, 0.90), -0.10)

    def test_conventional_material_flip_supports(self):
        """any·100 m 에서 L1 이 여유 0.02 이상으로 통과하면 C-c 지지다."""
        # 참조에서 L1 탈락(−0.26), any 에서 통과(+0.05)
        long, events = self.long_table({("f10", 100): 0.44, ("any", 100): 0.80, ("f10", 1000): 0.44},
                                       {("f10", 100): 0.07, ("any", 100): 0.55, ("f10", 1000): 0.07})
        table = D.verdict_table(long, events)
        self.assertTrue(D.decide(table)["verdict"].startswith("C-c 지지"))

    def test_boundary_flip_is_not_material(self):
        """여유가 0.02 미만인 뒤집힘은 실질 뒤집힘이 아니다."""
        # 참조 −0.01 → 크기 1000 m +0.01
        long, events = self.long_table({("f10", 100): 0.69, ("any", 100): 0.69, ("f10", 1000): 0.71},
                                       {("f10", 100): 0.60, ("any", 100): 0.60, ("f10", 1000): 0.60})
        table = D.verdict_table(long, events)
        row = table[(table["verdict"] == "V1") & (table["score"] == "L1") & (table["size_m"] == 1000)].iloc[0]
        self.assertTrue(row["flip"])
        self.assertFalse(row["material_flip"])
        self.assertTrue(D.decide(table)["verdict"].startswith("C-c 폐기"))

    def test_size_only_flip_is_partial(self):
        """굵은 격자에서만 실질 뒤집힘이 있으면 부분 지지다."""
        # 1000 m 에서만 L1 통과
        long, events = self.long_table({("f10", 100): 0.44, ("any", 100): 0.44, ("f10", 1000): 0.80},
                                       {("f10", 100): 0.07, ("any", 100): 0.07, ("f10", 1000): 0.60})
        table = D.verdict_table(long, events)
        self.assertTrue(D.decide(table)["verdict"].startswith("C-c 부분 지지"))
        self.assertEqual(set(table.loc[table["flip"], "config_class"]), {"size_only"})
        self.assertEqual({f["n_events"] for f in D.decide(table)["L1_material_flips"]}, {1, 2})

    def test_min_positive_cells_blocks_evaluation(self):
        """양성 칸이 5 미만이면 V1·V2 모두 평가하지 않는다."""
        # 모든 사상 양성 4칸
        long, events = self.long_table({k: 0.8 for k in (("f10", 100), ("any", 100), ("f10", 1000))},
                                       {k: 0.6 for k in (("f10", 100), ("any", 100), ("f10", 1000))}, n_pos=4)
        table = D.verdict_table(long, events)
        self.assertFalse(table["evaluable"].any())
        self.assertEqual(D.decide(table)["verdict"], "판정 불가")


if __name__ == "__main__":
    unittest.main()
