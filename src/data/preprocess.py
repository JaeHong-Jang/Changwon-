"""
데이터 전처리 모듈

수집된 원본 데이터(data/raw/)를 정제하여 분석용 데이터(data/processed/)로 저장합니다.
각 데이터셋별 전처리 함수를 제공합니다.
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.utils.config import get_path
from src.data.collect_public_data import load_dataset


def _save(df: pd.DataFrame, filename: str):
    """전처리 결과를 data/processed/에 저장합니다."""
    out_dir = get_path("processed_data")
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / filename
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"  💾 저장: {filepath} ({len(df)}행)")


# ──────────────────────────────────────────────
# 1. 하수관로 설치현황
# ──────────────────────────────────────────────

def preprocess_sewer_pipe() -> pd.DataFrame:
    """
    하수관로 데이터 전처리
    - 창원시 데이터만 필터링
    - 관종·관경·연장 컬럼 정리
    - 수치형 변환 및 결측치 처리
    """
    df = load_dataset("sewer_pipe")

    # 창원시 필터링 (컬럼명은 실제 데이터에 맞게 조정 필요)
    # 일반적으로 '시군구명' 또는 '시도명' + '시군구명' 형태
    changwon_keywords = ["창원"]
    mask = df.apply(
        lambda row: any(kw in str(v) for v in row.values for kw in changwon_keywords),
        axis=1,
    )
    df = df[mask].copy()

    # 수치 컬럼 변환 (숫자가 아닌 값은 NaN 처리)
    for col in df.select_dtypes(include=["object"]).columns:
        try:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.notna().sum() > len(df) * 0.5:
                df[col] = converted
        except (ValueError, TypeError):
            pass

    _save(df, "sewer_pipe_cleaned.csv")
    return df


# ──────────────────────────────────────────────
# 2. 기상 데이터
# ──────────────────────────────────────────────

def preprocess_weather(filename: str = "weather_daily_2024.csv") -> pd.DataFrame:
    """
    기상 데이터 전처리
    - 날짜 파싱
    - 강수량·기온 수치형 변환
    - 결측치 0 또는 보간 처리
    """
    raw_dir = get_path("raw_data")
    filepath = raw_dir / filename
    df = pd.read_csv(filepath, encoding="utf-8-sig")

    # 날짜 컬럼 파싱 (기상청 API: 'tm' 컬럼)
    if "tm" in df.columns:
        df["date"] = pd.to_datetime(df["tm"])

    # 강수량: 빈 값 → 0 (비가 안 온 날)
    rain_cols = [c for c in df.columns if "rn" in c.lower() or "강수" in c]
    for col in rain_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 기온
    temp_cols = [c for c in df.columns if "ta" in c.lower() or "기온" in c]
    for col in temp_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    out_name = filename.replace(".csv", "_cleaned.csv")
    _save(df, out_name)
    return df


# ──────────────────────────────────────────────
# 3. 배수펌프장
# ──────────────────────────────────────────────

def preprocess_pump_station() -> pd.DataFrame:
    """
    배수펌프장 데이터 전처리
    - 창원시 필터링
    - 용량·위치 정보 정리
    """
    df = load_dataset("pump_station")

    # 창원시 필터링
    changwon_keywords = ["창원"]
    mask = df.apply(
        lambda row: any(kw in str(v) for v in row.values for kw in changwon_keywords),
        axis=1,
    )
    df = df[mask].copy()

    _save(df, "pump_station_cleaned.csv")
    return df


# ──────────────────────────────────────────────
# 4. 건축물대장
# ──────────────────────────────────────────────

def preprocess_building_register() -> pd.DataFrame:
    """
    건축물대장 전처리
    - 건축년도 추출 → 노후도(경과 연수) 계산
    - 용도별 분류 (주거·반지하 등)
    - 결측치 처리
    """
    df = load_dataset("building_register")

    # 건축년도 → 경과 연수 계산
    year_cols = [c for c in df.columns if "년도" in c or "년" in c]
    if year_cols:
        col = year_cols[0]
        df["건축년도"] = pd.to_numeric(df[col], errors="coerce")
        df["경과연수"] = 2026 - df["건축년도"]
        df["노후여부"] = df["경과연수"] >= 30  # 30년 이상 노후 건물

    _save(df, "building_register_cleaned.csv")
    return df


# ──────────────────────────────────────────────
# 5. 하수도 민원 (정보공개청구 회신 후)
# ──────────────────────────────────────────────

def preprocess_sewer_complaints(filename: str = "sewer_complaints.csv") -> pd.DataFrame:
    """
    하수도 민원 데이터 전처리 (정보공개청구 회신 후 사용)
    - 접수일시 파싱
    - 민원 유형 분류 (악취/역류/파손/기타)
    - 위치 정보 정리
    """
    raw_dir = get_path("raw_data")
    filepath = raw_dir / filename

    if not filepath.exists():
        print(f"  ⚠️ 파일 없음: {filepath}")
        print("  정보공개청구 회신 후 해당 파일을 data/raw/에 저장하세요.")
        return pd.DataFrame()

    # 인코딩 시도
    try:
        df = pd.read_csv(filepath, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(filepath, encoding="cp949")

    # 날짜 파싱 (컬럼명은 실제 데이터에 맞게 조정)
    date_cols = [c for c in df.columns if "일" in c or "일시" in c or "날짜" in c]
    if date_cols:
        df["접수일"] = pd.to_datetime(df[date_cols[0]], errors="coerce")

    # 민원 유형 키워드 기반 분류
    type_col = [c for c in df.columns if "유형" in c or "내용" in c or "구분" in c]
    if type_col:
        col = type_col[0]
        conditions = [
            df[col].str.contains("악취|냄새", na=False),
            df[col].str.contains("역류|넘침|범람", na=False),
            df[col].str.contains("파손|파열|침하", na=False),
        ]
        choices = ["악취", "역류", "파손"]
        df["민원유형"] = np.select(conditions, choices, default="기타")

    _save(df, "sewer_complaints_cleaned.csv")
    return df


# ──────────────────────────────────────────────
# 전체 전처리 실행
# ──────────────────────────────────────────────

def run_all():
    """다운로드된 모든 데이터를 전처리합니다."""
    print("=" * 60)
    print("  전처리 시작")
    print("=" * 60)

    steps = [
        ("하수관로 설치현황", preprocess_sewer_pipe),
        ("배수펌프장 현황", preprocess_pump_station),
        ("건축물대장", preprocess_building_register),
        ("하수도 민원", preprocess_sewer_complaints),
    ]

    for name, func in steps:
        print(f"\n  ▸ {name}")
        try:
            func()
        except FileNotFoundError as e:
            print(f"    ⚠️ 건너뜀 — {e}")
        except Exception as e:
            print(f"    ❌ 오류 — {e}")

    # 기상 데이터 (파일이 있으면 처리)
    raw_dir = get_path("raw_data")
    for f in sorted(raw_dir.glob("weather_*.csv")):
        print(f"\n  ▸ 기상 데이터: {f.name}")
        try:
            preprocess_weather(f.name)
        except Exception as e:
            print(f"    ❌ 오류 — {e}")

    print("\n" + "=" * 60)
    print("  전처리 완료")
    print("=" * 60)


if __name__ == "__main__":
    run_all()
