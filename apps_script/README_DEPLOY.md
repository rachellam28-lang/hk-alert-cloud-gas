# Google Apps Script 部署

一個 Google 帳戶只需要做一次。如果之前已部署，**請按更新步驟覆蓋舊版 Code.gs 然後重新部署**。

## 首次部署

1. 打開 [Google Apps Script](https://script.google.com/)
2. New project
3. 將 `Code.gs` 的全部內容貼入（覆蓋預設 `Code.gs`）
4. 設定 Script Property（**唔再 hardcode 落程式碼**）：
   - 左側齒輪 ⚙ Project Settings → Script Properties → Add script property
   - Property name：`GAS_SECRET`
   - Value：填入你 GitHub repo `GAS_SECRET` secret 同一個值
   - Save
5. Deploy → New deployment
6. Type 選 `Web app`
7. Execute as: `Me`
8. Who has access: `Anyone`
9. Deploy
10. 複製 Web app URL
11. 去 GitHub repo → Settings → Secrets and variables → Actions → Secrets
12. 新增或更新 `GAS_WEBHOOK_URL`，貼上 Web app URL

## 更新已部署版本（今次必做）

1. 打開原本嘅 Apps Script project
2. 將新版 `Code.gs` 全部內容覆蓋貼入
3. 確認 Script Properties 已經有 `GAS_SECRET`（如冇就照上面第 4 步加返）
4. Deploy → Manage deployments → 揀返現有嗰個 deployment → ✏ 鉛筆 icon → Version 揀 `New version` → Deploy
5. Web app URL 通常維持不變，毋須再改 GitHub secret
6. 喺瀏覽器打開 Web app URL 確認顯示新版 dashboard（深色 navbar、KPI cards、分類 tabs、按股票 grouped 嘅 table）

## Dashboard 功能

- 頂部 KPI cards：HSI、HSI PE、DXY、VIX，全部用 Yahoo Finance 即時資料（HSI PE 用 worldperatio.com）
- 分類 tabs：全部 / POC突破 / IPO突破 / 披露易公告，旁邊顯示對應數量
- 搜尋框：按代號或名稱即時 filter
- Table 按股票 code grouping，每行顯示分類數量 pill chips、最近訊號 chips、最近時間、TradingView 連結
- 每 120 秒自動 refresh，所有資料來自 `Alerts` sheet（由 GitHub Actions scanner 寫入），絕無 demo / fake data

## Telegram 設定（不用改 Apps Script）

Scanner 會直接用 GitHub Actions secrets `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID`，每個 alert 會發出單一 Telegram 訊息：有 chart image + caption（HTML），如果 chart 生成失敗則自動 fall back 為單一文字訊息。
