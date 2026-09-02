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
