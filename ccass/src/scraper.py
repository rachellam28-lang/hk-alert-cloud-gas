"""CCASS Scraper — Playwright edition.

HKEX CCASS Shareholding Search:
  https://www3.hkexnews.hk/sdw/search/searchsdw.aspx

Replaced cloudscraper with Playwright browser automation because cloudscraper
hangs indefinitely on Akamai WAF POST requests. Playwright runs a real
headless Chromium browser, which navigates the ASP.NET WebForms page
naturally — filling form fields and clicking the search button triggers
__doPostBack via the browser's JS engine, so Akamai sees genuine user
behaviour.

Responsibilities:
1. Scrape one stock for one date
2. Parse total holdings + participant breakdown
3. Schema validation (FATAL-003)
4. JSON serialisation (DB write is caller's job in shard mode)
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.sync_api import (
    sync_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    Error as PlaywrightError,
)

from src.db import get_conn
from src.logger import setup_logger

logger = setup_logger("scraper")

SDW_URL = "https://www3.hkexnews.hk/sdw/search/searchsdw.aspx"
DEBUG_DIR = Path(__file__).parent.parent / "debug"

# ── Playwright timeouts (milliseconds) ──────────────────────────────────────
NAVIGATION_TIMEOUT = 60_000       # page.goto / initial load
FORM_FILL_TIMEOUT = 15_000        # typing into form fields
CLICK_TIMEOUT = 15_000            # clicking the search button
RESULT_TIMEOUT = 30_000           # waiting for results table / message
BROWSER_LAUNCH_TIMEOUT = 30_000   # browser process startup


@dataclass
class CCASSSnapshot:
    stock_code: str
    trade_date: str          # YYYY-MM-DD
    total_shares: int
    total_pct: Optional[float]
    num_participants: int
    holdings: list[dict]     # [{participant_id, participant_name, shares, pct_of_issued}, ...]


class CCASSScraper:
    def __init__(
        self,
        user_agent: str,
        delay_min: float = 1.0,
        delay_max: float = 3.0,
        timeout: int = 30,
        max_retries: int = 3,
        headless: bool = True,
    ):
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.timeout = timeout
        self.max_retries = max_retries

        # Sliding window of recent request outcomes (True = blocked/failed).
        from collections import deque
        self._outcome_window: deque[bool] = deque(maxlen=12)
        self._abort_threshold = 7   # >=7 bad out of last 12 → HKEX down / blocked

        # Playwright state
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._user_agent = user_agent
        self._headless = headless
        self._page_ready = False     # True once we've navigated to SDW_URL at least once

        self._launch_browser()

    # ═══════════════════════════════════════════════════════════════════════
    #  Browser lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    def _launch_browser(self) -> None:
        """Launch headless Chromium. Each subprocess gets its own browser."""
        logger.info("Launching Playwright Chromium (headless=%s)...", self._headless)
        try:
            self._playwright = sync_playwright().start()
            # Try existing chromium installs first (avoid re-downloading)
            import os as _os
            _chromium_base = _os.path.expandvars(
                r"%LOCALAPPDATA%\ms-playwright"
            )
            _candidates = []
            for _entry in _os.listdir(_chromium_base) if _os.path.isdir(_chromium_base) else []:
                _chrome = _os.path.join(_chromium_base, _entry, "chrome-win64", "chrome.exe")
                if _os.path.isfile(_chrome):
                    _candidates.append(_chrome)
            _exe_path = _candidates[0] if _candidates else None
            if _exe_path:
                logger.info("Using existing Chromium: %s", _exe_path)
            self._browser = self._playwright.chromium.launch(
                headless=self._headless,
                executable_path=_exe_path,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
                timeout=BROWSER_LAUNCH_TIMEOUT,
            )
            logger.info("Playwright browser launched (pid=%s)", self._browser)
        except Exception as e:
            logger.error("Failed to launch Playwright browser: %s", e)
            self.close()
            raise

    def _ensure_page(self) -> Page:
        """Return a ready page, creating context + page + navigating if needed."""
        # Recover from browser crash (e.g., OOM, GPU crash)
        if self._browser is not None and not self._browser.is_connected():
            logger.warning("Browser disconnected — re-launching")
            self.close()
            self._launch_browser()

        if self._context is None:
            self._context = self._browser.new_context(
                user_agent=self._user_agent,
                viewport={"width": 1920, "height": 1080},
                locale="en-HK",
                timezone_id="Asia/Hong_Kong",
                # Additional stealth: hide webdriver flag
                bypass_csp=True,
            )
            # Inject stealth script to mask automation
            self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-HK','en-US','en']});
            """)

        if self._page is None or self._page.is_closed():
            self._page = self._context.new_page()
            self._page.set_default_navigation_timeout(NAVIGATION_TIMEOUT)
            self._page.set_default_timeout(FORM_FILL_TIMEOUT)
            self._page_ready = False

        if not self._page_ready:
            self._navigate_to_search()
            self._page_ready = True

        return self._page

    def _navigate_to_search(self) -> None:
        """Navigate to the CCASS search page and wait for the form."""
        logger.debug("Navigating to %s", SDW_URL)
        try:
            self._page.goto(
                SDW_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT,
            )
            # Wait for the stock-code input to appear (confirms form loaded)
            self._page.wait_for_selector(
                "#txtStockCode", state="visible", timeout=NAVIGATION_TIMEOUT,
            )
            logger.debug("CCASS search page loaded")
        except (PlaywrightTimeout, PlaywrightError) as e:
            logger.error("Failed to load CCASS search page: %s", e)
            raise RuntimeError(f"CCASS search page did not load: {e}")

    def close(self) -> None:
        """Release all Playwright resources."""
        for obj, name in [
            (self._page, "page"),
            (self._context, "context"),
            (self._browser, "browser"),
            (self._playwright, "playwright"),
        ]:
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        logger.debug("Playwright resources released")

    def __del__(self) -> None:
        self.close()

    # ═══════════════════════════════════════════════════════════════════════
    #  Public API (same interface as cloudscraper version)
    # ═══════════════════════════════════════════════════════════════════════

    def _refresh_form_tokens(self) -> None:
        """No-op: Playwright manages ASP.NET tokens through the browser.
        Kept for interface compatibility with callers that invoke this."""
        pass

    def scrape_stock(self, stock_code: str, query_date: date) -> Optional[CCASSSnapshot]:
        """Scrape one stock for one date. Returns None if no data or parse failure."""
        stock_code = stock_code.zfill(5)
        date_str = query_date.strftime("%Y/%m/%d")

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                page = self._ensure_page()

                # ── Fill the search form ──
                _safe_fill(page, "#txtStockCode", stock_code)
                _safe_fill(page, "#txtShareholdingDate", date_str)

                # ── Click Search ──
                # ASP.NET WebForms: <a id="btnSearch"> calls __doPostBack on click.
                search_btn = page.locator("#btnSearch")
                search_btn.click(timeout=CLICK_TIMEOUT)

                # ── Wait for results ──
                try:
                    page.wait_for_selector(
                        "#pnlResultSummary, .ccass-search-msg, #participantShareholding, "
                        "table.table-scroll, .ccass-search-result",
                        state="attached",
                        timeout=RESULT_TIMEOUT,
                    )
                except PlaywrightTimeout:
                    logger.warning(
                        "Timeout waiting for results on %s (attempt %d)",
                        stock_code, attempt,
                    )
                    self._record_outcome(True, stock_code)
                    self._reset_page_state()
                    time.sleep(min(15, 2 ** attempt))
                    continue

                # Small grace period for any async rendering
                page.wait_for_timeout(800)

                html = page.content()

                # ── Block detection ──
                if self._looks_like_block(html):
                    self._record_outcome(True, stock_code)
                    logger.warning(
                        "HTTP 200 but Akamai/WAF block page for %s (attempt %d)",
                        stock_code, attempt,
                    )
                    self._save_debug_html(stock_code, query_date, html)
                    self._reset_page_state()
                    time.sleep(min(15, 2 ** attempt))
                    continue

                # ── Genuine success ──
                self._record_outcome(False, stock_code)
                snapshot = self._parse(stock_code, query_date, html)
                self._polite_sleep()
                return snapshot

            except (PlaywrightTimeout, PlaywrightError) as e:
                last_err = e
                backoff = 2 ** attempt
                logger.warning(
                    "Scrape %s attempt %d Playwright error: %s. Sleeping %ds",
                    stock_code, attempt, e, backoff,
                )
                self._reset_page_state()
                time.sleep(backoff)

            except RuntimeError:
                # Re-raise abort signals so the caller (shard runner) can exit
                raise

            except Exception as e:
                last_err = e
                backoff = 2 ** attempt
                logger.warning(
                    "Scrape %s attempt %d failed: %s. Sleeping %ds",
                    stock_code, attempt, e, backoff,
                )
                self._reset_page_state()
                time.sleep(backoff)

        logger.error("Scrape %s exhausted retries (%s)", stock_code, last_err)
        return None

    def _reset_page_state(self) -> None:
        """Re-navigate to the search page after an error to get fresh tokens."""
        try:
            self._navigate_to_search()
            self._page_ready = True
        except Exception:
            # If re-navigation fails, force a fresh page next time
            self._page_ready = False
            if self._page and not self._page.is_closed():
                try:
                    self._page.close()
                except Exception:
                    pass
                self._page = None

    # ═══════════════════════════════════════════════════════════════════════
    #  Outcome tracking (same logic as cloudscraper version)
    # ═══════════════════════════════════════════════════════════════════════

    def _polite_sleep(self) -> None:
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def _record_outcome(self, bad: bool, stock_code: str) -> None:
        self._outcome_window.append(bad)
        bad_count = sum(self._outcome_window)
        if bad:
            logger.warning(
                "Bad response on %s (window %d/%d bad)",
                stock_code, bad_count, len(self._outcome_window),
            )
        if (
            len(self._outcome_window) == self._outcome_window.maxlen
            and bad_count >= self._abort_threshold
        ):
            raise RuntimeError(
                f"HKEX CCASS appears DOWN or BLOCKING — "
                f"{bad_count}/{len(self._outcome_window)} recent requests failed. "
                f"Aborting scrape."
            )

    @staticmethod
    def _looks_like_block(html: str) -> bool:
        """Detect Akamai / WAF block page that returns HTTP 200."""
        if not html:
            return True
        head = html[:3000].lower()
        markers = (
            "access denied",
            "reference&#32;",
            "reference #",
            "akamai",
            "errors.edgesuite.net",
            "you don't have permission to access",
            "/sdw/search/" not in html and "viewstate" not in head,
        )
        return any(m if isinstance(m, bool) else (m in head) for m in markers)

    # ═══════════════════════════════════════════════════════════════════════
    #  HTML parsing (unchanged from cloudscraper version)
    # ═══════════════════════════════════════════════════════════════════════

    def _parse(
        self, stock_code: str, query_date: date, html: str
    ) -> Optional[CCASSSnapshot]:
        """Parse CCASS HTML with schema validation."""
        soup = BeautifulSoup(html, "lxml")

        # 1. Detect "no data" message
        err_block = soup.find("div", class_="ccass-search-msg")
        if err_block:
            msg_text = err_block.get_text(strip=True).lower()
            if "no record" in msg_text or "no data" in msg_text or "not found" in msg_text:
                logger.info("No CCASS data for %s on %s", stock_code, query_date)
                return None
            logger.debug(
                "CCASS msg for %s: %s", stock_code, err_block.get_text(strip=True)[:200]
            )

        # Detect anti-bot / access-denied pages
        page_title = soup.find("title")
        if page_title:
            title_lc = page_title.get_text(strip=True).lower()
            if any(k in title_lc for k in ("access denied", "captcha", "403", "blocked")):
                logger.warning(
                    "Possible anti-bot page for %s: %s",
                    stock_code, page_title.get_text(strip=True)[:100],
                )
                return None

        # 2. Extract total shareholding
        total_shares = self._extract_total_shares(soup)
        total_pct = self._extract_total_pct(soup)

        if total_shares is None:
            total_shares = self._extract_total_from_text(html)
            if total_shares:
                logger.debug(
                    "Used regex fallback total_shares for %s: %d", stock_code, total_shares
                )

        if total_shares is None:
            self._save_debug_html(stock_code, query_date, html)
            body_snip = BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)[:400]
            logger.warning(
                "Schema validation failed for %s on %s: total_shares not found. Snippet: %s",
                stock_code, query_date, body_snip,
            )
            return None

        # 3. Extract participant breakdown
        holdings = self._extract_holdings(soup)

        # 4. Sanity checks (FATAL-003)
        if total_shares < 0 or total_shares > 1e15:
            self._save_debug_html(stock_code, query_date, html)
            logger.warning(
                "Schema validation failed for %s: total_shares=%d out of range",
                stock_code, total_shares,
            )
            return None

        if total_pct is not None and (total_pct < 0 or total_pct > 100):
            logger.warning(
                "total_pct out of range for %s: %.4f, clamping", stock_code, total_pct,
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
        """Multi-strategy extraction of CCASS total shareholding count."""
        # Strategy 1: ccass-search-total row
        total_row = soup.find("div", class_="ccass-search-total")
        if total_row:
            val = total_row.find("div", class_="value")
            if val:
                num = CCASSScraper._parse_number(val.get_text(strip=True))
                if num and num > 0:
                    return num

        # Strategy 2: "Total number of Issued Shares/Warrants/Units"
        label = soup.find(string=re.compile(r"Total number of Issued Shares", re.I))
        if label:
            summary_val = label.find_next("div", class_="summary-value")
            if summary_val:
                num = CCASSScraper._parse_number(summary_val.get_text(strip=True))
                if num and num > 0:
                    return num

        # Strategy 3: sum participant categories (old layout fallback)
        total = 0
        for label_text in [
            "Market Intermediaries",
            "Consenting Investor Participants",
            "Non-consenting Investor Participants",
        ]:
            el = soup.find(string=re.compile(re.escape(label_text), re.I))
            if el:
                parent = el.find_parent()
                body = (
                    parent.find("div", class_="mobile-list-body")
                    or parent.find_next("div", class_="value")
                    or parent.find_next("td")
                )
                if body:
                    num = CCASSScraper._parse_number(body.get_text(strip=True))
                    if num and num > 0:
                        total += num
        return total if total > 0 else None

    @staticmethod
    def _extract_total_from_text(html: str) -> Optional[int]:
        """Last-resort: find most-frequent large number (≥10M) in raw HTML."""
        from collections import Counter

        candidates = re.findall(r"(?<![0-9])([0-9]{1,3}(?:,[0-9]{3}){2,})", html)
        nums = []
        for c in candidates:
            try:
                n = int(c.replace(",", ""))
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

        # Fallback: find % label and get next value
        el = soup.find(
            string=re.compile(r"% of the total number of Issued Shares", re.I)
        )
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
        """Extract participant table using CSS class selectors."""
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
            pid_td = tr.find("td", class_=re.compile(r"col-participant-id", re.I))
            name_td = tr.find("td", class_=re.compile(r"col-participant-name", re.I))
            share_td = tr.find("td", class_=re.compile(r"col-shareholding", re.I))
            pct_td = tr.find("td", class_=re.compile(r"col-shareholding-percent", re.I))

            if pid_td and share_td:
                pid = _cell_val(pid_td)
                name = _cell_val(name_td) if name_td else ""
                shares_txt = _cell_val(share_td)
                pct_txt = _cell_val(pct_td) if pct_td else ""
            elif len(tds) >= 5:
                pid, name, _, shares_txt, pct_txt = (
                    _cell_val(tds[0]),
                    _cell_val(tds[1]),
                    _cell_val(tds[2]),
                    _cell_val(tds[3]),
                    _cell_val(tds[4]),
                )
            elif len(tds) >= 4:
                pid, name, shares_txt, pct_txt = (
                    _cell_val(tds[0]),
                    _cell_val(tds[1]),
                    _cell_val(tds[2]),
                    _cell_val(tds[3]),
                )
            else:
                continue

            shares = CCASSScraper._parse_number(shares_txt)
            try:
                pct = float(pct_txt.rstrip("%").strip())
            except ValueError:
                pct = None

            if pid and shares is not None:
                rows.append({
                    "participant_id": pid,
                    "participant_name": name,
                    "shares": shares,
                    "pct_of_issued": pct,
                })
        return rows

    @staticmethod
    def _parse_number(text: str) -> Optional[int]:
        """Parse '1,234,567' → 1234567."""
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


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _safe_fill(page: Page, selector: str, value: str) -> None:
    """Fill a form field robustly. Handles ASP.NET read-only inputs by
    using JavaScript to set the value directly, then dispatching events
    so __doPostBack / ViewState picks it up."""
    loc = page.locator(selector)
    loc.wait_for(state="visible", timeout=FORM_FILL_TIMEOUT)

    # Check if the input is read-only; if so, use JS to force-set the value
    is_readonly = loc.evaluate("el => el.readOnly || el.getAttribute('readonly') !== null")

    if is_readonly:
        # Remove readonly (both attribute and DOM property), set value via JS
        loc.evaluate(
            """(el, val) => {
                el.readOnly = false;
                el.removeAttribute('readonly');
                el.value = val;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.readOnly = true;
                el.setAttribute('readonly', 'readonly');
            }""",
            value,
        )
    else:
        # Normal fill: triple-click to select all, then type
        loc.click(click_count=3, timeout=FORM_FILL_TIMEOUT)
        loc.fill(value, timeout=FORM_FILL_TIMEOUT)


# ═══════════════════════════════════════════════════════════════════════════
#  DB persistence (unchanged from cloudscraper version)
# ═══════════════════════════════════════════════════════════════════════════

def save_snapshot(snap: CCASSSnapshot) -> None:
    """Write snapshot to DB. Idempotent (UPSERT)."""
    now_iso = datetime.utcnow().isoformat()
    # Compute top5/top10 concentration
    sorted_shares = sorted(
        [h["shares"] for h in snap.holdings if h.get("shares")], reverse=True
    )
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
        # Replace holdings for this (stock, date)
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
