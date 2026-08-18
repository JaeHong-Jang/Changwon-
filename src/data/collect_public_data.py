"""
공공데이터포털(data.go.kr) 파일 데이터 수집 모듈

data.go.kr의 파일 데이터는 로그인 후 수동 다운로드가 필요합니다.
이 모듈은 두 가지 역할을 합니다:
  1. 각 데이터셋의 다운로드 URL과 안내를 출력 (guide_download)
  2. 다운로드된 CSV/Excel 파일을 로드 (load_*)
"""

import sys
from pathlib import Path

import pandas as pd

# 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.utils.config import get_path

# ──────────────────────────────────────────────
# 데이터셋 카탈로그
# ──────────────────────────────────────────────
DATASETS = {
    "sewer_pipe": {
        "name": "한국환경공단_하수관로시설별설치현황",
        "url": "https://www.data.go.kr/data/15118453/fileData.do",
        "filename": "sewer_pipe_installation.csv",
        "description": "시군구별 하수관로 관종·관경·연장 현황 (관로 노후도 분석용)",
    },
    "rainfall": {
        "name": "기상청_시간별강수량",
        "url": "https://www.data.go.kr/data/15150315/fileData.do",
        "filename": "hourly_rainfall.csv",
        "description": "관측소별 시간 단위 강수량 데이터 (침수·역류 트리거 분석용)",
    },
    "pump_station": {
        "name": "환경부_배수펌프장현황",
        "url": "https://www.data.go.kr/data/15047868/fileData.do",
        "filename": "pump_station.csv",
        "description": "배수펌프장 위치·용량·가동 현황 (배수 용량 분석용)",
    },
    "drainage_area": {
        "name": "국토교통부_하수도배수구역",
        "url": "https://www.data.go.kr/data/15129161/fileData.do",
        "filename": "drainage_area.csv",
        "description": "하수도 배수구역 경계·면적 정보 (배수 구역 분석용)",
    },
    "building_register": {
        "name": "경상남도 창원시_건축물대장정보",
        "url": "https://www.data.go.kr/data/15064338/fileData.do",
        "filename": "building_register.csv",
        "description": "건축물 주소·건축년도·구조·용도 (노후 건물·반지하 분석용)",
    },
}


def guide_download():
    """모든 데이터셋의 다운로드 안내를 출력합니다."""
    raw_dir = get_path("raw_data")
    print("=" * 70)
    print("  공공데이터포털 파일 데이터 다운로드 안내")
    print("=" * 70)
    print()
    print(f"  저장 위치: {raw_dir}")
    print()

    for key, info in DATASETS.items():
        print(f"  [{key}] {info['name']}")
        print(f"    URL  : {info['url']}")
        print(f"    저장명: {info['filename']}")
        print(f"    설명  : {info['description']}")
        print()

    print("-" * 70)
    print("  ※ data.go.kr에 로그인 → 위 URL 접속 → 파일 다운로드")
    print(f"  ※ 다운로드한 파일을 위 저장 위치에 지정된 파일명으로 저장하세요.")
    print(f"  ※ 파일명이 다르면 load_dataset() 호출 시 filename 인자로 지정 가능합니다.")
    print("=" * 70)


def check_downloaded() -> dict[str, bool]:
    """각 데이터셋의 다운로드 여부를 확인합니다."""
    raw_dir = get_path("raw_data")
    result = {}
    for key, info in DATASETS.items():
        filepath = raw_dir / info["filename"]
        result[key] = filepath.exists()
    return result


def print_status():
    """데이터 다운로드 상태를 출력합니다."""
    status = check_downloaded()
    print("\n  데이터 다운로드 상태:")
    for key, downloaded in status.items():
        mark = "✅" if downloaded else "❌"
        print(f"    {mark} {DATASETS[key]['name']} ({DATASETS[key]['filename']})")
    print()


def load_dataset(key: str, filename: str | None = None, **kwargs) -> pd.DataFrame:
    """
    다운로드된 데이터셋을 DataFrame으로 로드합니다.

    Parameters
    ----------
    key : str
        DATASETS 딕셔너리의 키 (예: 'sewer_pipe')
    filename : str, optional
        기본 파일명 대신 사용할 파일명
    **kwargs
        pd.read_csv 또는 pd.read_excel에 전달할 추가 인자

    Returns
    -------
    pd.DataFrame
    """
    if key not in DATASETS:
        raise KeyError(f"알 수 없는 데이터셋 키: '{key}'. 가능한 키: {list(DATASETS.keys())}")

    raw_dir = get_path("raw_data")
    fname = filename or DATASETS[key]["filename"]
    filepath = raw_dir / fname

    if not filepath.exists():
        raise FileNotFoundError(
            f"파일을 찾을 수 없습니다: {filepath}\n"
            f"guide_download()를 실행하여 다운로드 방법을 확인하세요."
        )

    # 확장자에 따라 로드 방식 분기
    suffix = filepath.suffix.lower()
    if suffix in (".xls", ".xlsx"):
        return pd.read_excel(filepath, **kwargs)
    else:
        # CSV 기본: UTF-8 시도 → 실패 시 cp949
        encoding = kwargs.pop("encoding", None)
        if encoding:
            return pd.read_csv(filepath, encoding=encoding, **kwargs)
        try:
            return pd.read_csv(filepath, encoding="utf-8", **kwargs)
        except UnicodeDecodeError:
            return pd.read_csv(filepath, encoding="cp949", **kwargs)


# ──────────────────────────────────────────────
# 개별 데이터 로드 편의 함수
# ──────────────────────────────────────────────

def load_sewer_pipe(**kwargs) -> pd.DataFrame:
    """하수관로 설치현황 데이터를 로드합니다."""
    return load_dataset("sewer_pipe", **kwargs)


def load_rainfall(**kwargs) -> pd.DataFrame:
    """시간별 강수량 데이터를 로드합니다."""
    return load_dataset("rainfall", **kwargs)


def load_pump_station(**kwargs) -> pd.DataFrame:
    """배수펌프장 현황 데이터를 로드합니다."""
    return load_dataset("pump_station", **kwargs)


def load_drainage_area(**kwargs) -> pd.DataFrame:
    """하수도 배수구역 데이터를 로드합니다."""
    return load_dataset("drainage_area", **kwargs)


def load_building_register(**kwargs) -> pd.DataFrame:
    """건축물대장 데이터를 로드합니다."""
    return load_dataset("building_register", **kwargs)


if __name__ == "__main__":
    guide_download()
    print_status()
