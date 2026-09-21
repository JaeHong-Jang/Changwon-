"""보고서 그림 공통 스타일."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager

# 백엔드는 실행 환경이 고르게 둔다.

# 흑백 인쇄용 회색 단계.
INK = "#000000"
DARK = "#404040"
MID = "#808080"
LIGHT = "#c0c0c0"
PALE = "#e8e8e8"

# 한글 폰트 후보
FONT_CANDIDATES = [
    Path("/mnt/c/Windows/Fonts/malgun.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
]

_applied = False


def apply() -> None:
    """전역 스타일 적용. 여러 번 불러도 한 번만 동작한다."""
    global _applied
    if _applied:
        return
    font = next((p for p in FONT_CANDIDATES if p.exists()), None)
    if font is None:
        raise RuntimeError(
            "한글 폰트를 찾지 못했습니다. 그림 제목이 깨지므로 중단합니다.\n"
            "설치: sudo apt install fonts-nanum  (또는 폰트 경로를 FONT_CANDIDATES 에 추가)"
        )
    font_manager.fontManager.addfont(str(font))

    plt.rcParams.update({
        "font.family": font_manager.FontProperties(fname=str(font)).get_name(),
        "axes.unicode_minus": False,
        "figure.dpi": 120,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.edgecolor": INK,
        "axes.linewidth": 0.8,
        # 값을 읽기 위한 옅은 y축 격자선.
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": LIGHT,
        "grid.linewidth": 0.5,
        "grid.alpha": 0.7,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": INK,
        "ytick.color": INK,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "legend.frameon": False,
        "legend.fontsize": 9,
        "lines.linewidth": 1.2,
        "patch.linewidth": 0.8,
    })
    _applied = True


def new_axes(title: str, subtitle: str = "", *, figsize=(8, 4.2)):
    """제목이 왼쪽에 붙은 축 하나."""
    apply()
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_title(title, loc="left", pad=22 if subtitle else 10)
    if subtitle:
        ax.annotate(
            subtitle, xy=(0, 1), xycoords="axes fraction",
            xytext=(0, 8), textcoords="offset points",
            fontsize=8.5, color=DARK, va="bottom", ha="left",
        )
    return fig, ax


def save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
