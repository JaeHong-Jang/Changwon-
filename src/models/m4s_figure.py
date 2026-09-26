"""M4S 그림: 묶음 A 의 σ × β 격자에서 공식 Δ* 와 soft·f10 실현 차이 중앙값(칸 글자 P10)을 나란히 그린다."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

NEGATIVE = "#e34948"
MIDPOINT = "#f0efec"
POSITIVE = "#2a78d6"
INK = "#1a1a19"
LIMIT = 0.4


def gap_map(summary: pd.DataFrame, path: Path) -> None:
    """행 = 객체 수(200, 30), 열 = Δ*·soft·f10 인 발산 색 격자 그림을 저장한다."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    # 빨강(격자 < 객체)–회색–파랑(격자 > 객체) 발산 색과 칸 배치를 정한다
    cmap = LinearSegmentedColormap.from_list("gap", [NEGATIVE, MIDPOINT, POSITIVE])
    a = summary[summary["block"] == "A"]
    sigmas, betas = sorted(a["shape"].unique()), sorted(a["beta"].unique())
    fig, axes = plt.subplots(2, 3, figsize=(12, 7.2), constrained_layout=True)

    # 칸마다 값과 (실현 차이면) P10 을 적는다
    for r, n in enumerate((200, 30)):
        for c, (title, rule) in enumerate((("Δ* (formula, area weights)", None), ("soft: median gap", "soft"),
                                           ("f10: median gap", "f10"))):
            ax = axes[r, c]
            part = a[(a["n_obj"] == n) & (a["rule"] == (rule or "soft"))]
            col = "delta_star" if rule is None else "gap_median"
            grid = part.pivot(index="beta", columns="shape", values=col).reindex(index=betas, columns=sigmas)
            p10 = part.pivot(index="beta", columns="shape", values="p10").reindex(index=betas, columns=sigmas)
            image = ax.imshow(grid.to_numpy(), cmap=cmap, vmin=-LIMIT, vmax=LIMIT, origin="lower", aspect="auto")
            for i in range(len(betas)):
                for j in range(len(sigmas)):
                    value = grid.iat[i, j]
                    text = f"{value:+.2f}" if rule is None else f"{value:+.2f}\nP10 {p10.iat[i, j]:.2f}"
                    ax.text(j, i, text, ha="center", va="center", fontsize=7.5, color=INK)
            ax.set_xticks(range(len(sigmas)), [f"{s:g}" for s in sigmas])
            ax.set_yticks(range(len(betas)), [f"{b:+g}" for b in betas])
            ax.set_xlabel("size dispersion σ (sd of ln area)")
            ax.set_ylabel("size–detectability coupling β")
            ax.set_title(f"{title} — n = {n}", fontsize=10, color=INK)
            for spine in ax.spines.values():
                spine.set_visible(False)

    # 공통 색 막대와 제목을 붙여 저장한다
    fig.colorbar(image, ax=axes, shrink=0.6, label="grid AUC − object AUC")
    fig.suptitle("M4S block A: grid–object AUC gap (single event, median area 5,000 m², μ0 = 0.95)", color=INK)
    fig.savefig(path, dpi=150)
    plt.close(fig)
