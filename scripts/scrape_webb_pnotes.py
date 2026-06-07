#!/usr/bin/env python
"""Scrape Webb-site pnotes_daily.asp for 1 year of historical placement data.

Fetches: http://119.246.139.86:8080/Webb-site/ccass/pnotes_daily.asp?d=YYYY-MM-DD
Parses stock placement table, extracts code/name/price/date.
Merges into announcements.json, deduplicating by code+date.
"""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SCRIPT_DIR)
DATA = os.path.join(PROJ, "data")
ANN_PATH = os.path.join(DATA, "announcements.json")
WEBB_URL = "http://119.246.139.86:8080/Webb-site/ccass/pnotes_daily.asp"

HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_date(date_str: str) -> list[dict]:
    """Fetch pnotes for a specific date. Returns list of dicts."""
    url = f"{WEBB_URL}?d={date_str}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  {date_str}: fetch failed ({e})")
        return []

    # Parse table rows: each row has 12 <td> cells
    # Pattern: <tr>...<td>ROW</td><td>CODE</td><td>NAME</td>...
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    results = []
    for row_html in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        if len(cells) < 11:
            continue

        # Strip HTML tags
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

        # First cell should be a row number
        row_num = cells[0]
        if not row_num.isdigit():
            continue

        # Stock code: extract digits from "1327 📈" format
        code_text = cells[1]
        code_match = re.search(r"(\d+)", code_text)
        if not code_match:
            continue
        code = code_match.group(1).zfill(5)

        # Stock name: clean up annotations like <[Done]>, <<...>>
        name = cells[2]
        name = re.sub(r"<[^>]*>", "", name).strip()

        # Type: @ = done, <<text>> = note
        stype = cells[3].strip()

        # Note date (DD/MM/YYYY format)
        note_date_raw = cells[4].strip()
        note_date = _parse_date(note_date_raw)

        # Finished date
        finished_date_raw = cells[5].strip() if len(cells) > 5 else ""
        finished_date = _parse_date(finished_date_raw) if finished_date_raw else ""

        # Unit price
        unitprice_raw = cells[6].strip() if len(cells) > 6 else ""
        try:
            unitprice = float(unitprice_raw.replace(",", ""))
        except (ValueError, AttributeError):
            unitprice = None

        # Ratio
        ratio = cells[7].strip() if len(cells) > 7 else ""

        if not note_date:
            continue

        results.append({
            "code": code,
            "name": name,
            "note_date": note_date,
            "finished_date": finished_date,
            "unitprice": unitprice,
            "ratio": ratio,
            "stype": stype,
        })

    return results


def _parse_date(raw: str) -> str:
    """Convert DD/MM/YYYY or D/M/YYYY to YYYY-MM-DD."""
    if not raw:
        return ""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return raw


def merge_into_announcements(pnotes: list[dict]) -> int:
    """Merge pnotes into announcements.json. Returns number of new entries."""
    if not os.path.exists(ANN_PATH):
        with open(ANN_PATH, "w") as f:
            json.dump([], f)

    with open(ANN_PATH, "r") as f:
        anns = json.load(f)

    # Build dedup set
    existing = set()
    for a in anns:
        code = str(a.get("code", "")).zfill(5)
        date = a.get("date", "")
        existing.add((code, date))

    added = 0
    for p in pnotes:
        key = (p["code"], p["note_date"])
        if key in existing:
            continue
        existing.add(key)

        entry = {
            "code": p["code"],
            "name": p["name"],
            "types": ["配股"],
            "title": "PLACING OF NEW SHARES (Webb-site pnotes)",
            "date": p["note_date"],
            "url": "",
            "type": "placement",
            "typeLabel": "配股",
            "direction": "up",
        }
        if p["unitprice"] is not None and p["unitprice"] > 0:
            entry["offer_price"] = p["unitprice"]

        anns.append(entry)
        added += 1

    anns.sort(key=lambda x: x.get("date", ""), reverse=True)
    with open(ANN_PATH, "w") as f:
        json.dump(anns, f, ensure_ascii=False, indent=2)

    return added


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", default="2025-06-07")
    parser.add_argument("--to", dest="to_date", default="2026-06-07")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = datetime.strptime(args.from_date, "%Y-%m-%d")
    end = datetime.strptime(args.to_date, "%Y-%m-%d")

    all_pnotes = []
    current = start
    total_days = (end - start).days
    processed = 0
    empty_days = 0

    print(f"Scraping {total_days} days: {args.from_date} to {args.to_date}")
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        results = fetch_date(date_str)
        processed += 1

        if results:
            all_pnotes.extend(results)
            codes = set(r["code"] for r in results)
            print(f"  {date_str}: {len(results)} placements ({', '.join(sorted(codes)[:5])}{'...' if len(codes)>5 else ''})")
        else:
            empty_days += 1

        current += timedelta(days=1)
        if processed % 30 == 0:
            print(f"  Progress: {processed}/{total_days} days, {len(all_pnotes)} placements, {empty_days} empty")

    print(f"\nDone: {len(all_pnotes)} placements across {processed} days ({empty_days} empty)")

    if args.dry_run:
        print("DRY RUN — not saving")
        # Show sample
        for p in all_pnotes[:10]:
            print(f"  {p['code']} {p['name'][:20]} | {p['note_date']} | {p['unitprice']}")
        return

    added = merge_into_announcements(all_pnotes)
    print(f"Merged: {added} new entries into announcements.json")
    with open(ANN_PATH) as f:
        total = len(json.load(f))
    print(f"Total announcements: {total}")


if __name__ == "__main__":
    main()
