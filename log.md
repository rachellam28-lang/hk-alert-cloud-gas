# 2026-06-16

## Backfill / CCASS
- 已重新開 `2026-06-12` full backfill。
- 新路線已經 work，唔再依賴 Longbridge。
- 目前 `direct_backfill.py 2026-06-12`、`fill_missing.py 2026-06-12`、`scrape_one.py` 都仲 active。
- 最新進度：
  - `ccass_daily`: `8` rows for `2026-06-12`
  - `ccass_holdings`: `2359` rows for `2026-06-12`
  - `latest date`: `2026-06-12`

## Fixes
- `build_events_v2.py` 已恢復成兼容版，`ccass-events` workflow 可以正常 build。
- Longbridge holdings backfill wrappers 已退役，改走 `fill_missing.py` / HKEX scraper。
- `requests`、`beautifulsoup4`、`lxml` 已補返入 system Python，避免 `scrape_one.py` 再因缺依賴而空跑。

## Current status
- backfill 正在進行中
- 暫時仲未 fill 完
- 但 `2026-06-12` 已經開始落庫，證明新路線有效
