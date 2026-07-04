# HK Alert Cloud GAS Memory

Last updated: 2026-07-04 HKT

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

### 2026-07-04 Telegram bot routing, Hermes sync, and tooling audit

- `run_corp_cron.py` and `_run_corp_cron.py` now run from this repo root, not `C:\Users\Administrator\Desktop\automatic\ccass-debug`, and read only this repo's local `.env`.
- CCASS/corporate-action Telegram sends now prefer dedicated second-bot env names: `CCASS_TELEGRAM_TOKEN` and `CCASS_TELEGRAM_CHAT_ID`. Corp cron launchers and `daily_refresh.sh` default `CCASS_TELEGRAM_REQUIRE_DEDICATED=1`, so they cannot silently use Hermes/generic Telegram credentials.
- Hermes/status paths now prefer `HERMES_TELEGRAM_TOKEN` and `HERMES_TELEGRAM_CHAT_ID`. `scripts/health_check.py --telegram` and `scripts/tg_claude_bot.py` were aligned to those names while keeping legacy generic fallback for manual use.
- Local disabled GitHub workflow references were hardened: CCASS workflows now reference `CCASS_TELEGRAM_*` and no longer keep a commit/push-capable permissions block for `ccass-events`; heartbeat references `HERMES_TELEGRAM_*`.
- Web/tooling audit recommendations:
  - Install/enable first: Sentry Cron Monitoring for `daily_refresh`, resume/backfill, and Hermes/CCASS cron no-run/failed-run detection; Playwright smoke tests for live page/heatmap click-to-table checks; DuckDB/Parquet snapshots for lighter history/audit queries.
  - Use next if the pipeline grows: Prefect for local Python orchestration and retry/state UI; Cloudflare Queues with dead-letter queues if alerts/jobs move into Workers and need retry isolation.
  - Defer unless validation rules become much bigger: Great Expectations or Dagster, because the current repo already has custom `audit_gate` and direct scripts.

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

## Open Items

- Keep auditing page data sources when new pages or JSON files are added.
- Audit SQL/SQLite pressure paths when time allows: look for unbounded loops, fan-out queries, missing indexes, parallel writes, retry storms, and refresh jobs that can hammer `ccass/holdings.db` or `holdings.db`.
- If local `ccass/holdings.db` is 0 bytes, audit gate should report structured fail instead of traceback.
- Verify Cloudflare live pages after every push that affects public files.
