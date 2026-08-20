# 🤝 협업 가이드

> 팀원 모두가 충돌 없이 효율적으로 작업하기 위한 규칙입니다.
> **작업 전에 반드시 한 번 읽어주세요.**

---

## 📌 Git 브랜치 전략

### 브랜치 구조

```
main              ← 최종 제출용 (직접 push 금지)
├── dev           ← 통합 개발 브랜치 (여기서 테스트 후 main에 병합)
├── feat/주제     ← 기능 개발
├── data/주제     ← 데이터 수집·전처리
├── docs/주제     ← 문서·보고서
└── fix/주제      ← 버그 수정
```

### 규칙

| 규칙 | 설명 |
|------|------|
| `main`에 직접 push ❌ | 반드시 `dev` → `main` PR을 통해서만 병합 |
| `dev`에 직접 push ❌ | 개인 브랜치에서 작업 후 `dev`로 PR |
| 개인 브랜치에서 작업 ✅ | `feat/`, `data/`, `docs/`, `fix/` 접두사 사용 |

### 브랜치 이름 예시

```bash
feat/eda-visualization      # EDA 시각화 작업
data/traffic-accident        # 교통사고 데이터 수집
docs/report-draft            # 보고서 초안 작성
fix/missing-values           # 결측치 처리 버그 수정
```

---

## 📝 커밋 메시지 규칙

### 형식

```
<타입>: <무엇을 했는지 간단하게>

(선택) 상세 설명
```

### 타입 목록

| 타입 | 사용 시점 | 예시 |
|------|-----------|------|
| `feat` | 새로운 분석/기능 추가 | `feat: 교통사고 핫스팟 클러스터링 추가` |
| `data` | 데이터 수집·전처리 | `data: 창원시 인구통계 데이터 전처리` |
| `fix` | 버그 수정 | `fix: 결측치 처리 로직 오류 수정` |
| `docs` | 문서 작성·수정 | `docs: 보고서 3장 시각화 결과 추가` |
| `refactor` | 코드 정리 (기능 변화 없음) | `refactor: 데이터 로딩 함수 분리` |
| `style` | 포맷팅, 주석 등 | `style: 노트북 셀 정리 및 주석 보강` |
| `chore` | 설정, 환경, 기타 | `chore: requirements.txt 패키지 추가` |

### 나쁜 커밋 메시지 vs 좋은 커밋 메시지

```bash
# ❌ 나쁜 예시
git commit -m "수정"
git commit -m "업데이트"
git commit -m "작업중"

# ✅ 좋은 예시
git commit -m "feat: XGBoost 모델 학습 및 하이퍼파라미터 튜닝"
git commit -m "data: 공공데이터포털 대기질 데이터 수집 스크립트 작성"
git commit -m "docs: 분석보고서 2장 데이터 설명 작성"
```

---

## 🔄 작업 흐름 (Workflow)

### 1. 작업 시작 전

```bash
# 1) dev 브랜치 최신화
git checkout dev
git pull origin dev

# 2) 작업 브랜치 생성
git checkout -b feat/내-작업-이름
```

### 2. 작업 중

```bash
# 적절한 단위로 커밋 (한 번에 몰아서 ❌)
git add 변경파일
git commit -m "feat: 작업 내용 설명"
```

### 3. 작업 완료 → PR

```bash
# 1) dev 최신 내용 반영 (충돌 방지)
git checkout dev
git pull origin dev
git checkout feat/내-작업-이름
git merge dev

# 2) 충돌 있으면 해결 후 커밋

# 3) push
git push origin feat/내-작업-이름

# 4) GitHub에서 dev ← feat/내-작업-이름 PR 생성
#    - 무엇을 했는지 간단히 설명
#    - 팀원 1명 이상 리뷰 후 병합
```

### 4. PR 병합 후 정리

```bash
# 로컬 브랜치 삭제
git checkout dev
git pull origin dev
git branch -d feat/내-작업-이름
```

---

## 📂 파일 관리 규칙

### 데이터 파일

| 규칙 | 이유 |
|------|------|
| `data/raw/` 원본은 **절대 수정 금지** | 재현성 보장 |
| `data/raw/**`는 Git LFS로만 공유 | 일반 Git blob 비대화 방지, commit과 원본 checksum 고정 |
| 데이터 추가 시 해당 폴더 `README.md`에 출처 기록 | 보고서에 명시 필요 |
| clone/pull 후 `git lfs pull`과 원본 검증 실행 | 포인터를 원본으로 오인하는 문제 방지 |

### 노트북 (.ipynb)

| 규칙 | 이유 |
|------|------|
| 번호 순서 유지 (`01_`, `02_`, ...) | 분석 흐름 파악 |
| **커밋 전 Kernel → Restart & Run All** 실행 | 처음부터 돌아가는지 확인 |
| 셀 출력 결과는 **지우고** 커밋 (선택) | 충돌 감소 |
| 재사용 코드는 `src/`로 분리 | 노트북 간 중복 방지 |

### 보고서

| 규칙 | 이유 |
|------|------|
| 그래프는 `reports/figures/`에 저장 | 보고서에서 참조 |
| 최종 제출물은 `reports/final/`에 | 명확한 구분 |
| 파일명: `보고서_v1.docx`, `보고서_v2.docx` | 버전 관리 |

---

## 🚫 하지 말아야 할 것들

1. **`main` 브랜치에 직접 push** → 반드시 PR을 통해 병합
2. **커밋 메시지 "수정", "업데이트"** → 구체적으로 쓰기
3. **다른 사람 브랜치에서 작업** → 자기 브랜치만 사용
4. **API 키를 코드에 직접 작성** → `.env` 파일 사용
5. **Git LFS 확인 없이 `data/raw/` 추가** → `.gitattributes` 적용과 `git lfs status`를 먼저 확인
6. **merge 충돌을 대충 해결** → 확인 후 충돌 해결, 모르면 팀원에게 물어보기

---

## 💬 소통 규칙

- **작업 시작/완료** 시 팀 채팅에 공유
- **PR 생성** 시 팀원 태그하여 리뷰 요청
- **충돌** 발생 시 혼자 해결하지 말고 관련 팀원과 상의
- **큰 구조 변경** 전에 팀원 합의 필요

---

## 🛠️ 개발 환경 세팅

```bash
# 1. 저장소 클론
git clone https://github.com/JaeHong-Jang/Changwon-.git
cd Changwon-

# 2. dev 브랜치로 이동
git checkout dev

# 3. 가상환경 생성
python -m venv venv

# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate

# 4. 패키지 설치
pip install -r requirements.txt

# 5. .env 파일 생성 (API 키 설정)
cp .env.example .env
# .env 파일 열어서 API 키 입력
```
