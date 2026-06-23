#!/usr/bin/env python3
"""
AI Team 集成 — 用 TradingAgents 分析 CCASS 信號，輸出 Buy/Hold/Sell 建議。

用法:
    python scripts/ai_team.py                              # 分析 top 5 VR 爆量股
    python scripts/ai_team.py --signal breakthrough         # 分析 breakthrough 信號
    python scripts/ai_team.py --signal transfers            # 分析大額轉倉信號
    python scripts/ai_team.py --codes 00700,09988,00005    # 指定股票代碼
    python scripts/ai_team.py --limit 3 --min-vr 2.0       # 分析 VR >= 2.0 嘅 top 3

環境變數 (from .env):
    DEEPSEEK_API_KEY / DEEPSEEK_MODEL / 
    TRADINGAGENTS_LLM_PROVIDER / TRADINGAGENTS_DEEP_THINK_LLM / 
    TRADINGAGENTS_QUICK_THINK_LLM / TRADINGAGENTS_LLM_BACKEND_URL
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import sqlite3
import time
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent  # ccass-debug/
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = PROJECT_DIR / "ccass" / "holdings.db"
OUTPUT_DIR = PROJECT_DIR / "data" / "ai_team_output"
TRADINGAGENTS_DIR = PROJECT_DIR.parent / "TradingAgents"

# Add TradingAgents to path (so it can be imported from ccass venv)
if str(TRADINGAGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(TRADINGAGENTS_DIR))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass

HKT = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════
# CCASS Data Loading
# ═══════════════════════════════════════════════════════════════

def load_ccass_dashboard() -> list[dict]:
    """Load ccass.json dashboard sorted by volume ratio (vr) descending."""
    with open(PROJECT_DIR / "ccass.json", encoding="utf-8") as f:
        data = json.load(f)
    stocks = data.get("stocks", [])
    # Filter: not suspended, has VR, has price
    active = [
        s for s in stocks
        if not s.get("suspended") and s.get("vr") is not None and s.get("lp")
    ]
    active.sort(key=lambda s: abs(s.get("vr", 0) or 0), reverse=True)
    return active


def load_breakthroughs() -> list[dict]:
    """Load data/breakthroughs.json."""
    bp_file = DATA_DIR / "breakthroughs.json"
    if not bp_file.exists():
        return []
    with open(bp_file, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("breakthroughs", [])


def load_transfers() -> list[dict]:
    """Load data/transfers.json."""
    tf_file = DATA_DIR / "transfers.json"
    if not tf_file.exists():
        return []
    with open(tf_file, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("transfers", [])


def load_stock_prices() -> dict:
    """Load data/stock_prices.json: {code: {yo, lp, py, py_pct}}."""
    sp_file = DATA_DIR / "stock_prices.json"
    if not sp_file.exists():
        return {}
    with open(sp_file, encoding="utf-8") as f:
        return json.load(f)


def load_db_trends(lookback_days: int = 30) -> list[dict]:
    """Load recent alerts/trends from holdings.db if populated."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # Try ccass_trends
        cur = conn.execute(
            "SELECT stock_code, trade_date, delta_5d_pct, delta_20d_pct, "
            "consecutive_increase_days, consecutive_decrease_days "
            "FROM ccass_trends ORDER BY trade_date DESC LIMIT 500"
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.OperationalError:
        return []


# ═══════════════════════════════════════════════════════════════
# Ticker Conversion
# ═══════════════════════════════════════════════════════════════

def hk_code_to_ticker(code: str) -> str:
    """Convert CCASS 5-digit code to a ticker string.
    
    00700 → 0700.HK
    00005 → 0005.HK
    """
    code = code.strip().zfill(5)
    # Strip leading zeros but keep at least 1 digit
    stripped = code.lstrip("0") or "0"
    return f"{int(code):04d}.HK"


def ccass_code_to_ticker(code: str) -> str:
    """Convert any HK stock code format to a ticker string."""
    code = code.strip()
    if code.endswith(".HK"):
        return code.upper()
    code = code.zfill(5)
    return f"{int(code):04d}.HK"


# ═══════════════════════════════════════════════════════════════
# Signal extraction / prioritisation
# ═══════════════════════════════════════════════════════════════

def extract_top_signals(
    dashboard: list[dict],
    limit: int = 5,
    min_vr: float = 0,
    signal_type: str = "dashboard",
    breakthroughs: list[dict] = None,
    transfers: list[dict] = None,
    specified_codes: list[str] = None,
) -> list[dict]:
    """Extract top signals for AI analysis.

    Returns list of {'code', 'name', 'reason', 'ticker', 'context'}
    """
    signals = []

    if specified_codes:
        # User specified exact codes
        code_set = {c.strip().zfill(5) for c in specified_codes}
        for s in dashboard:
            if s["c"] in code_set:
                signals.append(_make_signal_dashboard(s))
        return signals

    if signal_type == "breakthrough":
        if breakthroughs:
            # Sort by pct_above descending (most significant breakthroughs)
            bps = sorted(breakthroughs, key=lambda b: b.get("pct_above", 0), reverse=True)
            seen = set()
            for b in bps[:limit]:
                code = b.get("stock_code", "").strip().zfill(5)
                if code in seen:
                    continue
                seen.add(code)
                signals.append({
                    "code": code,
                    "name": b.get("title", ""),
                    "reason": f"Breakthrough: {b.get('type','?')} | "
                              f"Offer: {b.get('offer_price')} → Now: {b.get('current_price')} "
                              f"(+{b.get('pct_above',0):.1f}%)",
                    "ticker": ccass_code_to_ticker(code),
                    "context": json.dumps(b, ensure_ascii=False),
                })
        return signals

    if signal_type == "transfers":
        if transfers:
            # Sort by largest total_in or highest pct change
            ranked = sorted(
                transfers,
                key=lambda t: max(
                    abs(i.get("pct_chg") or 0) for i in t.get("ins", [])
                ) if t.get("ins") else 0,
                reverse=True,
            )
            seen = set()
            for t in ranked[:limit]:
                code = t.get("code", "").strip().zfill(5)
                if code in seen:
                    continue
                seen.add(code)
                top_in = t.get("ins", [{}])[0] if t.get("ins") else {}
                top_out = t.get("outs", [{}])[0] if t.get("outs") else {}
                signals.append({
                    "code": code,
                    "name": t.get("name", ""),
                    "reason": f"大額轉倉 | IN: {top_in.get('pname','?')[:30]} "
                              f"({top_in.get('pct_chg',0):+.1f}%) | "
                              f"OUT: {top_out.get('pname','?')[:30]} "
                              f"({top_out.get('pct_chg',0):+.1f}%)",
                    "ticker": ccass_code_to_ticker(code),
                    "context": json.dumps(t, ensure_ascii=False, default=str),
                })
        return signals

    # Default: dashboard signals (VR rank + CCASS delta)
    count = 0
    for s in dashboard:
        vr = s.get("vr") or 0
        if abs(vr) < min_vr:
            continue
        signals.append(_make_signal_dashboard(s))
        count += 1
        if count >= limit:
            break

    return signals


def _make_signal_dashboard(s: dict) -> dict:
    """Build a signal dict from a dashboard row."""
    code = s["c"]
    name = s.get("n", "")
    vr = s.get("vr", 0) or 0
    d5 = s.get("d5")
    chg = s.get("chg", 0) or 0
    lp = s.get("lp", 0)
    py_pct = s.get("py_pct", 0)
    tp = s.get("tp", 0)
    t5 = s.get("t5", 0)
    bt5 = s.get("bt5", 0)
    ah = s.get("ah", 0)
    pe = s.get("pe")

    parts = []
    if vr and abs(vr) > 1.5:
        parts.append(f"VR爆量 {vr:.1f}x")
    if d5 is not None and abs(d5) > 1:
        parts.append(f"CCASS Δ5d: {d5:+.2f}%")
    if abs(chg) > 1:
        parts.append(f"股價變動: {chg:+.2f}%")
    if py_pct:
        parts.append(f"YTD: {py_pct:+.1f}%")
    if pe:
        parts.append(f"PE: {pe:.1f}")

    reason = " | ".join(parts) if parts else f"Dashboard signal | VR={vr:.2f}"

    # Build rich context
    context = json.dumps({
        "ccass_total_pct": tp,
        "ccass_top5_pct": t5,
        "ccass_delta_5d": d5,
        "price_last": lp,
        "price_ytd_pct": py_pct,
        "price_change_pct": chg,
        "vol_ratio": vr,
        "adj_hhi": ah,
        "broker_top5_pct": bt5,
        "pe": pe,
    }, ensure_ascii=False, default=str)

    return {
        "code": code,
        "name": name,
        "reason": reason,
        "ticker": ccass_code_to_ticker(code),
        "context": context,
    }


# ═══════════════════════════════════════════════════════════════
# TradingAgents Integration
# ═══════════════════════════════════════════════════════════════

def run_ai_analysis(
    signals: list[dict],
    trade_date: str = None,
    quiet: bool = False,
    skip_llm: bool = False,
) -> list[dict]:
    """Run TradingAgents multi-agent analysis on each signal.

    Returns list of result dicts with 'code', 'name', 'decision', 'reasoning', 'raw'
    """
    if trade_date is None:
        trade_date = datetime.now(HKT).strftime("%Y-%m-%d")

    results = []

    if skip_llm:
        # Dry-run mode: just show what would be analyzed
        if not quiet:
            print(f"\n{'='*60}")
            print(f"AI Team 信號清單 ({len(signals)} 隻)")
            print(f"{'='*60}")
            for i, s in enumerate(signals, 1):
                print(f"\n#{i}  {s['code']} {s['name']}")
                print(f"   Ticker: {s['ticker']}")
                print(f"   信號: {s['reason']}")
        return signals

    # Import TradingAgents
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG
    except ImportError as e:
        print(f"❌ Cannot import TradingAgents: {e}")
        print(f"   Make sure TradingAgents is installed in the venv")
        print(f"   TRADINGAGENTS_DIR: {TRADINGAGENTS_DIR}")
        return []

    # ── Auto-detect best LLM provider ──
    provider = os.getenv("TRADINGAGENTS_LLM_PROVIDER")
    if not provider:
        # Auto-detect: prefer DeepSeek → OpenAI
        if os.getenv("DEEPSEEK_API_KEY"):
            provider = "deepseek"
        elif os.getenv("OPENAI_API_KEY"):
            provider = "openai"

    # Set good default models per provider
    provider_defaults = {
        "deepseek": {"deep": "deepseek-v4-pro", "quick": "deepseek-v4-flash"},
        "openai": {"deep": "gpt-4.1", "quick": "gpt-4.1-mini"},
    }
    pd = provider_defaults.get(provider, {})
    deep_model = os.getenv("TRADINGAGENTS_DEEP_THINK_LLM") or pd.get("deep", "gpt-4.1")
    quick_model = os.getenv("TRADINGAGENTS_QUICK_THINK_LLM") or pd.get("quick", "gpt-4.1-mini")

    # Explicit config (NOT from DEFAULT_CONFIG which resolves env at import time)
    from tradingagents.default_config import DEFAULT_CONFIG
    config = DEFAULT_CONFIG.copy()
    if provider:
        config["llm_provider"] = provider
    config["deep_think_llm"] = deep_model
    config["quick_think_llm"] = quick_model
    config["output_language"] = "Chinese"
    config["benchmark_ticker"] = "^HSI"
    config["data_vendors"] = {
        "core_stock_apis": "futu",
        "technical_indicators": "futu",
        "fundamental_data": "futu",
        "news_data": "futu",
    }
    # Keep debate rounds low for speed; CCASS signals are screening, not deep dives
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1

    if not quiet:
        provider = config.get("llm_provider", "openai")
        deep_model = config.get("deep_think_llm", "?")
        quick_model = config.get("quick_think_llm", "?")
        print(f"🤖 TradingAgents: {provider} / {deep_model} / {quick_model}")
        print(f"📅 Trade date: {trade_date}")
        print(f"📊 Analyzing {len(signals)} signals...\n")

    for i, sig in enumerate(signals):
        ticker = sig["ticker"]
        code = sig["code"]
        name = sig["name"]

        if not quiet:
            print(f"[{i+1}/{len(signals)}] {code} {name} ({ticker})")
            print(f"    信號: {sig['reason']}")

        try:
            ta = TradingAgentsGraph(
                selected_analysts=["market", "news", "fundamentals"],
                debug=False,
                config=config,
            )
            final_state, decision = ta.propagate(ticker, trade_date)

            # Extract key outputs
            market_report = final_state.get("market_report", "")
            fundamentals_report = final_state.get("fundamentals_report", "")
            news_report = final_state.get("news_report", "")
            investment_plan = final_state.get("investment_plan", "")
            final_decision = final_state.get("final_trade_decision", "")

            result = {
                "code": code,
                "name": name,
                "ticker": ticker,
                "signal_reason": sig["reason"],
                "decision": decision,
                "final_decision_full": final_decision[:1000],
                "market_report": market_report[:800],
                "fundamentals_report": fundamentals_report[:800],
                "news_report": news_report[:800],
                "investment_plan": investment_plan[:800],
                "trade_date": trade_date,
                "analyzed_at": datetime.now(HKT).isoformat(),
                "error": None,
            }

            if not quiet:
                emoji = {"Buy": "🟢", "Overweight": "🟡⬆️", "Hold": "⚪",
                          "Underweight": "🟡⬇️", "Sell": "🔴"}.get(decision, "❓")
                print(f"    → {emoji} **{decision}**\n")

            results.append(result)

        except Exception as e:
            if not quiet:
                print(f"    → ❌ Error: {e}\n")
            results.append({
                "code": code,
                "name": name,
                "ticker": ticker,
                "signal_reason": sig["reason"],
                "decision": "Error",
                "final_decision_full": "",
                "trade_date": trade_date,
                "analyzed_at": datetime.now(HKT).isoformat(),
                "error": str(e),
            })

        # Small delay to avoid rate limits
        if i < len(signals) - 1:
            time.sleep(1)

    return results


# ═══════════════════════════════════════════════════════════════
# Output formatting
# ═══════════════════════════════════════════════════════════════

def format_cantonese_summary(results: list[dict]) -> str:
    """Format results in Cantonese terse style for Telegram."""
    lines = []
    lines.append("🤖 **AI Team 分析報告**")
    lines.append("")

    # Group by decision
    by_decision = {}
    for r in results:
        d = r.get("decision", "Error")
        by_decision.setdefault(d, []).append(r)

    order = ["Buy", "Overweight", "Hold", "Underweight", "Sell", "Error"]
    for dec in order:
        items = by_decision.get(dec, [])
        if not items:
            continue
        emoji = {"Buy": "🟢", "Overweight": "🟡⬆️", "Hold": "⚪",
                  "Underweight": "🟡⬇️", "Sell": "🔴", "Error": "❌"}.get(dec, "❓")
        lines.append(f"{emoji} **{dec}**")
        for r in items:
            code = r["code"]
            name = r.get("name", "")
            reason = r.get("signal_reason", "")
            error = r.get("error")
            if error:
                lines.append(f"  • {code} {name} — ERROR: {error[:80]}")
            else:
                # Truncate reason for Telegram readability
                short_reason = reason[:100] + ("..." if len(reason) > 100 else "")
                lines.append(f"  • {code} {name}")
                if short_reason:
                    lines.append(f"    _{short_reason}_")
        lines.append("")

    lines.append(f"📅 {results[0].get('trade_date','?') if results else '?'}")
    return "\n".join(lines)


def save_results(results: list[dict]) -> Path:
    """Save results to JSON for later review."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(HKT).strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"ai_team_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    return out_file


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="AI Team: TradingAgents 分析 CCASS 信號",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/ai_team.py                              # Top 5 VR 爆量股
  python scripts/ai_team.py --signal breakthrough         # 突破信號
  python scripts/ai_team.py --signal transfers            # 大額轉倉
  python scripts/ai_team.py --codes 00700,09988           # 指定股票
  python scripts/ai_team.py --limit 3 --min-vr 2.0        # VR ≥ 2.0
  python scripts/ai_team.py --no-llm --limit 10           # Dry-run preview
        """,
    )
    parser.add_argument(
        "--signal", choices=["dashboard", "breakthrough", "transfers"],
        default="dashboard",
        help="信號來源 (default: dashboard — VR ranking)"
    )
    parser.add_argument(
        "--codes", type=str, default=None,
        help="指定股票代碼，逗號分隔 (e.g. 00700,09988,00005)"
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="最多分析幾多隻 (default: 5)"
    )
    parser.add_argument(
        "--min-vr", type=float, default=0,
        help="最低 VR 閾值 (default: 0 = no filter)"
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Trade date YYYY-MM-DD (default: today HKT)"
    )
    parser.add_argument(
        "--no-llm", dest="skip_llm", action="store_true",
        help="Dry-run: 淨係顯示信號清單，唔行 TradingAgents"
    )
    parser.add_argument(
        "--no-save", dest="no_save", action="store_true",
        help="唔 save JSON output"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Silent mode (淨 print final summary)"
    )
    parser.add_argument(
        "--telegram", action="store_true",
        help="Send summary via Telegram (需要 TELEGRAM_TOKEN + TELEGRAM_CHAT_ID)"
    )

    args = parser.parse_args()

    # 1. Load data
    dashboard = load_ccass_dashboard()
    breakthroughs = load_breakthroughs()
    transfers = load_transfers()

    if not args.quiet:
        print(f"📦 CCASS dashboard: {len(dashboard)} stocks ({sum(1 for s in dashboard if (s.get('vr') or 0) > 1.5)} 爆量)")
        if breakthroughs:
            print(f"📦 Breakthroughs: {len(breakthroughs)} signals")
        if transfers:
            print(f"📦 Transfers: {len(transfers)} detected")

    # 2. Parse specified codes
    specified = None
    if args.codes:
        specified = [c.strip() for c in args.codes.split(",") if c.strip()]

    # 3. Extract signals
    signals = extract_top_signals(
        dashboard=dashboard,
        limit=args.limit,
        min_vr=args.min_vr,
        signal_type=args.signal,
        breakthroughs=breakthroughs,
        transfers=transfers,
        specified_codes=specified,
    )

    if not signals:
        print("⚠️ No signals found. Check data or relax filters.")
        return 1

    # 4. Run AI analysis
    trade_date = args.date or datetime.now(HKT).strftime("%Y-%m-%d")
    results = run_ai_analysis(
        signals=signals,
        trade_date=trade_date,
        quiet=args.quiet,
        skip_llm=args.skip_llm,
    )

    # 5. Output
    if args.skip_llm:
        print(f"\n{'='*60}")
        print("Dry-run complete. 用 --no-llm 實際行 TradingAgents。")
        print(f"{'='*60}")
    else:
        print(f"\n{'='*60}")
        print(format_cantonese_summary(results))
        print(f"{'='*60}")

    # 6. Save
    if not args.no_save and not args.skip_llm:
        out_file = save_results(results)
        print(f"\n💾 Saved: {out_file}")

    # 7. Telegram
    if args.telegram and results and not args.skip_llm:
        _maybe_send_telegram(results)

    return 0


def _maybe_send_telegram(results: list[dict]):
    """Send summary via Telegram if configured."""
    try:
        from ccass.src.alerts import send_telegram
    except ImportError:
        print("⚠️ Cannot import ccass.src.alerts — skip Telegram")
        return

    summary = format_cantonese_summary(results)
    if send_telegram(summary):
        print("📨 Telegram sent OK")
    else:
        print("⚠️ Telegram send failed")


if __name__ == "__main__":
    sys.exit(main())
