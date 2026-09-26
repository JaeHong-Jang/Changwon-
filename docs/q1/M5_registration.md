# M5 등록 기록 — 절차 고정 해시

> 대상: `docs/q1/M5_protocol.md` (M5 단계 A, 다른 도시 자료를 보기 전에 고정).
> 이 파일은 절차 문서의 커밋 해시를 적으려고 **절차 커밋 다음 커밋**에서 만든다 (파일이 자기 커밋 해시를 담을 수 없어서다).

## 고정한 절차

| 항목 | 값 |
|---|---|
| 파일 | `docs/q1/M5_protocol.md` |
| 절차 커밋 | `@@COMMIT@@` (`@@COMMIT_DATE@@`) |
| 브랜치 | `cloud/M5A` (origin 에 푸시) |
| 파일 SHA256 | `@@SHA256@@` |
| git blob | `@@BLOB@@` |

확인 명령 (누구나 같은 값이 나와야 한다):

```bash
git show @@COMMIT_SHORT@@:docs/q1/M5_protocol.md | sha256sum    # → @@SHA256@@
git rev-parse @@COMMIT_SHORT@@:docs/q1/M5_protocol.md            # → @@BLOB@@
```

## 외부 등록 (사용자가 채운다)

| 항목 | 값 |
|---|---|
| 등록처 | OSF / Zenodo (택1 또는 둘 다) |
| 등록 ID·DOI | _미기입_ |
| 등록 URL | _미기입_ |
| 등록 시각 (UTC) | _미기입_ |
| 등록 파일의 SHA256 이 위 값과 같은가 | _미기입_ |

## 단계 B 시작 조건

- 위 외부 등록 표가 채워진 뒤에 B1(도시 선정)을 시작한다 (`M5_protocol.md` §9).
- 등록 뒤 절차를 바꾸면 `docs/q1/M5_deviations.md` 에 기록한다 (`M5_protocol.md` §10).
