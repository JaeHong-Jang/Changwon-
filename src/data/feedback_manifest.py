"""자료원·모델 파일의 해시와 환류 버전 전환을 기록하고 검증한다."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.data.trace_registry import load_registry, registered_files
from src.models.provenance import file_sha256, vector_manifest

REQUIRED_KEYS = ("version", "previous_version", "created_utc", "data_versions",
                 "model_versions", "holdout_reference", "changed")


def _registered_paths(sources, root):
    """각 등록 패턴의 벡터 파일 존재를 검사하고 자료원별 경로를 반환한다."""
    # 한 자료원의 다른 패턴이 비어 있는 패턴을 가리지 않게 검사한다.
    result = {}
    for source_id, source in sources.items():
        paths = []
        for pattern in source["paths"]:
            selected = {source_id: {**source, "paths": [pattern]}}
            matched = [path for path, _, _ in registered_files(selected, root)]
            if not matched:
                raise ValueError(f"{source_id}: missing registered pattern: {pattern}")
            paths.extend(matched)
        result[source_id] = paths
    return result


def _changes(previous, current):
    """두 기록의 자료·모델 키 차이를 결정적인 순서로 계산한다."""
    # 버전과 선언된 changed를 신뢰하지 않고 두 영역의 값으로 재계산한다.
    changed = []
    for section in ("data_versions", "model_versions"):
        old, new = previous[section] if previous is not None else {}, current[section]
        changed.extend(f"{section}.{key}" for key in sorted(old.keys() | new.keys())
                       if key not in old or key not in new or old[key] != new[key])
    return changed


def _deleted_files(previous, root):
    """이전 기록에 있었으나 현재 사라진 파일을 오류로 반환한다."""
    # 현재 등록부나 모델 목록에서 빠진 파일도 물리적 삭제 여부를 검사한다.
    if previous is None:
        return []
    files = set(previous["model_versions"])
    for source in previous["data_versions"].values():
        files.update(source["files"])
    return [f"previous: missing file: {relative}" for relative in sorted(files)
            if not (root / relative).is_file()]


def build(previous: dict | None, *, root, registry, model_files, holdout_reference) -> dict:
    """등록 패턴·이전 파일의 존재를 확인하고 변경 버전과 해시를 만든다."""
    # 누락을 빈 파일 목록이나 정상적인 버전 증가로 받아들이지 않는다.
    root = Path(root).resolve()
    sources = load_registry(root / "config/flood_traces.yaml") if registry is None else registry
    paths = _registered_paths(sources, root)
    errors = _deleted_files(previous, root)
    if errors:
        raise ValueError("; ".join(errors))
    data_versions = {key: {"role": source["role"], "files": vector_manifest(paths[key], root)}
                     for key, source in sources.items()}
    model_versions = {}
    for file in model_files:
        path = (root / file).resolve()
        model_versions[path.relative_to(root).as_posix()] = file_sha256(path)

    # 실제 영역 차이로 변경 목록과 버전 전환을 함께 결정한다.
    changed = _changes(previous, {"data_versions": data_versions, "model_versions": model_versions})
    previous_version = previous["version"] if previous is not None else None
    version = 1 if previous is None else previous_version + bool(changed)
    return {"version": version, "previous_version": previous_version,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "data_versions": data_versions, "model_versions": model_versions,
            "holdout_reference": holdout_reference, "changed": changed}


def validate(manifest, root, previous=None) -> list[str]:
    """등록 패턴·파일 무결성·변경 목록과 이전 기록 기반 버전 전환을 검사한다."""
    # 최초 기록과 이전 기록이 있는 전환을 구분해 스키마를 검사한다.
    errors = [f"missing required key: {key}" for key in REQUIRED_KEYS if key not in manifest]
    version, previous_version = manifest.get("version"), manifest.get("previous_version")
    valid_version = type(version) is int and version >= 1
    if not valid_version:
        errors.append("version must be an integer >= 1")
    if previous_version is not None and (type(previous_version) is not int or previous_version < 1):
        errors.append("previous_version must be an integer >= 1 or null")
    changed = manifest.get("changed")
    if not isinstance(changed, list) or any(not isinstance(key, str) for key in changed):
        errors.append("changed must be a list of strings")
    if previous is None:
        if version != 1 or previous_version is not None:
            errors.append("initial version must be 1 with previous_version null")
    else:
        try:
            actual = _changes(previous, manifest)
            if changed != actual:
                errors.append("changed does not match recomputed data_versions/model_versions changes")
            old_version = previous["version"]
            if type(old_version) is not int or old_version < 1:
                errors.append("previous record version must be an integer >= 1")
            elif previous_version != old_version or (valid_version and version != old_version + bool(actual)):
                errors.append("version transition violates recomputed changes/previous record rule")
        except (KeyError, TypeError, AttributeError) as exc:
            errors.append(f"cannot recompute changed: {exc}")

    # 등록 패턴과 이전 파일은 현재 manifest에 생략되었더라도 검사한다.
    root = Path(root).resolve()
    try:
        sources = load_registry(root / "config/flood_traces.yaml")
        paths = _registered_paths(sources, root)
        for source_id, files in paths.items():
            recorded = manifest.get("data_versions", {}).get(source_id, {}).get("files", {})
            expected = vector_manifest(files, root)
            if not expected or not set(expected).issubset(recorded):
                errors.append(f"{source_id}: registered files missing from manifest")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(f"registry: {exc}")
    try:
        errors.extend(_deleted_files(previous, root))
    except (KeyError, TypeError, AttributeError) as exc:
        errors.append(f"previous file inventory invalid: {exc}")

    # 잘못된 파일 목록은 오류로 남기고 정상 목록의 해시 검사를 계속한다.
    root = Path(root).resolve()
    groups = [("model_versions", manifest.get("model_versions", {}))]
    data = manifest.get("data_versions", {})
    if not isinstance(data, dict):
        errors.append("data_versions must be a mapping")
    else:
        for source_id, source in data.items():
            if not isinstance(source, dict) or not isinstance(source.get("files"), dict):
                errors.append(f"data_versions.{source_id}.files must be a mapping")
                continue
            groups.append((f"data_versions.{source_id}", source["files"]))
    for group, files in groups:
        if not isinstance(files, dict):
            errors.append(f"{group} must be a mapping")
            continue
        for relative, expected in files.items():
            try:
                path = (root / relative).resolve()
                if Path(relative).is_absolute() or not path.is_relative_to(root):
                    errors.append(f"{group}: path must be relative to root: {relative}")
                elif not path.is_file():
                    errors.append(f"{group}: missing file: {relative}")
                elif file_sha256(path) != expected:
                    errors.append(f"{group}: sha256 mismatch: {relative}")
            except (OSError, TypeError, ValueError) as exc:
                errors.append(f"{group}: {relative}: {exc}")
    return errors
