"""M2 숲 그림: 주요 점수의 사상별 격자 AUC·95% 구간과 개발·홀드아웃 통합(마름모·예측구간)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SCORES = [("slope_neg", "Slope only (−)"), ("hand_neg", "HAND, OSM (−)"), ("rf_F1_wf", "RF-F1, walk-forward"),
          ("L1", "L1 (frozen index)")]
COLORS = {"development": "#2a78d6", "holdout": "#eb6834"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d4"


def _diamond(ax, y: float, lo: float, mid: float, hi: float, color: str) -> None:
    """통합 평균·구간을 마름모로 그린다."""
    ax.fill([lo, mid, hi, mid], [y, y + 0.28, y, y - 0.28], color=color, lw=0, zorder=3)


def forest(effect_rows: pd.DataFrame, pooled: pd.DataFrame, path: Path, *, unit: str = "cell_gate",
           stratum: str = "ALL") -> None:
    """점수마다 한 칸: 포함 사상의 AUC 점·구간, 집합별 통합 마름모와 예측구간, 게이트 0.70 선."""
    # 화면 없는 백엔드로 그림 도구를 불러온다
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 칸 배치와 공통 축 범위를 정한다
    fig, axes = plt.subplots(1, len(SCORES), figsize=(3.1 * len(SCORES), 5.2), sharey=True)
    rows = effect_rows[(effect_rows["unit"] == unit) & (effect_rows["stratum"] == stratum) & effect_rows["included"]]
    main = pooled[(pooled["unit"] == unit) & (pooled["stratum"] == stratum) & (pooled["variant"] == "main")]
    order = list(dict.fromkeys(rows.sort_values(["role", "test_event"])["test_event"].astype(str)))
    labels = order + ["Pooled: development", "Pooled: holdout"]
    ypos = {name: len(labels) - i for i, name in enumerate(labels)}

    # 칸마다 사상 점·구간, 통합 마름모·예측구간, 게이트 선을 그린다
    for ax, (score, title) in zip(axes, SCORES):
        part = rows[rows["score"] == score]
        for r in part.itertuples():
            y = ypos[str(r.test_event)]
            ax.plot([r.ci_lo, r.ci_hi], [y, y], color=COLORS[r.role], lw=2, solid_capstyle="round", zorder=2)
            ax.plot(r.auc, y, "o", ms=6, color=COLORS[r.role], mec="white", mew=0.8, zorder=3)
        for set_name in ("development", "holdout"):
            p = main[(main["score"] == score) & (main["set"] == set_name)]
            if p.empty:
                continue
            p = p.iloc[0]
            y = ypos[f"Pooled: {set_name}"]
            if p["k"] >= 2:
                _diamond(ax, y, p["auc_ci_lo"], p["auc_mu"], p["auc_ci_hi"], COLORS[set_name])
            if np.isfinite(p["auc_pi_lo"]):
                ax.plot([p["auc_pi_lo"], p["auc_pi_hi"]], [y - 0.38, y - 0.38], color=COLORS[set_name], lw=1,
                        alpha=0.7)
            ax.text(0.305, y + 0.33, f"k={int(p['k'])}, I²={p['i2']:.0%}" if p["k"] >= 2 else f"k={int(p['k'])}",
                    fontsize=7, color=MUTED, va="bottom")
        ax.axvline(0.70, color=MUTED, lw=1, ls=(0, (4, 3)), zorder=1)
        ax.set_xlim(0.3, 1.0)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.tick_params(colors=MUTED, labelsize=8)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.set_xlabel("Grid AUC (95% CI)", fontsize=8, color=MUTED)

    # 축 이름표·범례·주석을 붙이고 저장한다
    axes[0].set_yticks([ypos[n] for n in labels], labels, fontsize=8, color=INK)
    handles = [plt.Line2D([], [], color=c, marker="o", lw=2, label=n.capitalize()) for n, c in COLORS.items()]
    fig.legend(handles=handles, loc="upper right", ncol=2, frameon=False, fontsize=8)
    fig.text(0.01, 0.01, "Diamond: REML + modified HKSJ 95% CI (k≥2). Thin line below: 95% prediction interval "
             "(k≥3). Dashed: gate AUC 0.70. Units = events (k). Holdout k=2 intervals (t, 1 df) run past the axis.",
             fontsize=7, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)
