# 🏆 2026년 창원시 AI·데이터 활용 공모전

> 개방된 공공데이터를 활용하여 창원시의 생활불편 해결 및 공공 이익·발전에 기여

## 🎯 프로젝트 주제

### 창원시 폭우·기후재난 AI 선제 대응 시스템

집중호우·태풍 발생 시 **침수 취약지역 + 하수도 역류 위험 + 취약계층 분포**를 통합 분석하여
창원시가 우선적으로 점검·대응해야 하는 지역을 선정하는 AI 시스템

```
폭우 예보 → Layer 1. 어디가 잠기나? (침수 취약 격자)
           → Layer 2. 어디가 역류하나? (관로 노후도)
           → Layer 3. 누가 위험한가? (취약계층 분포)
           → 통합 위험도 → 우선 대응 지역 TOP 20
           → 🤖 AI Agent 선제 알림
```

## 📋 공모전 개요

| 항목 | 내용 |
|------|------|
| **주최** | 창원시 |
| **접수기간** | 2026.06.01 ~ 2026.09.30 (18:00) |
| **참가자격** | 대학생·대학원생 (휴학생 포함, 4인 이내 팀) |
| **제출물** | 참가신청서 + 분석보고서 (A4 10~20매) |
| **시상** | 최우수(150만) / 우수(100만×2) / 장려(50만×3) / 노력(10만×5) |

## 📁 프로젝트 구조

```
├── data/                  # 데이터
│   ├── raw/               #   원본 데이터 (수정 금지)
│   ├── processed/         #   전처리 완료 데이터
│   └── external/          #   외부 보조 데이터
├── notebooks/             # Jupyter 분석 노트북
│   ├── 01_data_collection.ipynb    # 데이터 수집
│   ├── 02_eda.ipynb                # 탐색적 데이터 분석
│   ├── 03_preprocessing.ipynb      # 전처리·병합
│   ├── 04_modeling.ipynb           # 위험도 모델링
│   └── 05_visualization.ipynb      # 시각화·지도
├── src/                   # 소스 코드
│   ├── data/              #   데이터 수집·전처리 모듈
│   ├── models/            #   분석 모델
│   ├── visualization/     #   시각화
│   └── utils/             #   유틸리티
├── reports/               # 보고서·발표자료
│   ├── figures/           #   그래프·이미지
│   └── final/             #   최종 제출물
├── docs/                  # 문서·참고자료
│   ├── references/        #   참고문헌·정보공개청구 문안
│   └── submission/        #   제출 서식
├── config/                # 설정 파일
├── tests/                 # 테스트 코드
├── .gitignore
├── requirements.txt       # Python 패키지 목록
├── CONTRIBUTING.md        # 협업 가이드
└── README.md
```

## 🚀 시작하기

### 환경 설정

```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

# 패키지 설치
pip install -r requirements.txt

# .env 파일 생성 (API 키 설정)
cp .env.example .env
# .env 파일을 열어 기상청 API 키 입력
```

### 분석 파이프라인

```
데이터 수집 → EDA → 전처리 → 모델링 → 시각화 → 보고서 작성
  (01)       (02)    (03)      (04)      (05)      reports/
```

## 📊 활용 데이터

| # | 데이터 | 출처 | 용도 |
|---|--------|------|------|
| 1 | [하수관로 시설별 설치현황](https://www.data.go.kr/data/15118453/fileData.do) | 한국환경공단 | 관로 노후도 분석 |
| 2 | [시간별 강수량](https://www.data.go.kr/data/15150315/fileData.do) | 기상청 | 침수·역류 트리거 |
| 3 | [배수펌프장 현황](https://www.data.go.kr/data/15047868/fileData.do) | 환경부 | 배수 용량 분석 |
| 4 | [하수도 배수구역](https://www.data.go.kr/data/15129161/fileData.do) | 국토교통부 | 배수 구역 경계 |
| 5 | [건축물대장](https://www.data.go.kr/data/15064338/fileData.do) | 창원시 | 노후 건물·반지하 |
| 6 | 기상청 종관기상관측 API | 기상청 | 실시간 기상 데이터 |
| 7 | 동별 인구통계 (고령·1인가구) | 통계청 | 취약계층 분포 |
| 8 | 하수도 민원 접수 현황 | 창원시 (정보공개청구) | 민원 핫스팟 분석 |

## 🤖 AI Agent 시스템

| Agent | 기능 |
|-------|------|
| 재난 감시 | 기상청 API 감시 → 폭우 시 위험 구간 선제 알림 |
| 민원 분석 | 민원 텍스트 → 위치·유형·긴급도 자동 분류 |
| 시민 안내 | "우리 동네 침수 위험?" → 위험도 + 대피소 안내 |

## 👥 팀 구성

| 이름 | 역할 | 담당 |
|------|------|------|
| (추후 기입) | 팀장 | |
| | | |

## 🗺️ 연구 계획 & 진행 관리 (하네스)

**계획 원본**: [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) — 딥리서치 3건(데이터 검증·방법론·수상작 패턴) 기반, 14개 스토리 × 7 페이즈, 각 스토리에 검증 기준·담당·기한 명시.

진행 상태는 `.fablize/goals.json`에 영속화되며, **증거 없이는 스토리를 완료할 수 없습니다.**

```bash
# 저장소 루트에서 (Windows는 python + C:\Users\User\.claude\... 경로)
python3 /mnt/c/Users/User/.claude/plugins/fablize/scripts/goals.py status       # 현재 어디까지 왔나
python3 /mnt/c/Users/User/.claude/plugins/fablize/scripts/goals.py next         # 다음 스토리 활성화 + 할 일 출력
python3 /mnt/c/Users/User/.claude/plugins/fablize/scripts/goals.py checkpoint --id G001 --status complete --evidence "docs/data_access_log.md 접수번호 6건"
```

| Phase | 스토리 | 기간 |
|-------|--------|------|
| 0 착수 | G001 데이터 접근 일괄 신청 | 8/18~8/20 |
| 1 데이터 | G002 다운로드·검증 → G003 관측지점 좌표 → G004 100m 격자 | 8/18~8/31 |
| 2 EDA | G005 | 8/25~9/5 |
| 3 **Decision Gate** | G006 Layer 2 Plan A/B 확정 (정보공개 회신 기반) | 9/1~9/3 |
| 4 모델링 | G007 침수 → G008 역류 → G009 취약계층 → G010 통합 CDRI·TOP 20 | 9/1~9/15 |
| 5 AI Agent | G011 프로토타입·시나리오 3개 | 9/10~9/20 |
| 6 보고서 | G012 시각화 → G013 v1→리뷰→v2 | 9/15~9/28 |
| 7 **검증 게이트** | G014 재실행·페이지·출처 검증 → 제출 | 9/28~9/30 18:00 |

관련 문서: [`docs/report_checklist.md`](docs/report_checklist.md) · [`docs/data_access_log.md`](docs/data_access_log.md) · [`docs/decisions/`](docs/decisions/) · [`docs/references/정보공개청구_문안.md`](docs/references/정보공개청구_문안.md)

## 📝 라이선스

본 프로젝트는 2026년 창원시 AI·데이터 활용 공모전 출품작입니다.
