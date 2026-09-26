"""수정 벤치마크의 선택 비교와 모든 평균 지표를 보고한다."""

import json
from pathlib import Path

import pandas as pd


output = Path('.omc/benchmark')
spec = json.loads((output / 'prespec.json').read_text())
verification = json.loads((output / 'verification.json').read_text())
selection = spec['selection']
table = pd.read_csv(output / 'results_dev.csv')
means = table[table.fold == 'mean'].pivot(index=['model', 'feature_set', 'cv'], columns='metric', values='value').reset_index()
gates = pd.read_csv(output / 'gates_dev.csv')
failed = gates[~(gates.auc_gate_pass & gates.capture_gate_pass)]
same = spec['revision']['selection_matches_v1']
summary = f"v1 대비 선택 {'동일' if same else '변경'}: {selection['model']}/{selection['feature_set']}, {selection['parameters']}"
note = {'run_id': spec['run_id'], 'holdout_read': False, 'holdout_scored': False,
        'test_scope': 'tests.test_benchmark only; CHANGWON_HOLDOUT_TESTS unset',
        'test_command': 'env -u CHANGWON_HOLDOUT_TESTS PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp /home/data/.venv-changwon/bin/python -m unittest tests.test_benchmark',
        'test_output': (output / 'unittest.log').read_text().strip(),
        'v1_holdout_read': True, 'v1_violation_preserved': 'v1/prespec.json, v1/unittest.log, v1/validation_scope_note.json',
        'independent_review': '미실시; 이 실행은 구현 작업자의 자체 재검산이며 승인은 리더·독립 검토자 담당'}
(output / 'validation_scope_note.json').write_text(json.dumps(note, ensure_ascii=False, indent=2) + '\n')
lines = [summary, '', '## 결과 요약', '',
         f"- run_id: `{spec['run_id']}`; `{spec['command']}` → {spec['elapsed_seconds']}초, {len(table)}행.",
         f"- 후보·특징·선택 규칙·고정 파라미터는 v1과 동일; 평균 게이트 탈락 {len(failed)}/{len(gates)}건.",
         '- 이번 실행은 홀드아웃 미접근·미채점. v1의 접근 위반은 보존했으며 소급해 지우지 않았다.', '',
         '## 변경 파일', '', '- src/models/folds.py: LOEO 학습 사상별 그룹, 원본 폴리곤 거리.',
         '- src/models/benchmark.py: 사상별 그룹 연결·개발 원본 로딩·v1 비교 이력 기록.',
         '- tests/test_benchmark.py: 제외 사상 변경 불변성·원본 거리·공간 제외 검증.',
         '- .omc/benchmark/: 새 산출물·로그·재현 스크립트; v1/에 기존 산출물 보존.', '',
         '## 증거', '', '공통 환경: `env -u CHANGWON_HOLDOUT_TESTS PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp PYTHONPATH=.`',
         '`PY=/home/data/.venv-changwon/bin/python`', '',
         '| 발견 | 재현 전 출력 → 수정 후 출력 | 명령/증거 |', '|---|---|---|',
         '| 1 | v1 `holdout_read=true`, `holdout: polygons=196 ... positive=1267` → 환경변수 없음, 벤치마크 테스트만 `OK`, 이번 `holdout_read=false` | `rg -n "holdout:|holdout_read" .omc/benchmark/v1/unittest.log .omc/benchmark/v1/prespec.json`; `$PY -m unittest tests.test_benchmark` |',
         '| 2 | 검토 명령 `254 259`; 제외 사상 제거 시 변경 그룹 행 `807` → 공간·배경 그룹 변경 행 `0 0`; 회귀 테스트 `FAIL` → `OK` | `$PY .omc/benchmark/reproduce_review.py`; `reproduction_test_before.log`, `unittest.log` |',
         '| 3 | `center_score -100.0 polygon_score -50.0` → `past_flood -50.0 polygon_score -50.0 inside -0.0` | `$PY .omc/benchmark/reproduce_review.py` |', '',
         '단위 테스트 출력:', '```', note['test_output'], '```', '',
         f"`$PY .omc/benchmark/verify_dev.py` → 지표 {verification['verified_metric_values']}개 재검산, "
         f"외부 {verification['verified_outer_parts']}개 부분 fold·내부 {verification['verified_inner_splits']}개 분할 확인. "
         f"덩어리 분리·버퍼 위반·학습 시험 중복 0. LOEO {verification['loeo_held_label_invariance_events']}개 사상 모두 제외 라벨 반전에도 그룹 불변. "
         '원본 폴리곤 거리 전수 후보 비교와 저장 예측 표본 일치. 코드·입력·v1 산출물 해시 일치.', '',
         '모든 모델×특징×CV 평균 지표 (출처: 같은 run_id의 results_dev.csv; 생성: `$PY .omc/benchmark/summarize_dev.py`):', '',
         '| 모델 | 특징 | CV | 격자 AUC | 덩어리 AUC | 관측 AP | 상위20% 포착 |', '|---|---|---|---:|---:|---:|---:|']
for row in means.itertuples():
    lines.append(f'| {row.model} | {row.feature_set} | {row.cv} | {row.grid_auc:.6f} | {row.cluster_auc:.6f} | {row.observed_label_ap:.6f} | {row.top20_capture:.6f} |')
lines += ['', '평균 게이트 탈락 항목 (기준 유지: AUC≥0.70, 포착≥0.50):', '',
          '| 모델 | 특징 | CV | AUC | 포착 |', '|---|---|---|---:|---:|']
for row in failed.itertuples():
    lines.append(f'| {row.model} | {row.feature_set} | {row.cv} | {row.mean_grid_auc:.6f} | {row.mean_top20_capture:.6f} |')
lines += ['', 'fold별 모든 값은 results_dev.csv, 개별 게이트는 gates_all_folds.csv에 기록했다.', '',
          '## 한계·미확인', '', '- 기존 홀드아웃 결과가 알려진 뒤의 post-hoc 검토 수정이며 최초 사전등록이 아니다.',
          '- 폴리곤 1표 평가는 기존 비교 지표 범위에 없어 추가하지 않았다. 원본 폴리곤은 근접도 기준선에 사용했다.',
          '- 공간 CV의 근접도는 학습·시험 영역을 함께 가로지르는 원본 폴리곤을 통째로 제외한다.',
          '- 전체 테스트 및 홀드아웃 평가는 실행하지 않았다.', '', '## 리더 판단 필요', '',
          '- 수정 코드·새 동결 결과의 독립 검토 및 최종 승인. 과거 v1 접근 위반 이력은 계속 병기해야 한다.', '']
(output / 'report_dev.md').write_text('\n'.join(lines))
print(summary)
print('run_id', spec['run_id'], 'elapsed_seconds', spec['elapsed_seconds'], 'result_rows', len(table), 'failed_mean_gates', len(failed))
print(means[(means.model == selection['model']) & (means.feature_set == selection['feature_set'])].to_string(index=False))
