"""실행 기록 공통 함수: 파일 해시, JSON 저장, 원본 manifest, 패키지 버전, git 상태."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    """파일 내용을 1 MB 단위로 읽어 SHA256 을 구한다."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    """NaN 없이 UTF-8 JSON 으로 저장한다."""
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                          encoding="utf-8")


def atomic_write_json(path: Path, value: Any) -> None:
    """같은 폴더의 임시 JSON을 동기화한 뒤 원자적으로 교체한다."""
    # 기존 공통 함수는 바꾸지 않고 원자적 저장 의존성만 불러온다.
    import os
    import tempfile

    # 쓰기·동기화·교체 실패 시 기존 파일을 보존하고 임시 파일을 지운다.
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException as error:
        # 정리 오류는 메모로 남기고 원래 저장 예외를 그대로 전파한다.
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                error.add_note(f"임시 파일 정리 실패: {temporary}: {cleanup_error}")
        raise


def vector_manifest(paths: list[Path], root: Path) -> dict[str, str]:
    """벡터 파일과 같은 이름의 부속 파일(.dbf·.shx·.prj·.cpg 등)의 해시."""
    # 같은 stem 을 가진 파일을 모두 모은다
    files = sorted({p for path in paths for p in Path(path).parent.glob(Path(path).stem + ".*") if p.is_file()})
    return {str(p.relative_to(root)): file_sha256(p) for p in files}


def package_versions() -> dict[str, str]:
    """계산에 쓰인 주요 패키지 버전."""
    import geopandas
    import numpy
    import pandas
    import pyogrio
    import scipy
    import shapely
    import sklearn
    import xgboost

    # 파이썬과 각 패키지의 버전을 이름으로 묶는다
    modules = (numpy, pandas, geopandas, pyogrio, shapely, scipy, sklearn, xgboost)
    return {"python": platform.python_version(), **{m.__name__: m.__version__ for m in modules}}


def git_state(root: Path, paths: tuple[str, ...] = ("src", "config")) -> tuple[str, bool]:
    """(HEAD 짧은 해시, 지정 경로에 커밋 안 된 변경이 있는가)."""
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                          cwd=root).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", *paths], capture_output=True,
                                text=True, cwd=root).stdout.strip())
    return head, dirty
