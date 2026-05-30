# CCASS 使用說明書

> 港股 CCASS（中央結算系統）持倉追蹤 Dashboard  
> 最後更新：2026-05-30

---

## 🔍 呢個 Dashboard 係咩？

追蹤港股 CCASS 持倉數據 — 睇邊個大戶/券商正在收貨或散貨。

---

## 📊 數據來源

| 來源 | 說明 |
|------|------|
| **CCASS 持倉** | HKEX 每日 CCASS 持股報告（持倉%、Top5/Top10 集中度、HHI） |
| **股價** | GAS 實時報價 + yfinance 歷史數據（今日Δ%、52週高低、PE、Beta） |
| **信號** | 技術分析信號（POC、FVG、年開突破、IPO首日突破） |
| **配股/供股** | 配股價、供股價突破監測 |

---

## 🎯 點樣用嚟炒？

1. **CCASS% ↑ + 股價 ↑** → 大戶收貨中，跟勢追入
2. **CCASS% ↑ + 股價 ↓** → 大戶壓價收貨，留意見底信號
3. **CCASS% ↓ + 股價 ↑** → 大戶散貨中，高位減持
4. **Top5% > 80%** → 高度集中，莊家股，大波動
5. **連續增持（🔥）** → 大戶持續買入，強勢信號
6. **連續減持（❄️）** → 大戶持續沽出，避開
7. **🔺 年開突破** → 現價高過今年開市價，多頭趨勢
8. **52週%近0%** → 股價近52週低位，可能見底
9. **52週%近100%** → 股價近52週高位，小心高追

---

## 📌 Dashboard Columns 說明

| 欄位 | 說明 |
|------|------|
| 代碼 (c) | 股票代碼 |
| 名稱 (n) | 公司名 |
| 😻 (py) | 現價 > 2025開盤，顯示喺 code 旁邊 |
| 前年Δ% (py_pct) | (lp-py)/py×100，下細字=py開盤價，sortable |
| 量比 (vr) | 今日成交量 / 10日平均，sortable |
| 現價 (lp) | GAS優先 → yfinance fallback，sortable |
| 今年Δ%🔺 (yo_pct) | (lp-yo)/yo×100，🔺=lp>yo，sortable |
| CCASS% (tp) | CCASS 總持倉% |
| Top5% (t5) | Top5 集中度 |
| 5日Δ (d5) | 5日 CCASS% 變化，🟢增持 🔴減持 |
| 🔥/❄️ (su/sd) | 連續增持/減持日數 |
| 今日Δ% (chg) | 今日股價變幅 (yfinance)，sortable |
| 52週% (p52) | (lp-lo52)/(hi52-lo52)×100，進度條，sortable |
| PE (pe) | 市盈率，sortable |
| 市值 (mc) | 市值（億） |
| 信號 (sig) | IPO/POC/FVG/配股/供股 signal pills |

### 現價+Δ% 顯示規則

- **現價欄**: 只有現價 $lp，無 icon
- **🔺**: lp > yo（現價 > 今年開盤）→ 今年Δ% 前加 🔺
- **😻**: lp > py（現價 > 前年開盤）→ code 旁加 😻
- 所有 Δ% null-safe: yo/lp/py 任一 null → —

---

## 📊 量比警報 (Volume Ratio)

量比 = 今日成交量 / 10日平均成交量

| 量比 | 信號 | 標記 |
|------|------|------|
| vr ≥ 2 | 成交量異常放大 | 🟠 橙色 |
| vr ≥ 5 | 極端放量 | 🟢 綠色 |
| vr < 0.5 | 極度縮量 | — |

**常見解讀：**
- 量比 > 2 + 股價 ↑ → 放量上漲，強勢信號
- 量比 > 2 + 股價 ↓ → 放量下跌，小心沽壓

Dashboard: 📊 量比警報 section，vr≥2，頭8隻 + 「顯示全部」按鈕

---

## 📦 存倉轉倉監測

比較兩個交易日 CCASS 持倉，detect >10萬股 participant-level 變動。

**📥 存入（綠色）：** 券商 + 增持股數 → 大戶存入 CCASS  
**📤 提出（紅色）：** 券商 + 減持股數 → 大戶提取 CCASS

- 總量 = 📥 + 📤 總和
- 總值 = 總量 × 現價（億/萬格式）
- 佔比 = 轉倉量 / CCASS 總持股 × 100%

Dashboard: 📦 存倉轉倉監測 section（量比警報下面），頭8隻 + 「顯示全部」

---

## ⚡ 快篩 Presets

| Preset | 條件 |
|--------|------|
| **信號突破** | 按技術信號數量排序 |
| **配股預警** | CCASS% > 30 + 有配股記錄 |
| **高動能** | 5日Δ跌 5-20%（大戶低位掃貨） |

---

## 🔬 數據精準度

> 另類數據（Alternative Data）的靈魂在於數據清洗的顆粒度與精準度，及其深度關聯處理。

### 8 重驗證（verify_data.py）

| # | 檢查 | 說明 | 閾值 |
|---|------|------|------|
| 1 | Range Validation | total_pct 必須 0-100，total_shares >0 | — |
| 2 | Pct Consistency | ccass_daily.total_pct vs SUM(holdings.pct) | 誤差 ≤5% |
| 3 | Shares Consistency | ccass_daily.total_shares vs SUM(holdings.shares) | 誤差 ≤2% |
| 4 | Day-over-day Jump | 前後日 total_pct 跳變檢測 | >30% → alert |
| 5 | Coverage Gap | 每日股票數 vs median | <50% median → warning |
| 6 | Zero Participant | 有股數但 num_participants=0 | → warning |
| 7 | Orphan Row | daily 有 record 但無對應 holdings | → warning |
| 8 | Concentration Sanity | top5_pct > total_pct = 不可能 | → error |

### JSON 層驗證（verify_dashboard.py）

- NaN 檢測：raw JSON 含 "NaN" string → error
- Structure check：required keys（updated, stock_count, stocks, first_date）
- Stock count ≥ 2000
- Per-stock：required fields（c, n, tp, t5, t10, np），tp range [0,100]
- Price sanity：py_pct recalculated vs stored，誤差 >0.5% → warning
- Coverage：lp/py/py_pct 覆蓋率統計

### 數據清洗規則

| 規則 | 說明 |
|------|------|
| **幽靈數據防護** | fill_missing + runner DELETE before INSERT，防重複 scrape 疊加 |
| **NaN/Infinity Sanitize** | export JSON 前 `math.isnan(v) or math.isinf(v) → None` |
| **Scraper Bug Detection** | pct 大變但 shares 不變 → scraper error（非公司行動） |
| **Corporate Action 識別** | pct + shares 同時大變 → 公司行動（非數據錯誤） |
| **WAF Protection** | sequential only，subprocess 60s timeout，fail rate >5% → admin alert |

---

## 🔄 更新頻率

| 數據 | 頻率 |
|------|------|
| CCASS 數據 | 每日 HKEX update 後（約 7am HKT） |
| 股價 + 停牌 | 每日 9pm HKT yfinance refresh |
| 信號 | GAS 自動推送 |

---

## 🖥️ 系統架構

```
ccass-debug/
├── ccass/              核心 DB + scripts
│   ├── ccass.db         SQLite (local, 不入 git)
│   ├── scripts/         backfill / runner / fill_missing / detect_transfers / compute_metrics / regenerate_json
│   └── data/            stock_prices.json / suspended_stocks.json / transfers.json
├── index.html           GitHub Pages 主頁
├── ccass.html           Dashboard 源碼
├── data/                GitHub Pages 數據: ccass.json / transfers.json / market.json
├── signals.html         港股訊號
├── watchlist.html       ⭐自選
└── history.html         每日訊號歷史
```

---

## 📋 日常更新流程

```
1. Clear pycache + lock
   find . -name "*.pyc" -delete
   rm -f /tmp/ccass_backfill.lock

2. fill_missing.py → scrape missing stocks

3. backfill.py → sequential scrape (subprocess per stock, 60s timeout)
   ⚠️ NEVER parallel — HKEX WAF ban

4. compute_metrics.py → HHI/trends

5. regenerate_json.py → refresh ccass.json

6. detect_transfers.py → 轉倉 → transfers.json

7. cp ccass.html index.html && git push → deploy
```

**速度:** ~7 stocks/sec  
**架構:** subprocess per stock — OS SIGKILL bypasses Python GIL, never hangs

---

## 🛠️ 常用指令

```bash
# Clear cache
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} +

# Backfill
cd ccass && python -m scripts.backfill --start 2026-05-29

# Fill missing
cd ccass && python scripts/fill_missing.py 2026-05-29

# Regenerate JSON
cd ccass && python scripts/regenerate_json.py

# Detect transfers
cd ccass && python scripts/detect_transfers.py

# Compute metrics
cd ccass && python -m scripts.compute_metrics

# Deploy
cp ccass.html index.html && git add . && git commit -m "deploy" && git push
```

---

## ⚠️ 危險陷阱

| 陷阱 | 後果 | 規則 |
|------|------|------|
| Parallel scrape | HKEX WAF IP ban (6-12hr) | FATAL-003: sequential only |
| DROP/DELETE ccass.db | 數據永久丟失 | FATAL-002: backup first |
| NaN/Infinity in JSON | Dashboard 白畫面 | sanitize before export |
| yfinance 5-digit code | API error | drop leading zero |
| HTML edit with write_file | Line number leak corrupt | 只用 patch tool |
| Wide format ccass.json | Dashboard 白畫面 | Narrow format only |
| Telegram batch alert | Flood control → bot mute | FATAL-001: max 20/batch |

---

## 📄 ccass.json 格式

```json
{
  "updated": "2026-05-30T...",
  "first_date": "2026-04-30",
  "total_stocks": 2776,
  "stocks": [{
    "c": "00005", "n": "滙豐控股",
    "tp": 66.7, "t5": 76.5, "t10": 86.0,
    "d5": 0.5, "d20": 1.2, "d60": -0.3, "d120": 2.1,
    "su": 3, "sd": 0, "np": 312,
    "mc": 12000, "yo": 75.0, "lp": 80.5,
    "py": 68.0, "py_pct": 18.4, "chg": 1.2,
    "p52": 65.0, "pe": 10.5, "hi52": 85.0, "lo52": 55.0,
    "vol": 15000000, "beta": 0.8, "avg_vol": 4600000,
    "suspended": false
  }]
}
```

⚠️ Wide per-date format 會令 dashboard 白畫面  
⚠️ NaN/Infinity → `math.isnan(v) or math.isinf(v)` → None
