"""기상청 격자, 계획, 응답 저장, 특보 파서를 로컬에서 검증한다."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.forecast.forecast_plan import (block_of, fallback_var, issue_before, plan_for_storms,
                                        precip_var, target_hours)
from src.forecast.kma_client import KEY_IN_RESPONSE, KMAClient, append_manifest, contains_key, response_status, store_response
from src.forecast.kma_grid import lonlat_to_grid, parse_grid, value_at
from src.forecast.collect_run import run_fetch as grid_fetch
from src.forecast.warnings import changwon_rows, parse_warnings, parse_zones
from src.forecast.warnings_run import main as warnings_main, run_build, run_fetch as warnings_fetch


FIXTURES = Path('tests/fixtures/kma')


def fixture(name: str) -> bytes:
    """제공된 gzip 표본의 원문을 반환한다."""
    # 읽기 전용 표본만 압축 해제한다.
    return gzip.decompress((FIXTURES / name).read_bytes())


class FakeResponse(io.BytesIO):
    """urllib 응답처럼 context manager 로 읽히는 바이트 객체다."""


class FakeOpener:
    """지정된 실패 횟수 뒤 성공하는 HTTP 대역이다."""

    def __init__(self, status: int, failures: int):
        """실패 코드와 실패 횟수를 저장한다."""
        # 각 요청이 호출될 때 응답 순서를 확인한다.
        self.status = status
        self.failures = failures
        self.calls = 0

    def open(self, url: str, timeout: int = 30) -> FakeResponse:
        """실패를 재현한 뒤 성공 바이트를 반환한다."""
        # URL 에 키가 들어간 오류를 만들어 예외 정제를 시험한다.
        self.calls += 1
        if self.calls <= self.failures:
            raise urllib.error.HTTPError(url, self.status, f'bad key {url}', {}, None)
        return FakeResponse(b'ok')


class GridTests(unittest.TestCase):
    """격자 좌표와 배열 방향을 실제 기온 표본으로 검증한다."""

    def test_lcc_and_sample_orientation(self):
        """서울·제주 육지와 서해·동해 결측이 남쪽 첫 행에서 맞는지 확인한다."""
        # 기상청 공식 서울 좌표와 표본의 유효 9,295칸을 확인한다.
        self.assertEqual(lonlat_to_grid(126.9784, 37.5667), (60, 127))
        grid = parse_grid(fixture('grid_TMP_2024022505_2024022506.txt.gz'))
        self.assertEqual(grid.shape, (253, 149))
        self.assertEqual(int(np.isfinite(grid).sum()), 9295)

        # 북쪽 첫 행으로 뒤집으면 제주가 결측이므로 남쪽 첫 행을 고정한다.
        self.assertTrue(np.isfinite(value_at(grid, 60, 127)))
        self.assertTrue(np.isfinite(value_at(grid, 52, 38)))
        self.assertTrue(np.isnan(value_at(grid, 20, 100)))
        self.assertTrue(np.isnan(value_at(grid, 130, 150)))
        self.assertTrue(np.isnan(grid[253 - 38, 52 - 1]))

    def test_all_missing(self):
        """전 격자 결측 응답을 NaN 으로 바꾼다."""
        # 제공 안 되는 대상시각의 R06 표본을 사용한다.
        grid = parse_grid(fixture('grid_R06_2014011005_2014011006_missing.txt.gz'))
        self.assertTrue(np.isnan(grid).all())


class PlanTests(unittest.TestCase):
    """발표시각, 변수 경계와 블록별 요청 시각을 검증한다."""

    def test_vars_and_issue(self):
        """변수 전환일과 선행시간 이전 발표본을 고른다."""
        # 양쪽 경계와 정시 발표를 확인한다.
        self.assertEqual(precip_var('2013052905'), 'R12')
        self.assertEqual(precip_var('2013053005'), 'R06')
        self.assertEqual(precip_var('2021062805'), 'R06')
        self.assertEqual(precip_var('2021062905'), 'PCP')
        self.assertEqual(fallback_var('2013052905'), 'R06')
        self.assertEqual(fallback_var('2013060202'), 'R12')
        self.assertEqual(fallback_var('2021070202'), 'R06')
        self.assertIsNone(fallback_var('2021070302'))
        self.assertIsNone(fallback_var('2013061005'))
        self.assertEqual(issue_before('2024-01-10 06:00', 6), datetime(2024, 1, 9, 23))
        self.assertEqual(issue_before('2024-01-10 11:00', 6), datetime(2024, 1, 10, 5))

    def test_targets(self):
        """PCP·POP 매시/3시간과 R06·R12 블록 규칙을 확인한다."""
        # 구 체계는 블록 안에서 tmfc+3h 이상인 첫 3시간 정각을 쓴다.
        self.assertEqual(len(target_hours('2014011005', 'PCP')), 48)
        self.assertEqual(len(target_hours('2014011005', 'POP')), 16)
        r06 = target_hours('2014011005', 'R06')
        r12 = target_hours('2012011005', 'R12')
        self.assertEqual(len(r06), 8)
        self.assertEqual(r06[0], datetime(2014, 1, 10, 9))
        self.assertEqual(len(r12), 4)
        self.assertEqual(r12[0], datetime(2012, 1, 10, 15))
        self.assertEqual(block_of('R06', r06[0]), (datetime(2014, 1, 10, 9), datetime(2014, 1, 10, 15)))
        self.assertEqual(block_of('R12', r12[0]), (datetime(2012, 1, 10, 15), datetime(2012, 1, 11, 3)))

    def test_transition_plans_both_full_variables(self):
        """전환일 사흘 뒤까지 두 강수 변수의 전체 대상시각을 넣는다."""
        # 발표본을 고정해 두 변수와 POP 의 요청 수를 비교한다.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'storms.csv'
            pd.DataFrame([{'storm_id': 'a', 't0': '2021-07-03 05:00', 'label': '1'}]).to_csv(path, index=False)
            plan = plan_for_storms(path, leads=(24,))
            issue = issue_before('2021-07-03 05:00', 24).strftime('%Y%m%d%H')
            self.assertEqual(issue[:8], '20210702')
            for var in ('R06', 'PCP', 'POP'):
                self.assertEqual(set(plan.loc[plan['var'].eq(var), 'tmef']),
                                 {hour.strftime('%Y%m%d%H') for hour in target_hours(issue, var)})
            self.assertEqual(len(plan.loc[plan['var'].eq('PCP')]), 48)

    def test_plan_filters_and_dedup(self):
        """빈 라벨과 이른 사상을 빼고 같은 요청을 한 번만 둔다."""
        # 같은 사상 시작시각 두 건과 제외 대상 두 건을 만든다.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'storms.csv'
            pd.DataFrame([{'storm_id': 'a', 't0': '2014-01-10 12:00', 'label': '1'},
                          {'storm_id': 'b', 't0': '2014-01-10 12:00', 'label': '0'},
                          {'storm_id': 'c', 't0': '2014-01-10 12:00', 'label': ''},
                          {'storm_id': 'd', 't0': '2010-06-30 12:00', 'label': '1'}]).to_csv(path, index=False)
            plan = plan_for_storms(path)
            self.assertTrue(set(plan.storm_id).issubset({'a', 'b'}))
            self.assertFalse(plan.duplicated(['tmfc', 'tmef', 'var']).any())
            self.assertGreater(len(plan), 0)


class ClientTests(unittest.TestCase):
    """가짜 HTTP 와 임시 저장소로 네트워크 없는 수집을 검증한다."""

    def test_percent_and_form_decoding_keep_distinct_key_meanings(self):
        """일반 디코딩은 더하기를 보존하고 폼 디코딩은 공백을 복원한다."""
        # 이중 URL 인코딩과 폼 인코딩을 각각 독립 경로로 검사한다.
        key = 'K+한%문'
        encoded = urllib.parse.quote(key, safe='+').encode('ascii')
        nested = urllib.parse.quote_from_bytes(encoded, safe='+').encode('ascii')
        self.assertTrue(contains_key(nested, key))
        spaced_key = 'K 한%문'
        self.assertTrue(contains_key(urllib.parse.quote_plus(spaced_key).encode('ascii'), spaced_key))
        self.assertFalse(contains_key(b'other response', key))

    def test_retry_and_key_redaction(self):
        """504 두 번은 재시도하고 4xx 는 즉시 키 없는 오류를 낸다."""
        # 실패 후 성공하는 opener 와 영구 4xx opener 를 각각 사용한다.
        success = FakeOpener(504, 2)
        self.assertEqual(KMAClient('SECRET', opener=success, pause_s=0, backoff_s=0).get('/x', {}), b'ok')
        self.assertEqual(success.calls, 3)
        bad = FakeOpener(401, 2)
        with self.assertRaises(RuntimeError) as caught:
            KMAClient('SECRET', opener=bad, pause_s=0, backoff_s=0).get('/x', {})
        self.assertEqual(bad.calls, 1)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_store_resume_and_hash(self):
        """기존 gzip 을 덮어쓰지 않고 해시와 manifest 헤더를 기록한다."""
        # 유효한 특보 표본으로 저장 경로와 결정적 gzip 을 시험한다.
        with tempfile.TemporaryDirectory() as folder:
            params = {'path': '/api/typ01/url/wrn_met_data.php', 'tmfc1': '201501010000', 'authKey': 'SECRET'}
            raw = fixture('wrn_met_data_201501.txt.gz')
            first = store_response(folder, '201501.txt.gz', raw, params)
            second = store_response(folder, '201501.txt.gz', b'two', params)
            path = Path(folder) / '201501.txt.gz'
            self.assertEqual(gzip.decompress(path.read_bytes()), raw)
            self.assertEqual(first['sha256_gz'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(first['sha256_gz'], second['sha256_gz'])
            self.assertNotIn('SECRET', first['url_without_key'])
            append_manifest(Path(folder) / 'manifest.csv', [first])
            append_manifest(Path(folder) / 'manifest.csv', [second])
            self.assertEqual((Path(folder) / 'manifest.csv').read_text().count('sha256_gz'), 1)

    def test_html_error_is_preserved_and_retried(self):
        """HTML 오류는 오류 폴더에 남고 다음 실행에서 정상 격자를 다시 받는다."""
        # 첫 실행은 HTML, 두 번째 실행은 정상 PCP 표본을 돌려준다.
        class Responses:
            """응답 바이트 목록을 순서대로 제공한다."""

            def __init__(self):
                """두 번의 HTTP 요청을 센다."""
                # 가짜 응답 순서를 저장한다.
                self.raws = [b'<html>error</html>', fixture('grid_PCP_2022011005_2022011006.txt.gz')]
                self.calls = 0

            def get(self, path, params):
                """다음 원문을 반환한다."""
                # 호출마다 다른 서버 응답을 사용한다.
                raw = self.raws[self.calls]
                self.calls += 1
                return raw

        # 정상 캐시의 부재와 오류 원문 경로 및 재개 결과를 확인한다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = root / 'plan.csv'
            pd.DataFrame([{'storm_id': 'a', 'lead_h': 24, 'tmfc': '2022011005',
                           'tmef': '2022011006', 'var': 'PCP'}]).to_csv(plan, index=False)
            responses = Responses()
            with patch('src.forecast.collect_run.load_key', return_value='FAKE'), \
                 patch('src.forecast.collect_run.KMAClient', return_value=responses):
                grid_fetch(str(plan), str(root / 'store'), None)
                normal = root / 'store/PCP/2022011005/2022011006.txt.gz'
                self.assertFalse(normal.exists())
                errors = list((root / 'store/_errors/PCP/2022011005').glob('*.txt.gz'))
                self.assertEqual(len(errors), 1)
                self.assertEqual(gzip.decompress(errors[0].read_bytes()), b'<html>error</html>')
                grid_fetch(str(plan), str(root / 'store'), None)
            self.assertTrue(normal.exists())
            self.assertEqual(responses.calls, 2)
            with (root / 'store/manifest.csv').open(newline='', encoding='utf-8') as source:
                self.assertEqual([row['status'] for row in csv.DictReader(source)], ['error', 'ok'])

    def test_missing_r06_keeps_full_pcp_plan(self):
        """R06 전결측이어도 PCP 는 자체 48시간 계획 전부 요청한다."""
        # 두 변수의 계획을 만들고 POP 결측까지 포함한 가짜 응답을 제공한다.
        class Responses:
            """변수별 전결측 또는 정상 표본을 돌려준다."""

            def __init__(self):
                """요청 변수를 기록한다."""
                # 변수별 호출 횟수를 세기 위한 목록이다.
                self.vars = []

            def get(self, path, params):
                """PCP 만 정상인 격자 응답을 반환한다."""
                # R06 과 POP 의 전결측이 추가 요청을 만들지 않게 한다.
                self.vars.append(params['vars'])
                if params['vars'] == 'PCP':
                    return fixture('grid_PCP_2022011005_2022011006.txt.gz')
                return fixture('grid_R06_2014011005_2014011006_missing.txt.gz')

        # 수집 계획의 PCP 48개가 모두 실행되고 중복 호출이 없는지 확인한다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            issue = '2021062805'
            plan = root / 'plan.csv'
            pd.DataFrame([{'storm_id': 'a', 'lead_h': 24, 'tmfc': issue,
                           'tmef': hour.strftime('%Y%m%d%H'), 'var': var}
                          for var in ('R06', 'PCP', 'POP') for hour in target_hours(issue, var)]).to_csv(plan, index=False)
            responses = Responses()
            with patch('src.forecast.collect_run.load_key', return_value='FAKE'), \
                 patch('src.forecast.collect_run.KMAClient', return_value=responses):
                grid_fetch(str(plan), str(root / 'store'), None)
            self.assertEqual(responses.vars.count('PCP'), 48)
            self.assertEqual(responses.vars.count('R06'), len(target_hours(issue, 'R06')))
            self.assertEqual(responses.vars.count('POP'), 16)
            with (root / 'store/manifest.csv').open(newline='', encoding='utf-8') as source:
                records = list(csv.DictReader(source))
            self.assertEqual(sum(row['var'] == 'PCP' and row['status'] == 'ok' for row in records), 48)

    def test_reflected_key_is_discarded_without_log_or_file(self):
        """원본·URL·퍼센트·EUC-KR 키가 정상·오류 응답에 있어도 저장하지 않는다."""
        # 격자와 정상 경계 표식 특보에 원문·두 URL 방식·두 문자 인코딩을 주입한다.
        key = 'K+한%문'
        variants = (key.encode('utf-8'), key.encode('euc-kr'),
                    urllib.parse.quote(key, safe='').encode(),
                    urllib.parse.quote(key, safe='+').encode(),
                    urllib.parse.quote(key, safe='', encoding='euc-kr').encode(),
                    urllib.parse.quote(key, safe='+', encoding='euc-kr').encode(),
                    ''.join(f'%{part:02X}' for part in key.encode('utf-8')).encode(),
                    ''.join(f'%{part:02X}' for part in key.encode('euc-kr')).encode())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index, variant in enumerate(variants):
                warning = b'#START7777\n#' + variant + b'\n#7777END\n'
                record = store_response(root, f'{index}.txt.gz', warning,
                                        {'path': '/api/typ01/url/wrn_met_data.php', 'tmfc1': f'2015010{index}0000'},
                                        key=key)
                self.assertEqual((record['status'], record['n_valid']), ('error', KEY_IN_RESPONSE))
                self.assertFalse((root / f'{index}.txt.gz').exists())
                self.assertEqual(record['sha256_gz'], '')
            grid = store_response(root, 'PCP/2022011005/2022011006.txt.gz', b'bad ' + variants[3],
                                  {'vars': 'PCP', 'tmfc': '2022011005', 'tmef': '2022011006'}, key=key)
            append_manifest(root / 'manifest.csv', [grid])
            self.assertEqual((grid['status'], grid['n_valid']), ('error', KEY_IN_RESPONSE))
            self.assertFalse((root / 'PCP/2022011005/2022011006.txt.gz').exists())
            self.assertFalse((root / '_errors').exists())
            self.assertNotIn(key, (root / 'manifest.csv').read_text())

    def test_key_in_existing_parse_error_is_not_printed(self):
        """깨진 기존 격자의 원문 토큰은 출력하지 않고 정상 경로를 보존한다."""
        # 기존 파일에 키가 포함된 숫자 토큰을 두고 네트워크 없이 재개한다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = root / 'plan.csv'
            pd.DataFrame([{'tmfc': '2022011005', 'tmef': '2022011006', 'var': 'PCP'}]).to_csv(plan, index=False)
            cache = root / 'store/PCP/2022011005/2022011006.txt.gz'
            cache.parent.mkdir(parents=True)
            cache.write_bytes(gzip.compress(b'BAD_SECRET_TOKEN'))
            output = io.StringIO()
            with redirect_stdout(output):
                grid_fetch(str(plan), str(root / 'store'), None)
            self.assertNotIn('BAD_SECRET_TOKEN', output.getvalue())
            self.assertIn('2022011006.txt.gz', output.getvalue())
            self.assertEqual(gzip.decompress(cache.read_bytes()), b'BAD_SECRET_TOKEN')

    def test_fetch_discards_reflected_key_in_both_endpoints(self):
        """더하기 기호가 남은 키 표현을 두 수집 경로가 저장하지 않는다."""
        # 특보와 격자 응답에 safe='+' 방식으로 인코딩한 키를 넣는다.
        key = 'K+한%문'
        encoded = urllib.parse.quote(key, safe='+').encode('ascii')

        class Responses:
            """호출 경로에 따라 키가 반사된 응답을 반환한다."""

            def get(self, path, params):
                """인증키 표현을 포함한 바이트를 반환한다."""
                # 특보는 정상 경계 표식으로도 키 검사를 통과할 수 없게 한다.
                if path.endswith('wrn_met_data.php'):
                    return b'#START7777\n#' + encoded + b'\n#7777END\n'
                return b'<html>' + encoded + b'</html>'

        # 두 실행의 manifest 를 확인하고 저장소와 stdout 에 키가 없는지 검사한다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = root / 'plan.csv'
            pd.DataFrame([{'tmfc': '2022011005', 'tmef': '2022011006', 'var': 'PCP'}]).to_csv(plan, index=False)
            output = io.StringIO()
            with patch('src.forecast.collect_run.load_key', return_value=key), \
                 patch('src.forecast.collect_run.KMAClient', return_value=Responses()), \
                 patch('src.forecast.warnings_run.load_key', return_value=key), \
                 patch('src.forecast.warnings_run.KMAClient', return_value=Responses()), \
                 redirect_stdout(output):
                grid_fetch(str(plan), str(root / 'grid'), None)
                warnings_fetch('2015-01', '2015-01', str(root / 'warnings'))

            # 두 저장소에 manifest 만 남고 error 및 고정 설명 외 원문 정보가 없는지 확인한다.
            for store in (root / 'grid', root / 'warnings'):
                self.assertEqual(sorted(path.name for path in store.iterdir()), ['manifest.csv'])
                with (store / 'manifest.csv').open(newline='', encoding='utf-8') as source:
                    record = next(csv.DictReader(source))
                self.assertEqual((record['status'], record['n_valid']), ('error', KEY_IN_RESPONSE))
                self.assertEqual((record['sha256_gz'], record['bytes_raw']), ('', '0'))
                self.assertNotIn(encoded, (store / 'manifest.csv').read_bytes())
                self.assertNotIn(key.encode('utf-8'), (store / 'manifest.csv').read_bytes())
            self.assertNotIn(key, output.getvalue())
            self.assertNotIn(encoded.decode('ascii'), output.getvalue())


class WarningTests(unittest.TestCase):
    """제공된 특보 원문과 구역표의 필드 배치를 확인한다."""

    def test_parsers_and_changwon(self):
        """이력에 행이 있고 구역표의 창원 기본 코드가 선택된다."""
        # 2015년 월별 표본과 최신 구역표를 함께 읽는다.
        warnings = parse_warnings(fixture('wrn_met_data_201501.txt.gz'))
        zones = parse_zones(fixture('wrn_reg_latest.txt.gz'))
        self.assertGreater(len(warnings), 0)
        self.assertIn('TM_FC', warnings.columns)
        self.assertIn('T18', warnings.columns)
        self.assertEqual(zones.loc[zones.REG_ID.eq('L1080600'), 'REG_UP'].iloc[0], 'L1080000')
        selected = changwon_rows(warnings, zones)
        self.assertIn('L1080600', selected.attrs['reg_ids'])
        self.assertGreater(len(selected), 0)

    def test_variable_trailing_columns_preserve_required_fields(self):
        """31~38열 부가 필드는 허용하고 앞 11개 오류는 거부한다."""
        # 정상 표본의 앞 11개 필드로 길이가 다른 특보 행을 만든다.
        line = next(line for line in fixture('wrn_met_data_201501.txt.gz').decode('euc-kr').splitlines()
                    if line and not line.startswith('#'))
        required = [part.strip() for part in line.split(',')[:11]]
        for width in range(31, 39):
            with self.subTest(width=width):
                fields = required + [''] * (width - len(required))
                raw = ('#START7777\n' + ','.join(fields) + ',=\n#7777END\n').encode('euc-kr')
                self.assertEqual(response_status(raw, 'warning')[0], 'ok')
                parsed = parse_warnings(raw)
                self.assertEqual(len(parsed), 1)
                self.assertEqual(parsed.REG_ID.iloc[0], required[4])
                self.assertEqual(parsed.RPT.iloc[0], required[10])

        # 부가 필드가 없어도 앞 11개를 읽고 필수 필드의 결손·오류는 거부한다.
        self.assertEqual(len(parse_warnings(','.join(required).encode('euc-kr'))), 1)
        for label, fields in (('short', required[:10]), ('invalid', required[:4] + ['INVALID'] + required[5:])):
            with self.subTest(label=label):
                raw = ('#START7777\n' + ','.join(fields) + '\n#7777END\n').encode('euc-kr')
                with self.assertRaisesRegex(ValueError, '특보 행'):
                    response_status(raw, 'warning')

    def test_build_ignores_months_outside_requested_period(self):
        """build 는 2005년 7월부터의 요청 기간만 coverage 로 판정한다."""
        # 기간 밖 오류 월과 기간 안 정상 월을 임시 manifest 에 기록한다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = root / 'store'
            earlier = store_response(store, '200506.txt.gz', b'<html>error</html>',
                                     {'path': '/api/typ01/url/wrn_met_data.php', 'tmfc1': '200506010000'})
            active = store_response(store, '200507.txt.gz', fixture('wrn_met_data_201501.txt.gz'),
                                    {'path': '/api/typ01/url/wrn_met_data.php', 'tmfc1': '200507010000'})
            append_manifest(store / 'manifest.csv', [earlier, active])
            destination = run_build(str(store), str(root / 'out'), '2005-07', '2005-07')
            self.assertEqual(pd.read_csv(destination / 'coverage.csv').to_dict('records'),
                             [{'month': '2005-07', 'status': 'ok'}])
            self.assertEqual(json.loads((destination / 'manifest.json').read_text())['missing_months'], [])

        # CLI 의 기본 build 범위가 창원 특보구역 유효 기간과 맞는지 확인한다.
        with patch('sys.argv', ['warnings_run', 'build']), patch('src.forecast.warnings_run.run_build') as build:
            warnings_main()
        build.assert_called_once_with('data/raw/kma/warnings', 'artifacts/forecast/warnings',
                                      '2005-07', '2025-09', False)

    def test_monthly_resume_without_network(self):
        """이미 받은 월을 다시 요청하지 않고 manifest 누락을 복구한다."""
        # 제공 표본을 임시 저장소에 놓아 인증키를 읽지 않는 재개 경로를 확인한다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = FIXTURES / 'wrn_met_data_201501.txt.gz'
            (root / '201501.txt.gz').write_bytes(original.read_bytes())
            warnings_fetch('2015-01', '2015-01', str(root))
            self.assertEqual((root / '201501.txt.gz').read_bytes(), original.read_bytes())
            self.assertIn('201501.txt.gz', (root / 'manifest.csv').read_text(encoding='utf-8'))

    def test_build_rejects_missing_month_unless_allowed(self):
        """오류 월은 기본 build 를 막고 허용 시 coverage 와 목록에 남는다."""
        # 오류 월과 정상 월을 함께 가진 임시 manifest 를 만든다.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = root / 'store'
            ok = store_response(store, '201501.txt.gz', fixture('wrn_met_data_201501.txt.gz'),
                                {'path': '/api/typ01/url/wrn_met_data.php',
                                 'tmfc1': '201501010000', 'tmfc2': '201501312359'})
            bad = store_response(store, '201502.txt.gz', b'<html>error</html>',
                                 {'path': '/api/typ01/url/wrn_met_data.php',
                                  'tmfc1': '201502010000', 'tmfc2': '201502282359'})
            append_manifest(store / 'manifest.csv', [ok, bad])
            self.assertEqual(bad['status'], 'error')
            self.assertFalse((store / '201502.txt.gz').exists())
            with self.assertRaisesRegex(RuntimeError, '2015-02'):
                run_build(str(store), str(root / 'out'), '2015-01', '2015-02')
            self.assertFalse((root / 'out').exists())

            # 명시적 허용은 누락 월과 기간별 상태를 산출물에 기록한다.
            destination = run_build(str(store), str(root / 'out'), '2015-01', '2015-02', True)
            self.assertEqual(pd.read_csv(destination / 'coverage.csv').to_dict('records'),
                             [{'month': '2015-01', 'status': 'ok'}, {'month': '2015-02', 'status': 'error'}])
            self.assertEqual(pd.read_csv(destination / 'missing_months.csv')['month'].tolist(), ['2015-02'])
            self.assertEqual(json.loads((destination / 'manifest.json').read_text())['missing_months'], ['2015-02'])

    def test_invalid_warning_rows_fail_the_month(self):
        """잘못된 열과 필수 필드는 월 수집·coverage 를 오류로 만든다."""
        # 실제 표본의 첫 자료 행에 반례 E 와 각 필드 형식 오류를 만든다.
        lines = fixture('wrn_met_data_201501.txt.gz').decode('euc-kr').splitlines()
        position = next(index for index, line in enumerate(lines) if line and not line.startswith('#'))
        originals = [part.strip() for part in lines[position].split(',')]
        cases = [('columns', None, 'malformed,row'), ('TM_FC', 0, '201513010000'),
                 ('TM_EF', 1, ''), ('REG_ID', 4, 'INVALID'), ('WRN', 5, ''),
                 ('LVL', 6, 'X'), ('CMD', 7, '9')]
        for label, column, replacement in cases:
            with self.subTest(label=label):
                changed = lines.copy()
                fields = originals.copy()
                if column is not None:
                    fields[column] = replacement
                changed[position] = ','.join(fields) if column is not None else replacement
                raw = ('\n'.join(changed) + '\n').encode('euc-kr')
                with self.assertRaisesRegex(ValueError, '특보 행'):
                    response_status(raw, 'warning')

        # 한 행이 깨진 월은 정상 경로 없이 오류 원문과 error coverage 를 남긴다.
        class Responses:
            """깨진 특보 월 한 건을 반환한다."""

            def get(self, path, params):
                """요청마다 깨진 응답을 반환한다."""
                # 응답 경계는 정상이고 첫 자료 행만 잘못됐다.
                return bad_raw

        # 깨진 월 응답을 구성해 수집하고 누락 허용 시 coverage 오류를 확인한다.
        bad_lines = lines.copy()
        bad_lines[position] = 'malformed,row'
        bad_raw = ('\n'.join(bad_lines) + '\n').encode('euc-kr')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch('src.forecast.warnings_run.load_key', return_value='FAKE'), \
                 patch('src.forecast.warnings_run.KMAClient', return_value=Responses()):
                warnings_fetch('2015-01', '2015-01', str(root / 'store'))
            self.assertFalse((root / 'store/201501.txt.gz').exists())
            with (root / 'store/manifest.csv').open(newline='', encoding='utf-8') as source:
                self.assertEqual(list(csv.DictReader(source))[0]['status'], 'error')
            destination = run_build(str(root / 'store'), str(root / 'out'), '2015-01', '2015-01', True)
            self.assertEqual(pd.read_csv(destination / 'coverage.csv').iloc[0].to_dict(),
                             {'month': '2015-01', 'status': 'error'})


if __name__ == '__main__':
    unittest.main()
