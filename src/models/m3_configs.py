"""M3 설정 공간: prespec 격자의 특징집합 × 모델군 × 후보와 고정 구성 (docs/q1/M3_protocol.md §2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models.estimators import CANDIDATES, FIXED_PARAMS
from src.models.features import FEATURES

# 변형 이름 → 후보로 쓰는 모델군 (주: RF 고정, 보조: 전체 격자)
VARIANTS = {"nested_rf": ("random_forest",), "nested_all": tuple(CANDIDATES)}


def config_id(model: str, feature_set: str, params: dict[str, Any]) -> str:
    """설정을 '모델군|특징집합|키=값,…' 한 줄 이름으로 바꾼다."""
    return f"{model}|{feature_set}|" + ",".join(f"{k}={v}" for k, v in params.items())


FIXED_ID = config_id("random_forest", "F1", {"max_depth": 4, "min_samples_leaf": 400})


def grid(models: tuple[str, ...] = tuple(CANDIDATES)) -> list[dict[str, Any]]:
    """선언 순서(특징집합 → 모델군 → 후보)로 설정 목록을 만든다."""
    return [{"id": config_id(m, f, p), "model": m, "feature_set": f, "params": dict(p)}
            for f in FEATURES for m in CANDIDATES if m in models for p in CANDIDATES[m]]


def check_prespec(path: Path) -> dict[str, Any]:
    """prespec 의 특징·후보·고정 파라미터와 동결 선택이 코드 상수·고정 구성과 같은지 확인한다."""
    # 격자 세 항목을 코드 상수와 비교한다
    prespec = json.loads(Path(path).read_text(encoding="utf-8"))
    for key, value in (("features", FEATURES), ("candidates", CANDIDATES), ("fixed_parameters", FIXED_PARAMS)):
        if prespec[key] != value:
            raise ValueError(f"prespec {key} 가 코드 상수와 다르다")

    # 동결 선택의 모델군·특징집합·후보 파라미터가 고정 구성과 같은지 본다
    selection = prespec["selection"]
    chosen = {k: selection["parameters"][k] for k in CANDIDATES[selection["model"]][0]}
    if config_id(selection["model"], selection["feature_set"], chosen) != FIXED_ID:
        raise ValueError("prespec 동결 선택이 고정 구성과 다르다")
    return prespec
