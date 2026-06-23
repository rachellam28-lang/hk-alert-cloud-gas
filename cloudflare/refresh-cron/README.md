# CCASS refresh cron

Cloudflare Cron Trigger 會定時叫 GitHub Actions `ccass_refresh.yml`，由 GitHub runner 跑現有 `ccass/scripts/daily_refresh.sh`。

## 需要設定

1. 先用 Wrangler 登入 Cloudflare
2. 設 `GITHUB_TOKEN` secret
   - 權限要可以觸發 workflow dispatch
3. Deploy Worker
4. Cloudflare Cron Trigger 會按 `wrangler.toml` 的 `30 23 * * 0-4` 執行
   - 即 HKT 07:30，Mon-Fri

## 本地測試

可以用 Wrangler 的 scheduled test route 驗證 handler。
