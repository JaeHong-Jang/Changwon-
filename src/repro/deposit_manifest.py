"""git 추적 파일을 M6 절차 §5 규칙으로 분류해 Zenodo 기탁 후보 목록(경로·크기·SHA256·처리)을 만든다."""

from __future__ import annotations

import subprocess
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from src.models.provenance import file_sha256

# (경로 패턴들, 분류, 처리, 근거) — 위에서부터 먼저 맞는 규칙 하나를 쓴다. 패턴의 * 는 / 도 넘는다.
RULES: list[tuple[tuple[str, ...], str, str, str]] = [
    (("data/raw/README.md", "data/raw/open_data_manifest.json", "data/*/README.md"), "docs", "open",
     "프로젝트가 쓴 설명·목록"),
    (("data/raw/rivers/osm_waterways.gpkg",), "raw_open", "open",
     "ODbL (docs/data_access_log.md #19, data/raw/README.md) — 출처 표시·동일 조건"),
    (("data/raw/flood_traces/changwon_info_disclosure_*",), "raw_restricted", "hash_only",
     "창원시 정보공개 제공, 재배포 허락 미확인 (PAPER_ROADMAP §7)"),
    (("data/raw/flood_traces/safetydata_*",), "raw_restricted", "hash_only",
     "재난안전데이터공유플랫폼 이용 조건 미확인"),
    (("data/raw/*", "data/external/*"), "raw_third_party", "hash_only", "제3자 자료, 저장소에 이용 조건 기록 없음"),
    (("artifacts/processed_snapshot/*",), "derived_data", "restricted",
     "격자 인구(SGIS)·흔적 라벨을 담은 파생 자료, 원본 조건 확인 전 제한"),
    (("artifacts/frozen/*",), "frozen_models", "open", "동결 모델·사전 명세"),
    (("artifacts/*", "reports/*"), "results", "open", "점수·지표·요약"),
    (("docs/*",), "docs", "open", "절차·보고·연구 문서"),
    ((".fablize/*",), "internal", "exclude", "하네스 내부 진행 기록"),
    (("*",), "code", "open", "코드·설정"),
]


def classify(path: str) -> tuple[str, str, str]:
    """경로 하나에 처음 맞는 규칙의 (분류, 처리, 근거)를 돌려준다."""
    # 규칙 순서대로 패턴을 대조한다
    for patterns, category, decision, basis in RULES:
        if any(fnmatchcase(path, p) for p in patterns):
            return category, decision, basis
    raise ValueError(f"규칙에 맞지 않는 경로: {path}")


def tracked_files(root: Path) -> list[str]:
    """git 인덱스의 추적 파일 목록 (NUL 구분이라 비ASCII 경로가 그대로 온다)."""
    # -z 로 받아 따옴표 이스케이프 없이 경로를 나눈다
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return sorted(p for p in out.decode("utf-8").split("\0") if p)


def build_manifest(root: Path, paths: list[str]) -> Any:
    """경로마다 분류·처리·근거·바이트·SHA256 을 붙인 표를 만든다."""
    import pandas as pd

    # 파일이 없으면(예: 삭제 뒤 미반영) 크기·해시를 비워 드러낸다
    rows = []
    for path in paths:
        category, decision, basis = classify(path)
        target = root / path
        exists = target.is_file()
        rows.append({"path": path, "category": category, "decision": decision,
                     "bytes": target.stat().st_size if exists else None,
                     "sha256": file_sha256(target) if exists else None, "basis": basis})
    return pd.DataFrame(rows)


def _totals(manifest: Any, keys: list[str]) -> dict[str, dict[str, int]]:
    """주어진 열 조합별 파일 수와 바이트 합계."""
    # 묶음 이름은 열 값을 / 로 이어 붙인다
    return {"/".join(map(str, k)): {"n_files": int(len(g)), "bytes": int(g["bytes"].fillna(0).sum())}
            for k, g in manifest.groupby(keys)}


def summarise(manifest: Any, root: Path) -> dict[str, Any]:
    """처리·분류별 파일 수와 바이트, 라이선스 파일 유무를 요약한다."""
    # 루트의 LICENSE·COPYING 파일을 찾고 처리별·분류별 합계를 붙인다
    licenses = sorted(p.name for p in root.iterdir()
                      if p.is_file() and p.name.upper().startswith(("LICENSE", "COPYING")))
    return {"n_files": int(len(manifest)), "bytes": int(manifest["bytes"].fillna(0).sum()),
            "missing_files": manifest.loc[manifest["bytes"].isna(), "path"].tolist(),
            "by_decision": _totals(manifest, ["decision"]), "by_category": _totals(manifest, ["category", "decision"]),
            "license_files": licenses}
