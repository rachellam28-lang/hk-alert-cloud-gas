#!/usr/bin/env python3
"""Telegram → Claude bridge bot. Polling mode with session memory."""
import os, sys, json, time, requests
from datetime import datetime, timedelta

# === CONFIG ===
TG_TOKEN = os.environ.get("TG_BOT_TOKEN", "<YOUR_TG_TOKEN>")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "<YOUR_ANTHROPIC_KEY>")
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096
SESSION_TTL = timedelta(hours=1)  # keep per-chat history for 1hr

TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# === Per-chat session store ===
sessions: dict[int, dict] = {}  # chat_id → {"messages": [...], "last_active": datetime}


def claude_reply(chat_id: int, text: str) -> str:
    now = datetime.now()
    sess = sessions.get(chat_id)

    # Init or refresh session
    if not sess or (now - sess["last_active"]) > SESSION_TTL:
        sess = {"messages": [], "last_active": now}
        sessions[chat_id] = sess
    else:
        sess["last_active"] = now

    sess["messages"].append({"role": "user", "content": text})

    # Keep last 20 messages max to control cost
    if len(sess["messages"]) > 20:
        sess["messages"] = sess["messages"][-20:]

    try:
        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "messages": sess["messages"],
            },
            timeout=60,
        )
        if resp.status_code == 429:
            return "⏳ Rate limited. 等一陣再試。"
        if resp.status_code != 200:
            err = resp.json().get("error", {}).get("message", resp.text)
            return f"❌ API error: {err}"
        data = resp.json()
        reply = data["content"][0]["text"]
        sess["messages"].append({"role": "assistant", "content": reply})
        return reply
    except requests.exceptions.Timeout:
        return "⏳ Claude timeout — 試多次？"
    except Exception as e:
        return f"❌ Error: {e}"


def main():
    offset = 0
    print(f"Bot starting (model={MODEL})...")
    while True:
        try:
            r = requests.get(
                f"{TG_API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            if r.status_code != 200:
                print(f"TG API error {r.status_code}: {r.text[:200]}")
                time.sleep(5)
                continue
            data = r.json()
            for u in data.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message", {})
                text = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")
                if not text or not chat_id:
                    continue

                print(f"[{chat_id}] {text[:80]}...")
                reply = claude_reply(chat_id, text)

                # Telegram max 4096 chars per message
                for chunk in [reply[i:i+4000] for i in range(0, len(reply), 4000)]:
                    requests.post(
                        f"{TG_API}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk},
                        timeout=10,
                    )
        except requests.exceptions.ReadTimeout:
            pass  # getUpdates long-poll timeout — normal
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
