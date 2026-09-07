"""H08 우선대응 지역 정책화 — 정책카드는 '문장'이 아니라 트리거-행동 계약이다 (RESEARCH_PLAN §0-6).

CDRI 가 위험군(tier) 모드이면 정밀 순위를 주장하지 않는다. 그 경우 표의 `rank` 는
표시 순서일 뿐이며 `robust_core` 와 `risk_tier` 가 실제 근거다.
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
    "rank", "grid_id", "district", "neighborhood", "cdri", "risk_tier", "in_robust_core",
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
    """300m NMS — 같은 침수 구역이 인접 격자로 여러 번 뽑히는 것을 막는다 (ANALYSIS_PLAN §5)."""
    import numpy as np

    ordered = frame.sort_values("cdri", ascending=False)
    xy = np.column_stack([ordered.geometry.centroid.x, ordered.geometry.centroid.y])
    chosen: list[int] = []
    for i in range(len(ordered)):
        if all(np.hypot(*(xy[i] - xy[j])) >= radius_m for j in chosen):
            chosen.append(i)
            if len(chosen) == limit:
                break
    return ordered.iloc[chosen].copy()


def top20(ctx: StageContext) -> dict[str, Any]:
    """통과: 선정된 격자마다 트리거·담당·조치·KPI 가 모두 채워져 있어야 한다.
    비어 있으면 그 격자를 표에서 뺀다. 민원 홀드아웃은 비공개라 최종 1회 평가를 수행하지 않고
    `holdout_evaluated=false` 로 기록한다 (docs/decisions/001)."""
    import geopandas as gpd
    import pandas as pd

    p = ctx.params
    top_n = int(p["cdri.top_n"])
    radius = float(p["policy.nms_radius_m"])

    cdri = gpd.read_file(PROJECT_ROOT / "data/processed/layers/cdri.gpkg", layer="cdri")
    formula = json.loads((PROJECT_ROOT / "artifacts/evaluation/primary_formula_manifest.json").read_text(encoding="utf-8"))
    ranking_mode = formula.get("ranking_mode", "rank")
    features = pd.read_parquet(
        PROJECT_ROOT / "data/processed/features/grid_features.parquet", columns=["grid_id", "pump_dist_m"]
    )
    cdri = cdri.merge(features, on="grid_id", how="left")

    m: dict[str, Any] = {
        "ranking_mode": ranking_mode,
        "n_candidates": int(len(cdri)),
        "nms_radius_m": radius,
        "primary_formula": formula.get("primary_formula"),
    }

    selected = _suppress_neighbours(cdri, radius, top_n)
    m["n_selected"] = int(len(selected))
    m["n_in_robust_core"] = int(selected["in_robust_core"].sum())

    names_path = PROJECT_ROOT / DONG_NAME_FILE
    names = (
        dict(zip(*pd.read_csv(names_path, encoding="utf-8-sig", dtype={"adm_cd": str})[["adm_cd", "adm_name"]].values.T))
        if names_path.exists() else {}
    )
    m["dong_names_available"] = bool(names)

    out = selected.copy()
    out["district"] = out["gu_code"].astype(str).map(GU_NAMES)
    out["neighborhood"] = out["adm_cd"].astype(str).map(names) if names else "행정동명 미확보"
    out["elderly_estimate"] = (out["pop_total"] * out["elderly_ratio"]).round(0)
    out["hazard_contribution"] = out["h_contribution"].round(4)
    out["exposure_contribution"] = out["e_contribution"].round(4)
    out["vulnerability_contribution"] = out["v_contribution"].round(4)
    out["capacity_deficit_contribution"] = out["d_contribution"].round(4)
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
    out["evidence_run_id"] = ctx.run_id
    out["rank"] = range(1, len(out) + 1)
    out["cdri"] = out["cdri"].round(4)
    out["shelter_dist_m"] = out["shelter_dist_m"].round(0)
    out["pump_dist_m"] = out["pump_dist_m"].round(0)

    required = ["trigger", "recommended_action", "owner_department", "kpi"]
    complete = out[required].notna().all(axis=1) & (out[required] != "").all(axis=1)
    m["n_dropped_incomplete"] = int((~complete).sum())
    out = out[complete].copy()
    out["rank"] = range(1, len(out) + 1)

    if out.empty:
        raise StageFailed(
            "정책카드를 채운 격자가 하나도 없다",
            [{"code": "no_policy_card", "detail": "주 원인별 행동 계약 매핑 확인"}], metrics=m,
        )

    m["selected"] = [
        {
            "rank": int(r.rank), "grid_id": r.grid_id, "district": r.district,
            "cdri": float(r.cdri), "risk_tier": r.risk_tier, "primary_cause": r.primary_cause,
            "robust_core": int(r.in_robust_core), "pop_total": int(r.pop_total),
            "elderly_estimate": int(r.elderly_estimate),
        }
        for r in out.itertuples()
    ]
    m["cause_mix"] = {k: int(v) for k, v in out["primary_cause"].value_counts().items()}
    m["people_covered"] = {
        "pop_total": int(out["pop_total"].sum()),
        "elderly_estimate": int(out["elderly_estimate"].sum()),
        "shelter_over_2km": int((out["shelter_dist_m"] > 2000).sum()),
    }

    csv = next(o for o in ctx.outputs if o.suffix == ".csv")
    csv.parent.mkdir(parents=True, exist_ok=True)
    out[POLICY_COLUMNS].to_csv(csv, index=False, encoding="utf-8-sig")

    evaluation = next(o for o in ctx.outputs if o.suffix == ".json")
    evaluation.parent.mkdir(parents=True, exist_ok=True)
    evaluation.write_text(json.dumps({
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
        "run_id": ctx.run_id,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return m
