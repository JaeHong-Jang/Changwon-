# 논문화 로드맵 — SCI Q1 방법론 논문으로 가는 길

> 2026-09-24 갱신. 근거: 홀드아웃 재채점(`src/models/holdout_eval.py`) + Codex 조사 보고서 6편
> (`.omc/research/R1~R4.md`, `N1.md` 신규성, `N2.md` Q1 가능성; 인용 DOI 102개 전수 확인).
> 작업 규칙 `AGENTS.md`, 진행 추적 `.omc/paper/.fablize/goals.json`.

## 1. 한 줄 결론

"창원형 지수를 만들어 AUC 0.750 으로 검증했다"는 지금 원고의 주장은, 지수 확정 뒤 받은
2022~2024 사상에서 유지되지 않았다. 논문의 질문을 이렇게 바꾼다.

> 사전 동결한 도시 침수 지수를 지수 확정 뒤 확보한 독립 사상으로 평가했을 때 원래 게이트에서 탈락했다.
> 같은 기록을 다른 단위로 채점하면 결론이 달라졌고, 그 차이는 행정 침수 폴리곤을 100 m 격자로 옮기는
> 규칙(소형 도심 침수 소실)과 사상 유형(도심/농경지)에서 온다.

**쓰면 안 되는 표현** (N1): "전향적(prospective)·사전등록(pre-registered) 검증" — 2022~2024 사상은 지수 확정
**전에** 일어났고 공개 등록도 없었다. 정확한 표현은 **"사전 동결 지수의 사후 확보 독립 사상 평가"**다.
그 밖에 "검증 단위가 AUC 를 바꾼다는 최초 발견"(Ozturk et al. 2021 선행), "국토부 지침의 최초 실측 반례"
(이상혁·강정은 2018 선행), "미기록 침수 때문에 AUC 는 하한", "강수 축 역방향 원인은 산지 강우로 확정"도 쓰지 않는다.

## 2. 확인된 수치

출처: `python -m src.models.holdout_eval`, run_id `holdout_20260924T100939Z_ae9c122-dirty_cf388a23`
(`artifacts/evaluation/holdout_2022_2024/<run_id>/summary.json`; `-dirty` = 코드 미커밋 상태에서 실행).
게이트 = 격자 1표 AUC ≥ 0.70, 상위 20% 포착 ≥ 0.50 (h06 과 같은 함수).

| 점수 | 성격 | 격자 AUC | 침수 1건 AUC | 상위 20% 포착 | 게이트 |
|---|---|---:|---:|---:|:--:|
| L1 (현행 지수) | 사전 게이트 대상 | 0.436 | 0.603 | 0.073 | 탈락 |
| 시 침수예상도 | 기준 | 0.450 | 0.494 | 0.026 | 탈락 |
| 과거 침수 근접도 (2022 이전 흔적 폴리곤 거리) | 기준 | 0.532 | 0.568 | 0.205 | 탈락 |
| 민감도 축 단독 | post-hoc | 0.735 | 0.762 | 0.225 | 탈락 |
| 강수 노출 축 단독 | post-hoc | 0.147 | 0.346 | 0.016 | 탈락 |
| **RF-F1 동결 (v2)** | 동결, post-hoc 설계 | 0.858 | 0.826 | 0.857 | 통과 |
| **RF-F1, 2019년까지 사상만 학습** | 동결 설정 재학습 | 0.843 | 0.821 | 0.763 | 통과 |
| RF-F0 (v1) | 대체됨 | 0.876 | 0.834 | 0.867 | 통과 |

- RF 는 개발 자료(6사상) 공간·사상 교차검증으로 선택하고 동결했다(prespec run_id `P005_dev_20260924T094916Z`).
  v1 선택(RF-F0)은 교차 리뷰에서 LOEO 분할 누수가 발견돼 고친 뒤 RF-F1 로 바뀌었다(선택 점수 0.8412 vs 0.8407, 사실상 동점).
- **주 결과는 "2019년까지 학습" 행이다.** 2025 개발 사상은 홀드아웃보다 늦고, 2024-09 침수 지역과 겹친다.
- 특징 후보군(F0/F1/F2)은 리더가 홀드아웃 진단을 본 뒤 정했다. 확증 근거가 아니다.

폴리곤 1개 = 1표 AUC [95% 구간] (배경 = 어떤 흔적과도 닿지 않은 격자):

| 폴리곤 | L1 | RF-F1 (2019까지) | 시 예상도 |
|---|---:|---:|---:|
| 전체 196 | 0.712 | 0.840 | 0.606 |
| 도심 57 | 0.910 [0.879, 0.938] | 0.893 [0.859, 0.922] | 0.894 |
| 농경지 119 | 0.608 [0.574, 0.642] | 0.818 [0.800, 0.834] | 0.450 |

라벨 감사 (`python -m src.models.label_audit`, 10% 격자 규칙에서 양성 격자를 남기는 폴리곤 비율):

| 자료 | 전체 | 도심 | 농경지 | 면적 중앙값 |
|---|---:|---:|---:|---:|
| 개발 145개 (`label_audit_development_20260924T095654Z_40523c56`) | 95.2% | — | — | 8,750 m² |
| 홀드아웃 196개 (`label_audit_holdout_20260924T095656Z_40523c56`) | 66.3% | 12.3% | 97.5% | 3,590 m² |

→ 두 인벤토리의 크기 구성이 달라 같은 규칙이 홀드아웃에서만 도심 침수 88% 를 지운다.
격자 단위 검증이 홀드아웃에서 사실상 농경지 침수 시험이 된 이유다(C2 의 메커니즘).

개발 자료(6사상) 공간 교차검증, 침수 1건 AUC: L1 0.749, 민감도 축 0.836, RF-F0 0.836, RF-F2(강수 포함) 0.816.
→ **강수 기후 변수는 모든 모델에서 성능을 낮춘다. 기계학습은 단순 민감도 축보다 낫지 않다.**

## 3. 신규성 판정 (N1)

| 후보 기여 | 판정 | 가장 가까운 선행 | 우리가 주장할 수 있는 것 |
|---|---|---|---|
| C2 검증 단위·라벨 변환 효과 | **좁은 버전은 차별점 있음** | Ozturk et al. 2021 (산사태 크기·격자 중첩), Landwehr et al. 2024 (EO 침수지도 검증 설계) | 행정 침수 폴리곤을 10% 격자 규칙으로 옮길 때 소형 도심 침수가 사라지고 농경지 대면적 침수가 투표권을 얻는 과정을 객체 단위로 추적 |
| C5 다도시 재현 | **동일 설계 선행 미발견** — 가장 강한 확장 | Han & Lee 2026 (SSRN, 무주·청양 전이) | 행안부 전국 흔적으로 C2 를 여러 도시에서 사전 고정 절차로 재현 |
| C1 동결 지수 실패 보고 | 부분 선행 | Lee et al. 2018 (서울 다른 연도 검증), Merz et al. 2024 | 실패 게이트를 보존하고 감사 가능한 연대표 제시 |
| C3 강수 축 역방향 | 좁은 경험 결과 | 이상혁·강정은 2018 (부산 지침 결과의 실측 대조) | 100 m 내수침수에서 축별 순위 시험 |
| C4 등급 구성 타당도 | 원리 선행 | Rufat et al. 2019, Bakkensen et al. 2017 | 창원 등급의 발생률 역전 사례 |

## 4. 투고처 (N2, JCR 2024 기준 — 투고 직전 도서관 JCR·MJL 로 재확인)

| 저널 | JCR 2024 | 보강 후 현실성 | 조건 |
|---|---|:--:|---|
| **NHESS** | Q1 (수자원·다학제 지구과학) | 상 | 동결 원안 실패 재현, 단위·기록편향·라벨 규칙 분리, 재사용 가능한 진단 절차 |
| **IJDRR** | Q1 | 상 | 평가 선택이 대응지역·보호대상 인구를 어떻게 바꾸는지 |
| Natural Hazards | 다학제 지구과학 Q1, 수자원 Q2 | 상 | 인정 분야 확인 필요 |
| Environmental Modelling & Software | 수자원 Q1, 환경과학 Q2 | 중 | 외부 사용자가 쓸 평가 소프트웨어·예제 |
| Journal of Hydrology | Q1 | 중 | 강수·지형·배수와 실패의 수문학적 설명 |
| Earth's Future / WRR | Q1 | 중 | 다도시 재현 + 정책 영향 |
| JFRM | **Q2** (SJR Q1 과 혼동 금지) | 상 | Q1 목표와 불일치 |
| STOTEN | 색인 문제 | 하 | 목표에서 제외 |
| npj Natural Hazards | 미확인 | — | Nature 브랜드 ≠ JCR Q1 |

단일 도시·학부생 신분은 결정적 장애가 아니다(N2 게재 사례 17건). 가장 큰 장애는 실패 결과를
재현 가능한 과학적 주장으로 완성하는 것이다.

## 5. 할 일

### P0 — 논문의 전제 조건

| # | 내용 | 상태 |
|---|---|---|
| 1 | 홀드아웃 채점을 저장소 코드·run_id 로 편입 | 완료 (`src/models/holdout_eval.py`) |
| 2 | 침수흔적 로더: 개발/홀드아웃 등록부, storm_id·object_id, 합집합 겹침, 날짜 복원 | 완료, 2차 리뷰 통과 |
| 3 | 검증 프로토콜 v2: 격자(게이트)·덩어리·폴리곤·면적, Boyce, 포착곡선 | 완료, 2차 리뷰 통과 |
| 4 | 비교 모델 벤치마크 (ridge·FR·RF·XGBoost, 공간·사상 CV) | 완료, 분할 누수 수정 후 재선택(RF-F1) |
| 5 | 복합지수 설계 불확실성 (TOP20 포함확률) | 완료, 리뷰 통과 |
| 6 | HEAD 전체 재실행 재현성 | 격리 작업트리 준비됨 — 사용자 실행 대기 |
| 7 | C2 원인 분해: 폴리곤별 면적·토지이용·교차 격자·규칙별 포함 여부 추적표 | 완료 (`src/models/label_audit.py`) |
| 8 | 연대표: 지수 동결 시점, 입력 자료 시점, 흔적 입수 시점, 최초 채점 | 예정 |

### P1 — Q1 수준으로 올리는 것

- **다도시 재현 (C5)**: 행안부 API 전국 흔적에서 도시 선정 기준(자료 완전성·도시구조·침수유형)을 성능 확인 전에 고정하고, 창원에서 얻은 평가 규약을 그대로 적용한다. 창원 지수 없이도 "지형 기준 점수 + 단위별 평가"로 C2 를 시험할 수 있다.
- 강수 축 메커니즘: 사건별 레이더 강우(HSR), 상류 집수역 강우와 비교.
- Layer 1(침수 발생)과 CDRI(대응 우선순위)의 결과변수 분리, CDRI 는 피해·119 자료로 검증.
- METHODOLOGY 정정: "비보상 집계" → "보상이 제한된 기하 집계", "AUC 는 하한" 삭제, 수치 불일치 정리.

## 6. 연구 무결성

- 2022~2024 흔적은 이미 봤다. 그 뒤 만든 개선안을 같은 자료로 채점한 결과는 post-hoc 이다.
- 창원시는 2022~2025년분만 제공했다. **창원 안에서 봉인할 수 있는 새 자료는 2026년 이후 사상뿐이다.**
  확증은 (a) 다른 도시 흔적을 사전 고정 절차로 한 번 채점하거나, (b) 2026년 이후 사상을 기다린다.
- 봉인 절차: 개선안·평가 규약 문서를 커밋하고 sha256 을 남긴 뒤, 새 자료는 한 사람이 열지 않고 해시만 기록한다.

## 7. 자료 확보 (사람이 할 일)

| 우선 | 자료 | 경로 | 쓰임 |
|---|---|---|---|
| P0 | 다른 도시 침수흔적 | 행안부 재난안전데이터공유플랫폼 API (전국) | 다도시 재현 (C5) |
| P0 | 창원 흔적의 조사 범위·미침수 확인 기록 | 창원시 정보공개 | 음성 오염 평가 |
| P1 | 기상청 레이더 합성(HSR) | apihub.kma.go.kr | 사건 강우 |
| P1 | 창원소방 119 침수 신고·출동 | 정보공개 | 소형 도심 침수 보강, CDRI 검증 |
| P1 | 원본 재배포 가능 여부(공공누리 유형) | 창원시 | 자료 공개 진술 |

## 8. 핵심 참고문헌 (DOI 확인 완료)

- Merz, B. et al. (2024) Invited perspectives: safeguarding the usability and credibility of flood hazard and risk assessments. *NHESS* 24, 4015. doi:10.5194/nhess-24-4015-2024
- Ozturk, U. et al. (2021) How robust are landslide susceptibility estimates? *Landslides* 18, 681. doi:10.1007/s10346-020-01485-5
- Landwehr, T., Dasgupta, A., Waske, B. (2024) Towards robust validation strategies for EO flood maps. *RSE* 315, 114439. doi:10.1016/j.rse.2024.114439
- Schubert, J.E., Mach, K.J., Sanders, B.F. (2024) National-scale flood hazard data unfit for urban risk management. *Earth's Future*. doi:10.1029/2024EF004549
- Ploton, P. et al. (2020) Spatial validation reveals poor predictive performance of large-scale ecological mapping models. *Nat. Commun.* 11, 4540. doi:10.1038/s41467-020-18321-y
- Hirzel, A.H. et al. (2006) Evaluating the ability of habitat suitability models to predict species presences. *Ecol. Model.* 199, 142. doi:10.1016/j.ecolmodel.2006.05.017
- Phillips, S.J. et al. (2009) Sample selection bias and presence-only distribution models. *Ecol. Appl.* 19, 181. doi:10.1890/07-2153.1
- Bekker, J., Davis, J. (2020) Learning from positive and unlabeled data: a survey. *Mach. Learn.* 109, 719. doi:10.1007/s10994-020-05877-5
- Roberts, D.R. et al. (2017) Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure. *Ecography* 40, 913. doi:10.1111/ecog.02881
- Wadoux, A.M.J.-C. et al. (2021) Spatial cross-validation is not the right way to evaluate map accuracy. *Ecol. Model.* 457, 109692. doi:10.1016/j.ecolmodel.2021.109692
- Saisana, M., Saltelli, A., Tarantola, S. (2005) Uncertainty and sensitivity analysis techniques as tools for the quality assessment of composite indicators. *JRSS-A* 168, 307. doi:10.1111/j.1467-985X.2005.00350.x
- Greco, S. et al. (2019) On the methodological framework of composite indices. *Soc. Indic. Res.* 141, 61. doi:10.1007/s11205-017-1832-9
- Rufat, S. et al. (2019) How valid are social vulnerability models? *Ann. AAG* 109, 1131. doi:10.1080/24694452.2018.1535887
- Bakkensen, L.A. et al. (2017) Validating resilience and vulnerability indices in the context of natural disasters. *Risk Anal.* 37, 982. doi:10.1111/risa.12677
- Kapoor, S., Narayanan, A. (2023) Leakage and the reproducibility crisis in machine-learning-based science. *Patterns* 4, 100804. doi:10.1016/j.patter.2023.100804
- 이상혁·강정은 (2018) 도시계획 적용을 위한 도시홍수 취약성 및 리스크 평가. 『국토계획』 53(5), 185. doi:10.17208/jkpa.2018.10.53.5.185
- Lee, S. et al. (2018) Spatial assessment of urban flood susceptibility using data mining and GIS tools. *Sustainability* 10, 648. doi:10.3390/su10030648
- Lee, Y. et al. (2026) Assessing urban flood susceptibility in Seoul using machine learning models. *J. Hydrol.* 674, 135531. doi:10.1016/j.jhydrol.2026.135531
- Han, S., Lee, S. (2026) Bidirectional transferability of flood susceptibility models under regional and event-related dataset shifts. SSRN preprint. doi:10.2139/ssrn.7294469

조사 보고서의 저자 오기 3건을 이 목록에서 바로잡았다: NHESS 2024 제1저자 Merz(Apel 아님),
STOTEN 2024.174135 제1저자 Zhou(Xu 아님), *Water* 16, 2987 제1저자 Kang(Lee 아님).
