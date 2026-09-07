"""SGIS 통계 CSV 표준화 (하네스 §6-3).

모든 SGIS 통계 CSV는 **헤더가 없다**. 계약(config/data_contracts.yaml)이 정한
4개 컬럼 `year, spatial_id, variable, value` 를 코드에서 명시적으로 부여한다.
파일마다 인코딩이 다르다: 100m 격자 통계는 cp949, 집계구 통계는 utf-8-sig.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

CONTRACT_COLUMNS = ["year", "spatial_id", "variable", "value"]

# 코드북 (원본에 설명이 없어 SGIS 지표 정의로 확인한 값)
VARIABLE_LABELS = {
    "to_in_001": "총인구",
    "to_in_004": "노령화지수",
    "to_in_007": "남자인구",
    "to_in_008": "여자인구",
    "to_ga_001": "총가구",
    "to_ho_001": "총주택",
}


def read_headerless(path: Path, encoding: str) -> pd.DataFrame:
    """헤더 없는 SGIS CSV 한 개를 계약 컬럼으로 읽는다. 원행 번호를 보존한다."""
    df = pd.read_csv(
        path,
        header=None,
        names=CONTRACT_COLUMNS,
        encoding=encoding,
        dtype={"year": "Int64", "spatial_id": "string", "variable": "string"},
    )
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["source_file"] = path.name
    df["source_row"] = range(len(df))
    return df


def load_group(paths: list[Path], encoding: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """여러 파일을 하나의 long 표로 합치고 키 유일성을 확인한다.

    반환 metrics: files, rows, unique_spatial_ids, variables, duplicate_keys,
    null_values (value 파싱 실패 수).
    """
    frames = [read_headerless(p, encoding) for p in sorted(paths)]
    if not frames:
        return pd.DataFrame(columns=CONTRACT_COLUMNS + ["source_file", "source_row"]), {
            "files": 0, "rows": 0, "unique_spatial_ids": 0, "variables": [],
            "duplicate_keys": 0, "null_values": 0,
        }
    df = pd.concat(frames, ignore_index=True)
    key = ["year", "spatial_id", "variable"]
    duplicate_keys = int(df.duplicated(subset=key).sum())
    metrics = {
        "files": len(frames),
        "rows": int(len(df)),
        "unique_spatial_ids": int(df["spatial_id"].nunique()),
        "variables": sorted(v for v in df["variable"].dropna().unique()),
        "variable_labels": {
            v: VARIABLE_LABELS.get(v, "코드북 미확인")
            for v in sorted(df["variable"].dropna().unique())
        },
        "duplicate_keys": duplicate_keys,
        "null_values": int(df["value"].isna().sum()),
        "rows_per_file": {f: int(n) for f, n in df.groupby("source_file").size().items()},
    }
    return df, metrics


# ── 성·연령별 인구 코드북 (집계구 통계) ────────────────────────────────────
# `in_age_NNN` 은 5세 계급 21개(0~4 … 100+)가 세 블록으로 반복된다.
#   001~021 전체 · 031~051 남자 · 061~081 여자
# 2026-09-07 항등식으로 확인했다 (하네스 §6 "연령 코드북 확정 전 65세 이상 파생 금지"):
#   ① 블록 합 ≤ 대응 공표값(총인구·남자·여자) 위반 0/2,118, 합계 비율 0.9895 (나머지는 소수 마스킹)
#   ② 남자합 + 여자합 = 전체합 (평균 오차 11.6명, 마스킹 차이)
#   ③ in_age_014~021 을 65세 이상으로 보고 계산한 노령화지수가 공표 to_in_004 와
#      상관 0.963 · 중앙 절대오차 7.7 로 일치. 한 칸 당긴 대안(60~·70~)은 중앙오차 100·80 으로 기각
AGE_BAND_YEARS = 5
AGE_BLOCK_TOTAL = range(1, 22)     # 전체
AGE_BLOCK_MALE = range(31, 52)     # 남자
AGE_BLOCK_FEMALE = range(61, 82)   # 여자
ELDERLY_FROM_AGE = 65
YOUTH_UNDER_AGE = 15


def age_columns(block: range, *, min_age: int | None = None, max_age: int | None = None) -> list[str]:
    """블록 안에서 [min_age, max_age] 에 걸치는 연령 계급 컬럼명. max_age=None 이면 상한 없음."""
    out = []
    for offset, code in enumerate(block):
        low = offset * AGE_BAND_YEARS
        high = low + AGE_BAND_YEARS - 1
        if min_age is not None and high < min_age:
            continue
        if max_age is not None and low > max_age:
            continue
        out.append(f"in_age_{code:03d}")
    return out


def elderly_ratio(aggregation: pd.DataFrame, year: int) -> pd.DataFrame:
    """집계구별 65세 이상 비율. 마스킹(5명 미만 미공표)으로 연령합이 총인구보다 작으므로
    분모는 **연령 계급 합**을 쓴다. 총인구를 분모로 쓰면 비율이 체계적으로 낮아진다.

    반환: spatial_id, pop_age_total, pop_elderly, elderly_ratio, pop_published
    """
    sub = aggregation[aggregation["year"] == year]
    wide = sub.pivot_table(index="spatial_id", columns="variable", values="value", aggfunc="first")
    total_cols = [c for c in age_columns(AGE_BLOCK_TOTAL) if c in wide.columns]
    elderly_cols = [c for c in age_columns(AGE_BLOCK_TOTAL, min_age=ELDERLY_FROM_AGE) if c in wide.columns]
    if not elderly_cols:
        raise ValueError("65세 이상 연령 계급 컬럼을 찾지 못했다 — 코드북 확인 필요")
    pop_age_total = wide[total_cols].sum(axis=1)
    pop_elderly = wide[elderly_cols].sum(axis=1)
    out = pd.DataFrame({
        "spatial_id": wide.index,
        "pop_age_total": pop_age_total.to_numpy(),
        "pop_elderly": pop_elderly.to_numpy(),
        "pop_published": wide["to_in_001"].to_numpy() if "to_in_001" in wide.columns else pop_age_total.to_numpy(),
    })
    out["elderly_ratio"] = (out["pop_elderly"] / out["pop_age_total"]).where(out["pop_age_total"] > 0)
    return out
