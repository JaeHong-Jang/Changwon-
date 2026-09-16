"""등급 경계 캘리브레이션 — 점수 구간이 아니라 **실제 침수 발생률**로 경계를 정한다.

결정 003 이 본안으로 고른 3안이다(`docs/CDRI_GRADE_SYSTEM.md` §1③). Jenks 는 점수 분포의
자연스러운 단절만 보므로 "R5 와 R4 가 실제로 얼마나 다르게 잠기는지"는 말해 주지 못한다.
이 모듈은 그 질문에 답한다.

**순환을 막는 장치.** 흔적으로 경계를 맞추고 같은 흔적으로 검증하면 in-sample 이라
성능이 부풀려진다. 그래서 사상을 시간으로 나눠 **앞 사상으로 경계를 정하고 뒤 사상으로
검증한다**. 이 모듈은 경계만 만들고, 검증은 호출부가 out-of-sample 라벨로 수행한다.

절차 (CDRI_GRADE_SYSTEM §1③ ②)
  1. 캘리브레이션 라벨로 CDRI 순 등온회귀(PAV) 단조 발생률 곡선 p̂(c) 추정
  2. 목표 백분위(98/90/70/40)에서 ±tolerance 안의 PAV 단절점으로 경계 이동
  3. 인접 등급 발생률 비 < min_ratio 이면 허용 범위 안에서 재이동
  4. 그래도 미달이면 두 등급을 통합해 보고 (경계를 억지로 만들지 않는다)
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# 목표 백분위 — R5/R4/R3/R2 의 하한. TARGET_SHARE(2/8/20/30/40%)의 누적 여집합이다.
TARGET_PERCENTILES = (0.98, 0.90, 0.70, 0.40)
DEFAULT_TOLERANCE = 0.03      # 목표 백분위에서 ±3%p 까지 단절점을 찾는다
DEFAULT_MIN_RATIO = 1.3       # 인접 등급 발생률 비 하한
TOLERANCE_GRID = (0.02, 0.03, 0.05)     # 민감도 보고용
MIN_RATIO_GRID = (1.2, 1.3, 1.5)


def isotonic_incidence(scores: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """PAV(pool-adjacent-violators) 로 점수에 대해 **단조 증가**하는 발생률 곡선을 적합한다.

    (오름차순 정렬된 점수, 같은 위치의 적합 발생률) 을 돌려준다.

    왜 등온회귀인가. 원자료의 발생률은 표본 잡음 때문에 오르내린다. 그 상태로 단절점을
    찾으면 잡음을 경계로 삼게 된다. "위험이 높을수록 더 자주 잠긴다"는 단조성은 지수의
    전제이므로, 그 전제를 만족하는 곡선 중 자료에 가장 가까운 것을 쓴다.
    이것은 제약하의 최소제곱해이며 O(n) 에 구한다 (Ayer et al. 1955).
    """
    order = np.argsort(scores, kind="stable")
    x = np.asarray(scores, dtype=float)[order]
    y = np.asarray(labels, dtype=float)[order]

    # 각 블록을 (합, 개수) 로 쌓고, 앞 블록의 평균이 더 크면 합쳐서 단조성을 회복한다.
    sums: list[float] = []
    counts: list[int] = []
    for value in y:
        sums.append(float(value))
        counts.append(1)
        while len(sums) > 1 and sums[-2] / counts[-2] > sums[-1] / counts[-1]:
            s, c = sums.pop(), counts.pop()
            sums[-1] += s
            counts[-1] += c

    fitted = np.repeat(np.array(sums) / np.array(counts), counts)
    return x, fitted


def _jump_positions(fitted: np.ndarray) -> np.ndarray:
    """PAV 곡선의 값이 바뀌는 위치(인덱스). 이 지점이 자료가 말하는 '자연스러운 경계'다."""
    return np.flatnonzero(np.diff(fitted) > 0) + 1


def _incidence(labels: np.ndarray, lo: int, hi: int) -> float:
    """정렬된 라벨의 [lo, hi) 구간 발생률. 구간이 비면 0."""
    return float(labels[lo:hi].mean()) if hi > lo else 0.0


def calibration_breaks(
    scores: np.ndarray,
    labels: np.ndarray,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    min_ratio: float = DEFAULT_MIN_RATIO,
) -> dict[str, Any]:
    """발생률로 5등급 경계를 정한다. 경계값·이동 내역·통합 권고를 함께 돌려준다.

    `breaks` 는 R1~R4 의 **상한 점수** 4개(오름차순)로, `layers.classify` 가 받는 형식과
    같다. 상한으로 두는 이유는 경계값 자체가 낮은 등급에 들어가도록 맞추기 위해서다.
    """
    x, fitted = isotonic_incidence(scores, labels)
    order = np.argsort(scores, kind="stable")
    y_sorted = np.asarray(labels, dtype=float)[order]
    n = len(x)
    jumps = _jump_positions(fitted)

    cuts: list[int] = []
    moves: list[dict[str, Any]] = []
    # 높은 등급부터 정한다. 경계가 서로 넘지 않도록 이미 정한 위치를 상한으로 쓴다.
    upper = n
    for target in TARGET_PERCENTILES:
        wanted = int(round(target * n))
        window = jumps[(jumps >= int((target - tolerance) * n)) & (jumps <= int((target + tolerance) * n))]
        window = window[window < upper]
        if len(window):
            # 허용 범위 안에서 발생률 단차가 가장 큰 단절점을 고른다.
            gaps = fitted[window] - fitted[window - 1]
            chosen = int(window[int(np.argmax(gaps))])
        else:
            chosen = min(wanted, upper - 1)
        moves.append({
            "target_percentile": target,
            "moved_to_percentile": round(chosen / n, 4),
            "shift_pp": round((chosen - wanted) / n * 100, 2),
            "snapped_to_pav_break": bool(len(window)),
        })
        cuts.append(chosen)
        upper = chosen

    cuts = sorted(cuts)                                     # 오름차순 = R2/R3/R4/R5 하한
    bounds = [0, *cuts, n]
    incidence = [_incidence(y_sorted, bounds[i], bounds[i + 1]) for i in range(5)]

    # 인접 등급 발생률 비가 기준에 못 미치면 통합을 권고한다. 경계를 억지로 만들지 않는다.
    merges = []
    for i in range(4):
        lower, upper_rate = incidence[i], incidence[i + 1]
        ratio = (upper_rate / lower) if lower > 0 else math.inf
        if ratio < min_ratio:
            merges.append({"grades": [i + 1, i + 2], "incidence_ratio": round(ratio, 3)})

    return {
        # cuts[i] 는 위 등급의 첫 위치이므로, 그 바로 앞 값이 아래 등급의 상한이 된다.
        "breaks": [float(x[c - 1]) for c in cuts],
        "moves": moves,
        "incidence_by_grade": [round(v, 5) for v in incidence],
        "grade_sizes": [bounds[i + 1] - bounds[i] for i in range(5)],
        "merge_recommended": merges,
        "tolerance": tolerance,
        "min_ratio": min_ratio,
        "n_pav_breaks": int(len(jumps)),
    }


def _cochran_armitage_counts(sizes: np.ndarray, positives: np.ndarray) -> dict[str, float]:
    """등급별 (격자 수, 양성 수) 로 Cochran-Armitage 추세 z 와 양측 p 를 구한다."""
    levels = np.arange(1, len(sizes) + 1, dtype=float)
    total = sizes.sum()
    p_bar = positives.sum() / total if total else 0.0
    numerator = float(np.sum(levels * (positives - sizes * p_bar)))
    spread = float(np.sum(sizes * levels**2) - np.sum(sizes * levels) ** 2 / total) if total else 0.0
    variance = p_bar * (1 - p_bar) * spread
    if variance <= 0:
        return {"z": 0.0, "p_value": 1.0}
    z = numerator / math.sqrt(variance)
    return {"z": round(z, 4), "p_value": float(math.erfc(abs(z) / math.sqrt(2)))}


def cochran_armitage(grades: np.ndarray, labels: np.ndarray, n_classes: int = 5) -> dict[str, float]:
    """등급이 오를수록 발생률이 오르는지 추세검정한다 (Cochran 1954; Armitage 1955).

    **격자가 독립이라고 가정한다.** 침수 폴리곤이 격자 여러 칸을 덮는 자료에서는 이 가정이
    깨져 p 값이 지나치게 작아진다. 주장의 근거로는 `uncertainty.grade_incidence_bootstrap`
    의 덩어리 단위 기울기를 쓰고, 이 값은 참고로만 남긴다.
    """
    g = np.asarray(grades).astype(int)
    sizes = np.bincount(g, minlength=n_classes + 1)[1:].astype(float)
    positives = np.bincount(g, weights=np.asarray(labels, dtype=float), minlength=n_classes + 1)[1:]
    return _cochran_armitage_counts(sizes, positives)


def table_from_counts(sizes: np.ndarray, positives: np.ndarray) -> dict[str, Any]:
    """등급별 (격자 수, 양성 수) 로 발생률·lift·인접 비·단조성 표를 만든다.

    한 번의 등급 배정(시간 분할)이든 여러 폴드를 합친 것(LOEO)이든 개수만 있으면
    같은 표가 나오도록 계산을 여기 모았다.
    """
    sizes = np.asarray(sizes, dtype=float)
    positives = np.asarray(positives, dtype=float)
    n_classes = len(sizes)
    base = positives.sum() / sizes.sum() if sizes.sum() else 0.0
    rates = np.divide(positives, sizes, out=np.zeros_like(positives), where=sizes > 0)
    rows = [
        {
            "grade": k + 1, "n": int(sizes[k]), "positives": int(positives[k]),
            "incidence": round(float(rates[k]), 5),
            "lift": round(float(rates[k] / base), 3) if base > 0 else None,
        }
        for k in range(n_classes)
    ]
    rounded = [r["incidence"] for r in rows]
    return {
        "rows": rows,
        "n_classes": n_classes,
        "base_rate": round(float(base), 5),
        "adjacent_ratios": [
            round(rounded[k + 1] / rounded[k], 3) if rounded[k] > 0 else None for k in range(n_classes - 1)
        ],
        "monotone": all(rounded[k] <= rounded[k + 1] for k in range(n_classes - 1)),
        "top_over_bottom": round(rounded[-1] / rounded[0], 2) if rounded[0] > 0 else None,
        **_cochran_armitage_counts(sizes, positives),
        "p_value_note": "격자 독립을 가정한 값이라 주장의 근거로 쓰지 않는다 (덩어리 단위 기울기를 본다)",
    }


def incidence_table(grades: np.ndarray, labels: np.ndarray, n_classes: int = 5) -> dict[str, Any]:
    """등급별 발생률·lift·인접 비를 낸다. 통합 등급(3~4단)에도 쓸 수 있게 등급 수를 받는다."""
    g = np.asarray(grades).astype(int)
    sizes = np.bincount(g, minlength=n_classes + 1)[1:]
    positives = np.bincount(g, weights=np.asarray(labels, dtype=float), minlength=n_classes + 1)[1:]
    return table_from_counts(sizes, positives)


def leave_one_event_out(
    scores: np.ndarray,
    event_labels: dict[str, np.ndarray],
    x: np.ndarray,
    y: np.ndarray,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    min_ratio: float = DEFAULT_MIN_RATIO,
    n_boot: int | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """사상 하나를 빼고 나머지로 경계를 맞춘 뒤, 뺀 사상으로 채점한다. 사상마다 반복해 합친다.

    **왜 필요한가.** 앞 사상 3개로 경계를 정하고 뒤 사상 3개로 채점하는 시간 분할은 검증에
    쓰이는 침수가 12건뿐이었다(R5 는 1건). 표본이 너무 작아 어떤 판정도 할 수 없다.
    LOEO 로 돌리면 모든 사상이 한 번씩 검증에 쓰여 검증 침수가 전체(창원 46건)로 늘어난다.
    설계 문서가 미리 정해 둔 대안이다 (CDRI_GRADE_SYSTEM §1③① "사상 수가 부족하면
    사상 단위 leave-one-event-out 으로 대체").

    **가정.** 사상들이 서로 바꿔 써도 되는 표본이라고 본다. 그래서 2019 년 사상으로 정한
    경계로 2006 년을 채점하는 일도 생긴다. 미래 예측 검증이 아니라 교차검증이다.

    **합치는 방법.** 폴드마다 등급별 격자 수(분모)와 뺀 사상의 양성 수(분자)를 더한다.
    불확실성은 (사상, 덩어리) 를 한 단위로 재표본해 잰다.
    """
    from src.data import uncertainty as U
    from src.data.layers import classify

    s = np.asarray(scores, dtype=float)
    n_classes = len(TARGET_PERCENTILES) + 1
    sizes = np.zeros(n_classes)
    units, folds = [], []
    for event in sorted(event_labels):
        calibration = np.zeros(s.size, dtype=bool)
        for other, labels in event_labels.items():
            if other != event:
                calibration |= np.asarray(labels).astype(bool)
        result = calibration_breaks(s, calibration.astype(float), tolerance=tolerance, min_ratio=min_ratio)
        grades = classify(s, [*result["breaks"], float(s.max())]).astype(int)
        sizes += np.bincount(grades, minlength=n_classes + 1)[1:]
        event_units = U.unit_grade_counts(grades, event_labels[event], x, y, n_classes)
        units.append(event_units)
        folds.append({
            "held_out": event,
            "breaks": [round(b, 4) for b in result["breaks"]],
            "n_positive": int(np.asarray(event_labels[event]).astype(bool).sum()),
            "n_cluster": int(len(event_units)),
        })

    units = np.vstack(units) if units else np.zeros((0, n_classes))
    table = table_from_counts(sizes, units.sum(axis=0))
    breaks = np.array([f["breaks"] for f in folds])
    boot_kwargs = {"seed": seed} if n_boot is None else {"seed": seed, "n_boot": n_boot}
    return {
        **table,
        "folds": folds,
        "n_cluster": int(len(units)),
        # 뺀 사상이 바뀌어도 경계가 거의 같으면 경계 규칙이 특정 사상에 끌려다니지 않는다는 뜻이다.
        "break_range": [round(float(v), 4) for v in (breaks.max(axis=0) - breaks.min(axis=0))],
        "bootstrap": U.grade_incidence_bootstrap(units, sizes, **boot_kwargs),
        "clusters_by_grade": {f"R{k + 1}": int((units[:, k] > 0).sum()) for k in range(n_classes)},
        "sample": "leave-one-event-out — 모든 사상이 한 번씩 검증에 쓰인다",
    }


def merge_weak_grades(grades: np.ndarray, merges: list[dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    """발생률이 갈리지 않는 인접 등급을 하나로 묶는다. (묶은 등급, 대응표).

    "인접 등급 발생률 비가 기준에 못 미치면 두 등급을 통합해 보고한다"는 절차 ④다
    (CDRI_GRADE_SYSTEM §1③). 통합 대상은 **캘리브레이션 기간 자료**가 정한다. 검증 자료로
    정하면 검증에 맞춰 등급을 깎는 셈이라 out-of-sample 이 아니게 된다.

    묶인 등급은 1부터 다시 번호를 매긴다.
    """
    pairs = {tuple(m["grades"]) for m in merges}
    tier_of: dict[int, int] = {1: 1}
    for grade in range(2, 6):
        tier_of[grade] = tier_of[grade - 1] if (grade - 1, grade) in pairs else tier_of[grade - 1] + 1
    merged = np.array([tier_of[int(g)] for g in grades], dtype="int8")
    groups: dict[int, list[int]] = {}
    for grade, tier in tier_of.items():
        groups.setdefault(tier, []).append(grade)
    return merged, {
        "n_tiers": len(groups),
        "tier_members": {str(t): [f"R{g}" for g in v] for t, v in sorted(groups.items())},
        "merged_pairs": [m["grades"] for m in merges],
    }


def sensitivity(scores: np.ndarray, labels: np.ndarray) -> list[dict[str, Any]]:
    """설계 파라미터(±%p, 최소 발생률 비)를 흔들어 경계가 얼마나 달라지는지 본다.

    CDRI_GRADE_SYSTEM §1③ 이 요구한 민감도 보고다. 경계가 파라미터에 크게 휘둘리면
    캘리브레이션 자체를 본안으로 쓰면 안 된다.
    """
    out = []
    for tolerance in TOLERANCE_GRID:
        for min_ratio in MIN_RATIO_GRID:
            result = calibration_breaks(scores, labels, tolerance=tolerance, min_ratio=min_ratio)
            out.append({
                "tolerance": tolerance, "min_ratio": min_ratio,
                "breaks": [round(b, 4) for b in result["breaks"]],
                "grade_sizes": result["grade_sizes"],
                "n_merge_recommended": len(result["merge_recommended"]),
            })
    return out
