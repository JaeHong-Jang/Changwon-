# 🏆 2026년 창원시 AI·데이터 활용 공모전

> 개방된 공공데이터를 활용하여 창원시의 생활불편 해결 및 공공 이익·발전에 기여

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
│   ├── 01_data_collection.ipynb
│   ├── 02_eda.ipynb
│   ├── 03_preprocessing.ipynb
│   ├── 04_modeling.ipynb
│   └── 05_visualization.ipynb
├── src/                   # 소스 코드
│   ├── data/              #   데이터 수집·전처리
│   ├── models/            #   분석 모델
│   ├── visualization/     #   시각화
│   └── utils/             #   유틸리티
├── reports/               # 보고서·발표자료
│   ├── figures/           #   그래프·이미지
│   └── final/             #   최종 제출물
├── docs/                  # 문서·참고자료
│   ├── references/        #   참고문헌·논문
│   └── submission/        #   제출 서식
├── config/                # 설정 파일
├── tests/                 # 테스트 코드
├── .gitignore
├── requirements.txt       # Python 패키지 목록
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
```

### 분석 파이프라인

```
데이터 수집 → EDA → 전처리 → 모델링 → 시각화 → 보고서 작성
  (01)       (02)    (03)      (04)      (05)      reports/
```

## 📊 활용 데이터

| 데이터 | 출처 | 비고 |
|--------|------|------|
| (추후 기입) | [공공데이터포털](https://www.data.go.kr) | 필수 1건 이상 |
| (추후 기입) | [창원시 데이터포털](http://bigdata.changwon.go.kr) | |

## 👥 팀 구성

| 이름 | 역할 | 담당 |
|------|------|------|
| (추후 기입) | 팀장 | |
| | | |

## 📅 일정

- [x] 주제 선정
- [ ] 데이터 수집
- [ ] 탐색적 데이터 분석 (EDA)
- [ ] 데이터 전처리
- [ ] 모델링 및 분석
- [ ] 시각화
- [ ] 보고서 작성 (A4 10~20매)
- [ ] 제출 (~9/30 18:00)

## 📝 라이선스

본 프로젝트는 2026년 창원시 AI·데이터 활용 공모전 출품작입니다.
