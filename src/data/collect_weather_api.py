"""
기상청 종관기상관측(ASOS) API를 통한 기상 데이터 수집 모듈

사용법:
  1. 기상청 기상자료개방포털(data.kma.go.kr)에서 API 키 발급
  2. .env 파일에 KMA_API_KEY=발급받은키 추가
  3. 아래 함수 호출하여 데이터 수집

창원 관측소 번호: 155
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.utils.config import get_path, load_env

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────

# 기상청 ASOS API 엔드포인트
ASOS_DAILY_URL = (
    "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
)
ASOS_HOURLY_URL = (
    "https://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"
)

CHANGWON_STN_ID = "155"  # 창원 관측소


def _get_api_key() -> str:
    """환경 변수에서 기상청 API 키를 가져옵니다."""
    import os
    load_env()
    key = os.getenv("KMA_API_KEY", "")
    if not key:
        raise ValueError(
            "기상청 API 키가 설정되지 않았습니다. "
            ".env 파일에 KMA_API_KEY=발급받은키 를 추가하세요. "
            "키 발급: https://data.kma.go.kr → 오픈 API → 활용신청"
        )
    return key


# ──────────────────────────────────────────────
# 일별 관측 데이터 수집
# ──────────────────────────────────────────────

def fetch_daily(
    start_date: str,
    end_date: str,
    stn_id: str = CHANGWON_STN_ID,
) -> pd.DataFrame:
    """
    일별 기상관측 데이터를 수집합니다.

    Parameters
    ----------
    start_date : str
        시작일 (YYYYMMDD 형식, 예: '20230101')
    end_date : str
        종료일 (YYYYMMDD 형식, 예: '20231231')
    stn_id : str
        관측소 번호 (기본값: 155 = 창원)

    Returns
    -------
    pd.DataFrame
        일별 기상관측 데이터
    """
    api_key = _get_api_key()

    params = {
        "serviceKey": api_key,
        "pageNo": "1",
        "numOfRows": "999",
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": start_date,
        "endDt": end_date,
        "stnIds": stn_id,
    }

    print(f"  일별 데이터 수집 중: {start_date} ~ {end_date} (관측소 {stn_id})")
    resp = requests.get(ASOS_DAILY_URL, params=params, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])

    if not items:
        print("  ⚠️ 조회 결과가 없습니다.")
        return pd.DataFrame()

    df = pd.DataFrame(items)
    print(f"  ✅ {len(df)}일치 수집 완료")
    return df


# ──────────────────────────────────────────────
# 시간별 관측 데이터 수집
# ──────────────────────────────────────────────

def fetch_hourly(
    date: str,
    stn_id: str = CHANGWON_STN_ID,
) -> pd.DataFrame:
    """
    특정 날짜의 시간별 기상관측 데이터를 수집합니다.

    Parameters
    ----------
    date : str
        조회일 (YYYYMMDD 형식)
    stn_id : str
        관측소 번호

    Returns
    -------
    pd.DataFrame
    """
    api_key = _get_api_key()

    params = {
        "serviceKey": api_key,
        "pageNo": "1",
        "numOfRows": "24",
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "HR",
        "startDt": date,
        "startHh": "00",
        "endDt": date,
        "endHh": "23",
        "stnIds": stn_id,
    }

    resp = requests.get(ASOS_HOURLY_URL, params=params, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    return pd.DataFrame(items) if items else pd.DataFrame()


def fetch_hourly_range(
    start_date: str,
    end_date: str,
    stn_id: str = CHANGWON_STN_ID,
    sleep_sec: float = 0.5,
) -> pd.DataFrame:
    """
    기간 동안의 시간별 데이터를 일별로 반복 수집합니다.

    Parameters
    ----------
    start_date, end_date : str
        YYYYMMDD 형식
    sleep_sec : float
        API 호출 간 대기 시간 (초). 과도한 호출 방지.
    """
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    days = (end - start).days + 1

    print(f"  시간별 데이터 수집 중: {start_date} ~ {end_date} ({days}일)")

    frames = []
    current = start
    for i in range(days):
        date_str = current.strftime("%Y%m%d")
        df = fetch_hourly(date_str, stn_id)
        if not df.empty:
            frames.append(df)
        current += timedelta(days=1)

        # 진행률 표시 (10일마다)
        if (i + 1) % 10 == 0:
            print(f"    ... {i + 1}/{days}일 완료")
        time.sleep(sleep_sec)

    if not frames:
        print("  ⚠️ 조회 결과가 없습니다.")
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    print(f"  ✅ 총 {len(result)}건 수집 완료")
    return result


# ──────────────────────────────────────────────
# 저장
# ──────────────────────────────────────────────

def save_weather_data(df: pd.DataFrame, filename: str):
    """수집된 기상 데이터를 data/raw/에 CSV로 저장합니다."""
    raw_dir = get_path("raw_data")
    filepath = raw_dir / filename
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"  💾 저장 완료: {filepath}")


# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────

def collect_all(year: int = 2024):
    """
    지정 연도의 일별 + 폭우 기간 시간별 데이터를 수집합니다.

    Parameters
    ----------
    year : int
        수집 대상 연도 (기본값: 2024)
    """
    print("=" * 60)
    print(f"  기상청 ASOS 데이터 수집 (창원, {year}년)")
    print("=" * 60)

    # 일별 데이터 (연간)
    daily = fetch_daily(f"{year}0101", f"{year}1231")
    if not daily.empty:
        save_weather_data(daily, f"weather_daily_{year}.csv")

    # 시간별 데이터 (여름·가을 폭우 시즌: 6~10월)
    hourly = fetch_hourly_range(f"{year}0601", f"{year}1031")
    if not hourly.empty:
        save_weather_data(hourly, f"weather_hourly_{year}_summer.csv")

    print("\n  수집 완료!")


if __name__ == "__main__":
    collect_all(2024)
