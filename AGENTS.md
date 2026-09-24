# AGENTS.md — 창원 CDRI 프로젝트 에이전트 작업 규칙

> Codex·Claude 등 이 저장소에서 일하는 모든 에이전트가 따른다.
> 사람용 안내는 `README.md`·`CONTRIBUTING.md`, 방법론은 `docs/METHODOLOGY.md`.

## 1. 팀 구조

| 역할 | 담당 | 하는 일 |
|---|---|---|
| 리더 (오케스트레이터) | Claude Opus 5.5 (Claude Code) | 과제 분해·배정, 결과 통합, 교차검증, 최종 판정. 사용자와의 유일한 창구 |
| 작업자 | Codex `gpt-6-astra`, `gpt-6-sol` | 배정받은 범위의 조사·구현·검토. 한 과제 = 한 작업자 |
| 검토자 | 작업자와 **다른** 에이전트 | 작업 결과의 독립 재계산·리뷰. 자기 결과를 스스로 승인하지 않는다 |

- 작업자는 과제 지시문에 적힌 **파일·범위 밖을 수정하지 않는다.** 범위 밖 문제는 보고만 한다.
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

상세는 `.omc/research/00_context_brief.md`.
- 동결 지수가 2022~2024 홀드아웃에서 게이트 탈락 (L1 AUC 0.436 격자 1표 / 0.603 침수 1표)
- 강수 노출 축이 역방향 (단독 AUC 0.389 기존, 0.147 신규)
- 10% 겹침 라벨이 소규모 도심 침수를 배제 (도심 57개 중 52개 < 1,000 m²)
- 위험지수 등급을 침수 발생으로 캘리브레이션하는 개념 불일치
- `src/data/flood_traces.py` 로더가 신규 자료의 중복(좌표계 2벌·L100 세분)을 거르지 못함

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
