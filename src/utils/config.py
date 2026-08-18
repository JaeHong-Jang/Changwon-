"""
프로젝트 설정 로드 유틸리티
config/config.yaml 파일을 읽어 딕셔너리로 반환합니다.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 프로젝트 루트 디렉토리 (src/utils/config.py 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_config(path: str | None = None) -> dict:
    """config.yaml을 로드하여 딕셔너리로 반환합니다."""
    if path is None:
        path = PROJECT_ROOT / "config" / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_env():
    """프로젝트 루트의 .env 파일을 로드합니다."""
    dotenv_path = PROJECT_ROOT / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)


def get_api_key(name: str = "DATA_GO_KR_API_KEY") -> str:
    """환경 변수에서 API 키를 가져옵니다."""
    load_env()
    key = os.getenv(name, "")
    if not key:
        raise ValueError(
            f"API 키 '{name}'이(가) 설정되지 않았습니다. "
            f".env 파일에 {name}=your_key 형태로 추가하세요."
        )
    return key


def get_path(key: str) -> Path:
    """config.yaml의 paths 섹션에서 절대 경로를 반환합니다."""
    cfg = load_config()
    rel = cfg["paths"][key]
    return PROJECT_ROOT / rel
