"""HOLDINGS Scraper.

HKEX HOLDINGS Shareholding Search:
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
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup

from src.db import get_conn
from src.logger import setup_logger

logger = setup_logger("scraper")

SDW_URL = "https://www3.hkexnews.hk/sdw/search/searchsdw.aspx"

DEBUG_DIR = Path(__file__).parent.parent / "debug"


@dataclass
class HOLDINGSSnapshot:
    stock_code: str
    trade_date: str          # YYYY-MM-DD
    total_shares: int
    total_pct: Optional[float]
    num_participants: int
    holdings: list[dict]     # [{participant_id, name, shares, pct}, ...]


class HKEXBlockedError(RuntimeError):
    """HKEX HOLDINGS is blocking/rate-limiting this IP. Propagate to exit 2."""
    pass


class HOLDINGSScraper:
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
        # Sliding window of recent request outcomes (True = 503/blocked).
        # We abort only if the window is full AND mostly failures, so a
        # single stray 200 in the middle can no longer reset us to zero.
        from collections import deque
        self._outcome_window: deque[bool] = deque(maxlen=8)
        self._abort_threshold = 6   # >=6 bad out of last 8 -> HKEX down / blocked
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.session.timeout = self.timeout
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
            raise RuntimeError("Cannot find __VIEWSTATE on HOLDINGS search page")
        logger.info("Got %d form tokens: %s", len(tokens), list(tokens.keys()))
        # Log form field names to diagnose structure changes
        all_inputs = [(el.get("name",""), el.get("type",""), el.get("value","")[:30] if el.get("value") else "")
                      for el in soup.find_all("input")]
        logger.info("All form inputs: %s", all_inputs)
        self._form_tokens = tokens
        self._last_token_refresh = now

    def _polite_sleep(self) -> None:
        if os.environ.get("HOLDINGS_ULTRA_FAST", "0") == "1":
            return
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def _record_outcome(self, bad: bool, stock_code: str) -> None:
        """Record one request outcome; raise HKEXBlockedError if HKEX looks down.

        bad is True for a 503 OR an Akamai access-denied page. We abort
        when the recent window is saturated with failures, instead of
        requiring a strictly-consecutive streak (which a stray 200 reset).
        """
        self._outcome_window.append(bad)
        bad_count = sum(self._outcome_window)
        if bad:
            logger.warning(
                "Bad response on %s (window %d/%d bad)",
                stock_code, bad_count, len(self._outcome_window),
            )
        if (len(self._outcome_window) == self._outcome_window.maxlen
                and bad_count >= self._abort_threshold):
            raise HKEXBlockedError(
                f"HKEX HOLDINGS appears DOWN or BLOCKING — "
                f"{bad_count}/{len(self._outcome_window)} recent requests failed. "
                f"Aborting scrape."
            )

    @staticmethod
    def _looks_like_block(html: str) -> bool:
        """Detect an Akamai / WAF block page that still returns HTTP 200.

        Akamai frequently answers bots with a 200-status 'Access Denied'
        or reference-error page. Treating that as success is what let the
        old consecutive-503 counter reset and never fire.
        
        Note: empty html is NOT automatically treated as blocked — it could
        be a network error, not a WAF response.
        """
        if not html:
            return False
        head = html[:10000].lower()  # P2-2: increase from 3000 to catch viewstate in large pages
        markers = (
            "access denied",
            "reference&#32;",
            "reference #",
            "akamai",
            "errors.edgesuite.net",
            "you don't have permission to access",
            "/sdw/search/" not in html and "viewstate" not in head,
        )
        # The last tuple entry is already a bool; the rest are substring tests.
        return any(m if isinstance(m, bool) else (m in head) for m in markers)

    def scrape_stock(self, stock_code: str, query_date: date) -> Optional[HOLDINGSSnapshot]:
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

                # HKEX outage / rate-limit handling
                if resp.status_code == 503:
                    self._record_outcome(True, stock_code)   # may raise -> abort
                    time.sleep(15)
                    continue
                if resp.status_code == 429:
                    self._record_outcome(True, stock_code)   # may raise -> abort
                    logger.warning("Rate limited (429) on %s, sleeping 30s", stock_code)
                    time.sleep(30)
                    continue

                # HTTP 200 is NOT automatically a success — Akamai serves
                # block pages with status 200. Check the body first.
                if self._looks_like_block(resp.text):
                    self._record_outcome(True, stock_code)   # may raise -> abort
                    logger.warning(
                        "HTTP 200 but looks like an Akamai block page for %s; "
                        "treating as failure", stock_code,
                    )
                    self._save_debug_html(stock_code, query_date, resp.text)
                    time.sleep(15)
                    continue

                # Genuine success
                self._record_outcome(False, stock_code)
                resp.raise_for_status()

                snapshot = self._parse(stock_code, query_date, resp.text)
                self._polite_sleep()
                return snapshot

            except HKEXBlockedError:
                # Don't catch — propagate to runner for exit(2)
                raise
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
    ) -> Optional[HOLDINGSSnapshot]:
        """Parse HOLDINGS HTML. 加 schema validation。"""
        soup = BeautifulSoup(html, "lxml")

        # 1. 偵測「冇數據」: HKEX 會 render error message
        err_block = soup.find("div", class_="holdings-search-msg")
        if err_block:
            msg_text = err_block.get_text(strip=True).lower()
            if "no record" in msg_text or "no data" in msg_text or "not found" in msg_text:
                logger.info("No HOLDINGS data for %s on %s", stock_code, query_date)
                return None
            logger.debug("HOLDINGS msg for %s: %s", stock_code, err_block.get_text(strip=True)[:200])
        # Detect anti-bot / access-denied pages
        page_title = soup.find("title")
        if page_title:
            title_lc = page_title.get_text(strip=True).lower()
            if any(k in title_lc for k in ("access denied", "captcha", "403", "blocked")):
                logger.warning("Possible anti-bot page for %s: %s", stock_code, page_title.get_text(strip=True)[:100])
                return None

        # 2. 攞 total shareholding
        # HKEX 用 <div class="holdings-search-total"> 包總數
        total_section = soup.find("div", id="pnlResultSummary") or soup.find(
            "div", class_="holdings-search-result"
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

        return HOLDINGSSnapshot(
            stock_code=stock_code,
            trade_date=query_date.strftime("%Y-%m-%d"),
            total_shares=total_shares,
            total_pct=total_pct,
            num_participants=len(holdings),
            holdings=holdings,
        )

    @staticmethod
    def _extract_total_shares(soup: BeautifulSoup) -> Optional[int]:
        """多層次 strategy 搵 HOLDINGS total shareholding count。

        Strategy 1: 搵 holdings-search-total row 嘅 shareholding value
        Strategy 2: 搵 "Total number of Issued Shares/Warrants/Units" summary value
        Strategy 3: sum Market Intermediaries + Investor Participants
        """
        # Strategy 1: holdings-search-total row
        total_row = soup.find("div", class_="holdings-search-total")
        if total_row:
            val = total_row.find("div", class_="value")
            if val:
                num = HOLDINGSScraper._parse_number(val.get_text(strip=True))
                if num and num > 0:
                    return num
        # Strategy 2: Total number of Issued Shares/Warrants/Units
        label = soup.find(string=re.compile(
            r"Total number of Issued Shares", re.I))
        if label:
            summary_val = label.find_next("div", class_="summary-value")
            if summary_val:
                num = HOLDINGSScraper._parse_number(
                    summary_val.get_text(strip=True))
                if num and num > 0:
                    return num
        # Strategy 3: sum participants (old page layout fallback)
        # P2-4: add more participant categories for complete coverage
        total = 0
        for label_text in ["Market Intermediaries",
                            "Consenting Investor Participants",
                            "Non-consenting Investor Participants",
                            "Settlement Agents",
                            "Custodian Participants"]:
            el = soup.find(string=re.compile(
                re.escape(label_text), re.I))
            if el:
                parent = el.find_parent()
                body = (parent.find("div", class_="mobile-list-body") or
                        parent.find_next("div", class_="value") or
                        parent.find_next("td"))
                if body:
                    num = HOLDINGSScraper._parse_number(
                        body.get_text(strip=True))
                    if num and num > 0:
                        total += num
        return total if total > 0 else None

    @staticmethod
    def _extract_total_from_text(html: str) -> Optional[int]:
        """Last-resort: find most-frequent large number (>=10M) in raw HTML — likely total shares."""
        from collections import Counter
        candidates = re.findall(r'(?<![0-9])([0-9]{1,3}(?:,[0-9]{3}){2,})', html)
        # ✅ P1-7: also match unformatted large numbers (>=10M without commas)
        if not candidates:
            candidates = re.findall(r'(?<![0-9])([0-9]{8,})(?![0-9])', html)
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
        total_row = soup.find("div", class_="holdings-search-total")
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
            shares = HOLDINGSScraper._parse_number(shares_txt)
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


def _compute_concentration_metrics(holdings: list[dict]) -> dict:
    """Sentinel Option A: A00005-only strip, broker-top5, FUTU tracking.

    A00005 = CSDC immobilized domestic shares. NOT tradable on HKEX.
    A00003/A00004 = Stock Connect = REAL tradable liquidity → stays.
    """
    clean = [h for h in holdings if h.get("shares")]
    total = sum(h["shares"] for h in clean)
    if total <= 0:
        return {}

    a5_shares = sum(h["shares"] for h in clean if h.get("participant_id") == "A00005")
    adjusted_float = total - a5_shares

    # Everyone except A00005 (includes A00003/A00004 Stock Connect)
    adjusted = sorted(
        [h for h in clean if h.get("participant_id") != "A00005"],
        key=lambda h: h["shares"], reverse=True,
    )
    brokers = [h for h in adjusted if str(h.get("participant_id", "")).startswith("B")]
    top_broker = brokers[0] if brokers else None
    futu_shares = sum(h["shares"] for h in adjusted if h.get("participant_id") == "B01955")

    if adjusted_float > 0:
        adj_hhi = sum((h["shares"] / adjusted_float * 100) ** 2 for h in adjusted)
        btop5 = sum(h["shares"] for h in brokers[:5]) / adjusted_float * 100
        tbp = top_broker["shares"] / adjusted_float * 100 if top_broker else 0.0
        fp = futu_shares / adjusted_float * 100
    else:
        adj_hhi = btop5 = tbp = fp = 0.0

    return {
        "adj_hhi": round(adj_hhi, 1),
        "broker_top5_pct": round(btop5, 2),
        "top_broker_id": top_broker["participant_id"] if top_broker else "",
        "top_broker_name": (top_broker.get("participant_name") or "")[:40] if top_broker else "",
        "top_broker_pct": round(tbp, 2),
        "futu_pct": round(fp, 2),
        "a00005_pct": round(a5_shares / total * 100, 2),
        "adjusted_float": adjusted_float,
    }


def save_snapshot(snap: HOLDINGSSnapshot) -> None:
    """Write snapshot to DB. Idempotent (UPSERT)."""
    now_iso = datetime.utcnow().isoformat()
    # Compute top5/top10 concentration (raw — all participants)
    sorted_shares = sorted([h["shares"] for h in snap.holdings if h.get("shares")], reverse=True)
    top5 = sum(sorted_shares[:5])
    top10 = sum(sorted_shares[:10])
    top5_pct = round(top5 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    top10_pct = round(top10 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None

    # Sentinel Option A concentration metrics (ex-A00005)
    cm = _compute_concentration_metrics(snap.holdings)

    with get_conn() as conn:
        # ✅ P0-4 fix: single atomic transaction for daily + holdings
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """INSERT INTO ccass_daily
                     (stock_code, trade_date, total_shares, total_pct,
                      num_participants, top5_pct, top10_pct,
                      adj_hhi, broker_top5_pct, top_broker_id, top_broker_name,
                      top_broker_pct, futu_pct, a00005_pct, adjusted_float,
                      scraped_at, validation_failed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                   ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                     total_shares = excluded.total_shares,
                     total_pct = excluded.total_pct,
                     num_participants = excluded.num_participants,
                     top5_pct = excluded.top5_pct,
                     top10_pct = excluded.top10_pct,
                     adj_hhi = excluded.adj_hhi,
                     broker_top5_pct = excluded.broker_top5_pct,
                     top_broker_id = excluded.top_broker_id,
                     top_broker_name = excluded.top_broker_name,
                     top_broker_pct = excluded.top_broker_pct,
                     futu_pct = excluded.futu_pct,
                     a00005_pct = excluded.a00005_pct,
                     adjusted_float = excluded.adjusted_float,
                     scraped_at = excluded.scraped_at,
                     validation_failed = 0""",
                (
                    snap.stock_code, snap.trade_date, snap.total_shares,
                    snap.total_pct, snap.num_participants, top5_pct, top10_pct,
                    cm.get("adj_hhi"), cm.get("broker_top5_pct"),
                    cm.get("top_broker_id"), cm.get("top_broker_name"),
                    cm.get("top_broker_pct"), cm.get("futu_pct"),
                    cm.get("a00005_pct"), cm.get("adjusted_float"), now_iso,
                ),
            )
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
                    (snap.stock_code, snap.trade_date,
                     h["participant_id"], h["participant_name"],
                     h["shares"], h["pct_of_issued"])
                    for h in snap.holdings
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
