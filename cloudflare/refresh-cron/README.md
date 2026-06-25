# CCASS refresh cron

Cloudflare Cron Trigger 會定時叫 GitHub Actions workflow。

目前分兩條線：

1. `ccass_refresh.yml`
   - bounded daily refresh
   - 跑 `ccass/scripts/daily_refresh.sh`
2. `ccass_resume.yml`
   - separate resume job
   - 跑 `ccass/scripts/resume_incomplete_dates.py`

## 需要設定

1. 先用 Wrangler 登入 Cloudflare
2. 設 `GITHUB_TOKEN` secret
   - 權限要可以觸發 workflow dispatch
3. Deploy Worker
4. Cloudflare Cron Trigger 會按 `wrangler.toml` 的兩個 cron 執行
   - `30 23 * * 0-4` → HKT 07:30 daily refresh
   - `0 7 * * 1-5` → HKT 15:00 resume job

## 本地測試

可以用 Wrangler 的 scheduled test route 驗證 handler。
