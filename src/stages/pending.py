"""아직 구현하지 않은 노드들. 각 함수의 docstring 이 그 노드의 통과 기준·metrics 계약이다.

구현할 때는 이 파일에서 빼내 게이트별 모듈(`h04_features.py` 처럼)로 옮기고
`config/pipeline.yaml` 의 runner 경로를 함께 고친다. 구현 전까지 한곳에 모아 둔다.
"""

from __future__ import annotations

from typing import Any

from src.pipeline.runner import StageContext


def _todo(name: str) -> None:
    raise NotImplementedError(name)


# ── H05 민원 (정보공개청구 회신 후) ─────────────────────────────────────────
def holdout_freeze(ctx: StageContext) -> dict[str, Any]:
    """메타데이터만으로 개발/최종 홀드아웃 분리 후 checksum 동결.
    통과: 분할 규칙·checksum 기록, 최종 홀드아웃 원문 접근 0회. metrics: n_dev, n_holdout."""
    _todo("holdout_freeze")


def complaint_extract(ctx: StageContext) -> dict[str, Any]:
    """개발세트 원문만 LLM 구조화, extractor 코드·프롬프트·모델·taxonomy checksum 고정.
    통과: 표본정확도·사람검수율·공간오차 기록.
    metrics: n_extracted, sample_accuracy, human_review_rate."""
    _todo("complaint_extract")


# ── H06 레이어 ────────────────────────────────────────────────────────────
def layer2_sewer(ctx: StageContext) -> dict[str, Any]:
    """decisions/001 에 따라 Plan B(인프라 baseline) 또는 Plan A(+로지스틱/XGBoost).
    민원 부재를 음성 라벨로 쓰지 않는다. metrics: plan, auc, n_grid."""
    _todo("layer2_sewer")


def cdri(ctx: StageContext) -> dict[str, Any]:
    """equal/entropy × 곱셈/가중합 중 primary 산식 선택, 입력오차·가중치 민감도.
    통과: 중위 Spearman rho ≥ 0.8, TOP20 중첩 ≥ 70%. 미달이면 tier 보고 모드.
    metrics: rho_median, top20_overlap, primary_formula."""
    _todo("cdri")


def top20(ctx: StageContext) -> dict[str, Any]:
    """top20.csv(격자별 트리거·근거 3개·신뢰등급·담당·조치·KPI) + 최종 홀드아웃 1회 평가.
    행동 트리거·실행 주체 없는 항목은 제외. metrics: n_top20, holdout_metrics."""
    _todo("top20")


def result_review(ctx: StageContext) -> dict[str, Any]:
    """CDRI 분포·TOP 20 지도를 A1 침수예상도·A7 홍수위험지도와 대조.
    통과: 기여도 합 100%, 동 편중 없음, 중첩률 보고.
    metrics: overlap_a1, overlap_a7, top20_dong_max_share."""
    _todo("result_review")


def alert_draft(ctx: StageContext) -> dict[str, Any]:
    """고정 TOP 20 + 유효 예보로 내부 검토용 문안 1건과 화면 1장.
    만료·단위·timezone 불일치 예보는 차단. metrics: forecast_valid, elapsed_s."""
    _todo("alert_draft")


def reproducibility(ctx: StageContext) -> dict[str, Any]:
    """빈 processed 환경 전체 재실행 + feedback_manifest 필수키·checksum·version 검사.
    통과: 홀드아웃 결과 checksum 불변. metrics: checks_passed, holdout_checksum_unchanged."""
    _todo("reproducibility")
