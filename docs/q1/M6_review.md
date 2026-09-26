# M6 독립 검토 (읽기 전용)

판정: **PASS-with-fixes**

> 검토자: Claude 서브 에이전트 (구현과 다른 모델, AGENTS.md §1·§8). 홀드아웃 원본
> (`data/raw/flood_traces/changwon_info_disclosure_20260924/`)은 열거나 해시하지 않았다.
> `holdout_eval`·`label_audit`·`m6_run` 의 compare·audit·zenodo 단계도 실행하지 않았다.
> 실행한 것은 단위 검사, `m6_run --steps chronology`(임시 폴더, 검토 뒤 삭제), 저장된 파생 산출(JSON·CSV) 재계산뿐이다.
> 아래는 검토 보고를 옮긴 것이고, 마지막 절은 리더의 조치다.

## 확인한 것

1. **순서·커밋 상태.** 절차 `b834248`(16:42:40Z) → 모듈 `7f7968f`(16:47:59Z) → 재실행 `started_utc` 16:48:05Z 순서다.
   재실행의 `git_head` 는 `7f7968f`, `source_dirty` 는 false 다. `git diff b834248..7f7968f -- src config` 는 `src/repro/*`·`tests/test_m6.py` 추가뿐이다.
   `holdout_eval` 이 쓰는 코드는 바뀌지 않았다.
2. **J1.** 새 실행의 `canonical_hash(gates)` = `48d83b93…`, `canonical_hash(development_gates)` = `2ea2f057…` 다.
   `config/holdout_reference.yaml` 과 같다. H10 과 같은 함수·키다.
3. **J2 (독립 재계산).** 5,670 = 5,670행이고 한쪽에만 있는 키는 0 이다. 차이 1,966행(area 1,163 / object 803)이다.
   최대 절대차는 value 1.82e-12, ci_lo 1.37e-12, ci_hi 8.46e-13 이다. `cell_gate` 1,566행과 `cluster_gate` 306행의 최대차는 0.0 이다.
4. **J3.** `holdout.union_area_km2`(Δ 2.0e-13)만 다르고 나머지 판정 키는 같다. `verdict()` 결과 `mismatch` 가 절차 §2.3 과 맞다.
5. **게이트 표.** 10개 점수 모두 새 실행과 9/24 인용 실행이 소수 4자리까지 같다.
6. **라벨 감사.** 인용 값 10개가 저장 요약과 같다. 폴리곤 표의 `object_id` 불일치 행(개발 9, 홀드아웃 47)은 `area_m2` 차이 행과 정확히 같다.
   개발 9행은 모두 2025-07-19 사상이다. 저장본 `artifacts/evaluation/label_audit/*` 은 바뀌지 않았다(`git diff` 비어 있음).
7. **연대표.** `git fetch origin develop cloud/M1` 뒤 chronology 단계를 임시 폴더로 다시 돌렸다. 저장 `chronology.csv` 와 완전히 같았다.
   커밋 16개의 시각·인용을 `git show -s --format='%aI %s'` 로 대조했고 모두 맞았다. "10분 22초"·"16일 전"·RF-F0 0.8761 도 확인했다.
   `SENSITIVITY_SPEC`·`EXPOSURE_SPEC` 는 `85fc544`·`254162b`·`140a433`·`4647f47`·`ae9c122` 에서 AST 로 같다.
8. **Zenodo.** `classify()` 를 453행 전부에 다시 적용했고 불일치는 0 이다. `M6_zenodo.md` §1 합계는 `zenodo_summary.json` 과 같다.
   홀드아웃·API 흔적은 hash_only 다.
9. **단위 검사·§6·표현.** `tests.test_m6` 12개, 전체 370개(2 skip)가 통과한다. `src/repro/*.py` docstring 은 한 줄이고 문단마다 주석이 있다.
   금지 표현은 없다. `config/holdout_reference.yaml` 은 바뀌지 않았다(절차 §2.4). 변경 파일 범위는 `M6.md` 표와 같다.

## 지적

| # | 심각도 | 위치 | 내용 | 제안 |
|---|---|---|---|---|
| 1 | 중간 | `src/repro/run_compare.py` `_same()`·`compare_metrics()` | 바깥 병합에서 한쪽에만 있는 키가 생기면 정수 열(`n_units`, `n_polygons`)이 float 로 올라간다. 그 뒤 문자열 비교에서 `"1267"` ≠ `"1267.0"` 이 되어 같은 값도 불일치로 센다. 이번 비교는 한쪽에만 있는 키가 0 이라 영향이 없다 | 숫자는 값으로, 결측을 고려해 비교 |
| 2 | 낮음 | `src/repro/m6_run.py` `step_audit` | `label_audit.OUTPUT` 전역을 바꾼 뒤 되돌리지 않는다 | 끝나면 원래 값 복원 |
| 3 | 낮음 | `config/m6_chronology.yaml` V7·V9 | 둘 다 절차 고정 커밋인데 분류가 다르다(설계 변경 / 재실행·검증) | 분류 통일 또는 이유 명시 |

## 한계 (검토자)

- `src/models/label_audit.py` 자체 논리는 M6 범위 밖이라 보지 않았다(변경 없음만 확인).
- 재투영 원인은 홀드아웃 원본을 열어야 확인할 수 있어 확인하지 않았다. 확인한 것은 과정의 정합성까지다
  (`object_id`·면적 변화 행 일치, 해당 사상의 좌표계). 보고서의 "추정" 표현이 맞다.
- 453개 파일 SHA256 을 모두 다시 해시하지는 않았다(분류 재적용과 합계 재계산으로 대신).
- 로컬 전용 기록(`.omc/review/RV1.md` 등)은 클라우드에 없어 보지 못했다.

## 리더 조치 (커밋 `fix(q1/M6): 교차 리뷰 반영`)

1. **지적 1 수정.** `run_compare.same_values()` 로 바꿨다. 결측끼리는 같다고 본다. 논리형이 아닌 숫자 열은 dtype 과 상관없이 실수 값으로 비교한다.
   나머지 열은 `eq` 로 비교한다. `audit_check.compare_polygon_tables` 도 같은 함수를 쓴다(정수 열 업캐스트에서 같은 문제가 있었다).
   단위 검사에 업캐스트 사례 3개를 더했다. 수정한 코드로 compare 단계를 다시 돌렸고 `holdout_compare.json`·`metrics_diff.csv` 는 바이트까지 같았다.
   라벨 감사 비교는 저장된 재실행 CSV 에 새 함수를 적용해 `label_audit_compare.json` 의 폴리곤 결과와 같음을 확인했다.
   홀드아웃을 다시 읽는 audit 단계는 다시 돌리지 않았다.
2. **지적 2 수정.** `try/finally` 로 `label_audit.OUTPUT` 을 되돌린다.
3. **지적 3 — 분류는 유지하고 이유를 적었다.** M1 은 홀드아웃을 채점하는 새 post-hoc 설계라 설계 변경이다.
   M6 은 기존 채점을 같은 코드로 다시 돌리는 재실행이다. 두 행의 `note` 에 이 이유를 넣고 chronology 단계를 다시 돌렸다.
   `chronology.csv` 는 두 행의 note 열만 바뀌었다.
- 전체 단위 검사는 수정 뒤에도 370개 통과(2 skip)다.
- 리뷰 뒤 Zenodo 목록을 최종 파일 구성으로 다시 만들었다. 453 → 458개가 됐고, 늘어난 5개는 M6 문서 3개와 목록 산출 2개다.
  분류 규칙은 바꾸지 않았다. `M6_zenodo.md` §1 합계를 새 `zenodo_summary.json` 에 맞췄다.
