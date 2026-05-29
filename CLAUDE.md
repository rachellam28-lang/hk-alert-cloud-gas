# CCASS Tracker — Hermes / Codex 常設合約

> 限制愈清晰，自主性愈高。你寫清楚邊界，AI 喺邊界內就敢自主行動。
> 每月第 1 個星期一 review + 更新此文件。

---

## FATAL 規則（任何情況都唔可以 override）

### FATAL-001：禁止批量發送 Telegram alert
- 根因：Telegram 有 rate limit，批量發送會觸發 flood control → bot 被 mute/ban，損失不可逆
- 每條 alert ≥ 3 秒間隔
- 單次 batch 上限：20 條 alert
- 超過 50 條 → summary only，只發一條 summary message
- 唔理係咩情況、咩原因，FATAL-001 不可繞過

### FATAL-002：禁止破壞 production database
- 根因：`ccass.db` 係唯一 source of truth，任何 DROP/DELETE/ALTER 可能導致數據永久丟失，backfill 成本極高（數日 runtime）
- `ccass.db` 係 source of truth
- 只可以 INSERT / UPDATE / ADD COLUMN / SELECT
- Migration 前必須先 backup：`cp ccass.db ccass.db.backup.$(date +%Y%m%d_%H%M%S)`
- Never DROP TABLE, never DROP COLUMN, never DELETE without user explicit approval

### FATAL-003（2026-05-23 修訂）：Parallel scraping 限制
- 根因：HKEX 有 WAF/Akamai protection，過多 concurrent request → IP ban，所有 scraper 全死，restore 需等 IP cool-down（數小時至數日）
- **Direct in-process parallel scraping/writing must stay disabled (parallel_workers=1).**
- **Historical backfill may use bounded stock-shard parallelism** where:
  - Shards are **separate subprocesses** writing JSON only (never direct DB writes)
  - Starts are **staggered by ≥30 seconds** between shards
  - HKEX block detection (`RuntimeError` on 7+/12 bad) **aborts the entire run**
  - SQLite writes happen in a **single merge process** after all shards complete
  - Aggregate failure rate > 10% → abort that date
- This provides ~6× speedup for backfill without increasing WAF risk beyond what the existing daily 6-shard GitHub Actions workflow already does.

### FATAL-004：禁止 commit secrets
- 根因：API key / token 一旦 push 上 public repo → 即刻 exposed，必須 revoke + rotate，所有 dependent service 中斷
- `.env` 必須喺 `.gitignore`
- Telegram bot token、OpenAI/DeepSeek API key、Discord webhook URL → 全部入 `.env`
- 每次 commit 前 check diff 有冇潛在 secret leakage
- 如果懷疑 exposed → 即刻通知用戶 rotate key，唔好等

---

## GUIDELINE（預設行為，可用戶 override）

### GUIDELINE-001：Prefer structural fixes over band-aids
- 例如：remove race condition entirely vs adding retries
- 例如：fix root cause in scraper vs adding try/except wrapper

### GUIDELINE-002：Codex review before merge
- 所有 CCASS 代碼改動 → Codex review first（除非 Codex block 咗）
- 用戶 directive：「你問左 codex 先好 action」

### GUIDELINE-003：Ask Codex first, don't over-specify
- 俾 Codex 自主決定 implementation detail
- 用戶 directive：「所有叫 codex 攪」、「ccass 所有比 codex 決策」

### GUIDELINE-004：Small-cap data = priority
- 100% market cap coverage matters
- Missing 08xxx is blocking, not cosmetic
- 用戶 trade 細價股，small-cap data > large-cap polish

### GUIDELINE-005：Speed over explanation
- 用戶 impatient，prefer 直接行動
- 多步驟任務 → monolithic script，唔好分拆太多 step
- 用「？」、「done?」、「點？」check progress → 即刻 status update

### GUIDELINE-006：Use SQLite window functions for trends
- Trend calculation (5d/20d/60d delta) → SQL window functions
- Easier to add columns later, query 比 Python pandas 簡單
- Keep it simple — 呢個 use case 根本唔需要 PostgreSQL

---

## 主動性規則（Proactive Mandate）

核心原則：**唔好等人問，主動做。由「AI assistant」變成「AI teammate」。**

### 發現問題時
1. **即時診斷** — 唔好只報告症狀，要搵 root cause
2. **提出修復方案** — 同時提供即時修復 + 長遠方案
3. **主動修復** — 低風險、可逆嘅直接做；高風險先問用戶
4. **匯報結果** — 做完要講：做咗咩、點解、結果如何

### Cron 失敗時
1. 檢查**所有相關 pipeline**，唔好只修一個
2. 分析係**個別失敗**定係**系統性問題**
3. 補跑必須遵守 FATAL-001

### 代碼質量
- 改完 `.py` → 即刻 clear `.pyc` cache + test run
- Silent corruption（冇 error 但有錯 data）最危險 → 加 validation check
- 每次 parse CCASS data 後 check 數字範圍係咪合理

### CCASS 特定
- 香港公眾假期 CCASS 冇更新 → cron 跑出空數據要 skip，唔好當 fail
- HTML 結構會改 → 加 schema validation，唔好只 check format
- 如果 scrape 失敗率突然升高 → 檢查係咪 HTML structure changed

---

## Night Shift Agent

每日 cron job（Hermes `cronjob` tool）：
- **時間**: 每日 HKEX update 後（約 7am HKT）
- **任務**:
  1. Scrape 當日 CCASS data（如有）
  2. 計算 5d/20d 持倉變化趨勢
  3. 檢測異常變動（大手增減 ≥5%）
  4. Generate alert summary → Telegram
  5. Check 所有 pipeline health
  6. Report: success/fail + 異常變動 summary
- **失敗處理**: ping Telegram with error detail
- **約束**: 遵守所有 FATAL rules，尤其 FATAL-001（alert summary only）

---

## 自我迭代指令

### Save as skill（完成複雜 task 後）
- 完成 5+ tool call 嘅 task → offer to save as skill
- Fix tricky bug → save approach as skill（`skill_manage(action='create')`）
- 新 workflow discovered → save as skill

### Update skill（使用 skill 時發現問題）
- Skill outdated / incomplete / wrong → `skill_manage(action='patch')` immediately
- 唔好等 — skills that aren't maintained become liabilities

### Update this file
- 系統改咗 → update CLAUDE.md
- 新踩坑 → add FATAL/GUIDELINE
- Monthly review: 每月第 1 個星期一

---

## Backfill 流程 (WORKING — 2026-05-28)

```
# 1. Clear stale caches + lock
rm -rf ccass/src/__pycache__ ccass/scripts/__pycache__
rm -f /tmp/ccass_backfill.lock

# 2. Clear stale .pyc from ALL directories
find ccass-debug -name "*.pyc" -delete
find ccass-debug -name "__pycache__" -type d -exec rm -rf {} +

# 3. Run sequential backfill (NEVER parallel)
cd ccass && python -m scripts.backfill --start 2026-05-26 --end 2026-05-27

# 4. After scrape, compute missing concentration metrics
python -m scripts.compute_metrics
```

**Speed:** ~7 stocks/sec when IP is OK
**Disk:** ~70MB per date, ~1.5GB for 20 dates
**Failures:** subprocess-based scrape_one.py per stock — reliable 60s hard timeout, never hangs
**Known bug:** runner reports "0 succeeded" even when data saved successfully (subprocess return code issue — cosmetic only)

---

## 踩坑記錄

| 坑 | 症狀 | 修復 |
|---|---|---|
| `.pyc` cache stale | New metrics all NULL | Clear `__pycache__/` before backfill |
| Codex Cloudflare block | 403 from HK IP | Wait for IP cool-down; use Hermes meanwhile |
| CCASS HTML structure change | XPath matches wrong column | Schema validation: check value ranges |
| Windows curl + Chinese = GBK | Crash UTF-8 server | Use browser fetch() or Python urllib |
| Parallel scrape → WAF ban | All scrapers dead | FATAL-003: subprocess shard only, staggered starts |
| **cloudscraper JS engine hang** | Infinite hang, ~10s→∞ | **2026-05-27: REMOVED. Plain `requests` works — HKEX no Cloudflare.** |
| **parallel_backfill.py shard** | PID lock fragile, shards fail | **2026-05-27: ABANDONED. Simple sequential for-loop only.** |
| **ProcessPoolExecutor scrape** | Workers stuck, stdout hidden | **2026-05-27: ABANDONED. Single-process sequential.** |
| **ThreadPoolExecutor timeout** | GIL blocks C-level I/O kill | **2026-05-28: ABANDONED. Sequential with 30s requests timeout works.** |
| **HKEX IP blacklist** | All requests hang > 10min | **2026-05-28: Wait 6-12hr cool-down. Parallel = trigger WAF ban.** |

## 踩坑記錄（Backfill Hang — 2026-05-27/28 實戰）

### Timeline
| 時間 | 症狀 | Root cause | 修復 |
|------|------|-----------|------|
| 05-27 上午 | backfill hang 喺 form token 後，冇 progress | IP blacklist（parallel_backfill 6-thread 觸發 HKEX WAF） | Wait cool-down |
| 05-27 下午 | 單隻 00018 hang 180s | `requests` timeout 對某啲 HKEX connections 冇效（TCP accept but no data） | 第一次 fix: `ThreadPoolExecutor` |
| 05-28 凌晨 | ThreadPoolExecutor fix FAIL | ThreadPoolExecutor.__exit__ 等 hung thread → GIL block | 第二次 fix: `ProcessPoolExecutor` |
| 05-28 凌晨 | ProcessPoolExecutor FAIL | C-level I/O hang — Python CANNOT kill C-blocked thread even with process timeout | 第三次 fix: `subprocess.run()` |
| 05-28 早上 | subprocess 成功 ✅ | OS-level `SIGKILL` on subprocess → reliably kills any hang | **Final solution** |

### 成功配方（2026-05-28 FINAL）

| 項目 | 值 |
|------|-----|
| 架構 | `subprocess.run(python scrape_one.py)` per stock |
| Hard timeout | 60s per stock（`subprocess.run(timeout=60)`） |
| 殺 process | OS SIGKILL — bypass Python GIL |
| Speed | ~7 stocks/sec (~5 min/day) |
| Method | Sequential only — NEVER parallel |
| Pre-run | Clear `__pycache__/` + `.pyc` everywhere |
| Post-run | `compute_metrics.py` 補濃度指標 |
| Known bug | Runner says "0 succeeded" — check DB directly |

### 死路（NEVER retry）

| 方法 | 死因 | Date |
|------|------|------|
| cloudscraper | JS engine indefinite hang | 2026-05-27 |
| parallel_backfill | Triggers HKEX IP blacklist | 2026-05-27 |
| ProcessPoolExecutor | Workers stuck, GIL block | 2026-05-28 |
| ThreadPoolExecutor | C-level I/O unkillable from Python | 2026-05-28 |
| Webb-site | Closed 2025 Oct | 2026-05-20 |
| requests+BS4 (fast) | HK IP gets banned | 2026-05-22 |
| baostock | A-shares only | 2026-05-23 |
| HKEX hidden JSON API | Does not exist | 2026-05-23 |
