# CCASS Tracker — Hermes / Codex 常設合約

## FATAL 規則（任何情況都唔可以 override）

### FATAL-001：禁止批量發送 Telegram alert
- 每條 alert ≥ 3 秒間隔
- 單次 batch 上限：20 條 alert
- 超過 50 條 → summary only

### FATAL-002：禁止破壞 production database
- `ccass.db` 係 source of truth
- 只可以 INSERT / UPDATE / ADD COLUMN
- Migration 前必須 backup

### FATAL-003（2026-05-23 修訂）：Parallel scraping 限制

> **Direct in-process parallel scraping/writing must stay disabled (parallel_workers=1).**
> 
> **Historical backfill may use bounded stock-shard parallelism** where:
> - Shards are **separate subprocesses** writing JSON only (never direct DB writes)
> - Starts are **staggered by ≥30 seconds** between shards
> - HKEX block detection (`RuntimeError` on 7+/12 bad) **aborts the entire run**
> - SQLite writes happen in a **single merge process** after all shards complete
> - Aggregate failure rate > 10% → abort that date
> 
> This provides ~6× speedup for backfill without increasing WAF risk beyond
> what the existing daily 6-shard GitHub Actions workflow already does.

### FATAL-004：禁止 commit secrets
- `.env` 必須喺 `.gitignore`
- Telegram bot token 入 `.env`

## Backfill 流程

```
parallel_backfill.py --start 2026-05-15 --end 2026-05-21

  Per trading day (oldest → newest):
    1. Launch 6 subprocess shards (stagger 30s)
       python -m src.runner --shard N --shard-total 6 --query-date YYYY-MM-DD --out backfill-shard-YYYYMMDD-N.json
    2. Wait all 6 → validate 9 checks → merge JSON → SQLite
    3. compute_trends_for_date()
    4. Clean up temp files
    5. Resume: skip dates already in DB (--force to override)
```
