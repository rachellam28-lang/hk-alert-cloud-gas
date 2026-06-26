# CCASS refresh cron

Cloudflare Cron Trigger 會定時叫 GitHub Actions workflow。

目前預設只自動跑一條線：

1. `ccass_refresh.yml`
   - bounded daily refresh
   - 跑 `ccass/scripts/daily_refresh.sh`

`ccass_resume.yml`
- 仍然保留作手動補缺口 / backfill
- 需要時再手動觸發，不再每日自動跑

## 需要設定

1. 先用 Wrangler 登入 Cloudflare
2. 設 `GITHUB_TOKEN` secret
   - 權限要可以觸發 workflow dispatch
3. Deploy Worker
4. Cloudflare Cron Trigger 只會按 `wrangler.toml` 的 daily refresh cron 執行
   - `30 23 * * 0-4` → HKT 07:30 daily refresh

## 本地測試

可以用 Wrangler 的 scheduled test route 驗證 handler。
