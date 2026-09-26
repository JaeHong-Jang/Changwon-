"""과거 발표 단기예보의 중복 없는 수집 계획을 계산한다."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


ISSUE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)


def _time(value: str | datetime | pd.Timestamp) -> datetime:
    """KST 벽시각을 시간 단위 datetime 으로 읽는다."""
    # 문자열과 pandas 시각을 하나의 시간 표현으로 맞춘다.
    if isinstance(value, str) and len(value) == 10 and value.isdigit():
        return datetime.strptime(value, '%Y%m%d%H')
    return pd.Timestamp(value).to_pydatetime().replace(tzinfo=None)


def precip_var(tmfc: str | datetime) -> str:
    """발표일의 공식 강수 변수 이름을 고른다."""
    # 공식 변수 전환일을 발표시각에 적용한다.
    t = _time(tmfc)
    return 'R12' if t < datetime(2013, 5, 30) else 'R06' if t < datetime(2021, 6, 29) else 'PCP'


def fallback_var(tmfc: str | datetime) -> str | None:
    """전환일 앞뒤 사흘의 발표일에 함께 요청할 강수 변수를 반환한다."""
    # 양 끝 날짜를 포함해 전환기 두 변수를 계획한다.
    day = _time(tmfc).date()
    for boundary, old, new in ((datetime(2013, 5, 30).date(), 'R12', 'R06'),
                               (datetime(2021, 6, 29).date(), 'R06', 'PCP')):
        if boundary - timedelta(days=3) <= day <= boundary + timedelta(days=3):
            return new if day < boundary else old
    return None


def issue_before(t: str | datetime, lead_h: int) -> datetime:
    """기준시각보다 lead_h 시간 앞선 가장 늦은 발표시각을 찾는다."""
    # 최대 하루 전부터 발표시각을 훑어 정확한 선행시간을 지킨다.
    limit = _time(t) - timedelta(hours=lead_h)
    for days in (0, 1):
        day = (limit - timedelta(days=days)).date()
        matches = [datetime.combine(day, datetime.min.time()).replace(hour=h) for h in ISSUE_HOURS]
        valid = [value for value in matches if value <= limit]
        if valid:
            return max(valid)
    raise RuntimeError('발표시각을 찾을 수 없습니다')


def block_of(var: str, tmef: str | datetime) -> tuple[datetime, datetime]:
    """강수 예보가 대표하는 시간 블록의 시작과 끝을 반환한다."""
    # PCP 는 직전 한 시간, 구 체계는 03시 기준 고정 길이 블록이다.
    t = _time(tmef)
    if var == 'PCP':
        return t - timedelta(hours=1), t
    if var not in ('R06', 'R12'):
        raise ValueError(var)
    hours = 6 if var == 'R06' else 12
    anchor = t.replace(hour=3, minute=0, second=0, microsecond=0)
    start = anchor + timedelta(hours=((t - anchor).total_seconds() // 3600 // hours) * hours)
    return start, start + timedelta(hours=hours)


def target_hours(tmfc: str | datetime, var: str, horizon_h: int = 48) -> list[datetime]:
    """중복 블록을 피하면서 발표 후 기간의 대상시각을 고른다."""
    # 시간별 변수와 3시간 간격 POP 의 시각을 만든다.
    issue = _time(tmfc)
    if var == 'PCP':
        return [issue + timedelta(hours=h) for h in range(1, horizon_h + 1)]
    if var == 'POP':
        return [issue + timedelta(hours=h) for h in range(1, horizon_h + 1, 3)]
    if var not in ('R06', 'R12'):
        raise ValueError(var)

    # 구 체계는 블록 안에서 tmfc+3h 이상인 첫 3시간 정각만 요청한다.
    found: dict[datetime, datetime] = {}
    for h in range(1, horizon_h + 1):
        candidate = issue + timedelta(hours=h)
        if h < 3 or candidate.hour % 3:
            continue
        start, _ = block_of(var, candidate)
        if start > issue:
            found.setdefault(start, candidate)
    return list(found.values())


def plan_for_storms(storms_csv: str | Path, leads: tuple[int, ...] = (24, 6)) -> pd.DataFrame:
    """라벨이 있는 2010년 7월 이후 사상의 발표본 수집표를 만든다."""
    # 라벨과 시작시각이 유효한 사상만 읽는다.
    storms = pd.read_csv(storms_csv, dtype={'storm_id': str, 'label': str})
    storms['t0'] = pd.to_datetime(storms['t0'])
    selected = storms[storms.label.notna() & storms.label.str.strip().ne('') &
                      storms.t0.ge(pd.Timestamp('2010-07-01'))]

    # 발표본마다 전환기 양쪽 강수 변수와 POP 의 전체 대상시각을 계획한다.
    rows = []
    for row in selected.itertuples():
        for lead in leads:
            issue = issue_before(row.t0, int(lead))
            vars_to_fetch = [precip_var(issue)]
            other = fallback_var(issue)
            if other is not None:
                vars_to_fetch.append(other)
            for var in (*vars_to_fetch, 'POP'):
                for target in target_hours(issue, var):
                    rows.append({'storm_id': row.storm_id, 'lead_h': int(lead),
                                 'tmfc': issue.strftime('%Y%m%d%H'), 'tmef': target.strftime('%Y%m%d%H'), 'var': var})
    columns = ['storm_id', 'lead_h', 'tmfc', 'tmef', 'var']
    return pd.DataFrame(rows, columns=columns).drop_duplicates(['tmfc', 'tmef', 'var']).reset_index(drop=True)


def estimate(plan: pd.DataFrame) -> dict[str, float | int]:
    """중복 제거 계획의 호출 수와 응답량을 추정한다."""
    # 기상청 격자 표본의 원문 크기로 하루 5 GB 한도 소비량을 계산한다.
    calls = len(plan.drop_duplicates(['tmfc', 'tmef', 'var']))
    bytes_total = calls * 341297
    return {'calls': calls, 'bytes': bytes_total, 'days_at_5GB': bytes_total / 5_000_000_000}
