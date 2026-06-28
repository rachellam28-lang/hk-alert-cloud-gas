# Agent Entry

Read `CODEX_MEMORY.md` first. It is the single project memory, runbook, and system map.

Do not recreate `CLAUDE.md`, `SYSTEM_MAP.md`, `Daily/` notes, or extra task Markdown unless the user explicitly asks. The project intentionally keeps Markdown to one active memory file plus this tiny entrypoint.

Hard rules:

- Work only inside `C:\Users\Administrator\Desktop\automatic\hk-alert-cloud-gas` unless the user explicitly changes scope.
- Main branch pushes deploy to Cloudflare Pages.
- Do not send bulk Telegram alerts; batch and summarize.
- Do not destructively modify production SQLite data. Backup before migrations.
- Do not run direct parallel HKEX scraping or direct parallel DB writes.
- Do not commit secrets.
- Prefer source-of-truth fixes over page-only patches.
