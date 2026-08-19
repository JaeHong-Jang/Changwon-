# 문헌 조사 (LITERATURE)

> 프로젝트: 창원시 폭우 침수·하수 역류 우선 대응지역 분석 — 100m 격자 통합위험지수(CDRI) 기반 TOP 20 선정
> 최종 갱신: 2026-08-19 · 총 55편 검증 통과(must 8 / recommended 35 / background 12), 미확인 0건 (1차 매칭 오류 15건은 §4에서 재검증·복귀)
> 서지는 검증 단계의 `corrected_citation`을 그대로 사용했다. 원 목록과 달라진 부분은 각 항목의 "서지 메모"에 적었다.

---

## 0. 한눈에 보기

| 구분 | 편수 | 용도 |
|---|---|---|
| 필독(must) | 8 | 방법론 골격·수식·검증 프로토콜·창원 대조군. 팀원 전원이 읽는다. |
| 권장(recommended) | 35 | 레이어별 변수 선정·수치 근거·인용 문장. 담당 레이어만 읽는다. |
| 배경(background) | 12 | 각주·서론 한 문장용. 초록만 읽는다. |
| 재검증 복귀 | 15 | 1차 매칭 오류분. §4에서 전부 실존 확인 — 국토부 지침·IPCC AR5는 must ⑦⑧로 복귀. |

레이어 약어: **L1** 침수 취약성 / **L2** 하수 역류 위험 / **L3** 취약계층·대응역량 / **IDX** 지수·정규화·가중치·집계 / **VAL** 검증·MAUP / **TXT** 민원 텍스트

---

## 1. 필독 (must) — 이 순서대로 읽기

읽는 순서의 논리: **① 창원의 문제와 대조군을 먼저 잡고 → ② 복합지수를 만드는 국제 표준 절차를 익힌 뒤 → ③ 우리가 쓸 결합·정규화·등급 수식의 원출처를 읽고 → ④ 그 지수가 강건한지 확인하는 검증 프로토콜을 배우고 → ⑤·⑥ L2(하수)의 데이터·모델 설계로 내려간다.** 앞의 4편은 팀 전원 공통, 뒤의 2편은 L2 담당이 먼저 읽고 요약을 공유한다.

### ① 최유라·한우석 (2024) — 창원시 폭우재해 취약지역 [L1 · 대조군]

- **서지**: 최유라, 한우석 (2024). 용도지역별 폭우재해 취약지역의 재해예방형 도시계획 수립방안: 창원시를 중심으로. 국토연구, 제120권(2024.03), pp.77-95. 국토연구원. https://doi.org/10.15793/kspr.2024.120..005
- **왜 필독인가**: 창원시를 직접 다룬 최신 국토연구원 논문. 침수흔적도(2011~2020) ∩ 하천범람지도(100년) 중첩으로 취약지역을 정의하고 현장조사 사례지 5곳을 제시한다. 우리 TOP 20을 이 사례지와 대조하면 '검증' 절이 바로 만들어진다.
- **가져올 것**: (a) 취약지역 정의 절차(과거피해 ∩ 미래피해예상). (b) 표4 수치 — 창원 도시지역 462.14㎢(시 748.81㎢의 61.72%), 침수피해지역 11.03㎢, 하천범람취약 18.34㎢, 중첩 취약지역 0.92㎢(공업 0.48㎢ 52.14%). (c) 사례지: 마산회원구 양덕동(준주거·복개천·해안 인접), 봉암동(하구·만조 시 해수 역류), 의창구 팔용·명서·사화동(창원천 저지대·지하도로), 동읍 덕산리(창원천·남천 합류부), 동읍 용전·남산리. (d) 피해 가중요인 '불투수면·지하차도·복개천·하천변 저지대' → 우리 민감도 변수 선정 근거. (e) 100m 격자 전환 언급 및 격자분석 한계(하천 인접도에 따른 Ⅰ등급 과다, 홍재주 외 2015 재인용) → 하천버퍼 가중치 민감도 분석의 근거.
- **인용 위치**: 1장 배경(창원 침수 현황 수치), 2장 선행연구, 3.2 L1 변수 선정, **5장 검증(TOP 20 vs 사례지 5곳 겹침표)**.
- **담당**: L1 (전원 공통 읽기)

### ② OECD & JRC (2008) — Handbook on Constructing Composite Indicators [IDX · 방법론 골격]

- **서지**: OECD & JRC European Commission (Nardo, M., Saisana, M., Saltelli, A., Tarantola, S., Hoffmann, A., Giovannini, E.) (2008). Handbook on Constructing Composite Indicators: Methodology and User Guide. OECD Publishing, Paris. ISBN 978-92-64-04345-9 (print), 978-92-64-04346-6 (PDF), 162p. https://doi.org/10.1787/9789264043466-en
- **서지 메모**: 원 목록의 oecd.org URL은 403이 나므로 DOI URL을 병기한다.
- **왜 필독인가**: 복합지수 산출 10단계(이론틀→지표선정→결측처리→다변량분석→정규화→가중·집계→불확실성/민감도→원자료 회귀→다른 지표와의 연계→시각화)를 체크리스트로 제공하는 국제 표준. 심사항목 '데이터 분석 적정성'을 방어하는 뼈대.
- **가져올 것**: 10단계 절차를 3장 방법론 흐름도로; min-max 정규화식 x'=(x−min)/(max−min); 가중치 3계열(동일·통계적 PCA/FA·참여형 AHP/BAP) 비교표; 선형 vs 기하 집계와 보상성(compensability) 개념; 7단계 불확실성·민감도 분석.
- **인용 위치**: 3.1 분석 틀(흐름도), 3.5 정규화·가중치·집계, 4.4 민감도.
- **담당**: IDX (전원 공통 읽기, 1~2·5~7단계 중심으로 훑기)

### ③ Balica, Wright & van der Meulen (2012) — Flood Vulnerability Index [IDX · 수식 원출처]

- **서지**: Balica, S.F., Wright, N.G., & van der Meulen, F. (2012). A flood vulnerability index for coastal cities and its use in assessing climate change impacts. Natural Hazards, 64(1), 73-105. https://doi.org/10.1007/s11069-012-0234-1
- **왜 필독인가**: CDRI 0~1 정규화와 5등급 해석의 원출처. 결합식·정규화식·무가중 원칙을 원문 수식으로 인용해야 한다.
- **가져올 것**: FVI = (E×S)/R (Eq.2, 회복력은 분모 → 펌프장·대피소 접근성의 위치); NV_i = RV_i / max(RV_i) (Eq.1); 'without weighting' 원칙(우리 동일가중 시나리오 근거); 지표 상관 중복 경고(상관행렬 점검 근거).
- **주의**: 5등급 해석표(<0.01 very small / 0.01–0.25 small / 0.25–0.5 vulnerable / 0.5–0.75 high / 0.75–1 very high)는 Nat Hazards 본문이 아니라 Balica(2012) UNESCO-IHE 박사학위논문(CRC Press, ISBN 9780415641579)에 있고 Karmaoui·Balica·Messouli(2016, NHESS discussion, Table 4)에 재수록되어 있다. **보고서에는 등급표 출처를 학위논문으로 정확히 적을 것.**
- **인용 위치**: 3.5 지수 결합·정규화, 4.1 등급 지도(5등급 범례 각주).
- **담당**: IDX

### ④ Moreira, de Brito & Kobiyama (2021, Water) — 정규화·집계·등급화 방법의 영향 [IDX · 검증 프로토콜]

- **서지**: Moreira, L.L., de Brito, M.M., Kobiyama, M. (2021). Effects of Different Normalization, Aggregation, and Classification Methods on the Construction of Flood Vulnerability Indexes. Water 13(1), 98. https://doi.org/10.3390/w13010098
- **왜 필독인가**: 우리가 하려는 것(정규화·집계·등급화 대안을 바꿔 Spearman·순위이동으로 강건성 확인)을 홍수취약성지수에 그대로 수행했다. 6주 안에 따라 할 수 있는 프로토콜과 Jenks natural breaks 최적 근거(AIC)를 준다.
- **가져올 것**: 비교 설계(정규화 4 × 집계 2 × 등급화 4), 강건성 지표(Spearman, 순위 이동, 공간분포 비교), 결과 문장 — '정규화 단계는 민감도가 낮음', '기하평균 집계는 취약성을 과소평가하는 경향', '등급화 선택은 결과를 매우 민감하게 함 → natural breaks 최적'.
- **인용 위치**: 3.5(방법 선택 근거), **4.4 민감도(동일 지표 사용)**, 4.1 등급화(Jenks vs Balica 두 안 병기 + kappa).
- **담당**: IDX

### ⑤ Bersabe & Jun (2025) — 서울 도시침수 취약성 ML 지도 + 배수시설 변수 [L2 · L1-L2 통합 근거]

- **서지**: Bersabe, J. T., & Jun, B.-W. (2025). The Machine Learning-Based Mapping of Urban Pluvial Flood Susceptibility in Seoul Integrating Flood Conditioning Factors and Drainage-Related Data. ISPRS International Journal of Geo-Information, 14(2), 57. https://doi.org/10.3390/ijgi14020057
- **왜 필독인가**: 서울 침수지점(2010~2022)을 타깃으로 16개 인자 + 하수관로밀도(SPD)·빗물받이 거리(DSD)를 넣어 LR/RF/SVM을 비교. '하수도 변수를 침수 모델에 넣으면 성능이 오른다'를 국내 도시에서 정량 입증 → 침수(L1)와 하수(L2)를 하나의 위험지수로 합치는 근거.
- **가져올 것**: RF 최우수(정확도 0.837, AUC 0.902); 배수 변수 2개 추가로 정확도 +7.58%p, AUC +3.80%p; 인용문 'recognizing drainage systems as key flood-conditioning factors is vital'; L2 변수 '관로밀도(km/km²)' 채택 근거; 검증지표 AUC·정확도.
- **인용 위치**: 1장(왜 L1+L2인가), 3.3 L2 변수, 5장 검증(AUC 비교 기준).
- **담당**: L2

### ⑥ Fontecha et al. (2021) — 하수관망 고장위험 2단계 시공간 ML [L2 · Plan A 프레임]

- **서지**: Fontecha, J. E., Agarwal, P., Torres, M. N., Mukherjee, S., Walteros, J. L., & Rodríguez, J. P. (2021). A Two-Stage Data-Driven Spatiotemporal Analysis to Predict Failure Risk of Urban Sewer Systems Leveraging Machine Learning Algorithms. Risk Analysis, 41(12), 2356-2391. https://doi.org/10.1111/risa.13742
- **왜 필독인가**: 보고타 하수관망 고장(민원성 사고) 자료로 로지스틱·DT·RF·XGBoost를 비교하고 격자×기간 단위 고장위험을 예측. Plan A(관로속성+강우 → XGBoost, 타깃=민원)와 구조가 거의 같고, 결측·불균형·우편향 처리 프레임을 제시한다.
- **가져올 것**: 고장 건수의 우편향·희소성 → 2단계(발생 여부 분류 → 강도); 격자 크기별 성능 비교(적정 해상도 논의 → 100m 격자 vs 동 단위 정당화); 임계값별 성능 검토; 결측·이상치·불균형 대처 명시.
- **인용 위치**: 3.3 L2 모델 설계('Fontecha et al.(2021)의 2단계 프레임을 단순화하여 적용'), 6장 한계.
- **담당**: L2 (유료 논문 — 학교 도서관 접근 필요; 실패 시 초록·Crossref로 프레임만 인용)

> must 편수 조정 메모: 원안 must 6편 + §4-1 준거 문서 2편(국토부 지침·IPCC AR5) = 8편(상한). 강정은·이명진(2012)과 Cutter et al.(2003)은 must에 준하는 중요도지만 각각 VAL·L3 담당만 읽으면 충분하므로 recommended에 두었다.

---

## 2. 권장 (recommended) — 레이어별

### L1 침수 취약성

| 서지 | URL | 한 줄 takeaway |
|---|---|---|
| 홍재주, 임호종, 함영한, 이병재 (2015). 격자단위 분석기법을 적용한 도시 기후변화 재해취약성분석. 공간정보연구(Spatial Information Research), 23(6), pp.67-75. | https://doi.org/10.12672/ksis.2015.23.6.067 | 집계구→격자 전환의 원류. '집계구보다 세부적 결과' 장점과 '하천 인접 Ⅰ등급 과다' 한계 → 격자 선택·하천버퍼 민감도 근거. (서지 메모: 학술지명은 KCI 표기 '공간정보연구'로 쓴다.) |
| 노윤진, 윤형미, 한학 (2025). 서울시 도시 침수 위험 잠재성의 공간 특성: 극한 강우와 불투수면의 영향. 한국도시지리학회지 28(3), pp.81-91. | https://doi.org/10.21189/JKUGS.28.3.6 | 관측소 시간강수 95퍼센타일을 격자 보간 × 불투수면 → 표준화 지수 → Gi* 핫스팟. 우리 L1과 가장 닮은 최신 벤치마크; 극한강우 지표=95퍼센타일 채택 검토, Gi* 보조지도. |
| 신상영, 박창열 (2014). 토지이용 특성과 침수피해면적 간의 관계 분석: 서울시를 사례로. 국토연구 제81권, pp.3-20. | https://doi.org/10.15793/kspr.2014.81..001 | 239개 배수분구 회귀: '최대 시간강우강도가 일관되게 가장 큰 영향', 완경사·주상혼재가 취약 → 기후노출(시간최대강우)·경사 부호 방향 근거, 배수구역 SHP 연계 아이디어. |
| Khosravi, K., Shahabi, H., Pham, B.T., Adamowski, J., Shirzadi, A., Pradhan, B., Dou, J., Ly, H.-B., Gróf, G., Ho, H.L., Hong, H., Chapi, K., Prakash, I. (2019). A comparative assessment of flood susceptibility modeling using Multi-Criteria Decision-Making Analysis and Machine Learning Methods. Journal of Hydrology 573, pp.311-323. | https://doi.org/10.1016/j.jhydrol.2019.03.073 | MCDM(SAW·VIKOR·TOPSIS) vs ML(NB·NBT) 비교; ML이 예측력 우위, SAW·VIKOR>TOPSIS → '지수(SAW형)=해석성, ML=예측력' 트레이드오프 문장, L1 가중합과 ML 결과의 Spearman 상호검증. |

### L2 하수 역류 위험

| 서지 | URL | 한 줄 takeaway |
|---|---|---|
| Malek Mohammadi, M., Najafi, M., Kermanshachi, S., Kaushal, V., & Serajiantehrani, R. (2020). Factors Influencing the Condition of Sewer Pipes: State-of-the-Art Review. Journal of Pipeline Systems Engineering and Practice, 11(4), 03120002. | https://doi.org/10.1061/(ASCE)PS.1949-1204.0000483 | 물리(age, diameter, material, depth, length, slope)·환경·운영 인자 정리; '가장 유의한 인자는 age, material, diameter, length, watertable' → Plan A/B 입력변수표. |
| Hawari, A., Alkadour, F., Elmasry, M., & Zayed, T. (2020). A state of the art review on condition assessment models developed for sewer pipelines. Engineering Applications of Artificial Intelligence, 93, 103721. | https://doi.org/10.1016/j.engappai.2020.103721 | 상태평가 모델 3분류(physical/statistical/AI); '환경·운영 인자를 입력으로 쓴 연구가 드묾' → 강우를 관로속성과 함께 넣는 것이 차별점. |
| 강병준, 유순유, 박규홍 (2020). 와이블 분포함수를 이용한 하수관로 노후도 추정. 상하수도학회지 34(4), 251-258. | https://doi.org/10.11001/jksww.2020.34.4.251 | 국내 CCTV 자료로 경과연수→중대결함(CS3) 확률 Weibull CDF; 50% 초과 11~16년, 90% 초과 27~30년 → Plan B의 P_defect(age)=1−exp[−(age/η)^β] 파라미터 범위. (자매: 강병준 외 2023 마르코프, 대한토목학회논문집 43(4)) |
| Okwori, E., Viklander, M., & Hedström, A. (2021). Spatial heterogeneity assessment of factors affecting sewer pipe blockages and predictions. Water Research, 194, 116934. | https://doi.org/10.1016/j.watres.2021.116934 | 막힘의 공간 군집(K-function)→GWPR→RF 재발예측; 유의 인자 재질·연결수·자정유속·처짐; RF 정확도 60~80% → 민원 핫스팟 분석 근거, 성능 기대치. |
| Mo Wang, Yingxin Li, Haojun Yuan, Shiqi Zhou, Yuankai Wang, Rana Muhammad Adnan Ikram, Jianjun Li (2023). An XGBoost-SHAP approach to quantifying morphological impact on urban flooding susceptibility. Ecological Indicators, 156, 111137. | https://doi.org/10.1016/j.ecolind.2023.111137 | XGBoost→SHAP summary/dependence/PDP로 침수취약성 인자 정량화 → Plan A 결과 제시 형식(SHAP 순위표 + dependence plot + TOP20 waterfall). |
| Scott M. Lundberg 외 (2020). From local explanations to global understanding with explainable AI for trees. Nature Machine Intelligence, 2(1), 56-67. | https://doi.org/10.1038/s42256-019-0138-9 | TreeExplainer 원저; 지역 SHAP의 가산성(additivity)이 격자별 기여도 분해의 수학적 정당성. XGBoost 원저(Chen & Guestrin 2016, doi 10.1145/2939672.2939785)와 함께 각주. |

### L3 취약계층·대응역량

| 서지 | URL | 한 줄 takeaway |
|---|---|---|
| Cutter, S.L., Boruff, B.J., Shirley, W.L. (2003). Social Vulnerability to Environmental Hazards. Social Science Quarterly 84(2):242-261. | https://doi.org/10.1111/1540-6237.8402002 | SoVI 원전; 연령·1인가구·주택유형·의료접근성 등 취약요인 → L3 변수(고령·1인가구·노후건물·지하층) 매핑표; 요인분석은 100m 격자에 부적합 → 직접 정규화·가중합(deductive) 채택 이유. |
| 김강민, 황태건, 이유빈, 황철수 (2024). 자연재해에 대한 사회적 취약성 평가. 대한지리학회지 59(1):73-90. | https://doi.org/10.22776/kgs.2024.59.1.73 | 국내 SoVI(PCA) 변수군·결과('사회경제 요소 영향 큼') → L3 변수 대응표, 실업률·수급자 격자통계 부재를 한계로 기술. (후속 GWPCA: 대한공간정보학회지 32(3), doi 10.7319/kogsis.2024.32.3.003) |
| 박재국, 김동문 (2012). 네트워크 분석을 이용한 보행속도에 따른 대피소 서비스 영역 분석. 대한공간정보학회지 20(4):37-44. | https://doi.org/10.7319/kogsis.2012.20.4.037 | 보행속도 1.0/1.3/2.0 m/s × 5분 → 300/390/600m 서비스 영역; '노약자 미도달 취약지역이 2배 이상' → 대피소 접근성 지표 임계값(고령자 300m). |
| 박현수, 권설아 (2022). 재난 대피 시설의 공간적 분포와 접근성에 관한 연구: 청주시를 중심으로. 한국방재학회논문집 22(5):161-170. | https://doi.org/10.9798/KOSHAM.2022.22.5.161 | 회귀: 노인비율·노후건물 많을수록 대피시설이 멂 → '취약계층 밀집 + 대피 접근성 열악' 결합 논리, 읍면부(동읍·북면) 해석. |

### 지수·정규화·가중치·집계 (IDX)

| 서지 | URL | 한 줄 takeaway |
|---|---|---|
| Nasiri, H., Mohd Yusof, M.J., Mohammad Ali, T.A. (2016). An overview to flood vulnerability assessment methods. Sustainable Water Resources Management 2(3), pp.331-336. | https://doi.org/10.1007/s40899-016-0051-x | 평가법 4범주(피해곡선·손실자료·컴퓨터모델·지표기반); '지표기반이 종합취약성 파악에 더 정밀' → 수리모형(SWMM) 부재 조건에서 지표기반 선택 근거 + 한계(침수심 미산정). |
| 유인상, 김형규, 박진택, 정휘철 (2025). 공통사회경제경로 기후변화 시나리오 기반 고해상도 홍수 리스크 평가. 한국기후변화학회지 16(1):25-42. | https://doi.org/10.15531/KSCCR.2025.16.1.025 | IPCC AR5 H/E/V를 AHP(0.35/0.34/0.31)로 결합, 취약성에 '노후 하수관 비율(0.17)' 포함, 30~100m 격자 → 우리 AHP 초기 비교행렬 참고값, 노후관=취약성 지표 선례. |
| Saisana, M., Saltelli, A., Tarantola, S. (2005). Uncertainty and sensitivity analysis techniques as tools for the quality assessment of composite indicators. JRSS Series A 168(2):307-323. | https://doi.org/10.1111/j.1467-985X.2005.00350.x | 가중치·정규화·집계 가정을 흔들어 순위 분포·|ΔR|로 강건성 평가하는 표준 절차 → 우리 12개 시나리오(가중 3×정규화 2×집계 2) 순위 중앙값·범위 표. |
| Ziarh, G.F. 외 (2024). Identifying the Contributing Sources of Uncertainties in Urban Flood Vulnerability in South Korea… Sustainability 16(8):3450. | https://doi.org/10.3390/su16083450 | 한국 33개 도시: 순위 불확실성 기여 '가중치 58%, MCDM 27%, 상호작용 15%' → 가중치 3안 병렬 산출의 필요성을 한 수치로. |
| Choi, H.I. (2019). Assessment of Aggregation Frameworks for Composite Indicators in Measuring Flood Vulnerability to Climate Change. Scientific Reports 9:19371. | https://doi.org/10.1038/s41598-019-55994-y | 6가지 집계틀 비교, 승법(곱) 집계 권고 → CDRI=H×E×V 본안 근거, 가중합 대안과 Spearman·TOP20 겹침 비교, 0값 처리(+ε) 명시. |
| Moreira, L.L., de Brito, M.M., Kobiyama, M. (2021). Review article: A systematic review and future prospects of flood vulnerability indices. NHESS 21(5):1513-1530. | https://doi.org/10.5194/nhess-21-1513-2021 | 95편 리뷰: min-max 30.5%, 동일가중 24.2%, 선형집계 80.0%; '민감도 9.5%, 불확실성 3.2%, 검증 13.7%에 그침' → 차별화 문장 및 대응역량 지표(대피소·펌프장) 포함 이유. |

### 검증·MAUP (VAL)

| 서지 | URL | 한 줄 takeaway |
|---|---|---|
| 강정은, 이명진 (2012). 퍼지모형과 GIS를 활용한 기후변화 홍수취약성 평가 - 서울시 사례를 중심으로. 한국지리정보학회지 15(3):119-136. | https://doi.org/10.11108/kagis.2012.15.3.119 | 격자 GIS 취약성 지도를 2010 침수로 학습·2011로 검증, AUC 84.37%; 변수 목록이 우리 L1과 거의 동일 → ROC-AUC 검증 절차의 국내 선례, 목표치 0.75~0.85. |
| 서정석, 한우석 (2019). 침수 취약지역과 사회적 취약계층의 공간적 상관성 분석: 제주특별자치도 사례를 중심으로. 한국방재학회논문집 19(4), pp.103-113. | https://doi.org/10.9798/KOSHAM.2019.19.4.103 | 침수흔적도×고령·저소득 핫스팟·상관 → '취약계층이 침수위험지에 더 산다' 문장 인용처, TOP20에서 고령·1인가구 vs 침수흔적 Spearman. |
| Lee, S., Kim, J.-C., Jung, H.-S., Lee, M.J., Lee, S. (2017). Spatial prediction of flood susceptibility using random-forest and boosted-tree models in Seoul metropolitan city, Korea. Geomatics, Natural Hazards and Risk 8(2), pp.1185-1203. | https://doi.org/10.1080/19475705.2017.1308971 | 2010 학습/2011 검증 시간분할, RF 78.78~79.18%; 중요도 상위 하천거리·지질·DEM → 연도 분할 검증 설계, 하천버퍼·표고 우선순위 근거. |
| Fekete, A. (2009). Validation of a social vulnerability index in context to river-floods in Germany. NHESS 9(2):393-403. | https://doi.org/10.5194/nhess-9-393-2009 | 사회취약성 지수를 독립 피해가구 설문으로 검증 → L3 지수 vs 민원·피해이력 외부검증 접근의 국제 선례. |
| Hinojos, S., McPhillips, L., Stempel, P., Grady, C. (2023). Social and environmental vulnerability to flooding: Investigating cross-scale hypotheses. Applied Geography 157:103017. | https://doi.org/10.1016/j.apgeog.2023.103017 | 집계 단위가 커질수록 고취약 인구 과소집계(MAUP) → 100m 격자 정당화, 250m·500m·행정동 재집계 민감도 절. |

### 민원 텍스트 (TXT)

| 서지 | URL | 한 줄 takeaway |
|---|---|---|
| Agonafir, C., Lakhankar, T., Khanbilvardi, R., Krakauer, N., Radell, D., & Devineni, N. (2022). A machine learning approach to evaluate the spatial variability of New York City's 311 street flooding complaints. Computers, Environment and Urban Systems, 97, 101854. | https://doi.org/10.1016/j.compenvurbsys.2022.101854 | 311 민원을 RF 회귀 종속변수로; 'catch basin clogged' 민원이 도로침수 최대 예측변수 → 민원=하수역류 대리변수, '막힘/역류' 유형 별도 변수화. |
| Agonafir, C., Pabon, A. R., Lakhankar, T., Khanbilvardi, R., & Devineni, N. (2022). Understanding New York City street flooding through 311 complaints. Journal of Hydrology, 605, 127300. | https://doi.org/10.1016/j.jhydrol.2021.127300 | 민원은 강우·지형·배수망과 결합 해석, 신고성향·인구 편향 → 격자 인구로 정규화(민원률) 한계 절. 세부 수치 인용은 피하고 방법론적 선례로만. |
| Fabrizio Gilardi, Meysam Alizadeh, Maël Kubli (2023). ChatGPT outperforms crowd workers for text-annotation tasks. PNAS, 120(30), e2305016120. | https://doi.org/10.1073/pnas.2305016120 | zero-shot LLM 주석 정확도가 크라우드워커보다 ~25%p 높음 → 민원 LLM 구조화 정당화 + 표본 100~200건 수작업 대조로 정확도·Cohen's κ 보고. (공공민원 후속: Rakhimzhanov et al. 2025, Information 16(8):644) |

---

## 3. 배경 (background) — 각주·서론 한 문장용

| 서지 | URL | 용도 |
|---|---|---|
| Rehman, S., Sahana, M., Hong, H., Sajjad, H., Ahmed, B.B. (2019). A systematic review on approaches and methods used for flood vulnerability assessment: framework for future research. Natural Hazards 96(2), pp.975-998. | https://doi.org/10.1007/s11069-018-03567-z | 서론: 지표기반→GIS/ML 결합이 국제 흐름과 일치. |
| Jenks, G. F. (1967). The Data Model Concept in Statistical Mapping. International Yearbook of Cartography, 7, 186-190. | https://scirp.org/reference/referencespapers?referenceid=3297697 | Jenks I~IV 등급화 각주(mapclassify.NaturalBreaks). DOI 없음, 원문 입수 불필요. |
| 「하수도법」 제4조의3(하수도정비중점관리지역의 지정 등) [본조신설 2012.2.1., 개정 2016.1.27., 2025.10.1.]; 「하수도법 시행규칙」 제1조의3(지정기준 및 절차 등). 현행: 법률 제21065호(2025.10.1. 시행, 소관 기후에너지환경부). 국가법령정보센터. | https://www.law.go.kr/법령/하수도법/제4조의3 | 6장 정책제언: TOP20을 중점관리지역 지정 요청 근거자료로. 저자를 '국회/환경부'로 쓰지 말고 법령명·조문·시행일로 인용; 제출 전 현행 조문(장관 명칭 변경) 재확인. |
| Laakso, T., Kokkonen, T., Mellin, I., Vahala, R. (2018). Sewer Condition Prediction and Analysis of Explanatory Factors. Water 10(9), 1239. | https://doi.org/10.3390/w10091239 | RF+Boruta+PDP; 'CCTV 검사 대상 선별' 활용 문장 → TOP20=정밀조사 우선 대상. |
| Park, J.H., Kang, J., Kang, J., Mun, D. (2022). Machine-learning-based ground sink susceptibility evaluation using underground pipeline data in Korean urban area. Scientific Reports 12, 20911. | https://doi.org/10.1038/s41598-022-25237-8 | 국내: 관로 노후도 최상위 인자, GB≈RF → 노후관로=지반침하 동반 위험 한 줄, GB 계열 채택 근거. |
| Tate, E. (2012). Social vulnerability indices: a comparative assessment using uncertainty and sensitivity analysis. Natural Hazards 63(2):325-347. | https://doi.org/10.1007/s11069-012-0152-2 | 우리 CDRI를 '계층형(hierarchical) 설계'로 명명, 계층형이 가장 정확하다는 근거. |
| Saaty, T.L. (1990). How to make a decision: The analytic hierarchy process. European Journal of Operational Research 48(1):9-26. | https://doi.org/10.1016/0377-2217(90)90057-I | AHP 1~9 척도, CR<0.1 기준 각주. |

---

## 4. 추가 검증 복귀 목록 (2026-08-19 재검증 완료)

> 1차 합성 시 서지 매칭 오류로 "미확인" 처리됐던 15건을 개별 검증 로그(DOI 리졸브·KCI·law.go.kr·ipcc.ch 원문)로 재확인한 결과 **15건 전부 실존**. 아래 서지는 검증된 표기 그대로 인용 가능. 두 준거 문서(★)는 **must**로 복귀한다.

### 4-1. must 복귀 (방법 준거)

| # | 서지 | URL | 가져올 것 |
|---|---|---|---|
| ★⑦ | 국토교통부 (2024). 도시 기후변화 재해취약성분석 및 활용에 관한 지침 [국토교통부훈령 제1704호, 2024.1.19. 일부개정, 시행 2024.7.20.]. 국가법령정보센터 행정규칙. | https://www.law.go.kr/행정규칙/도시기후변화재해취약성분석및활용에관한지침 | 취약성=기후노출×도시민감도, 100m 격자, 표준화→합산→Jenks I~IV 매트릭스, 폭우 재해 지표 목록(별표). 3.1·3.2의 "창원시 실무와 동일 표준" 근거. |
| ★⑧ | IPCC (2014). Summary for Policymakers. In: Climate Change 2014: Impacts, Adaptation, and Vulnerability. Part A. Contribution of WGII to AR5 [Field, C.B. et al. (eds.)]. Cambridge University Press, pp. 1-32. | https://www.ipcc.ch/site/assets/uploads/2018/02/ar5_wgII_spm_en.pdf | Risk = Hazard × Exposure × Vulnerability 프레임(SPM Fig. SPM.1). CDRI 수식의 원출처. 챕터 인용 필요 시 Oppenheimer et al. (2014) Ch.19 pp.1039-1099, DOI 10.1017/CBO9781107415379.024 |

### 4-2. recommended 복귀

| 서지 | URL | 레이어 · takeaway |
|---|---|---|
| 박기용, 정진호, 전원식 (2017). 창원시 용도지역별 침수 피해에 따른 위험등급화 분석. 한국산학기술학회논문지 18(4), 685-693. | https://doi.org/10.5762/KAIS.2017.18.4.685 | L1 · 창원 직접 사례(용도지역별 침수 위험등급) → 1장 배경·2장 선행연구·5장 대조 |
| 이선미, 최영제, 이재응 (2020). 엔트로피 가중치 산정방법을 활용한 도시지역 홍수취약성 평가. 한국방재학회논문집 20(6), 389-397. | https://doi.org/10.9798/KOSHAM.2020.20.6.389 | IDX · 엔트로피 가중치 수식·국내 적용 사례 → 3.5 가중치 2안 근거 |
| 이상혁, 강정은 (2018). 도시계획 적용을 위한 도시홍수 취약성 및 리스크 평가. 국토계획 53(5), 185-206. | https://doi.org/10.17208/jkpa.2018.10.53.5.185 | IDX · 취약성→리스크 전환, 도시계획 적용 프레임 → 3.1·6장 |
| 손주영, 이재현, 오재일 (2017). 위험도 기반의 하수관로 CCTV 조사 우선순위 결정 연구. 대한토목학회논문집 37(3), 585-592. | https://doi.org/10.12652/Ksce.2017.37.3.0585 | L2 · "위험도 → CCTV 조사 우선순위" 국내 선례 → TOP 20 = 정밀조사 우선 대상 논리(6장) |
| 이재현, 박기홍, 전창현, 오재일 (2021). 도시 소유역 내 내수침수 위험도 평가: 강우 시간분포 및 이중배수체계 모형을 중심으로. 상하수도학회지 35(6), 389-403. | https://doi.org/10.11001/jksww.2021.35.6.389 | L2 · 내수침수(하수 통수능)와 강우 시간분포 관계 → L1-L2 결합 근거 |
| 이은석 (2020). 건축물 정보를 활용한 도시침수 취약성 진단방법 개발. 한국기후변화학회지 11(1), 65-75. | https://doi.org/10.15531/KSCCR.2020.11.1.65 | L3 · 건축물 빅데이터(노후·지하층)로 침수 취약성 진단 → 건축HUB/건물통합정보 변수 근거 |
| 박종영, 이정식, 이진덕, 이원우 (2018). 폭우 취약성 지표를 활용한 재해취약지구 분석. 한국지리정보학회지 21(1), 12-22. | https://doi.org/10.11108/kagis.2018.21.1.012 | L1 · 폭우 취약성 지표 구성 사례 |
| 황석환, 함대헌 (2013). 공간 강수량 정확도 향상을 위한 공간상세화 방법 평가. 한국방재학회논문집 13(4), 149-163. | https://doi.org/10.9798/KOSHAM.2013.13.4.149 | L1 · 강수 공간보간(IDW 등) 방법 비교 → IDW 선택·LOOCV 근거 |
| 김현종, 이태헌, 유승의, 김나랑 (2018). 민원 분석을 위한 텍스트 마이닝 기법 연구: 계층적 연관성 분석. 한국산업정보학회논문지 23(3), 13-24. | https://doi.org/10.9723/jksiis.2018.23.3.013 | TXT · 국내 민원 텍스트 분석 선례 → LLM 구조화의 국내 맥락 |

### 4-3. background 복귀

| 서지 | URL | 용도 |
|---|---|---|
| Oppenheimer, M. et al. (2014). Emergent risks and key vulnerabilities. In: IPCC AR5 WGII Part A, Ch.19, pp.1039-1099. | https://www.ipcc.ch/site/assets/uploads/2018/02/WGIIAR5-Chap19_FINAL.pdf | 위험 프레임 챕터 인용 |
| 한우석 외 (2024). 도시 재해대응력 강화를 위한 도시 재해취약성 분석 등 도시계획제도 개선 연구. 국토교통부 수탁, 국토연구원 (NKIS 1613000-202300106). | https://www.nkis.re.kr/prism_api_info_view.do?researchId=1613000-202300106&otpSeq=0&popup=P | 지침 2024 개정(100m 격자) 배경 |
| 김대호, 김영오, 지희원, 강태호 (2020). 전국 단위 홍수위험도 평가를 위한 지수 개발과 미래 전망. 한국수자원학회논문집 53(5), 323-336. | https://doi.org/10.3741/JKWRA.2020.53.5.323 | 국내 홍수위험지수 설계 사례 |
| 환경부 (2022). KDS 61 10 00:2022 하수도설계 일반사항 (하수도설계기준, 환경부고시 제2022-270호, 2022.12.28.). | https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000217142 | 하수관로 설계강우 빈도(10~30년) 각주 → 확률강우량 초과비율 해석 |

> 컨텍스트에 있으나 이번 검증 목록에 없던 문헌(음정인·김형규 2024 서울 반지하 홍수취약성; 환경부 2025 하수관로·맨홀 상태등급 표준매뉴얼; 2022 창원 공모전 우수상 LGBM 침수예측)은 **원문 확인 후 인용** 원칙 유지.

---

## 5. 보고서 인용 매핑

| 장·절 | 문장(초안) | 인용 문헌 |
|---|---|---|
| 1장 서론 — 배경 | 창원시 도시지역 462.14㎢ 중 침수피해지역 11.03㎢, 하천범람취약 18.34㎢; 양덕동·봉암동 등은 하수관거 확충에도 반복 침수·해수 역류. | 최유라·한우석(2024) |
| 1장 — 문제 정의 | 배수(하수)시설은 도시침수의 핵심 조건 인자이며 이를 모델에 넣으면 정확도가 유의하게 오른다. | Bersabe & Jun(2025) |
| 1장 — 왜 격자인가 | 집계 단위가 커지면 고취약 인구를 과소집계하므로 100m 격자를 채택. | Hinojos et al.(2023), 홍재주 외(2015) |
| 2장 선행연구 — 국제 흐름 | 지표기반 취약성 + ML + GIS 결합이 최근 흐름. | Rehman et al.(2019), Nasiri et al.(2016) |
| 2장 — 관행과 공백 | 선행 FVI 95편 중 민감도 9.5%, 검증 13.7%에 그침. | Moreira et al.(2021, NHESS) |
| 2장 — 창원·국내 선행 | 창원 취약지역 정의(침수흔적∩범람), 서울 강우×불투수 지수, 서울 격자 취약성 AUC 84.37%. | 최유라·한우석(2024), 노윤진 외(2025), 강정은·이명진(2012) |
| 3.1 분석 틀 | 복합지수 10단계 절차; Risk=H×E×V(승법 집계); 계층형 설계. | OECD/JRC(2008), Choi(2019), Tate(2012), IPCC(2014) SPM, 국토교통부(2024) 지침 |
| 3.2 L1 변수 | 기후노출=시간최대강우/95퍼센타일; 민감도=저지대·경사·불투수·하천버퍼; 최대 강우강도·완경사·불투수가 침수 설명. | 신상영·박창열(2014), 노윤진 외(2025), 강정은·이명진(2012), 최유라·한우석(2024) |
| 3.3 L2 변수·모델 | 관로 age·material·diameter·length가 상태의 핵심 인자; 관로밀도 채택; 경과연수→결함확률 Weibull; 2단계 시공간 프레임; XGBoost+SHAP. | Malek Mohammadi et al.(2020), Bersabe & Jun(2025), 강병준 외(2020), Fontecha et al.(2021), Wang et al.(2023), Lundberg et al.(2020) |
| 3.3 L2 — 민원 활용 | 민원=역류·막힘의 관측 가능한 대리변수; 신고 편향은 인구로 정규화; LLM 구조화 + 표본 대조 κ. | Agonafir et al.(2022a, 2022b), Gilardi et al.(2023), Okwori et al.(2021) |
| 3.4 L3 변수 | 고령·1인가구·노후건물·지하층=사회취약 요인; 대피소 접근성 300m(고령자 5분); 노인·노후건물 많을수록 대피시설이 멂. | Cutter et al.(2003), 김강민 외(2024), 박재국·김동문(2012), 박현수·권설아(2022) |
| 3.5 정규화·가중·집계 | min-max 0~1; 무가중 기본형; 가중치 3안(동일·엔트로피·AHP, CR<0.1); 승법 집계; 5등급/Jenks. | Balica et al.(2012), OECD/JRC(2008), Saaty(1990), Choi(2019), Jenks(1967), 유인상 외(2025) |
| 3.6 검증 설계 | 연도 분할 AUC; 외부자료(침수흔적·민원) 검증; MCDA-ML 상호검증. | Lee et al.(2017), 강정은·이명진(2012), Fekete(2009), Khosravi et al.(2019) |
| 4.1 CDRI 지도·등급 | 5등급 범례(학위논문 출처 명기), Jenks 4등급 병기. | Balica(2012 학위논문 via Karmaoui et al. 2016), Moreira et al.(2021, Water) |
| 4.2 TOP 20·기여도 | SHAP 가산성으로 격자별 기여도 분해. | Lundberg et al.(2020), Wang et al.(2023) |
| 4.4 민감도 | 가중치가 순위 불확실성의 58%; 12개 시나리오 Spearman·순위이동·TOP20 겹침; MAUP 재집계. | Ziarh et al.(2024), Saisana et al.(2005), Moreira et al.(2021, Water), Hinojos et al.(2023) |
| 5장 검증·논의 | TOP20 vs 창원 사례지 5곳 대조; 취약계층-침수 양의 상관; 예측 정확도 60~80% 현실적 상한. | 최유라·한우석(2024), 서정석·한우석(2019), Okwori et al.(2021) |
| 6장 정책 제언 | 하수도정비 중점관리지역 지정 요청 근거자료; TOP20=CCTV 정밀조사 우선 대상; 노후관로=지반침하 동반. | 하수도법 제4조의3·시행규칙 제1조의3, Laakso et al.(2018), Park et al.(2022) |
| 6장 한계 | 지표기반은 침수심 미산정; 민원 편향; 환경·운영 인자 결합 연구 부족; AHP 응답자 수 부족. | Nasiri et al.(2016), Agonafir et al.(2022b), Hawari et al.(2020), Saaty(1990) |

---

## 6. 선행연구 대비 공백 — 차별화 문장 초안

1. 창원시를 다룬 기존 연구(최유라·한우석, 2024)는 침수흔적도와 하천범람지도의 중첩으로 취약지역을 용도지역 단위에서 정의했으나, 하수관로 노후·역류 위험과 취약계층 분포를 결합하지 않았다. 본 연구는 100m 격자에서 침수(L1)·하수역류(L2)·취약계층(L3)을 IPCC AR5 위험 프레임(H×E×V)으로 통합한 첫 창원 사례다.
2. 국내외 도시침수 ML 연구(Bersabe & Jun, 2025; Lee et al., 2017)는 하수관로밀도 등 배수 변수를 침수 예측에 넣어 성능 향상을 보였지만, 관로 경과연수·재질·관경과 강우를 결합해 '역류 민원'을 타깃으로 학습하고 SHAP로 격자별 기여도를 분해한 사례는 드물다(Hawari et al., 2020의 '환경·운영 인자 결합 연구 부족' 지적).
3. 홍수취약성지수 95편 중 민감도 분석은 9.5%, 외부 검증은 13.7%에 그친다(Moreira et al., 2021). 본 연구는 가중치 3안(동일·엔트로피·AHP) × 정규화·집계 대안의 Spearman·순위이동과, 침수흔적도·민원 이력을 이용한 ROC-AUC 외부 검증을 모두 수행한다.
4. 민원 원문을 LLM으로 위치·유형·긴급도로 구조화해 '막힘/역류' 유형 민원률을 하수역류 위험의 대리변수로 격자에 결합한 것은 311 민원 연구(Agonafir et al., 2022)를 국내 지자체 민원 체계에 확장한 시도이며, 표본 수작업 대조(κ)로 신뢰도를 보고한다.
5. 결과물인 TOP 20 격자를 「하수도법」 제4조의3 하수도정비중점관리지역 지정 요청의 근거자료 및 CCTV 정밀조사 우선순위(Laakso et al., 2018)로 연결해, 분석이 곧바로 창원시 정책 절차에 접속되도록 설계했다.
