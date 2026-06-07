"""Longbridge OAuth — run this on Windows, complete auth in browser."""
import sys, os
print("Starting...", flush=True)
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

from longbridge.openapi import Config, OAuthBuilder

def show_url(url):
    print(f"\n=== OPEN THIS URL IN BROWSER ===\n{url}\n================================", flush=True)

oauth = OAuthBuilder('ff0a3d7d-ca88-42b7-94b0-36f01d773f8c').build(show_url)
config = Config.from_oauth(oauth)
print("\n✅ OAuth SUCCESS! Token saved.", flush=True)

# Test
from longbridge.openapi import MarketContext
ctx = MarketContext(config)
resp = ctx.broker_holding_detail('700.HK')
print(f"00700.HK: {resp.security.name} — {len(resp.holdings)} brokers", flush=True)
h = resp.holdings[0]
print(f"Top 1: {h.broker_name} = {h.holding_ratio}%", flush=True)
print("DONE", flush=True)
