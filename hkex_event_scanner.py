#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hkex_event_scanner.py — 自動掃 披露易 公告標題,搵新 配售 / 供股 事件
出 events_watchlist.json(折讓/攤薄要人手或另寫 parser 補,先出殼)
跑法: pip install requests && python hkex_event_scanner.py
"""
import json, re, sys
from datetime import datetime, timedelta
from pathlib import Path
import requests

OUT = Path("events_watchlist.json")
LOOKBACK_DAYS = 45
KEYWORDS = {
    "配股": ["配售", "認購新股", "先舊後新", "PLACING"],
    "供股": ["供股", "RIGHTS ISSUE", "公開發售", "OPEN OFFER"],
}
URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh"}

def search(keyword: str):
    """披露易標題搜尋(JSON 介面)。注意: HKEX 介面間中改參數,壞咗就睇返 titlesearch.xhtml 的 network tab 對返。"""
    now = datetime.now()
    params = {
        "sortDir": "0", "sortByOptions": "DateTime", "category": "0",
        "market": "SEHK", "stockId": "-1", "documentType": "-1",
        "fromDate": (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d"),
        "toDate": now.strftime("%Y%m%d"),
        "title": keyword, "searchType": "1", "t1code": "-2", "t2Gcode": "-2",
        "t2code": "-2", "rowRange": "200", "lang": "ZH",
    }
    r = requests.get(URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = json.loads(r.text)
    return json.loads(data["result"]) if isinstance(data.get("result"), str) else data.get("result", [])

def main():
    seen, events = set(), []
    # 保留已有清單的人手欄位(折讓/攤薄/override)
    old = {}
    if OUT.exists():
        for e in json.loads(OUT.read_text(encoding="utf-8")):
            old[str(e["code"]).zfill(4)] = e

    for ev_type, kws in KEYWORDS.items():
        for kw in kws:
            try:
                rows = search(kw)
            except Exception as e:
                print(f"⚠ 搜尋 {kw} 失敗: {e}", file=sys.stderr)
                continue
            for row in rows:
                code = str(row.get("STOCK_CODE", "")).strip().zfill(4)
                if not code.isdigit() or code in seen:
                    continue
                title = row.get("TITLE", "")
                # 過濾雜訊: 月報表/翌日披露都會有 "配售" 字眼
                if re.search(r"月報表|翌日披露|股份發行人的證券變動", title):
                    continue
                seen.add(code)
                prev = old.get(code, {})
                events.append({
                    "code": code,
                    "name": row.get("STOCK_NAME", "").strip(),
                    "type": ev_type,
                    "date": datetime.strptime(row.get("DATE_TIME", "")[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
                            if row.get("DATE_TIME") else datetime.now().strftime("%Y-%m-%d"),
                    "discount": prev.get("discount", 0.0),   # 人手補或另寫公告 parser
                    "dilution": prev.get("dilution", 0.0),
                    "agent": prev.get("agent", ""),
                    "title": title,
                    **{k: prev[k] for k in ("year_open_override", "ipo_open_override", "poc_override") if k in prev},
                })
    OUT.write_text(json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ 搵到 {len(events)} 隻 → {OUT}")

if __name__ == "__main__":
    main()
