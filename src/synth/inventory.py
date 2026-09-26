"""가상 침수 객체 인벤토리: 절단 크기 분포·사상별 객체 수·타원 폴리곤 배치 (docs/q1/M4S_protocol.md §1.2~§1.4)."""

from __future__ import annotations

import numpy as np

AREA_MIN = 50.0
AREA_MAX = 1e7
ASPECT = (1.0, 3.0)
N_VERTEX = 32
EVENT_SIGMA = 1.5
POLYGON_UNIT_AREA = N_VERTEX / 2 * np.sin(2 * np.pi / N_VERTEX)


def draw_areas(rng: np.random.Generator, n: int, dist: str, median: float, shape: float) -> tuple[np.ndarray, np.ndarray]:
    """[50 m², 10 km²] 로 절단한 분포에서 면적과 생성 분포 기준 표준화 로그 면적 ζ 를 뽑는다."""
    # 분포마다 한 번에 뽑는 함수와 ζ 변환을 정한다
    if dist == "lognormal":
        draw = lambda k: np.exp(np.log(median) + shape * rng.standard_normal(k))
        zeta = lambda a: (np.log(a) - np.log(median)) / shape
    elif dist == "pareto":
        x_m = median * 2.0 ** (-1.0 / shape)
        draw = lambda k: x_m * (1.0 - rng.random(k)) ** (-1.0 / shape)
        zeta = lambda a: shape * np.log(a / x_m) - 1.0
    else:
        raise ValueError(f"알 수 없는 크기 분포: {dist}")

    # 범위 밖 값은 범위 안에 들 때까지 그 자리만 다시 뽑는다
    area = draw(n)
    bad = (area < AREA_MIN) | (area > AREA_MAX)
    while bad.any():
        area[bad] = draw(int(bad.sum()))
        bad = (area < AREA_MIN) | (area > AREA_MAX)
    return area, zeta(area)


def event_counts(rng: np.random.Generator, n_events: int, n_mean: int, mode: str) -> np.ndarray:
    """사상별 객체 수: equal 은 모두 n̄, skewed 는 LogNormal(0, 1.5) 배율로 총 E·n̄ 를 나눈다 (최소 1)."""
    # 같은 수 또는 배율 비례 반올림
    if mode == "equal":
        return np.full(n_events, int(n_mean))
    if mode == "skewed":
        m = np.exp(EVENT_SIGMA * rng.standard_normal(n_events))
        return np.maximum(1, np.round(n_events * n_mean * m / m.sum())).astype(int)
    raise ValueError(f"알 수 없는 사상별 객체 수 방식: {mode}")


def ellipses(rng: np.random.Generator, area: np.ndarray, box: tuple[float, float, float, float]):
    """넓이가 정확히 area 인 32각 타원(종횡비 U(1,3), 방향 U[0°,180°))을 장반축 원이 영역 안에 들도록 놓는다."""
    import shapely

    # 32각형 넓이 상수로 반축을 정해 다각형 넓이를 정확히 맞춘다
    n = len(area)
    ratio = rng.uniform(*ASPECT, n)
    theta = rng.uniform(0.0, np.pi, n)
    major = np.sqrt(area * ratio / POLYGON_UNIT_AREA)
    minor = np.sqrt(area / (ratio * POLYGON_UNIT_AREA))

    # 장반축만큼 안쪽 영역에서 중심을 뽑는다
    xmin, ymin, xmax, ymax = box
    cx = rng.uniform(xmin + major, xmax - major)
    cy = rng.uniform(ymin + major, ymax - major)

    # 단위원 꼭짓점(buffer(quad_segs=8) 와 같은 32각형)을 늘이고 돌리고 옮긴다
    t = 2 * np.pi * np.arange(N_VERTEX + 1) / N_VERTEX
    u, v = major[:, None] * np.cos(t), minor[:, None] * np.sin(t)
    c, s = np.cos(theta)[:, None], np.sin(theta)[:, None]
    coords = np.stack([cx[:, None] + c * u - s * v, cy[:, None] + s * u + c * v], axis=-1)
    return shapely.polygons(coords)


def inventory(rng: np.random.Generator, scenario, box: tuple[float, float, float, float]):
    """시나리오 하나의 객체 표: 사상 번호·storm_id·object_id·면적·ζ·타원 폴리곤."""
    import geopandas as gpd

    # 사상별 객체 수를 정하고 사상마다 면적을 뽑는다
    counts = event_counts(rng, scenario.n_events, scenario.n_obj, scenario.counts)
    event = np.repeat(np.arange(len(counts)), counts)
    parts = [draw_areas(rng, int(k), scenario.dist, scenario.median, scenario.shape) for k in counts]
    area = np.concatenate([p[0] for p in parts])
    zeta = np.concatenate([p[1] for p in parts])

    # 모양과 위치를 뽑아 객체 표를 만든다
    geometry = ellipses(rng, area, box)
    return gpd.GeoDataFrame({"event": event, "storm_id": [f"e{e}" for e in event],
                             "object_id": [f"o{k}" for k in range(len(area))], "area_m2": area, "zeta": zeta},
                            geometry=geometry, crs="EPSG:5179")
