"""CCASS Scraper.

HKEX CCASS Shareholding Search:
  https://www3.hkexnews.hk/sdw/search/searchsdw.aspx

呢個 endpoint 接受 POST，要傳 viewstate / eventvalidation token (ASP.NET form)。
我哋先 GET 個 page 攞 token，再 POST 查每隻股票。

呢個 module 嘅責任：
1. Scrape 一隻股票一個日期
2. Parse total holdings + participant breakdown
3. Schema validation (FATAL-003 對應)
4. 寫入 DB
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import cloudscraper
from requests.exceptions import RequestException
from bs4 import BeautifulSoup

from src.db import get_conn
from src.logger import setup_logger

logger = setup_logger("scraper")

SDW_URL = "https://www3.hkexnews.hk/sdw/search/searchsdw.aspx"

DEBUG_DIR = Path(__file__).parent.parent / "debug"


@dataclass
class CCASSSnapshot:
    stock_code: str
    trade_date: str          # YYYY-MM-DD
    total_shares: int
    total_pct: Optional[float]
    num_participants: int
    holdings: list[dict]     # [{participant_id, name, shares, pct}, ...]


class CCASSScraper:
    def __init__(
        self,
        user_agent: str,
        delay_min: float = 1.0,
        delay_max: float = 3.0,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.timeout = timeout
        self.max_retries = max_retries
        self._consecutive_503 = 0
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({"User-Agent": user_agent})
        self._form_tokens: dict[str, str] = {}
        self._last_token_refresh: float = 0

    def _refresh_form_tokens(self) -> None:
        """ASP.NET WebForms 要 __VIEWSTATE 等 token。每 30 分鐘 refresh。"""
        now = time.time()
        if self._form_tokens and (now - self._last_token_refresh) < 1800:
            return
        logger.debug("Refreshing form tokens")
        resp = self.session.get(SDW_URL, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # Extract ALL hidden fields (catches any new ASP.NET tokens)
        tokens = {}
        for el in soup.find_all("input", {"type": "hidden"}):
            name = el.get("name", "")
            if name:
                tokens[name] = el.get("value", "")
        if "__VIEWSTATE" not in tokens:
            logger.warning("No __VIEWSTATE found. Page title: %s",
                           (soup.find("title") or "").get_text()[:80] if soup.find("title") else "")
            raise RuntimeError("Cannot find __VIEWSTATE on CCASS search page")
        logger.info("Got %d form tokens: %s", len(tokens), list(tokens.keys()))
        # Log form field names to diagnose structure changes
        all_inputs = [(el.get("name",""), el.get("type",""), el.get("value","")[:30] if el.get("value") else "")
                      for el in soup.find_all("input")]
        logger.info("All form inputs: %s", all_inputs)
        self._form_tokens = tokens
        self._last_token_refresh = now

    def _polite_sleep(self) -> None:
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def scrape_stock(self, stock_code: str, query_date: date) -> Optional[CCASSSnapshot]:
        """
        Scrape 一隻股票一個日期。
        Returns None 如果 stock 唔存在 / 嗰日冇數據。
        """
        stock_code = stock_code.zfill(5)
        date_str = query_date.strftime("%Y/%m/%d")

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._refresh_form_tokens()
                payload = {
                    **self._form_tokens,
                    "__EVENTTARGET": "btnSearch",  # <a> tag calls __doPostBack('btnSearch','')
                    "__EVENTARGUMENT": "",
                    "txtShareholdingDate": date_str,
                    "txtStockCode": stock_code,
                    "txtStockName": "",
                    "txtParticipantID": "",
                    "txtParticipantName": "",
                }
                resp = self.session.post(SDW_URL, data=payload, timeout=self.timeout)

                # HKEX outage detection — 503 on multiple stocks = server down
                if resp.status_code == 503:
                    self._consecutive_503 += 1
                    logger.warning(
                        "HKEX 503 on %s (consecutive=%d/5), sleeping 15s",
                        stock_code, self._consecutive_503,
                    )
                    if self._consecutive_503 >= 5:
                        raise RuntimeError(
                            "HKEX CCASS appears DOWN — 5 consecutive 503s. Aborting scrape."
                        )
                    time.sleep(15)
                    continue
                # Generic rate limit (429)
                if resp.status_code == 429:
                    logger.warning("Rate limited (429) on %s, sleeping 30s", stock_code)
                    time.sleep(30)
                    continue
                # Successful response — reset outage counter
                self._consecutive_503 = 0
                resp.raise_for_status()

                snapshot = self._parse(stock_code, query_date, resp.text)
                self._polite_sleep()
                return snapshot

            except (RequestException, RuntimeError) as e:
                last_err = e
                backoff = 2 ** attempt
                logger.warning(
                    "Scrape %s attempt %d failed: %s. Sleeping %ds",
                    stock_code, attempt, e, backoff,
                )
                time.sleep(backoff)

        logger.error("Scrape %s exhausted retries: %s", stock_code, last_err)
        return None

    def _parse(
        self, stock_code: str, query_date: date, html: str
    ) -> Optional[CCASSSnapshot]:
        """Parse CCASS HTML. 加 schema validation。"""
        soup = BeautifulSoup(html, "lxml")

        # 1. 偵測「冇數據」: HKEX 會 render error message
        err_block = soup.find("div", class_="ccass-search-msg")
        if err_block:
            msg_text = err_block.get_text(strip=True).lower()
            if "no record" in msg_text or "no data" in msg_text or "not found" in msg_text:
                logger.info("No CCASS data for %s on %s", stock_code, query_date)
                return None
            logger.debug("CCASS msg for %s: %s", stock_code, err_block.get_text(strip=True)[:200])
        # Detect anti-bot / access-denied pages
        page_title = soup.find("title")
        if page_title:
            title_lc = page_title.get_text(strip=True).lower()
            if any(k in title_lc for k in ("access denied", "captcha", "403", "blocked")):
                logger.warning("Possible anti-bot page for %s: %s", stock_code, page_title.get_text(strip=True)[:100])
                return None

        # 2. 攞 total shareholding
        # HKEX 用 <div class="ccass-search-total"> 包總數
        total_section = soup.find("div", id="pnlResultSummary") or soup.find(
            "div", class_="ccass-search-result"
        )

        total_shares = self._extract_total_shares(soup)
        total_pct = self._extract_total_pct(soup)

        if total_shares is None:
            total_shares = self._extract_total_from_text(html)
            if total_shares:
                logger.debug("Used regex fallback total_shares for %s: %d", stock_code, total_shares)

        if total_shares is None:
            self._save_debug_html(stock_code, query_date, html)
            body_snip = BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)[:400]
            logger.warning(
                "Schema validation failed for %s on %s: total_shares not found. Snippet: %s",
                stock_code, query_date, body_snip,
            )
            return None

        # 3. 攞 participant breakdown
        holdings = self._extract_holdings(soup)

        # 4. Sanity check (FATAL-003 嗰類validation)
        if total_shares < 0 or total_shares > 1e15:
            self._save_debug_html(stock_code, query_date, html)
            logger.warning(
                "Schema validation failed for %s: total_shares=%d out of range",
                stock_code, total_shares,
            )
            return None
        if total_pct is not None and (total_pct < 0 or total_pct > 100):
            logger.warning(
                "total_pct out of range for %s: %.4f, clamping", stock_code, total_pct
            )
            total_pct = max(0.0, min(100.0, total_pct))

        return CCASSSnapshot(
            stock_code=stock_code,
            trade_date=query_date.strftime("%Y-%m-%d"),
            total_shares=total_shares,
            total_pct=total_pct,
            num_participants=len(holdings),
            holdings=holdings,
        )

    @staticmethod
    def _extract_total_shares(soup: BeautifulSoup) -> Optional[int]:
        """多層次 strategy 搵 CCASS total shareholding count。

        Strategy 1: 搵 ccass-search-total row 嘅 shareholding value
        Strategy 2: 搵 "Total number of Issued Shares/Warrants/Units" summary value
        Strategy 3: sum Market Intermediaries + Investor Participants
        """
        # Strategy 1: ccass-search-total row
        total_row = soup.find("div", class_="ccass-search-total")
        if total_row:
            val = total_row.find("div", class_="value")
            if val:
                num = CCASSScraper._parse_number(val.get_text(strip=True))
                if num and num > 0:
                    return num
        # Strategy 2: Total number of Issued Shares/Warrants/Units
        label = soup.find(string=re.compile(
            r"Total number of Issued Shares", re.I))
        if label:
            summary_val = label.find_next("div", class_="summary-value")
            if summary_val:
                num = CCASSScraper._parse_number(
                    summary_val.get_text(strip=True))
                if num and num > 0:
                    return num
        # Strategy 3: sum participants (old page layout fallback)
        total = 0
        for label_text in ["Market Intermediaries",
                            "Consenting Investor Participants",
                            "Non-consenting Investor Participants"]:
            el = soup.find(string=re.compile(
                re.escape(label_text), re.I))
            if el:
                parent = el.find_parent()
                body = (parent.find("div", class_="mobile-list-body") or
                        parent.find_next("div", class_="value") or
                        parent.find_next("td"))
                if body:
                    num = CCASSScraper._parse_number(
                        body.get_text(strip=True))
                    if num and num > 0:
                        total += num
        return total if total > 0 else None

    @staticmethod
    def _extract_total_from_text(html: str) -> Optional[int]:
        """Last-resort: find most-frequent large number (>=10M) in raw HTML — likely total shares."""
        from collections import Counter
        candidates = re.findall(r'(?<![0-9])([0-9]{1,3}(?:,[0-9]{3}){2,})', html)
        nums = []
        for c in candidates:
            try:
                n = int(c.replace(',', ''))
                if n >= 10_000_000:
                    nums.append(n)
            except ValueError:
                pass
        if not nums:
            return None
        return Counter(nums).most_common(1)[0][0]

    @staticmethod
    def _extract_total_pct(soup: BeautifulSoup) -> Optional[float]:
        # Try Total row first
        total_row = soup.find("div", class_="ccass-search-total")
        if total_row:
            pct_div = total_row.find("div", class_="percent-of-participants")
            if pct_div:
                val = pct_div.find("div", class_="value")
                if val:
                    txt = val.get_text(strip=True).rstrip("%").strip()
                    try:
                        return float(txt)
                    except ValueError:
                        pass
        # Fallback: find any % label and get next value
        el = soup.find(string=re.compile(r"% of the total number of Issued Shares", re.I))
        if el:
            parent = el.find_parent()
            value_el = parent.find_next("div", class_="value") or parent.find_next("td")
            if value_el:
                txt = value_el.get_text(strip=True).rstrip("%").strip()
                try:
                    return float(txt)
                except ValueError:
                    pass
        return None

    @staticmethod
    def _extract_holdings(soup: BeautifulSoup) -> list[dict]:
        """攞 participant table。用 CSS class 提取，兼容 HKEX 現有結構。"""
        table = None
        for t in soup.find_all("table"):
            if t.find("td", class_=re.compile("col-participant", re.I)):
                table = t
                break
        if not table:
            table = soup.find("table", id="participantShareholding") or soup.find(
                "table", class_="table-scroll"
            )
        if not table:
            return []

        def _cell_val(td) -> str:
            body = td.find("div", class_="mobile-list-body")
            return body.get_text(strip=True) if body else td.get_text(strip=True)

        rows = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            pid_td   = tr.find("td", class_=re.compile(r"col-participant-id", re.I))
            name_td  = tr.find("td", class_=re.compile(r"col-participant-name", re.I))
            share_td = tr.find("td", class_=re.compile(r"col-shareholding", re.I))
            pct_td   = tr.find("td", class_=re.compile(r"col-shareholding-percent", re.I))
            if pid_td and share_td:
                pid        = _cell_val(pid_td)
                name       = _cell_val(name_td) if name_td else ""
                shares_txt = _cell_val(share_td)
                pct_txt    = _cell_val(pct_td) if pct_td else ""
            elif len(tds) >= 5:
                pid, name, _, shares_txt, pct_txt = (
                    _cell_val(tds[0]), _cell_val(tds[1]),
                    _cell_val(tds[2]), _cell_val(tds[3]),
                    _cell_val(tds[4]),
                )
            elif len(tds) >= 4:
                pid, name, shares_txt, pct_txt = (
                    _cell_val(tds[0]), _cell_val(tds[1]),
                    _cell_val(tds[2]), _cell_val(tds[3]),
                )
            else:
                continue
            shares = CCASSScraper._parse_number(shares_txt)
            try:
                pct = float(pct_txt.rstrip("%").strip())
            except ValueError:
                pct = None
            if pid and shares is not None:
                rows.append({"participant_id": pid, "participant_name": name,
                             "shares": shares, "pct_of_issued": pct})
        return rows

    @staticmethod
    def _parse_number(text: str) -> Optional[int]:
        """Parse '1,234,567' → 1234567。"""
        if not text:
            return None
        cleaned = re.sub(r"[,\s]", "", text)
        if not cleaned or not re.match(r"^-?\d+$", cleaned):
            return None
        try:
            return int(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _save_debug_html(stock_code: str, query_date: date, html: str) -> None:
        DEBUG_DIR.mkdir(exist_ok=True)
        ts = query_date.strftime("%Y%m%d")
        path = DEBUG_DIR / f"failed_{ts}_{stock_code}.html"
        path.write_text(html, encoding="utf-8")
        logger.info("Saved debug HTML to %s", path)


def save_snapshot(snap: CCASSSnapshot) -> None:
    """Write snapshot to DB. Idempotent (UPSERT)."""
    now_iso = datetime.utcnow().isoformat()
    # Compute top5/top10 concentration
    sorted_shares = sorted([h["shares"] for h in snap.holdings if h.get("shares")], reverse=True)
    top5 = sum(sorted_shares[:5])
    top10 = sum(sorted_shares[:10])
    top5_pct = round(top5 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    top10_pct = round(top10 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO ccass_daily
                 (stock_code, trade_date, total_shares, total_pct,
                  num_participants, top5_pct, top10_pct, scraped_at, validation_failed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                 total_shares = excluded.total_shares,
                 total_pct = excluded.total_pct,
                 num_participants = excluded.num_participants,
                 top5_pct = excluded.top5_pct,
                 top10_pct = excluded.top10_pct,
                 scraped_at = excluded.scraped_at,
                 validation_failed = 0""",
            (
                snap.stock_code,
                snap.trade_date,
                snap.total_shares,
                snap.total_pct,
                snap.num_participants,
                top5_pct,
                top10_pct,
                now_iso,
            ),
        )
        # Replace holdings for呢個 (stock, date)
        conn.execute(
            "DELETE FROM ccass_holdings WHERE stock_code = ? AND trade_date = ?",
            (snap.stock_code, snap.trade_date),
        )
        conn.executemany(
            """INSERT INTO ccass_holdings
                 (stock_code, trade_date, participant_id, participant_name,
                  shares, pct_of_issued)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    snap.stock_code,
                    snap.trade_date,
                    h["participant_id"],
                    h["participant_name"],
                    h["shares"],
                    h["pct_of_issued"],
                )
                for h in snap.holdings
            ],
        )
