r"""Redeem a Longbridge auth code and update local token caches.

Usage:
    .\.venv\Scripts\python.exe .\scripts\redeem_longbridge_auth_code.py --auth-code <CODE>
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import requests


def redeem(auth_code: str) -> dict:
    resp = requests.post(
        "https://mcp.longbridge.com/agent",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "authenticate",
                "arguments": {"auth_code": auth_code},
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    for line in resp.text.splitlines():
        if not line.startswith("data: "):
            continue
        data = json.loads(line[6:])
        if "error" in data:
            raise RuntimeError(data["error"].get("message") or str(data["error"]))
        result = data.get("result", {})
        content = result.get("content") or []
        if content:
            return json.loads(content[0]["text"])
    raise RuntimeError("No auth payload returned by Longbridge agent")


def write_repo_env(access_token: str) -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    text = env_path.read_text(encoding="utf-8", errors="ignore") if env_path.exists() else ""
    line = "LONGBRIDGE_ACCESS_TOKEN=" + access_token
    if re.search(r"^LONGBRIDGE_ACCESS_TOKEN=.*$", text, re.M):
        text = re.sub(r"^LONGBRIDGE_ACCESS_TOKEN=.*$", line, text, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    env_path.write_text(text, encoding="utf-8")


def write_local_cache(payload: dict) -> None:
    token_dir = Path.home() / ".longbridge" / "openapi" / "tokens" / "mcp-auth"
    token_dir.mkdir(parents=True, exist_ok=True)
    token_data = {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "token_type": "Bearer",
        "expires_in": payload.get("expires_in", 1209600),
        "scope": " ".join(payload.get("scopes", [])),
    }
    (token_dir / "token.json").write_text(
        json.dumps(token_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-code", required=True)
    args = parser.parse_args()

    payload = redeem(args.auth_code.strip())
    write_repo_env(payload["access_token"])
    write_local_cache(payload)
    print("redeem_ok=1")
    print("account_channel=" + str(payload.get("account_channel", "")))
    print("scopes=" + ",".join(payload.get("scopes", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
