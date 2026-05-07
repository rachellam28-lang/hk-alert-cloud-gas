# Google Apps Script 部署

一個 Google 帳戶只需要做一次。

1. 打開 [Google Apps Script](https://script.google.com/)
2. New project
3. 將 `Code.gs` 的全部內容貼入
4. 將 `GAS_SECRET` 改成 GitHub repo secret 入面的同一個值
5. Deploy → New deployment
6. Type 選 `Web app`
7. Execute as: `Me`
8. Who has access: `Anyone`
9. Deploy
10. 複製 Web app URL
11. 去 GitHub repo → Settings → Secrets and variables → Actions → Secrets
12. 新增或更新 `GAS_WEBHOOK_URL`，貼上 Web app URL

完成後，GitHub Actions 跑 scanner 時會 POST alert 入 Google Sheet，dashboard URL 就係你部署出來的 Apps Script Web App URL。
