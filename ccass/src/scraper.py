"""CCASS Scraper — Playwright edition with sustainable anti-blocking.

HKEX CCASS Shareholding Search:
  https://www3.hkexnews.hk/sdw/search/searchsdw.aspx

Anti-blocking strategy (v2 — May 2026):
1. Tiered cooldown: When Akamai blocks, enter escalating cooldown periods
   (5→10→20 min) with full browser session rotation. No more RuntimeError
   that wastes hours on already-blocked sessions.
2. Batch breaks: After every ~50-80 successful stocks, take a human-like
   coffee break (30-120s) to avoid detection.
3. Enhanced stealth: rotating UA pool, randomised viewport, comprehensive
   JS property masking.
4. Smart retry: Individual request failures get exponential backoff, but
   the overall window state resets after successful cooldown recovery.

FATAL-003 remains: delays must stay within human range (3-8s between
stocks). We trade speed for reliability.
"""
from __future__ import annotations

import random
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
RESULT_TIMEOUT = 15_000           # waiting for results table / message
BROWSER_LAUNCH_TIMEOUT = 30_000   # browser process startup

# ── Anti-blocking constants ─────────────────────────────────────────────────
# Outcome window: track last 12 request outcomes
OUTCOME_WINDOW_SIZE = 12
ABORT_THRESHOLD = 7               # >=7 bad out of last 12 → enter cooldown
WARNING_THRESHOLD = 5              # >=5 bad → slow down preemptively

# Cooldown tiers (seconds) — escalates on repeated blocks
COOLDOWN_TIER_1 = (300, 600)      # 5-10 min (first block)
COOLDOWN_TIER_2 = (600, 1200)     # 10-20 min (second block)
COOLDOWN_TIER_3 = (1200, 1800)    # 20-30 min (third+ block)

# Batch breaks — mimic human coffee breaks
BATCH_SIZE = 60                   # take a break after this many successes
BATCH_BREAK = (30, 90)            # pause 30-90 seconds

# Rotating user-agent pool (recent Chrome versions on Win/Mac)
_USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


@dataclass
class CCASSSnapshot:
    stock_code: str
    trade_date: str          # YYYY-MM-DD
    total_shares: int
    total_pct: Optional[float]
    num_participants: int
    holdings: list[dict]     # [{participant_id, participant_name, shares, pct_of_issued}, ...]


# ── Enhanced stealth init script ────────────────────────────────────────────
# More comprehensive than the old version — masks additional fingerprint
# vectors that Akamai/Bot Manager checks.
_STEALTH_INIT_SCRIPT = """
// 1. Hide webdriver flag (multiple variants)
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, '__webdriver_evaluate', {get: () => undefined});
Object.defineProperty(navigator, '__driver_evaluate', {get: () => undefined});
Object.defineProperty(navigator, '__webdriver_script_function', {get: () => undefined});
Object.defineProperty(navigator, '__webdriver_script_func', {get: () => undefined});
Object.defineProperty(navigator, '__webdriver_script_fn', {get: () => undefined});
Object.defineProperty(navigator, '__fxdriver_evaluate', {get: () => undefined});
Object.defineProperty(navigator, '__driver_unwrapped', {get: () => undefined});
Object.defineProperty(navigator, '__webdriver_unwrapped', {get: () => undefined});

// 2. Mask Chrome automation flags
Object.defineProperty(document, 'hidden', {get: () => false});
Object.defineProperty(document, 'visibilityState', {get: () => 'visible'});

// 3. Fake plugins (real browsers have plugins)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [1, 2, 3, 4, 5];
        plugins.item = (i) => plugins[i];
        plugins.namedItem = (name) => null;
        plugins.refresh = () => {};
        return plugins;
    }
});

// 4. Fake languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-HK', 'zh-HK', 'en-US', 'en', 'zh']
});

// 5. Fake permissions API (headless chrome has quirks)
const originalQuery = window.navigator.permissions?.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({state: Notification.permission}) :
            originalQuery(parameters)
    );
}

// 6. Mask chrome runtime (headless detection)
window.chrome = {
    runtime: {},
    loadTimes: () => {},
    csi: () => {},
    app: {}
};

// 7. Override toString for masked functions
const originalToString = Function.prototype.toString;
Function.prototype.toString = function() {
    if (this === window.chrome.runtime || this === window.chrome.loadTimes) {
        return 'function () { [native code] }';
    }
    return originalToString.call(this);
};
"""


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

        # ── Anti-blocking state ──
        # Sliding window: track recent request outcomes (True = bad/failed)
        self._outcome_window: deque[bool] = deque(maxlen=OUTCOME_WINDOW_SIZE)

        # Cooldown state machine
        self._blocked_until: Optional[datetime] = None  # UTC timestamp
        self._cooldown_tier: int = 0                     # 0=normal, 1,2,3+
        self._consecutive_bad: int = 0                    # count of consecutive bad
        self._consecutive_good: int = 0                   # count of consecutive good

        # Batch break tracking
        self._batch_counter: int = 0                       # successes since last break

        # User agent rotation
        self._user_agent_pool: list[str] = list(_USER_AGENT_POOL)
        self._current_ua_index: int = 0

        # Playwright state
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._user_agent = user_agent
        self._headless = headless
        self._page_ready = False

        self._launch_browser()

    # ═══════════════════════════════════════════════════════════════════════
    #  Browser lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    def _launch_browser(self) -> None:
        """Launch headless Chromium with anti-detection flags."""
        logger.info("Launching Playwright Chromium (headless=%s)...", self._headless)
        try:
            self._playwright = sync_playwright().start()
            # Try existing chromium installs first
            import os as _os
            _chromium_base = _os.path.expandvars(
                r"%LOCALAPPDATA%\ms-playwright"
            )
            _candidates = []
            for _entry in _os.listdir(_chromium_base) if _os.path.isdir(_chromium_base) else []:
                _chrome = _os.path.join(_chromium_base, _entry, "chrome-win64", "chrome.exe")
                if _os.path.isfile(_chrome):
                    _candidates.append(_chrome)
            _exe_path = _candidates[-1] if _candidates else None  # newest
            if _exe_path:
                logger.info("Using existing Chromium: %s", _exe_path)

            self._browser = self._playwright.chromium.launch(
                headless=self._headless,
                executable_path=_exe_path,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    # Anti-detection flags
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-features=WebRtcHideLocalIpsWithMdns",
                    "--disable-features=OptimizationHints,TranslateUI",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--mute-audio",
                    "--no-default-browser-check",
                    "--no-first-run",
                    "--no-pings",
                ],
                timeout=BROWSER_LAUNCH_TIMEOUT,
            )
            logger.info("Playwright browser launched (pid=%s)", self._browser)
        except Exception as e:
            logger.error("Failed to launch Playwright browser: %s", e)
            self.close()
            raise

    def _rotate_user_agent(self) -> str:
        """Return next user agent from the rotation pool."""
        ua = self._user_agent_pool[self._current_ua_index]
        self._current_ua_index = (self._current_ua_index + 1) % len(self._user_agent_pool)
        return ua

    def _random_viewport(self) -> dict:
        """Randomised viewport size to avoid fingerprinting."""
        return {
            "width": random.randint(1500, 1920),
            "height": random.randint(800, 1080),
        }

    def _ensure_context(self) -> BrowserContext:
        """Create or return browser context with fresh stealth profile."""
        if self._context is None:
            ua = self._rotate_user_agent()
            vp = self._random_viewport()
            logger.debug("New context: UA=%s..., viewport=%s", ua[:50], vp)
            self._context = self._browser.new_context(
                user_agent=ua,
                viewport=vp,
                locale="en-HK",
                timezone_id="Asia/Hong_Kong",
                bypass_csp=True,
                # No extra permissions
                permissions=[],
            )
            # Block heavy assets to save bandwidth/RAM
            self._context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "font", "media", "stylesheet")
                else route.continue_(),
            )
            # Inject enhanced stealth script
            self._context.add_init_script(_STEALTH_INIT_SCRIPT)
        return self._context

    def _rotate_browser_session(self) -> None:
        """Destroy current context and create a fresh one.
        
        This is the key recovery mechanism: when Akamai blocks us,
        we get a completely fresh session (new cookies, new fingerprint,
        new user agent, new viewport). This usually clears the block.
        """
        logger.info("Rotating browser session (cooldown tier %d)...", self._cooldown_tier)
        # Close old context and page
        for obj in [self._page, self._context]:
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        self._page = None
        self._context = None
        self._page_ready = False

        # If browser is still healthy, just recreate context
        if self._browser and self._browser.is_connected():
            self._ensure_context()
        else:
            # Browser died — relaunch
            logger.warning("Browser disconnected, re-launching...")
            self._browser = None
            self._launch_browser()

    def _ensure_page(self) -> Page:
        """Return a ready page, handling browser crashes and cooldown states."""
        # Check if browser is still connected
        if self._browser is not None and not self._browser.is_connected():
            logger.warning("Browser disconnected — re-launching")
            self.close()
            self._launch_browser()

        self._ensure_context()

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
            # Wait for the stock-code input to appear
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
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.debug("Playwright resources released")

    def __del__(self) -> None:
        self.close()

    # ═══════════════════════════════════════════════════════════════════════
    #  Anti-blocking: cooldown state machine
    # ═══════════════════════════════════════════════════════════════════════

    def _is_in_cooldown(self) -> bool:
        """Check if we're currently in a cooldown period."""
        if self._blocked_until is None:
            return False
        if datetime.utcnow() >= self._blocked_until:
            # Cooldown expired
            self._blocked_until = None
            return False
        return True

    def _enter_cooldown(self, reason: str = "blocked") -> None:
        """Enter escalating cooldown mode after being blocked.
        
        Each cooldown rotates the browser session for a fresh identity.
        Cooldown duration increases with each repeated block.
        """
        if self._is_in_cooldown():
            logger.debug("Already in cooldown until %s", self._blocked_until)
            return

        self._cooldown_tier = min(self._cooldown_tier + 1, 3)

        if self._cooldown_tier == 1:
            tier_range = COOLDOWN_TIER_1
        elif self._cooldown_tier == 2:
            tier_range = COOLDOWN_TIER_2
        else:
            tier_range = COOLDOWN_TIER_3

        cooldown_seconds = random.uniform(*tier_range)
        cooldown_minutes = cooldown_seconds / 60
        self._blocked_until = datetime.utcnow() + timedelta(seconds=cooldown_seconds)

        logger.warning(
            "⏸️ ENTERING COOLDOWN (tier %d): %.1f min — %s. "
            "Rotating browser session...",
            self._cooldown_tier, cooldown_minutes, reason,
        )

        # Rotate browser session for fresh identity
        self._rotate_browser_session()

        # Reset outcome tracking — fresh start after cooldown
        self._outcome_window.clear()
        self._consecutive_bad = 0

        logger.info(
            "Cooldown active until %s UTC. "
            "Outcome window reset. %d blocks this session.",
            self._blocked_until.strftime("%H:%M:%S"),
            self._cooldown_tier,
        )

    def _check_batch_break(self) -> None:
        """Take a coffee break after a batch of successful requests.
        
        Mimics human behaviour: after ~50-80 stocks, pause for 30-90 seconds.
        This prevents Akamai from detecting a sustained high-rate pattern.
        """
        self._batch_counter += 1
        if self._batch_counter >= BATCH_SIZE:
            break_seconds = random.uniform(*BATCH_BREAK)
            logger.info(
                "☕ Batch break: %d stocks done, pausing %.0fs...",
                self._batch_counter, break_seconds,
            )
            time.sleep(break_seconds)
            self._batch_counter = 0

    def _record_outcome(self, bad: bool, stock_code: str) -> None:
        """Record request outcome and manage anti-blocking state machine.
        
        NO LONGER raises RuntimeError! Instead:
        - Tracks sliding window of outcomes
        - Enters escalating cooldown when threshold hit
        - Recovers gracefully after cooldown expires
        - Tracks warning threshold for preemptive slowdown
        """
        self._outcome_window.append(bad)

        if bad:
            self._consecutive_bad += 1
            self._consecutive_good = 0
        else:
            self._consecutive_good += 1
            self._consecutive_bad = 0

        bad_count = sum(self._outcome_window)
        window_len = len(self._outcome_window)

        if bad:
            logger.warning(
                "Bad response on %s (window %d/%d bad, consecutive=%d)",
                stock_code, bad_count, window_len, self._consecutive_bad,
            )

        # ── Warning threshold: slow down preemptively ──
        if (
            window_len >= OUTCOME_WINDOW_SIZE
            and bad_count >= WARNING_THRESHOLD
            and bad_count < ABORT_THRESHOLD
            and not self._is_in_cooldown()
        ):
            extra_pause = random.uniform(5, 10)
            logger.warning(
                "⚠️  Warning threshold hit (%d/%d bad) — extra pause %.1fs",
                bad_count, window_len, extra_pause,
            )
            time.sleep(extra_pause)

        # ── Abort threshold: enter cooldown (DON'T raise RuntimeError!) ──
        if (
            window_len >= OUTCOME_WINDOW_SIZE
            and bad_count >= ABORT_THRESHOLD
            and not self._is_in_cooldown()
        ):
            self._enter_cooldown(
                reason=f"{bad_count}/{window_len} recent requests failed"
            )

    # ═══════════════════════════════════════════════════════════════════════
    #  Public API
    # ═══════════════════════════════════════════════════════════════════════

    def _refresh_form_tokens(self) -> None:
        """No-op: Playwright manages ASP.NET tokens through the browser.
        Kept for interface compatibility."""
        pass

    def scrape_stock(self, stock_code: str, query_date: date) -> Optional[CCASSSnapshot]:
        """Scrape one stock for one date. Returns None if no data, blocked, or failure.

        Anti-blocking flow:
        1. Check if we're in cooldown → return None immediately (don't waste time)
        2. Try scraping with retries
        3. On failure: record outcome → may trigger cooldown
        4. On success: record outcome + check batch break
        """
        # ── Cooldown check: don't even try if we're blocked ──
        if self._is_in_cooldown():
            remaining = (self._blocked_until - datetime.utcnow()).total_seconds()
            logger.debug(
                "In cooldown (%.0fs remaining), skipping %s",
                remaining, stock_code,
            )
            return None

        stock_code = stock_code.zfill(5)
        date_str = query_date.strftime("%Y/%m/%d")

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                page = self._ensure_page()

                # ── Quick pre-check: is the page responsive? ──
                # After cooldown, first navigation test
                try:
                    page.wait_for_selector(
                        "#txtStockCode", state="visible", timeout=5000,
                    )
                except PlaywrightTimeout:
                    logger.warning(
                        "Page unresponsive after cooldown for %s (attempt %d) — "
                        "may still be blocked",
                        stock_code, attempt,
                    )
                    self._record_outcome(True, stock_code)
                    self._reset_page_state()
                    time.sleep(min(10, 2 ** attempt))
                    continue

                # ── Fill the search form ──
                _safe_fill(page, "#txtStockCode", stock_code)
                _safe_fill(page, "#txtShareholdingDate", date_str)

                # ── Click Search ──
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
                    # Shorter backoff since we already track with cooldown system
                    time.sleep(min(8, 2 ** attempt))
                    continue

                # Small grace period for async rendering
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
                    time.sleep(min(10, 2 ** attempt))
                    continue

                # ── Genuine success ──
                self._record_outcome(False, stock_code)
                snapshot = self._parse(stock_code, query_date, html)

                # After success, check batch break
                self._check_batch_break()

                # Polite delay between successful requests
                self._polite_sleep()
                return snapshot

            except (PlaywrightTimeout, PlaywrightError) as e:
                last_err = e
                backoff = 2 ** attempt
                logger.warning(
                    "Scrape %s attempt %d Playwright error: %s. Sleeping %ds",
                    stock_code, attempt, e, backoff,
                )
                self._record_outcome(True, stock_code)
                self._reset_page_state()
                time.sleep(min(backoff, 15))

            except Exception as e:
                last_err = e
                backoff = 2 ** attempt
                logger.warning(
                    "Scrape %s attempt %d failed: %s. Sleeping %ds",
                    stock_code, attempt, e, backoff,
                )
                self._record_outcome(True, stock_code)
                self._reset_page_state()
                time.sleep(min(backoff, 15))

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
    #  Delay helpers
    # ═══════════════════════════════════════════════════════════════════════

    def _polite_sleep(self) -> None:
        """Random delay between successful requests (human-like)."""
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    # ═══════════════════════════════════════════════════════════════════════
    #  Block detection (unchanged)
    # ═══════════════════════════════════════════════════════════════════════

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
    #  HTML parsing (unchanged from original)
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

        # Detect "not available / does not exist" via hidden #alertMsg input
        alert_input = soup.find("input", id="alertMsg")
        if alert_input:
            msg_text = (alert_input.get("value") or "").strip().lower()
            if any(k in msg_text for k in (
                "does not exist", "not available for enquiry",
                "no record", "no data", "not found",
            )):
                logger.info(
                    "No CCASS data for %s on %s: %s",
                    stock_code, query_date, msg_text[:160],
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
        """Last-resort: find most-frequent large number (>=10M) in raw HTML."""
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
        """Parse '1,234,567' -> 1234567."""
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
#  Form helpers
# ═══════════════════════════════════════════════════════════════════════════

def _safe_fill(page: Page, selector: str, value: str) -> None:
    """Fill a form field robustly. Handles ASP.NET read-only inputs by
    using JavaScript to set the value directly."""
    loc = page.locator(selector)
    loc.wait_for(state="visible", timeout=FORM_FILL_TIMEOUT)

    is_readonly = loc.evaluate("el => el.readOnly || el.getAttribute('readonly') !== null")

    if is_readonly:
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
        loc.click(click_count=3, timeout=FORM_FILL_TIMEOUT)
        loc.fill(value, timeout=FORM_FILL_TIMEOUT)


def _fill_search_form(page: Page, stock_code: str, date_str: str) -> None:
    """Fill both stock code and date fields in one JS call — ~2s faster per stock."""
    page.wait_for_selector("#txtStockCode", state="visible", timeout=FORM_FILL_TIMEOUT)
    page.evaluate(
        """([code, dt]) => {
            const stock = document.querySelector('#txtStockCode');
            const date = document.querySelector('#txtShareholdingDate');
            for (const [el, val] of [[stock, code], [date, dt]]) {
                if (!el) throw new Error('missing form input');
                const wasReadOnly = el.readOnly || el.hasAttribute('readonly');
                el.readOnly = false;
                el.removeAttribute('readonly');
                el.value = val;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                if (wasReadOnly) {
                    el.readOnly = true;
                    el.setAttribute('readonly', 'readonly');
                }
            }
        }""",
        [stock_code, date_str],
    )


# ═══════════════════════════════════════════════════════════════════════════
#  DB persistence (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

def save_snapshot(snap: CCASSSnapshot) -> None:
    """Write snapshot to DB. Idempotent (UPSERT)."""
    now_iso = datetime.utcnow().isoformat()
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
        conn.execute(
            """UPDATE stock_universe
               SET first_seen_date = MIN(
                   COALESCE(first_seen_date, ?), ?
               )
               WHERE stock_code = ?""",
            (snap.trade_date, snap.trade_date, snap.stock_code),
        )
