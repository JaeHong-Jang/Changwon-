"""연대표 사건 명세의 시각을 실행 기록·git 커밋·gpkg·문서에서 직접 읽어 UTC·KST 로 확정한다."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
STAMP = re.compile(r"(\d{8}T\d{6})Z")


def parse_time(text: str) -> datetime:
    """ISO 시각(Z·오프셋) 또는 run_id 에 박힌 YYYYMMDDTHHMMSSZ 를 UTC 로 읽는다."""
    # run_id 형식을 먼저 찾고, 없으면 ISO 로 해석한다 (오프셋 없는 값은 UTC 로 본다)
    found = STAMP.search(text)
    if found:
        return datetime.strptime(found.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def json_time(root: Path, path: str, key: str) -> datetime:
    """JSON 파일에서 점으로 이은 키의 시각 값을 읽는다."""
    # 키 경로를 따라 내려간 뒤 문자열 시각을 해석한다
    value: Any = json.loads((root / path).read_text(encoding="utf-8"))
    for part in key.split("."):
        value = value[part]
    return parse_time(str(value))


def git_time(root: Path, commit: str) -> tuple[datetime, str]:
    """커밋의 작성 시각(author date)과 제목을 읽는다. 커밋이 없으면 예외다."""
    # %aI 는 오프셋이 붙은 ISO 시각이라 그대로 UTC 로 바꾼다
    out = subprocess.run(["git", "show", "-s", "--format=%aI%n%s", commit], cwd=root,
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return parse_time(out[0]), out[1] if len(out) > 1 else ""


def gpkg_time(root: Path, path: str) -> datetime:
    """GeoPackage 의 gpkg_contents.last_change (여러 표면 가장 늦은 값)를 읽는다."""
    # 읽기 전용 URI 로 열어 파일을 건드리지 않는다
    with closing(sqlite3.connect(f"file:{root / path}?mode=ro", uri=True)) as con:
        values = [row[0] for row in con.execute("select last_change from gpkg_contents")]
    return max(parse_time(v) for v in values)


def doc_has(root: Path, path: str, quote: str) -> bool:
    """문서에 인용 문장이 그대로 있는지 본다."""
    return quote in (root / path).read_text(encoding="utf-8")


def resolve(spec: dict[str, Any], root: Path) -> dict[str, Any]:
    """사건 하나의 출처를 읽어 시각·확인 여부·근거 문자열을 채운다."""
    # 명세의 공통 열을 먼저 옮긴다
    kind = spec["source"]
    row = {k: spec.get(k) for k in ("id", "class", "event", "precision", "note")} | {"source": kind}
    utc, verified, evidence = None, False, ""

    # 출처 종류별로 시각을 읽고, 인용이 있으면 원문에 있는지도 확인한다
    try:
        if kind == "json":
            utc, verified, evidence = json_time(root, spec["path"], spec["key"]), True, f"{spec['path']}#{spec['key']}"
        elif kind == "run_id":
            target = root / spec["path"]
            found = target.is_dir() or (target.is_file() and spec["run_id"] in target.read_text(encoding="utf-8"))
            utc, verified, evidence = parse_time(spec["run_id"]), found, f"{spec['path']} ({spec['run_id']})"
        elif kind == "git":
            utc, subject = git_time(root, spec["commit"])
            verified = spec.get("quote", "") in subject
            evidence = f"commit {spec['commit']} «{subject}»"
        elif kind == "gpkg":
            utc, verified, evidence = gpkg_time(root, spec["path"]), True, f"{spec['path']}#gpkg_contents.last_change"
        elif kind == "doc":
            verified, evidence = doc_has(root, spec["path"], spec["quote"]), f"{spec['path']} «{spec['quote']}»"
        elif kind == "none":
            verified, evidence = True, spec.get("evidence", "")
        else:
            raise ValueError(f"알 수 없는 출처 종류: {kind}")
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError, sqlite3.Error) as error:
        evidence = f"해석 실패: {type(error).__name__}: {error}"

    # UTC 와 KST 를 초 단위 ISO 로 적고, 문서 날짜(한국 날짜)는 KST 칸에 날짜만 둔다
    row["utc"] = utc.isoformat(timespec="seconds") if utc else None
    row["kst"] = utc.astimezone(KST).isoformat(timespec="seconds") if utc else spec.get("date")
    return row | {"verified": verified, "evidence": evidence}


def resolve_all(specs: list[dict[str, Any]], root: Path) -> Any:
    """명세 순서대로 모든 사건을 확정한 표를 만든다."""
    import pandas as pd

    # 열 순서를 고정해 문서와 CSV 가 같은 모양이 되게 한다
    columns = ["id", "class", "utc", "kst", "precision", "event", "source", "evidence", "verified", "note"]
    return pd.DataFrame([resolve(s, root) for s in specs], columns=columns)
