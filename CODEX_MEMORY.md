# HK Alert Cloud GAS Memory

Last updated: 2026-07-16 HKT

## 2026-07-16 observed RRG and timing-stack integration

- Public-source review covered QuantStock AI's published workflow description, `doubleupasset`, the image-only `futualgo_kayman` Threads post, and MOFI's public RRG write-up/source repository. The three supplied Facebook photo URLs remained login-gated; no unseen rule or proprietary QuantStock implementation was guessed, scraped, or represented as copied.
- `scripts/build_sector_rotation.py` and `rotation_matrix.html` now produce schema-v2 RRG-style sector rotation from same-date, non-stale observed closes. Each sector's equal-weight median return is compared with the equal-weight market median; `RS-Ratio` uses the long relative return and `RS-Momentum` uses the short relative return around a neutral 100 axis.
- Rotation profiles are 20-day (5/20), 60-day (20/60), and 120-day (60/120). Missing history remains unavailable. The 2026-07-15 snapshot has real 20/60-day profiles; 120-day is explicitly unavailable. Classification coverage is disclosed as 1,457 of 2,723 observed named stocks (53.5%); 1,266 unclassified stocks remain in the market benchmark but are excluded from plotted sector signals.
- The generator reuses the main page's existing explicit `SECTOR_CODE_MAP` overrides instead of creating another heavy membership JSON. The output keeps truthful `windows` metadata for backward compatibility and publish/data-honesty tests.
- Added `timing_stack.html` under the `時序` navigation group. It accepts any 1-5 digit HK code and loads real daily bars through the existing Cloudflare `/api/kbar/<code>` route, then falls back to a real static shard and finally the existing real `data/kbar_cache.json`; it never synthesizes candles.
- The timing page combines observed price swing cadence, VQC dates, fixed jieqi dates, and HK distribution days on one log-price timeline. Projected pivot windows require at least three confirmed five-bar pivots and a median interval of at least 10 sessions. A future vertical line is a time-alert window only; no future OHLC or direction is generated.
- The same page exposes an observed 20-day price channel, EMA20/EMA60 trend, 20-day momentum, ATR14 risk, support/resistance, and a fail-closed `未確認／不入場` state unless a real close-and-volume channel breakout confirms. This adapts the useful separation of trend/momentum/support/pressure/risk seen in the public Threads image without copying its scoring or inventing options data.
- Daily refresh staging, guide, publish-bundle summary, direct Cloudflare allowlist, and shared navigation include the new page/schema. Browser audits at 393px and 1440px show populated SVGs, no JavaScript exceptions, and no document-level horizontal overflow.
- Verification: all `tests/` pass `53/53`; page-source audit reports 22 pages with zero missing data references; date aliases match and current publish gate is PASS. Current market/signals/events/rights/fundflow/Kbar/rotation data are through 2026-07-15 while CCASS is the expected 2026-07-14 publish date. Historical CCASS gaps/low coverage and participant-detail gaps remain honest maintenance WARN.

## 2026-07-16 Navigation and semantic colour consolidation

- Primary navigation order is `交易台 -> Market -> 訊號 -> 細價股 -> Kbar -> 動量 -> 事件 -> 自選 -> 更多`. `事件` is a direct link to `rights_analysis.html`; it must not be moved back under `更多`. `更多` follows `自選` in both DOM and visual order.
- `更多` contains lower-frequency stock selection, timing and records. CCASS 戰情室 is under records; duplicate momentum, watchlist and event entries were removed from the panel.
- `shared-nav.js` maps legacy palette aliases (`teal/green/red/blue/gold/accent/pos/neg`) to the canonical semantic palette. Legacy positive, risk, wait and info badges are normalized centrally so regenerated pages do not return to unrelated hard-coded colours.
- Ordinary pages remain one cool light workspace. Kbar and CCASS warroom remain dark tools but retain the same colour meanings: teal action, green positive, red risk, amber caution, purple CCASS and muted blue information.

## 2026-07-16 Semantic colour system and Kbar paired views

- `shared-nav.js` is the canonical colour layer for ordinary pages. Semantic colours are fixed across the suite: teal = selected/action, green = positive/up, red = downside/risk, amber = waiting/caution, purple = CCASS, and muted blue = information/timing.
- Ordinary data pages use the same cool light-gray background, white data surfaces and cool-gray borders. The legacy dark `細價股 Desk` embedded in `index.html` is normalized to the light workspace by the shared theme; it must not return as a random dark block.
- Kbar is now a coherent dark chart workspace from controls through chart panes. TradingView embeds also request dark mode. `docs/ccass-warroom.html` remains the only other intentionally dark tool.
- Kbar has four paired modes: `3m_pair`, `6m_pair`, `1y_pair` and `1d_pair`. Every mode renders its normal and inverted-price charts together from the exact same real daily-bar series. Desktop uses two columns; mobile stacks the pair. Inversion changes only price-axis direction, never OHLCV values or date direction.
- Old normal/inverted links for quarter, half-year, year and daily views are normalized to their paired mode, preserving bookmarks while removing split single-chart states.
- Kbar must report the actual available candle count. A source shard with 260 daily bars is shown as 260; tests must not require or invent 520 bars when the source does not contain them.
- Pair definitions use 66 real bars for quarter, 126 for half-year, 260 for year, and up to the available 520-bar source for daily. Each pair must report its actual source count and have identical candle/profile/POC geometry with opposite price-axis Y positions. No extra data download is introduced by paired rendering.

## 2026-07-15 Navigation consolidation

- Navigation now follows the trading workflow: `交易台 -> Market -> 訊號 -> 細價股 -> Kbar`, with desktop shortcuts for momentum and watchlist. Less frequent tools are grouped under `更多` as stock selection, events, timing and records.
- `daily_trade_prompt.html` is retired as a separate data consumer because its useful decisions already exist in Trading Desk, Market and Signals. The old URL remains as a lightweight redirect to `trading_desk.html`; no bookmark is broken and no analysis data was deleted.
- `gap_fvg.html` is retired as a separate data consumer because Gap, FVG and POC alerts already exist in Signals and Market. The old URL remains as a lightweight redirect to `signals.html`.
- Page generators and the rights-page legacy navigation no longer restore either retired link during daily refresh. The deploy allowlist intentionally keeps both redirect files.
- The guide page catalog uses the same workflow order and its duplicate top shortcut row has been reduced to one Trading Desk return action.

## 2026-07-15 Full-system audit and Futu watchdog repair

- Live audit covered all 21 public HTML routes on the canonical Cloudflare Pages domain at a 393px viewport: every route returned HTTP 200, same-origin data requests had no 404s, no page-level JavaScript exceptions were observed, and no document-level horizontal overflow was found.
- Canonical data aliases are synchronized; source dates span only the current market/publish boundary (2026-07-14 CCASS and 2026-07-15 price/signals/events). The current publish gate and dashboard verifier pass.
- SQLite `PRAGMA quick_check` passes. The production CCASS DB is about 3.46 GB with 106,635 daily rows and 14,835,135 participant rows. Core stock/date and participant indexes exist. Do not add duplicate indexes casually; historical participant storage is the main size driver.
- Remaining maintenance debt is real and must stay visible: one missing trading date (`2026-05-13`), 12 sub-99% historical dates, and participant-detail gaps on `2026-06-17` and `2026-06-18`. These do not contaminate the latest publish, but maintenance is correctly WARN rather than PASS.
- Root cause of the Futu watchdog failure: a gateway could keep port 11111 open after losing its upstream quote backend. Both `scripts/ensure_futu_opend.ps1` and the daily runner now replace that unhealthy process with `start_futu_opend_rs.py --stop-existing --background`, then require a real market snapshot before declaring Futu ready.
- `scripts/health_check.py` now runs the same real-quote probe. A broken Futu backend is operational WARN with an explicit Longbridge-fallback label; an open TCP port alone can no longer leave health at a misleading PASS.
- Verified recovery on account configuration already stored in repo-local `.env`: new gateway process, live `HK.00700` snapshot, daily automation preflight, and scheduled task result 0. No secret was printed or committed.
- Daily Cloudflare preflight now uses the installed global `wrangler` directly, matching the deploy helper, instead of routing through `npx`. OAuth verification passes. Deployment remains direct Cloudflare only.
- Removed the last production GitHub Pages fallback from `docs/ccass-warroom.html`; its data and page links now remain on Cloudflare-relative paths only.

## 2026-07-15 Unified page theme

- Root cause of mixed black/white pages was two legacy CSS families plus `prefers-color-scheme` overrides. It was not a data or handset fault.
- `shared-nav.js` now applies one persistent light data-workspace theme to ordinary pages after their generated/local CSS loads: light gray page background, white data surfaces, cool-gray borders and readable light controls.
- Kbar and `docs/ccass-warroom.html` intentionally remain dark tools for chart contrast and live-monitor use.
- Time-window pages no longer auto-open the `更多` menu on navigation; the current group is still marked active, but the panel opens only on user action.
- This is centralized in the shared navigation layer so regenerated timing, rights, daily-prompt and analysis HTML cannot revert to mixed themes on the next refresh.

## 2026-07-15 Full-book finance event chain integration

- The user confirmed that the 97 screenshots in `C:\Users\Administrator\Desktop\財技X盤路_倍升股全攻略-pdf` are the complete substantive book capture; blank/no-text pages were intentionally omitted. Do not describe this source as incomplete again.
- `scripts/build_trade_engine.py` now turns observed announcement order into an auditable finance-event chain instead of showing isolated badges only.
- Every classified event carries a title-derived lifecycle stage: announced, proposed, delayed/revised, completed, results/acceptance, or terminated/lapsed. A stage is never inferred without matching words in the observed announcement title.
- Added source-backed event classes for privatization, control change, transfer to Main Board, bonus issue and disposal, while retaining placement, rights, convertible bonds, shareholder increase, buyback, acquisition/offer, resumption, consolidation/subdivision, capital reduction and failed transactions.
- Derived sequence labels now expose repeated financing, control/offer followed on a later date by financing, privatization progress, transaction termination, increase/buyback observation and other multi-step events. Same-date mixed announcements do not qualify as "control then financing".
- `smallcap_playbook.html` adds a visible `財技階段` column, event timeline, filters for multi-step finance/control-then-financing/increase-buyback/terminated events, and a broker-level CCASS supply label (`多席收集`, `多席派發`, `疑似轉倉`, `集中兼增持`, `貨源集中`, `合計增持`, or `未確認`).
- The page still keeps finance events, technical confirmations and CCASS as separate evidence lanes. It does not copy order-book/tape methods into the site, and it does not manufacture sponsor, IPO subscription or unavailable transaction terms.
- The existing `data/trade_engine.json` remains the only runtime output; no duplicate heavy JSON was added. Its source snapshot metadata now includes announcements and rights-analysis dates.
- Verified local rebuild: 2,722-stock universe, 240/240 HK candidates analyzed, 0 errors. Targeted source/UI tests pass on desktop and 393px mobile with no horizontal overflow.

## 2026-07-15 Small-cap Finance x Technical x CCASS Playbook

- Added `smallcap_playbook.html` as a new page; no existing page was removed or replaced.
- Method source now includes all 97 licensed-reader screenshots supplied by the user, covering the substantive table of contents and text through page 220 of `財技X盤路：倍升股全攻略`; blank/no-text pages were intentionally not captured. Summarize methods only and do not reproduce protected book text. The local `.acsm` remains a fulfilment token, not readable book content.
- The page translates only source-backed, data-supported ideas into three independent lanes:
  - finance / supply: observed HKEX announcement titles and the existing canonical circle-stock / circle-cash judgement;
  - technical confirmation: `Gap 跳升`, `向上 FVG`, and `突破中長期 POC` from published signals;
  - CCASS aggregate holdings: consecutive increase plus separate 5D and 20D changes.
- `scripts/build_trade_engine.py` classifies observed placement, rights, shareholder increase, buyback, acquisition / offer, resumption, convertible bond, share consolidation, capital reduction and failed-sale / transaction-termination events. It does not infer an event absent from the announcement title/type.
- Placement/rights events are now matched to same-code, same-date rows in canonical `data/rights_analysis.json`. Extracted ratio/dilution, discount, authorization and use-of-funds fields are shown independently as observed or missing. A row from another date is never attached as fallback.
- Finance-event term status is `complete`, `partial`, or `not_extracted`; a matched announcement with zero extracted terms remains `not_extracted`. Existing circle-stock/circle-cash judgement and its positive/negative/pending basis are carried through without recalculation.
- Supply-cash risk always outranks apparent three-lane confluence. The output is an evidence funnel, not a buy instruction.
- Per the user's decision, order-book/tape concepts are excluded from this system feature. User-facing Kbar evidence is named `技術確認`, never `盤路`; the trading desk uses the same terminology.
- The new page reuses `data/trade_engine.json` and `data/publish_bundle.json`; no duplicate heavy JSON source was added.
- Verified snapshot after rebuild: 240/240 HK candidates analyzed, 0 errors; 74 classified finance events, 16 with partial same-date extracted terms, 58 honestly marked not extracted, and 3 three-lane confluences. Small-cap view contains 101 candidates and paginates 10 per page.
- Shared navigation, guide, daily refresh staging and direct Cloudflare deploy allowlist include the new page.
- Tests: 16 targeted engine/page tests pass; 393px mobile has no horizontal overflow. Repo audit: 21 pages, 0 missing refs, 0 alias mismatches. Current publish gate is PASS; maintenance remains WARN for genuine historical CCASS gaps/low-coverage dates.

## 2026-07-15 Unified Trading Desk

- Added `trading_desk.html` as a new daily decision layer. No old page was deleted or replaced.
- The page fuses the existing canonical sources instead of copying them into another large duplicate cache:
  - market regime: `market.json`
  - installed trading-skill rules / Kbar setups: `data/trade_engine.json`
  - CCASS trend: `holdings.json`
  - corporate signals and supply judgement: `data/signals.json` + `data/rights_analysis.json`
  - fund flow / southbound: `data/fundflow.json`
  - broker-seat anomalies: `data/participant_anomalies.json`
  - sector pulse: `data/sector_rotation.json`
- The decision queues are `優先研究`, `等確認`, `反抽短打`, and `避開 / 高風險`. They are derived research queues, not observed facts or buy instructions. Trigger, invalidation, target, evidence, risk, and source dates remain visible per stock.
- Added two real external observation layers:
  - `scripts/fetch_market_intel.py` -> `data/market_intel.json`: Longbridge HK popularity ranks, real-time anomalies, and top-mover events.
  - `scripts/fetch_sfc_short_positions.py` -> `data/short_positions.json`: official SFC weekly aggregate reportable short positions.
- SFC coverage rule: a missing stock means `未涵蓋`, never zero short interest. Week-over-week change is shown only when two different official report dates exist.
- External fetch failure rule: preserve the previous snapshot and mark it `stale`; never manufacture fallback observations.
- `ccass/scripts/daily_refresh.sh`, `data/publish_bundle.json`, health checks, the direct Cloudflare deploy allowlist, and shared navigation now include the trading desk and both external sources.
- Current verified snapshot on 2026-07-15:
  - Longbridge: 120 rank positions, 100 intraday anomalies, 46 top-mover events.
  - SFC: report date `2026-07-03`, 1,231 reportable rows.
  - page dependency audit: 20 pages, 0 missing refs, 0 alias mismatch.
  - Playwright: desktop and 393px mobile tests pass with no JS errors or horizontal overflow.

### Financial-event x technical x CCASS model

- Method reference supplied by the user: `財技X盤路 倍升股全攻略`, plus the local `殼股財技.pdf`. Treat these as research frameworks, not copied content or deterministic trading truth.
- Announcement events and technical setups are equal-level triggers, but they must be separate evidence lanes so one published event cannot be counted again as a technical signal.
- `scripts/build_trade_engine.py` partitions every signal into exactly one lane:
  - event: placement, rights, shareholder increase, takeover/resumption and other corporate announcements;
  - technical: POC, year-open, IPO, FVG, gap and the derived Kbar setup;
  - CCASS accumulation: aggregate `total_shares` streak and 5D/20D changes.
- Event direction is explicit: shareholder increase and `supply-stock` can support a setup; `supply-cash` remains a risk; unknown/watch announcements are catalysts only and never automatic bullish evidence.
- CCASS aggregate consecutive increase is now a first-class signal. `strong` requires at least 3 consecutive increases plus positive 5D and 20D aggregate changes; `building` requires at least 2 consecutive increases and positive 5D change. Neutral days do not break the streak, matching `ccass/src/trend.py`.
- The trading desk shows the three lanes side by side, sorts three-lane confluence first, and displays streak days plus 5D/20D share and percentage changes. CCASS still represents broker-level holdings, not final-investor identity.
- The candidate table keeps separate adjacent columns in this order: `CCASS 連增`, `CCASS 5日`, `CCASS 20日`; do not collapse 5D and 20D back into one cell.
- Verified 2026-07-15 candidate set: 57 event triggers, 48 strong CCASS accumulations, and 14 event + Kbar + strong-CCASS confluences among 240 analyzed HK candidates.
- `data/trade_engine.json` is minified at write time to reduce daily mobile transfer while preserving every field.

## Latest Audit

### 2026-07-12 CCASS historical DB audit / repair

- New repo-native audit helper: `scripts/repo_audit.py`
  - `python scripts/repo_audit.py pages` = scan each HTML page's JSON dependencies and missing refs
  - `python scripts/repo_audit.py dates` = compare canonical JSON update dates / alias drift
  - `python scripts/repo_audit.py db` = show `ccass/holdings.db` trading-day gaps and low-coverage dates
  - `python scripts/repo_audit.py export` writes `data/repo_audit.json`
  - `ccass/scripts/daily_refresh.sh` now generates `data/repo_audit.json` on every run before `build_publish_bundle.py`
  - `scripts/build_publish_bundle.py` now exposes repo-audit summary in `data/publish_bundle.json`
  - `scripts/health_check.py` now reads `data/repo_audit.json` and surfaces page-ref/date-spread/db-gap warnings in health output
  - `ccass/scripts/_deploy_cf.py` now deploys `data/repo_audit.json`
  - Use this first before page-only fixes when the user reports inconsistent data across pages.

- Longbridge auth was refreshed successfully on 2026-07-12 and verified with a live `NVDA.US` quote. Repo `.env` is again the only valid token source for this system.
- Windows `.env` loading in `ccass/src/longbridge_provider.py` now uses `utf-8-sig`, because the default Windows codec caused real token read failures on this repo.
- `ccass/holdings.db` had a large historical `pct_of_issued` corruption backlog. Multiple repair passes were applied with DB backups created before each pass:
  - `ccass/holdings_before_pct_repair_20260712_164520.db`
  - `ccass/holdings_before_pct_repair_20260712_165029.db`
  - `ccass/holdings_before_pct_repair_20260712_165238.db`
  - `ccass/holdings_before_pct_repair_20260712_165337.db`
  - `ccass/holdings_before_pct_repair_20260712_165456.db`
- `ccass/scripts/repair_historical_pct.py` is the canonical pct repair tool. It can now target any pair where holdings pct sum materially exceeds daily pct and recompute participant pct from shares safely.
- New tool: `ccass/scripts/rescrape_verify_errors.py`
  - Purpose: collect remaining verifier error stock/date pairs, rescrape them from source, and overwrite both `ccass_daily` and `ccass_holdings`.
  - Use it after `verify_data.py` when old daily rows contain fake non-null `total_pct` values that source now returns as `null`.
- Source-truth rule confirmed on 2026-07-12:
  - Some historical error dates were not “missing data”; DB contained fake non-null `total_pct` / wrong daily totals.
  - Example class: `00328`, `00608`, `01118`, `01224`, `01771`, `03899`, `08552`.
  - For these, HKEX rescrape returned the honest payload and often `total_pct=null`; the correct action is to overwrite DB with source truth, not infer or smooth.
- Audit result after repair + targeted rescrape on 2026-07-12:
  - `verify_data.py --json --publish-scope`: `errors=0`
  - `audit_gate.py --min-coverage 99.0`: historical backlog downgraded from FAIL to WARN (`errors=0`, warnings remain)
  - `verify_dashboard`: PASS
- Current remaining integrity state is WARN, not PASS, for real reasons:
  - historical date gaps still exist: `2026-05-11`, `2026-05-12`, `2026-05-13`, `2026-06-16`, `2026-06-22`, `2026-06-30`
  - many historical warnings are now honest partial-data conditions (`total_pct` null, orphan daily rows, zero participant rows), not hard corruption
  - latest publishable CCASS remains `2026-07-09` at `99.4%` coverage
- Follow-up on 2026-07-12 evening:
  - Repo-local `LONGBRIDGE_ACCESS_TOKEN` in `.env` is expired for MCP historical broker-holding calls, even though the machine's Longbridge CLI session is still valid for quote/latest commands.
  - Added `ccass/scripts/hkex_gap_backfill.py` as the stable single-process HKEX fallback for explicit historical gap dates. It reuses one HKEX session, skips already-filled rows, writes directly through `save_snapshot`, and stays single-threaded by rule.
  - Tested on `2026-06-30`: partial real backfill advanced the date from `0` to `75` stocks, proving source access works, but HKEX throughput is still too slow for timely completion of all six gap dates without a fresh Longbridge historical token.
  - `ccass/scripts/audit_gate.py` now treats low-coverage historical dates as backlog warnings instead of implicitly treating any date with a few rows as "filled". Recent low-coverage dates now surface first, including `2026-07-08`, `2026-07-02`, and partial `2026-06-30`.
- Decision rule going forward:
  - If `verify_data` shows holdings pct sum materially larger than daily pct, repair or rescrape.
  - If source rescrape returns `total_pct=null`, keep it null; do not backfill a guessed percentage.
  - Treat `ccass_daily` rows as suspect when they disagree with rescraped participant payload; source overwrite beats local heuristic.

## Load First

1. `AGENTS.md`
2. `CODEX_MEMORY.md`
3. Current `git status`

If this file disagrees with chat memory, trust the current repo state.

## Markdown Policy

- This repository keeps only two tracked Markdown files:
  - `AGENTS.md`: tiny agent entrypoint.
  - `CODEX_MEMORY.md`: project memory, runbook, architecture map, and deploy notes.
- Do not recreate `CLAUDE.md`, `SYSTEM_MAP.md`, `Daily/` notes, root README/changelog/log files, or per-task Markdown unless the user explicitly asks.
- Update this file after major UI, data, pipeline, deploy, or source-of-truth changes.

## User Preferences

- User wants direct fixes, not only analysis.
- Keep status short and concrete.
- The site should stay HK-focused, except main pages may show US P/E and US breadth.
- Avoid vague memory. Read local files before changing the system.
- Keep Telegram, dashboard, Cloudflare pages, and memory aligned.
- Remember the Telegram Hermes bot as part of the system wiring for dashboard/status/health-style notifications; do not print or commit its token/chat secrets.
- User does not want `yfinance` for this project.
- User does not want `gh` CLI and does not want project internals searchable.

## Scope

- Repo: `C:\Users\Administrator\Desktop\automatic\hk-alert-cloud-gas`
- Live site: `https://hk-alert-cloud-gas.pages.dev`
- Current deploy preference: direct Cloudflare Pages deploy with Wrangler only.
- GitHub Pages, GitHub Actions, Cloudflare Git auto-deploy, and `gh` CLI must not be used for refresh/deploy unless the user explicitly asks to re-enable GitHub routes.

## Hard Rules

- No bulk Telegram floods. Send alerts slowly, cap batches, and summarize large runs.
- No destructive production DB changes without explicit approval. Backup before migrations.
- No direct in-process parallel HKEX scraping or direct parallel DB writes.
- No committed secrets.
- Prefer structural source-of-truth fixes over page-only patches.
- Small-cap data coverage matters.

## System Map

Data flow:

```text
HKEX / Futu / Longbridge / local JSON
  -> holdings DB / raw JSON
  -> generators and scoring scripts
  -> root JSON + data/*.json aliases
  -> data/publish_bundle.json
  -> HTML pages / health checks / Telegram
  -> local commit
  -> direct Wrangler upload to Cloudflare Pages
```

Primary layers:

- Raw sources: `ccass/holdings.db`, `holdings.db`, HKEX disclosures, Futu/Longbridge cache, local JSON snapshots.
- Compute: `ccass/src/runner.py`, `ccass/scripts/*.py`, `scripts/*.py`.
- Publish: `holdings.json`, `ccass.json`, `market.json`, `data/*.json`, `data/publish_bundle.json`.
- Pages: `trading_desk.html`, `index.html`, `signals.html`, `smallcap_playbook.html`, `kbar_matrix.html`, `rights_analysis.html`, timing pages, and related static pages. `daily_trade_prompt.html` and `gap_fvg.html` are compatibility redirects only.
- Notify: Telegram and health checks should read the same publish metadata as the dashboard.

## Canonical Data Rules

- Root publish JSON and `data/*.json` aliases must be synchronized before page generation:
  - `holdings.json -> data/holdings.json`
  - `ccass.json -> data/ccass.json`
  - `market.json -> data/market.json`
- `data/publish_bundle.json` is the shared freshness/status layer for dashboard, Telegram, health checks, and memory.
- If duplicate/cache/fallback sources exist, choose one primary source and label fallback use clearly.
- Page mismatch means fix source/export first, then page logic, then docs.
- Every public page must be refreshed every daily run, together with the JSON files it reads. If a page has no new domain event that day, still rebuild the page/cache stamp and publish freshness metadata so it cannot remain on an old snapshot.
- CCASS / participant interpretation rules:
  - A position moving from one large broker seat to another can be a transfer/warehouse move, not necessarily a real buy/sell.
  - Stronger practical signals come from multi-day large-seat accumulation, large-seat sudden reduction without price weakness, or fragmentation into many small seats.
  - Public wording must not overclaim final-investor identity from broker-level CCASS data.
  - Keep reminding that CCASS is broker-layer data and effectively T+2 settlement-lagged.

## Current Refresh Pipeline

Main workflow:

- Shell orchestrator: `ccass/scripts/daily_refresh.sh`
- Direct deploy helper: `ccass/scripts/_deploy_cf.py`
- GitHub Actions are disabled at repository settings; do not route refresh/deploy through GitHub unless the user explicitly asks to re-enable them.
- Cloudflare cron Worker `ccass-refresh-cron` is a no-op and must not dispatch GitHub Actions.

Expected sequence:

1. `ccass/src/runner.py`
2. `ccass/scripts/daily_lp_futu.py`
3. `ccass/scripts/generate_prices_json.py`
4. `scripts/sync_rights_from_announcements.py`
5. Generate `rights_analysis.json/html`
6. `ccass/scripts/generate_signals_json.py`
7. `ccass/scripts/regenerate_json.py`
8. `scripts/sync_publish_aliases.py`
9. `scripts/build_publish_bundle.py`
10. Generate static analysis pages
11. `scripts/audit_gate.py`
12. Commit locally and direct deploy to Cloudflare Pages

`audit_gate.py` should fail if root/data aliases diverge.

Separate resume/backfill jobs:

- `ccass/scripts/resume_incomplete_dates.py`
- `ccass/scripts/resume_backfill_range.py`

Keep the daily refresh bounded; let resume jobs mop up incomplete coverage.

## Page Data Consistency

- Main page corporate-action badges must show `data/signals.json.groups[].supply` as `圈股判斷` (`圈股` / `圈錢` / `待確認`), not `發行方有利度`.
- `data/signals.json` should still keep the canonical issuer payload from `data/rights_analysis.json` for audit/backward compatibility, but the visible main-page badge should use the canonical supply/cash judgement from `data/rights_analysis.json`.
- `rights_analysis.html` and the main signal badges must use the same supply/cash label and basis.
- Main-page theme/sector selectors and heatmaps should reuse existing page data. Heatmaps live in their own main-page card, separate from the toolbar/card that holds table controls. Until a canonical sector source exists, `index.html` uses lightweight in-browser keyword sector grouping and must not add another heavy JSON source for this.
- `timing_analysis.html`, `jieqi_analysis.html`, and `distribution_day.html` are signal-date tables, not first-screen backtest dashboards.
- Main page should not expose old `5d`, `20d`, or `60d` delta columns.
- Old URL/custom preset sorts using `d5`, `d20`, or `d60` should sanitize back to `vr`.
- Count bars on timing/jieqi/distribution pages use `log1p(count)` for width while displaying the real count.

## Deployment

- Current user preference is direct Wrangler deploy to Cloudflare Pages.
- Avoid GitHub/`gh` for refresh/deploy unless the user explicitly asks.
- GitHub Actions are disabled at repository settings; workflow files may remain locally for reference only, but they must not be used as a deploy/refresh route.
- Cloudflare cron Worker should stay no-op unless a non-GitHub refresh path is implemented.
- Telegram Hermes bot is for general dashboard/status/health summaries. CCASS events cron should use its own Telegram bot/chat secrets, not the Hermes bot, unless the user explicitly asks to merge them.
- Telegram env routing:
  - Hermes/status bot: prefer `HERMES_TELEGRAM_TOKEN` / `HERMES_TELEGRAM_CHAT_ID` (fallbacks: `HERMES_TG_BOT_TOKEN`, `TG_BOT_TOKEN`, old generic names only for legacy).
  - CCASS/corporate-action cron bot: use `CCASS_TELEGRAM_TOKEN` / `CCASS_TELEGRAM_CHAT_ID`.
  - CCASS cron paths set `CCASS_TELEGRAM_REQUIRE_DEDICATED=1`, so missing CCASS secrets means skip Telegram instead of reusing Hermes.
  - Do not put any bot token/chat id in tracked files; keep them in local `.env` or platform secrets only.
- Cloudflare Pages output should include `_headers` with `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet, noimageindex`.
- `robots.txt` and `_headers` reduce search indexing for the live site, but they do not make a public GitHub repository private.

Cloudflare cron Worker note:

- `ccass-refresh-cron` used to dispatch GitHub Actions; it is now intentionally disabled/no-op.

Apps Script notes formerly kept in `apps_script/README_DEPLOY.md`:

- Deploy `apps_script/Code.gs` through Google Apps Script as a Web App.
- Store `GAS_SECRET` in Script Properties, not in code.
- Keep `GAS_WEBHOOK_URL` in GitHub Actions secrets.
- Updating deployed Apps Script requires a new deployment version.
- Sheet schema should upgrade without destroying existing rows.

## Latest Deploy Notes

### 2026-07-12 provider split locked in

- Operating rule for this repo is now explicit:
  - Longbridge = primary CCASS / broker-holding / historical backfill source.
  - Futu/OpenD = primary price / snapshot / K-bar source.
- Reason:
  - Longbridge historical broker-holding path is the one that can repair real CCASS date holes in `ccass/holdings.db`.
  - Futu/OpenD is still the better local quote/chart engine for market cards, snapshots, and cached K-bar generation when the local gateway session is healthy.
- Repo-local secret routing:
  - `C:\Users\Administrator\Desktop\automatic\hk-alert-cloud-gas\.env` now remains the only repo token source for `LONGBRIDGE_ACCESS_TOKEN`.
  - `ccass/src/longbridge_provider.py` must read repo `.env` with `utf-8-sig` on Windows; plain default decoding caused real `gbk` failures when loading the token file path through the repo `.env`.
- Decision rule:
  - If the task is CCASS participant history, broker concentration, or backfilling missing trade dates, use Longbridge first.
  - If the task is latest price, turnover, intraday status, or K-bar cache refresh, use Futu first and Longbridge only as fallback.

### 2026-07-11 small-cap trading desk and CCASS trend restoration

- Main page now includes a compact `細價股 Desk` above the legacy breakthrough/heatmap/table sections. It reuses existing holdings, signals, alerts, and price data; no extra JSON feed was added.
- Desk lists are separated into `優先研究`, `收集／突破`, `等確認`, and `避開／高風險`. Ranking combines liquidity, relative volume, 52-week position, year-open position, technical signals, corporate-action risk, and trusted CCASS trend evidence. A one-day fall of 15% or more is hard-gated to risk until a real reclaim signal exists.
- CCASS 5/20/60/120-day trend export was restored. Compact stock fields are `d5s/d20s/d60s/d120s` for share changes and `d5p/d20p/d60p/d120p` for percentage changes.
- `ccass/src/trend.py` now compares only snapshots where both ends have a real `total_pct`; this prevents incompatible fallback-source totals from creating fake jumps. Missing exact reference dates may use the nearest high-coverage trusted snapshot within four calendar days, and the actual dates are published in `trend_reference_dates`.
- Current trusted references on 2026-07-09 are 5-day=`2026-07-03`, 20-day=`2026-06-10`; 60/120-day remain null because trusted history is insufficient. Null must stay visible as `—`, never zero.
- A meaningful 5-day accumulation signal requires `d5s > 0` and `d5p >= 0.10%`. `data/signals.json` now labels it `CCASS合計持股5日增持` and carries all four trend windows in the `ccass` payload.
- Main sorting/filter controls support CCASS 5/20/60/120-day values without restoring four wide table columns. The stock drawer shows all four windows and their actual reference dates.
- Browser regression coverage includes the Desk tabs/drawer plus existing desktop/mobile heatmap behavior in `tests/test_small_cap_desk.py`, `tests/test_main_heatmap_smoke.py`, and `tests/test_main_heatmap_mobile_touch.py`.
- Latest real `data/vqc_backtest.json` events are merged into `data/signals.json` as `成交轉勢日` with their actual signal date. The main Desk has a dedicated `成交轉勢` tab and gives this signal explicit ranking weight.
- `kbar_matrix.html` loads VQC, `jieqi_calendar.json`, and HK distribution-day data and plots dated vertical markers directly on every cached HK chart: green=`VQC`, blue=`節氣`, amber=`DD`, pink=multi-signal resonance. The old prior-low reclaim heuristic is still retained but relabeled `返`; it must never be called real VQC.
- Kbar page order is controls -> Kbar charts -> playbook/setup -> console. Do not reintroduce CSS order rules that push the chart below setup cards.
- `scripts/build_kbar_cache.py` now prioritizes the latest VQC stocks, fixed a broken `to_float()` implementation, reads canonical CCASS 5/20-day metrics from `holdings.json`, and supports a real `--help` exit. Current cache has 41 symbols and includes all nine 2026-07-10 VQC stocks.
- Kbar timing markers have browser coverage in `tests/test_kbar_timing_markers.py`.

### 2026-07-05 daily timing-sample rebuild and page-vs-sample freshness split

- `ccass/scripts/daily_refresh.sh` now rebuilds all three timing sample JSONs on every daily run before `build_publish_bundle.py`:
  - `scripts/build_vqc_backtest.py`
  - `scripts/build_distribution_day_backtest.py`
  - `scripts/build_jieqi_backtest.py`
- The same daily refresh script now stages `data/vqc_backtest.json`, `data/distribution_day_backtest.json`, and `data/jieqi_backtest.json`, so a fresh local rebuild cannot be dropped from the eventual direct Cloudflare deploy.
- `scanner/local_alert_store.py export_history_json()` now writes a real export timestamp to `data/history.json` as `updated`, instead of leaving history freshness implied by the latest event day.
- `scripts/build_publish_bundle.py` now treats history freshness and history latest-event date as different fields:
  - `files.history.updated` = export/build freshness
  - `files.history.latest_event_date` = latest actual alert day in the history window
- The same bundle builder now falls back to file mtime for history/backtest metadata if an `updated` field is ever missing, so Telegram/health/dashboard freshness cannot go blank just because one JSON omitted that key.
- Freshness labels on timing pages are now split between page rebuild time and sample-data time:
  - `vqc_analysis.html`
  - `distribution_day.html`
  - `jieqi_analysis.html`
  - `timing_analysis.html`
  - `daily_trade_prompt.html` now labels `VQC樣本` / `分佈日樣本` instead of implying those dates are the page-refresh date.
- Manual rebuild completed on `2026-07-05`:
  - `data/vqc_backtest.json.updated=2026-07-05T23:38:23`
  - `data/distribution_day_backtest.json.updated=2026-07-05T23:38:25`
  - `data/jieqi_backtest.json.updated=2026-07-05T23:41:03.525184`
  - `data/history.json.updated=2026-07-05 15:58 UTC`
  - `data/publish_bundle.json.generated_at=2026-07-05T23:58:32`
- Note: the manual VQC rebuild still saw a few transient TradingView `429 Too Many Requests` sample fetch failures, but the JSON/page output completed and published a current sample timestamp instead of leaving the page on an old snapshot.

### 2026-07-06 per-page freshness grouping audit

- Final page grouping for freshness/debugging:
  - Dynamic live-JSON pages: `index.html`, `signals.html`, `gap_fvg.html`, `fundflow.html`, `history.html`, `rights_analysis.html`, `daily_trade_prompt.html`
  - Static generated pages rebuilt from JSON snapshots: `vqc_analysis.html`, `distribution_day.html`, `jieqi_analysis.html`, `timing_analysis.html`
  - Local-only pages: `watchlist.html`, `momentum_list.html`
  - Pure static/non-data pages: `guide.html`, `ccass.html` (redirect), `404.html`
- Dynamic live-JSON pages now use `Date.now()` cache-busting and `cache:'no-store'` on their primary JSON fetches so Cloudflare/browser cache does not leave the user on an older snapshot after a successful deploy.
- `rights_analysis.html` no longer ships with a fixed `?v=...` build stamp in the HTML. It now fetches `data/rights_analysis.json?_=${Date.now()}` at runtime.
- `fundflow.html` now fetches both `holdings.json` and `data/fundflow.json` with `no-store` semantics instead of relying on default browser cache behavior.
- `daily_trade_prompt.html` remains an embedded/static page for most content, but now refreshes `data/publish_bundle.json` on load so the visible publish timestamp can stay current even if the page HTML is older than the bundle.
- Manual live verification on 2026-07-06 confirmed:
  - `index.html`, `signals.html`, and `gap_fvg.html` fetch `publish_bundle.json` with `cache:'no-store'`
  - static timing pages show `頁面更新：2026-07-06 03:09`
  - `daily_trade_prompt.html` still contains the `refreshBundle()` live-bundle logic

### 2026-07-04 Telegram bot routing, Hermes sync, and tooling audit

- `run_corp_cron.py` and `_run_corp_cron.py` now run from this repo root, not `C:\Users\Administrator\Desktop\automatic\ccass-debug`, and read only this repo's local `.env`.
- CCASS/corporate-action Telegram sends now prefer dedicated second-bot env names: `CCASS_TELEGRAM_TOKEN` and `CCASS_TELEGRAM_CHAT_ID`. Corp cron launchers and `daily_refresh.sh` default `CCASS_TELEGRAM_REQUIRE_DEDICATED=1`, so they cannot silently use Hermes/generic Telegram credentials.
- Hermes/status paths now prefer `HERMES_TELEGRAM_TOKEN` and `HERMES_TELEGRAM_CHAT_ID`. `scripts/health_check.py --telegram` and `scripts/tg_claude_bot.py` were aligned to those names while keeping legacy generic fallback for manual use.
- Local disabled GitHub workflow references were hardened: CCASS workflows now reference `CCASS_TELEGRAM_*` and no longer keep a commit/push-capable permissions block for `ccass-events`; heartbeat references `HERMES_TELEGRAM_*`.
- Web/tooling audit recommendations:
  - Install/enable first: Sentry Cron Monitoring for `daily_refresh`, resume/backfill, and Hermes/CCASS cron no-run/failed-run detection; Playwright smoke tests for live page/heatmap click-to-table checks; DuckDB/Parquet snapshots for lighter history/audit queries.
  - Use next if the pipeline grows: Prefect for local Python orchestration and retry/state UI; Cloudflare Queues with dead-letter queues if alerts/jobs move into Workers and need retry isolation.
  - Defer unless validation rules become much bigger: Great Expectations or Dagster, because the current repo already has custom `audit_gate` and direct scripts.
- Installed locally in `.venv` on 2026-07-04 and recorded in requirements: `sentry-sdk 2.64.0`, `duckdb 1.5.4`, `pytest-playwright 0.8.0`, `playwright 1.61.0`; Playwright Chromium browser `149.0.7827.55` was installed under the user Playwright cache.
- Sentry still needs a local/platform secret such as `SENTRY_DSN` before it can send cron monitoring events. Do not commit the DSN.
- `scripts/sentry_cron.py` and `scripts/cron_monitor.py` provide optional fail-open Sentry Cron Monitoring. They load local `.env`, send check-ins only when `SENTRY_DSN` is present, and never block the wrapped job if Sentry itself fails.
- Sentry cron slugs currently wired:
  - `hk-alert-daily-refresh`: auto-wraps `ccass/scripts/daily_refresh.sh`.
  - `hk-alert-resume-incomplete`: wraps `ccass/scripts/resume_incomplete_dates.py`.
  - `hk-alert-resume-backfill-range`: wraps `ccass/scripts/resume_backfill_range.py`.
  - `hk-alert-corp-cron`: wraps both corp cron launchers.
  - `hk-alert-health-check`: wraps `scripts/health_check.py`.
- To disable the wrapper for a one-off run, set `SENTRY_CRON_DISABLED=1`. To customize schedule metadata, use slug-specific env names like `SENTRY_CRON_HK_ALERT_DAILY_REFRESH_MAX_RUNTIME=240`; do not commit those secrets/settings unless they are non-sensitive.
- `tests/test_main_heatmap_smoke.py` is the first Playwright smoke test. It defaults to `https://hk-alert-cloud-gas.pages.dev` and checks that the main heatmap renders, a clickable theme tile activates, and the heatmap matches section appears. Override target with `HK_ALERT_BASE_URL`.
- Installed Codex skills from `https://github.com/Leonxlnx/taste-skill` into `C:\Users\Administrator\.codex\skills`: `taste-skill` (`design-taste-frontend`), `gpt-tasteskill` (`gpt-taste`), and `redesign-skill` (`redesign-existing-projects`). Restart Codex to load them in future sessions. For this CCASS dashboard, prefer `redesign-existing-projects` over the default taste skill because the default skill explicitly targets landing pages/portfolios rather than data-table dashboards.
- Installed `soda-core 3.5.6` CLI for future CCASS data-quality checks and `pytest-playwright-visual-snapshot 0.5.1` for future heatmap/UI screenshot regression tests. `soda-core-duckdb` was intentionally not installed because it pins `duckdb<1.1.0`, which has no Python 3.14 wheel here and tries to compile with Microsoft C++ Build Tools; keep using the already installed `duckdb 1.5.4` for local DuckDB checks.

### 2026-07-04 Longbridge CCASS latest backfill and publish gate split

- Root cause of stale `2026-06-26` CCASS publish: `holdings.json` had drifted away from the local DB. The DB latest rows were partial, and the old resume jobs missed fully absent trading days because they only inspected dates already present in `ccass_daily`.
- Longbridge CLI broker-holding detail is now the preferred latest-date CCASS provider. `ccass/src/longbridge_provider.py` defaults to CLI-first, uses the main MCP endpoint if needed, rejects date mismatches, and normalizes Longbridge ratio fractions such as `0.3239` into dashboard percentage points such as `32.39`.
- `ccass/scripts/resume_backfill_range.py` now supports `--provider auto|hkex|longbridge`, trading-calendar dates, `--max-stocks`, `--target-coverage`, and a real dry run when `--max-batches <= 0`. `auto` uses Longbridge only for the Longbridge latest holding date and HKEX for older dates.
- `ccass/scripts/resume_incomplete_dates.py` now builds candidates from the trading calendar, not only DB dates, so 0-row missing trading days can be detected/backfilled. Default lookback is 45 trading days.
- `ccass/scripts/fill_missing.py` now compares against active `stock_universe` instead of the historical max-row date, so newly active/listed stocks are no longer skipped when repairing coverage.
- Backfilled latest Longbridge CCASS date `2026-07-03`: public `holdings.json` / `data/holdings.json` / `ccass.json` / `data/ccass.json` now publish 2747 stocks, 99.6% coverage. Remaining missing/no-data codes after the run included `00876`, `00809`, `00309`, `01371`, `01468`, `03313`, `08048`, `08071`, `08471`, `08568`, `08569`, `08603`.
- `data/transfers.json` and `ccass/data/transfers.json` now align to `2026-07-03 vs 2026-07-02` with 22 transfer items. Do not show stale `2026-06-05` transfer output.
- Added `ccass/scripts/repair_pct_scale.py` and wired it into `daily_refresh.sh` before regeneration. It backs up `ccass/holdings.db` before repairing legacy `total_pct` rows stored as fractions when a nearby same-stock row confirms the x100 scale. Current local repair updated 2201 legacy rows after backup `ccass/backups/holdings.db.bak.20260704_103654`.
- `ccass/scripts/verify_data.py --date YYYY-MM-DD` now truly scopes daily-jump checks to that date. It treats unavailable `total_pct` as a warning, not a massive mismatch error. Latest `2026-07-03` verification is 0 errors / 30 warnings; 8 Longbridge rows have shares/participants but no percentage ratio and are published as `tp:null`, not fake `0`.
- `ccass/scripts/audit_gate.py` now gates on current publish-date errors. Historical DB gaps and full-history verifier failures remain warnings/backlog so old rows cannot block today's page refresh. Current gate is `WARN`, not `FAIL`: latest publish is deployable, while historical gaps/backlog remain visible.
- `index.html`, `ccass/scripts/merge_shards.py`, and `ccass/src/runner.py` preserve missing Market% as `null` and guard CSV/filter/detail rendering so unknown concentration is not displayed as low/0.
- Hermes/dashboard shared bundle now shows `publish=WARN`, holdings `2026-07-03`, signals generated on `2026-07-04`, rights/announcements/fundflow `2026-07-03`, and transfers `2026-07-03 vs 2026-07-02`.

### 2026-07-04 full-system audit, Hermes alignment, and refresh reliability

- Full page fetch audit found one missing main-page data request: `index.html` still fetched `data/webb_site/summary.json`, but the file was not present. Removed that fetch so the main page no longer creates a guaranteed failed request during load.
- `scripts/health_check.py` crashed on Windows GBK console output before it could report health. It now forces UTF-8 stdout/stderr like the other pipeline scripts, so local/Hermes health reporting can complete.
- `scripts/build_publish_bundle.py` now includes page-level status for `announcements`, `rights_analysis`, `fundflow`, `breakthroughs`, `corp_graded_scan`, `watchlist`, and `history`, not only holdings/signals/alerts/market.
- Hermes/Telegram health summaries must read the same `data/publish_bundle.json` metadata as the dashboard. The bundle Telegram summary now includes `anns`, `rights`, `flow`, and `transfers`, and `scripts/health_check.py` prints those same fields in the CCASS publish line.
- `ccass/scripts/daily_refresh.sh` now refreshes corporate announcements, breakthrough data, same-day corporate grading, and local alerts/watchlist/history exports before rebuilding rights/signals/publish bundle.
- Daily refresh no longer aborts staging merely because `audit_gate.py` fails on partial CCASS coverage. It continues staging fresh non-CCASS feeds while `publish_bundle` and Hermes honestly show `publish=FAIL/PARTIAL`.
- Direct Cloudflare deploy helper now uses a `data/*.json` whitelist instead of uploading nearly every JSON under `data/`. Dry-run deploy package dropped from about 43.6 MB to about 22.1 MB and no longer includes unused heavy cache/intermediate files such as `data/replay_results.json` or `data/price_cache/*.json`.
- Current audit truth remains red for CCASS: local DB latest `2026-07-02` has only 48 stocks / 1.7% coverage; `holdings.json.updated` remains `2026-06-26`; transfer monitor remains `backfill_required`. Do not fake this to green.

### 2026-07-04 main page partial-state UI cleanup

- Screenshot audit found the main page looked healthier than it really was: the top status dot stayed green even when `data/publish_bundle.json.publish.status=FAIL` because CCASS was partial.
- `index.html` now sets the top status dot to amber/warn for publish `FAIL`/partial and shortens the status text to `系統 YYYY-MM-DD HH:mm · CCASS MM/DD · PARTIAL`.
- Stale market chips now display the stale cached value with a `舊` + source tag, but suppress valuation/eval badges while stale. This prevents `HSI/M2` from showing a blank value with an old `高/合理` badge.
- The market partial line now says `部分刷新 · 舊欄 N` instead of the mixed `partial · 1舊` wording.
- Theme heatmap `高動能` was too broad because `p52>=30` admitted roughly half the market. It now requires real upper-range strength with `p52>=80` unless volume ratio or same-day change already qualify.

### 2026-07-03 daily freshness repair and CCASS partial truth

- User reported the live system still looked like `2026-07-01` on `2026-07-03`; confirmed local `data/publish_bundle.json` had previously been generated on `2026-07-01T16:48:57`.
- Refreshed public daily feeds without GitHub/`gh`: Longbridge price fallback, market card cache, westock fund-flow, announcements-to-rights sync, placement returns, rights page JSON/HTML, signals/events, timing/jieqi/distribution/daily prompt pages, breakthrough JSON, corp graded scan, alerts/watchlist exports, and publish bundle.
- Current public freshness after rebuild:
  - `data/publish_bundle.json.generated_at=2026-07-03T16:58:49`
  - `data/announcements.json` has 803 rows, latest announcement date `2026-07-03`.
  - `data/rights_analysis.json` has 502 rows after syncing the latest placement/rights announcements.
  - `data/signals.json.updatedAt=2026-07-03T16:58:44`
  - `data/alerts.json.updated=2026-07-03 08:54 UTC`
  - `data/watchlist.json.updated=2026-07-03 08:54 UTC`
  - `data/fundflow.json.updated=2026-07-03`
  - `data/breakthroughs.json.updated=2026-07-03T16:58:21+08:00`
  - `data/corp_graded_scan.json.scan_date=2026-07-03`
  - `market.json.updated_at=2026-07-03T08:33:58+00:00`
  - `raw/prices_20260703.json` saved from the 2026-07-03 price cache.
- CCASS/holdings must remain honestly labelled: `holdings.json.updated=2026-06-26`; local DB probe/scrape reached `2026-07-02` but only `48/2806` stocks, coverage `1.7%`, so `audit_gate.py --min-coverage 99.0` correctly stays `FAIL`.
- Do not fake `holdings.json` to `2026-07-03`. The publish bundle should keep showing `publish=FAIL`, `latest_db=2026-07-02 (1.7%)`, and transfer backfill required until participant DB coverage is actually complete.
- Root cause for long "loading" during CCASS refresh: `HOLDINGS_DAILY_MAX_MINUTES` was checked only between HKEX batches, while a single batch could wait far beyond the remaining daily budget. `ccass/src/runner.py` now caps batch and single-stock child timeouts by the remaining daily budget.
- Windows console bug fixed in `scanner/_corp_graded_scan.py` by forcing UTF-8 stdout/stderr before printing emoji/Chinese scan results.

### 2026-07-03 GitHub Pages and Actions disabled

- User received a GitHub email titled `pages build and deployment`, with build/report status succeeded and deploy failed. This was GitHub Pages' built-in `pages build and deployment` workflow, not Codex using the `gh` CLI.
- GitHub Pages was still enabled for `rachellam28-lang/hk-alert-cloud-gas`, build type `legacy`, source `main /`, URL `https://rachellam28-lang.github.io/hk-alert-cloud-gas/`. Deleted the GitHub Pages site via GitHub REST API; verification now returns HTTP `404` for `/repos/rachellam28-lang/hk-alert-cloud-gas/pages`.
- Disabled GitHub Actions at repository settings via GitHub REST API; verification now returns `{"enabled":false}` for `/repos/rachellam28-lang/hk-alert-cloud-gas/actions/permissions`.
- Cloudflare live site was unaffected and still served the latest direct-deploy build: root HTML contains `mcSectionHeat` and `.ev-gray`, and response headers include `Cache-Control: no-store`.
- Local guardrails added so old helper scripts cannot accidentally write to GitHub:
  - Deleted `_enable_pages.py`, `_verify_push.py`, and `scripts/gh_push_announcements.py`.
  - `scripts/codex_pipeline.py`, `ccass/scripts/post_backfill.py`, and `scripts/may_backfill_all.py` now skip GitHub push unless `ALLOW_GITHUB_WRITE=1` is explicitly set.
  - `.github/workflows/ccass_events.yml` no longer runs `git push` in its local copy.
- `AGENTS.md` now says deploy only by direct Wrangler upload to Cloudflare Pages, not main-branch push/GitHub Pages/GitHub Actions.

### 2026-07-02 Cloudflare production rollback check and gray badges

- `index.html` and `signals.html` now define `.ev-gray`, so market eval badges with `color:"gray"` such as HSI/M2 and SPX/M2 `合理` render with the same framed badge style as green/orange/red/neutral labels.
- Live production was found serving an older `index.html` that did not contain the current heatmap globals (`mcSectionHeat`, `scrollHeatMatchesIntoView`, and `function renderHeatmaps`). Local repo HEAD still had the latest heatmap commits, so the issue was Cloudflare production content, not a local worktree revert.
- Deployed directly with `ccass/scripts/_deploy_cf.py`; production root verified with cache-bust HTML checks for the heatmap markers plus `.ev-gray`, and a headless Chromium DOM audit verified the `合理` gray badge is framed, 24 heatmap tiles render, clicking `圈股吸貨` opens `Heatmap 命中` with 8 rows, and no JS exceptions fired.
- Follow-up root cause: Cloudflare Pages still had Git provider auto deployments enabled. At `2026-07-02T01:39Z`, Cloudflare received a `github:push` deployment from commit `ffc02c5` (`daily: westock deltas + fund flow + FCF 5Y 2026-07-02`) and production reverted to the older Git-built site. This was a Cloudflare Git integration trigger, not a `gh` command run from Codex.
- Fix applied in Cloudflare Pages project config via API/OAuth: keep source metadata but set `deployments_enabled=false`, `production_deployments_enabled=false`, `preview_deployment_setting=none`, `preview_branch_excludes=["*"]`, and path deploys disabled. Future GitHub pushes should no longer auto-deploy this Pages project.
- `_headers` now includes `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` for all deployed files to reduce stale HTML/JSON/browser-cache confusion.
- Final correction deploy: after disabling Cloudflare Git auto deploy, deployed local commit `dc99bc6 fix(deploy): disable stale page caching` directly to Cloudflare. Latest production deployment became `dfb402a9` with trigger `ad_hoc`, not `github:push`. Production `/` without query now contains `mcSectionHeat`, `scrollHeatMatchesIntoView`, `function renderHeatmaps`, `.ev-gray`, and `HSI/M2`; response headers include `Cache-Control: no-store...`.
- Final headless Chromium production audit verified `.ev-gray` text `合理` has a 1px border, 24 heatmap tiles render, clicking `supply_stock` opens `Heatmap 命中：圈股吸貨` with 8 rows, scrolls down, and no JS exceptions fired.
- Current incident log:
  - Read `AGENTS.md`, `CODEX_MEMORY.md`, and `git status --short` before touching files.
  - Compared local `index.html` with `https://hk-alert-cloud-gas.pages.dev/?verify=...`; local had latest heatmap code, live production did not.
  - Added `.ev-gray` to both `index.html` and `signals.html`.
  - Ran embedded-script parse check for `index.html` and `signals.html`; both passed.
  - Ran `git diff --check` on the touched files; no whitespace errors beyond normal line-ending warnings.
  - Committed only `index.html`, `signals.html`, and `CODEX_MEMORY.md` as `b4f6fc5 fix(main): frame gray market badges`.
  - Direct Cloudflare deploy returned preview `https://2faf647d.hk-alert-cloud-gas.pages.dev`; no GitHub/`gh` route was used.
  - Production cache-bust check verified `mcSectionHeat`, `scrollHeatMatchesIntoView`, `function renderHeatmaps`, `.ev-gray`, and `HSI/M2` are all present.
  - Headless Chromium DOM check on production verified `.ev-gray` text `合理` has a 1px border, 24 heatmap tiles render, `supply_stock` click scrolls to `Heatmap 命中：圈股吸貨`, and 8 rows appear.
  - After the commit/deploy, the only remaining dirty worktree files were pre-existing data files: `data/announcements.json`, `data/breakthroughs.json`, and `data/corp_graded_scan.json`.

### 2026-07-01 heatmap no-filter marking and stable render

- Main-page heatmap clicks must not narrow the stock table. Theme/sector/fund-flow tiles now set only `heatMarkType` / `heatMarkKey`; toolbar dropdowns remain the only theme/sector filters, and `flowFilter` remains a toolbar/preset filter.
- Rows and mobile stock cards matching the active heatmap tile get `.heat-marked` blue highlighting while the table keeps its current full filtered set. Heatmap clicks do not update URL query params, presets, `themeSelect`, `sectorSelect`, or `flowFilter`.
- Heatmap-marked rows are promoted to the top of the current table sort, then the normal primary/secondary sort continues inside marked and unmarked groups. This keeps the full table visible while making each Heatmap tap visibly change the stocks below.
- Because the main table is split into small/mid/large market-cap sections, active heatmap matches are also rendered in a dedicated `Heatmap 命中` section directly below the heatmap card. The original market-cap sections remain below, so heatmap does not replace the full table.
- Heatmap panels no longer cross-filter by theme/sector/flow/search/table controls. The three panel subtitles show `全市場`, and each panel computes from `allStocks`. Clicking a tile updates the global `Heatmap 命中` list even if the main table currently has a sector/search/range filter.
- Heatmap tile activation scrolls to `Heatmap 命中` so mobile users immediately see the stock list change instead of staying on the heatmap grid.
- Heatmap rendering is gated until holdings, `data/fundflow.json`, `data/signals.json`, and `data/alerts.json` have all completed or failed. Before then, the card shows a compact loading state instead of drawing partial percentages that later jump.
- Fund-flow failure now marks the feed complete with `未載入`, so the heatmap can still render a stable empty/fallback state instead of hanging.
- Local headless Chrome audit verified: two reloads produced identical heatmap signatures, 24 tiles rendered, fund-flow meta `資金 2026-06-30 · 500`, clicking the `supply_stock` theme tile kept `filtered.length` at 2731, kept URL/selectors unchanged, set `aria-pressed=true`, and marked 8 matching filtered stocks without JS exceptions.
- Follow-up local audit verified switching from `supply_stock` to `supply_cash` keeps `filtered.length` at 2731 but changes the first visible stock batch from the 8 marked supply-stock names to the supply-cash marked names.
- DOM audit verified `#mcHeatTbody` itself changes: before click the section is hidden; `supply_stock` shows all 8 marked rows; switching to `supply_cash` changes the section title/count and shows the first 120 of 164 marked rows, with URL/selectors unchanged.
- Follow-up audit with sector filter `電訊/基建` active verified Heatmap subtitles remain `全市場`, tile counts stay global, `Heatmap 命中` still shows global matches, and the page scrolls to that section after tile activation.

### 2026-07-01 heatmap active tile visibility

- Main-page heatmap tiles must visibly show selection after click/tap. Active tiles now use a blue fill, stronger border/shadow, and `aria-pressed=true`.
- Empty active tiles must not stay faded. `.heat-tile.empty` opacity only applies when the tile is not active, so zero-count theme tiles still look selected when tapped.
- Zero-count inactive sector/flow heatmap tiles are disabled and must not apply a new filter. Theme heatmap tiles stay clickable even at 0 matches, so the tile can still turn active and clearly show an empty result.
- Heatmap card audit after the zero-tile fixes:
  - DOM counts match the page's own theme/sector/flow filter functions.
  - Tile click row counts match displayed tile counts.
  - Mobile touch on heatmap chips is treated as a tile tap only, so chips cannot steal the tap and open a drawer unpredictably. Desktop/mouse chip clicks may still open the stock drawer.
  - Mobile 390px layout has no heatmap tile overflow.
  - `data/fundflow.json` was refreshed from westock to `2026-06-30` with 500 symbols; the heatmap header now shows `資金 2026-06-30 · 500`.
- Mobile heatmap tap handling is delegated at `#heatmapWrap`, not per-tile inline `onclick`. It uses touch/click/keyboard handling plus `elementFromPoint` and tile-rect fallback because some mobile compatibility clicks report `.heatmap-panel` instead of the tile under the finger.
- Stock-chip drawer opens only for non-touch clicks when the click coordinate is inside the chip rect; mobile tapping tile text/meta or chips applies the filter only.
- Latest theme audit: all six theme tiles stay clickable under a scoped sector filter, including a 0-count `supply_stock`; mobile chip taps select the parent tile without opening the drawer.
- Local headless Chrome mobile audit verified: all six theme tiles become active on touch, including when the center hit target is a chip button; no drawer opens from mobile heatmap taps; clear button resets; fundflow meta is `資金 2026-06-30 · 500`; sector `其他/未分類` count is 495.

### 2026-06-30 main heatmap card, sector overrides, and fund-flow heatmap

- Main-page heatmaps remain in their own `section.card heatmap-card`, separate from table controls, with three panels: theme, sector, and fund flow.
- The heatmap card now has a compact header with fund-flow publish date/count metadata so it does not look stuck while data is loading.
- Sector grouping still avoids another heavy JSON source. It now checks a lightweight `SECTOR_CODE_MAP` for common HK large caps before falling back to stock-name keyword rules, which reduces obvious wrong-sector placements.
- Sector grouping should not dump holding-company names into `其他/未分類`. `index.html` now has a `綜合/控股` sector for generic holding/group/development names, broader bilingual keyword rules, short English token boundary matching for `AI`/`EV`, and extra exact code overrides for obvious HK names. Local audit improved sector heatmap `other` from 1768 to about 495 stocks.
- Main page now fetches existing `data/fundflow.json` and builds a clickable fund-flow heatmap from `main_net`, `total_net`, and `lgt_cap_chg_daily`.
- Fund-flow heatmap tiles cover main/total/southbound inflow and outflow; clicking a tile applies the flow filter, and presets/URL state persist the `flow` filter.
- Heatmap tiles must connect to stocks without making mobile taps unstable. Each tile shows top stock-code chips; on mobile, chips behave as part of the tile and apply the filter only. On desktop/mouse click, a chip applies the parent heatmap filter and opens the stock drawer.
- Heatmap stats/chips must use the current filter context, not raw `allStocks`. `stockPassesFilters()` is shared by table filtering and heatmap rendering; each heatmap panel skips only its own dimension (`theme`, `sector`, or `flow`) so the tile count/chips match the stocks that will appear after clicking.
- Heatmap panel headers show the current scope label (`全市場`, `汽車/新能源內`, `大市值內`, etc.) so cross-filtered counts do not look like broken global totals after the user clicks a theme/sector/flow tile.
- Theme heatmap wording must not look like `圈錢可炒`. The positive supply theme is labelled `圈股吸貨`; `圈錢` remains a separate avoid/dilution theme.
- Keep the heatmap compact. The main-page heatmap card uses reduced tile height, dense grid gaps, smaller panel padding, and three top stock chips per tile so it does not dominate the dashboard.

### 2026-06-30 main signal badge and theme/sector heatmaps

- Main page corporate-action signal badges were changed from the old issuer-favourability wording to `圈股判斷`, sourced from `data/signals.json.groups[].supply`, which is copied from the canonical `data/rights_analysis.json` supply/cash judgement.
- `data/signals.json` still keeps `issuer` for audit/backward compatibility, but visible main-page badges must not show `發行方有利度`.
- Verified live `01069` reads `supply.label = 圈錢` with basis: current price below issue price, weak post-announcement return, below both year-open lines, T+5 below threshold, and large dilution.
- Main page added `主題選股` and `板塊選股` selectors. They save/restore through presets, reset, and URL state.
- Main page added theme/sector heatmaps using only existing in-page data: holdings, signalMap, techSignalMap, and lightweight stock-name keyword grouping. Do not add a heavy sector/theme JSON unless a canonical sector source is introduced.
- Heatmaps are in their own `section.card heatmap-card`, separate from the toolbar/table-control card. Clicking a heatmap tile applies the matching selector; clear buttons reset theme or sector.
- Keep Telegram Hermes bot summaries aligned with the same dashboard/publish metadata after these main-page UI/data changes; never store Hermes bot secrets in tracked files.
- Relevant commits:
  - `ef6d6bf fix(main): show supply judgement badges`
  - `c8052b1 feat(main): add theme sector heatmaps`
  - `8712084 fix(main): split heatmap into card`
- Deployed directly to Cloudflare Pages with `ccass/scripts/_deploy_cf.py`; no GitHub/`gh` route was used.

### 2026-06-30 rights year-open judgement and deploy slimming

- User clarified not to add another 2025/year-open JSON. Rights supply judgement must use the same dashboard price cache only: `data/stock_prices.json` fields `yo` (current year open) and `py` (dashboard "前年" open).
- `scripts/gen_rights_page.py` now adds `supply.year_open` from `stock_prices.json` and uses it in `圈股/圈錢` scoring:
  - above both `yo` and `py` supports `圈股`;
  - below both supports `圈錢`;
  - one missing line is labelled as insufficient instead of faking confidence.
- `rights_analysis.html` now shows a `年開線` badge inside the issuer stack, with tooltip details like current price versus the two year-open lines.
- `rights_analysis.html` also renders YO/PY as a separate visible detail line below the year-open badge, not only in the tooltip.
- Current UI rule: YO/PY are separate sortable table columns, not search-only text. `公告拆解` should stay structural only (stage, carried-forward terms date, issuer/shareholder/reaction scores). `邏輯` should carry the supply/placement reasoning and must not repeat `發行方有利度`, category-stage text, or `攤薄` because those are already separate columns/fields.
- Rights page `市價` must display and sort by `display_market_price`, sourced from latest raw/`latest_price`/`stock_prices.lp`, matching the main page. Do not use `market_price` for visible current price; in placement data it is the announcement/event reference price used for discount calculation and is copied to `announcement_market_price` for clarity.
- Longbridge `quote` is real-time/last-traded price (`last`/`last_done`), not proof of a settled daily close. After market close, use Longbridge daily `kline` close for `lp`/raw close when available. `raw/prices_YYYYMMDD.json` rows should carry `source_date`; stale quote rows must be ignored by placement return and rights-page latest-close logic.
- Rights/placement lifecycle rows should not look like duplicate new deals. Keep canonical `category` for filtering, but use `category_display` on the page, e.g. `供股結果` for a results/completion announcement that carries terms from the original `供股` row.
- 1069-style lifecycle audit: keep original terms rows and completion/update rows, but label them by `category_display` and `announcement_stage`. Current generated data has 37 carry-forward rows: 16 completion/result rows and 10 supplement/extension rows, with source dates resolved and label issues at 0.
- Exact duplicate protection is separate from lifecycle handling. `scripts/sync_rights_from_announcements.py` and `scripts/gen_rights_page.py` dedupe only fully identical rows using code/date/category/title/method/purpose/price/shares/amount/pct/pdf, so multi-tranche same-day announcements are preserved. Current `placements_enriched.json` and `rights_analysis.json` have 480 rows and 0 exact duplicates.
- Do not add `data/year_open_cache.json`; no separate westock/yfinance cache is needed for this judgement.
- Page-source audit found exact duplicate public aliases: `holdings.json == data/holdings.json`, `ccass.json == data/ccass.json`, and `market.json == data/market.json`. Public pages use the root versions, not the `data/*` aliases.
- `ccass/scripts/_deploy_cf.py` now skips deploying `data/holdings.json`, `data/ccass.json`, and `data/market.json` to Cloudflare Pages while keeping them in the worktree for local pipeline/audit compatibility.

### 2026-06-30 daily page refresh rule and rights feed sync

- User explicitly requires every page to update daily, not only selected cards or root JSON. Keep this as a standing rule for future work.
- Root cause of the stale supply/placement page: `rights_analysis.html` reads `data/rights_analysis.json`, but that JSON was generated only from stale `data/placements_enriched.json`; latest `data/announcements.json` already had newer placement/rights announcements.
- Fix: `scripts/sync_rights_from_announcements.py` bridges `data/announcements.json` into `data/placements_enriched.json` before `scripts/gen_rights_page.py`, so the rights page and main issuer badges share the same current announcement feed.
- `ccass/scripts/daily_refresh.sh` runs the rights announcement sync before placement return refresh and stages `data/announcements.json`, `data/placements_enriched.json`, and `data/rights_analysis.json` with the rest of the refreshed site files.
- Current regenerated supply/placement data has 481 rows and latest announcement date `2026-06-28`; examples verified: `01069` latest rights row `2026-06-16` score 100, `09982` row `2026-06-18`.
- Windows-safe stdout/stderr encoding was added to `scripts/gen_rights_page.py` and `scripts/build_signals.py`; daily refresh must not fail merely because console output contains emoji or Chinese labels.
- Rights page comment text was improved after user feedback. `scripts/gen_rights_page.py` now builds a human-readable comment from announcement stage, carried-forward terms, issuer score, discount, dilution, announcement-to-now return, issue-price return, and T+5 reaction, instead of only showing old T+5/jump wording.
- Terminal/cancelled rights or placement announcements show `已終止/取消` and are not treated as fresh supply pressure in the comment.
- User's intended distinction: `圈股` means new/rights shares appear absorbed or locked after ex-rights/completion, so it may have tradable supply-squeeze potential; `圈錢` means the deal is mainly cash-raising/dilution pressure and should not be treated as a buy setup.
- Rights page `圈股判斷` uses ex-rights/completion evidence first: price versus issue/rights price after completion/ex-rights, announcement-to-now return, T+5 as auxiliary evidence, discount, dilution, and use of proceeds. If terms or completion/ex-rights anchor are missing, label `待確認` rather than pretending to know.

### 2026-06-30 market card partial-refresh UI

- User reported the market card still had not changed after Longbridge auth, and then clarified that HSI and US/HK P/E must both update.
- `scripts/dopamine_refresh.py` now uses Longbridge CLI to refresh HSI, Dow, S&P 500, VIX, and US market temperature/fear-greed style sentiment.
- HSI P/E and S&P 500 P/E are refreshed from WorldPERatio, not yfinance:
  - HSI P/E source: `https://worldperatio.com/area/hong-kong/`
  - S&P 500 P/E source: `https://worldperatio.com/index/sp-500/`
- DXY is not available from Longbridge CLI for this account (`.DXY.US` returns no quote); it is refreshed from CNBC `.DXY`.
- HSI/M2 and S&P 500/M2 are refreshed directly from HKMA and FRED:
  - HK M2 source: HKMA `money/supply-adjusted`, `m2_total`.
  - US M2 source: FRED `M2SL` CSV.
- Current market card publish data is fully fresh: Longbridge fields are `hsi`, `dow`, `spx`, `vix`, `fear_greed`; P/E fields are `hsi_pe`, `spx_pe`; CNBC field is `dxy`; M2 fields are `hsi_m2`, `spx_m2`; `market_stale_fields=[]`.
- `scripts/build_publish_bundle.py` separates `dopamine_stale` from market-card stale status, so a Futu dopamine timeout no longer makes the market card report stale.
- Fix: `index.html` and `signals.html` now render market state from `market_longbridge_fields`, `market_pe_fields`, `market_cnbc_fields`, `market_m2_fields`, and `market_stale_fields` instead of hard-coding HSI-only wording. Stale chips show `舊`; fresh Longbridge chips show `LB`, P/E chips show `PE`, DXY shows `CNBC`, and M2 chips show `M2`.
- `signals.html` also had a missing closing `</script>` tag at EOF; fixed before deploy.

### 2026-06-29 live data refresh and no-GitHub deploy

- User asked whether data was actually updated; refresh/deploy must stay direct Cloudflare and must not use `gh`.
- Added `scripts/fetch_fundflow.py` as a Windows-safe fund-flow refresh path using `westock-data-clawhub`; it writes `data/fundflow.json` directly.
- `ccass/scripts/daily_refresh.sh` now runs the fund-flow refresh before building `data/publish_bundle.json` and stages `data/fundflow.json`.
- Current refreshed publish data:
  - `data/fundflow.json`: `2026-06-29`, 500 symbols.
  - `data/signals.json`: generated `2026-06-29`, 2731 symbols.
  - `data/alerts.json` / `data/watchlist.json`: exported `2026-06-29 05:13 UTC`.
  - `data/breakthroughs.json`: generated `2026-06-29`, 41 signals.
  - `data/announcements.json`: 728 HKEX announcement items.
  - `holdings.json` and `data/holdings.json`: `2026-06-26`, 2731 symbols, 99.5% coverage.
- Historical note from before Longbridge auth: market quote cache was stale because Futu timed out and Longbridge auth was not yet restored. Superseded by the 2026-06-30 market refresh note.
- Participant-level transfer DB is not complete for `2026-06-26`; full HKEX participant backfill was too slow and only wrote 24/2759 rows before being stopped.
- Transfer publish output now truthfully uses `ok:false`, `status:"backfill_required"`, date `2026-06-26`; pages must not show stale `2026-06-05` transfer signals.
- `ccass/scripts/audit_gate.py --min-coverage 99.0` still fails on local participant DB backfill mismatch; do not fake PASS. Deploy corrected publish JSON with the backfill status clearly labelled.

### 2026-06-29 Longbridge CLI auth and market fallback

- User supplied a one-time Longbridge auth code; redeemed it with Longbridge CLI, then installed the Codex plugin `longbridge@longbridge-skills`.
- Longbridge CLI installed at `%LOCALAPPDATA%\Programs\longbridge\longbridge.exe`, version `0.24.0`, auth status valid.
- Verification quotes succeeded for `NVDA.US` and `00700.HK`.
- `.env` exists as an ignored local template, but the CLI token is stored by Longbridge under the user profile; do not print or commit tokens.
- `ccass/scripts/daily_lp_longbridge.py` now uses the authenticated Longbridge CLI for quote fallback before trying MCP bearer token.
- `scripts/dopamine_refresh.py` initially used Longbridge CLI for HSI fallback before trying MCP bearer token; superseded on 2026-06-30 by multi-field Longbridge quote refresh plus WorldPERatio P/E refresh.
- On 2026-06-29, live HKEX HOLDINGS probe returned no data for `00700` on `2026-06-29` but valid participant data for `2026-06-26`; dashboard should label this as `CCASS持倉日`, not a whole-system stale date.
- `scripts/health_check.py` treats both `holdings.json` and `data/holdings.json` as publish-date/coverage checks instead of file-mtime freshness, so weekend/T-1 CCASS lag does not create false stale alerts.

### 2026-06-29 page data audit and transfer freshness guard

- Read `AGENTS.md` and `CODEX_MEMORY.md` before touching the system.
- All-page data audit found the live/local mismatch still visible on `gap_fvg.html`: `holdings.json.updated=2026-06-26` but `data/transfers.json.updated=2026-06-05 vs 2026-06-04`.
- Local `ccass/holdings.db` and root `holdings.db` are both 0 bytes, so do not fake a new transfer monitor; true transfer generation needs participant-level DB rows.
- Fix: `ccass/scripts/detect_transfers.py` now generates transfer JSON for the publishable `holdings.json.updated` date, writes both `ccass/data/transfers.json` and `data/transfers.json`, and fails clearly if the DB is missing/empty.
- Fix: `ccass/scripts/daily_refresh.sh` now runs transfer generation and stages both transfer JSON aliases.
- Fix: `ccass/scripts/audit_gate.py` now fails when transfer JSON date does not match `holdings.json.updated`.
- Fix: `gap_fvg.html` now compares holdings date with transfer date; stale transfer data is not counted as a current signal and shows an explicit backend-not-updated notice.
- Fix: `data/publish_bundle.json` now includes transfer metadata for shared freshness reporting.
- Fix: `ccass/scripts/_deploy_cf.py` now deploys a complete curated static-site set instead of only five files.
- User requested direct Cloudflare deploy instead of using `gh`; use a curated temporary Pages upload folder, not repo root, to avoid uploading local tooling, backups, or token helper files.
- Previous successful direct Wrangler deploy logs were found under `C:\Users\Administrator\Desktop\automatic\ccass-debug`.
- The only local Cloudflare token found for that path verifies as invalid/revoked, and Wrangler returns Cloudflare authentication error `10000`; live deploy is blocked until valid Cloudflare auth is restored.
- User approved Chrome OAuth on 2026-06-29; `wrangler login` succeeded using the existing Cloudflare browser session, so direct Pages deploy can use Wrangler OAuth cache without replacing the old API token.
- Do not deploy `AGENTS.md` or `CODEX_MEMORY.md` to Cloudflare public output; keep Markdown in the worktree only.

### 2026-06-29 GitHub refresh route disabled

- User received `ccass-refresh` GitHub Actions failure emails after direct Cloudflare deploy.
- Root cause: `.github/workflows/ccass_refresh.yml` still had a native GitHub `schedule`, and `cloudflare/refresh-cron` still dispatched GitHub Actions.
- Fix: disable GitHub schedules in `ccass_refresh.yml` and `ccass_events.yml`.
- Fix: change Cloudflare Worker `ccass-refresh-cron` to no-op; it must not call GitHub API or dispatch workflows.
- Direct Cloudflare deploy remains the active path.
- Public exposure note: unauthenticated HTTP to `https://github.com/rachellam28-lang/hk-alert-cloud-gas` returns 200, so GitHub repo visibility must be changed to private separately if the user wants repository contents not searchable.

### 2026-06-29 stale refresh and 02889 undefined POC fix

- Live warning "data stale 67 hours" was a backend freshness problem, not a page rendering problem.
- Root cause found: `.github/workflows/ccass_refresh.yml` only had `workflow_dispatch`; the scheduled run depended entirely on Cloudflare cron dispatch.
- Superseded: the GitHub Actions schedule fallback was later disabled because the user wants direct Cloudflare deploy, not GitHub refresh/deploy.
- `02889` showed `+undefined%` / `POC undefined -> undefined` because HKEX corp-action alerts from `data/alerts.json` were merged into the technical-signal map.
- Fix: `index.html` and `signals.html` now filter alert merges with `isTechnicalAlert`; `source=hkexnews` / `category=corp_action` stays in announcement/corp paths only.
- Local verification: embedded JS parsed successfully and real `data/alerts.json` filtering leaves `02889` with zero technical alerts.

### 2026-06-29 page data unification

- Commit pushed: `452a40b fix: unify signal data and timing tables`.
- Cloudflare live verified after that push:
  - `timing_analysis.html` shows a signal-date table, next window `2026-07-07`, no old delta columns, no backtest-first UI.
  - `jieqi_analysis.html` shows a signal-date table, no old delta columns, no backtest-first UI.
  - `distribution_day.html` shows a signal-date table, no old delta columns, no backtest-first UI.
  - `index.html` no longer exposes old `5d`, `20d`, or `60d` deltas.
  - Live `data/signals.json` has `01069` issuer score `100`, label `highly issuer-favourable`, rights date `2026-06-16`.
- Root cause: `index.html` dropped the `issuer` payload while building `signalMap`, then fell back to a local estimate and displayed score `65`.
- Long-term fix: generate rights analysis before signals, then let signals reuse the canonical issuer payload.

### 2026-07-04 Taste redesign pass

- User asked to use the installed taste skill to rework the CCASS dashboard.
- Correct skill for this repo is `redesign-existing-projects`, because CCASS is a dense trading dashboard, not a landing page.
- Applied a low-risk CSS override pass to `index.html` only: calmer terminal palette, denser market chips, stronger heatmap active/hover states, better buttons/filters, cleaner market-cap sections, and mobile-friendly heatmap sizing.
- Fixed a CSS scope bug introduced during the pass: sticky table headers now target `.mc-section` only, so IPO/placement mini tables are not distorted.
- Fixed sticky-toolbar blank-space behavior by letting the outer dashboard card use `overflow:visible` while nested heatmap cards remain clipped.
- Follow-up same day: user said mobile cards were too large; compressed mobile market chips, IPO/placement cards, toolbar, and heatmap tiles. On 393px viewport, market chip block reduced from about 165px to 109px and heatmap tiles from about 69px to 54px.
- Follow-up same day: user wanted mobile market cards in one row. `index.html` and `signals.html` mobile `.mbar` now use horizontal nowrap scroll instead of wrapping/grid rows.
- Verification: `python -m pytest tests/test_main_heatmap_smoke.py -q` passed; Playwright screenshots checked desktop and mobile locally.
- Remaining truth-in-data warning: participant/backfill coverage is still the core incomplete issue; dashboard and Hermes must say `partial`/`backfill_required` instead of pretending all signals are fully trade-ready.

### 2026-07-04 fake-green audit

- User challenged whether the system was still showing fake readiness. Clarification: no fabricated market data was found in this pass; the problem was optimistic status coloring/wording.
- Fixed `scripts/health_check.py`: `holdings.json` and `data/holdings.json` now show warning when `is_complete=false`, even if date and coverage are present. `publish_bundle` now shows warning for `publish.status=WARN` instead of green just because the bundle exists.
- Fixed `scripts/health_check.py` price freshness: `price_snapshot` now checks primary `data/stock_prices.json` `price_updated_at`/`lp_time` and accepts the previous trading day on weekends, instead of marking `data/prices.json` mtime stale.
- Fixed `signals.html`: top status now reads `data/publish_bundle.json` and turns amber for `WARN/PARTIAL`.
- Fixed `gap_fvg.html`: top status now turns amber when holdings are incomplete, transfers are unusable, or `publish_bundle` is not `PASS`; loading success alone no longer means green.
- Verification: local browser probe showed `index.html`, `signals.html`, and `gap_fvg.html` all expose `dot warn` under current `publish=WARN`; `scripts/health_check.py` now ends with `WARNINGS`, not false `ALL OK`.

### 2026-07-04 CCASS Health Watchdog WinError 10053

- Automation `CCASS Health Watchdog` reported `[WinError 10053]` after the health check. Local `scripts/health_check.py` and `scripts/health_check.py --telegram` both returned exit `0` with current `WARNINGS`, so the data health result itself was not a hard failure.
- Root repo-side risk found in `scripts/sentry_cron.py`: final `sentry_sdk.flush(timeout=5)` was not wrapped, so a transient Sentry/network abort could turn an already-decided successful job result into a failed cron.
- Fix: final Sentry flush is now fail-open and preserves the job result.
- Fix: Telegram health push now retries once and stays fail-open; Telegram/Hermes notification failures must not change the health-check exit code.
- Fix: new `scripts/run_health_watchdog.py` wraps the health check plus direct Cloudflare deploy of `health.json`; real data-red exits still fail, but transient Telegram/Sentry/deploy network noise stays green with a warning.
- Rule: data/integrity red should fail watchdog; Sentry, Telegram, or Hermes network notification errors should only be warnings unless the data check itself is red.

### 2026-07-05 market card partial refresh cleared

- User reported live main-page market meta still showing `市場卡部分刷新 2026-07-03 08:33:58` with stale `hsi_m2`.
- Manual `scripts/dopamine_refresh.py` run succeeded for Longbridge, WorldPERatio, CNBC, HKMA, and FRED, and refreshed both `market.json` and `data/market.json`.
- Result: `hsi_m2` moved from `1078.4` stale to `1106.0` fresh, `market_partial=false`, `market_stale_fields=[]`, and `data/publish_bundle.json.files.market.partial=false`.
- Important nuance: Futu-backed dopamine still timed out and stayed fallback/stale, but market-card freshness is now clean because `dopamine_stale` is intentionally separate from market-card stale status.

### 2026-07-05 Hermes health notification dedup

- Researched `ZhuLinsen/daily_stock_analysis` for useful lightweight ideas only; did not import its GitHub/Docker/Web stack.
- Borrowed the notification-noise idea in a smaller repo-native form: `scripts/health_check.py` now keeps persistent Telegram dedup state in `logs/health_telegram_state.json`.
- Exact same Hermes health summary is suppressed for `HEALTH_TELEGRAM_DEDUP_TTL_SECONDS` seconds (default `21600`), even when only the header timestamp changed between cron retries.
- This protects the Hermes/status bot from duplicate watchdog spam without hiding changed health content or affecting the health-check exit code.

### 2026-07-05 cross-market momentum list page

- Added new static page `momentum_list.html` for managing cross-market momentum watchlists across HK stocks, US stocks, index/ETF proxies, and gold/resource names.
- The page now also has a dedicated `smallcap` bucket for high-volatility small-cap names, so small-cap runners do not get mixed into the broad-market buckets.
- The page stores local state in `localStorage` key `hk_cross_market_momentum_lists_v1`, normalizes symbols such as `00700 -> 00700.HK` and `NVDA -> NVDA.US`, can import HK codes from existing `hk_watchlist_v1`, and exports both a grouped plain list plus a ready-to-paste analysis prompt.
- Index/ETF defaults now include Japan and China proxies (`EWJ`, `ASHR`, `02823.HK`) in addition to US broad-market proxies (`SPY`, `QQQ`, `DIA`) and Hong Kong proxies (`02800.HK`, `03033.HK`).
- `shared-nav.js` now includes the new page so it appears in the site navigation, `guide.html` now uses the shared nav instead of a hardcoded nav list, and direct Cloudflare deploy helper `_deploy_cf.py` now includes `momentum_list.html`.

### 2026-07-06 Longbridge backfill source-of-truth fix

- Root cause found in `direct_backfill.py`: it was pointed at legacy `ccass/ccass.db`, while the live system source-of-truth is `ccass/holdings.db`.
- Impact: manual/Hermes Longbridge backfill diagnostics could report dates as empty in the wrong DB, and successful backfill writes would not necessarily land in the DB used by dashboard/publish health.
- Fix: `direct_backfill.py` now uses shared `src.db.DB_PATH` / `get_conn`, so it reads and writes the same `ccass/holdings.db` used by the rest of the pipeline.
- Fix: `direct_backfill.py` now has the current 10-date backlog queue, uses a PID lock like other backfill paths, and exits non-zero on auth-style hard failures or zero-success empty-date runs instead of silently returning exit `0`.
- Fix: historical `direct_backfill.py` now forces `LONGBRIDGE_USE_CLI=0` because the Longbridge CLI `broker-holding detail` command has no date flag and only returns latest holdings, which caused false date-mismatch drops before the API call.
- Fix: `ccass/src/longbridge_provider.py` now raises a clear runtime error when repeated `401` auth reload attempts still fail, instead of falling through with no usable response.
- Fix: `ccass/src/longbridge_provider.py` no longer falls back to `~/Desktop/automatic/holdings-debug/.env`; this repo must use its own `.env` or explicit environment only.
- Verified against the real `ccass/holdings.db` on 2026-07-06: `2026-07-03=2747`, `2026-07-02=48`, `2026-06-30=0`, `2026-06-27=0`, `2026-06-26=25`, `2026-06-25=1`, `2026-06-24=1`, `2026-06-23=1`, `2026-06-20=0`, `2026-06-19=0`.
- Verified at 2026-07-06 23:44 local: manual B-run (`2026-07-02,2026-06-30`) now hard-fails immediately on `401` instead of fake-running; repo `.env` exists but currently has no `LONGBRIDGE_ACCESS_TOKEN=` line, so backfill is blocked until a valid access token is stored in this repo root `.env`.
- Decision rule: do not estimate backfill need from legacy `ccass.db`; always inspect `ccass/holdings.db` because that is the only publish/dashboard source-of-truth.

### 2026-07-07 Futu/OpenD repo probe and machine-state audit

- Added `scripts/check_futu_setup.py` as the repo-local Futu/OpenD probe. It checks repo `.env`, `USE_FUTU`, TCP reachability to `FUTU_HOST:FUTU_PORT`, Python SDK import, quote context creation, `get_global_state()`, and a sample `get_market_snapshot(["HK.00700"])`.
- Added `scripts/futu_env.py` as the shared Futu/OpenD env/socket helper. Normalized old hardcoded localhost scripts to use repo `.env` plus the shared socket gate:
  - `ccass/scripts/daily_lp_futu.py`
  - `ccass/scripts/fetch_lp_yo_futu.py`
  - `ccass/scripts/fetch_py2024_futu.py`
  - `scripts/fetch_mc_futu.py`
  - `scripts/enrich_all_futu.py`
  - `scripts/pull_hkex_prices.py`
- The shared helper now distinguishes two different failure classes:
  - socket/listener missing (`127.0.0.1:11111` unreachable)
  - socket alive but quote backend not logged in (`qot_logined=false`)
- Futu data scripts now use a stronger quote-backend readiness gate, not only a raw TCP socket check. This prevents an offline/partially initialized gateway from pretending to be usable during daily refresh.
- Added `scripts/start_futu_opend_rs.py` as a local helper to start/stop the machine's `futu-opend-rs` gateway. It supports:
  - foreground interactive start for SMS/device verification
  - `--verify-code <SMS_CODE>` for non-interactive restart
  - `--stop-only` to clear a stale local listener on `127.0.0.1:11111`
- `ccass/scripts/daily_lp_futu.py` now prints a direct hint to run `scripts/check_futu_setup.py` when OpenD is unreachable, instead of only timing out.
- Current machine evidence on `2026-07-07`:
  - Repo `.env` has `FUTU_HOST=127.0.0.1`, `FUTU_PORT=11111`, `FUTU_CONNECT_TIMEOUT=2`, `USE_FUTU=true`.
  - Repo `.venv` has `futu_api 10.8.6808` installed.
  - `scripts/check_futu_setup.py` now distinguishes between:
    - TCP/socket down
    - socket up but `qot_logined=false` / `trd_logined=false`
    - quote path actually usable
  - Local roaming artifacts exist under `C:\Users\Administrator\AppData\Roaming\com.futunn.FutuOpenD`, including logs up to `2026-07-07`, which means this machine has prior OpenD usage traces.
  - A local Rust gateway install exists at `C:\Users\Administrator\futu-opend\futu-opend-rs-1.4.110\futu-opend.exe` with local config beside it.
  - Manual start on 2026-07-07 proved the gateway can bind `127.0.0.1:11111`, but backend quote login stayed offline because remember-login was rejected and device/SMS verification was required. In that state:
    - TCP connect works
    - `get_global_state()` works
    - `qot_logined=false`
    - market snapshot returns `no backend connection`
  - Background helper behavior on this machine:
    - without `--verify-code`, `start_futu_opend_rs.py --background` currently fails fast and stderr shows remember-login rejection plus the password/SMS flow kicking in
    - this is expected for a non-interactive process when device/SMS verification is still required
  - The temporary offline `futu-opend` listener started during this audit was later stopped, so port `11111` should not remain occupied by the repo audit itself.
- Decision rule: when Futu-backed paths fail, first run `python scripts/check_futu_setup.py` from repo root. Do not assume token/API issues; verify local OpenD socket and session health first.

## Open Items

- Keep auditing page data sources when new pages or JSON files are added.
- Audit SQL/SQLite pressure paths when time allows: look for unbounded loops, fan-out queries, missing indexes, parallel writes, retry storms, and refresh jobs that can hammer `ccass/holdings.db` or `holdings.db`.
- If local `ccass/holdings.db` is 0 bytes, audit gate should report structured fail instead of traceback.
- Verify Cloudflare live pages after every push that affects public files.

### 2026-07-11 page/data consolidation

- `py_pct` must always be recomputed from `latest_price` and the effective year-open (`apy` first, then `py`). Never copy stale `apy_pct`/`py_pct` between datasets. This removed 2,486 false dashboard mismatch warnings.
- `shared-nav.js` is the canonical grouped navigation and shared loading/error/empty-state shell. Run `scripts/apply_shared_shell.py` after generating public HTML pages; `daily_refresh.sh` already does this.
- `daily_trade_prompt.html` now fetches holdings/signals/tradeable JSON on demand instead of embedding them (about 5 MB to 68 KB). `vqc_analysis.html` embeds only page-used fields and the latest 300 events (about 2.7 MB to 195 KB).
- Current honest gate state remains WARN, not PASS: latest publishable CCASS is 2026-07-09 at 99.4% coverage; historical date gaps and current/historical verification backlog still need backfill/repair.
- Deploy public changes directly with `ccass/scripts/_deploy_cf.py`; do not use GitHub Pages or GitHub Actions as the deployment path.

### 2026-07-13 all-HK Kbar access

- Kbar charts must not render Distribution Day (DD) lines or load the DD backtest JSON. The standalone Distribution Day page/data remain intact.
- Visible Kbar order is fixed at quarter normal/inverted, half-year normal/inverted, then daily normal/inverted. The 4H pane and visible 4H wording were removed; hourly data remains internal to setup/trend calculations.
- `kbar_matrix.html` uses a hybrid source model. A searched HK symbol first lazy-loads `data/kbar_symbols/<5-digit-code>.json`; cached symbols retain the custom normal/inverted day, half-year, quarter, and 4H charts with CCASS and timing overlays.
- Superseded: the direct TradingView HK widget fallback was rejected by TradingView licensing. See the on-demand Cloudflare Kbar section below.
- `scripts/build_kbar_cache.py --symbols 1733` writes real per-symbol Futu shards. `--all-hk --resume` is resumable, and `--workers` controls concurrency. No yfinance or synthetic OHLC is allowed.
- Futu Rust gateway history quota was the reason uncached symbols failed (`100/100`). Local `.env` now sets `FUTU_HISTORY_KL_QUOTA_MAX=4000`; this setting is local-only and must never be deployed.
- Verified `01733` with 260 real daily bars through 2026-07-13 and 120 real 60-minute bars. Static Futu shards remain useful for symbols needing 1H Playbook analysis; all other HK symbols use the on-demand daily path below.
- Cloudflare deploy allowlist includes `data/kbar_symbols/*.json`. Deploy remains direct Wrangler through `ccass/scripts/_deploy_cf.py`, never GitHub.

### 2026-07-12 display fixes

- `index.html` market-cap sections now paginate independently at 10 stocks per page for small, mid, and large caps. Existing sorting, filters, signals, and rows are preserved; only the visible page size changed.
- `kbar_matrix.html` now uses larger responsive chart panes: three columns on wide desktop, two on tablet, one on mobile, with taller charts and stronger VQC/Jieqi/distribution-day marker lines and labels so reversal dates remain readable.
- Verification after the change: the four focused Playwright smoke/touch tests passed; browser check confirmed 30 rows and independent pagination in all three market-cap sections.
- `kbar_matrix.html` now adds a reproducible multi-timeframe Trend Guard: 1H/4H EMA direction plus 1H EMA21 close as the守位線, with `多頭守位`, `空頭守位`, `轉勢觀察`, or `多空未決` states. This implements the accessible part of the referenced Threads technique without claiming hidden video formulas.
- Main market metadata now explains partial refresh in plain language and names stale fields such as `SPX/M2`, rather than the ambiguous old source-count-only sentence.
- `kbar_matrix.html` now reserves a first `年圖` pane and level-overlay path for 1D data. `scripts/build_kbar_cache.py --daily-only` can fill 260 daily bars; the current Futu OpenD historical endpoint returned no rows for the long-range probe, so the UI must keep showing unavailable rather than fabricate a year chart.
- Futu daily backfill was corrected to use five-digit HK codes (`HK.00700`) and a current-year date range. Direct Futu batch verification populated 35 HK cache symbols with 126 daily bars; 700.HK was browser-verified with real year-chart candles. Non-HK symbols remain unavailable for this HK-specific daily source.
- Daily year-chart completion: `scripts/build_kbar_cache.py --daily-only` now preserves existing HK Futu bars and fills non-HK symbols through Longbridge. Current Kbar cache is 41/41 with 1D data: 35 HK symbols x 126 bars and 6 US/ETF symbols x 260 bars.
- Daily cache guarantee: the normal Kbar rebuild now records `daily_chart_ready` and adds an explicit `daily_chart` error when any newly selected symbol lacks 1D data; the daily refresh cannot silently present a new Kbar symbol without a year-chart series.
- Main table CCASS trends restored as four independent sortable columns: 5/20/60/120-day shares and percentage with reference dates. 60/120 display `資料不足` when their reference date is unavailable; they are not coerced to zero. The 5-day badge/filter now means any positive 5-day net change, while `su` remains a separate consecutive-positive-days metric.
- Added `rotation_matrix.html`: a Hong Kong sector rotation template using existing `holdings.json` only. It provides Leading/Weakening/Lagging/Improving quadrants, 5/20, 20/60, and 60/120 CCASS windows, sector detail rows, and links back to the main sector filter. Navigation exposes it as `板塊輪動`.
- Shared primary navigation now exposes `動量名單`, `每日提示`, `Gap/FVG`, `資金`, and `供配股`; only lower-frequency reference pages remain under `更多`.
- Kbar terminology is `破底翻`, not `破底返`: it requires a support/prior-low break followed by a close back above that same level. The chart now draws the broken support line and marks the reclaim candle with `翻`; a break without reclaim is not classified as 破底翻.
### 2026-07-13 Kbar single-chart TradingView trial

- User wanted system signals beside a TradingView-connected chart without downloading the whole market every day.
- Reworked `kbar_matrix.html` from six simultaneous chart panes to one large chart with six tabs: quarter, inverted quarter, half-year, inverted half-year, daily, inverted daily. Switching tabs rebuilds only one chart host.
- Added a date-filtered signal rail below the chart using only existing published JSON: VQC, jieqi dates, `data/signals.json` technical/corporate signals, rights/placement records, and CCASS delta only when the selected cached symbol has a real dated CCASS payload.
- Added a sourced key-level strip for latest price, 52-week high/low, year open, and IPO open/high/low. Missing values remain absent; no estimated data is inserted.
- Actual Chrome verification found TradingView's free Advanced Chart widget rejects embedded HKEX symbols, including `HKEX:700` and `HKEX:1733`, with "This symbol is only available on TradingView." This is an embed/licensing limit, not a symbol-search bug.
- Honest hybrid rule: cached HK symbols use one local real Kbar chart plus a TradingView external link; uncached HK symbols show the signal rail and an explicit TradingView external-link notice instead of a blank/fake chart; US/other supported markets keep one embedded TradingView widget.
- Cleaned duplicate runtime declarations so `renderMatrix`, `renderSetupLens`, `renderTrendGuard`, `renderSetupScoutBoard`, and `applyState` each have one active definition.
- Mobile overflow from the horizontal signal rail was fixed with zero-min-width grid children; verified 393px document width stays 393px.
- Updated `tests/test_kbar_timing_markers.py` for the single-chart contract and honest uncached-HK fallback.

### 2026-07-13 on-demand all-HK daily Kbar

- Added `functions/api/kbar/[code].js`, a restricted Cloudflare Pages Function for real unadjusted HK daily OHLCV. It accepts only a 1-5 digit HK code, hardcodes Tencent's public K-line host, caps output at 260 bars, validates every OHLC row, and never reads or exposes Longbridge/Futu secrets.
- Cross-checked the public source against the installed `westock-data-clawhub` CLI for `00700`, `01733`, and `01069`. Historical OHLCV matched; for a no-trade day on `01069`, the source correctly kept the last actual trading date instead of fabricating an O/H/L zero candle.
- `kbar_matrix.html` lookup order is now static Futu shard -> 15-minute browser cache -> `/api/kbar/<code>` -> honest TradingView external-link error. Cloudflare edge caching is five minutes, so intraday daily candles do not stay stale all day.
- On-demand entries provide daily/quarter/half-year normal and inverted charts plus the existing signal rail and key levels. They do not pretend to provide 1H-based Playbook classifications; those still require a real static Futu shard.
- `ccass/scripts/_deploy_cf.py` now includes the `functions/` directory and `.js` files in its curated Pages package. Package verification confirmed `functions/api/kbar/[code].js` is included.
- Local Wrangler runtime probes passed for success (`1069`, 260 bars), invalid code (400), and missing symbol (404). Canonical production API and API/data desktop/mobile Playwright tests passed `4/4`; mobile width stayed `393/393` with one SVG and zero iframe.
- Deployment remains direct Wrangler to Cloudflare Pages only. No GitHub/`gh`/Actions route is involved.
## 2026-07-13 Data Honesty Audit

- CCASS aggregate completeness uses validated rows with observed `total_shares > 0`. Official `total_pct` can legitimately be absent and must remain `null`; its availability is reported separately and must never stand in for stock/date coverage.
- Current publish coverage uses the active publish-scope universe. Historical coverage uses the median of the nearest three complete dates before and after each date, so later IPOs and a run of partial dates cannot distort the baseline.
- Historical/backfill runs are DB-only. They must never overwrite root/data publish aliases. Historical publish is blocked unless `HOLDINGS_ALLOW_HISTORICAL_PUBLISH=1` is explicitly set.
- `rights_analysis.json`: missing amount, issue price, dilution, and announcement market price are `null`, never numeric zero.
- `fundflow.json`: westock does not provide short-sale fields. `short_*` values are `null`, `top_short` is empty, and the page says the source did not provide the field.
- TimesFM output is labeled `data_kind=model_forecast`, `is_observed=false`. Confluence/tradeable scores are labeled derived rule outputs; UI wording must not present them as observed facts or direct buy instructions.
- Sector rotation accepts only same-date, non-stale closes and ignores snapshots with fewer than 500 fresh rows. The honest latest rotation snapshot is 2026-07-10, not the stale wrapper date 2026-07-12.
- `data/placements_enriched.json` is an internal intermediate and is not deployed. Public JSON must remain strict JSON with no `NaN`, `Infinity`, or `undefined` literals.
- Direct Cloudflare deploy only; do not use GitHub/gh.
- Dopamine/Futu failures must never invent a neutral `50` score. Preserve the last observed snapshot with `stale=true`, or publish `score=null`, `level=unavailable`, `data_kind=unavailable`, and `is_observed=false` when no observation exists. Fresh Futu dopamine is labeled `observed_provider_snapshot`.
- Missing CCASS participant/concentration inputs must stay `null`: shard merge no longer defaults `num_participants` to zero, and an empty holdings list cannot generate fake `top5_pct=0` or `top10_pct=0`.

### 2026-07-13 full-universe Kbar lookup and Vibe-Trading

- `scripts/build_hk_symbol_index.py` exports every active canonical `stock_universe` row to `data/hk_symbols.json`. Current observed index is 2,823 HK codes; daily refresh/rebuild must regenerate it, and the Cloudflare deploy allowlist must include it.
- `kbar_matrix.html` accepts any 1-5 digit HK code, HKEX form, `.HK` form, or an exact unique Chinese stock name. Uncached symbols load real daily OHLCV on demand from `/api/kbar/<code>`; no all-market Kbar download is required.
- The resolver must map a Chinese name back to an already loaded code entry. Otherwise a second lookup of the same stock can incorrectly fall back to TradingView even though the real Kbar is already in browser cache.
- Production verification: canonical `data/hk_symbols.json` reports 2,823 rows; `08131` and exact name `諾亞智能` both render the same local SVG from 260 observed Tencent daily bars. Focused Kbar/API/UI tests pass `6/6`.
- Installed official `HKUDS/Vibe-Trading` main release `0.1.11` in isolated `.tools/vibe-trading/.venv`. Its upstream dependency set contains yfinance and its generic HK auto-route defaults to Yahoo, so that route is forbidden for CCASS integration.
- `scripts/vibe_ccass_bridge.py` is the approved Vibe HK data path: it accepts only this project's Cloudflare Kbar API payload with exact source `Tencent public HK daily K-line (unadjusted)`, validates OHLC/date uniqueness, writes an isolated CSV/config, and verifies through Vibe's official `local` loader. `scripts/vibe_ccass.ps1` is the launcher; it uses an isolated Vibe home and never reads the CCASS `.env` or enables a live trading connector.
- Verified bridge example: `01733` produced and reloaded 260 observed bars from 2025-06-20 through 2026-07-13 with `uses_yfinance=false`.
- Data-honesty follow-up: the small-cap desk must not call `Number(null)` for price. That coerced missing prices to zero, then falsely classified every triggered stock as a zero-turnover risk and emptied the priority list. Missing price/turnover now stays unknown. A genuine zero-row VQC/turn list renders an honest empty state; tests must not require a fabricated candidate.
- Latest direct Cloudflare deployment for this change: `https://f0059d87.hk-alert-cloud-gas.pages.dev`. Canonical domain is `https://hk-alert-cloud-gas.pages.dev`; no GitHub deployment was used.
- Final verification against the deployed build: all official tests under `tests/` pass `17/17`. Running bare repo-wide `pytest` still collects retired `scripts/full_test.py`, which intentionally raises `SystemExit`; use `pytest tests` until that legacy collector path is removed.

### 2026-07-13 inverted Kbar geometry fix

- Inverted price charts must invert only the price-to-screen Y mapping. Candle direction/color still follows observed `close >= open`; body and wick geometry must use screen-coordinate `min/max/abs`, never assume a higher price always has a smaller Y coordinate.
- The old renderer inverted `priceY()` but calculated `bodyBottom - bodyTop` using the normal-axis assumption. This made nearly every inverted candle collapse to the 1.5px minimum. The same signed-height bug affected the POC value zone and right-side volume profile.
- `kbar_matrix.html` now normalizes candle bodies, POC bands, volume-profile bins, and reclaim-marker placement for both axis directions. Normal and inverted views preserve identical candle/profile/POC heights and differ only in vertical orientation.
- Mobile visual audit for `1733` inverted quarter chart found 66 candles and 46 non-doji bodies with real height. Focused deployed Kbar/API tests pass `6/6` at `https://08eb0ad6.hk-alert-cloud-gas.pages.dev`; canonical remains `https://hk-alert-cloud-gas.pages.dev`.

### 2026-07-13 deeper daily Kbar history

- Tencent's observed HK endpoint was probed with 520/780/1,000/1,500 daily bars and returned each requested depth for an established listing. The UI target is deliberately 520 bars: about two trading years and the largest count that remains distinguishable in the current 1,180-unit SVG without candle overlap.
- Quarter and half-year views remain 66 and 126 bars. Normal and inverted daily views now request and render up to 520 bars; their pane metadata reports the actual candle count.
- Existing 260-bar static/Futu entries are supplemented on demand and merged with the deeper daily series. The merge must preserve static `1h`, CCASS, aliases, and metadata; it must not replace the whole entry with the daily-only API payload.
- The Kbar Function caps requests at 520 and retries transient empty/network responses before falling back to a real 260-bar request. `series_meta.1d.requested_count` records intent, while `count` records actual observed bars; newly listed stocks are never padded.
- Vibe's approved local bridge default is also 520. Verified `01733` with 520 observed bars from 2024-05-29 through 2026-07-13 and 520 rows reloaded through Vibe local loader without yfinance.
- On 520-bar charts, all timing lines and hover titles remain. Ordinary jieqi text labels are suppressed to prevent mobile overlap; VQC and multi-signal resonance labels remain visible. Stable mobile screenshot confirmed 520 bodies with valid first/last coordinates.
- Latest direct Cloudflare deployment: `https://6d983c16.hk-alert-cloud-gas.pages.dev`; canonical remains `https://hk-alert-cloud-gas.pages.dev`.

### 2026-07-14 year Kbar views restored

- `kbar_matrix.html` has eight ordered tabs: quarter, inverted quarter, half-year, inverted half-year, year, inverted year, daily, inverted daily.
- Year and inverted-year views use exactly 260 observed daily bars. Quarter remains 66, half-year 126, and daily/deep-history remains up to 520; no resampling or synthetic candles are used.
- Signal-rail date range for year views is 380 calendar days, while the 520-bar daily view keeps the two-year range.
- Deployed Kbar/API test suite passes `6/6`; mobile visual audit confirmed the year tab is active with 260 candle bodies. Direct Cloudflare deployment: `https://694e64a5.hk-alert-cloud-gas.pages.dev`; canonical remains `https://hk-alert-cloud-gas.pages.dev`.

### 2026-07-14 runtime trading-skill integration

- Installed trading skills are agent instructions, not automatic website features. The runtime integration point is now `scripts/build_trade_engine.py` and its single public output `data/trade_engine.json`; do not create duplicate per-skill signal JSON files.
- The engine is two-stage. Stage 1 screens the full observed HK CCASS/price universe using CCASS changes, concentration streaks, liquidity, 52-week position, relative volume, fund flow, technical signals, and supply-event risk. It selects a balanced 240-stock pool: 101 small, 79 mid, and 60 large caps from the current 2,722 usable names.
- Stage 2 downloads only the selected stocks' real Tencent unadjusted daily OHLCV with six-worker bounded concurrency and stores a local ignored cache in `raw/trading_skill_kbars/`. Invalid OHLC, duplicate dates, missing history, and fewer than 50 observed bars are rejected; bars are never padded or synthesized.
- Daily technical analysis now classifies every successful candidate as one of breakout, base, breaklow reclaim, or weak rebound. It calculates EMA20/50/200 regime, high20/high55, relative volume, 5/20/60-day momentum, and derived entry/invalidation/target levels. Output is explicitly `data_kind=derived_rule_output`, `is_observed=false`; source bars remain marked observed.
- Unadjusted corporate-action/extreme-move returns are retained as real observations but their ranking contribution is capped. `extremeMove=true` identifies 50%+ lookback moves so a split, resumption, or genuine spike cannot produce an unbounded ranking score.
- `momentum_list.html` now ranks the expanded engine universe and its four setup boards no longer require a stock to exist in the old 41-symbol static Kbar cache. `kbar_matrix.html` setup scout also works from engine metadata; clicking a candidate loads the real on-demand chart.
- `index.html` loads the same engine and shows one compact derived setup badge in desktop rows, mobile cards, and stock detail. Hover text includes source date and derived entry/invalidation/target. The summary reports analyzed/candidate/universe scope.
- `build_publish_bundle.py` and `health_check.py` expose engine source date, runtime version, universe/candidate/analyzed counts, errors, and data kind. Hermes receives one batched engine status in the existing health summary; no per-stock Telegram flood.
- Current verified build: universe 2,722; candidates 240; analyzed 240; errors 0; momentum rows 246 including six retained non-HK presets. Source daily Kbar date is 2026-07-13.

### 2026-07-15 local unattended automation

- The production refresh/deploy route is Windows Task Scheduler -> repo-local pipeline -> direct Wrangler Cloudflare Pages. It never uses GitHub, `gh`, GitHub Actions, or GitHub Pages.
- `scripts/run_daily_automation.ps1` is the canonical unattended runner. It uses a named mutex to prevent overlapping DB jobs, imports the ignored repo `.env`, verifies Futu and Longbridge, runs `ccass/scripts/daily_refresh.sh`, accepts only publish bundle `PASS` or honest `WARN`, blocks deploy on any health `FAIL`, generates the batched Hermes health summary, retries direct Cloudflare deploy three times, and verifies the canonical live bundle timestamp.
- `ccass/scripts/daily_refresh.sh` honors `AUTO_STAGE_REFRESHED_FILES=0`; unattended runs must not alter the git index. Manual runs keep the existing staging default.
- Scheduled task `HKAlert-DailyRefresh` runs daily at 18:30 HKT. Its 22:00 trigger is a retry only: a same-day success state makes it exit immediately. The task uses `IgnoreNew`, a five-hour limit, network gating, start-when-available, and wake-to-run.
- `scripts/ensure_futu_opend.ps1` and scheduled task `HKAlert-FutuOpenD` probe a real SDK market snapshot and only start OpenD when the quote backend is unavailable. Triggers are user logon plus 08:30, 12:30, and 17:45 HKT; wake-to-run is enabled.
- Futu account `2198756` is active. On 2026-07-15 a full stop/start succeeded with `qot_logined=true`, `trd_logined=true`, and a real `HK.00700` snapshot. The login password was migrated out of `futu-opend.toml` into Windows Credential Manager; never put it back into a repo file or print it.
- Longbridge fallback was live-verified with `NVDA.US`; Wrangler OAuth was live-verified for the Cloudflare account. End-to-end runner smoke deployment succeeded at `https://d8826b25.hk-alert-cloud-gas.pages.dev`, and the canonical domain returned the exact expected publish bundle timestamp.
- Both scheduled tasks use the current Administrator interactive profile because Longbridge, Wrangler OAuth, and Futu Credential Manager credentials are profile-scoped. The PC may be unattended and may sleep, but the user session must remain signed in; changing to a logged-out service account requires separate non-interactive credentials.
- Automation logs live under ignored `logs/automation/`. Do not create a second daily refresh scheduler or parallel DB writer.
- The Windows runner sets `SENTRY_CRON_DISABLED=1` for the nested Bash pipeline because Windows Python cannot `CreateProcess` a `.sh` path. The outer runner transcript, task result, health gate, and deploy verification remain authoritative; invoking `daily_refresh.sh` directly from Git Bash may still use the Sentry wrapper.
- Before a full-universe Longbridge CCASS run, `ccass/scripts/latest_longbridge_ccass_date.py` probes one liquid HK stock and returns the provider's actual `updated_at` date. `daily_refresh.sh` passes that date as `--query-date`; if the probe fails or returns an invalid date, the pipeline fails closed instead of making thousands of guaranteed date-mismatch calls. At 2026-07-15 01:31 HKT, Longbridge's real latest CCASS date was 2026-07-13, not 2026-07-14.
- VQC, distribution-day, and jieqi legacy backtests use an unauthenticated TradingView client and may be refused upstream. Daily automation defaults `TIMING_BACKTEST_REFRESH_ENABLED=0`, preserving the last observed cache while still regenerating the text pages; an explicit opt-in is capped by `TIMING_BACKTEST_TIMEOUT_SECONDS` and is best-effort. It must not block fresher CCASS, prices, announcements, rights, signals, or Cloudflare deploy, and failed fetches must never be replaced with synthetic data.

### 2026-07-15 current-health and price-date repair

- Futu `daily_lp_futu.py` previously refreshed numeric fields without updating `lp_time` or `price_updated_at`, leaving `data/stock_prices.json` apparently stuck at 2026-07-10. It now records Futu's own `update_time` with `+08:00` and source `futu:opend`; it never substitutes the process clock for provider observation time.
- Price snapshots under `raw/prices_YYYYMMDD.json` are named for the dominant real provider session, not the process date. This matters after midnight: the 2026-07-15 run correctly wrote the 2026-07-14 session and sector rotation advanced from 2026-07-10 to 2026-07-14.
- Health freshness before the HK close expects the previous completed weekday. At 02:00 on 2026-07-15, a 2026-07-14 Futu close is current, not stale. Announcement-volume checks before 08:00 are neutral because the day's feed has not opened yet.
- Current publish health and historical maintenance are separate. Current `publish_status=PASS` requires present-date audit/data/dashboard checks to pass; historical DB gaps and low-coverage dates remain disclosed as `maintenance_status=WARN` and are never erased or relabeled as current failures.
- A trusted 99.2% current CCASS snapshot is operationally healthy at the documented 98% publish threshold even though exact `is_complete` remains honestly `false`.
- A successful refresh before 17:30 does not suppress the same day's 18:30 post-close task. Only a post-close success skips the 22:00 retry.
- Verified canonical production after direct Cloudflare deploy: health `PASS`; CCASS 2026-07-13 at 99.2%; market/prices/rights/fundflow/trade engine/sector rotation through 2026-07-14; signals generated 2026-07-15. Historical maintenance remains `WARN` for the recorded backlog.

### 2026-07-15 historical CCASS maintenance

- `scripts/repo_audit.py` and `ccass/scripts/audit_gate.py` now report aggregate stock coverage, official `total_pct` availability, and participant-detail coverage independently. Historical verifier observations remain visible but no longer masquerade as missing-date maintenance failures.
- Never import apparent full historical rows from `C:\Users\Administrator\Desktop\automatic\ccass-debug\ccass\ccass.db` for 2026-06-19 through 2026-07-02. Cross-checking showed identical per-stock holdings repeated across requested dates and written on 2026-07-07; they came from the old Longbridge date mismatch and are not valid history.
- Before repair writes, `ccass/backups/holdings.db.bak.before-gap-repair-20260715_110440` passed SQLite `integrity_check=ok`.
- Official serial HKEX repair raised 2026-05-29 to 2725/2742 (99.4%) and 2026-05-06 to 2700/2725 (99.1%) against date-eligible candidate sets. No-record responses stayed missing and official null percentages stayed null.
- `ccass/scripts/hkex_gap_backfill.py --auto` selects the newest genuine aggregate gap first, then participant-detail gaps. It derives target codes from nearby complete dates, reuses one HKEX session, stays single-threaded, and resumes after a bounded request budget.
- Scheduled task `HKAlert-CCASSMaintenance` runs at 00:15, 06:15, and 12:15 HKT with a 1,200-request budget. It shares `Local\HKAlertDailyAutomation` with production refresh, so it exits without touching the DB if another writer is active. Remaining official backfill stays `maintenance_status=WARN` until rows really reach threshold.

### 2026-07-16 observed rotation and timing windows

- `rotation_matrix.html` is a real-data RRG-style rebuild, not a copy of a proprietary service. It calculates equal-weight sector median returns relative to the equal-weight observed HK market and exposes honest 20/60/120-day profiles. The 120-day view must remain unavailable until sufficient observed price history exists.
- `timing_stack.html` overlays confirmed swing-cycle projections, VQC dates, solar-term dates, Hong Kong distribution days, a real 20-day price channel, EMA20/60 trend, momentum, support/resistance, and ATR risk. Projected windows indicate time only; they never invent a future price or direction, and the page fails closed to `unconfirmed/no entry` without a real price-and-volume breakout.
- Sector membership reuses the main dashboard map and all Kbar fetches use the existing live API/static observed-cache chain. Do not add duplicate sector universes or synthetic candles.
- Direct Wrangler deployment succeeded at `https://a8072e51.hk-alert-cloud-gas.pages.dev`; canonical production is `https://hk-alert-cloud-gas.pages.dev`. Production mobile smoke verified `timing_stack?symbol=1733` and 20/60/120-day rotation switching with no JavaScript errors or document overflow.

### 2026-07-16 cross-market turning-time radar

- `timing_stack.html` now compares five real tradable proxies: `2800.HK` for Hong Kong, `SPY.US` for the US, `ASHR.US` for China, `EWJ.US` for Japan, and `GLD.US` for gold. Always label them as proxies, not the underlying indices.
- The fixed seasonal mapping starts at winter solstice and assigns every two solar terms to one of the twelve waxing/waning hexagram states (`復` through `坤`). This is a deterministic calendar-regime label only; never infer bullish/bearish direction from a hexagram name.
- Direction fails closed. A time window can come from a solar term, confirmed swing cadence, VQC, or distribution day, but `upturn confirmed` / `downturn confirmed` requires a real 20-day price-channel break with volume ratio at least 1.2. Outside a window or without a break, show waiting/unconfirmed.
- Hong Kong stock views read observed CCASS 5-day and 20-day changes from `holdings.json`; non-HK proxies explicitly show not applicable. Solar-term reversal rate is an exploratory event study against an all-day baseline and must display sample size and lack of out-of-sample guarantee.
- `scripts/build_kbar_cache.py` keeps the dynamic stock cache at 260 daily bars while targeting 1,600 bars only for the small preset/core proxy set. A provider timeout preserves previous real bars and must never trigger padding or synthetic history.
- Direct Wrangler deployment completed at `https://197c624f.hk-alert-cloud-gas.pages.dev`. Canonical production mobile smoke loaded all five proxies and `1733` through the live API with 520 bars through 2026-07-16, 50 usable solar-term observations, no JavaScript errors, and no document overflow.
