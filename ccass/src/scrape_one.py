"""Scrape single stock in subprocess — returns full snapshot as JSON."""
import sys, json, os
# Add PROJECT ROOT (ccass/) to sys.path so BOTH 'src.scraper' and scraper's
# internal 'from src.db import ...' work correctly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    stock_code = sys.argv[1]
    query_date = sys.argv[2]
    user_agent = sys.argv[3] if len(sys.argv) > 3 else 'Mozilla/5.0'
    
    # P2-6: suppress scraper logger noise in subprocess stdout (stderr only)
    import logging
    logging.root.setLevel(logging.WARNING)
    from src.scraper import CCASSScraper, _compute_concentration_metrics
    from datetime import date
    
    s = CCASSScraper(user_agent, delay_min=0, delay_max=0, timeout=15, max_retries=1)
    dt = date.fromisoformat(query_date)
    snap = s.scrape_stock(stock_code, dt)
    
    if snap and snap.holdings:
        # Compute top5/top10 from holdings (CCASSSnapshot has no top5_pct attr)
        sorted_shares = sorted([h["shares"] for h in snap.holdings if h.get("shares")], reverse=True)
        top5 = sum(sorted_shares[:5])
        top10 = sum(sorted_shares[:10])
        top5_pct = round(top5 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
        top10_pct = round(top10 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
        
        # Compute concentration metrics in subprocess, return everything as JSON
        cm = _compute_concentration_metrics(snap.holdings)
        print(json.dumps({
            "ok": True,
            "stock_code": snap.stock_code,
            "trade_date": snap.trade_date,
            "total_shares": snap.total_shares,
            "total_pct": snap.total_pct,
            "num_participants": snap.num_participants,
            "top5_pct": top5_pct,
            "top10_pct": top10_pct,
            "adj_hhi": cm.get("adj_hhi"),
            "broker_top5_pct": cm.get("broker_top5_pct"),
            "top_broker_id": cm.get("top_broker_id", ""),
            "top_broker_name": cm.get("top_broker_name", ""),
            "top_broker_pct": cm.get("top_broker_pct"),
            "futu_pct": cm.get("futu_pct"),
            "a00005_pct": cm.get("a00005_pct"),
            "adjusted_float": cm.get("adjusted_float"),
            "holdings": snap.holdings,
        }))
    else:
        print(json.dumps({"ok": False, "stock_code": stock_code, "reason": "no_data"}))

if __name__ == "__main__":
    main()
