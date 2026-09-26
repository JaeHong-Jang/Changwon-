"""CDRI 5등급 위험 분류 체계. R5가 가장 위험하다."""

from __future__ import annotations

from typing import Any

import numpy as np

from src.data.layers import BALICA_BREAKS, classify, jenks_breaks

GRADE_NAMES = {
    5: "R5 최우선 대응",
    4: "R4 우선 대응",
    3: "R3 점검 강화",
    2: "R2 일반 관리",
    1: "R1 관찰",
}
GRADE_CODES = {5: "R5", 4: "R4", 3: "R3", 2: "R2", 1: "R1"}
# ColorBrewer YlOrRd 5급.
GRADE_COLORS = {5: "#bd0026", 4: "#f03b20", 3: "#fd8d3c", 2: "#fecc5c", 1: "#ffffb2"}
# 설계 목표 비율.
TARGET_SHARE = {5: 0.02, 4: 0.08, 3: 0.20, 2: 0.30, 1: 0.40}

MIN_POSITIVE_FOR_CALIBRATION = 100
RULE_A_PERCENTILE = 0.99      # L1 백분위 하한
RULE_A_FLOOR_GRADE = 3        # 상향 결과가 이보다 낮으면 여기까지 올린다
RULE_B_V_PERCENTILE = 0.90    # 취약성 상위 10%
RULE_B_H_PERCENTILE = 0.70    # 위험 상위 30%
MAX_UPLIFT = 2                # 규칙 A·B 합산 상향 한도
OVERUSE_SHARE = 0.05          # 실제 변경 격자가 이 비율을 넘으면 규칙이 아니라 지수를 의심한다
DESIGNATED_BUFFER_M = 200


def choose_scheme(n_positive: int, has_time_split: bool) -> tuple[str, str]:
    """본안 등급 방식을 고른다. 발생률 캘리브레이션은 표본이 충분할 때만 쓴다."""
    if n_positive >= MIN_POSITIVE_FOR_CALIBRATION and has_time_split:
        return "calibration", (
            f"침수흔적 양성 격자 {n_positive}개 ≥ {MIN_POSITIVE_FOR_CALIBRATION} 이고 시간 분할 가능"
        )
    reason = (
        f"침수흔적 양성 격자 {n_positive}개 < {MIN_POSITIVE_FOR_CALIBRATION}"
        if n_positive < MIN_POSITIVE_FOR_CALIBRATION else "사상 시간 분할 불가"
    )
    return "jenks", f"{reason} → Jenks 본안, Balica 병기 (CDRI_GRADE_SYSTEM §1 분기)"


def jenks_grades(values: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """Jenks 자연구분 5등급. 값이 클수록 높은 등급(R5)."""
    breaks = jenks_breaks(np.asarray(values, dtype=float), 5)
    return classify(values, breaks).astype("int8"), breaks


def calibration_grades(
    values: np.ndarray, calibration_labels: np.ndarray, *, tolerance: float, min_ratio: float
) -> tuple[np.ndarray, dict[str, Any]]:
    """실제 침수 발생률로 경계를 맞춘다. 검증 기간 라벨을 섞지 않는다."""
    from src.data import calibration as C

    result = C.calibration_breaks(values, calibration_labels, tolerance=tolerance, min_ratio=min_ratio)
    grades = classify(values, [*result["breaks"], float(np.max(values))])
    return grades.astype("int8"), result


def percentile_grades(values: np.ndarray) -> np.ndarray:
    """설계 목표 비율(2/8/20/30/40%)을 그대로 강제한 고정 백분위 등급."""
    a = np.asarray(values, dtype=float)
    cuts = np.quantile(a, [TARGET_SHARE[1],
                           TARGET_SHARE[1] + TARGET_SHARE[2],
                           TARGET_SHARE[1] + TARGET_SHARE[2] + TARGET_SHARE[3],
                           1 - TARGET_SHARE[5]])
    return (np.searchsorted(cuts, a, side="left") + 1).clip(1, 5).astype("int8")


def balica_grades(values: np.ndarray) -> np.ndarray:
    """Balica(2012) 고정 경계 5등급. 국제 비교용 병기."""
    idx = np.searchsorted(np.asarray(BALICA_BREAKS), np.asarray(values, dtype=float), side="left")
    return (np.clip(idx, 0, 4) + 1).astype("int8")


def apply_rules(
    grade_raw: np.ndarray,
    *,
    l1_percentile: np.ndarray,
    v_percentile: np.ndarray,
    h_percentile: np.ndarray,
    designated_near: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """등급 결정 규칙 A·B·C 를 적용한다. 검증은 적용 전 grade_raw 로 한다."""
    raw = np.asarray(grade_raw, dtype=int)
    rule_a = np.asarray(l1_percentile, dtype=float) >= RULE_A_PERCENTILE
    rule_b = (np.asarray(v_percentile, dtype=float) >= RULE_B_V_PERCENTILE) & (
        np.asarray(h_percentile, dtype=float) >= RULE_B_H_PERCENTILE
    )

    uplift = np.minimum(rule_a.astype(int) + rule_b.astype(int), MAX_UPLIFT)
    final = np.clip(raw + uplift, 1, 5)
    final = np.where(rule_a & (final < RULE_A_FLOOR_GRADE), RULE_A_FLOOR_GRADE, final).astype("int8")

    review = np.zeros(len(raw), dtype="int8")
    if designated_near is not None:
        review = (np.asarray(designated_near).astype(bool) & np.isin(raw, [1, 2])).astype("int8")

    changed = final != raw
    metrics = {
        "rule_a_matched": int(rule_a.sum()),
        "rule_b_matched": int(rule_b.sum()),
        "rule_a_and_b": int((rule_a & rule_b).sum()),
        "n_changed": int(changed.sum()),
        "changed_share": round(float(changed.mean()), 4),
        "overuse_threshold": OVERUSE_SHARE,
        "overused": bool(changed.mean() > OVERUSE_SHARE),
        "rule_c_available": designated_near is not None,
        "rule_c_review_flagged": int(review.sum()),
        "thresholds": {
            "rule_a_l1_percentile": RULE_A_PERCENTILE,
            "rule_a_floor_grade": RULE_A_FLOOR_GRADE,
            "rule_b_v_percentile": RULE_B_V_PERCENTILE,
            "rule_b_h_percentile": RULE_B_H_PERCENTILE,
            "max_uplift": MAX_UPLIFT,
        },
    }
    return final, review, metrics


def weighted_kappa(a: np.ndarray, b: np.ndarray, n_classes: int = 5) -> float:
    """2차 가중 κ. 등급 차이가 클수록 불일치를 크게 센다 (Landis & Koch 1977 해석 기준)."""
    a = np.asarray(a, dtype=int) - 1
    b = np.asarray(b, dtype=int) - 1
    observed = np.zeros((n_classes, n_classes))
    for i, j in zip(a, b):
        observed[i, j] += 1
    observed /= observed.sum()
    row, col = observed.sum(axis=1), observed.sum(axis=0)
    expected = np.outer(row, col)
    idx = np.arange(n_classes)
    weight = (idx[:, None] - idx[None, :]) ** 2 / (n_classes - 1) ** 2
    denominator = float((weight * expected).sum())
    return 1.0 if denominator == 0 else float(1.0 - (weight * observed).sum() / denominator)


def grade_summary(grades: np.ndarray) -> dict[str, Any]:
    """등급별 격자 수·비율과 설계 목표 비율 대비 편차."""
    grades = np.asarray(grades, dtype=int)
    total = max(len(grades), 1)
    rows = {}
    for g in sorted(GRADE_CODES, reverse=True):
        count = int((grades == g).sum())
        share = count / total
        rows[GRADE_CODES[g]] = {
            "name": GRADE_NAMES[g],
            "n": count,
            "share": round(share, 4),
            "target_share": TARGET_SHARE[g],
            "diff": round(share - TARGET_SHARE[g], 4),
        }
    return rows
