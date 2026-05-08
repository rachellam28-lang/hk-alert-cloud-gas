# HK Alert Cloud GAS 版

這版不需要你的電腦長開。GitHub Actions 會在雲端定時跑 scanner，Google Apps Script 會做 webhook + dashboard。

## 已建立的 Google Sheet

Spreadsheet ID:

`129IieKTIfssX18O_PfnRoxbx3c12UoCPQ_MxxBizgeA`

Alerts sheet 會儲存所有 alert。

## 自動排程

GitHub Actions 用 UTC cron，等同以下香港時間：

- 星期一至五 09:30、12:30、16:30、20:00：披露易供股 / 配股 / 股東增持
- 星期一至五 16:45：IPO 首日高突破
- 星期一至五 17:05、17:30、17:55、18:20：半年 / 12 個月 / 3 年 POC 突破（分 4 批自動跑完全市場）

## POC 分批自動掃描

POC 全市場（約 2700 隻）+ 3 個窗口（半年／1 年／3 年）+ 圖片產生會超過單個 GitHub Actions job 的時間。所以 POC 已經自動分成 4 個 shard：每個 shard 只掃 1/4 的股票，在收市後分時段排程。一日跑完所有股票，毋須人手介入。

如果手動 Run workflow 揀 `poc` 而唔填 `shard_index`，會用 matrix job 同時跑齊 4 個 shard（會發出 4 條開始／完成 Telegram 通知）。要試單一 shard 就填 `shard_index`（例如 `0`）。

## GitHub Secrets

需要以下 secrets：

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GAS_SECRET`
- `GAS_WEBHOOK_URL`

`GAS_WEBHOOK_URL` 要等你部署 Apps Script Web App 後先有。

## 手動測試

GitHub repo → Actions → HK Alert Cloud Scanner → Run workflow。

可選：

- `corp`
- `ipo`
- `poc`
- `all`

## 真實數據原則

這版不使用 demo alert、假數或假圖。外部數據取不到時，只會略過或在 dashboard 顯示 stale / 無資料。
