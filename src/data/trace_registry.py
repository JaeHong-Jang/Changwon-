"""침수흔적 자료원의 경로·역할과 벡터 파일 등록부를 관리한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "config/flood_traces.yaml"
VECTOR_SUFFIXES = {".shp", ".gpkg", ".geojson", ".json", ".gml", ".kml"}
# 수집 기록·메타데이터 파일을 제외한다.
SKIP_NAME_TOKENS = ("metric", "meta", "manifest", "readme", "log")


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, dict[str, Any]]:
    """자료원별 경로·역할·제공자 등록부를 읽는다."""
    # YAML 등록부를 읽을 도구를 준비한다.
    import yaml

    # 자료원 등록부를 읽고 개발·홀드아웃 역할을 검증한다.
    with Path(path).open(encoding="utf-8") as stream:
        sources = yaml.safe_load(stream)["sources"]
    for source_id, source in sources.items():
        if source["role"] not in {"development", "holdout"}:
            raise ValueError(f"{source_id}: 잘못된 자료 역할 {source['role']}")
    return sources


def registered_files(registry: dict[str, dict[str, Any]], root: Path) -> Iterable[tuple[Path, str, str]]:
    """등록된 경로·glob에서 자료 파일과 출처를 돌려준다."""
    # 등록 경로에서 벡터 파일만 골라 출처와 역할을 함께 반환한다.
    for source_id, source in registry.items():
        for pattern in source["paths"]:
            for path in sorted(root.glob(pattern)):
                if (path.is_file() and path.suffix.lower() in VECTOR_SUFFIXES
                        and not any(tok in path.stem.lower() for tok in SKIP_NAME_TOKENS)):
                    yield path.resolve(), source_id, source["role"]


def files_for(role: str, *, registry: dict[str, dict[str, Any]] | None = None,
              root: Path = PROJECT_ROOT) -> list[Path]:
    """지정한 역할의 등록된 벡터 파일만 돌려준다."""
    # 역할을 검증한 뒤 해당 자료원의 파일 경로를 정렬한다.
    if role not in {"development", "holdout"}:
        raise ValueError(f"잘못된 자료 역할: {role}")
    sources = load_registry() if registry is None else registry
    selected = {key: value for key, value in sources.items() if value["role"] == role}
    return sorted({path for path, _, _ in registered_files(selected, Path(root))})
