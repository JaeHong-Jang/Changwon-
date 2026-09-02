"""DAG 노드 runner 모음. 각 함수는 (ctx: StageContext) -> dict 계약을 따른다.

규칙
- 입력은 ctx.inputs / ctx.params / ctx.config 로만 받는다 (숨은 전역 경로 금지).
- 출력은 ctx.outputs 에 선언된 경로에만 쓴다. 전부 생성돼야 게이트 통과.
- 통과 기준 미달이면 StageFailed(message, findings) 를 던진다. 임계치 완화 금지.
- 반환 dict는 manifest의 metrics로 기록된다 (행수, coverage, AUC 등 핵심 지표).
- 무거운 로직은 src/data, src/models, src/visualization 에 두고 여기서는 조립만 한다.
"""
