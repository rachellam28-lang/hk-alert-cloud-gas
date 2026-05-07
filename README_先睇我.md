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
- 星期一至五 17:05：半年 / 12 個月 POC 突破

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
