"""M4 객체 생존: 폴리곤이 겹친 칸 중 양성 칸이 하나라도 있는지와 면적·토지이용 구간별 생존율 (docs/q1/M4_protocol.md §5)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.trace_footprint import Footprint
from src.models.label_audit import AREA_BINS

AREA_LABELS = ["<500", "500-1k", "1k-5k", "5k-20k", ">=20k"]


def survives(p: np.ndarray, fp: Footprint) -> np.ndarray:
    """폴리곤마다 겹친(면적 > 0) 칸 중 양성 질량이 있는 칸이 하나라도 있으면 참."""
    # 겹침 쌍의 칸 양성 여부를 폴리곤별로 모은다
    hit = (np.asarray(p, dtype=float)[fp.cell] > 0) & (fp.area > 0)
    return np.bincount(fp.obj, weights=hit, minlength=fp.n_obj) > 0


def in_domain(fp: Footprint) -> np.ndarray:
    """폴리곤이 분석 영역과 면적 > 0 으로 겹치는지."""
    return np.bincount(fp.obj, weights=fp.area > 0, minlength=fp.n_obj) > 0


def area_bin(area_m2: np.ndarray) -> pd.Categorical:
    """label_audit 과 같은 폴리곤 면적 구간."""
    return pd.cut(np.asarray(area_m2, dtype=float), AREA_BINS, right=False, labels=AREA_LABELS)


def summarise(objects: pd.DataFrame) -> pd.DataFrame:
    """역할·규칙·크기별로 전체·면적 구간·토지이용 구간의 생존율을 센다 (분석 영역 밖 폴리곤은 분모에서 뺀다)."""
    # 영역 안 폴리곤만 남기고 세 가지 묶음 기준으로 생존율을 모은다
    inside = objects[objects["in_domain"]]
    keys = ["role_group", "rule", "size_m"]
    parts = [inside.assign(group="all", level="all"),
             inside.assign(group="area_bin", level=inside["area_bin"].astype(str)),
             inside.assign(group="land_class", level=inside["land_class"].astype(str))]
    table = pd.concat(parts, ignore_index=True).groupby(keys + ["group", "level"], sort=False).agg(
        n=("survive", "size"), n_survive=("survive", "sum"), median_area_m2=("area_m2", "median")).reset_index()
    table["survival"] = table["n_survive"] / table["n"]

    # 영역 밖 폴리곤 수를 역할별로 붙인다
    outside = objects[~objects["in_domain"]].groupby(keys).size().rename("n_outside_domain")
    return table.merge(outside.reset_index(), on=keys, how="left").fillna({"n_outside_domain": 0})
