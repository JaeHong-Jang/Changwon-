"""두 홀드아웃 평가 실행의 게이트 해시·지표표·실행 메타를 M6 절차 규칙(J1~J3)으로 비교한다."""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from src.data.reproducibility import canonical_hash

METRIC_KEYS = ["score", "unit", "stratum", "storm", "metric", "polygon_subset"]
METRIC_FLOATS = ["value", "ci_lo", "ci_hi"]
METRIC_EXACT = ["n_units", "n_polygons", "score_role", "post_hoc_design", "confirmatory"]
JUDGED_KEYS = ["holdout", "polygons_by_storm", "polygons_by_subset", "n_background_cells", "raw_sha256",
               "score_roles", "gate_definition", "models"]
RECORDED_KEYS = ["run_id", "started_utc", "git_head", "source_dirty", "versions", "code_sha256",
                 "processed_sha256", "note", "command"]
FLOAT_NOISE = 1e-9


def gate_hashes(summary: dict[str, Any]) -> dict[str, str]:
    """H10 과 같은 정규 JSON 해시로 홀드아웃·개발 게이트를 요약한다."""
    return {"gates_sha256": canonical_hash(summary["gates"]),
            "development_gates_sha256": canonical_hash(summary.get("development_gates"))}


def first_difference(a: Any, b: Any, path: str = "$") -> str:
    """중첩 JSON 에서 처음 다른 경로를 돌려주고 같으면 빈 문자열이다."""
    # 사전은 키 합집합 순서로, 목록은 위치 순서로 내려가며 비교한다
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key not in a or key not in b:
                return f"{path}.{key}: 한쪽에만 있음"
            found = first_difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return ""
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: 길이 {len(a)} ≠ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return ""
    if canonical_hash(a) == canonical_hash(b):
        return ""
    left, right = (json.dumps(v, ensure_ascii=False, default=str)[:80] for v in (a, b))
    return f"{path}: {left} ≠ {right}"


def _same(a: Any, b: Any) -> np.ndarray:
    """두 열을 결측끼리 같다고 보고 원소별로 비교한다."""
    import pandas as pd

    # 결측 위치가 같으면 같은 값으로 친다
    both_na = pd.isna(a).to_numpy() & pd.isna(b).to_numpy()
    return both_na | (a.astype(str).to_numpy() == b.astype(str).to_numpy())


def compare_metrics(new: Any, ref: Any) -> tuple[dict[str, Any], Any]:
    """metrics.csv 두 개를 키로 맞춰 J2 요약과 차이 행을 돌려준다."""
    import pandas as pd

    # 키로 바깥 병합하고 한쪽에만 있는 행을 센다
    merged = new.merge(ref, on=METRIC_KEYS, how="outer", suffixes=("_new", "_ref"), indicator=True)
    both = merged["_merge"] == "both"
    out: dict[str, Any] = {"n_rows_new": int(len(new)), "n_rows_ref": int(len(ref)),
                           "only_new": int((merged["_merge"] == "left_only").sum()),
                           "only_ref": int((merged["_merge"] == "right_only").sum()),
                           "duplicate_keys_new": int(new.duplicated(METRIC_KEYS).sum()),
                           "duplicate_keys_ref": int(ref.duplicated(METRIC_KEYS).sum())}

    # 실수 열은 최대 절대차와 결측 위치 불일치를, 나머지 열은 불일치 행 수를 센다
    bad = ~both.to_numpy()
    for col in METRIC_FLOATS:
        a, b = merged[f"{col}_new"].astype(float), merged[f"{col}_ref"].astype(float)
        na_mismatch = (a.isna() != b.isna()) & both
        diff = (a - b).abs().where(both)
        out[f"max_abs_diff_{col}"] = float(diff.max()) if diff.notna().any() else 0.0
        out[f"na_mismatch_{col}"] = int(na_mismatch.sum())
        bad |= (na_mismatch | (diff > 0)).to_numpy()
    for col in METRIC_EXACT:
        unequal = ~_same(merged[f"{col}_new"], merged[f"{col}_ref"]) & both.to_numpy()
        out[f"mismatch_{col}"] = int(unequal.sum())
        bad |= unequal

    # 차이 행만 모아 J2 판정 재료와 함께 돌려준다
    out["max_abs_diff"] = max(out[f"max_abs_diff_{c}"] for c in METRIC_FLOATS)
    out["n_diff_rows"] = int(bad.sum())
    keep = METRIC_KEYS + [f"{c}_{s}" for c in METRIC_FLOATS + METRIC_EXACT for s in ("new", "ref")] + ["_merge"]
    return out, pd.DataFrame(merged.loc[bad, keep]).reset_index(drop=True)


def compare_summaries(new: dict[str, Any], ref: dict[str, Any], reference: dict[str, str]) -> dict[str, Any]:
    """J1 게이트 해시와 J3 실행 메타를 판정하고 기록 전용 항목의 차이를 적는다."""
    # 새 실행의 게이트 해시를 고정 기준값·기준 실행 요약과 대조한다
    hashes = gate_hashes(new)
    j1 = {"new": hashes, "reference": {k: reference[k] for k in hashes},
          "ref_run": gate_hashes(ref),
          "pass": all(hashes[k] == reference[k] for k in hashes)}

    # 판정 대상 메타는 첫 차이 경로를, 기록 전용 항목은 값 차이를 남긴다
    j3 = {key: first_difference(new.get(key), ref.get(key)) for key in JUDGED_KEYS}
    recorded = {}
    for key in RECORDED_KEYS:
        a, b = new.get(key), ref.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            changed = {k: {"new": a.get(k), "ref": b.get(k)} for k in sorted(set(a) | set(b), key=str)
                       if a.get(k) != b.get(k)}
            recorded[key] = changed
        elif a != b:
            recorded[key] = {"new": a, "ref": b}
    return {"J1": j1, "J3": {"differences": {k: v for k, v in j3.items() if v}, "pass": not any(j3.values())},
            "recorded_differences": recorded}


def verdict(j1_pass: bool, j2: dict[str, Any], j3_pass: bool) -> str:
    """절차 §2.3 에 따라 재현·부동소수 차이·불일치 중 하나를 고른다."""
    # 행 구성과 범주 열이 같아야 수치 비교가 의미를 갖는다
    structural = (j2["only_new"] == 0 and j2["only_ref"] == 0 and j2["duplicate_keys_new"] == 0
                  and j2["duplicate_keys_ref"] == 0
                  and all(j2[f"mismatch_{c}"] == 0 for c in METRIC_EXACT)
                  and all(j2[f"na_mismatch_{c}"] == 0 for c in METRIC_FLOATS))
    if not (j1_pass and j3_pass and structural):
        return "mismatch"
    if j2["max_abs_diff"] == 0:
        return "reproduced"
    return "float_noise" if j2["max_abs_diff"] <= FLOAT_NOISE else "mismatch"
