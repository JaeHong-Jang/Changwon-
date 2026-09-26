# M6 절차 — 재현성 정리, 클라우드 항목 (계산 전 고정)

> 과제 정의: `docs/CLOUD_TASKS.md` M6. 규칙: `AGENTS.md` §2·§6·§8.
> 이 문서는 **비교 기준·판정 규칙·목록 규칙을 재실행 전에 고정**하려고 커밋한다.
> 이 커밋 전에는 이 세션에서 `src.models.holdout_eval` 과 `src.models.label_audit` 를 실행하지 않았다.

## 0. 범위

| 항목 | 이 세션 (클라우드) | 로컬 |
|---|---|---|
| A. 공식 홀드아웃 재실행 (`-dirty` 없이), 9/24 수치와 비교 | 한다 (가공 스냅샷 사용) | — |
| B. run_id 정정 (`PAPER_ROADMAP.md`, 같은 오류가 있는 `METHODOLOGY.md`) | 한다 | — |
| C. 동결 연대표 (P0-8) | 한다 | 로컬 전용 기록(`.omc/`)으로 보강 |
| D. Zenodo 기탁 목록 | cloud-base 에 있는 파일만 | LFS 전용 원본(SGIS·토지피복·침수예상도·KMA) 추가 |
| 파이프라인으로 `data/processed` 재생성, `SHA256SUMS` 비교 | **하지 않는다** | 한다 |

## 1. 사전 확인 (결과를 보지 않는 사실, 이 문서 작성 전에 확인)

- `bash scripts/cloud_setup.sh` 통과: `artifacts/processed_snapshot/SHA256SUMS` 4개 파일 해시 일치, 동결 모델을 `.omc/benchmark` 로 복원.
- 원본 흔적 47개 파일(개발 9·홀드아웃 38)의 SHA256 이 9/24 run `…100939Z…cf388a23` 의 `raw_sha256` 과 모두 같다.
- 코드: 9/24 최신 run `…104608Z…4af97d5d` 의 `code_sha256` 21개 중 `src/models/provenance.py` 하나만 현재와 다르다.
  따라서 새 run_id 의 끝 8자리(코드 해시)는 `4af97d5d` 와 다를 것이다.
- 가공 자료: `grid_features.parquet` 해시는 9/24 run 과 같다(`092545b6…`). `layer1_flood.gpkg` 는 다르다
  (9/24 `3f5fb14e…`, 스냅샷 `0a731462…`). 스냅샷 파일의 `gpkg_contents.last_change` 는 `2026-09-24T16:18:26Z` 로,
  9/24 홀드아웃 run(09:38~10:46Z) 뒤에 파이프라인이 다시 쓴 파일이다. 바이트 차이의 원인이 내용인지 기록 시각인지는
  9/24 파일이 cloud-base 에 없어 여기서 판정할 수 없다 (로컬 해시 비교 과제).
- 패키지: 9/24 는 Python 3.14.4·numpy 2.5.2·pandas 3.0.5, 이 세션은 Python 3.12.3·numpy 2.5.3·pandas 3.0.6.
  geopandas·pyogrio·shapely·scipy·sklearn·xgboost 는 같은 판이다.
- 9/24 run 두 개(`…cf388a23`, `…4af97d5d`)는 `metrics.csv` 5,670행이 최대 절대차 0 으로 같고, 게이트 해시도 같다.

## 2. A — 공식 홀드아웃 재실행

### 2.1 실행

- 명령: `PYTHONPATH=. .venv/bin/python -m src.models.holdout_eval` (클라우드 리더 세션만. 서브 에이전트는 실행하지 않는다).
- 실행 직전 `git status --porcelain -- src config` 가 비어 있어야 한다. 비어 있지 않으면 실행하지 않고 먼저 커밋한다.
- 산출 위치는 코드가 정한 `artifacts/evaluation/holdout_2022_2024/<run_id>/` 와 `latest.json` 이다 (코드를 바꾸지 않는다).
  비교 결과는 `artifacts/q1/M6/<m6_run_id>/` 에 둔다.
- 한 번만 실행한다. 실패(예외)하면 원인을 고친 뒤 다시 실행하고, 실패한 시도도 보고서에 적는다.

### 2.2 기준

- 주 기준: `holdout_20260924T100939Z_ae9c122-dirty_cf388a23` (문서 인용, `config/holdout_reference.yaml`).
- 보조 기준: `holdout_20260924T104608Z_ae9c122-dirty_4af97d5d` (9/24 `latest.json`).

### 2.3 판정 규칙 (고정)

| 규칙 | 내용 | 통과 조건 |
|---|---|---|
| J1 게이트 해시 | H10 과 같은 규칙. `canonical_hash(summary["gates"])`, `canonical_hash(summary["development_gates"])` | 두 해시가 `config/holdout_reference.yaml` 값과 같다 |
| J2 지표표 | `metrics.csv` 를 키 (`score`, `unit`, `stratum`, `storm`, `metric`, `polygon_subset`) 로 맞춘다 | 키 집합이 같고, `value`·`ci_lo`·`ci_hi` 최대 절대차 0, `n_units`·`n_polygons`·`score_role`·`post_hoc_design`·`confirmatory` 가 같다 |
| J3 실행 메타 | `holdout`, `polygons_by_storm`, `polygons_by_subset`, `n_background_cells`, `raw_sha256`, `score_roles`, `gate_definition`, `models` (모델·prespec 해시, prespec run_id, selection) | 모두 같다 |
| 기록만 | `run_id`, `started_utc`, `git_head`, `source_dirty`, `versions`, `code_sha256`, `processed_sha256`, `note`, `command` | 차이를 표로 적고 원인을 단다. 판정에 쓰지 않는다 |

- **재현:** J1·J2·J3 모두 통과.
- **부동소수 차이:** J1·J3 통과, J2 의 최대 절대차가 0 보다 크고 1e-9 이하. 재현으로 보지 않고 따로 보고한다.
- **불일치:** 그 밖의 모든 경우.
- 결과가 무엇이든 코드·설정·입력을 바꿔 맞추지 않는다 (§2 재튜닝 금지와 같은 취지). 차이가 있으면 차이 행과 원인 후보를 보고한다.

### 2.4 판정에 따른 문서 처리 (고정)

- 재현이면: `PAPER_ROADMAP.md` §2 와 `METHODOLOGY.md` §7.6 의 출처에 새 run_id 를 **공식 재실행**으로 추가한다.
  9/24 run 은 **최초 공식 채점(코드 미커밋 상태)**으로 남긴다. 수치는 바꾸지 않는다.
  `config/holdout_reference.yaml` 은 해시 값을 그대로 두고 `run_id` 만 새 run 으로 바꾸며, 주석에 9/24 run_id 를 남긴다.
- 재현이 아니면: 인용은 9/24 run 으로 두고, 두 문서에 차이와 새 run_id 를 병기한다. `holdout_reference.yaml` 은 바꾸지 않는다.

## 3. B — run_id 정정

1. 인용 수치 대조: `PAPER_ROADMAP.md` §2 라벨 감사 표의 6개 값(개발 95.2%·8,750 m², 홀드아웃 66.3%·12.3%·97.5%·3,590 m²)과
   `METHODOLOGY.md` 같은 문단의 값을 `artifacts/evaluation/label_audit/*_summary.json` 과 대조한다.
   같으면 run_id 만 저장 파일의 것으로 바꾼다. 다르면 run_id 를 바꾸지 않고 차이를 보고한다.
2. 재실행 확인: `src.models.label_audit.run` 을 산출 폴더만 `artifacts/q1/M6/<m6_run_id>/label_audit/` 로 바꿔
   `development`·`holdout` 두 역할로 실행한다 (저장본을 덮어쓰지 않는다). 요약 JSON 은 `run_id` 를 뺀 값이 저장본과 같아야 하고,
   폴리곤 표는 정수·문자·논리 열이 같고 실수 열 최대 절대차가 1e-6 이하여야 한다.
3. `40523c56` 은 저장된 적이 있는 산출물로 확인할 수 없다. 코드 해시 접두어이므로 `label_audit.py` 의 이전 판본이며,
   같은 경로를 쓰는 뒤 실행이 산출을 덮어썼다고 **추정**한다. 보고서에서 추정으로 표기한다.

## 4. C — 동결 연대표 (P0-8)

- 사건 분류: **동결**(지수 산식·가중·게이트 고정), **입수**(흔적 자료 수령·반입), **최초 채점**(홀드아웃을 처음 읽거나 채점),
  **설계 변경**(홀드아웃 노출 뒤의 모델·특징·평가 설계 변경), **재실행·검증**.
- 시각 출처 우선순위:
  1. 실행 기록 안의 기계 시각: `started_utc`, `created_at_utc`, `frozen_at_utc`, `created_utc`, run_id 에 박힌 UTC, `gpkg_contents.last_change`.
  2. git 커밋 작성 시각 (`origin/develop`, `origin/cloud/*`, `cloud-base`). 커밋 시각은 그 내용이 **그때까지는 존재했다**는 상한이다.
  3. 문서에 적힌 날짜 (`data/raw/README.md`, `docs/data_access_log.md` 등). 날짜 정밀도.
  4. 날짜 없는 서술은 **미기록**으로 두고, 앞뒤 사건으로 구간만 적는다.
- 모든 시각을 UTC 와 KST 로 함께 적는다. 정밀도(초·일·상한·하한·미기록)를 행마다 표기한다.
- 1·2 순위 출처는 실행 모듈이 파일·커밋에서 직접 읽어 `chronology.csv` 로 만든다. 사람이 옮겨 적은 시각은 쓰지 않는다.
  3 순위는 인용 문장이 그 파일에 있는지 모듈이 확인한다.
- 사건 목록(출처 위치)은 `config/m6_chronology.yaml` 에 적는다. 목록은 증거 조사 뒤 정하지만 시각은 모듈이 읽는다.

## 5. D — Zenodo 기탁 목록

- 대상: 이 커밋 트리의 git 추적 파일 전부 (`git ls-files`). 파일마다 경로·바이트·SHA256·분류·처리·근거를 적는다.
- 처리 값: `open` (공개 기탁), `restricted` (Zenodo 제한 접근 후보), `hash_only` (올리지 않고 해시·출처만 적음), `exclude` (기탁하지 않음).
- 분류 규칙 (위에서부터 먼저 맞는 규칙 하나):

| 순서 | 경로 | 분류 | 처리 | 근거 |
|---|---|---|---|---|
| 1 | `data/raw/README.md`, `data/raw/open_data_manifest.json`, `data/*/README.md` | docs | open | 프로젝트가 쓴 설명·목록 |
| 2 | `data/raw/rivers/osm_waterways.gpkg` | raw_open | open | ODbL (`docs/data_access_log.md` #19, `data/raw/README.md`) — 출처 표시·동일 조건 |
| 3 | `data/raw/flood_traces/changwon_info_disclosure_*/**` | raw_restricted | hash_only | 창원시 정보공개 제공. 재배포 허락 미확인 (`PAPER_ROADMAP.md` §7) |
| 4 | `data/raw/flood_traces/safetydata_*/**` | raw_restricted | hash_only | 재난안전데이터공유플랫폼 이용 조건 미확인 |
| 5 | 그 밖의 `data/raw/**`, `data/external/**` | raw_third_party | hash_only | 제3자 자료, 저장소에 이용 조건 기록 없음 |
| 6 | `artifacts/processed_snapshot/**` | derived_data | restricted | 격자 인구(SGIS)·흔적 라벨을 담은 파생 자료. 원본 조건 확인 전 제한 |
| 7 | `artifacts/frozen/**` | frozen_models | open | 동결 모델·사전 명세 |
| 8 | `artifacts/**`, `reports/**` | results | open | 점수·지표·요약 (도형 없음 또는 격자 파생 지표) |
| 9 | `docs/**` | docs | open | 절차·보고·연구 문서 |
| 10 | `.fablize/**` | internal | exclude | 하네스 내부 진행 기록 |
| 11 | 그 밖 (`src`, `tests`, `config`, `scripts`, `app`, `notebooks`, 루트 파일) | code | open | 코드·설정 |

- 이 규칙은 기탁 **후보** 목록이다. 라이선스 선택과 제3자 자료 공개 여부는 사용자가 정한다. 저장소에 라이선스 파일이 있는지도 목록에 적는다.

## 6. 산출

- `artifacts/evaluation/holdout_2022_2024/<새 run_id>/` (코드가 쓰는 위치) 와 `latest.json`.
- `artifacts/q1/M6/<m6_run_id>/`: `holdout_compare.json`, `metrics_diff.csv`(차이 행만, 없으면 머리글만),
  `label_audit/`(재실행 산출), `label_audit_compare.json`, `chronology.csv`, `zenodo_manifest.csv`, `zenodo_summary.json`, `summary.json`.
- 문서: `docs/q1/M6.md` (§4 형식 보고), `docs/q1/M6_chronology.md`, `docs/q1/M6_zenodo.md`, `docs/q1/M6_review.md` (교차 리뷰).

## 7. 표현

- 재실행은 **같은 코드·같은 입력으로 같은 수치가 나오는지**만 확인한다. 새 설계가 아니며 새 채점도 아니다 (post-hoc 아님).
  다만 채점 대상 점수 가운데 post-hoc 점수의 지위는 9/24 와 같다.
- `docs/CLOUD_TASKS.md` 의 금지 표현(전향적·사전등록 검증 등)을 쓰지 않는다.
