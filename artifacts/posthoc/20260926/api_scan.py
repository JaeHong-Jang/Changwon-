"""전국 침수흔적 API 전건을 훑어 연도·시도·창원 분포만 요약한다 (일회성 확인)."""
import collections, json, sys
from src.data import safetydata as SD

# 전건을 페이지로 읽으며 연도·시군구·시작일만 집계
years, sido_year, sgg_year, cw_dates = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
seen = 0
for page, batch in enumerate(SD.iter_records(sleep=0.3), start=1):
    for r in batch:
        y = str(r.get("FLDN_YR", ""))
        years[y] += 1
        sido_year[f"{r.get('STDG_CTPV_CD')}|{y}"] += 1
        sgg_year[f"{r.get('STDG_SGG_CD')}|{y}"] += 1
        if str(r.get("STDG_SGG_CD", "")) in SD.CHANGWON_SGG:
            cw_dates[f"{y}|{r.get('FLDN_BGNG_YMD')}|{r.get('FLDN_DST_NM')}"] += 1
    seen += len(batch)
    print(f"page {page} seen {seen}", file=sys.stderr, flush=True)

# 요약 저장
out = {"records_scanned": seen, "years": dict(sorted(years.items())),
       "sido_year": dict(sorted(sido_year.items())), "sgg_year": dict(sorted(sgg_year.items())),
       "changwon": dict(sorted(cw_dates.items()))}
json.dump(out, open(".omc/api_scan_20260926/summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({"records": seen, "years": out["years"], "changwon": out["changwon"]}, ensure_ascii=False, indent=1))
