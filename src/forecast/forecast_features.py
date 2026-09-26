"""고정 발표본과 완전 포함 블록에서 창원 예보 특징을 계산한다."""

import numpy as np
import pandas as pd

from src.forecast.forecast_plan import issue_before, precip_var
from src.forecast.kma_grid import value_at
from src.forecast.time_utils import parse_time


FEATURE_COLUMNS = ["storm_id", "lead_h", "tmfc", "var", "r12max_fc", "pop_max", "n_blocks", "status", "n_error_blocks"]


def _candidates(issue):
    """전환일 전후 삼일에만 인접 강수 변수를 추가한다."""
    # 둘 다 유효하면 날짜 규칙의 변수가 항상 우선한다.
    primary = precip_var(issue)
    candidates = [primary]
    for day, old, new in (("2013-05-30", "R12", "R06"), ("2021-06-29", "R06", "PCP")):
        if abs((issue.normalize() - pd.Timestamp(day)).days) <= 3:
            candidates.append(new if primary == old else old)
    return candidates


def _cell_values(path, cells, grid_loader, cache):
    """격자를 읽되 캐시에는 창원 값과 전국 유효 여부만 보관한다."""
    # 수천 발표 파일의 전국 배열을 계속 쌓아 메모리를 소모하지 않는다.
    if path not in cache:
        grid = grid_loader(path)
        selected = np.array([value_at(grid, int(c.nx), int(c.ny)) for c in cells.itertuples()])
        cache[path] = selected, bool(np.isfinite(grid).any())
    return cache[path]


def _blocks(rows, var, issue, horizon_h, cells, grid_loader, block_of, cache):
    """예상 완전 블록마다 창원값 또는 미제공·수집실패 상태를 구한다."""
    # 대상시각 하나만 있어도 그 블록 전체가 대표되므로 블록 키로 중복을 제거한다.
    end = issue + pd.Timedelta(hours=horizon_h)
    expected = set()
    for hour in range(horizon_h + 1):
        start, stop = map(pd.Timestamp, block_of(var, issue + pd.Timedelta(hours=hour)))
        if start >= issue and stop <= end:
            expected.add((start, stop))
    values, states = {}, {}
    for key in sorted(expected):
        candidates = []
        for row in rows.itertuples():
            if tuple(map(pd.Timestamp, block_of(var, row.tmef))) == key:
                candidates.append(row)
        states[key] = "collection_error"
        for row in candidates:
            if row.status == "all_missing":
                states[key] = "all_missing"
            if row.status != "ok":
                continue
            try:
                selected, nationally_valid = _cell_values(row.path, cells, grid_loader, cache)
            except (OSError, ValueError, IndexError, EOFError):
                states[key] = "collection_error"
                continue
            if not nationally_valid:
                states[key] = "all_missing"
                continue
            values[key] = selected
            states[key] = "ok" if np.isfinite(selected).any() else "no_valid_cells"
            break
    return values, states


def _accumulation(values, var):
    """격자별 연속 블록을 합한 뒤 격자와 창의 최댓값을 구한다."""
    # 각 합산창에서 한 격자라도 결측이면 그 격자 창을 쓰지 않는다.
    width = {"R12": 12, "R06": 6, "PCP": 1}[var]
    count = 12 // width
    maxima = []
    for start, stop in sorted(values):
        keys = [(start + pd.Timedelta(hours=width * j), stop + pd.Timedelta(hours=width * j)) for j in range(count)]
        if not all(key in values for key in keys):
            continue
        total = np.stack([values[key] for key in keys]).sum(axis=0)
        if np.isfinite(total).any():
            maxima.append(float(np.nanmax(total)))
    return max(maxima) if maxima else np.nan


def _pop_max(rows, issue, horizon_h, cells, grid_loader, cache):
    """같은 발표 후 범위에서 창원 격자 POP 최댓값을 구한다."""
    # POP는 기술용으로만 계산하며 강수 결측을 대신하지 않는다.
    selected = rows[(rows["var"] == "POP") & (rows.status == "ok") &
                    rows.tmef.gt(issue) & rows.tmef.le(issue + pd.Timedelta(hours=horizon_h))]
    maxima = []
    for row in selected.itertuples():
        try:
            values, _ = _cell_values(row.path, cells, grid_loader, cache)
        except (OSError, ValueError, IndexError, EOFError):
            continue
        if np.isfinite(values).any():
            maxima.append(float(np.nanmax(values)))
    return max(maxima) if maxima else np.nan


def storm_forecast_features(storms, manifest, cells, *, leads=(24, 6), horizon_h=48, grid_loader, block_of):
    """사상별 예정 발표본의 강수 특징과 자료 가용 상태를 반환한다."""
    # 시각 정규화와 격자 캐시는 계산 호출 안에서만 유지한다.
    manifest = manifest.copy()
    for column in ("tmfc", "tmef"):
        manifest[column] = manifest[column].map(parse_time)
    cells = cells.drop_duplicates(["nx", "ny"])
    cache, result = {}, []
    for storm in storms.itertuples():
        for lead in leads:
            issue = pd.Timestamp(issue_before(parse_time(storm.t0), lead))
            row = dict(storm_id=storm.storm_id, lead_h=lead, tmfc=issue, var=precip_var(issue),
                       r12max_fc=np.nan, pop_max=np.nan, n_blocks=0, status="missing_issue", n_error_blocks=0)
            result.append(row)
            if parse_time(storm.t0) < pd.Timestamp("2010-07-01"):
                row["status"] = "outside_coverage"
                continue
            issue_rows = manifest[manifest.tmfc.eq(issue)]
            if issue_rows.empty:
                continue
            row["pop_max"] = _pop_max(issue_rows, issue, horizon_h, cells, grid_loader, cache)
            choices = []
            for var in _candidates(issue):
                values, states = _blocks(issue_rows[issue_rows["var"].eq(var)], var, issue,
                                         horizon_h, cells, grid_loader, block_of, cache)
                choices.append((var, values, states))
            # 창원 유효값이 있는 변수를 고르고 둘 다 유효하면 날짜 규칙을 우선한다.
            chosen = next((choice for choice in choices if "ok" in choice[2].values()), choices[0])
            var, values, states = chosen
            row.update(var=var, n_blocks=sum(s == "ok" for s in states.values()),
                       n_error_blocks=sum(s == "collection_error" for s in states.values()))
            statuses = set(states.values())
            # 수집 실패가 하나라도 남으면 최대값의 하향 편향을 막기 위해 NA로 두고 공식 미제공만 제외한다.
            if "collection_error" in statuses:
                row["status"] = "collection_error"
                continue
            row["r12max_fc"] = _accumulation(values, var)
            if not states or statuses == {"all_missing"}:
                row["status"] = "all_missing"
            elif not np.isfinite(row["r12max_fc"]):
                row["status"] = "no_valid_cells" if "no_valid_cells" in statuses else "insufficient_blocks"
            elif "all_missing" in statuses:
                row["status"] = "partial_all_missing"
            elif "no_valid_cells" in statuses:
                row["status"] = "partial_missing_cells"
            else:
                row["status"] = "ok"
    return pd.DataFrame(result, columns=FEATURE_COLUMNS)
