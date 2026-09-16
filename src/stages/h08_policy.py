"""H08 우선대응 지역 정책화 — 정책카드는 '문장'이 아니라 트리거-행동 계약이다 (RESEARCH_PLAN §0-6).

CDRI 가 위험군(tier) 모드이면 정밀 순위를 주장하지 않는다. 그 경우 표의 `rank` 는
표시 순서일 뿐이며 `in_robust_core` 와 `grade_final` 이 실제 근거다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.pipeline.runner import StageContext, StageFailed
from src.utils.config import PROJECT_ROOT

# 공식 기준으로 대체한 트리거 (docs/WORK_PLAN_0914.md §2-4).
# 시 SOP 확인 전 임의의 시간기준(24h·6h)을 쓰지 않고 기상청 호우특보 발효 기준을 쓴다.
TRIGGER_WATCH = "기상청 호우주의보 (3시간 60mm 또는 12시간 110mm 예상)"
TRIGGER_WARNING = "기상청 호우경보 (3시간 90mm 또는 12시간 180mm 예상)"

# 주 원인(가법형 기여도 최대 요소)별 행동 계약. 하나의 격자에 하나의 1순위 조치를 준다.
ACTION_BY_CAUSE: dict[str, dict[str, str]] = {
    "H": {
        "recommended_action": "우기 전 빗물받이·측구 준설, 호우주의보 시 이동식 펌프·차수판 배치 지점으로 지정",
        "owner_department": "창원시 하수도사업소 (해당 하수처리구역 관할)",
        "required_resource": "기존 준설 인력 + 이동식 펌프 1대",
        "cost_band": "소규모 정비 (기존 정비사업 내 우선순위 조정)",
        "kpi": "우기 전 준설 완료율, 호우 후 해당 격자 침수신고 건수",
    },
    "E": {
        "recommended_action": "호우경보 시 지하공간·지하차도 출입통제와 도로 우회 안내를 우선 적용할 구간으로 지정",
        "owner_department": "창원시 재난안전대책본부 (구청 안전건설과 협조)",
        "required_resource": "기존 통제 인력 + 안내표지",
        "cost_band": "기존 인력",
        "kpi": "통제 선행시간(경보 발효 후 통제까지), 침수 도로 고립 신고 건수",
    },
    "V": {
        "recommended_action": "고령가구 사전 연락 명단을 갱신하고 호우주의보 시 1차 연락 대상으로 지정",
        "owner_department": "행정복지센터·복지정책과",
        "required_resource": "기존 방문건강관리 인력",
        "cost_band": "기존 인력",
        "kpi": "주의보 발효 후 연락 완료율, 대피 지원 요청 처리시간",
    },
    "D": {
        "recommended_action": "반경 2km 내 임시 대피장소 추가 지정과 방재기관 접근로 사전 점검",
        "owner_department": "창원시 재난안전대책본부",
        "required_resource": "기존 시설 협약 (학교·경로당 등)",
        "cost_band": "기존 인력",
        "kpi": "신규 지정 대피장소 수, 최근접 대피장소까지 거리 단축량",
    },
}
POLICY_COLUMNS = [
    "rank", "grid_id", "district", "neighborhood", "cdri",
    "grade_raw", "grade_final", "grade_code", "grade_name", "in_robust_core",
    "hazard_contribution", "exposure_contribution", "vulnerability_contribution",
    "capacity_deficit_contribution", "primary_cause", "confidence_grade",
    "trigger", "action_timing", "recommended_action", "owner_department",
    "required_resource", "cost_band", "kpi", "human_approval_required",
    "pop_total", "elderly_estimate", "shelter_dist_m", "pump_dist_m",
    "forecast_issued_at", "forecast_valid_to", "evidence_run_id",
]
DONG_NAME_FILE = "data/external/adm_dong_names.csv"
GU_NAMES = {"38111": "의창구", "38112": "성산구", "38113": "마산합포구", "38114": "마산회원구", "38115": "진해구"}


def _suppress_neighbours(frame, radius_m: float, limit: int):
    """300m NMS — 같은 침수 구역이 인접 격자로 여러 번 뽑히는 것을 막는다 (ANALYSIS_PLAN §5).

    점수가 높은 격자부터 보며, 이미 뽑힌 격자에서 radius_m 안에 있으면 건너뛴다.
    후보 전체(7만여 격자)의 중심점을 계산하면 낭비이므로 상위 일부만 보고,
    그것으로 limit 을 못 채우면 범위를 두 배로 넓힌다. 결과는 전체를 훑은 것과 같다.
    """
    import numpy as np

    ordered = frame.sort_values("cdri", ascending=False, kind="stable")
    # 반경 300m·격자 100m 면 하나가 최대 28개를 누르므로 limit*30 이면 거의 항상 충분하다.
    head = min(len(ordered), max(limit * 30, 512))
    while True:
        window = ordered.iloc[:head]
        xy = np.column_stack([window.geometry.centroid.x, window.geometry.centroid.y])
        chosen: list[int] = []
        for i in range(len(window)):
            # 이미 뽑힌 점들과의 거리를 한 번에 잰다 (파이썬 반복문 대신 배열 연산).
            if not chosen or np.min(np.hypot(*(xy[i] - xy[chosen]).T)) >= radius_m:
                chosen.append(i)
                if len(chosen) == limit:
                    return window.iloc[chosen].copy()
        if head >= len(ordered):   # 전체를 다 봤는데도 못 채웠다
            return window.iloc[chosen].copy()
        head = min(len(ordered), head * 2)


def _load_candidates() -> tuple[Any, dict[str, Any]]:
    """CDRI 격자와 확정 산식 이력을 읽는다. (격자, 산식 manifest).

    펌프장 거리는 CDRI 에 들어가지 않는 참고 지표라 피처 표에서 따로 붙인다.
    """
    import geopandas as gpd
    import pandas as pd

    cdri = gpd.read_file(PROJECT_ROOT / "data/processed/layers/cdri.gpkg", layer="cdri")
    formula = json.loads(
        (PROJECT_ROOT / "artifacts/evaluation/primary_formula_manifest.json").read_text(encoding="utf-8")
    )
    pumps = pd.read_parquet(
        PROJECT_ROOT / "data/processed/features/grid_features.parquet", columns=["grid_id", "pump_dist_m"]
    )
    return cdri.merge(pumps, on="grid_id", how="left"), formula


def _attach_place_names(out) -> bool:
    """격자에 구·행정동 이름을 붙인다. 행정동명 확보 여부를 돌려준다.

    사람이 읽는 표에 '38111' 같은 코드만 있으면 현장에서 못 쓴다.
    """
    import pandas as pd

    names_path = PROJECT_ROOT / DONG_NAME_FILE
    names = (
        dict(zip(*pd.read_csv(names_path, encoding="utf-8-sig", dtype={"adm_cd": str})[["adm_cd", "adm_name"]].values.T))
        if names_path.exists() else {}
    )
    out["district"] = out["gu_code"].astype(str).map(GU_NAMES)
    out["neighborhood"] = out["adm_cd"].astype(str).map(names) if names else "행정동명 미확보"
    return bool(names)


def _build_policy_cards(out, run_id: str):
    """주 원인에 따라 트리거·담당부서·조치·KPI 를 채운다.

    정책카드는 문장이 아니라 '언제(트리거) 누가(담당) 무엇을(조치) 어떻게 확인(KPI)' 의
    계약이어야 한다 (RESEARCH_PLAN §0-6). 네 칸 중 하나라도 비면 그 격자는 표에서 뺀다.
    """
    out["elderly_estimate"] = (out["pop_total"] * out["elderly_ratio"]).round(0)
    for target, source in (
        ("hazard_contribution", "h_contribution"),
        ("exposure_contribution", "e_contribution"),
        ("vulnerability_contribution", "v_contribution"),
        ("capacity_deficit_contribution", "d_contribution"),
    ):
        out[target] = out[source].round(4)

    # 신뢰등급: A(직접 관측+검증) 는 침수흔적 검증 전까지 부여하지 않는다.
    out["confidence_grade"] = "B"
    out.loc[out["neighborhood"].eq("행정동명 미확보"), "confidence_grade"] = "C"

    out["trigger"] = TRIGGER_WATCH + " → " + TRIGGER_WARNING
    out["action_timing"] = "우기 전 상시 + 호우주의보 발효 시"
    for field in ("recommended_action", "owner_department", "required_resource", "cost_band", "kpi"):
        out[field] = out["primary_cause"].map(lambda c: ACTION_BY_CAUSE.get(c, {}).get(field, ""))
    out["human_approval_required"] = "통제·대피 결정은 법적 권한자가 공식 예보·현장확인 후 판단"
    out["forecast_issued_at"] = None
    out["forecast_valid_to"] = None
    out["evidence_run_id"] = run_id

    for column in ("cdri", "shelter_dist_m", "pump_dist_m"):
        out[column] = out[column].round(4 if column == "cdri" else 0)
    return out


def _drop_incomplete_cards(out) -> tuple[Any, int]:
    """네 칸(트리거·조치·담당·KPI)이 모두 찬 격자만 남긴다. (표, 제외 건수)."""
    required = ["trigger", "recommended_action", "owner_department", "kpi"]
    complete = out[required].notna().all(axis=1) & (out[required] != "").all(axis=1)
    kept = out[complete].copy()
    kept["rank"] = range(1, len(kept) + 1)
    return kept, int((~complete).sum())


def _summarise(out) -> dict[str, Any]:
    """선정 결과를 지표로 정리한다. 원인·등급 구성과 대상 인구가 핵심이다."""
    return {
        "selected": [
            {
                "rank": int(r.rank), "grid_id": r.grid_id, "district": r.district,
                "cdri": float(r.cdri), "grade_raw": int(r.grade_raw), "grade_final": int(r.grade_final),
                "grade_code": r.grade_code, "primary_cause": r.primary_cause,
                "robust_core": int(r.in_robust_core), "pop_total": int(r.pop_total),
                "elderly_estimate": int(r.elderly_estimate),
            }
            for r in out.itertuples()
        ],
        "cause_mix": {k: int(v) for k, v in out["primary_cause"].value_counts().items()},
        "grade_mix": {k: int(v) for k, v in out["grade_code"].value_counts().items()},
        "grade_note": "TOP 20 은 CDRI 점수 순(300m NMS)이며 규칙 A·B 의 영향을 받지 않는다 (CDRI_GRADE_SYSTEM §2)",
        "people_covered": {
            "pop_total": int(out["pop_total"].sum()),
            "elderly_estimate": int(out["elderly_estimate"].sum()),
            "shelter_over_2km": int((out["shelter_dist_m"] > 2000).sum()),
        },
    }


def _write_evaluation(path: Path, out, ranking_mode: str, run_id: str) -> None:
    """홀드아웃 평가 이력을 남긴다. 몇 번 평가했는지가 과적합 방지의 증거다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "holdout_evaluated": False,
        "reason": "민원 3년 자료 비공개 (정보공개법 §9①6호) — docs/decisions/001-layer2-design.md",
        "evaluation_count": 0,
        "substitute_validation": "2026-09-14 침수흔적도 수령 후 Layer 1 ROC-AUC·사후검증으로 대체 예정",
        "ranking_mode": ranking_mode,
        "ranking_claim": (
            "정밀 순위를 주장하지 않는다. 위험군과 강건 공통집합으로만 보고한다"
            if ranking_mode == "tier" else "정밀 순위 보고 가능"
        ),
        "n_selected": int(len(out)),
        "n_in_robust_core": int(out["in_robust_core"].sum()),
        "run_id": run_id,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def top20(ctx: StageContext) -> dict[str, Any]:
    """통과: 선정된 격자마다 트리거·담당·조치·KPI 가 모두 채워져 있어야 한다.
    비어 있으면 그 격자를 표에서 뺀다. 민원 홀드아웃은 비공개라 최종 1회 평가를 수행하지 않고
    `holdout_evaluated=false` 로 기록한다 (docs/decisions/001)."""
    p = ctx.params
    top_n = int(p["cdri.top_n"])
    radius = float(p["policy.nms_radius_m"])

    cdri, formula = _load_candidates()
    ranking_mode = formula.get("ranking_mode", "rank")
    m: dict[str, Any] = {
        "ranking_mode": ranking_mode,
        "n_candidates": int(len(cdri)),
        "nms_radius_m": radius,
        "primary_formula": formula.get("primary_formula"),
    }

    selected = _suppress_neighbours(cdri, radius, top_n)
    m["n_selected"] = int(len(selected))
    m["n_in_robust_core"] = int(selected["in_robust_core"].sum())

    out = selected.copy()
    m["dong_names_available"] = _attach_place_names(out)
    out["rank"] = range(1, len(out) + 1)
    out = _build_policy_cards(out, ctx.run_id)
    out, dropped = _drop_incomplete_cards(out)
    m["n_dropped_incomplete"] = dropped

    if out.empty:
        raise StageFailed(
            "정책카드를 채운 격자가 하나도 없다",
            [{"code": "no_policy_card", "detail": "주 원인별 행동 계약 매핑 확인"}], metrics=m,
        )
    m.update(_summarise(out))

    csv = next(o for o in ctx.outputs if o.suffix == ".csv")
    csv.parent.mkdir(parents=True, exist_ok=True)
    out[POLICY_COLUMNS].to_csv(csv, index=False, encoding="utf-8-sig")
    _write_evaluation(next(o for o in ctx.outputs if o.suffix == ".json"), out, ranking_mode, ctx.run_id)
    return m
