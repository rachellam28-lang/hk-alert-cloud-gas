#!/usr/bin/env python3
"""Keep the retired Daily Prompt URL as a lightweight Trading Desk redirect."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "daily_trade_prompt.html"

HTML = """<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta http-equiv="refresh" content="0;url=trading_desk.html">
<title>每日提示已整合至交易台</title>
</head>
<body>
<p>每日提示已整合至<a href="trading_desk.html">交易台</a>。</p>
<script>location.replace('trading_desk.html');</script>
</body>
</html>
"""


def main() -> int:
    OUT_PATH.write_text(HTML, encoding="utf-8")
    print(f"Generated retired route redirect: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
