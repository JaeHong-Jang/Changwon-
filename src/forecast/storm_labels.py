"""호우의 인벤토리 역할과 날짜 기반 흔적 연결·라벨을 계산한다."""

from __future__ import annotations

import pandas as pd

from src.models.features import EVENTS

COVERAGE = {"development": [("2006-01-01", "2019-12-31"), ("2025-01-01", "2025-09-17")],
            "holdout": [("2022-01-01", "2024-12-31")]}


def label_window(t0, t1) -> tuple:
    """사상 양 끝 날짜에서 하루씩 확장한 포함 구간을 반환한다."""
    # 시각을 자정으로 정규화해 날짜 단위 창을 만든다.
    return pd.Timestamp(t0).normalize() - pd.Timedelta(days=1), pd.Timestamp(t1).normalize() + pd.Timedelta(days=1)


def assign_roles(storms: pd.DataFrame) -> pd.DataFrame:
    """라벨 창 전체가 단일 인벤토리 구간 안에 있는 사상에 역할을 붙인다."""
    # 경계를 넘는 사상은 uncovered로 남긴다.
    out = storms.copy()
    out["role"] = "uncovered"
    for index, row in out.iterrows():
        lo, hi = label_window(row.t0, row.t1)
        for role, intervals in COVERAGE.items():
            if any(pd.Timestamp(start) <= lo and hi <= pd.Timestamp(end) for start, end in intervals):
                out.loc[index, "role"] = role
    return out


def trace_key_columns(traces: pd.DataFrame) -> list[str]:
    """흔적을 원본 표에서 유일하게 다시 선택할 수 있는 키 열을 확인한다."""
    # 기본 키가 충돌하면 로더의 영속 원본 행 식별자를 추가한다.
    keys = ["source_id", "object_id"]
    if traces[keys].isna().any().any():
        raise ValueError("흔적 기본 키에 결측이 있다")
    duplicates = traces.duplicated(keys, keep=False)
    if duplicates.any():
        keys.append("source_record_id")
        if "source_record_id" not in traces or traces.loc[duplicates, keys].isna().any().any() or traces.duplicated(keys).any():
            raise ValueError("흔적 유일 키를 구성할 source_record_id가 필요하다")
    return keys


def trace_keys(traces: pd.DataFrame) -> pd.Series:
    """중복 기본 키 행에만 원본 행 식별자를 붙인 유일 문자열 키를 반환한다."""
    # 확장 키가 필요한 행만 검증하고 입력 색인과 순서를 보존한다.
    trace_key_columns(traces)
    keys = traces.source_id.astype(str) + "|" + traces.object_id.astype(str)
    duplicates = traces.duplicated(["source_id", "object_id"], keep=False)
    if duplicates.any():
        keys.loc[duplicates] = keys.loc[duplicates] + "|" + traces.loc[duplicates, "source_record_id"].astype(str)
    if keys.duplicated().any():
        raise ValueError("문자열 trace_key가 중복된다")
    return keys.rename("trace_key")


def link_traces(storms: pd.DataFrame, traces: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """같은 역할의 단일 라벨 창에 속한 흔적만 배정하고 제외 사유를 남긴다."""
    # 원본 키를 보존하고 기존 로더의 storm_id 대신 관측 호우 ID를 기록한다.
    keys = trace_keys(traces)
    if storms.storm_id.duplicated().any():
        raise ValueError("storm_id는 유일해야 한다")
    columns = ["source_id", "object_id"] + (["source_record_id"] if "source_record_id" in traces else [])
    out = traces[columns + ["role", "event_date"]].copy().reset_index(drop=True)
    out.insert(0, "trace_key", keys.to_numpy())
    out["event_date"] = pd.to_datetime(out.event_date).dt.normalize()
    out["storm_id"] = pd.Series(pd.NA, index=out.index, dtype="string")
    out["status"] = "unlinked"
    out["candidate_storms"] = ""
    windows = [(row.storm_id, row.role, *label_window(row.t0, row.t1)) for row in storms.itertuples(index=False)]

    # 날짜 없는 흔적과 여러 창에 걸친 흔적은 어느 사상에도 배정하지 않는다.
    for index, date in out.event_date.items():
        if pd.isna(date):
            out.loc[index, "status"] = "undated"
            continue
        dated = [(storm, role) for storm, role, lo, hi in windows if lo <= date <= hi]
        candidates = sorted(storm for storm, role in dated if role != "uncovered" and role == out.loc[index, "role"])
        if not candidates and dated:
            covered = sorted(storm for storm, role in dated if role != "uncovered")
            out.loc[index, "status"] = "role_mismatch" if covered else "uncovered_window"
            out.loc[index, "candidate_storms"] = ";".join(covered or sorted(storm for storm, _ in dated))
            continue
        out.loc[index, "candidate_storms"] = ";".join(candidates)
        if len(candidates) == 1:
            out.loc[index, ["storm_id", "status"]] = [candidates[0], "linked"]
        elif len(candidates) > 1:
            out.loc[index, "status"] = "ambiguous"
    return out.loc[out.status.eq("linked")].copy(), out


def label_storms(storms: pd.DataFrame, storm_links: pd.DataFrame, loaded_roles) -> pd.DataFrame:
    """읽은 인벤토리의 사상에만 라벨·사상 키·양성 연도 표시를 붙인다."""
    # 연결 개수와 날짜를 집계하되 uncovered 사상에는 라벨을 부여하지 않는다.
    out = storms.copy()
    groups = storm_links.groupby("storm_id")
    out["n_linked_traces"] = out.storm_id.map(groups.size()).fillna(0).astype(int)
    dates = groups.event_date.agg(
        lambda values: ";".join(sorted(set(pd.to_datetime(values).dt.strftime("%Y-%m-%d"))))).astype("string")
    out["linked_dates"] = out.storm_id.map(dates).fillna("")
    eligible = out.role.isin(set(loaded_roles) & set(COVERAGE))
    out["label"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out.loc[eligible, "label"] = out.loc[eligible, "n_linked_traces"].gt(0).astype(int)

    # 개발 키는 기존 공간 학습 연도에만 대응시키고 같은 역할·연도의 양성을 표시한다.
    positive = out.label.eq(1).fillna(False)
    development = positive & out.role.eq("development")
    out["event_key"] = pd.Series(pd.NA, index=out.index, dtype="string")
    known = development & out.year.isin(EVENTS)
    out.loc[known, "event_key"] = out.loc[known, "year"].astype(int).astype(str)
    out.loc[positive & out.role.eq("holdout"), "event_key"] = out.loc[positive & out.role.eq("holdout"), "storm_id"]
    active = set(out.loc[positive, ["role", "year"]].itertuples(index=False, name=None))
    out["active_year"] = [(role, year) in active for role, year in zip(out.role, out.year)]
    return out
