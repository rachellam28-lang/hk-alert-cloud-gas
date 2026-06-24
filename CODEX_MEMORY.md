# Codex Persistent Memory

Last updated: 2026-06-24

## Always load first

1. `CODEX_MEMORY.md`
2. `AGENTS.md`
3. `SYSTEM_MAP.md`
4. Latest file in `Daily/`

If these disagree with chat history, prefer the file state and current repo state.

## Operating rules

- Telegram, dashboard, and notes must use the same source of truth.
- If cache / fallback / legacy duplicate exists, pick one primary source and label any fallback.
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
- Longbridge is for holdings backfill, not full-site refresh.
- Standalone US dashboard page was removed; keep only `美股P/E` and `美股 breadth` on main pages.
- Main pages currently restored:
  - `index.html`
  - `signals.html`
  - Both show `美股P/E` and `美股 breadth`
- A Cloudflare Cron Trigger path is being added to trigger the GitHub refresh workflow.
- GitHub workflow push may fail if PAT lacks `workflow` scope.
- `data/publish_bundle.json` is the shared publish metadata layer for Telegram / dashboard / Daily / health check.

## Cloudflare / GitHub

- Main site deploys from GitHub `main` to Cloudflare Pages.
- Cloudflare schedule should trigger GitHub `workflow_dispatch` for refresh.
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

- Finish Cloudflare Cron → GitHub refresh workflow push by adding GitHub `workflow` scope.
- Keep `Telegram / dashboard / notes` fully aligned on freshness and source.
- Continue auditing pages for shared data consistency after any change.
