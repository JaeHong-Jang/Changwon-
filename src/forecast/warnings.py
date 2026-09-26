"""기상청 특보 이력과 특보구역 표를 해석한다."""

from __future__ import annotations

from datetime import datetime
import re

import pandas as pd


WARNING_COLUMNS = ['TM_FC', 'TM_EF', 'TM_IN', 'STN', 'REG_ID', 'WRN', 'LVL', 'CMD',
                   'GRD', 'CNT', 'RPT'] + [f'T{i:02d}' for i in range(1, 19)]


def parse_warnings(raw: bytes) -> pd.DataFrame:
    """EUC-KR 특보 CSV 의 모든 자료 행을 검증해 읽는다."""
    # 주석을 건너뛰고 자료 행의 고정 필드 수와 필수 필드를 검사한다.
    rows = []
    for line_number, line in enumerate(raw.decode('euc-kr').splitlines(), 1):
        if not line or line.startswith('#'):
            continue
        parts = [part.strip() for part in line.split(',')]
        if parts[-1] == '=':
            parts.pop()
        if len(parts) < 11:
            raise ValueError(f'특보 행 {line_number}: 열 수 오류')
        try:
            for field in (parts[0], parts[1]):
                if not re.fullmatch(r'\d{12}', field):
                    raise ValueError
                datetime.strptime(field, '%Y%m%d%H%M')
            if not re.fullmatch(r'[A-Z]\d{7}', parts[4]):
                raise ValueError
            if not re.fullmatch(r'[A-Z]', parts[5]):
                raise ValueError
            if parts[6] not in {'1', '2', '3', '4'} or parts[7] not in {'1', '2', '3', '4', '5', '6', '7'}:
                raise ValueError
        except ValueError:
            raise ValueError(f'특보 행 {line_number}: 필수 필드 형식 오류') from None
        rows.append((parts + [''] * len(WARNING_COLUMNS))[:len(WARNING_COLUMNS)])
    frame = pd.DataFrame(rows, columns=WARNING_COLUMNS)

    # API 의 KST 벽시각을 시간대 정보가 있는 datetime 으로 변환한다.
    for column in ('TM_FC', 'TM_EF', 'TM_IN'):
        frame[column] = pd.to_datetime(frame[column], format='%Y%m%d%H%M', errors='coerce').dt.tz_localize('Asia/Seoul')
    return frame


def parse_zones(raw: bytes) -> pd.DataFrame:
    """EUC-KR 특보구역 목록에서 코드, 적용일, 상위구역과 이름을 읽는다."""
    # 앞의 고정 폭 식별자를 나눈 뒤 마지막 한글 명칭을 쓴다.
    rows = []
    for line in raw.decode('euc-kr').splitlines():
        if not line or line.startswith('#'):
            continue
        parts = line.split(maxsplit=6)
        if len(parts) < 7:
            continue
        rows.append({'REG_ID': parts[0], 'TM_ST': parts[1], 'TM_ED': parts[2],
                     'REG_UP': parts[4], 'REG_NAME': parts[6].split()[-1]})
    return pd.DataFrame(rows, columns=['REG_ID', 'TM_ST', 'TM_ED', 'REG_UP', 'REG_NAME'])


def changwon_rows(df: pd.DataFrame, zones: pd.DataFrame,
                  reg_ids: tuple[str, ...] = ('L1080600',)) -> pd.DataFrame:
    """창원·마산·진해 특보구역의 원본 이력 행을 고른다."""
    # 주어진 기본 코드와 이름으로 확인한 추가 코드를 합친다.
    names = zones.REG_NAME.astype(str).str.contains('창원|마산|진해', regex=True)
    used = sorted(set(reg_ids) | set(zones.loc[names, 'REG_ID'].astype(str)))
    result = df[df.REG_ID.isin(used)].copy()
    result.attrs['reg_ids'] = used
    return result
