#!/usr/bin/env python3
"""Fill missing placing agents in data/placements_enriched.json from HKEX PDFs.

This is a bounded, text-first extractor. It avoids OCR hangs and saves progress
after every successful match. If MISTRAL_API_KEY is set, it uses Mistral OCR as
a fallback for PDFs where embedded text extraction is weak.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import base64
from pathlib import Path
from typing import Any

import pymupdf
import requests


DATA = Path("data/placements_enriched.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
NEEDS_KW = ("配售", "供股", "先舊後新")
SKIP_KW = ("代價發行",)

AGENT_KEYWORDS = (
    "Placing Agent",
    "Placing Agents",
    "Underwriter",
    "Underwriters",
    "Bookrunner",
    "Global Coordinator",
    "配售代理",
    "包銷商",
)

COMPANY_RE = re.compile(
    r"([A-Z][A-Za-z0-9\s&.,'()/-]{3,80}?"
    r"(?:Securities|Capital|Finance|Financial|Bank|Asia|International|"
    r"Partners|Wealth|Asset\s+Management|Investments?|Brokerage|"
    r"Corporate\s+Finance|Futures)"
    r"(?:[A-Za-z0-9\s&.,'()/-]{0,50})"
    r"\s+(?:Limited|Ltd\.?|Company\s+Limited|Co\.?\s+Ltd\.?|Corporation|Inc\.?))"
    r"|([\u4e00-\u9fffA-Za-z0-9（）()·\s]{2,50}?"
    r"(?:證券|資本|金融|融資|財務|銀行|投資|包銷|企業融資)[\u4e00-\u9fffA-Za-z0-9（）()·\s]{0,20}?"
    r"(?:有限公司|股份有限公司)?)",
    re.I,
)

BAD_RE = re.compile(
    r"(stock exchange|hong kong exchanges|securities and futures|"
    r"announcement|general mandate|the board|the company|the group|"
    r"placing agreement|placing shares|shareholder|underwriting agreement|"
    r"rights issue|prospectus|application form|nil-paid|acceptance|"
    r"mandatory cash offer|possible unconditional|cash offer)",
    re.I,
)

FINANCIAL_RE = re.compile(
    r"(securities|capital|finance|financial|bank|brokerage|corporate finance|"
    r"asset management|wealth|investment|證券|資本|金融|融資|財務|銀行|投資|包銷)",
    re.I,
)

SUSPICIOUS_RE = re.compile(
    r"(^HK\)|\bLimited\s+[A-Z][a-z]+|\bGroup\s+Limited$|^\d|"
    r"placing agreement|the company|the board|shareholder)",
    re.I,
)


def save(items: list[dict]) -> None:
    tmp = DATA.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA)


def clean_agent(raw: str, stock_name: str) -> str | None:
    name = re.sub(r"\s+", " ", raw or "").strip(" ,.;:：-")
    name = re.sub(r"^(?:and|or|the|as|to|by)\s+", "", name, flags=re.I)
    name = re.sub(r"^(?:Sole|Joint|Overall|Company)\s+", "", name, flags=re.I)
    name = re.sub(r"^(?:Placing Agents?|Underwriters?|Bookrunners?|Global Coordinators?)\s*:?\s*", "", name, flags=re.I)
    name = re.sub(r"^(?:配售代理|包銷商)\s*:?\s*", "", name)
    name = re.sub(r",?\s+being\s+.*$", "", name, flags=re.I)
    name = name.strip(" ,.;:：-")

    if not (4 <= len(name) <= 80):
        return None
    if re.match(r"^(FOR AND ON BEHALF OF|ON BEHALF OF)\b", name, flags=re.I):
        return None
    if re.search(r"[A-Za-z]", name) and not re.match(r"^[A-Z]", name):
        return None
    if stock_name and len(stock_name) >= 3 and stock_name.lower() in name.lower():
        return None
    if BAD_RE.search(name):
        return None
    if SUSPICIOUS_RE.search(name):
        return None
    if not FINANCIAL_RE.search(name):
        return None
    if re.match(r"^\d", name):
        return None
    return name


def is_agent_missing_or_bad(item: dict[str, Any]) -> bool:
    agent = item.get("placing_agent")
    if not agent:
        return True
    return clean_agent(str(agent), str(item.get("name", ""))) is None


def candidate_score(text: str, start: int) -> int:
    window_start = max(0, start - 900)
    window_end = min(len(text), start + 900)
    window = text[window_start:window_end]
    positions = [window.lower().find(k.lower()) for k in AGENT_KEYWORDS]
    positions = [p for p in positions if p >= 0]
    if not positions:
        return 10_000
    rel = start - window_start
    return min(abs(rel - p) for p in positions)


def extract_from_text(text: str, stock_name: str) -> str | None:
    if not any(k.lower() in text.lower() for k in AGENT_KEYWORDS):
        return None

    best: tuple[int, str] | None = None
    for m in COMPANY_RE.finditer(text):
        raw = m.group(1) or m.group(2) or ""
        agent = clean_agent(raw, stock_name)
        if not agent:
            continue
        score = candidate_score(text, m.start())
        if score > 2500:
            continue
        if best is None or score < best[0]:
            best = (score, agent)

    if best:
        return best[1]

    # Table-style fallback: key phrase on one line, company on nearby line.
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    for i, line in enumerate(lines):
        if any(k.lower() in line.lower() for k in AGENT_KEYWORDS):
            for near in lines[i : i + 6] + lines[max(0, i - 3) : i]:
                for m in COMPANY_RE.finditer(near):
                    agent = clean_agent(m.group(1) or m.group(2) or "", stock_name)
                    if agent:
                        return agent
    return None


def extract_from_pdf(url: str, stock_name: str) -> str | None:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    resp.raise_for_status()
    if len(resp.content) < 500:
        return None
    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    try:
        pages = min(doc.page_count, 8)
        text = "\n".join(doc[i].get_text("text") for i in range(pages))
    finally:
        doc.close()
    agent = extract_from_text(text, stock_name)
    if agent:
        return agent
    return extract_with_mistral_ocr(resp.content, stock_name)


def extract_with_mistral_ocr(pdf_bytes: bytes, stock_name: str) -> str | None:
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return None

    max_pages = int(os.environ.get("MISTRAL_MAX_PAGES", "0") or "0")
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    body = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": "data:application/pdf;base64," + pdf_b64,
        },
        "document_annotation_prompt": (
            "Extract the placing agent or underwriter company name for this HKEX "
            "announcement. Return JSON with keys placing_agent and evidence. "
            "placing_agent must be the exact company name, or null if unavailable."
        ),
        "document_annotation_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "placing_agent_extraction",
                "schema": {
                    "type": "object",
                    "properties": {
                        "placing_agent": {"type": ["string", "null"]},
                        "evidence": {"type": ["string", "null"]},
                    },
                    "required": ["placing_agent", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "table_format": "markdown",
        "extract_header": True,
        "extract_footer": True,
    }
    if max_pages > 0:
        body["pages"] = f"0-{max_pages - 1}"
    resp = requests.post(
        "https://api.mistral.ai/v1/ocr",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    payload = resp.json()
    doc_ann = payload.get("document_annotation")
    if doc_ann:
        try:
            parsed = json.loads(doc_ann)
            agent = clean_agent(str(parsed.get("placing_agent") or ""), stock_name)
            if agent:
                return agent
        except Exception:
            pass
    pages = payload.get("pages") or []
    markdown = "\n\n".join(str(p.get("markdown") or "") for p in pages)
    return extract_from_text(markdown, stock_name)


def main() -> int:
    limit = int(os.environ.get("AGENT_FILL_LIMIT", "0") or "0")
    items = json.loads(DATA.read_text(encoding="utf-8"))
    needs = [
        (i, x)
        for i, x in enumerate(items)
        if is_agent_missing_or_bad(x)
        and x.get("pdf_url")
        and any(k in x.get("method", "") for k in NEEDS_KW)
        and not any(k in x.get("method", "") for k in SKIP_KW)
    ]
    if limit:
        needs = needs[:limit]
    print(f"Need with PDF: {len(needs)}")

    found = 0
    for n, (idx, item) in enumerate(needs, 1):
        code = item.get("code", "")
        name = item.get("name", "")
        url = item.get("pdf_url", "")
        print(f"[{n}/{len(needs)}] {code} {name}", end=" ", flush=True)
        try:
            agent = extract_from_pdf(url, name)
        except Exception as exc:
            print(f"ERR {type(exc).__name__}: {str(exc)[:80]}", flush=True)
            time.sleep(0.2)
            continue
        if agent:
            items[idx]["placing_agent"] = agent
            found += 1
            save(items)
            print(f"-> {agent}", flush=True)
        else:
            print("-", flush=True)
        time.sleep(0.2)

    total = sum(1 for x in items if x.get("placing_agent"))
    print(f"Done: found={found}, total={total}/{len(items)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
