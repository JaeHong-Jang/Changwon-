# 창원시 CDRI 분석 방법론 설계서 (최종, 2026-08-19)

> 목적: G002~G010을 팀원이 그대로 구현할 수 있는 규격. 근거 표준: 국토부 「도시 기후변화 재해취약성분석 지침」(2024.1 개정: 100m 격자, 취약성=기후노출×도시민감도, z-score 표준화 → 합산 → Jenks 자연구분 I~IV 매트릭스), IPCC AR5 Risk=Hazard×Exposure×Vulnerability, Balica(2012) FVI 5등급, OECD/JRC(2008) 복합지수 10단계(이론틀→데이터→결측→다변량→정규화→가중·집계→민감도→시각화). 노트북: 01 수집·검증 / 02 EDA / 03 격자·변수 / 04 L1~L3 합성·L2 모델·CDRI·민감도 / 05 시각화. 파라미터는 `config/config.yaml` 단일 소스(seed=42).

---

## 1. 분석 단위·좌표계·격자 (G004)

| 항목 | 규격 |
|---|---|
| 좌표계 | **EPSG:5179** 단일 통일. 모든 입력을 읽자마자 `.crs` 확인 → `to_crs(5179)`. 공공 SHP는 5186/5187/4326 혼재(창원=동부원점 권역). 웹지도 출력만 4326 |
| 격자 | **SGIS 100m 격자(격자ID)를 그대로 사용**(인구 결합 시 면적보간 불필요). 없을 때만 아래 코드로 생성 |
| 클리핑 | 시군구 경계 `intersects` 격자 채택, `area_in_city` 컬럼 보관 |
| 유니버스 | 전체 약 7.5만 격자 중 **인구>0 또는 건물≥1 격자(`universe=1`, 약 2~3만)** 만 순위 대상. 무인구 격자는 E=0 → "무인구 침수위험"으로 지도 표기만 |
| MAUP | 최종 CDRI를 500m(25셀 평균·최대)로 재집계 → 행정동 순위 Spearman ρ, TOP 20 겹침 1회 보고(Fontecha et al. 2021의 해상도 비교 논리) |

- [입력] SGIS 격자·경계(15141768) [처리] 위 규격 [산출] `data/processed/grid_100m.gpkg`(grid_id, geometry, universe, area_in_city, 이후 `raw_/z_/mm_` 접두어 컬럼), `docs/data_dictionary.md` [검증] 격자 수·유니버스 수 기록, CRS=5179, 변수 결측률<5% [노트북] 03

```python
# 격자 생성(SGIS 격자 부재 시): 5179 좌표를 100m로 floor한 원점
import numpy as np, geopandas as gpd
from shapely.geometry import box
b = city.to_crs(5179).total_bounds; x0, y0 = np.floor(b[:2]/100)*100
xs = np.arange(x0, b[2]+100, 100); ys = np.arange(y0, b[3]+100, 100)
grid = gpd.GeoDataFrame({'grid_id':[f"{int(x)}_{int(y)}" for x in xs for y in ys]},
    geometry=[box(x,y,x+100,y+100) for x in xs for y in ys], crs=5179)
grid = grid[grid.intersects(city.union_all())]
```

## 2. Layer 1 침수 취약성 (G007) — 기후노출 × 도시민감도

**2-1 민감도 변수** (DEM 5m → rasterio/whitebox; 부호 = 취약 방향)

| 변수 | 산출 | 부호 |
|---|---|---|
| 상대고도 | 격자 평균표고 − 반경 500m 초점평균(`uniform_filter`); 가능하면 HAND 병행 | − |
| 경사 | 5m DEM 경사(도) 격자 평균 | − |
| TWI | 싱크 채움 → D8 유량누적 → `ln(a/tanβ)`, tanβ 하한 0.001 | + |
| 불투수율 | EGIS 세분류 시가화건조지역 면적/격자면적; 대체 SGIS 건물연면적 비율 | + |
| 하천 근접 | 전국하천표준(15139206)/V-World `lt_c_wkmstrm` 중심선 거리 d → `max(0,1−d/300)` | + |
| **내수침수 예상 침수심** (신규) | 창원 도시침수정보시스템 WFS `cw:L210_100`(내수침수 100년) F_SHIM 등급 중앙값(0.25/0.75/1.25/1.75/2.5/3.5m)×F_AREA를 격자 면적가중 평균; `L200_100`(홍수범람)은 하천버퍼 보조, `L220`(해안침수)은 마산만 연안 격자 플래그 | + |
| 펌프장 서비스권 | 배수펌프장 9곳 반경 1km 이내=1(자연배수 불가지역의 행정적 인정). **L3에는 넣지 않음** | + |

근거: 최유라·한우석(2024)이 창원 피해 가중요인으로 지목한 저지대·복개천·하천변·불투수면·지하차도; 같은 논문이 인용한 "하천 인접도에 따른 Ⅰ등급 과다"(홍재주 외 2015) → 하천 근접·예상도 변수 **제외 민감도 1회** 필수.

**2-2 기후노출** (10년 시간강수, 관측 ≥5년 지점 + 기상청 API허브 AWS 매분자료(창원 155·북창원 255 등)를 시간합산 병합)
① 연최대 시간강수 10년 평균 ② 시간강수 ≥30mm 발생시간 수(연평균) ③ 상위 5개 이벤트(2024.9 포함) 3h·24h 누적 평균 ④ (신규) 확률강우량 초과비율 = ①/WAMIS 30년빈도 1h 확률강우량(하수관로 설계빈도 초과 여부 서술용). IDW `power∈{1,2,3}` LOOCV RMSE 최소 선택, 최근접 12지점·반경 10km, 반경 밖은 결측→최근접 대체 플래그(외삽 금지).

```python
from scipy.spatial import cKDTree
def idw(xy_s, v, xy_t, p=2, k=12):
    d, i = cKDTree(xy_s).query(xy_t, k=k); w = 1/np.maximum(d,1e-6)**p
    return (w*v[i]).sum(1)/w.sum(1)
def loocv(xy, v, p):  # 지점 하나씩 빼고 예측 → RMSE
    e = [idw(np.delete(xy,j,0), np.delete(v,j), xy[[j]], p)[0]-v[j] for j in range(len(v))]
    return np.sqrt(np.mean(np.square(e)))
best_p = min([1,2,3], key=lambda p: loocv(xy, v, p))
```

**2-3 표준화·합산·등급·검증**
- 각 변수 1~99% 윈저라이즈 → z-score(부호 정렬) → 노출·민감도 각각 동일가중 합산 → 각각 Jenks 4등급 → 매트릭스 취약성 I~IV(지침 준수, 지도용). CDRI 입력 `L1 = minmax(z_노출+z_민감도)`.
- 검증 타깃 분리 원칙: **예상도(모델 산출) = 입력, 흔적도(실제 발생) = 검증**. 흔적도는 ① 창원 재난안전대책본부 침수흔적도 게시판(2020~23 사상 69건 PDF: 지구·침수면적·원인) 지번을 QGIS로 디지타이징 ② 행안부 재난안전데이터공유플랫폼 침수흔적도 API(dataSn=108) ③ 정보공개청구 SHP 중 먼저 오는 것.
- [입력] DEM·EGIS·하천·WFS L200/L210/L220·펌프장·강수·AWS·확률강우량·`stations.csv` [처리] 위 [산출] `layer1_flood.gpkg`(grid_id, z_노출, z_민감도, L1, 등급 I~IV), `reports/figures/layer1_map.png` [검증] (a) 사례지 5개 동(양덕·봉암·팔용·명서·사화) I·II등급 비율 lift ≥1.5 (b) 침수흔적 격자 vs 나머지 ROC-AUC ≥0.70(참고: Bersabe & Jun 2025 서울 RF AUC 0.902), 상위 20% 격자의 흔적 포착률 ≥50% (c) 침수형 민원 AUC ≥0.65(보조) (d) 하천·예상도 제외 시 ρ [노트북] 03(변수), 04(합성·검증)

## 3. Layer 2 하수 역류 위험 (G006 분기 → G008)

**3-0 민원 LLM 구조화** (`src/agent/classify_complaint.py`; 정보공개청구 회신 전엔 시민의소리 '역류·하수·맨홀·배수·침수' 검색 결과 스크래핑분으로 선착수)
전처리(PII 정규식 마스킹, 원문은 `data/raw/private/` .gitignore) → JSON 강제 프롬프트 `{location_text, address, dong, type∈[역류,침수,악취,막힘,파손,기타], rain_related, urgency 1~3, precision∈[지번,도로명,건물명,동,불명], confidence}` + few-shot 5건, temperature 0, 20건/배치, `sha1(text)` 캐시 → 지오코딩 V-World(일 4만건) → 실패 시 카카오 `similar` → precision '동' 이하는 격자 라벨 제외(동 집계만).
[산출] `complaints_labeled.csv`(id, date, type, urgency, lon, lat, grid_id, precision) [검증] 층화 100건 2인 독립 라벨 → 유형 정확도 ≥85%, Cohen's κ ≥0.7 [노트북] 01(수집), 04(라벨)

**3-1 Plan A (관로별 좌표·연도 회신 시) — XGBoost** (Fontecha et al. 2021 2단계 프레임 중 1단계 '발생 여부'만 단순 적용)
- 단위 격자, 라벨 = 3년 역류·막힘·침수형 민원 ≥1(악취 제외), 유니버스 = 처리구역 내 & 관로 존재 격자.
- 피처: 관로 평균·최대 경과연수, 30년↑ 연장비, 평균·최소 관경, 흄관 비율, **관로밀도(km/㎢, Bersabe & Jun 2025 근거)**, 합류식 비율, 상대고도, TWI, 불투수율, 하천거리, 내수침수 예상 침수심, 펌프장 서비스권, 10년 시간최대강우, 인구밀도(신고 노출 통제).
- 불균형 `scale_pos_weight=N_neg/N_pos`, **행정동 GroupKFold 5-fold 공간 CV**(무작위 CV 금지), max_depth 3~5, lr 0.05, n_estimators 500+early stopping, subsample 0.8, 베이스라인 로지스틱. SHAP TreeExplainer beeswarm·경과연수/관경 dependence·mean|SHAP| Top5. `L2 = out-of-fold 예측확률`.

```python
from sklearn.model_selection import GroupKFold
from sklearn.metrics import average_precision_score, roc_auc_score
import xgboost as xgb
oof = np.zeros(len(X))
for tr, te in GroupKFold(5).split(X, y, groups=df['adm_dong']):
    m = xgb.XGBClassifier(max_depth=4, learning_rate=0.05, n_estimators=500, subsample=0.8,
        scale_pos_weight=(y[tr]==0).sum()/(y[tr]==1).sum(), random_state=42, early_stopping_rounds=30)
    m.fit(X.iloc[tr], y[tr], eval_set=[(X.iloc[te], y[te])], verbose=False)
    oof[te] = m.predict_proba(X.iloc[te])[:,1]
print('PR-AUC', average_precision_score(y, oof), 'ROC-AUC', roc_auc_score(y, oof))
```

**3-2 Plan B (집계만/미회신) — rule-based, 회신 무관 지금 착수**
`L2 = [(mm(합류식비율_처리구역)+ε)(mm(관로밀도)+ε)(mm(민원밀도_동)+ε)]^(1/3)`, ε=0.05 → minmax; 가법형 병기. 민원밀도는 동별 건수/㎢를 격자에 인구 비례 배분.
- [입력] 하수관로 집계(15118453), 배수구역 SHP(15129161), `complaints_labeled.csv`, 관로 회신 [산출] `layer2_sewer.gpkg`(grid_id, L2, Jenks 4등급, plan, coverage) [검증] A: PR-AUC ≥ 양성비×2, ROC-AUC ≥0.70, Brier / B: **민원 항목 제외 점수** vs 동별 민원 순위 Spearman ρ ≥0.4(순환 방지) / 공통: 자연재해저감종합계획 내수재해 위험지구 13개소(명서·내동천·봉암·석전 등) 격자의 L2 백분위 중앙값 ≥70 [노트북] 04

## 4. Layer 3 취약계층 (G009)

| 변수 | 산출 | 부호 |
|---|---|---|
| 65세↑ 비율, 1인가구 비율 | SGIS 격자. **V는 비율, E는 수**(이중계산 방지). 소수 격자 베이즈 축소 `(x+20p̄)/(n+20)`, 마스킹은 중앙값 대체 플래그 | + |
| 노후건물 비율(사용승인 30년↑), 지하층 보유 건물 수 | **1순위: 국토부 GIS건물통합정보 SHP(15083092, 폴리곤+건축물대장 속성) 격자 공간조인** → 건축HUB API는 결측 보완만(1만건/일 제한 회피). 그래도 부족 시 PNU-연속지적 중심점 조인 | + |
| 대피소 접근성 | 창원 도시침수정보시스템 `api/data/point?frequency=1`(444개소) 최근접 거리 → `min(d,2km)/2km` | + |

z-score(부호 정렬) 합산 → `L3=minmax`, Jenks 4등급. 상관 |r|>0.8 쌍은 하나만 채택(Balica et al. 2012 지표 상관 경고).
- [산출] `layer3_vuln.gpkg`, `layer3_map.png` [검증] 건물 커버리지(건물통합정보 건수/SGIS 건물수) ≥90%, 변수 상관행렬·VIF<5, 인명피해우려지역 '침수취약시설 58·반지하 5' 격자의 L3 백분위 분포 보고 [노트북] 03(변수), 04(합성)

## 5. 통합 CDRI (G010)

- **H** = 0.5·L1 + 0.5·L2(처리구역 밖 L2 결측 → H=L1, `H_source` 플래그). **E** = minmax(z(인구밀도)+z(건물 수)). **V** = L3.
- 집계: **가중기하평균 `CDRI = H^wH·E^wE·V^wV`**(기본 w=1/3). 근거: IPCC AR5 세 요소 필요조건, OECD/JRC(2008) 기하평균의 비보상성(compensability). Moreira et al.(2021)이 지적한 기하평균의 과소평가 경향 때문에 가법형 `ΣwX`를 민감도로 병기. H·V는 minmax 후 `[0.05,1]` 재척도, E=0 격자 제외.
- 등급: **→ `docs/CDRI_GRADE_SYSTEM.md` v2가 등급 규격의 원본** (R1~R5 오름차순, 조건부 캘리브레이션 본안 + Balica·Jenks 병기, 규칙 A/B/C, raw/final 분리, 대응표). 아래는 1안 Balica 설명으로 유지: 유니버스 minmax 0~1 → **Balica 5등급**(<0.01 매우낮음 / 0.01–0.25 낮음 / 0.25–0.50 보통 / 0.50–0.75 높음 / 0.75–1 매우높음; 출처는 Balica(2012) UNESCO-IHE 박사논문, Karmaoui et al.(2016) Table 4 재수록 — Nat Hazards 논문 아님, 정확 표기). Moreira(2021)에 따라 등급화가 가장 민감 → **Jenks 5등급 대안과 등급 일치율 κ 병기**.
- 가중치 3안(OECD/JRC 비교표 근거): ① 동일(Balica 'without weighting') ② 엔트로피 ③ AHP 3×3(팀 3인+하수도사업소 담당 1인, CR<0.1, RI=0.58; 9/8까지 수집). 비교: 전 격자 Spearman ρ ≥0.9, TOP 20 겹침 ≥14, 등급 이동 매트릭스.

```python
def entropy_weights(X):            # X: (n격자, k지표) 0~1 정규화값
    P = (X+1e-9)/(X+1e-9).sum(0)
    e = -(P*np.log(P)).sum(0)/np.log(len(X))
    return (1-e)/(1-e).sum()
def cdri(H, E, V, w=(1/3,1/3,1/3)):
    r = lambda a: 0.05+0.95*(a-a.min())/(a.max()-a.min())
    H, V = r(H), r(V)
    c = H**w[0]*E**w[1]*V**w[2]
    return (c-c.min())/(c.max()-c.min())
grade = np.select([c<.01, c<.25, c<.5, c<.75], ['매우낮음','낮음','보통','높음'], '매우높음')
```

- 기여도: TOP 20 각 격자에 H·E·V(및 L1·L2) 백분위 + 가법형 구성비 `w_kX_k/Σw_jX_j`(%), 최대 백분위 요소 = "주 원인". TOP 20은 300m NMS 후 선정(원 표는 부록); 라벨 = 행정동, 카카오 coord2address 도로명·지번, 최근접 펌프장·하수센터, 인구·65세↑수·지하층 건물 수·3년 민원 수.
- [산출] `cdri.gpkg`, `reports/tables/top20.csv`, `sensitivity.csv`, `cdri_map.png` [검증] 위 ρ·겹침·κ + **외부 대조**: 인명피해우려지역(침수취약 58) 및 자연재해위험개선지구(15139679)·내수 위험지구 13개소와 TOP 20 중첩률(정책 실현성 근거), 미지정 고위험 격자 목록 [노트북] 04(계산), 05(지도·표)

## 6. 검증 요약표·재현성

| 단계 | 지표 | 기준 |
|---|---|---|
| IDW | LOOCV RMSE, p | 크리깅 대비 ±10%, p 기록 |
| L1 | 사례지 lift / 흔적도 AUC / 민원 AUC | ≥1.5 / ≥0.70 / ≥0.65 |
| LLM | 유형 정확도, κ | ≥85%, ≥0.7 |
| L2-A | 공간CV PR-AUC, ROC-AUC | 양성비×2, ≥0.70 |
| L2-B | 민원 제외 점수 vs 민원 순위 ρ | ≥0.4 |
| L3 | 건물 커버리지, VIF | ≥90%, <5 |
| CDRI | 가중치 3안 ρ / TOP20 겹침 / MAUP ρ / Balica-Jenks κ | ≥0.9 / ≥14 / ≥0.8 / 보고 |

재현성: `data/raw/README.md`(다운로드일·md5·버전), `requirements.txt` 핀 고정, `nbconvert --execute` 01~05 전체 통과 = G014 게이트.

## 7. 흔한 함정
경계 격자·하천 클리핑 잔여 / 관측망 시가지 편중(외삽 금지) / 민원 신고편향(E로 통제, 민원은 라벨·검증 한쪽만) / L1 검증(침수형)·L2 라벨(역류형) 민원 분리 / 예상도 입력·흔적도 검증 분리 / 고도·상대고도·TWI, 인구밀도 vs 65세↑ 수 이중계산 → 상관·VIF / 결측 플래그(처리구역 밖 L2, EGIS 미승인, SGIS 마스킹) / CRS 혼용 / DEM 싱크 미처리 TWI 이상치 / 관로 경과연수 결측=신설 오해 / WFS 예상도 ADM_CD가 구 단위(4812x)라 시 전체 5개 구 모두 요청.

## 8. 기존 하네스 스토리(G002~G010) 수정 제안

| 스토리 | 현재 | 수정안 | 이유 |
|---|---|---|---|
| G002 | 강수·수위·펌프장·관로집계·SGIS·하천·시민의소리 | + 창원 도시침수정보시스템 WFS(L200/L210/L220/L300), 대피장소 API, GIS건물통합정보 SHP, 홍수위험지도 SHP, 재해위험지구 API, 침수흔적도 게시판 PDF, 인명피해우려지역 PDF, 저감종합계획 PDF, 기상청 AWS 매분, WAMIS 확률강우량 | L1 핵심 변수·검증 타깃·L3 건물 데이터를 청구 회신 없이 확보 |
| G003 | 지오코딩→문의→ASOS 대체 | + AWS 매분자료 병합, ≥5년 관측 지점 필터, 검증에 IDW p LOOCV 기록 | 보간 밀도·QC 명문화 |
| G004 | 고도·경사·불투수·하천버퍼·펌프장·인구 | + TWI·HAND, 내수침수 예상 침수심, `universe` 플래그, SGIS 격자ID 채택, 5179 통일 명시 | 지침 100m 격자·유니버스 정의 부재 |
| G005 | 하천수위 반응 EDA | 하천수위는 EDA 1장으로 한정(지수 미포함 결정 기록); 예상도·흔적도 겹침 EDA 추가 | 활용처 결정 |
| G006 | 회신 여부로 A/B 분기 | Plan B는 회신 무관 즉시 착수(9/1 이전), A는 회신 시 추가; 침수흔적도 경로 3안(게시판·행안부 API·청구) 결정 포함 | 일정 리스크 완화 |
| G007 | 사례지 5곳·민원 검증 | 침수흔적도 AUC를 주 검증으로 승격, 하천·예상도 제외 민감도, 확률강우량 초과비율 지표 추가 | 예상도 입력/흔적도 검증 분리, 하천 Ⅰ등급 과다 대응 |
| G008 | 홀드아웃 F1·AUC / 동 순위 ρ | A: 행정동 GroupKFold 공간CV, PR-AUC 주지표, 관로밀도 피처; B: 민원 제외 점수로 검증; 침수형/역류형 민원 분리, PII 마스킹·`.gitignore` 규칙, 내수 위험지구 13개소 대조 | 자기상관 누수·순환 검증 제거 |
| G009 | 건축HUB 법정동 순차 호출, 펌프장 접근성 포함 | GIS건물통합정보 SHP 1순위·건축HUB 보완, 펌프장 제외(L1만), 대피소 API 444개소, V는 비율로 재정의, 인명피해우려지역 대조 | 1만건 제한 회피·이중계산 방지 |
| G010 | H×E×V, 3가중치 ρ | + 0 처리·`[0.05,1]` 재척도, Balica 5등급 정확 인용+Jenks κ, 500m MAUP, 300m NMS, 기여도 산식, 인명피해우려지역·재해위험지구 중첩률, AHP 설문 9/8 마감 | 등급화 민감도(Moreira 2021)·정책 실현성 근거 |
