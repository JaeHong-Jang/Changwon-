"""개발 전체 모형의 보고용 강수 시나리오 지도를 만든다."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.forecast.logit_prior import predict_raw

THRESHOLDS = [0.01, 0.05, 0.10, 0.20]
COLORS = ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"]
TITLE = "기록 침수 결합 확률(평가 아님) · 절차 v1.1"


def scenario_probability(params_M_fc24_all_dev, q_scenario, grid_ids, r12_values=(60, 110, 180)) -> pd.DataFrame:
    """고정 강수량별 사건 확률·격자 확률·등급을 반환한다."""
    # 공간 확률과 격자 ID의 길이와 확률 범위를 검증한다.
    q = np.asarray(q_scenario, float)
    ids = np.asarray(grid_ids)
    if q.ndim != 1 or len(q) != len(ids) or not np.isfinite(q).all() or ((q < 0) | (q > 1)).any():
        raise ValueError("시나리오 격자 점수가 유효하지 않다")

    # 각 강수 시나리오의 발생 확률과 결합 확률을 같은 격자 순서로 쌓는다.
    frames = []
    for rain in r12_values:
        p = float(predict_raw(params_M_fc24_all_dev, np.array([rain], float))[0])
        if not np.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("시나리오 발생 확률이 유효하지 않다")
        probability = p * q
        frames.append(pd.DataFrame({"grid_id": ids, "r12": rain, "p_event": p, "q": q,
                                    "P": probability, "grade": np.digitize(probability, THRESHOLDS)}))
    return pd.concat(frames, ignore_index=True)


def write_maps(frame: pd.DataFrame, grid_gpkg, out_dir) -> list[Path]:
    """EPSG:5179 격자 GeoPackage와 강수별 고정 색상 PNG를 저장한다."""
    # 공간·그림 라이브러리를 지도 저장 시점에 불러온다.
    import geopandas as gpd
    import matplotlib

    # 화면 환경 없이 지도 렌더링을 준비하고 입력 격자 좌표계를 검사한다.
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import Patch

    # 지도 좌표계와 출력 경로를 준비한다.
    grid = gpd.read_file(grid_gpkg) if isinstance(grid_gpkg, (str, Path)) else grid_gpkg
    if grid.crs is None or grid.crs.to_epsg() != 5179:
        raise ValueError("시나리오 격자는 EPSG:5179여야 한다")
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    korean_font = next((path for path in (Path("/mnt/c/Windows/Fonts/malgun.ttf"),
                                         Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf")) if path.exists()), None)
    title_font = FontProperties(fname=str(korean_font)) if korean_font else FontProperties()

    # 시나리오별 결합 결과를 격자와 일대일로 결합해 파일로 남긴다.
    cmap = ListedColormap(COLORS)
    norm = BoundaryNorm(np.arange(-0.5, 5.5, 1), cmap.N)
    for rain, rows in frame.groupby("r12", sort=True):
        merged = grid[["grid_id", "geometry"]].merge(rows, on="grid_id", how="left", validate="one_to_one")
        if merged["P"].isna().any():
            raise ValueError("지도에 빠진 격자 ID가 있다")
        geo = gpd.GeoDataFrame(merged, geometry="geometry", crs=grid.crs)
        gpkg = target / f"scenario_r12_{rain}.gpkg"
        geo.to_file(gpkg, driver="GPKG")
        paths.append(gpkg)

        # 고정 등급 색과 해석 제목·범례를 PNG에 명시한다.
        fig, ax = plt.subplots(figsize=(9, 9))
        geo.plot(column="grade", ax=ax, cmap=cmap, norm=norm, linewidth=0, legend=False)
        ax.set_title(f"{TITLE}\nr12max_fc = {rain} mm", fontproperties=title_font)
        ax.set_axis_off()
        labels = ["<0.01", "0.01–<0.05", "0.05–<0.10", "0.10–<0.20", "≥0.20"]
        ax.legend([Patch(facecolor=color) for color in COLORS], labels, title=TITLE,
                  loc="lower left", fontsize=8, title_fontproperties=title_font)
        png = target / f"scenario_r12_{rain}.png"
        fig.savefig(png, dpi=160, bbox_inches="tight")
        plt.close(fig)
        paths.append(png)
    return paths
