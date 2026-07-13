#!/usr/bin/env python3
"""Fetch HK fund-flow data through westock CLI without requiring bash."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "fundflow.json"


def load_top_codes(limit: int) -> list[str]:
    data = json.loads((ROOT / "holdings.json").read_text(encoding="utf-8"))
    stocks = data.get("stocks", [])
    stocks = sorted(stocks, key=lambda s: s.get("mc") or 0, reverse=True)
    return [str(s["c"]).zfill(5) for s in stocks[:limit] if s.get("c")]


def parse_number(value: str) -> float | None:
    value = (value or "").strip()
    if not value or value == "-":
        return None
    return float(value.replace(",", ""))


def parse_output(text: str) -> dict[str, dict]:
    fundflow: dict[str, dict] = {}
    headers: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if cols and cols[0] == "symbol":
            headers = cols
            continue
        if not cols or not cols[0].startswith("hk"):
            continue

        row = dict(zip(headers, cols)) if headers else {}
        code_value = row.get("symbol") or row.get("code") or cols[0]
        code = code_value.replace("hk", "").zfill(5)
        lgt: dict = {}
        try:
            lgt = json.loads(row.get("LgtHoldInfo", ""))
        except Exception:
            pass
        fundflow[code] = {
            "date": row.get("EndDate", cols[4] if len(cols) > 4 else ""),
            "main_in": parse_number(row.get("MainIn", "")),
            "main_net": parse_number(row.get("MainNetFlow", "")),
            "main_out": parse_number(row.get("MainOut", "")),
            "retail_in": parse_number(row.get("RetailIn", "")),
            "retail_net": parse_number(row.get("RetailNetFlow", "")),
            "retail_out": parse_number(row.get("RetailOut", "")),
            "total_net": parse_number(row.get("TotalNetFlow", "")),
            # The westock hkfund response does not provide short-sale fields.
            # Missing is null, never a fabricated numeric zero.
            "short_amount": None,
            "short_ratio": None,
            "short_shares": None,
            "lgt_hold_ratio": parse_number(str(lgt.get("LgtHoldRatio", row.get("_lgtHoldInfo.LgtHoldRatio", "")))),
            "lgt_cap_chg_daily": parse_number(str(lgt.get("LgtCapChgDaily", row.get("_lgtHoldInfo.LgtCapChgDaily", "")))),
            "lgt_share_chg_daily": parse_number(str(lgt.get("LgtShareChgDaily", row.get("_lgtHoldInfo.LgtShareChgDaily", "")))),
        }
    return fundflow


def batched(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_batch(codes: list[str], timeout: int) -> dict[str, dict]:
    symbol_arg = ",".join("hk" + c for c in codes)
    proc = subprocess.run(
        ["cmd.exe", "/c", "npx", "-y", "westock-data-clawhub@1.0.4", "hkfund", symbol_arg],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "westock hkfund failed").strip())
    return parse_output(proc.stdout)


def build_output(fundflow: dict[str, dict]) -> dict:
    ranked_main_in = sorted(
        ((c, d) for c, d in fundflow.items() if d.get("main_net") is not None),
        key=lambda x: x[1]["main_net"], reverse=True,
    )
    ranked_main_out = sorted(
        ((c, d) for c, d in fundflow.items() if d.get("main_net") is not None),
        key=lambda x: x[1]["main_net"],
    )
    ranked_short = sorted(
        ((c, d) for c, d in fundflow.items() if d.get("short_ratio") is not None),
        key=lambda x: x[1]["short_ratio"], reverse=True,
    )
    ranked_sb = sorted(
        ((c, d) for c, d in fundflow.items() if d.get("lgt_cap_chg_daily") is not None),
        key=lambda x: abs(x[1]["lgt_cap_chg_daily"]), reverse=True,
    )
    updated = next((v.get("date") for v in fundflow.values() if v.get("date")), "")
    return {
        "updated": updated,
        "source": "westock-data-clawhub hkfund",
        "data_kind": "observed_provider_snapshot",
        "top_main_in": [{"c": c, **{k: d[k] for k in ("main_net", "main_in", "main_out", "total_net")}} for c, d in ranked_main_in[:20]],
        "top_main_out": [{"c": c, **{k: d[k] for k in ("main_net", "main_in", "main_out", "total_net")}} for c, d in ranked_main_out[:20]],
        "top_short": [{"c": c, "short_ratio": d["short_ratio"], "short_amount": d["short_amount"]} for c, d in ranked_short[:20]],
        "top_southbound": [
            {
                "c": c,
                "lgt_hold_ratio": d["lgt_hold_ratio"],
                "lgt_cap_chg_daily": d["lgt_cap_chg_daily"],
                "lgt_share_chg_daily": d["lgt_share_chg_daily"],
            }
            for c, d in ranked_sb[:20]
        ],
        "all": fundflow,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    codes = load_top_codes(args.top)
    if not codes:
        raise SystemExit("No codes loaded from holdings.json")

    fundflow: dict[str, dict] = {}
    batches = list(batched(codes, args.batch_size))
    for idx, batch in enumerate(batches, 1):
        print(f"[{idx}/{len(batches)}] {batch[0]}..{batch[-1]}", flush=True)
        fundflow.update(fetch_batch(batch, args.timeout))

    output = build_output(fundflow)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT)
    print(f"Saved {len(fundflow)} fundflow rows to {OUT} updated={output.get('updated')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
