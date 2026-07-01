# HK Alert Cloud GAS Memory

Last updated: 2026-07-01 HKT

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
- Current deploy preference: direct Cloudflare Pages deploy with Wrangler.
- Main branch push deployment exists historically, but do not route through GitHub unless the user asks.

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
  -> GitHub main
  -> Cloudflare Pages
```

Primary layers:

- Raw sources: `ccass/holdings.db`, `holdings.db`, HKEX disclosures, Futu/Longbridge cache, local JSON snapshots.
- Compute: `ccass/src/runner.py`, `ccass/scripts/*.py`, `scripts/*.py`.
- Publish: `holdings.json`, `ccass.json`, `market.json`, `data/*.json`, `data/publish_bundle.json`.
- Pages: `index.html`, `signals.html`, `rights_analysis.html`, `timing_analysis.html`, `jieqi_analysis.html`, `distribution_day.html`, `daily_trade_prompt.html`, and related static pages.
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

## Current Refresh Pipeline

Main workflow:

- Shell orchestrator: `ccass/scripts/daily_refresh.sh`
- Direct deploy helper: `ccass/scripts/_deploy_cf.py`
- GitHub Actions schedules are disabled; do not route refresh/deploy through GitHub unless the user explicitly asks.
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
- GitHub Actions workflow files may remain for manual fallback, but schedules should stay disabled.
- Cloudflare cron Worker should stay no-op unless a non-GitHub refresh path is implemented.
- Telegram Hermes bot is for general dashboard/status/health summaries. CCASS events cron should use its own Telegram bot/chat secrets, not the Hermes bot, unless the user explicitly asks to merge them.
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

### 2026-06-30 main heatmap card, sector overrides, and fund-flow heatmap

- Main-page heatmaps remain in their own `section.card heatmap-card`, separate from table controls, with three panels: theme, sector, and fund flow.
- The heatmap card now has a compact header with fund-flow publish date/count metadata so it does not look stuck while data is loading.
- Sector grouping still avoids another heavy JSON source. It now checks a lightweight `SECTOR_CODE_MAP` for common HK large caps before falling back to stock-name keyword rules, which reduces obvious wrong-sector placements.
- Sector grouping should not dump holding-company names into `其他/未分類`. `index.html` now has a `綜合/控股` sector for generic holding/group/development names, broader bilingual keyword rules, short English token boundary matching for `AI`/`EV`, and extra exact code overrides for obvious HK names. Local audit improved sector heatmap `other` from 1768 to about 621 stocks.
- Main page now fetches existing `data/fundflow.json` and builds a clickable fund-flow heatmap from `main_net`, `total_net`, and `lgt_cap_chg_daily`.
- Fund-flow heatmap tiles cover main/total/southbound inflow and outflow; clicking a tile applies the flow filter, and presets/URL state persist the `flow` filter.
- Heatmap tiles must connect to stocks, not only show group stats. Each tile shows top stock-code chips that open the stock drawer directly, and clicking the tile filters then scrolls/highlights the first matching stock row/card.
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

## Open Items

- Keep auditing page data sources when new pages or JSON files are added.
- Audit SQL/SQLite pressure paths when time allows: look for unbounded loops, fan-out queries, missing indexes, parallel writes, retry storms, and refresh jobs that can hammer `ccass/holdings.db` or `holdings.db`.
- If local `ccass/holdings.db` is 0 bytes, audit gate should report structured fail instead of traceback.
- Verify Cloudflare live pages after every push that affects public files.
