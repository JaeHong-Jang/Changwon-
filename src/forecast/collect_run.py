"""단기예보 계획, 원본 수집, 창원 격자 매핑 CLI 를 실행한다."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.forecast.forecast_plan import estimate, plan_for_storms
from src.forecast.kma_client import KMAClient, append_manifest, load_key, sanitize, store_response, url_without_key
from src.forecast.kma_grid import changwon_cells


GRID_PATH = '/api/typ01/cgi-bin/url/nph-dfs_shrt_grd'


def run_plan(storms: str, out: str, leads: tuple[int, ...]) -> None:
    """사상 CSV 로 요청 계획을 만들고 추정량을 출력한다."""
    # 네트워크 없이 계획과 중복 제거 후 호출량을 저장한다.
    plan = plan_for_storms(storms, leads)
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    plan.to_csv(target, index=False)
    print(estimate(plan))


def run_fetch(plan_path: str, store: str, max_calls: int | None) -> None:
    """계획의 미수집 격자만 호출하고 응답과 상태를 기록한다."""
    # 기존 manifest 는 정상 파일의 기록 누락을 복구할 때만 참조한다.
    root = Path(store)
    plan = pd.read_csv(plan_path, dtype=str).drop_duplicates(['tmfc', 'tmef', 'var'])
    manifest = root / 'manifest.csv'
    logged = set()
    if manifest.exists():
        with manifest.open(newline='', encoding='utf-8') as source:
            logged = {row['path'] for row in csv.DictReader(source) if row['status'] in {'ok', 'all_missing'}}
    client = None
    auth_key = None
    counts = {'ok': 0, 'all_missing': 0, 'error': 0, 'bytes_raw': 0, 'calls': 0}

    # 계획된 요청별 정상 파일을 검증하고 오류 기록만 있는 요청은 재시도한다.
    for row in plan.itertuples():
        var = str(row.var)
        relative = f'{var}/{row.tmfc}/{row.tmef}.txt.gz'
        params = {'tmfc': row.tmfc, 'tmef': row.tmef, 'vars': var}
        if (root / relative).exists():
            try:
                record = store_response(root, relative, b'', {**params, 'path': GRID_PATH})
            except Exception:
                print(f'기존 정상 경로 파싱 실패, 리더 처리 필요: {sanitize(relative, "")}')
                continue
            if relative not in logged:
                append_manifest(manifest, [record])
                logged.add(relative)
            continue
        if max_calls is not None and counts['calls'] >= max_calls:
            print(counts)
            return
        if client is None:
            auth_key = load_key()
            client = KMAClient(auth_key)
        counts['calls'] += 1
        try:
            raw = client.get(GRID_PATH, params)
            record = store_response(root, relative, raw, {**params, 'path': GRID_PATH}, key=auth_key)
        except Exception:
            record = {'path': relative, 'tmfc': row.tmfc, 'tmef': row.tmef, 'var': var,
                      'url_without_key': url_without_key(GRID_PATH, params), 'sha256_gz': '', 'bytes_raw': 0,
                      'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'status': 'error', 'n_valid': ''}
            print(f'{sanitize(relative, auth_key or "")}: 응답 처리 실패')
        append_manifest(manifest, [record])
        counts[record['status']] += 1
        counts['bytes_raw'] += int(record['bytes_raw'])
    print(counts)


def run_cells(out: str) -> None:
    """창원 분석 격자의 예보 격자 대응표를 저장한다."""
    # 분석 격자 중심점 대응을 두 CSV 로 저장하고 범위를 출력한다.
    cells, mapping = changwon_cells()
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    cells.to_csv(root / 'cells.csv', index=False)
    mapping.to_csv(root / 'mapping.csv', index=False)
    print({'cells': len(cells), 'analysis_grid_cells': len(mapping),
           'nx': [int(cells.nx.min()), int(cells.nx.max())],
           'ny': [int(cells.ny.min()), int(cells.ny.max())]})


def main() -> None:
    """CLI 명령에 따라 계획, 수집, 격자 매핑을 실행한다."""
    # 각 하위 명령의 인자를 검사한 뒤 해당 실행 함수를 호출한다.
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan')
    plan.add_argument('--storms', required=True)
    plan.add_argument('--out', required=True)
    plan.add_argument('--leads', nargs='+', type=int, default=[24, 6])
    fetch = commands.add_parser('fetch')
    fetch.add_argument('--plan', required=True)
    fetch.add_argument('--store', default='data/raw/kma/short_forecast')
    fetch.add_argument('--max-calls', type=int)
    cells = commands.add_parser('cells')
    cells.add_argument('--out', default='artifacts/forecast/grid')
    args = parser.parse_args()
    if args.command == 'plan':
        run_plan(args.storms, args.out, tuple(args.leads))
    elif args.command == 'fetch':
        run_fetch(args.plan, args.store, args.max_calls)
    else:
        run_cells(args.out)


if __name__ == '__main__':
    main()
