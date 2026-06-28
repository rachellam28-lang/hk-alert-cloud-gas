# Codex Persistent Memory

Last updated: 2026-06-29

## Always load first

1. `CODEX_MEMORY.md`
2. `AGENTS.md`
3. `SYSTEM_MAP.md`
4. Latest file in `Daily/`

If these disagree with chat history, prefer the file state and current repo state.

## Operating rules

- Telegram, dashboard, and notes must use the same source of truth.
- If cache / fallback / legacy duplicate exists, pick one primary source and label any fallback.
- Do not use any legacy noncanonical quote Python provider or portal fallback in this project. Use Futu, Longbridge, TradingView/tvdatafeed, or existing local JSON snapshots.
- Root publish JSON and `data/*.json` aliases must be synchronized before bundle/page generation:
  `holdings.json -> data/holdings.json`, `ccass.json -> data/ccass.json`, `market.json -> data/market.json`.
- Static generated pages must be regenerated after `data/publish_bundle.json` / backtest JSON changes:
  `daily_trade_prompt.html`, `timing_analysis.html`, `vqc_analysis.html`, `distribution_day.html`, `jieqi_analysis.html`, `rights_analysis.html`.
- Prefer structural fixes over band-aids.
- Keep small-cap data priority high.
- Keep explanations short; act first, explain after.
- The repo now has a canonical system map in `SYSTEM_MAP.md`; read it when orienting to the project.

## Current project facts

- Main holdings source of truth: `holdings.db` / `ccass/holdings.db`.
- Daily refresh pipeline:
  - `ccass/src/runner.py`
  - `ccass/scripts/daily_lp_futu.py`
  - `ccass/scripts/generate_prices_json.py`
  - `ccass/scripts/generate_signals_json.py`
  - `ccass/scripts/regenerate_json.py`
- Daily refresh is now bounded by `HOLDINGS_DAILY_MAX_MINUTES` and should stop instead of lingering on slow tail stocks.
- Separate resume job:
  - `ccass/scripts/resume_incomplete_dates.py`
  - `ccass/scripts/resume_backfill_range.py`
  - Keep the daily job quick; let resume mop up missing coverage later.
- Daily refresh now runs `scripts/sync_publish_aliases.py` before `build_publish_bundle.py`, and `audit_gate.py` fails if root/data aliases diverge.
- Cloudflare cron dispatches `.github/workflows/ccass_refresh.yml`, which runs `ccass/scripts/daily_refresh.sh`.
- Longbridge is for holdings backfill, not full-site refresh.
- Standalone US dashboard page was removed; keep only `美股P/E` and `美股 breadth` on main pages.
- Main pages currently restored:
  - `index.html`
  - `signals.html`
  - Both show `美股P/E` and `美股 breadth`
- A Cloudflare Cron Trigger path is being added to trigger the GitHub refresh workflows.
- Cloudflare cron should split into bounded daily refresh + separate resume/backfill dispatch, not one endless job.
- GitHub workflow push may fail if PAT lacks `workflow` scope.
- `data/publish_bundle.json` is the shared publish metadata layer for Telegram / dashboard / Daily / health check.

## Cloudflare / GitHub

- Main site deploys from GitHub `main` to Cloudflare Pages.
- Cloudflare schedule should trigger GitHub `workflow_dispatch` for refresh/resume depending on cron slot.
- If GitHub workflow push fails, check PAT `workflow` scope first.
- CCASS events cron should use its own Telegram bot/chat secrets, not the Hermes bot.
- Major source-of-truth changes should be synced to Hermes via Telegram so the human-visible side stays aligned.

## User preferences

- User wants `update`口徑 to match Telegram.
- User wants markdown summaries written into `Daily/`.
- User wants direct fixes, not just analysis.
- User wants the system to stay HK-only in the UI, except for `美股P/E` and `美股 breadth`.
- User dislikes vague explanations; give a short conclusion, then details only if needed.
- User wants CCASS cron alerts separated from Hermes because Hermes gets too many messages.
- User wants major workflow / source-of-truth changes mirrored to Hermes via Telegram updates.

## Keep updated

- After any major pipeline or UI change, update this file.
- Add new root causes, file paths, or workflow decisions here.

## Latest open items

- Keep `Telegram / dashboard / notes` fully aligned on freshness and source.
- Continue auditing pages for shared data consistency after any change.
- If local `ccass/holdings.db` is 0 bytes, audit gate should report structured FAIL instead of traceback; use GitHub refresh or restore DB before full DB verification.
