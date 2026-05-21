"""
Webb-site CCASS Scraper
=======================
Scrapes FireCat's Webb-site mirror for CCASS data:
  1. pnotes_daily  — New share subscriptions (配股/供股)
  2. bigchanges    — Big CCASS holding changes
  3. cconc         — CCASS Concentration (Top 5/10/NCIP)
  4. cparticipants — Named CCASS participants
  5. ipstakes      — Investor participant stakes

Usage:
  python -m scanner.webb_site_scraper --date 2026-05-20
  python -m scanner.webb_site_scraper --date 2026-05-20 --source pnotes
  python -m scanner.webb_site_scraper --all --days 5  # last 5 trading days
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────────
BASE_URL = "http://119.246.139.86:8080/Webb-site/ccass"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "webb_site"
STATE_FILE = OUTPUT_DIR / "last_run.json"

# Delay between requests (be polite to FireCat's server)
REQUEST_DELAY = float(os.getenv("WEBB_DELAY", "2.0"))

# ── Sources ─────────────────────────────────────────────────────────────────
SOURCES = {
    "pnotes": {
        "url_tpl": "/pnotes_daily.asp?sort=chgdn&d={date}&s=",
        "table_class": "numtable",
        "columns": [
            "stock_code", "stock_name", "stock_type",
            "note_date", "finished_date",
            "unit_price", "ratio", "qty",
            "last_price", "last_ratio", "vendor",
        ],
    },
    "bigchanges": {
        "url_tpl": "/bigchanges.asp?d={date}",
        "table_class": "numtable",
        "columns": [
            "stock_code", "issue_name", "participant",
            "change_pct", "prev_change",
        ],
    },
    "cconc": {
        "url_tpl": "/cconc.asp?d={date}",
        "table_class": "numtable",
        "columns": [
            "stock_code", "issue_name",
            "top5_pct", "top10_pct", "top10_ncip_pct",
            "ccass_stake_pct",
        ],
    },
    "cparticipants": {
        "url_tpl": "/cparticipants.asp",
        "table_class": "txtable",
        "columns": ["ccass_id", "participant_name"],
        "no_date": True,
    },
    "ipstakes": {
        "url_tpl": "/ipstakes.asp?d={date}",
        "table_class": "numtable",
        "columns": [
            "stock_code", "issue_name",
            "ncip_count", "cip_count", "total_ip_count",
            "ncip_stake_pct", "cip_stake_pct", "ip_stake_pct",
            "value_m",
        ],
    },
}


def fetch_page(source_key: str, query_date: str) -> str:
    """Fetch a Webb-site page, return HTML text."""
    cfg = SOURCES[source_key]
    url = BASE_URL + cfg["url_tpl"].format(date=query_date)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_table(html: str, table_class: str) -> list[list[str]]:
    """Extract rows from the main data table."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_=table_class)
    if not table:
        return []

    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        # First td is usually "colHide1" row number — skip it
        cells = []
        for td in tds:
            if "colHide1" in td.get("class", []):
                continue
            # Extract text, strip extra whitespace
            text = td.get_text(separator=" ", strip=True)
            # Remove AAStocks link icon text (📈)
            text = re.sub(r"\s*📈\s*", "", text)
            cells.append(text)
        if cells:
            rows.append(cells)
    return rows


def clean_value(val: str) -> str:
    """Clean a cell value: remove [Done] tags, extra spaces, etc."""
    val = re.sub(r"<[^>]+>", "", val)  # Remove any inline HTML tags
    val = val.strip()
    return val


def parse_number(val: str) -> Optional[float]:
    """Parse '68.85', '1.77%', '4665.371W' → float."""
    if not val:
        return None
    val = val.replace(",", "").replace("%", "").strip()
    # Handle "万" (W = 10K multiplier in Chinese finance)
    w_mult = 1.0
    if "W" in val or "万" in val:
        w_mult = 10_000.0
        val = val.replace("W", "").replace("万", "")
    try:
        return float(val) * w_mult
    except ValueError:
        return None


def scrape_source(source_key: str, query_date: str) -> list[dict]:
    """Scrape one Webb-site data source."""
    cfg = SOURCES[source_key]
    html = fetch_page(source_key, query_date)
    rows = parse_table(html, cfg["table_class"])

    results = []
    for row in rows:
        entry = {"source": source_key, "scraped_date": query_date}
        for i, col_name in enumerate(cfg["columns"]):
            if i < len(row):
                entry[col_name] = clean_value(row[i])
            else:
                entry[col_name] = ""
        # Add parsed numeric fields
        for key in ["change_pct", "ratio", "last_ratio", "unit_price",
                     "last_price", "top5_pct", "top10_pct", "top10_ncip_pct",
                     "ccass_stake_pct", "ncip_stake_pct", "cip_stake_pct",
                     "ip_stake_pct", "value_m"]:
            if key in entry:
                entry[f"{key}_num"] = parse_number(entry[key])
        results.append(entry)

    return results


def scrape_all_sources(query_date: str) -> dict[str, list[dict]]:
    """Scrape all 5 sources for a given date."""
    all_data = {}
    for source_key in SOURCES:
        try:
            print(f"  [{source_key}] scraping...")
            data = scrape_source(source_key, query_date)
            all_data[source_key] = data
            print(f"  [{source_key}] → {len(data)} records")
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"  [{source_key}] ERROR: {e}")
            all_data[source_key] = []
    return all_data


def detect_changes(new_data: dict, old_data: dict) -> list[str]:
    """Compare with previous run and report new entries."""
    alerts = []
    for source_key, entries in new_data.items():
        old_entries = old_data.get(source_key, [])
        if not old_entries:
            continue

        new_codes = {e.get("stock_code", "") for e in entries}
        old_codes = {e.get("stock_code", "") for e in old_entries}

        new_stocks = new_codes - old_codes
        if new_stocks:
            alerts.append(
                f"[{source_key}] New stocks detected: {', '.join(sorted(new_stocks))}"
            )

    return alerts


def load_state() -> dict:
    """Load previous scrape results."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(data: dict) -> None:
    """Save current scrape results."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def save_daily(data: dict, query_date: str) -> Path:
    """Save daily dump to JSON file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"webb_{query_date}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


# ── Alert formatting ────────────────────────────────────────────────────────
def format_alerts(alerts: list[str], query_date: str) -> str:
    """Format alerts for Telegram."""
    if not alerts:
        return ""
    lines = [f"🔔 <b>Webb-site CCASS Alerts</b> ({query_date})", ""]
    lines.extend(f"• {a}" for a in alerts)
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Webb-site CCASS Scraper")
    parser.add_argument("--date", help="Query date (YYYY-MM-DD)", default=None)
    parser.add_argument("--source", help="Single source key", default=None)
    parser.add_argument("--days", type=int, help="Scrape last N days", default=1)
    parser.add_argument("--output", help="Output JSON path", default=None)
    parser.add_argument("--compare", action="store_true",
                        help="Compare with previous run and report new entries")
    parser.add_argument("--telegram", action="store_true",
                        help="Send alerts to Telegram")
    args = parser.parse_args()

    # Determine dates
    if args.date:
        target_date = args.date
    else:
        target_date = date.today().strftime("%Y-%m-%d")

    # Scrape
    sources_to_scrape = [args.source] if args.source else list(SOURCES)

    if args.source:
        print(f"Scraping [{args.source}] for {target_date}")
        data = scrape_source(args.source, target_date)
        all_data = {args.source: data}
    else:
        print(f"Scraping ALL sources for {target_date}")
        all_data = scrape_all_sources(target_date)

    # Save
    out_path = save_daily(all_data, target_date)
    print(f"Saved → {out_path}")

    # Compare
    if args.compare:
        old = load_state()
        alerts = detect_changes(all_data, old)
        if alerts:
            print("\n".join(alerts))
    save_state(all_data)

    # Telegram
    if args.telegram and args.compare:
        old = load_state()
        alerts = detect_changes(all_data, old)
        if alerts:
            msg = format_alerts(alerts, target_date)
            print(f"Would send Telegram:\n{msg}")

    # Custom output path
    if args.output:
        Path(args.output).write_text(
            json.dumps(all_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # Summary
    total = sum(len(v) for v in all_data.values())
    print(f"\nTotal: {total} records across {len(all_data)} sources")


if __name__ == "__main__":
    main()
