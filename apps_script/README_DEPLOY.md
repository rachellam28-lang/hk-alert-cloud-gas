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
5. **新版會用 DriveApp 將 scanner 真實 chart PNG 存入「HK Alert Charts」folder，所以第一次 deploy 後 Apps Script 會 prompt 你 authorize Google Drive 權限**（Review permissions → Allow）。
   - 如果 Drive 授權失敗或被機構政策封鎖，仍然會記錄 alert，dashboard 會自動 fallback 用簡約 sparkline。
6. Web app URL 通常維持不變，毋須再改 GitHub secret。
7. 喺瀏覽器打開 Web app URL 確認顯示新版 dashboard（每個股票顯示真實 OHLC chart 縮圖，TG 同步傳同一張）。
8. Sheet schema 會自動 upgrade：新加 `poc_2y`/`poc_3y`/`chart_image_url`/`chart_drive_id` columns，舊 row 維持不變。

## Dashboard 功能

- 頂部 KPI cards：HSI、HSI PE、DXY、VIX，全部用 Yahoo Finance 即時資料（HSI PE 用 worldperatio.com）
- 分類 tabs：全部 / 技術信號 / 披露易 / 配股 / 增持 / 供股
- 搜尋框：按代號或名稱即時 filter
- Table 按股票 code grouping。**走勢圖**欄顯示同 Telegram 一模一樣嘅真實 OHLC chart 縮圖（matplotlib + yfinance），如果未有圖則 fallback 用 20 日 close sparkline
- 每 120 秒自動 refresh，所有資料來自 `Alerts` sheet（由 GitHub Actions scanner 寫入），絕無 demo / fake data

## 速度優化（手機 Chrome 開得到）

舊版 `doGet` 對每隻股票都打一次 Yahoo Finance（過百個 HTTP request 串行行），手機 Chrome 30 秒前未行完就 timeout。新版做咗以下優化，目標係手機首屏 ~10 秒以內：

- **CacheService HTML cache（90 秒）**：第一個 request 渲染好之後 cache 整頁 HTML，之後 90 秒內所有 request 即時返回，唔再讀 Sheet 唔再 fetch Yahoo。
- **Market snapshot cache（5 分鐘）**：HSI / HSI PE / DXY / VIX 用 `UrlFetchApp.fetchAll` 並行抓，再 cache 5 分鐘，唔再因 worldperatio.com 慢就拖死成個頁。
- **限制初始 row 數**：每次只取 sheet 尾 600 條 alert，group by code 後最多顯示 120 隻最新股票。Sheet 全部歷史照樣保留，只係首屏唔會 dump 出嚟。
- **走勢圖優先用 scanner 已存嘅 chart_image_url**：如果某隻股有 Drive 上嘅真實 chart 縮圖（由 `doPost` 寫入），就直接 `<img loading="lazy">` lazy load，唔會 server-side 再 fetch Yahoo。只有冇圖嘅股先 fallback Yahoo（最多 25 隻）。
- **圖片 fallback**：`<img onerror>` 處理 Drive 權限失敗 / 圖檔被刪 / 機構政策 block link sharing 等情況——會即時換成「—」placeholder，唔會塞死 layout。
- **固定 `<img width/height>` + `loading="lazy"` + `decoding="async"`**：減少 reflow 同 main-thread block。

### 部署後驗證

1. 第一次開 Web app URL（cache miss）：渲染時間視乎 sheet rows，一般 5–10 秒。
2. 第二次開（90 秒內）：cache hit，1 秒內返回。
3. 手機 Chrome 開得到 = 成功。如果仍然 timeout，去 Apps Script editor → Executions 睇邊段 timeout，通常係 Drive 權限未 authorize。

## POC 訊號

- 半年 POC（126 trading days）
- 1 年 POC（252 trading days）
- 2 年 POC（504 trading days）
- 3 年 POC（756 trading days）
- 任何向上突破都會觸發；同一隻股當日多個 POC 一齊突破會合併成一條訊息（caption 會列出所有觸發 window 同 POC 數值）

## Telegram 設定（不用改 Apps Script）

Scanner 會直接用 GitHub Actions secrets `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID`，每個 alert 會發出單一精簡 Telegram 訊息：sendPhoto（chart + 簡短 caption），chart 生成失敗就 fallback 為單一文字訊息。同一張 chart 亦會 base64 傳俾 GAS 存入 Drive，作為 dashboard 縮圖。
