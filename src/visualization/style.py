"""보고서 그림 공통 스타일. 한글 폰트 등록과 흑백 논문 스타일을 한곳에서 정한다.

matplotlib 는 기본 폰트에 한글 글리프가 없어서 제목·축 라벨이 네모(□□□)로 깨진다.
`apply()` 를 한 번 부르면 시스템에서 한글 폰트를 찾아 등록하고, 못 찾으면 예외를 던진다.
조용히 깨진 그림을 만드는 것보다 실패하는 편이 낫다.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager

# 백엔드는 강제하지 않는다. 화면이 없는 파이프라인 실행에서는 matplotlib 이 Agg 를 고르고,
# 노트북에서는 ipykernel 이 인라인 백엔드를 쓴다. 여기서 Agg 로 못박으면 노트북에
# 그림이 표시되지 않는다.

# 흑백 인쇄에서도 구분되는 회색 단계. 색으로 의미를 나누지 않고 명도·해칭으로 나눈다.
INK = "#000000"
DARK = "#404040"
MID = "#808080"
LIGHT = "#c0c0c0"
PALE = "#e8e8e8"

# 한글 폰트 후보. WSL 에서는 Windows 폰트를 그대로 쓸 수 있다.
FONT_CANDIDATES = [
    Path("/mnt/c/Windows/Fonts/malgun.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
]

_applied = False


def apply() -> None:
    """전역 스타일 적용. 여러 번 불러도 한 번만 동작한다.

    한글 폰트를 못 찾으면 RuntimeError 를 낸다. 제목이 네모로 깨진 그림을 조용히
    만드는 것보다 실패하는 편이 낫다.
    """
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
        # 값을 눈으로 읽으려면 격자선이 있어야 한다. 데이터를 가리지 않게 옅게, 축 뒤로.
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
    """제목이 왼쪽에 붙은 축 하나.

    subtitle 은 그림만 보고도 무엇을 봐야 하는지 알려주는 한 줄이다. 제목 아래에 두는 이유는
    회전된 축 라벨이 긴 그림에서 아래쪽 각주가 라벨과 겹치기 때문이다.
    """
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
