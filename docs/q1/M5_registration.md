# M5 등록 기록 — 절차 고정 해시

> 대상: `docs/q1/M5_protocol.md` (M5 단계 A, 다른 도시 자료를 보기 전에 고정).
> 아래 해시는 **절차 커밋 다음 커밋**에서 채웠다 (절차 파일이 자기 커밋 해시를 담을 수 없어서다). 틀은 초안 커밋 `365bcc2` 에서 만들었다.

## 고정한 절차

| 항목 | 값 |
|---|---|
| 파일 | `docs/q1/M5_protocol.md` |
| 절차 커밋 | `f80f73629d588d68d87eff187679f53cde2115da` (`2026-09-26 16:57:20 +0000`) |
| 브랜치 | `cloud/M5A` (origin 에 푸시) |
| 파일 SHA256 | `68818ca765939c005580e80f8b5fdae2f016fe9aa6387722343edc32f784385d` |
| git blob | `cf6d59c3bae24c447e56c51061b5df13978afeef` |

확인 명령 (누구나 같은 값이 나와야 한다):

```bash
git show f80f736:docs/q1/M5_protocol.md | sha256sum    # → 68818ca765939c005580e80f8b5fdae2f016fe9aa6387722343edc32f784385d
git rev-parse f80f736:docs/q1/M5_protocol.md            # → cf6d59c3bae24c447e56c51061b5df13978afeef
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
