"""호우특보 월별 수집과 창원 이력 산출물 생성 CLI 를 실행한다."""

from __future__ import annotations

import argparse
import csv
import gzip
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.forecast.kma_client import KMAClient, append_manifest, load_key, response_status, sanitize, store_response, url_without_key
from src.forecast.warnings import changwon_rows, parse_warnings, parse_zones
from src.models.provenance import file_sha256, write_json


WARNING_PATH = '/api/typ01/url/wrn_met_data.php'
FIXTURE_ZONES = Path('tests/fixtures/kma/wrn_reg_latest.txt.gz')


def _months(start: str, end: str) -> list[pd.Period]:
    """양 끝 월을 포함한 월별 구간을 만든다."""
    # 월 단위 기간을 순서대로 열거한다.
    return list(pd.period_range(start=start, end=end, freq='M'))


def run_fetch(start: str, end: str, store: str) -> None:
    """기간별 특보 원문을 월 단위로 받아 manifest 에 기록한다."""
    # 기존 원문은 검증해서 재사용하고 오류 기록만 있는 월은 다시 요청한다.
    root = Path(store)
    manifest = root / 'manifest.csv'
    if manifest.exists():
        with manifest.open(newline='', encoding='utf-8') as source:
            logged = {row['path'] for row in csv.DictReader(source) if row['status'] == 'ok'}
    else:
        logged = set()
    client = None
    auth_key = None
    counts = {'ok': 0, 'error': 0, 'bytes_raw': 0}

    # 월말 다음날 00시 직전까지의 KST 시각으로 각 요청을 만든다.
    for month in _months(start, end):
        begin = month.start_time.strftime('%Y%m%d%H%M')
        end_time = month.end_time.floor('min').strftime('%Y%m%d%H%M')
        params = {'reg': 0, 'wrn': 'A', 'tmfc1': begin, 'tmfc2': end_time, 'disp': 1, 'help': 1}
        relative = month.strftime('%Y%m') + '.txt.gz'
        if (root / relative).exists():
            try:
                record = store_response(root, relative, b'', {**params, 'path': WARNING_PATH})
            except Exception:
                print(f'기존 정상 경로 파싱 실패, 리더 처리 필요: {sanitize(relative, "")}')
                continue
            if relative not in logged:
                append_manifest(manifest, [record])
                logged.add(relative)
            continue
        if client is None:
            auth_key = load_key()
            client = KMAClient(auth_key)
        try:
            raw = client.get(WARNING_PATH, params)
            record = store_response(root, relative, raw, {**params, 'path': WARNING_PATH}, key=auth_key)
        except Exception:
            print(f'{sanitize(relative, auth_key or "")}: 응답 처리 실패')
            record = {'path': relative, 'tmfc': begin, 'tmef': end_time, 'var': 'warning',
                      'url_without_key': url_without_key(WARNING_PATH, params), 'sha256_gz': '', 'bytes_raw': 0,
                      'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'status': 'error', 'n_valid': ''}
        append_manifest(manifest, [record])
        counts[record['status']] += 1
        counts['bytes_raw'] += int(record['bytes_raw'])
    print(counts)


def run_build(store: str, out: str, start: str = '2005-07', end: str = '2025-09',
              allow_missing: bool = False) -> Path:
    """월별 원문과 특보구역 표로 창원 호우·태풍 특보표를 만든다."""
    # 요청 기간의 모든 월에 정상 manifest 행과 검증 가능한 원문이 있는지 확인한다.
    root = Path(store)
    manifest = root / 'manifest.csv'
    if not manifest.exists():
        raise FileNotFoundError(manifest)
    with manifest.open(newline='', encoding='utf-8') as source:
        records = list(csv.DictReader(source))
    latest = {record['tmfc'][:6]: record for record in records if record['var'] == 'warning'}
    coverage = []
    frames = []
    for month in _months(start, end):
        name = month.strftime('%Y%m')
        record = latest.get(name)
        status = record['status'] if record else 'missing'
        source_path = root / f'{name}.txt.gz'
        if status == 'ok':
            if not source_path.exists():
                status = 'missing'
            else:
                try:
                    with gzip.open(source_path, 'rb') as source:
                        raw = source.read()
                    response_status(raw, 'warning')
                    frames.append(parse_warnings(raw))
                except (OSError, ValueError, UnicodeError):
                    status = 'error'
        coverage.append({'month': month.strftime('%Y-%m'), 'status': status})
    missing_months = [item['month'] for item in coverage if item['status'] != 'ok']
    if missing_months and not allow_missing:
        raise RuntimeError('누락 또는 오류 특보 월: ' + ', '.join(missing_months))

    # 저장소의 구역표를 우선하고 없으면 검증된 제공 표본을 사용한다.
    zone_path = root / 'wrn_reg_latest.txt.gz'
    if not zone_path.exists():
        zone_path = FIXTURE_ZONES
    with gzip.open(zone_path, 'rb') as source:
        zones = parse_zones(source.read())

    # 정상 월의 이력만 결합하고 창원 호우·태풍 행을 고른다.
    all_rows = pd.concat(frames, ignore_index=True) if frames else parse_warnings(b'')
    chosen = changwon_rows(all_rows, zones)
    result = chosen[chosen.WRN.isin(('R', 'T'))][['TM_FC', 'TM_EF', 'TM_IN', 'REG_ID', 'WRN', 'LVL', 'CMD']]

    # 공통 provenance 함수로 입력 해시를 기록하고 고유 실행 폴더를 만든다.
    manifest_sha = file_sha256(manifest)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + manifest_sha[:8]
    destination = Path(out) / run_id
    destination.mkdir(parents=True, exist_ok=False)
    result.to_csv(destination / 'changwon_warnings.csv', index=False)
    pd.DataFrame(coverage, columns=['month', 'status']).to_csv(destination / 'coverage.csv', index=False)
    if missing_months:
        pd.DataFrame([item for item in coverage if item['status'] != 'ok']).to_csv(
            destination / 'missing_months.csv', index=False)
    write_json(destination / 'manifest.json', {'run_id': run_id, 'input_manifest_sha256': manifest_sha,
                                               'zone_sha256': file_sha256(zone_path),
                                               'reg_ids': chosen.attrs['reg_ids'], 'rows': len(result),
                                               'missing_months': missing_months})
    print({'run_id': run_id, 'rows': len(result), 'reg_ids': chosen.attrs['reg_ids']})
    return destination


def main() -> None:
    """특보 수집 또는 창원 특보표 생성을 실행한다."""
    # CLI 의 월 범위와 저장 경로를 각 실행 함수에 전달한다.
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    fetch = commands.add_parser('fetch')
    fetch.add_argument('--start', default='2005-01')
    fetch.add_argument('--end', default='2025-09')
    fetch.add_argument('--store', default='data/raw/kma/warnings')
    build = commands.add_parser('build')
    build.add_argument('--store', default='data/raw/kma/warnings')
    build.add_argument('--out', default='artifacts/forecast/warnings')
    build.add_argument('--start', default='2005-07')
    build.add_argument('--end', default='2025-09')
    build.add_argument('--allow-missing', action='store_true')
    args = parser.parse_args()
    if args.command == 'fetch':
        run_fetch(args.start, args.end, args.store)
    else:
        run_build(args.store, args.out, args.start, args.end, args.allow_missing)


if __name__ == '__main__':
    main()
