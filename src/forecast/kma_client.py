"""기상청 API 호출과 키가 없는 원본 응답 기록을 맡는다."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.forecast.kma_grid import parse_grid
from src.forecast.warnings import parse_warnings


BASE_URL = 'https://apihub.kma.go.kr'
MANIFEST_FIELDS = ('path', 'tmfc', 'tmef', 'var', 'url_without_key', 'sha256_gz',
                   'bytes_raw', 'retrieved_utc', 'status', 'n_valid')
KEY_IN_RESPONSE = '응답에 인증키 포함 — 원문 폐기'


def load_key(env_path: str | Path = '.env') -> str:
    """환경변수 또는 로컬 환경 파일에서 인증키를 조용히 읽는다."""
    # 환경변수 우선순위를 적용하고 값의 존재만 검증한다.
    key = os.environ.get('KMA_APIHUB_KEY')
    if key:
        return key

    # 로컬 환경 파일에서 같은 이름의 한 줄만 읽고 키를 출력하지 않는다.
    try:
        lines = Path(env_path).read_text(encoding='utf-8').splitlines()
    except OSError:
        lines = []
    for line in lines:
        if line.strip().startswith('KMA_APIHUB_KEY='):
            key = line.split('=', 1)[1].strip().strip('"\'')
            if key:
                return key
    raise RuntimeError('KMA_APIHUB_KEY 가 설정되지 않았습니다')


def sanitize(value: object, key: str) -> str:
    """오류 문자열에서 원본 키와 바이트·URL 표현을 가린다."""
    # 원본과 두 문자 인코딩의 퍼센트 표기 및 바이트 표기를 치환한다.
    result = str(value)
    if not key:
        return result
    forms = {key, urllib.parse.quote(key, safe=''), urllib.parse.quote_plus(key)}
    for encoding in ('utf-8', 'euc-kr'):
        try:
            encoded = key.encode(encoding)
        except UnicodeError:
            continue
        forms.update((urllib.parse.quote_from_bytes(encoded, safe=''),
                      ''.join(f'%{byte:02X}' for byte in encoded), repr(encoded)[2:-1]))
    for secret in sorted(forms, key=len, reverse=True):
        result = result.replace(secret, '***').replace(secret.lower(), '***')
    return result


def contains_key(raw: bytes, key: str) -> bool:
    """응답 바이트와 중첩 퍼센트 인코딩에서 인증키를 찾는다."""
    # 키가 없으면 검사할 표현이 없고, 있으면 UTF-8·EUC-KR 바이트와 URL 표기를 준비한다.
    if not key:
        return False
    candidates = set()
    for encoding in ('utf-8', 'euc-kr'):
        try:
            encoded = key.encode(encoding)
        except UnicodeError:
            continue
        candidates.update((encoded, repr(encoded).encode('ascii'),
                           ''.join(f'%{byte:02X}' for byte in encoded).encode('ascii')))
        candidates.update(urllib.parse.quote_from_bytes(encoded, safe=safe).encode('ascii')
                          for safe in ('', '+'))

    # 일반 퍼센트 디코딩과 폼 디코딩의 모든 경로를 별도로 따라가며 중첩 표현을 검사한다.
    pending = {raw}
    seen = {raw}
    for _ in range(5):
        if any(candidate in content for content in pending for candidate in candidates):
            return True
        decoded = {result for content in pending for result in
                   (urllib.parse.unquote_to_bytes(content),
                    urllib.parse.unquote_to_bytes(content.replace(b'+', b' ')))}
        pending = decoded - seen
        if not pending:
            break
        seen.update(pending)
    return False


def url_without_key(path: str, params: dict[str, object]) -> str:
    """인증키 매개변수를 제외한 요청 URL 을 만든다."""
    # manifest 와 오류 행에는 요청 조건만 남긴다.
    safe = {name: value for name, value in params.items() if name.lower() != 'authkey'}
    return urllib.parse.urljoin(BASE_URL, path) + '?' + urllib.parse.urlencode(safe)


def response_status(raw: bytes, var: str) -> tuple[str, int | None]:
    """격자 크기 또는 특보 경계 표식을 검사해 응답 상태를 반환한다."""
    # API 오류 본문은 파서가 정상 자료로 해석하기 전에 거른다.
    if var == 'warning':
        if not raw.startswith(b'#START7777') or b'#7777END' not in raw:
            raise ValueError('특보 응답 경계 표식이 없습니다')
        parse_warnings(raw)
        return 'ok', None
    if var in {'R12', 'R06', 'PCP', 'POP', 'TMP'}:
        grid = parse_grid(raw)
        n_valid = int(np.isfinite(grid).sum())
        return ('ok' if n_valid else 'all_missing'), n_valid
    raise ValueError(f'알 수 없는 응답 변수: {var}')


def _write_gzip(target: Path, raw: bytes) -> bytes:
    """원문을 결정적 gzip 으로 같은 폴더에서 원자 저장한다."""
    # 임시파일을 완전히 기록한 뒤 확정 경로로 교체한다.
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, filename='') as output:
        output.write(raw)
    compressed = buffer.getvalue()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.kma-', delete=False) as output:
            temporary = Path(output.name)
            output.write(compressed)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return compressed


class KMAClient:
    """주입 가능한 opener 로 API 를 호출하고 일시 오류를 재시도한다."""

    def __init__(self, key: str, *, opener=None, retries: int = 4,
                 backoff_s: float = 5, pause_s: float = 0.2):
        """키와 요청 간격 및 재시도 정책을 저장한다."""
        # 테스트에서는 가짜 opener 를 받으며 기본값은 urllib 를 쓴다.
        self.key = key
        self.opener = opener or urllib.request.urlopen
        self.retries = retries
        self.backoff_s = backoff_s
        self.pause_s = pause_s

    def get(self, path: str, params: dict[str, object]) -> bytes:
        """5xx 와 시간초과를 재시도하고 인증키 없는 오류를 낸다."""
        # URL 을 만든 뒤 각 시도 전에 호출 간격을 지킨다.
        query = urllib.parse.urlencode({**params, 'authKey': self.key})
        url = urllib.parse.urljoin(BASE_URL, path) + '?' + query
        for attempt in range(self.retries + 1):
            if self.pause_s:
                time.sleep(self.pause_s)
            try:
                response = self.opener.open(url, timeout=30) if hasattr(self.opener, 'open') else self.opener(url, timeout=30)
                with response:
                    return response.read()
            except urllib.error.HTTPError as error:
                # urllib 의 응답 핸들을 닫아 예외 정리 중 URL 이 출력되지 않게 한다.
                error.close()
                if error.code < 500 or attempt == self.retries:
                    raise RuntimeError(sanitize(f'KMA HTTP {error.code}', self.key)) from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.retries:
                    raise RuntimeError(sanitize('KMA 요청 실패', self.key)) from None
            except Exception:
                raise RuntimeError(sanitize('KMA 요청 실패', self.key)) from None
            if self.backoff_s:
                time.sleep(self.backoff_s * 2 ** attempt)
        raise RuntimeError('KMA 요청 실패')


def store_response(root: str | Path, relative_path: str | Path, raw: bytes,
                   request_params: dict[str, object], key: str | None = None) -> dict[str, object]:
    """검증한 응답만 정상 경로에 저장하고 오류 원문은 분리한다."""
    # 저장 경로를 루트 안으로 제한하고 기존 응답은 그대로 재사용한다.
    root = Path(root)
    relative = Path(relative_path)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('상대 저장 경로가 잘못되었습니다')
    target = root / relative
    if target.exists():
        with gzip.open(target, 'rb') as source:
            raw = source.read()
        compressed = target.read_bytes()

    # 인증키를 제외한 요청 조건으로 변수와 manifest 주소를 만든다.
    safe_params = {key: value for key, value in request_params.items() if key.lower() != 'authkey'}
    path = str(safe_params.pop('path', '/api/typ01/cgi-bin/url/nph-dfs_shrt_grd'))
    url = url_without_key(path, safe_params)
    var = str(safe_params.get('vars', safe_params.get('var', '')))
    if path.endswith('/wrn_met_data.php'):
        var = 'warning'
    # 키가 포함된 응답은 상태와 고정 설명만 기록하고 원문은 폐기한다.
    secret = key if key is not None else str(request_params.get('authKey', ''))
    key_exposed = contains_key(raw, secret)
    if key_exposed:
        if target.exists():
            raise ValueError(KEY_IN_RESPONSE)
        status, n_valid = 'error', KEY_IN_RESPONSE
        compressed = b''
    else:
        try:
            status, n_valid = response_status(raw, var)
        except (ValueError, UnicodeError):
            if target.exists():
                raise ValueError('기존 응답 검증 실패') from None
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            relative = Path('_errors') / var / str(safe_params.get('tmfc', safe_params.get('tmfc1', ''))) / f"{safe_params.get('tmef', safe_params.get('tmfc2', ''))}.{stamp}.txt.gz"
            status, n_valid = 'error', None
            compressed = _write_gzip(root / relative, raw)
        else:
            if not target.exists():
                compressed = _write_gzip(target, raw)
    return {'path': relative.as_posix(), 'tmfc': safe_params.get('tmfc', safe_params.get('tmfc1', '')),
            'tmef': safe_params.get('tmef', safe_params.get('tmfc2', '')), 'var': var, 'url_without_key': url,
            'sha256_gz': '' if key_exposed else hashlib.sha256(compressed).hexdigest(),
            'bytes_raw': 0 if key_exposed else len(raw),
            'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'status': status, 'n_valid': n_valid}


def append_manifest(csv_path: str | Path, rows: list[dict[str, object]]) -> None:
    """단일 프로세스 CSV manifest 에 헤더와 새 행을 추가한다."""
    # 빈 목록은 파일을 만들지 않고, 첫 저장 때만 헤더를 기록한다.
    if not rows:
        return
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.exists() or path.stat().st_size == 0
    with path.open('a', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=MANIFEST_FIELDS, extrasaction='ignore')
        if first:
            writer.writeheader()
        writer.writerows(rows)
