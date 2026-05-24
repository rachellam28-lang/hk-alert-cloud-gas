"""
Parallel CCASS Backfill — 6-shard subprocess orchestrator.

用法:
    cd ccass
    python -m scripts.parallel_backfill --start 2026-05-15 --end 2026-05-21
    python -m scripts.parallel_backfill --days 5  --stagger 60

架構:
    1. 每個交易日 launch 6 個 subprocess shard（stock-shard JSON only）
    2. Shard 之間 stagger 60s 起步
    3. 全部完成後 validate + merge JSON → SQLite（single process）
    4. 每個日期 merge 後即時計 trends（oldest first）
    5. 支援 resume：skip 已經喺 DB 嘅日期（除非 --force）

Safety:
    - 任何 shard exit 2（HKEX block）→ kill 晒所有 siblings
    - Atomic write (.tmp → rename)
    - Merge 前 9 項 validation
    - Per-shard log files
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = _PROJECT_ROOT / "data"
LOGS_DIR = _PROJECT_ROOT / "logs"

SHARD_TOTAL = 6
BACKFILL_SHARD_PREFIX = "backfill-shard"

# ─── helpers ────────────────────────────────────────────────────────────────

def _db_count_for_date(db_path: Path, query_date: date) -> int:
    """Count how many stocks already in ccass_daily for a given date."""
    import sqlite3
    date_str = query_date.strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode = WAL")
        n = conn.execute(
            "SELECT COUNT(*) FROM ccass_daily WHERE trade_date = ?", (date_str,)
        ).fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def _is_date_complete(db_path: Path, query_date: date, min_count: int = 2500) -> bool:
    """Return True if DB already has enough rows for this date."""
    return _db_count_for_date(db_path, query_date) >= min_count


def _shard_path(date_str: str, shard_idx: int) -> Path:
    return _PROJECT_ROOT / f"{BACKFILL_SHARD_PREFIX}-{date_str}-{shard_idx}.json"


def _shard_log_path(date_str: str, shard_idx: int) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / f"backfill-{date_str}-shard-{shard_idx}.log"


def _validate_shard_output(fpath: Path, expected_date: str, expected_shard: int,
                           expected_total: int) -> dict | None:
    """Validate a single shard JSON file. Returns parsed payload or None."""
    if not fpath.exists():
        print(f"  ❌ shard {expected_shard}: file not found: {fpath}")
        return None
    try:
        payload = json.loads(fpath.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ❌ shard {expected_shard}: JSON parse error: {e}")
        return None

    # Basic structure
    for k in ("shard", "shard_total", "query_date", "snapshots", "succeeded",
              "failed", "failed_stocks", "stocks_total", "stocks_in_shard"):
        if k not in payload:
            print(f"  ❌ shard {expected_shard}: missing key '{k}'")
            return None

    if payload["shard"] != expected_shard:
        print(f"  ❌ shard {expected_shard}: shard id mismatch ({payload['shard']})")
        return None
    if payload["shard_total"] != expected_total:
        print(f"  ❌ shard {expected_shard}: shard_total mismatch ({payload['shard_total']})")
        return None
    if payload["query_date"] != expected_date:
        print(f"  ❌ shard {expected_shard}: date mismatch ({payload['query_date']} != {expected_date})")
        return None
    if len(payload["snapshots"]) != payload["succeeded"]:
        print(f"  ❌ shard {expected_shard}: len(snapshots)={len(payload['snapshots'])} != succeeded={payload['succeeded']}")
        return None

    return payload


# ── Cleanup helpers ──────────────────────────────────────────────────────

def _cleanup_chromium_orphans() -> None:
    """Kill orphaned Chromium processes left by killed Playwright subprocesses."""
    import platform
    if platform.system() != "Windows":
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "chrome.exe", "/FI", "PID ne 0"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


def _kill_subprocess(p: subprocess.Popen) -> None:
    """Kill a subprocess and clean up its Chromium orphans."""
    try:
        p.kill()
        p.wait(timeout=10)
    except Exception:
        pass
    _cleanup_chromium_orphans()


def _validate_all_shards(date_str: str, universe_size: int) -> tuple[list[dict], int, bool]:
    """Validate all 6 shards for a date. Returns (all_payloads, total_failed, ok)."""
    all_payloads = []
    total_failed = 0
    all_ok = True

    for i in range(SHARD_TOTAL):
        fpath = _shard_path(date_str, i)
        p = _validate_shard_output(fpath, date_str, i, SHARD_TOTAL)
        if p is None:
            all_ok = False
            continue
        all_payloads.append(p)
        total_failed += p["failed"]
        print(f"  ✓ shard {i}: {p['succeeded']}/{p['stocks_in_shard']} succeeded, {p['failed']} failed")

    if len(all_payloads) != SHARD_TOTAL:
        print(f"  ❌ Only {len(all_payloads)}/{SHARD_TOTAL} valid shard files")
        return [], 0, False

    # Check for duplicate (stock_code, trade_date) across shards
    seen = set()
    for p in all_payloads:
        for snap in p["snapshots"]:
            key = (snap["stock_code"], snap["trade_date"])
            if key in seen:
                print(f"  ❌ Duplicate stock across shards: {key}")
                all_ok = False
            seen.add(key)

    # Check aggregate failure rate
    total_attempted = sum(p["stocks_in_shard"] for p in all_payloads)
    if total_attempted > 0:
        fail_rate = total_failed / total_attempted
        if fail_rate > 0.10:
            print(f"  ❌ Aggregate failure rate {fail_rate:.1%} > 10%, aborting")
            all_ok = False

    return all_payloads, total_failed, all_ok


def _merge_date(all_payloads: list[dict]) -> int:
    """Merge validated shard payloads into SQLite. Returns count of snapshots written."""
    from src.db import DB_PATH, init_db
    from src.scraper import save_snapshot, CCASSSnapshot

    init_db()

    written = 0
    for p in all_payloads:
        for snap_dict in p["snapshots"]:
            snap = CCASSSnapshot(
                stock_code=snap_dict["stock_code"],
                trade_date=snap_dict["trade_date"],
                total_shares=snap_dict["total_shares"],
                total_pct=snap_dict["total_pct"],
                num_participants=snap_dict.get("num_participants", 0),
                holdings=snap_dict.get("holdings", []),
            )
            try:
                save_snapshot(snap)
                written += 1
            except Exception as e:
                print(f"  ⚠️  save_snapshot failed for {snap_dict.get('stock_code', '??')}: {e}")

    return written


# ─── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parallel CCASS backfill")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD (inclusive, default: today)")
    parser.add_argument("--days", type=int, help="Last N trading days")
    parser.add_argument("--stagger", type=int, default=60, help="Seconds between shard starts (default: 60)")
    parser.add_argument("--force", action="store_true", help="Re-scrape dates already in DB")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    args = parser.parse_args()

    # Compute trading days
    from src.trading_calendar import today_hk, is_trading_day

    if args.days:
        from src.trading_calendar import last_n_trading_days
        days = last_n_trading_days(today_hk(), args.days)
    elif args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else today_hk()
        cur = start
        days = []
        while cur <= end:
            if is_trading_day(cur):
                days.append(cur)
            cur += timedelta(days=1)
    else:
        parser.error("Need --start/--end or --days")

    if not days:
        print("No trading days in range.")
        return

    print(f"📅 Trading days: {len(days)} — {', '.join(d.strftime('%Y-%m-%d') for d in days)}")
    print(f"🔧 Stagger: {args.stagger}s | Shards: {SHARD_TOTAL} | Force: {args.force}")

    from src.db import DB_PATH

    # Refresh universe once (parent process)
    from src.db import init_db
    from src.universe import refresh_universe, get_active_stocks
    init_db()
    # Skip universe refresh if DB already has stock data (avoids HKEX requests.get() hang)
    import sqlite3
    existing = sqlite3.connect(str(DB_PATH)).execute(
        "SELECT COUNT(*) FROM stock_universe"
    ).fetchone()[0]
    if existing < 500:
        try:
            refresh_universe()
        except Exception as e:
            print(f"⚠️  Universe refresh failed: {e}")
    else:
        print(f"⏭️  Skip universe refresh: {existing} stocks already in DB")
    stocks = get_active_stocks()
    print(f"📊 Universe: {len(stocks)} active stocks")

    total_start = time.monotonic()
    success_days = 0
    fail_days = 0

    # Process oldest first
    for d in sorted(days):
        date_str = d.strftime("%Y-%m-%d")
        print(f"\n{'='*60}")
        print(f"🔄 {date_str}")

        # Resume check
        if not args.force and _is_date_complete(DB_PATH, d):
            existing = _db_count_for_date(DB_PATH, d)
            print(f"  ⏭️  Skip: {existing} snapshots already in DB (use --force to redo)")
            success_days += 1
            continue

        if args.dry_run:
            print(f"  [DRY-RUN] Would launch {SHARD_TOTAL} shards, stagger {args.stagger}s")
            continue

        # Launch 6 shard subprocesses
        procs = []
        for si in range(SHARD_TOTAL):
            out_path = _shard_path(date_str, si)
            log_path = _shard_log_path(date_str, si)

            # Remove old files
            for p in (out_path, Path(str(out_path) + ".tmp")):
                if p.exists():
                    p.unlink()

            with open(str(log_path), "w", encoding="utf-8") as logf:
                p = subprocess.Popen(
                    [sys.executable, "-m", "src.runner",
                     "--shard", str(si),
                     "--shard-total", str(SHARD_TOTAL),
                     "--query-date", date_str,
                     "--out", str(out_path)],
                    cwd=str(_PROJECT_ROOT),
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                )
            procs.append((si, p, out_path, log_path))
            print(f"  🚀 Shard {si} PID={p.pid}")

            if si < SHARD_TOTAL - 1:
                print(f"     ⏳ Stagger {args.stagger}s...")
                time.sleep(args.stagger)

        # Wait for all to finish (max 3h per day)
        deadline = time.monotonic() + 10800  # 3 hours
        hkex_block_detected = False
        for si, p, out_path, log_path in procs:
            remaining = max(0, deadline - time.monotonic())
            try:
                rc = p.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                _kill_subprocess(p)
                print(f"  ❌ Shard {si} timed out (3h), killed")
                continue

            if rc == 2:
                # HKEX rate-limit / blocking — abort all
                print(f"  ❌ Shard {si} exit 2 (HKEX block detected)")
                hkex_block_detected = True
                # Kill all remaining siblings
                for sj, pj, _, _ in procs:
                    if sj != si and pj.poll() is None:
                        _kill_subprocess(pj)
                        print(f"     💀 Killed shard {sj}")
                break

            if rc != 0:
                # Non-zero but NOT HKEX block (e.g. internal deadline rc=3,
                # unhandled exception rc=1, etc.)
                print(f"  ⚠️  Shard {si} exit {rc} (non-HKEX error)")
                # Check if JSON was written despite the crash
                if out_path.exists():
                    print(f"     📄 JSON exists ({out_path.stat().st_size / 1024:.1f} KB) — will attempt recovery")
                continue

            print(f"  ✅ Shard {si} done (rc={rc}) → {out_path.name}")

        if hkex_block_detected:
            print(f"  🛑 {date_str} aborted: HKEX block detected")
            fail_days += 1
            continue

        # Validate all shards
        print(f"  🔍 Validating...")
        all_payloads, total_failed, valid = _validate_all_shards(date_str, len(stocks))

        if not valid:
            print(f"  🛑 {date_str} validation failed, skipping merge")
            fail_days += 1
            continue

        # Merge into DB
        print(f"  💾 Merging into DB...")
        written = _merge_date(all_payloads)
        print(f"  ✅ Merged {written} snapshots ({total_failed} failures)")

        # Compute trends for this date
        print(f"  📈 Computing trends...")
        try:
            from src.trend import compute_trends_for_date
            n_trends = compute_trends_for_date(d)
            print(f"  ✅ Trends: {n_trends} stocks computed")
        except Exception as e:
            print(f"  ⚠️  Trends failed: {e}")

        # Clean up temp files
        for si in range(SHARD_TOTAL):
            for p in (_shard_path(date_str, si), Path(str(_shard_path(date_str, si)) + ".tmp")):
                if p.exists():
                    p.unlink()

        success_days += 1

    # Final report
    elapsed = time.monotonic() - total_start
    print(f"\n{'='*60}")
    print(f"🏁 Backfill complete: {success_days}/{len(days)} days succeeded, {fail_days} failed")
    print(f"⏱️  Total time: {elapsed/3600:.1f} hours")
    if fail_days > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
