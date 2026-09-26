"""라벨 감사 재실행 산출을 저장본과 비교한다 (요약은 run_id 제외 동일, 폴리곤 표는 실수 열 허용오차)."""

from __future__ import annotations

from typing import Any

import numpy as np

from src.repro.run_compare import first_difference

POLYGON_TOLERANCE = 1e-6


def compare_audit_summary(new: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """run_id 만 빼고 요약 JSON 이 같은지 본다."""
    # 실행마다 달라지는 run_id 를 지운 사본끼리 첫 차이를 찾는다
    new_body = {k: v for k, v in new.items() if k != "run_id"}
    stored_body = {k: v for k, v in stored.items() if k != "run_id"}
    found = first_difference(new_body, stored_body)
    return {"run_id_new": new.get("run_id"), "run_id_stored": stored.get("run_id"),
            "first_difference": found, "pass": not found}


def compare_polygon_tables(new: Any, stored: Any) -> dict[str, Any]:
    """같은 순서의 폴리곤 표에서 실수 열은 최대 절대차, 나머지 열은 불일치 수를 센다."""
    import pandas as pd

    # 열 구성과 행 수가 다르면 값 비교 없이 실패로 돌려준다
    out: dict[str, Any] = {"columns_new_only": sorted(set(new.columns) - set(stored.columns)),
                           "columns_stored_only": sorted(set(stored.columns) - set(new.columns)),
                           "n_rows_new": int(len(new)), "n_rows_stored": int(len(stored))}
    if out["columns_new_only"] or out["columns_stored_only"] or len(new) != len(stored):
        return out | {"pass": False}

    # 열마다 결측 위치를 맞춘 뒤 실수는 차이, 그 밖은 문자열 일치로 비교한다
    worst, mismatches = 0.0, {}
    for col in stored.columns:
        a, b = new[col].reset_index(drop=True), stored[col].reset_index(drop=True)
        na = a.isna().to_numpy() != b.isna().to_numpy()
        if pd.api.types.is_float_dtype(a) and pd.api.types.is_float_dtype(b):
            diff = np.nanmax(np.abs(a.to_numpy(float) - b.to_numpy(float)), initial=0.0)
            worst = max(worst, float(diff))
            count = int(na.sum())
        else:
            same = (a.isna() & b.isna()).to_numpy() | (a.astype(str).to_numpy() == b.astype(str).to_numpy())
            count = int((~same).sum())
        if count:
            mismatches[col] = count
    return out | {"max_abs_diff_float": worst, "mismatch_counts": mismatches,
                  "pass": not mismatches and worst <= POLYGON_TOLERANCE}
