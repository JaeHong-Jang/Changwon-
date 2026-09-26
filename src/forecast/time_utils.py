"""예보와 특보에서 공통으로 쓰는 KST 시각을 정규화한다."""

import pandas as pd


def parse_time(value):
    """KST 벽시각과 기상청 숫자 시각을 동일한 Timestamp로 바꾼다."""
    # CSV 숫자 추론으로 생긴 정수 및 문자열 시각을 모두 지원한다.
    if pd.isna(value) or str(value).strip() == "":
        return pd.NaT
    text = str(value).strip().removesuffix(".0")
    formats = {10: "%Y%m%d%H", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}
    stamp = pd.to_datetime(text, format=formats[len(text)]) if text.isdigit() and len(text) in formats else pd.Timestamp(text)
    return stamp.tz_convert("Asia/Seoul").tz_localize(None) if stamp.tzinfo else stamp
