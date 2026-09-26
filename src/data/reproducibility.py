"""산출물의 바이트·내용 동일성과 정규 JSON 해시를 계산한다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from src.models.provenance import file_sha256


CSV_IGNORED_COLUMNS = frozenset({"run_id", "evidence_run_id"})
JSON_IGNORED_KEYS = frozenset({"run_id", "source_run_id", "evidence_run_id", "created_utc",
                               "started_utc", "created_at_utc", "frozen_at_utc"})


def canonical_hash(obj) -> str:
    """키 순서에 독립적인 UTF-8 JSON SHA256을 반환한다."""
    # 지정된 직렬화 규칙으로 JSON 바이트를 고정한다.
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stable_json(obj):
    """JSON_IGNORED_KEYS(run_id, source_run_id, evidence_run_id, created_utc, started_utc, created_at_utc, frozen_at_utc)만 제외한다."""
    # 중첩 객체와 배열의 실행별 메타데이터를 제거한다.
    if isinstance(obj, dict):
        return {key: _stable_json(value) for key, value in obj.items()
                if key not in JSON_IGNORED_KEYS}
    if isinstance(obj, list):
        return [_stable_json(value) for value in obj]
    return obj


def _json_difference(a, b, path="$") -> str:
    """중첩 JSON에서 처음 다른 키 또는 배열 위치를 반환한다."""
    # 구조·키·값을 순서대로 비교해 첫 차이의 경로를 남긴다.
    if type(a) is not type(b):
        return f"{path}: type differs"
    if isinstance(a, dict):
        for key in sorted(a.keys() | b.keys()):
            if key not in a or key not in b:
                return f"{path}.{key}: missing key"
            detail = _json_difference(a[key], b[key], f"{path}.{key}")
            if detail:
                return detail
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length differs"
        for index, (left, right) in enumerate(zip(a, b)):
            detail = _json_difference(left, right, f"{path}[{index}]")
            if detail:
                return detail
        return ""
    return "" if a == b else f"{path}: value differs"


def _frame_difference(a, b) -> str:
    """열 순서를 무시하고 표의 첫 불일치 열을 반환한다."""
    # 열 집합과 인덱스를 확인한 뒤 열마다 정확한 값을 비교한다.
    if set(a.columns) != set(b.columns):
        return f"column {sorted(set(a.columns) ^ set(b.columns), key=str)[0]}: missing"
    if not a.index.equals(b.index):
        return "index: differs"
    for column in a.columns:
        if not a[column].equals(b[column]):
            return f"column {column}: values or dtype differ"
    return ""


def _gpkg_difference(a: Path, b: Path) -> str:
    """모든 GeoPackage 레이어의 속성·좌표계·도형을 비교한다."""
    # 공간 및 비공간 레이어 이름을 모두 비교한다.
    layers_a = {row[0] for row in pyogrio.list_layers(a)}
    layers_b = {row[0] for row in pyogrio.list_layers(b)}
    if layers_a != layers_b:
        return f"layer {sorted(layers_a ^ layers_b)[0]}: missing"
    for layer in sorted(layers_a):
        left, right = (gpd.read_file(path, layer=layer) for path in (a, b))
        if "grid_id" in left and "grid_id" in right:
            left = left.sort_values("grid_id", kind="stable").reset_index(drop=True)
            right = right.sort_values("grid_id", kind="stable").reset_index(drop=True)
        spatial = isinstance(left, gpd.GeoDataFrame), isinstance(right, gpd.GeoDataFrame)
        if spatial[0] != spatial[1]:
            return f"layer {layer}: geometry column missing"
        if all(spatial):
            if left.crs != right.crs:
                return f"layer {layer}: CRS differs"
            detail = _frame_difference(left.drop(columns=left.geometry.name),
                                       right.drop(columns=right.geometry.name))
            if not detail:
                for index, (x, y) in enumerate(zip(left.geometry, right.geometry)):
                    if not ((x is None and y is None)
                            or (x is not None and y is not None and x.equals_exact(y, tolerance=1e-6))):
                        detail = f"column geometry: row {index} differs"
                        break
        else:
            detail = _frame_difference(left, right)
        if detail:
            return f"layer {layer}: {detail}"
    return ""


def compare_file(a, b) -> dict:
    """파일 내용을 비교하되 CSV는 CSV_IGNORED_COLUMNS(run_id, evidence_run_id)만 제외한다."""
    # 파일 부재와 바이트 일치를 내용 비교보다 먼저 검사한다.
    a, b = Path(a), Path(b)
    if not a.is_file() or not b.is_file():
        missing = [str(path) for path in (a, b) if not path.is_file()]
        return {"status": "missing", "detail": f"missing: {', '.join(missing)}"}
    if a.stat().st_size == b.stat().st_size and file_sha256(a) == file_sha256(b):
        return {"status": "identical", "detail": "bytes identical"}

    # 지원 형식은 내용으로 비교하고 해석 실패는 불일치로 기록한다.
    try:
        suffix = a.suffix.lower()
        if suffix == ".parquet":
            detail = _frame_difference(pd.read_parquet(a), pd.read_parquet(b))
        elif suffix == ".gpkg":
            detail = _gpkg_difference(a, b)
        elif suffix == ".csv":
            left, right = pd.read_csv(a), pd.read_csv(b)
            left = left.loc[:, [c for c in left if c not in CSV_IGNORED_COLUMNS]]
            right = right.loc[:, [c for c in right if c not in CSV_IGNORED_COLUMNS]]
            detail = _frame_difference(left, right)
        elif suffix == ".json":
            left, right = (_stable_json(json.loads(p.read_text(encoding="utf-8"))) for p in (a, b))
            detail = _json_difference(left, right)
        else:
            detail = "bytes differ"
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
    return {"status": "different" if detail else "content_identical", "detail": detail}


def compare_trees(root_a, root_b, patterns) -> list[dict]:
    """패턴별 양쪽 파일 합집합을 비교하고 상대 경로와 상태를 반환한다."""
    # 한쪽에만 존재하는 파일도 누락 없이 비교표에 포함한다.
    root_a, root_b = Path(root_a), Path(root_b)
    rows = []
    for pattern in patterns:
        paths = {p.relative_to(root) for root in (root_a, root_b)
                 for p in root.glob(pattern) if p.is_file()}
        if not paths:
            rows.append({"pattern": pattern, "path": pattern, "status": "missing_pattern",
                         "detail": "no files match pattern in either tree"})
        for path in sorted(paths):
            rows.append({"pattern": pattern, "path": path.as_posix(),
                         **compare_file(root_a / path, root_b / path)})
    return rows
