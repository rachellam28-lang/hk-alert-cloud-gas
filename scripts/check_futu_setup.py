#!/usr/bin/env python
"""
Quick Futu/OpenD probe for this repository.

Checks:
1. local .env values relevant to Futu
2. Python SDK import
3. TCP reachability to FutuOpenD
4. quote context creation
5. a lightweight API probe via get_global_state / get_market_snapshot
6. local futu-opend-rs presence for Windows fallback

Usage:
    python scripts/check_futu_setup.py
    python scripts/check_futu_setup.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from futu_env import (
    DEFAULT_FUTU_HOST,
    DEFAULT_FUTU_PORT,
    DEFAULT_FUTU_TIMEOUT,
    get_local_futu_opend_rs_info,
    probe_futu_socket,
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def env_str(name: str, default: str) -> str:
    return str(os.environ.get(name, default)).strip() or default


def env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def detect_opend_artifacts() -> dict:
    roaming = Path(os.environ.get("APPDATA", "")) / "com.futunn.FutuOpenD"
    log_dir = roaming / "Log"
    latest_log = None
    latest_log_mtime = None
    if log_dir.exists():
        logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if logs:
            latest_log = str(logs[0])
            latest_log_mtime = datetime.fromtimestamp(logs[0].stat().st_mtime).isoformat(timespec="seconds")
    local_rs = get_local_futu_opend_rs_info()
    return {
        "roaming_dir_exists": roaming.exists(),
        "log_dir_exists": log_dir.exists(),
        "latest_log": latest_log,
        "latest_log_mtime": latest_log_mtime,
        "local_futu_opend_rs": {
            "root": str(local_rs["root"]),
            "exe": str(local_rs["exe"]),
            "config": str(local_rs["config"]),
            "stderr_log": str(local_rs["stderr_log"]),
        } if local_rs else None,
    }


def futu_probe(host: str, port: int) -> dict:
    result = {
        "sdk_import_ok": False,
        "context_ok": False,
        "global_state_ok": False,
        "market_snapshot_ok": False,
        "global_state": None,
        "global_state_flags": None,
        "sample_snapshot": None,
        "error": None,
    }
    try:
        from futu import OpenQuoteContext, RET_OK
    except Exception as exc:
        result["error"] = f"import futu failed: {exc}"
        return result

    result["sdk_import_ok"] = True
    ctx = None
    try:
        ctx = OpenQuoteContext(host=host, port=port)
        result["context_ok"] = True

        try:
            ret, data = ctx.get_global_state()
            if ret == RET_OK:
                result["global_state_ok"] = True
                if isinstance(data, dict):
                    result["global_state"] = data
                    result["global_state_flags"] = {
                        "qot_logined": bool(data.get("qot_logined")),
                        "trd_logined": bool(data.get("trd_logined")),
                        "market_hk": data.get("market_hk"),
                        "server_ver": data.get("server_ver"),
                    }
                elif hasattr(data, "to_dict"):
                    rows = data.to_dict(orient="records")
                    result["global_state"] = rows
                    if rows:
                        row = rows[0]
                        result["global_state_flags"] = {
                            "qot_logined": bool(row.get("qot_logined")),
                            "trd_logined": bool(row.get("trd_logined")),
                            "market_hk": row.get("market_hk"),
                            "server_ver": row.get("server_ver"),
                        }
                else:
                    result["global_state"] = str(data)
        except Exception as exc:
            result["error"] = f"get_global_state failed: {exc}"

        try:
            ret2, snap = ctx.get_market_snapshot(["HK.00700"])
            if ret2 == RET_OK and getattr(snap, "empty", True) is False:
                row = snap.iloc[0]
                result["market_snapshot_ok"] = True
                result["sample_snapshot"] = {
                    "code": str(row.get("code", "")),
                    "name": str(row.get("name", "")),
                    "last_price": float(row.get("last_price", 0) or 0),
                    "update_time": str(row.get("update_time", "")),
                }
            elif not result["error"]:
                result["error"] = str(snap)
        except Exception as exc:
            if not result["error"]:
                result["error"] = f"get_market_snapshot failed: {exc}"
    except Exception as exc:
        result["error"] = f"context connect failed: {exc}"
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()

    load_env()
    host = env_str("FUTU_HOST", DEFAULT_FUTU_HOST)
    port = env_int("FUTU_PORT", DEFAULT_FUTU_PORT)
    timeout_s = env_float("FUTU_CONNECT_TIMEOUT", DEFAULT_FUTU_TIMEOUT)
    use_futu = env_str("USE_FUTU", "false").lower() in {"1", "true", "yes"}

    tcp_ok, tcp_detail = probe_futu_socket(host, port, timeout_s)
    artifacts = detect_opend_artifacts()
    probe = futu_probe(host, port) if tcp_ok else {
        "sdk_import_ok": False,
        "context_ok": False,
        "global_state_ok": False,
        "market_snapshot_ok": False,
        "global_state": None,
        "global_state_flags": None,
        "sample_snapshot": None,
        "error": "skipped because tcp connect failed",
    }
    if not tcp_ok:
        try:
            import futu  # noqa: F401
            probe["sdk_import_ok"] = True
        except Exception:
            probe["sdk_import_ok"] = False

    flags = probe.get("global_state_flags") or {}
    qot_logined = flags.get("qot_logined")
    trd_logined = flags.get("trd_logined")
    auth_required = bool(tcp_ok and probe.get("context_ok") and probe.get("global_state_ok") and qot_logined is False)

    status = "ok"
    if not use_futu:
        status = "warn"
    if not tcp_ok or not probe.get("context_ok"):
        status = "fail"
    elif auth_required or not probe.get("market_snapshot_ok"):
        status = "warn"

    payload = {
        "status": status,
        "repo_env": {
            "env_path": str(ENV_PATH),
            "env_exists": ENV_PATH.exists(),
            "FUTU_HOST": host,
            "FUTU_PORT": port,
            "FUTU_CONNECT_TIMEOUT": timeout_s,
            "USE_FUTU": use_futu,
        },
        "tcp": {
            "ok": tcp_ok,
            "detail": tcp_detail,
        },
        "futu": probe,
        "auth_required": auth_required,
        "opend_artifacts": artifacts,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if status == "ok" else 1

    print("=== Futu/OpenD Setup Probe ===")
    print(f"env: {ENV_PATH}")
    print(f"USE_FUTU={use_futu} host={host} port={port} timeout={timeout_s}")
    print(f"tcp: {'OK' if tcp_ok else 'FAIL'} - {tcp_detail}")
    print(f"sdk import: {'OK' if probe.get('sdk_import_ok') else 'FAIL'}")
    print(f"context: {'OK' if probe.get('context_ok') else 'FAIL'}")
    print(f"global_state: {'OK' if probe.get('global_state_ok') else 'FAIL'}")
    print(f"market_snapshot(HK.00700): {'OK' if probe.get('market_snapshot_ok') else 'FAIL'}")
    if flags:
        print(
            "global flags: "
            f"qot_logined={qot_logined} "
            f"trd_logined={trd_logined} "
            f"market_hk={flags.get('market_hk')} "
            f"server_ver={flags.get('server_ver')}"
        )
    if probe.get("error"):
        print(f"probe detail: {probe['error']}")

    if artifacts.get("roaming_dir_exists"):
        print("opend artifacts: found local FutuOpenD roaming dir")
    if artifacts.get("latest_log"):
        print(f"latest opend log: {artifacts['latest_log']}")
        print(f"log mtime: {artifacts['latest_log_mtime']}")
    if artifacts.get("local_futu_opend_rs"):
        rs = artifacts["local_futu_opend_rs"]
        print(f"local futu-opend-rs: {rs['exe']}")
        print(f"local futu-opend-rs config: {rs['config']}")

    if probe.get("sample_snapshot"):
        snap = probe["sample_snapshot"]
        print(
            "sample quote: "
            f"{snap.get('code')} {snap.get('name')} "
            f"last={snap.get('last_price')} time={snap.get('update_time')}"
        )

    if status != "ok":
        print("\nNext actions:")
        if not use_futu:
            print("- set USE_FUTU=true in repo .env")
        if not tcp_ok:
            print("- start FutuOpenD and keep it listening on 127.0.0.1:11111")
            print("- log into FutuOpenD with the 牛牛 account used by this machine")
            if artifacts.get("local_futu_opend_rs"):
                print("- local helper: python scripts/start_futu_opend_rs.py")
        elif auth_required:
            print("- gateway socket is up, but quote backend is not logged in yet")
            print("- complete device/SMS verification, then retry")
            if artifacts.get("local_futu_opend_rs"):
                print("- local helper: python scripts/start_futu_opend_rs.py")
                print("- non-interactive SMS path: python scripts/start_futu_opend_rs.py --verify-code <SMS_CODE>")
        elif not probe.get("market_snapshot_ok"):
            print("- verify the OpenD login/session is healthy, then retry")
        if not artifacts.get("roaming_dir_exists") and not artifacts.get("local_futu_opend_rs"):
            print("- install FutuOpenD on this machine")

    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
