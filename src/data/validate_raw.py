"""Validate immutable raw inputs against ``config/data_contracts.yaml``.

The validator intentionally separates structural failures (``error``) from
quality decisions that need an explicit cleaning rule (``warning``).  Use
``--fail-on warning`` for the research-stage gate and ``--fail-on error`` to
check only that downloads and schemas are intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}


def display_path(path: Path, base: Path = PROJECT_ROOT) -> str:
    """Return a stable repository-relative path when possible."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


@dataclass
class DatasetResult:
    name: str
    kind: str
    description: str
    files: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)

    def add(self, severity: str, code: str, message: str, **details: Any) -> None:
        self.findings.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "details": details,
            }
        )

    @property
    def status(self) -> str:
        active = [item for item in self.findings if not item.get("waived", False)]
        if any(item["severity"] == "error" for item in active):
            return "error"
        if any(item["severity"] == "warning" for item in active):
            return "warning"
        return "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "status": self.status,
            "files": self.files,
            "metrics": self.metrics,
            "findings": self.findings,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_worktree_provenance() -> dict[str, Any]:
    """Bind evidence to tracked diffs and the contents of untracked files."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        if not status:
            return {"git_dirty": False, "git_diff_sha256": None}

        digest = hashlib.sha256()
        digest.update(b"TRACKED_DIFF\0")
        digest.update(
            subprocess.run(
                ["git", "diff", "--binary", "HEAD", "--", "."],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
            ).stdout
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        digest.update(b"\0UNTRACKED\0")
        for raw_path in sorted(path for path in untracked if path):
            relative = raw_path.decode("utf-8", errors="surrogateescape")
            path = PROJECT_ROOT / relative
            digest.update(raw_path)
            digest.update(b"\0")
            if path.is_file():
                digest.update(sha256_file(path).encode("ascii"))
            digest.update(b"\0")
        return {"git_dirty": True, "git_diff_sha256": digest.hexdigest()}
    except (OSError, subprocess.CalledProcessError):
        return {"git_dirty": None, "git_diff_sha256": None}


def finding_fingerprint(result: DatasetResult, finding: dict[str, Any]) -> str:
    payload = {
        "dataset": result.name,
        "severity": finding["severity"],
        "code": finding["code"],
        "details": finding.get("details", {}),
        "input_sha256": sorted(item["sha256"] for item in result.files),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def apply_waivers(
    results: list[DatasetResult],
    waiver_path: Path | None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    if waiver_path and waiver_path.exists():
        try:
            document = yaml.safe_load(waiver_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            document = {}
            invalid.append({"entry": None, "errors": [f"waiver YAML read/parse failure: {exc}"]})
        if not isinstance(document, dict) or not isinstance(document.get("waivers", []), list):
            invalid.append({"entry": None, "errors": ["top-level waivers must be a list"]})
        else:
            entries = document.get("waivers", [])

    required_fields = {
        "fingerprint",
        "dataset",
        "code",
        "owner",
        "reason",
        "cleaning_rule",
        "expires_on",
    }
    validated_entries: list[dict[str, Any]] = []
    fingerprints: list[str] = []
    for index, entry in enumerate(entries):
        errors: list[str] = []
        if not isinstance(entry, dict):
            invalid.append({"entry": index, "errors": ["waiver entry must be a mapping"]})
            continue
        missing = sorted(required_fields - set(entry))
        if missing:
            errors.append(f"missing required fields: {', '.join(missing)}")
        for field in required_fields - {"expires_on"}:
            if field in entry and (not isinstance(entry[field], str) or not entry[field].strip()):
                errors.append(f"{field} must be a non-empty string")
        fingerprint = entry.get("fingerprint")
        if isinstance(fingerprint, str) and not re.fullmatch(r"[0-9a-f]{16}", fingerprint):
            errors.append("fingerprint must be 16 lowercase hexadecimal characters")
        expires_on = entry.get("expires_on")
        if expires_on is None or (isinstance(expires_on, str) and not expires_on.strip()):
            errors.append("expires_on must be a non-empty ISO date (YYYY-MM-DD)")
        else:
            try:
                date.fromisoformat(str(expires_on))
            except (TypeError, ValueError):
                errors.append("expires_on must be a valid ISO date (YYYY-MM-DD)")
        if errors:
            invalid.append({"entry": index, "fingerprint": fingerprint, "errors": errors})
            continue
        validated_entries.append(entry)
        fingerprints.append(fingerprint)

    duplicate_fingerprints = sorted(
        fingerprint for fingerprint in set(fingerprints) if fingerprints.count(fingerprint) > 1
    )
    if duplicate_fingerprints:
        invalid.extend(
            {
                "entry": None,
                "fingerprint": fingerprint,
                "errors": ["duplicate fingerprint"],
            }
            for fingerprint in duplicate_fingerprints
        )
    by_fingerprint = {
        entry["fingerprint"]: entry
        for entry in validated_entries
        if entry["fingerprint"] not in duplicate_fingerprints
    }
    used: set[str] = set()
    expired: set[str] = set()

    for result in results:
        for finding in result.findings:
            fingerprint = finding_fingerprint(result, finding)
            finding["fingerprint"] = fingerprint
            waiver = by_fingerprint.get(fingerprint)
            if not waiver or finding["severity"] != "warning":
                continue
            expires_on = waiver.get("expires_on")
            if expires_on and date.fromisoformat(str(expires_on)) < date.today():
                expired.add(fingerprint)
                continue
            if waiver["dataset"] != result.name:
                continue
            if waiver["code"] != finding["code"]:
                continue
            finding["waived"] = True
            finding["waiver"] = {
                key: (
                    str(waiver[key])
                    if isinstance(waiver[key], (date, datetime))
                    else waiver[key]
                )
                for key in ("owner", "reason", "cleaning_rule", "expires_on")
                if key in waiver
            }
            used.add(fingerprint)

    return {
        "path": display_path(waiver_path) if waiver_path else None,
        "declared": len(entries),
        "applied": len(used),
        "unused": sorted(set(by_fingerprint) - used - expired),
        "expired": sorted(expired),
        "invalid": invalid,
    }


def resolve_files(raw_root: Path, spec: dict[str, Any]) -> list[Path]:
    patterns = spec.get("globs") or [spec["glob"]]
    return sorted({path for pattern in patterns for path in raw_root.glob(pattern)})


def record_files(result: DatasetResult, paths: list[Path], raw_root: Path) -> None:
    result.metrics["artifact_file_count"] = len(paths)
    for path in paths:
        pointer = is_lfs_pointer(path)
        result.files.append(
            {
                "path": display_path(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "lfs_pointer": pointer,
            }
        )
        if pointer:
            result.add(
                "error",
                "lfs_pointer",
                "Git LFS 원본 대신 포인터 파일이 체크아웃되어 있습니다.",
                path=str(path.relative_to(raw_root)),
            )


def validate_file_counts(result: DatasetResult, paths: list[Path], spec: dict[str, Any]) -> None:
    result.metrics["file_count"] = len(paths)
    if "expected_files" in spec and len(paths) != spec["expected_files"]:
        result.add(
            "error",
            "file_count",
            f"파일 수가 계약과 다릅니다: {len(paths)} != {spec['expected_files']}",
        )
    if not paths:
        result.add("error", "missing_files", "계약 경로에 일치하는 파일이 없습니다.")


def check_size(result: DatasetResult, path: Path, spec: dict[str, Any]) -> None:
    size = path.stat().st_size
    if "exact_bytes_per_file" in spec and size != spec["exact_bytes_per_file"]:
        result.add(
            "error",
            "file_size",
            "파일 크기가 계약과 다릅니다.",
            path=str(path),
            actual=size,
            expected=spec["exact_bytes_per_file"],
        )
    if "min_bytes_per_file" in spec and size < spec["min_bytes_per_file"]:
        result.add(
            "error",
            "file_size",
            "파일 크기가 계약 최소값보다 작습니다.",
            path=str(path),
            actual=size,
            minimum=spec["min_bytes_per_file"],
        )


def add_threshold_finding(
    result: DatasetResult,
    actual: int | float,
    maximum: int | float,
    severity: str,
    code: str,
    message: str,
) -> None:
    if actual > maximum:
        result.add(severity, code, message, actual=actual, maximum=maximum)


def validate_csv(result: DatasetResult, paths: list[Path], spec: dict[str, Any]) -> None:
    row_counts: dict[str, int] = {}
    exact_duplicates = 0
    key_duplicates = 0
    invalid_dates = 0
    below_min = 0
    above_max = 0
    sentinel_counts: dict[str, int] = {}
    max_null_ratio = 0.0
    observed_values: dict[str, set[str]] = {
        column: set() for column in spec.get("allowed_values", {})
    }
    variable_values: set[str] = set()
    profile_unique_values: dict[str, set[str]] = {
        column: set() for column in spec.get("profile_unique_columns", [])
    }
    observed_dates: list[pd.Timestamp] = []

    for path in paths:
        if is_lfs_pointer(path):
            continue
        header = 0 if spec.get("header", True) else None
        names = None if header == 0 else spec.get("columns")
        try:
            frame = pd.read_csv(
                path,
                encoding=spec.get("encoding", "utf-8"),
                header=header,
                names=names,
                low_memory=False,
            )
        except Exception as exc:  # pandas exposes several parser/codec exceptions
            result.add("error", "csv_read", f"CSV를 읽지 못했습니다: {exc}", path=str(path))
            continue

        relative = display_path(path)
        row_counts[relative] = len(frame)
        required = set(spec.get("required_columns", []))
        missing = sorted(required - set(frame.columns))
        if missing:
            result.add("error", "missing_columns", "필수 컬럼이 없습니다.", path=relative, columns=missing)

        if "exact_rows_per_file" in spec and len(frame) != spec["exact_rows_per_file"]:
            result.add(
                "error",
                "row_count",
                "행 수가 계약과 다릅니다.",
                path=relative,
                actual=len(frame),
                expected=spec["exact_rows_per_file"],
            )
        if "min_rows_per_file" in spec and len(frame) < spec["min_rows_per_file"]:
            result.add(
                "error",
                "row_count",
                "행 수가 계약 최소값보다 작습니다.",
                path=relative,
                actual=len(frame),
                minimum=spec["min_rows_per_file"],
            )

        quality = spec.get("quality", {})
        exact_duplicates += int(frame.duplicated().sum())
        key_columns = spec.get("key_columns", [])
        if key_columns and all(column in frame for column in key_columns):
            key_duplicates += int(frame.duplicated(key_columns).sum())

        date_column = quality.get("date_column")
        if date_column in frame:
            parsed_dates = pd.to_datetime(
                frame[date_column],
                format=quality.get("date_format"),
                errors="coerce",
            )
            invalid_dates += int(parsed_dates.isna().sum())
            valid_dates = parsed_dates.dropna()
            if not valid_dates.empty:
                observed_dates.extend([valid_dates.min(), valid_dates.max()])

        for column, values in profile_unique_values.items():
            if column in frame:
                values.update(frame[column].dropna().astype(str).unique())

        numeric_pattern = quality.get("numeric_columns_regex")
        if numeric_pattern:
            numeric_columns = [column for column in frame if re.fullmatch(numeric_pattern, str(column))]
            if not numeric_columns:
                result.add("error", "numeric_columns", "수치 컬럼 패턴과 일치하는 컬럼이 없습니다.", path=relative)
            else:
                numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
                numeric_for_range = numeric.copy()
                for sentinel in quality.get("sentinel_values", []):
                    count = int((numeric == sentinel).sum().sum())
                    if count:
                        sentinel_counts[str(sentinel)] = sentinel_counts.get(str(sentinel), 0) + count
                    numeric_for_range = numeric_for_range.mask(numeric_for_range == sentinel)
                if "min_numeric_value" in quality:
                    below_min += int(
                        (numeric_for_range < quality["min_numeric_value"]).sum().sum()
                    )
                if "max_numeric_value" in quality:
                    above_max += int(
                        (numeric_for_range > quality["max_numeric_value"]).sum().sum()
                    )

        null_columns = quality.get("null_columns") or list(frame.columns)
        existing_null_columns = [column for column in null_columns if column in frame]
        if existing_null_columns:
            max_null_ratio = max(max_null_ratio, float(frame[existing_null_columns].isna().mean().max()))

        for column, allowed in spec.get("allowed_values", {}).items():
            if column in frame:
                observed_values[column].update(frame[column].dropna().astype(str).unique())
                allowed_strings = {str(value) for value in allowed}
                unexpected = sorted(observed_values[column] - allowed_strings)
                if unexpected:
                    result.add(
                        "error",
                        "unexpected_values",
                        "허용되지 않은 값이 있습니다.",
                        path=relative,
                        column=column,
                        values=unexpected[:20],
                    )

        variable_column = spec.get("variable_column")
        if variable_column in frame:
            variable_values.update(frame[variable_column].dropna().astype(str).unique())
            pattern = spec.get("variable_regex")
            unexpected = sorted(value for value in variable_values if pattern and not re.fullmatch(pattern, value))
            if unexpected:
                result.add(
                    "error",
                    "variable_code",
                    "변수 코드가 계약 패턴과 다릅니다.",
                    path=relative,
                    values=unexpected[:20],
                )

    result.metrics.update(
        {
            "rows_by_file": row_counts,
            "total_rows": sum(row_counts.values()),
            "exact_duplicate_rows": exact_duplicates,
            "duplicate_key_rows": key_duplicates,
            "invalid_dates": invalid_dates,
            "values_below_min": below_min,
            "values_above_max": above_max,
            "sentinel_counts": sentinel_counts,
            "max_null_ratio": round(max_null_ratio, 6),
            "variable_values": sorted(variable_values),
            "unique_counts": {
                column: len(values) for column, values in profile_unique_values.items()
            },
            "date_range": {
                "min": min(observed_dates).date().isoformat() if observed_dates else None,
                "max": max(observed_dates).date().isoformat() if observed_dates else None,
            },
        }
    )

    quality = spec.get("quality", {})
    add_threshold_finding(
        result,
        exact_duplicates,
        quality.get("max_exact_duplicate_rows", float("inf")),
        quality.get("duplicate_severity", "warning"),
        "exact_duplicates",
        "완전 중복 행이 허용치를 초과합니다.",
    )
    add_threshold_finding(
        result,
        key_duplicates,
        quality.get("max_duplicate_key_rows", float("inf")),
        quality.get("duplicate_severity", "warning"),
        "duplicate_keys",
        "키 중복 행이 허용치를 초과합니다.",
    )
    add_threshold_finding(
        result,
        invalid_dates,
        quality.get("max_invalid_dates", float("inf")),
        quality.get("date_severity", "warning"),
        "invalid_dates",
        "파싱할 수 없는 날짜가 허용치를 초과합니다.",
    )
    if below_min or above_max:
        result.add(
            quality.get("range_severity", "warning"),
            "numeric_range",
            "수치 범위를 벗어난 값이 있습니다.",
            below_min=below_min,
            above_max=above_max,
        )
    if sentinel_counts:
        result.add(
            quality.get("sentinel_severity", "warning"),
            "sentinel_values",
            "분석 전 결측 처리 규칙이 필요한 센티널 값이 있습니다.",
            counts=sentinel_counts,
        )
    add_threshold_finding(
        result,
        max_null_ratio,
        quality.get("max_null_ratio", float("inf")),
        quality.get("null_severity", "warning"),
        "null_ratio",
        "결측률이 계약 허용치를 초과합니다.",
    )
    validate_csv_advanced_profiles(result, paths, spec)


def validate_csv_advanced_profiles(
    result: DatasetResult,
    paths: list[Path],
    spec: dict[str, Any],
) -> None:
    """Run cross-file, temporal-coverage, numeric and aggregate checks."""
    quality = spec.get("quality", {})
    key_columns = spec.get("key_columns", [])
    seen_key_hashes: set[int] = set()
    cross_file_duplicate_keys = 0
    numeric_parse_failures = 0
    dates_before_min = 0
    dates_after_max = 0
    coverage_parts: list[pd.DataFrame] = []
    consistency_parts: list[pd.DataFrame] = []

    for path in paths:
        if is_lfs_pointer(path):
            continue
        header = 0 if spec.get("header", True) else None
        names = None if header == 0 else spec.get("columns")
        try:
            frame = pd.read_csv(
                path,
                encoding=spec.get("encoding", "utf-8"),
                header=header,
                names=names,
                low_memory=False,
            )
        except Exception:
            continue

        if key_columns and all(column in frame for column in key_columns):
            key_frame = frame[key_columns].astype("string").fillna("<NA>")
            file_key_hashes = {
                int(value)
                for value in pd.util.hash_pandas_object(key_frame, index=False).unique()
            }
            cross_file_duplicate_keys += len(file_key_hashes & seen_key_hashes)
            seen_key_hashes.update(file_key_hashes)

        numeric_pattern = quality.get("numeric_columns_regex")
        if numeric_pattern:
            numeric_columns = [
                column for column in frame if re.fullmatch(numeric_pattern, str(column))
            ]
            if numeric_columns:
                numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
                numeric_parse_failures += int(
                    (frame[numeric_columns].notna() & numeric.isna()).sum().sum()
                )

        date_column = quality.get("date_column")
        parsed_dates: pd.Series | None = None
        if date_column in frame:
            parsed_dates = pd.to_datetime(
                frame[date_column],
                format=quality.get("date_format"),
                errors="coerce",
            )
            valid_dates = parsed_dates.dropna()
            if quality.get("min_allowed_date"):
                dates_before_min += int(
                    (valid_dates < pd.Timestamp(quality["min_allowed_date"])).sum()
                )
            if quality.get("max_allowed_date"):
                dates_after_max += int(
                    (valid_dates > pd.Timestamp(quality["max_allowed_date"])).sum()
                )

        coverage = spec.get("coverage")
        if coverage:
            group_columns = coverage.get("group_columns", [])
            coverage_date_column = coverage.get("date_column")
            needed = [*group_columns, coverage_date_column]
            if all(column in frame for column in needed):
                coverage_dates = (
                    parsed_dates
                    if coverage_date_column == date_column and parsed_dates is not None
                    else pd.to_datetime(
                        frame[coverage_date_column],
                        format=coverage.get("date_format"),
                        errors="coerce",
                    )
                )
                part = frame[group_columns].copy()
                part["__date"] = coverage_dates
                pattern = coverage.get("numeric_columns_regex")
                value_columns = [
                    column for column in frame if pattern and re.fullmatch(pattern, str(column))
                ]
                if value_columns:
                    values = frame[value_columns].apply(pd.to_numeric, errors="coerce")
                    for sentinel in coverage.get("sentinel_values", []):
                        values = values.mask(values == sentinel)
                    part["__nonzero_values"] = (values.fillna(0) != 0).sum(axis=1)
                    part["__valid_values"] = values.notna().sum(axis=1)
                else:
                    part["__nonzero_values"] = 0
                    part["__valid_values"] = 0
                coverage_parts.append(part)

        consistency = spec.get("consistency")
        if consistency:
            required = [
                *consistency["group_columns"],
                consistency["variable_column"],
                consistency["value_column"],
            ]
            if all(column in frame for column in required):
                relevant_variables = {
                    consistency["total_variable"],
                    *consistency["part_variables"],
                }
                consistency_parts.append(
                    frame.loc[
                        frame[consistency["variable_column"]].isin(relevant_variables),
                        required,
                    ].copy()
                )

    result.metrics.update(
        {
            "cross_file_duplicate_keys": cross_file_duplicate_keys,
            "numeric_parse_failures": numeric_parse_failures,
            "dates_before_min": dates_before_min,
            "dates_after_max": dates_after_max,
        }
    )
    add_threshold_finding(
        result,
        cross_file_duplicate_keys,
        quality.get(
            "max_cross_file_duplicate_keys",
            quality.get("max_duplicate_key_rows", float("inf")),
        ),
        quality.get("duplicate_severity", "warning"),
        "cross_file_duplicate_keys",
        "서로 다른 파일 사이에 동일한 키가 있습니다.",
    )
    add_threshold_finding(
        result,
        numeric_parse_failures,
        quality.get("max_numeric_parse_failures", 0),
        quality.get("numeric_parse_severity", "error"),
        "numeric_parse",
        "수치 컬럼에 숫자로 변환할 수 없는 값이 있습니다.",
    )
    if dates_before_min or dates_after_max:
        result.add(
            quality.get("date_range_severity", "warning"),
            "date_range",
            "분석 허용 범위를 벗어난 날짜가 있습니다.",
            before_min=dates_before_min,
            after_max=dates_after_max,
            minimum=quality.get("min_allowed_date"),
            maximum=quality.get("max_allowed_date"),
        )

    if coverage_parts:
        coverage = spec["coverage"]
        coverage_frame = pd.concat(coverage_parts, ignore_index=True)
        start = pd.Timestamp(coverage["analysis_start"])
        end = pd.Timestamp(coverage["analysis_end"])
        expected_days = (end - start).days + 1
        coverage_frame = coverage_frame[
            coverage_frame["__date"].between(start, end, inclusive="both")
        ]
        group_columns = coverage["group_columns"]
        groups: list[dict[str, Any]] = []
        min_valid_values_per_day = coverage.get("min_valid_values_per_day", 1)
        for group_key, group in coverage_frame.groupby(group_columns, dropna=False):
            key_values = group_key if isinstance(group_key, tuple) else (group_key,)
            row_days = int(group["__date"].nunique())
            valid_days = int(
                group.loc[
                    group["__valid_values"] >= min_valid_values_per_day,
                    "__date",
                ].nunique()
            )
            groups.append(
                {
                    **{column: str(value) for column, value in zip(group_columns, key_values)},
                    "rows": len(group),
                    "first": group["__date"].min().date().isoformat(),
                    "last": group["__date"].max().date().isoformat(),
                    "row_days": row_days,
                    "valid_days": valid_days,
                    "coverage_ratio": round(valid_days / expected_days, 6),
                    "nonzero_values": int(group["__nonzero_values"].sum()),
                    "valid_values": int(group["__valid_values"].sum()),
                }
            )
        minimum_ratio = coverage.get("min_coverage_ratio", 0)
        groups_meeting = sum(item["coverage_ratio"] >= minimum_ratio for item in groups)
        result.metrics["coverage"] = {
            "analysis_start": start.date().isoformat(),
            "analysis_end": end.date().isoformat(),
            "expected_days": expected_days,
            "min_coverage_ratio": minimum_ratio,
            "min_valid_values_per_day": min_valid_values_per_day,
            "groups_meeting_coverage": groups_meeting,
            "groups": groups,
        }
        minimum_groups = coverage.get("min_groups_meeting_coverage", 0)
        if groups_meeting < minimum_groups:
            result.add(
                coverage.get("severity", "warning"),
                "temporal_coverage",
                "분석기간 완전성 기준을 충족한 지점 수가 부족합니다.",
                actual=groups_meeting,
                minimum=minimum_groups,
            )

    if consistency_parts:
        consistency = spec["consistency"]
        frame = pd.concat(consistency_parts, ignore_index=True)
        value_column = consistency["value_column"]
        frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce")
        pivot = frame.pivot_table(
            index=consistency["group_columns"],
            columns=consistency["variable_column"],
            values=value_column,
            aggfunc="first",
        )
        required_variables = [
            consistency["total_variable"],
            *consistency["part_variables"],
        ]
        complete = pivot.dropna(subset=required_variables)
        complete_ratio = len(complete) / len(pivot) if len(pivot) else 0.0
        differences = (
            complete[consistency["part_variables"]].sum(axis=1)
            - complete[consistency["total_variable"]]
        ).abs()
        violations = int(
            (differences > consistency.get("max_abs_difference", 0)).sum()
        )
        metrics = {
            "groups": len(pivot),
            "complete_groups": len(complete),
            "complete_ratio": round(complete_ratio, 6),
            "max_abs_difference": float(differences.max()) if not differences.empty else 0.0,
            "violations": violations,
        }
        result.metrics["consistency"] = metrics
        if complete_ratio < consistency.get("min_complete_ratio", 1.0) or violations:
            result.add(
                consistency.get("severity", "error"),
                "aggregate_consistency",
                "총계와 부분합의 정합성이 계약을 벗어납니다.",
                **metrics,
            )


def read_dbf_schema(path: Path) -> tuple[int, list[str]]:
    with path.open("rb") as handle:
        header = handle.read(32)
        if len(header) != 32:
            raise ValueError("DBF header is truncated")
        records = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        fields: list[str] = []
        while handle.tell() < header_length - 1:
            descriptor = handle.read(32)
            if not descriptor or descriptor[0] == 0x0D:
                break
            fields.append(descriptor[:11].split(b"\0", 1)[0].decode("ascii", errors="replace"))
    return records, fields


def validate_shapefile(result: DatasetResult, paths: list[Path], spec: dict[str, Any]) -> None:
    records_by_file: dict[str, int] = {}
    pyproj_crs = None
    if spec.get("crs_reader") == "pyproj":
        try:
            from pyproj import CRS  # type: ignore
        except ImportError:
            result.add(
                "warning",
                "crs_semantic_unchecked",
                "pyproj가 없어 PRJ 좌표계를 EPSG 코드로 의미 검증하지 못했습니다.",
            )
        else:
            pyproj_crs = CRS
    for shp_path in paths:
        if is_lfs_pointer(shp_path):
            continue
        relative = display_path(shp_path)
        with shp_path.open("rb") as handle:
            header = handle.read(100)
        if len(header) < 100 or struct.unpack(">i", header[:4])[0] != 9994:
            result.add("error", "shapefile_header", "SHP 헤더가 올바르지 않습니다.", path=relative)

        for suffix in spec.get("required_sidecars", []):
            sidecar = shp_path.with_suffix(suffix)
            if not sidecar.exists():
                result.add("error", "missing_sidecar", "Shapefile 구성 파일이 없습니다.", path=str(sidecar))

        dbf_path = shp_path.with_suffix(".dbf")
        if dbf_path.exists() and not is_lfs_pointer(dbf_path):
            try:
                records, fields = read_dbf_schema(dbf_path)
                records_by_file[relative] = records
                missing = sorted(set(spec.get("required_dbf_fields", [])) - set(fields))
                if missing:
                    result.add("error", "dbf_fields", "DBF 필수 필드가 없습니다.", path=relative, fields=missing)
                if records < spec.get("min_records_per_file", 0):
                    result.add(
                        "error",
                        "dbf_records",
                        "DBF 레코드 수가 계약 최소값보다 작습니다.",
                        path=relative,
                        actual=records,
                        minimum=spec["min_records_per_file"],
                    )
            except (OSError, ValueError, struct.error) as exc:
                result.add("error", "dbf_read", f"DBF 메타데이터를 읽지 못했습니다: {exc}", path=relative)

        prj_path = shp_path.with_suffix(".prj")
        if prj_path.exists() and not is_lfs_pointer(prj_path):
            prj_text = prj_path.read_text(encoding="utf-8", errors="replace")
            missing_tokens = [token for token in spec.get("prj_contains", []) if token not in prj_text]
            if missing_tokens:
                result.add(
                    "error",
                    "crs",
                    "PRJ가 예상 좌표계 토큰을 포함하지 않습니다.",
                    path=relative,
                    missing=missing_tokens,
                )
            if pyproj_crs and spec.get("expected_crs"):
                try:
                    actual_crs = pyproj_crs.from_wkt(prj_text).to_epsg()
                except Exception as exc:
                    result.add(
                        "error",
                        "crs_parse",
                        f"PRJ 좌표계를 해석하지 못했습니다: {exc}",
                        path=relative,
                    )
                else:
                    expected_epsg = int(str(spec["expected_crs"]).split(":")[-1])
                    if actual_crs != expected_epsg:
                        result.add(
                            "error",
                            "crs_semantic",
                            "PRJ의 실제 EPSG가 계약과 다릅니다.",
                            path=relative,
                            actual=actual_crs,
                            expected=expected_epsg,
                        )

    result.metrics["records_by_file"] = records_by_file
    result.metrics["expected_crs"] = spec.get("expected_crs")


def validate_raster(result: DatasetResult, paths: list[Path], spec: dict[str, Any]) -> None:
    for path in paths:
        if is_lfs_pointer(path):
            continue
        check_size(result, path, spec)
        magic = spec.get("magic_ascii")
        if magic:
            with path.open("rb") as handle:
                actual = handle.read(len(magic)).decode("ascii", errors="replace")
            if actual != magic:
                result.add("error", "raster_magic", "래스터 파일 시그니처가 다릅니다.", path=str(path))

    reader = spec.get("metadata_reader")
    if reader == "rasterio":
        try:
            import rasterio  # type: ignore
        except ImportError:
            result.add(
                "warning",
                "raster_metadata_unchecked",
                "rasterio가 없어 DEM의 CRS·해상도·NoData를 아직 검증하지 못했습니다.",
            )
        else:
            metadata: dict[str, Any] = {}
            for path in paths:
                if is_lfs_pointer(path):
                    continue
                try:
                    source_context = rasterio.open(path)
                except Exception as exc:
                    result.add(
                        "error",
                        "raster_open",
                        f"DEM을 열지 못했습니다: {exc}",
                        path=str(path),
                    )
                    continue
                with source_context as source:
                    metadata[display_path(path)] = {
                        "crs": str(source.crs),
                        "width": source.width,
                        "height": source.height,
                        "resolution": list(source.res),
                        "nodata": source.nodata,
                    }
                    expected_crs = spec.get("expected_crs")
                    if expected_crs and str(source.crs) != expected_crs:
                        result.add(
                            "error",
                            "crs",
                            "DEM 좌표계가 계약과 다릅니다.",
                            path=str(path),
                            actual=str(source.crs),
                            expected=expected_crs,
                        )
                    expected_driver = spec.get("expected_driver")
                    if expected_driver and source.driver != expected_driver:
                        result.add(
                            "error",
                            "raster_driver",
                            "DEM 드라이버가 계약과 다릅니다.",
                            path=str(path),
                            actual=source.driver,
                            expected=expected_driver,
                        )
                    expected_resolution = spec.get("expected_resolution")
                    if expected_resolution and any(
                        abs(actual - expected) > 1e-9
                        for actual, expected in zip(source.res, expected_resolution)
                    ):
                        result.add(
                            "error",
                            "raster_resolution",
                            "DEM 해상도가 계약과 다릅니다.",
                            path=str(path),
                            actual=list(source.res),
                            expected=expected_resolution,
                        )
                    expected_nodata = spec.get("expected_nodata")
                    if expected_nodata is not None and source.nodata != expected_nodata:
                        result.add(
                            "error",
                            "raster_nodata",
                            "DEM NoData 값이 계약과 다릅니다.",
                            path=str(path),
                            actual=source.nodata,
                            expected=expected_nodata,
                        )
                    width_range = spec.get("width_range")
                    if width_range and not width_range[0] <= source.width <= width_range[1]:
                        result.add(
                            "error",
                            "raster_width",
                            "DEM 폭이 계약 범위를 벗어납니다.",
                            path=str(path),
                            actual=source.width,
                            expected=width_range,
                        )
                    height_range = spec.get("height_range")
                    if height_range and not height_range[0] <= source.height <= height_range[1]:
                        result.add(
                            "error",
                            "raster_height",
                            "DEM 높이가 계약 범위를 벗어납니다.",
                            path=str(path),
                            actual=source.height,
                            expected=height_range,
                        )
            result.metrics["raster_metadata"] = metadata


def validate_contract(
    contract_path: Path,
    *,
    raw_root_override: Path | None = None,
    fail_on: str = "error",
    waiver_path: Path | None = None,
) -> dict[str, Any]:
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    raw_root = raw_root_override or PROJECT_ROOT / contract["raw_root"]
    results: list[DatasetResult] = []

    for name, spec in contract["datasets"].items():
        result = DatasetResult(name=name, kind=spec["kind"], description=spec.get("description", ""))
        result.metrics["source_url"] = spec.get("source_url")
        result.metrics["collected_at"] = (
            str(spec["collected_at"]) if spec.get("collected_at") is not None else None
        )
        paths = resolve_files(raw_root, spec)
        validate_file_counts(result, paths, spec)
        if paths:
            artifact_paths = list(paths)
            if spec["kind"] == "shapefile":
                artifact_paths.extend(
                    path.with_suffix(suffix)
                    for path in paths
                    for suffix in spec.get("required_sidecars", [])
                    if path.with_suffix(suffix).exists()
                )
            record_files(result, sorted(set(artifact_paths)), raw_root)
            for path in paths:
                check_size(result, path, spec)
            if spec["kind"] == "csv":
                validate_csv(result, paths, spec)
            elif spec["kind"] == "shapefile":
                validate_shapefile(result, paths, spec)
            elif spec["kind"] == "raster":
                validate_raster(result, paths, spec)
            else:
                result.add("error", "unknown_kind", f"지원하지 않는 데이터 종류입니다: {spec['kind']}")
        results.append(result)

    waiver_summary = apply_waivers(results, waiver_path)
    counts = {
        severity: sum(
            1
            for result in results
            for finding in result.findings
            if finding["severity"] == severity and not finding.get("waived", False)
        )
        for severity in SEVERITY_RANK
    }
    counts["waived"] = sum(
        1
        for result in results
        for finding in result.findings
        if finding.get("waived", False)
    )
    counts["waiver_errors"] = (
        len(waiver_summary["unused"])
        + len(waiver_summary["expired"])
        + len(waiver_summary["invalid"])
    )
    threshold = SEVERITY_RANK[fail_on]
    failed = counts["waiver_errors"] > 0 or any(
        SEVERITY_RANK[finding["severity"]] >= threshold
        for result in results
        for finding in result.findings
        if not finding.get("waived", False)
    )
    provenance = git_worktree_provenance()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        **provenance,
        "contract": str(contract_path.relative_to(PROJECT_ROOT)) if contract_path.is_relative_to(PROJECT_ROOT) else str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "validator_sha256": sha256_file(Path(__file__).resolve()),
        "waiver_sha256": (
            sha256_file(waiver_path)
            if waiver_path is not None and waiver_path.exists()
            else None
        ),
        "raw_root": str(raw_root),
        "fail_on": fail_on,
        "status": "fail" if failed else "pass",
        "finding_counts": counts,
        "waivers": waiver_summary,
        "datasets": [result.as_dict() for result in results],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="원본 데이터 계약·품질 게이트")
    parser.add_argument(
        "--contracts",
        type=Path,
        default=PROJECT_ROOT / "config" / "data_contracts.yaml",
        help="데이터 계약 YAML 경로",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=None,
        help="테스트용 raw 경로 재정의",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "validation" / "raw_validation.json",
        help="JSON 증거 파일 경로",
    )
    parser.add_argument(
        "--fail-on",
        choices=sorted(SEVERITY_RANK, key=SEVERITY_RANK.get),
        default="error",
        help="이 심각도 이상이면 종료 코드 1",
    )
    parser.add_argument(
        "--waivers",
        type=Path,
        default=PROJECT_ROOT / "config" / "raw_quality_waivers.yaml",
        help="finding fingerprint별 승인 예외 YAML 경로",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_contract(
        args.contracts.resolve(),
        raw_root_override=args.raw_root.resolve() if args.raw_root else None,
        fail_on=args.fail_on,
        waiver_path=args.waivers.resolve() if args.waivers else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"raw validation: {report['status'].upper()} ({report['fail_on']} 이상 차단)")
    if (
        report["waivers"]["unused"]
        or report["waivers"]["expired"]
        or report["waivers"]["invalid"]
    ):
        print(
            "  WAIVER ERROR: "
            f"unused={report['waivers']['unused']} expired={report['waivers']['expired']} "
            f"invalid={report['waivers']['invalid']}"
        )
    for dataset in report["datasets"]:
        metrics = dataset["metrics"]
        detail = f"files={metrics.get('file_count', 0)}"
        if "total_rows" in metrics:
            detail += f", rows={metrics['total_rows']}"
        print(f"  {dataset['status'].upper():7} {dataset['name']}: {detail}")
        for finding in dataset["findings"]:
            waived = " waived" if finding.get("waived") else ""
            print(
                f"    [{finding['severity']}{waived}] {finding['code']} "
                f"({finding['fingerprint']}): {finding['message']}"
            )
    print(f"evidence: {args.output}")
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
