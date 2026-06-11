#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hkex_history_scanner.py — 掃過去 N 年披露易公告,建回測事件庫
出 events_history.json: [{code, name, type, date, title}]
跑法: pip install requests && python hkex_history_scanner.py
"""
import json, re, sys, time
from datetime import datetime, date
from pathlib import Path
import requests

OUT        = Path("events_history.json")
YEAR_FROM  = 2023
YEAR_TO    = date.today().year
KEYWORDS   = {
    "配股": ["配售新股", "先舊後新", "認購新股"],
    "供股": ["供股", "公開發售"],
}
NOISE = re.compile(r"月報表|翌日披露|證券變動|股份購回|授出購股權|根據一般授權")
URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh"}

def search(kw: str, d_from: str, d_to: str):
    params = {
        "sortDir": "0", "sortByOptions": "DateTime", "category": "0",
        "market": "SEHK", "stockId": "-1", "documentType": "-1",
        "fromDate": d_from, "toDate": d_to,
        "title": kw, "searchType": "1",
        "t1code": "-2", "t2Gcode": "-2", "t2code": "-2",
        "rowRange": "500", "lang": "ZH",
    }
    r = requests.get(URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = json.loads(r.text)
    return json.loads(data["result"]) if isinstance(data.get("result"), str) else data.get("result", [])

def main():
    events, seen = [], set()   # seen: (code, year, type) 同年同類去重
    for y in range(YEAR_FROM, YEAR_TO + 1):
        for ev_type, kws in KEYWORDS.items():
            for kw in kws:
                try:
                    rows = search(kw, f"{y}0101", f"{y}1231")
                except Exception as e:
                    print(f"⚠ {y} {kw}: {e}", file=sys.stderr); continue
                for row in rows:
                    code = str(row.get("STOCK_CODE","")).strip().zfill(4)
                    title = row.get("TITLE","")
                    if not code.isdigit() or NOISE.search(title):
                        continue
                    try:
                        d = datetime.strptime(row["DATE_TIME"][:10], "%d/%m/%Y").strftime("%Y-%m-%d")
                    except Exception:
                        continue
                    key = (code, y, ev_type)
                    if key in seen:
                        continue
                    seen.add(key)
                    events.append({"code": code, "name": row.get("STOCK_NAME","").strip(),
                                   "type": ev_type, "date": d, "title": title})
                time.sleep(1.5)
        print(f"… {y} 完成,累計 {len(events)} 件")
    events.sort(key=lambda e: e["date"])
    OUT.write_text(json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ {len(events)} 件事件 → {OUT}")

if __name__ == "__main__":
    main()
