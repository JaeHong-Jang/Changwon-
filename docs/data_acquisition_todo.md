# 지금 확보해야 하는 데이터 (P1 차단 해소용)

> **2026-09-02 갱신**: 정보공개청구 회신으로 침수흔적도 전자파일이 9/14 에 온다. 아래 **A2 PDF 69건은 받지 않는다**
> (전자파일이 PDF/csd 일 때만 회귀). 신규 신청 목록과 2인 분담은 `docs/WORK_PLAN_0914.md` 가 최신이다.

> 2026-08-22 기준. `python -m src.pipeline run --phase P2` 가 `h00_access_requests` 에서
> **필수인데 미신청 2건**으로 막혀 있다. 아래를 채우고 `docs/data_access_log.md` 의
> 상태를 갱신하면 다시 진행된다.
>
> 받은 파일은 `data/raw/<폴더>/` 에 넣고 `data/raw/README.md` 에 **취득일·URL·md5** 를 기록한다.

---

## #7 강수·수위 관측지점 좌표 — **이것이 지금 P2 를 막는 진짜 병목**

`h03_stations` → IDW 공간보간 → Layer 1 전체가 이 좌표 없이는 성립하지 않는다.
좌표 확보율 90% 미달이면 하네스 규칙상 공간보간을 중단해야 한다.

### 좌표가 필요한 대상: 강수 29지점 + 수위 2지점

**강수 (2015~2024 커버리지 90% 이상 cohort 29개)**

| 코드 | 지점명 | 코드 | 지점명 | 코드 | 지점명 |
|---|---|---|---|---|---|
| 1 | 중앙동 | 15 | 태백동 | 29 | 소계민원 |
| 2 | 국방연구소 | 17 | 문화동 | 30 | 충무동 |
| 3 | 북면 | 19 | 구산면 | 31 | 삼귀민원 |
| 4 | 명곡동 | 20 | 진동면 | 32 | 봉림동 |
| 6 | 성산구청 | 21 | 진북면 | 33 | 의안민원 |
| 7 | 웅남동 | 23 | 진해물재생센터 | 34 | 팔용농산물 |
| 10 | 회성동 | 25 | 동부도서관 | 35 | 동읍 |
| 11 | 웅동1동 | 26 | 진전면 | 36 | 마산소방서 |
| 14 | 사파동 | 27 | 내서읍 | 37 | 덕동동 |
| | | 28 | 진해구청 | 38 | 화천민원 |

**수위 2지점**: 차룡8교(수위계, 코드 8), 연덕교(수위계, 코드 50)

지점명이 대부분 **행정동·공공시설명**이다. 창원시가 자체 운영하는 관측망이고
기상청 ASOS/AWS 가 아니므로, 기상청 지점정보로는 찾을 수 없다.

### 확보 경로 (권장 순서)

**1순위 — 창원시에 직접 요청 (정확한 좌표를 받는 유일한 길)**

- 창원시 재난안전대책본부 / 도시침수정보시스템 담당
- 요청 문안: "첨부 29개 강수 관측지점과 2개 수위계의 **설치 위치 좌표(위경도 또는 EPSG:5179)와 지점 코드북**"
- 이미 진행 중인 정보공개청구(#1, 접수번호 17369500)에 **추가 청구**하거나 별건으로 청구
- 정부24 정보공개청구: https://www.open.go.kr
- 창원시 도시침수정보시스템: https://bangjae.changwon.go.kr

**2순위 — 도시침수정보시스템 공개 API — 2026-08-22 확인: 관측소 좌표 없음**

두 경로를 직접 호출해 확인했다. 여기서는 못 구한다.

| 확인한 것 | 결과 |
|---|---|
| `geoserver/cw/wfs?request=GetCapabilities` | 레이어 13개 전부 침수예상도(L200/L210/L220 = 강우 시나리오별 침수심)와 L300. **관측소·우량계 레이어 없음** |
| `api/api/data/point?frequency=1..4` | 1·2 는 대피장소·방재기관(모텔·경로당·병원 등), 3·4 는 빈 응답. **관측소 없음** |

**3순위 — 지오코딩으로 근사 (대안, 한계 명시 필요)**

29개 지점을 이름으로 나눠보면 두 갈래이고, 절반 이상은 **이미 가진 자료로 처리된다.**

| 유형 | 개수 | 처리 방법 | 추가 확보 필요? |
|---|---:|---|---|
| 행정동·읍면 이름 (중앙동, 북면, 명곡동, 웅남동, 회성동, 웅동1동, 사파동, 태백동, 문화동, 구산면, 진동면, 진북면, 진전면, 내서읍, 충무동, 봉림동, 동읍, 덕동동) | 18 | 이미 만든 행정동 경계(`changwon_boundary.gpkg`, 55개)의 **중심점** | **불필요** |
| 공공시설 이름 (국방연구소, 성산구청, 진해물재생센터, 동부도서관, 진해구청, 소계민원, 삼귀민원, 의안민원, 팔용농산물, 마산소방서, 화천민원) | 11 | 시설 주소를 지오코딩 | V-World 또는 카카오 키 (#10 / #11) |

- V-World 지오코더 (일 40,000건, 무료): https://www.vworld.kr — 회원가입 후 인증키
  `https://api.vworld.kr/req/address?service=address&request=GetCoord&type=ROAD&address=<주소>&key=<KEY>`
- 카카오 로컬 API (이중 검증용): https://developers.kakao.com/docs/ko/local/dev-guide

**중요한 한계**: 행정동 중심점은 **우량계가 실제로 설치된 위치가 아니다.** 동 하나가
수 km 에 걸치므로 100m 격자 IDW 에서 오차가 그대로 들어간다. 이 방법을 채택하면
`docs/decisions/` 에 한계를 기록하고, 보고서에 "관측지점 위치는 행정동 대표점 근사"
라고 명시해야 한다. **1순위(시에 직접 요청)를 병행하는 것을 권한다.**

---

## #17 즉시 다운로드분 — 신청이 필요 없는데 아직 안 받은 것

로그인·승인 없이 바로 받을 수 있다. `h08_result_review`(결과 확인 EDA)가
TOP 20 을 외부 자료와 대조할 때 쓴다.

| 항목 | 링크 | 용도 | 저장 위치 |
|---|---|---|---|
| **A1 창원 침수예상도 WFS** | `https://bangjae.changwon.go.kr/geoserver/cw/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=cw:L210_100&outputFormat=application/json` | 결과 대조 (창원시 자체 시나리오) | `data/raw/flood_maps/changwon_wfs/` |
| **A7 홍수위험지도 SHP** (하천범람 + 도시침수, 창원 5개 구) | https://www.data.go.kr/data/15077744/fileData.do → https://data.floodmap.go.kr/main/board/map_data_download | 결과 대조 (국가 공식 시나리오) | `data/raw/flood_maps/floodmap_go_kr/` |
| **A2 침수흔적도 PDF** (2020~2023 지구별 69건) | https://bangjae.changwon.go.kr/portal/bbs/list.do?ptIdx=114&mId=0802000000 | Layer 1 검증 라벨 후보 | `data/raw/flood_traces/pdf/` |
| **A3 인명피해우려지역 대피장소 PDF** (구별 5개) | https://bangjae.changwon.go.kr/portal/bbs/view.do?mId=0803000000&ptIdx=115&bIdx=560 | Layer 3 적응역량 | `data/raw/shelters/` |
| **A4 제2차 자연재해저감종합계획(안)** — 위험지구 115개소 | https://council.changwon.go.kr/svc/cmt/CmtBillView.do?cmmtCd=305015&billSn=245555 | 결과 대조 (시가 지정한 위험지구) | `data/raw/reference/` |
| **A5 대피장소·방재기관 포인트 API** | `https://bangjae.changwon.go.kr/api/api/data/point?frequency=1` (및 `frequency=2`) | Layer 3 최근접 시설 거리 | `data/raw/shelters/` |
| **A9 환경부 하수도통계 2025 xlsx** (읍면동·매설연도별 관로) | https://www.hasudoinfo.or.kr/bbs/lay1/WS10000015/list.do (게시글 41430) | **Layer 2 Plan B 의 핵심 입력** | `data/raw/sewer/` |

**A9 가 특히 중요합니다** — 정보공개청구(#1) 회신이 늦어져도 이것만 있으면
Layer 2 를 Plan B(인프라 지수)로 진행할 수 있습니다.

---

## 받은 뒤 할 일

1. `data/raw/README.md` 에 취득일·URL·md5 기록
2. `docs/data_access_log.md` 의 해당 행 상태를 `✅ 수령` 으로 변경
3. `python -m src.pipeline run --phase P1` — 접근신청 노드가 통과하는지 확인
4. 좌표를 받았으면 `data/external/stations.csv` 로 정리 후 `h03_stations` 구현 착수

## 지금 확보 못 해도 진행할 수 있는 것

`#17` 은 P4(결과 확인)에서 쓰므로, 급하면 `docs/data_access_log.md` 에서
`대체가능` 으로 낮추고 P2·P3 를 먼저 진행할 수 있다. 다만 **`#7 좌표는 대안이 없다** —
지오코딩 근사로라도 채우지 않으면 Layer 1 이 만들어지지 않는다.
