# AGENTS.md — 창원 CDRI 프로젝트 에이전트 작업 규칙

> Codex·Claude 등 이 저장소에서 일하는 모든 에이전트가 따른다.
> 사람용 안내는 `README.md`·`CONTRIBUTING.md`, 방법론은 `docs/METHODOLOGY.md`.

## 1. 팀 구조

| 역할 | 담당 | 하는 일 |
|---|---|---|
| 리더 (오케스트레이터) | Claude Opus 5.5 (Claude Code) | 과제 분해·배정, 결과 통합, 검증, 커밋, 최종 판정. 사용자와의 유일한 창구. **분석·기능 코드는 직접 구현하지 않는다** (규칙 문서·설정·검증용 일회성 스크립트만 쓴다) |
| 작업자 | Codex `gpt-6-astra`, `gpt-6-sol` | 배정받은 범위의 조사·구현. 한 과제 = 한 작업자 |
| 검토자 | 작업자와 **다른 모델**의 Codex | 작업 결과의 독립 재계산·리뷰(읽기 전용). 자기 결과를 스스로 승인하지 않는다 |

- 작업자는 과제 지시문에 적힌 **파일·범위 밖을 수정하지 않는다.** 범위 밖 문제는 보고만 한다.
  '수정 가능 파일'은 코드를 고칠 수 있는 파일이라는 뜻이다. 실행이 원래 만드는 산출물(그림·표·증거 JSON)을
  막으려고 코드의 동작을 바꾸지 않는다.
- 작업 대상은 **로컬 폴더의 파일**이다. `git commit`·브랜치 병합은 리더가 지시할 때만 하고,
  GitHub 원격 저장소로의 `push` 는 하지 않는다 (사용자만 한다).
- 구현 작업자는 리더가 지정한 브랜치 또는 worktree 에서만 작업한다. `main` 에는 직접 쓰지 않는다.

## 2. 절대 규칙 (연구 무결성)

1. **원본 불변.** `data/raw/**` 는 읽기만 한다.
2. **2022~2024 침수흔적은 홀드아웃이다.** `data/raw/flood_traces/changwon_info_disclosure_20260924/` 는
   지수 설계·가중치·등급 경계·임계값 선택·LOEO 캘리브레이션에 **절대 쓰지 않는다.** 최종 평가에만 쓴다.
3. **재튜닝 금지.** 검증 결과를 본 뒤 산식·가중치·임계를 바꾸면 그 변경은 `post-hoc` 으로 표기하고,
   바꾸기 전의 사전등록 결과를 함께 보고한다. 사전 게이트(AUC ≥ 0.70, 상위 20% 포착 ≥ 0.50)는 낮추지 않는다.
4. **숫자에는 출처가 붙는다.** 보고하는 모든 수치에 그 수치를 만든 명령어·스크립트·run_id 를 적는다.
5. **불리한 결과를 숨기지 않는다.** 격자 1표·침수 1표·폴리곤 1표 결과를 함께 싣고, 탈락한 게이트도 싣는다.
6. **문헌은 확인한 것만.** DOI 또는 URL 로 존재를 확인한 문헌만 인용한다. 확인 못 한 것은 `[미확인]` 으로 표시한다.

## 3. 환경

```bash
PY=/home/data/.venv-changwon/bin/python          # WSL. geopandas·rasterio 가 있는 유일한 환경
$PY -m unittest discover -s tests                # 테스트
$PY -m src.pipeline plan                         # 무엇이 재실행되는지
$PY -m src.pipeline run --target <node>          # 실행 (승인 게이트가 있는 노드는 멈춘다)
```

- 분석 좌표계 EPSG:5179. 새 공간자료는 원본 CRS 를 `.prj` 로 확인한 뒤 변환한다.
- 파이프라인 정의 `config/pipeline.yaml`, 단계 코드 `src/stages/`, 계산 함수 `src/data/`.
- 임시 산출물은 `.omc/` 아래에 둔다. `data/processed/` 는 파이프라인만 쓴다.

## 4. 과제 지시문과 보고 형식

리더가 주는 지시문에는 **목표 · 범위(파일) · 합격 기준 · 검증 명령**이 있다. 작업자는 끝나면 아래 형식으로 보고한다.

```
## 결과 요약        — 3줄 이내, 숫자 먼저
## 변경 파일        — 경로와 한 줄 설명 (조사 과제면 생략)
## 증거            — 실행한 명령과 핵심 출력
## 한계·미확인      — 확인하지 못한 것, 가정한 것
## 리더 판단 필요    — 범위 밖에서 발견한 문제, 결정이 필요한 선택지
```

## 5. 알려진 문제 (2026-09-24 기준)

해결됨: 로더 중복·홀드아웃 섞임(등록부), 합집합 겹침, 원본 품질 면제 만료(재판정), 전체 재실행 재현(9/16 결과와 동일),
H10 재현성 노드 구현·통과(run 20260924T163108Z-e25f3f2: 6개 검사 전부 통과).
연구 결과로 남는 것 (버그가 아니다, 보고서·논문에 그대로 쓴다):
- 동결 지수 L1 이 2022~2024 홀드아웃 사전 게이트 탈락 (격자 AUC 0.436, 포착 0.073)
- 강수 기후 축 역방향 (단독 AUC 개발 0.389, 홀드아웃 0.147)
- 10% 격자 라벨이 소규모 도심 침수를 지움 (홀드아웃 도심 폴리곤 12.3% 만 남음)
- 위험지수 등급을 침수 발생으로 캘리브레이션하는 개념 불일치
남은 작업: 동결 모델·불확실성 산출물이 `.omc/`(git 제외)에 있음 → `artifacts/` 로 옮겨야 재현 가능,
기존 대형 단계 파일(h06·h07·validate_raw) 기능별 분리 미착수.

## 6. 코드 작성 규칙

1. **주석은 한 줄.** 함수·클래스는 무엇을 하는지 한 줄 docstring, 함수 안의 코드 문단(빈 줄로 나뉜 논리 블록)마다
   그 문단이 하는 일을 한 줄 주석으로 단다. 여러 줄 설명·장문 docstring 은 쓰지 않는다. 근거·수식은 docs/ 에 둔다.
2. **기능마다 파일을 나눈다.** 한 파일 = 한 기능. 실행 흐름(읽기→계산→저장을 잇는 `run()`)과 계산 함수는 다른 파일에 둔다.
   새 기능은 기존 파일에 덧붙이지 말고 새 파일로 만든다. 여러 파일이 쓰는 공통 함수는 공통 모듈로 뺀다
   (예: 실행 기록 `src/models/provenance.py`).
3. 파일을 나눌 때 바깥에서 쓰던 이름(`from src.data import flood_traces as FT` 의 `FT.load` 등)은 원래 모듈에서
   계속 import 되게 한다. 동작은 바꾸지 않고, 나누기 전후 출력이 같음을 확인한다.

현재 기능별 파일 배치:

| 기능 | 파일 |
|---|---|
| 침수흔적 등록부 (개발/홀드아웃 역할) | `src/data/trace_registry.py`, `config/flood_traces.yaml` |
| 흔적 일자·호우·연도 정규화 | `src/data/trace_events.py` |
| 흔적 읽기·중복 제거 | `src/data/flood_traces.py` |
| 폴리곤 → 격자 라벨 | `src/data/trace_labels.py` |
| 검증 지표 (AUC·포착곡선·Boyce·재표본·통합 평가) | `src/data/validation/` |
| 비교 모델: 특징·모델 정의·지표·튜닝·교차검증 분할·실행 | `src/models/features.py`, `estimators.py`, `scoring.py`, `tuning.py`, `folds.py`, `benchmark.py` |
| 홀드아웃 평가: 점수 구성·게이트·실행 | `src/models/holdout_scores.py`, `gates.py`, `holdout_eval.py` |
| 라벨 규칙 감사 | `src/models/label_audit.py` |
| 복합지수 설계 불확실성: 설계 공간·분석 | `src/data/index_design.py`, `src/data/index_uncertainty.py` |
| 실행 기록 공통 | `src/models/provenance.py` |
| 예보 조건부 예측 (절차 `docs/FORECAST_PROTOCOL.md`): 호우 목록·흔적 연결·실행 | `src/forecast/storms.py`, `storm_labels.py`, `catalog_run.py` |
| 기상청 격자·HTTP·수집 계획·수집 실행·특보 | `src/forecast/kma_grid.py`, `kma_client.py`, `forecast_plan.py`, `collect_run.py`, `warnings.py`, `warnings_run.py` |
| 1단계 사상 발생: 사전분포 로지스틱·지표·예보/특보 특징·검증·실행 | `src/forecast/logit_prior.py`, `event_metrics.py`, `forecast_features.py`, `warning_features.py`, `trigger_eval.py`, `trigger_run.py`, `time_utils.py` |
| 2단계 위치·결합: 공간 재적합·보정·사상별 라벨·결합 평가·시나리오 지도·실행 | `src/forecast/spatial_refit.py`, `location_calibration.py`, `storm_cell_labels.py`, `combined_eval.py`, `scenario_maps.py`, `combined_run.py` |
| Q1 M1 자명 기준선: HAND·기준선 점수·배경 층·사전 판정·실행 (절차 `docs/q1/M1_protocol.md`) | `src/data/hand.py`, `src/models/m1_scores.py`, `m1_strata.py`, `m1_decision.py`, `m1_run.py` |
| 무작위효과 통합 (REML·DL·수정 HKSJ·예측구간·Q·I²·Q-profile) | `src/data/validation/meta_analysis.py` |
| Q1 M2 사상 단위 보고: 효과 크기·집합별 통합·판정·SE 점검·숲 그림·실행 (절차 `docs/q1/M2_protocol.md`) | `src/models/m2_effects.py`, `m2_pooling.py`, `m2_decision.py`, `m2_se_check.py`, `m2_forest.py`, `m2_run.py` |
| Q1 M4 라벨 규칙 × 격자 크기: 굵은 격자·흔적 자국·라벨 규칙·가중 AUC·객체 분해·생존·채점·판정·정합·실행 (절차 `docs/q1/M4_protocol.md`) | `src/data/coarse_grid.py`, `trace_footprint.py`, `label_rules.py`, `src/data/validation/weighted_auc.py`, `decomposition.py`, `src/models/m4_survival.py`, `m4_metrics.py`, `m4_decision.py`, `m4_checks.py`, `m4_run.py` |
| Q1 M6 재현성: 실행 비교·라벨 감사 재확인·연대표·기탁 목록·실행 (절차 `docs/q1/M6_protocol.md`) | `src/repro/run_compare.py`, `audit_check.py`, `chronology.py`, `deposit_manifest.py`, `m6_run.py`, `config/m6_chronology.yaml` |

## 7. 작업 흐름 (오케스트라 하네스)

```
리더: 과제 분해 → 지시서 .omc/work/prompts/<ID>.txt (목표·수정 가능 파일·합격 기준·검증 명령)
  → 작업자: Codex 구현 (astra·sol 번갈아, 파일 범위가 겹치지 않게 병렬)    보고서 .omc/work/<ID>.md
  → 검토자: 다른 모델의 Codex 가 읽기 전용 교차 리뷰                         .omc/review/<ID>.md
       FAIL / PASS-with-fixes → 수정 지시서로 다시 작업자에게 (같은 흐름 반복)
  → 리더 검증: 전체 unittest, 수치 재계산·산출물 동일성 비교, §6 주석 규칙 점검
  → 리더 커밋: 기능 단위 로컬 커밋 (push 는 사용자)
  → 기록: .omc/paper/.fablize/goals.json 체크포인트 (증거 포함)
```

실행 명령 (stdin 을 닫아야 멈추지 않는다):

```bash
codex exec -m gpt-6-astra -s workspace-write --skip-git-repo-check -c model_reasoning_effort=high \
  --json -o .omc/work/<ID>.md "$(cat .omc/work/prompts/<ID>.txt)" < /dev/null   # 구현
codex exec -m gpt-6-sol -s read-only --skip-git-repo-check -c web_search=live ... < /dev/null  # 조사·리뷰
```

- 조사 결과의 문헌은 리더가 DOI 를 전수 조회해 실재·저자를 확인한 뒤 문서에 옮긴다.
- 홀드아웃을 읽는 실행(평가·홀드아웃 테스트)은 리더만 한다. 작업자 테스트는 `CHANGWON_HOLDOUT_TESTS` 없이 돌린다.

## 8. 클라우드 세션 (`claude --cloud`, 2026-09-27 사용자 결정)

클라우드 세션에는 Codex 가 없다. 이 경우에 한해 §1·§7 을 다음처럼 바꾼다. §2 연구 무결성 규칙은 그대로다.

- **시작:** `bash scripts/cloud_setup.sh` 를 먼저 실행한다. Python 은 `PY=.venv/bin/python` 이다.
  이 스크립트는 `artifacts/frozen/`(동결 모델·불확실성)과 `artifacts/processed_snapshot/`(가공 자료, SHA256SUMS)을
  코드가 읽는 `.omc/`·`data/processed/` 로 복원한다.
- **구현:** 클라우드 Claude 세션(리더)이 직접 구현한다.
- **리뷰:** 구현과 다른 모델의 Claude 서브 에이전트가 읽기 전용으로 교차 리뷰한다. 자기 결과를 스스로 승인하지 않는다.
- **홀드아웃:** 홀드아웃을 읽는 실행은 클라우드 리더 세션만 한다. 서브 에이전트는 홀드아웃 원본과 그것을 읽는 코드를 쓰지 않는다.
- **산출물:** `artifacts/q1/<과제ID>/<run_id>/` 에 저장한다. `data/processed/` 는 여전히 파이프라인만 쓴다.
- **보고:** `docs/q1/<과제ID>.md` 에 §4 형식으로 쓴다.
- **커밋·푸시:** 자기 브랜치 `cloud/<과제ID>` 에만 커밋·푸시한다. `develop`·`main` 병합은 사용자가 한다.
- **과제 정의:** `docs/CLOUD_TASKS.md`.
- **브랜치:** 클라우드는 LFS 없는 `cloud-base` 브랜치에서 시작한다. 이 브랜치는 필요한 코드·문서·자료만 담은 일반 git 파일이다.
  로컬 작업 폴더는 git worktree `../창원_cloud` 다.
- **결과 반영:** 결과 브랜치(`cloud/<ID>`)는 develop 에 병합하지 않는다. 리더가 파일 단위로 가져온다: `git checkout cloud/<ID> -- <경로>`.
