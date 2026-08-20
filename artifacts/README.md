# 하네스 실행 증거

분석 실행 중 자동 생성되는 검증 보고서와 run manifest를 저장합니다.

- `validation/raw_validation.json`: 원본 데이터 계약·품질 검사 결과
- `runs/<run_id>/`: 이후 단계별 설정, 로그, 지표, 산출물 checksum

실행 산출물은 용량과 시각 차이 때문에 Git에서 제외합니다. 보고서에 사용할 확정
수치와 표는 `reports/`로 승격하고, 해당 수치를 만든 `run_id`와 Git commit을 함께
기록합니다.
