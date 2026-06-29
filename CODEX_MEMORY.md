# HK Alert Cloud GAS Memory

Last updated: 2026-06-29 HKT

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
4. Generate `rights_analysis.json/html`
5. `ccass/scripts/generate_signals_json.py`
6. `ccass/scripts/regenerate_json.py`
7. `scripts/sync_publish_aliases.py`
8. `scripts/build_publish_bundle.py`
9. Generate static analysis pages
10. `scripts/audit_gate.py`
11. Commit locally and direct deploy to Cloudflare Pages

`audit_gate.py` should fail if root/data aliases diverge.

Separate resume/backfill jobs:

- `ccass/scripts/resume_incomplete_dates.py`
- `ccass/scripts/resume_backfill_range.py`

Keep the daily refresh bounded; let resume jobs mop up incomplete coverage.

## Page Data Consistency

- Main page issuer badges must use `data/signals.json.groups[].issuer`.
- `data/signals.json` should reuse the canonical issuer payload from `data/rights_analysis.json` when available.
- `rights_analysis.html` and the main signal badges must show the same issuer score/label.
- `timing_analysis.html`, `jieqi_analysis.html`, and `distribution_day.html` are signal-date tables, not first-screen backtest dashboards.
- Main page should not expose old `5d`, `20d`, or `60d` delta columns.
- Old URL/custom preset sorts using `d5`, `d20`, or `d60` should sanitize back to `vr`.
- Count bars on timing/jieqi/distribution pages use `log1p(count)` for width while displaying the real count.

## Deployment

- Current user preference is direct Wrangler deploy to Cloudflare Pages.
- Avoid GitHub/`gh` for refresh/deploy unless the user explicitly asks.
- GitHub Actions workflow files may remain for manual fallback, but schedules should stay disabled.
- Cloudflare cron Worker should stay no-op unless a non-GitHub refresh path is implemented.
- CCASS events cron should use its own Telegram bot/chat secrets, not the Hermes bot.
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
- Market quote cache is still `2026-06-26T08:08:32Z` because Futu timed out and Longbridge token is expired.
- Participant-level transfer DB is not complete for `2026-06-26`; full HKEX participant backfill was too slow and only wrote 24/2759 rows before being stopped.
- Transfer publish output now truthfully uses `ok:false`, `status:"backfill_required"`, date `2026-06-26`; pages must not show stale `2026-06-05` transfer signals.
- `ccass/scripts/audit_gate.py --min-coverage 99.0` still fails on local participant DB backfill mismatch; do not fake PASS. Deploy corrected publish JSON with the backfill status clearly labelled.

### 2026-06-29 Longbridge CLI auth and market fallback

- User supplied a one-time Longbridge auth code; redeemed it with Longbridge CLI, then installed the Codex plugin `longbridge@longbridge-skills`.
- Longbridge CLI installed at `%LOCALAPPDATA%\Programs\longbridge\longbridge.exe`, version `0.24.0`, auth status valid.
- Verification quotes succeeded for `NVDA.US` and `00700.HK`.
- `.env` exists as an ignored local template, but the CLI token is stored by Longbridge under the user profile; do not print or commit tokens.
- `ccass/scripts/daily_lp_longbridge.py` now uses the authenticated Longbridge CLI for quote fallback before trying MCP bearer token.
- `scripts/dopamine_refresh.py` now uses Longbridge CLI for HSI fallback before trying MCP bearer token; this refreshed `market.json` and `data/market.json` to `2026-06-29T15:19:01Z` with `market_partial=true`.

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
- If local `ccass/holdings.db` is 0 bytes, audit gate should report structured fail instead of traceback.
- Verify Cloudflare live pages after every push that affects public files.
