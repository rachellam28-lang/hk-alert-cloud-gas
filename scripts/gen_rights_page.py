#!/usr/bin/env python3
"""Generate rights_analysis.html — v4: 8120 pattern. Rating = jump status, not discount."""
import json, re, os, glob, sys
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'raw')

from issuer_score import issuer_pressure_score

with open(os.path.join(DATA_DIR, 'placements_enriched.json'), 'r', encoding='utf-8') as f:
    data = json.load(f)

EXACT_DEDUPE_FIELDS = (
    'title',
    'method',
    'purpose',
    'price',
    'shares',
    'amount',
    'pct_shares',
    'pdf_url',
)

def _norm_key_text(value):
    return re.sub(r'\s+', ' ', str(value or '').strip()).lower()

def _row_date(value):
    text = str(value or '').strip()
    return text[:10] if re.match(r'^\d{4}-\d{2}-\d{2}', text) else text

def exact_row_key(row):
    parts = [
        str(row.get('code') or '').strip().lstrip('0').zfill(5),
        _row_date(row.get('date_parsed') or row.get('date')),
        _norm_key_text(row.get('category')),
    ]
    for field in EXACT_DEDUPE_FIELDS:
        parts.append(_norm_key_text(row.get(field)))
    return tuple(parts)

def dedupe_exact_rows(rows):
    seen = set()
    deduped = []
    removed = 0
    for row in rows:
        key = exact_row_key(row)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        deduped.append(row)
    return deduped, removed

data, DEDUPED_EXACT_ROWS = dedupe_exact_rows(data)
if DEDUPED_EXACT_ROWS:
    print(f"Deduped exact placement rows: {DEDUPED_EXACT_ROWS}")

def load_json_file(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

STOCK_PRICE_CACHE = load_json_file(os.path.join(DATA_DIR, 'stock_prices.json'), {})
SYSTEM_YEAR = datetime.now().year

# ====== Load raw/ price history ======
def load_raw_prices():
    hist = {}
    raw_path = RAW_DIR
    if not os.path.isdir(raw_path):
        return hist
    for fp in sorted(glob.glob(os.path.join(raw_path, 'prices_*.json'))):
        m = re.search(r'prices_(\d{4})(\d{2})(\d{2})', os.path.basename(fp))
        if not m:
            continue
        d = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        try:
            day = json.load(open(fp))
            for code, val in day.items():
                code5 = str(code).zfill(5)
                px = val.get('close', val) if isinstance(val, dict) else val
                if px and float(px) > 0.0001:
                    hist.setdefault(code5, {})[d] = float(px)
        except Exception:
            continue
    return hist

PRICE_HIST = load_raw_prices()
print(f"Loaded raw/ prices for {len(PRICE_HIST)} stocks")

def latest_close(code):
    """Latest raw close from raw/prices_*.json, if available."""
    pxs = PRICE_HIST.get(str(code).zfill(5))
    if not pxs:
        return None, None
    dates = sorted(pxs.keys())
    if not dates:
        return None, None
    last_day = dates[-1]
    return pxs[last_day], last_day

def compute_jump(code, ann_date_str):
    """(jump_pct, status): jumped|waiting|no_jump|no_data"""
    from datetime import datetime
    pxs = PRICE_HIST.get(str(code).zfill(5))
    if not pxs:
        return None, 'no_data'
    dates = sorted(pxs.keys())
    base_day = None
    for d in dates:
        if d >= ann_date_str:
            base_day = d
            break
    if base_day is None:
        return None, 'no_data'
    # GUARD: base_day must be within 4 calendar days of announcement
    # Otherwise raw/ doesn't cover this placement (old → random window)
    gap = (datetime.strptime(base_day, '%Y-%m-%d') -
           datetime.strptime(ann_date_str, '%Y-%m-%d')).days
    if gap > 1:
        return None, 'no_data'
    base = pxs[base_day]
    fwd = [d for d in dates if d > base_day][:5]
    if not fwd:
        return None, 'waiting'
    best = max(pxs[d] / base - 1 for d in fwd)
    best_px = max(pxs[d] for d in fwd)
    pct = round(best * 100, 1)
    
    # Price floor: sub-$0.05 stocks need ≥3 tick move (not just % noise)
    if best >= 0.08 and base < 0.05:
        abs_move = best_px - base
        min_tick = 0.001 if base < 0.25 else 0.005  # HKEX tick rules
        if abs_move < min_tick * 3:
            # <3 ticks = noise, not a real jump. Downgrade to no_jump if window passed.
            return (pct, 'no_jump') if len(fwd) >= 5 else (pct, 'waiting')
    
    if best >= 0.08:
        return pct, 'jumped'
    return (pct, 'no_jump') if len(fwd) >= 5 else (pct, 'waiting')

def announcement_return(code, ann_date_str):
    """Return announcement-date-to-latest return using raw history.

    Uses the first available raw close on/after the announcement date as base,
    and the latest raw close in the history as the end point.
    """
    from datetime import datetime
    pxs = PRICE_HIST.get(str(code).zfill(5))
    if not pxs or not ann_date_str:
        return None
    dates = sorted(pxs.keys())
    base_day = None
    for d in dates:
      if d >= ann_date_str:
        base_day = d
        break
    if base_day is None:
        return None
    gap = (datetime.strptime(base_day, '%Y-%m-%d') -
           datetime.strptime(ann_date_str, '%Y-%m-%d')).days
    if gap > 1:
        return None
    base = pxs[base_day]
    latest = pxs[dates[-1]]
    if base <= 0:
        return None
    return round((latest / base - 1) * 100, 1)

# ====== V4: 8120 pattern rating ======
TERMINAL_RE = re.compile(r"(TERMINATION|TERMINATED|CANCELLATION|CANCELLED|LAPSE|LAPSED|WITHDRAW|終止|取消|失效)", re.I)
COMPLETE_RE = re.compile(r"(COMPLETION|RESULTS?|ALLOTMENT|完成|結果)", re.I)
SUPPLEMENT_RE = re.compile(r"(SUPPLEMENT|EXTENSION|REVISED|補充|延期|修訂)", re.I)

def _safe_num(v):
    try:
        n = float(v)
    except Exception:
        return None
    return n if n == n else None

def fmt_pct(v, signed=False):
    n = _safe_num(v)
    if n is None:
        return None
    prefix = '+' if signed and n > 0 else ''
    return f'{prefix}{n:.1f}%'

def fmt_price(v):
    n = _safe_num(v)
    if n is None:
        return '-'
    return f'{n:.3f}' if n < 1 else f'{n:.2f}'

def stock_price_year_lines(code):
    code5 = str(code or '').zfill(5)
    entry = STOCK_PRICE_CACHE.get(code5) if isinstance(STOCK_PRICE_CACHE, dict) else None
    if not isinstance(entry, dict):
        return {}
    lines = {}
    yo = _safe_num(entry.get('yo'))
    if yo is not None and yo > 0:
        year = SYSTEM_YEAR
        yo_date = entry.get('yo_date')
        if isinstance(yo_date, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', yo_date):
            year = int(yo_date[:4])
        lines[year] = {
            'year': year,
            'date': yo_date or f'{year}-year-open',
            'open': yo,
            'source': 'stock_prices.yo',
        }
    py = _safe_num(entry.get('py'))
    if py is not None and py > 0:
        year = int(entry.get('py_year') or (SYSTEM_YEAR - 2))
        lines.setdefault(year, {
            'year': year,
            'date': entry.get('py_date') or f'{year}-year-open',
            'open': py,
            'source': 'stock_prices.py',
        })
    return lines

def current_price_anchor(p):
    code = str(p.get('code') or '').zfill(5)
    for key in ('latest_price', 'manual_latest_price'):
        px = _safe_num(p.get(key))
        if px is not None and px > 0:
            return px, p.get('latest_date') or 'latest raw'
    px, d = latest_close(code)
    if px is not None and px > 0:
        return px, d
    entry = STOCK_PRICE_CACHE.get(code) if isinstance(STOCK_PRICE_CACHE, dict) else None
    if isinstance(entry, dict):
        px = _safe_num(entry.get('lp'))
        if px is not None and px > 0:
            return px, entry.get('lp_time') or entry.get('price_updated_at') or 'stock_prices'
    px = _safe_num(p.get('market_price'))
    if px is not None and px > 0:
        return px, 'announcement market price'
    return None, None

def year_open_profile(p):
    code = str(p.get('code') or '').zfill(5)
    target = [SYSTEM_YEAR, SYSTEM_YEAR - 2]
    lines = stock_price_year_lines(code)
    ordered = [lines[y] for y in target if y in lines]
    px, px_date = current_price_anchor(p)
    profile = {
        'available': len(ordered),
        'target_years': target,
        'above': 0,
        'below': 0,
        'anchor': px,
        'anchor_date': px_date,
        'levels': [],
        'badge': '不足',
        'cls': 'year-open-missing',
        'summary': '今年/前年年開線不足',
        'score_delta': 0,
        'basis_text': '年開線不足',
    }
    if px is None or px <= 0:
        profile['summary'] = '缺最新價，未能比較今年/前年年開線'
        return profile
    if not ordered:
        return profile

    above = below = 0
    parts = []
    for row in ordered:
        opened = _safe_num(row.get('open'))
        if opened is None or opened <= 0:
            continue
        dist = (px / opened - 1) * 100
        status = 'above' if px >= opened else 'below'
        if status == 'above':
            above += 1
        else:
            below += 1
        item = {
            'year': row.get('year'),
            'date': row.get('date'),
            'open': opened,
            'source': row.get('source'),
            'status': status,
            'distance_pct': round(dist, 1),
        }
        profile['levels'].append(item)
        sign = '+' if dist > 0 else ''
        parts.append(f"{row.get('year')} {fmt_price(opened)} ({sign}{dist:.1f}%)")

    available = len(profile['levels'])
    profile['available'] = available
    profile['above'] = above
    profile['below'] = below
    profile['summary'] = f"現價 {fmt_price(px)}；" + '；'.join(parts)

    if available < len(target):
        if available == 1 and below == 1:
            profile['badge'] = f"{below}/{len(target)} 下方"
            profile['cls'] = 'year-open-down'
        elif available == 1 and above == 1:
            profile['badge'] = f"{above}/{len(target)} 上方"
            profile['cls'] = 'year-open-up'
        profile['basis_text'] = f"年開線不足 {available}/{len(target)}"
        return profile

    if available >= 2 and above >= 2:
        profile['score_delta'] = 2
        profile['badge'] = f"{above}/{available} 上方"
        profile['cls'] = 'year-open-up'
        profile['basis_text'] = f"企上 {above}/{available} 條年開線"
    elif available >= 2 and below >= 2:
        profile['score_delta'] = -2
        profile['badge'] = f"{below}/{available} 下方"
        profile['cls'] = 'year-open-down'
        profile['basis_text'] = f"跌穿 {below}/{available} 條年開線"
    else:
        profile['badge'] = f"{above}/{available} 上方"
        profile['cls'] = 'year-open-mixed'
        profile['basis_text'] = f"年開線好淡混合 {above}/{available} 上方"
    return profile

def has_extracted_terms(p):
    return any((_safe_num(p.get(k)) or 0) > 0 for k in ('price_num', 'amount_num', 'pct_num'))

def announcement_stage(p):
    text = f"{p.get('title') or ''} {p.get('method') or ''}"
    if TERMINAL_RE.search(text):
        return '已終止/取消'
    if SUPPLEMENT_RE.search(text):
        return '補充/延期'
    if COMPLETE_RE.search(text):
        return '完成/結果'
    if p.get('source') == 'announcement':
        return '新公告'
    return '原始條款'

def display_category(p):
    cat = p.get('category') or '其他'
    stage = announcement_stage(p)
    if stage == '已終止/取消':
        return '已終止'
    if stage == '完成/結果' and cat in ('供股', '配售', '先舊後新'):
        return f'{cat}結果'
    if stage == '補充/延期' and cat in ('供股', '配售', '先舊後新'):
        return f'{cat}更新'
    return cat

def classify_supply_intent(p, jump_pct, jump_status):
    """Classify whether the issue looks like share-cornering or cash-raising.

    This is an evidence label, not an intent claim. Ex-rights/completion price
    behaviour is preferred; if terms or completion data are missing, stay
    conservative and mark it as pending.
    """
    stage = announcement_stage(p)
    year_open = year_open_profile(p)
    if stage == '已終止/取消':
        return {
            'label': '已終止',
            'cls': 'supply-ended',
            'score': 0,
            'basis': '公告已終止/取消，唔再當新供股/配股壓力',
            'tradable': False,
            'year_open': year_open,
        }

    score = 0
    positive = []
    negative = []
    pending = []

    terms_ok = has_extracted_terms(p)
    has_completion_anchor = bool(
        p.get('manual_finished_date')
        or _safe_num(p.get('post_ex_date_return_pct')) is not None
        or stage == '完成/結果'
    )
    current_ret = _safe_num(p.get('post_ex_date_return_pct'))
    if current_ret is None:
        current_ret = _safe_num(p.get('current_return_pct'))
    ann_ret = _safe_num(p.get('announcement_return_pct'))
    discount = _safe_num(p.get('discount_pct'))
    dilution = _safe_num(p.get('pct_num'))
    text = f"{p.get('purpose') or ''} {p.get('method') or ''} {p.get('title') or ''}"

    if not terms_ok:
        pending.append('價格/攤薄條款未抽齊')
    if not has_completion_anchor:
        pending.append('未有明確除淨/完成錨點')

    if current_ret is not None and (has_completion_anchor or p.get('price_num')):
        if current_ret >= 10:
            score += 4
            positive.append(f"現價高過發行價 {fmt_pct(current_ret, signed=True)}")
        elif current_ret >= 0:
            score += 2
            positive.append(f"現價守住發行價 {fmt_pct(current_ret, signed=True)}")
        elif current_ret <= -8:
            score -= 3
            negative.append(f"現價低過發行價 {fmt_pct(current_ret, signed=True)}")
        else:
            score -= 1
            negative.append(f"現價略低過發行價 {fmt_pct(current_ret, signed=True)}")

    if ann_ret is not None:
        if ann_ret >= 8:
            score += 2
            positive.append(f"公告至今轉強 {fmt_pct(ann_ret, signed=True)}")
        elif ann_ret >= 0:
            score += 1
            positive.append(f"公告至今未跌穿 {fmt_pct(ann_ret, signed=True)}")
        elif ann_ret <= -10:
            score -= 2
            negative.append(f"公告後轉弱 {fmt_pct(ann_ret, signed=True)}")
        else:
            score -= 1
            negative.append(f"公告後偏弱 {fmt_pct(ann_ret, signed=True)}")

    yo_delta = _safe_num(year_open.get('score_delta')) or 0
    if yo_delta > 0:
        score += yo_delta
        positive.append(year_open.get('basis_text') or '企上年開線')
    elif yo_delta < 0:
        score += yo_delta
        negative.append(year_open.get('basis_text') or '跌穿年開線')
    elif year_open.get('available', 0) <= 1:
        pending.append(year_open.get('basis_text') or '年開線不足')

    if jump_status == 'jumped':
        score += 2
        positive.append(f"T+5有炒味 {fmt_pct(jump_pct, signed=True)}")
    elif jump_status == 'no_jump':
        score -= 1
        negative.append(f"T+5未過 +8% 門檻 {fmt_pct(jump_pct, signed=True)}")

    if discount is not None:
        if discount <= -20:
            score -= 2
            negative.append(f"深折讓 {abs(discount):.1f}%")
        elif discount <= -10:
            score -= 1
            negative.append(f"折讓 {abs(discount):.1f}%")
        elif discount >= 0:
            score += 1
            positive.append('無折讓壓價')

    if dilution and dilution > 0:
        if dilution >= 100:
            score -= 3
            negative.append(f"超大攤薄 {dilution:.1f}%")
        elif dilution >= 50:
            score -= 2
            negative.append(f"大攤薄 {dilution:.1f}%")
        elif dilution >= 20:
            score -= 1
            negative.append(f"攤薄偏高 {dilution:.1f}%")
        elif dilution <= 3:
            score += 1
            positive.append(f"攤薄細 {dilution:.1f}%")

    if re.search(r"(償還債務|營運資金|working capital|debt repayment|refinanc|DEBT CAPITALISATION)", text, re.I):
        score -= 1
        negative.append('用途偏補錢/償債')
    if re.search(r"(specific subscriber|strategic|策略|特定認購人|控股股東|connected)", text, re.I):
        score += 1
        positive.append('有特定/策略認購味')

    if not terms_ok and not has_completion_anchor:
        label = '待確認'
        cls = 'supply-watch'
        tradable = False
    elif score >= 4:
        label = '圈股'
        cls = 'supply-stock'
        tradable = True
    elif score >= 2:
        label = '偏圈股'
        cls = 'supply-stock'
        tradable = True
    elif score <= -4:
        label = '圈錢'
        cls = 'supply-cash'
        tradable = False
    elif score <= -2:
        label = '偏圈錢'
        cls = 'supply-cash'
        tradable = False
    else:
        label = '待確認'
        cls = 'supply-watch'
        tradable = False

    if label in ('圈股', '偏圈股') and pending:
        label = '待確認'
        cls = 'supply-watch'
        tradable = False

    if score >= 2:
        basis_parts = positive[:5] + negative[:3] + pending[:2]
    elif score <= -2:
        basis_parts = negative[:5] + positive[:2] + pending[:2]
    else:
        basis_parts = positive[:3] + negative[:3] + pending[:2]
    basis = '；'.join(basis_parts) if basis_parts else '未有足夠除淨/完成後證據'
    return {
        'label': label,
        'cls': cls,
        'score': score,
        'basis': basis,
        'tradable': tradable,
        'positive': positive[:5],
        'negative': negative[:5],
        'pending': pending[:3],
        'year_open': year_open,
    }

def build_comment(p, jump_pct, jump_status):
    stage = announcement_stage(p)
    supply = classify_supply_intent(p, jump_pct, jump_status)
    parts = [f"圈股判斷：{supply['label']}"]
    risks = []

    if stage == '已終止/取消':
        parts.append('唔再當新供股/配股壓力')
        risks.append('已終止/取消')
    elif p.get('terms_carry_forward') and p.get('terms_source_date'):
        parts.append(f"條款沿用 {p.get('terms_source_date')}")
    elif p.get('source') == 'announcement' and not has_extracted_terms(p):
        parts.append('只得公告標題，價格未抽齊')
        risks.append('條款未抽齊')

    if supply.get('basis') and stage != '已終止/取消':
        basis_parts = []
        for bit in str(supply['basis']).split('；'):
            if bit == '價格/攤薄條款未抽齊':
                basis_parts.append('價格條款未抽齊')
            elif '攤薄' not in bit:
                basis_parts.append(bit)
        if basis_parts:
            parts.append('；'.join(basis_parts))

    terms_bits = []
    discount = _safe_num(p.get('discount_pct'))
    if discount is not None:
        if discount < 0:
            terms_bits.append(f"折讓 {abs(discount):.1f}%")
            if discount <= -15:
                risks.append(f"深折讓 {abs(discount):.1f}%")
        elif discount > 0:
            terms_bits.append(f"溢價 {discount:.1f}%")
        else:
            terms_bits.append('平價發行')

    if terms_bits:
        parts.append('條款：' + '／'.join(terms_bits[:3]))

    ann_ret = _safe_num(p.get('announcement_return_pct'))
    if ann_ret is not None and ann_ret <= -10:
        risks.append(f"公告後偏弱 {fmt_pct(ann_ret, signed=True)}")

    current_ret = _safe_num(p.get('current_return_pct'))
    if current_ret is None and jump_status == 'no_data':
        parts.append('價量 raw 未覆蓋，唔作短線判斷')

    if '貸款資本化' in p.get('method', '') or 'DEBT CAPITALISATION' in (p.get('title') or '').upper():
        risks.append('債務資本化')

    # Keep the cell short enough for table scanning, but still explain the call.
    return '；'.join(parts[:9]), risks[:4], supply

def trade_signal(p):
    """Rating = jump status. Discount is NOT used for rating (no evidence)."""
    jump_pct, jump_status = compute_jump(p.get('code', ''), p.get('date_parsed', ''))
    
    pct = _safe_num(p.get('pct_num')) or 0
    thesis, risks, supply = build_comment(p, jump_pct, jump_status)
    stage = announcement_stage(p)
    
    # Jump-based rating
    if stage == '已終止/取消':
        conviction = 0
        signal = '—'
        sig_class = 'trade-wait'
        verdict_text = '已終止/取消'
    elif jump_status == 'jumped':
        conviction = 3
        signal = '🟢 跟!'
        sig_class = 'trade-buy'
        verdict_text = '跳升確認'
    elif jump_status == 'waiting':
        conviction = 1
        signal = '🟡 等'
        sig_class = 'trade-wait'
        verdict_text = '等跳升'
    elif jump_status == 'no_jump':
        conviction = -1
        signal = '🔴 避'
        sig_class = 'trade-avoid'
        verdict_text = '冇跳升'
    else:
        conviction = 0
        signal = '—'
        sig_class = 'trade-wait'
        verdict_text = '數據不足'
    
    if pct > 50:
        conviction -= 1
    
    if '貸款資本化' in p.get('method', ''):
        conviction -= 1
    
    return {
        'conviction': conviction,
        'signal': signal,
        'sig_class': sig_class,
        'verdict_text': verdict_text,
        'thesis': thesis,
        'comment': thesis,
        'supply': supply,
        'risks': risks[:3],
        'jump_8d_pct': jump_pct,
        'jump_status': jump_status,
    }

for p in data:
    p['announcement_stage'] = announcement_stage(p)
    p['category_display'] = display_category(p)
    p['issuer'] = issuer_pressure_score(p)
    p['announcement_return_pct'] = announcement_return(p.get('code'), p.get('date_parsed'))
    p['trade'] = trade_signal(p)
    p['supply'] = p['trade'].get('supply')
    p['jump_8d_pct'] = p['trade'].get('jump_8d_pct')

signals = {}
for p in data:
    s = p['trade']['signal']
    signals[s] = signals.get(s, 0) + 1

print("V4 Signals:")
for s, c in sorted(signals.items()):
    print(f"  {s}: {c}")

# ====== Agent resolve (unchanged) ======
KNOWN_AGENTS = [
    'Guotai Junan', 'KGI Asia', 'Haitong', 'CLSA', 'UBS', 'Citigroup',
    'Goldman Sachs', 'Morgan Stanley', 'Macquarie', 'Futu', 'Tiger Brokers',
    'Zhongtai', 'CMBI', 'CCB International', 'BOC International',
    'Huatai', 'Essence', 'China Merchants', 'Soochow', 'Guosen',
    'Orient Securities', 'Ping An', 'Southwest Securities',
    'CITIC Securities', 'Shenwan Hongyuan', 'Deutsche Bank', 'Nomura',
    'DBS', 'OCBC', 'CGS International', 'Phillip Securities',
    '國泰君安', '海通', '中泰', '建銀', '中銀', '華泰', '國信', '平安',
    '中信証券', '中信里昂', '申萬宏源', '招銀', '光大',
]

def parse_agent_from_text(text):
    if not text: return None
    for agent in KNOWN_AGENTS:
        if agent.lower() in text.lower():
            return agent
    m = re.search(
        r'([A-Z][A-Za-z\s&]+(?:Limited|Ltd|Inc|Securities|Capital|International|Asia|Hong\s*Kong))'
        r'\s+(?:as\s+)?(?:placing\s+agent|sole\s+agent|bookrunner|underwriter)',
        text, re.IGNORECASE
    )
    if m: return m.group(1).strip()
    return None

def resolve_agent(row):
    return (
        row.get('placing_agent')
        or row.get('agent')
        or row.get('vendor')
        or parse_agent_from_text(row.get('method', ''))
        or parse_agent_from_text(row.get('purpose', ''))
    )

filled = 0
for d in data:
    if not d.get('placing_agent'):
        agent = resolve_agent(d)
        if agent:
            d['placing_agent'] = agent
            filled += 1
print(f"Agent resolve: filled {filled} previously null agents")

# ====== GENERATE HTML ======
rights_json_path = os.path.join(DATA_DIR, 'rights_analysis.json')
with open(rights_json_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
print(f"Wrote rights_analysis.json ({len(data)} rows)")
build_stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')

cats = {}
for d in data:
    c = d['category']
    if c not in cats: cats[c] = {'count': 0}
    cats[c]['count'] += 1

g_count = signals.get('🟢 跟!', 0) + signals.get('🟢 跟', 0)
y_count = signals.get('🟡 等', 0)
r_count = signals.get('🔴 避', 0) + signals.get('💀 走', 0)
rights_count = cats.get('供股', {}).get('count', 0)
topup_count = cats.get('先舊後新', {}).get('count', 0)

html = f'''<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta name="robots" content="noindex, nofollow">
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=0.3, maximum-scale=1.0, user-scalable=yes">
<title>供配股跟蹤器 — 8120 Pattern</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, 'Microsoft YaHei', sans-serif; font-size: 12px; }}
.nav {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 8px 12px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; position: sticky; top: 0; z-index: 100; }}
.nav a {{ color: #8b949e; text-decoration: none; padding: 4px 10px; border-radius: 4px; font-size: 11px; white-space: nowrap; }}
.nav a:hover, .nav a.active {{ color: #58a6ff; background: #1f2937; }}
.summary {{ display: flex; gap: 10px; padding: 10px 12px; flex-wrap: wrap; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 14px; min-width: 90px; text-align: center; }}
.card .label {{ font-size: 10px; color: #8b949e; }}
.card .value {{ font-size: 20px; font-weight: bold; margin-top: 2px; }}
.card.buy {{ border-color: #3fb950; }}
.card.buy .value {{ color: #3fb950; }}
.card.wait {{ border-color: #d2991d; }}
.card.wait .value {{ color: #d2991d; }}
.card.avoid {{ border-color: #f85149; }}
.card.avoid .value {{ color: #f85149; }}
.tabs {{ display: flex; gap: 4px; padding: 0 12px 8px; flex-wrap: wrap; }}
.tab {{ padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 11px; background: #21262d; color: #8b949e; border: 1px solid #30363d; }}
.tab:hover, .tab.active {{ background: #1f6feb; color: #fff; border-color: #1f6feb; }}
.tab .count {{ font-size: 10px; opacity: 0.7; margin-left: 3px; }}
.search-box {{ padding: 0 12px 6px; }}
.search-box input {{ background: #161b22; color: #c9d1d9; border: 1px solid #30363d; border-radius: 4px; padding: 5px 10px; font-size: 11px; width: 200px; outline: none; }}
.search-box input:focus {{ border-color: #58a6ff; }}
.table-wrap {{ overflow-x: auto; padding: 0 12px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 11px; min-width: 1200px; }}
th {{ background: #161b22; padding: 6px 8px; text-align: left; border-bottom: 2px solid #30363d; color: #8b949e; font-weight: 600; white-space: nowrap; cursor: pointer; }}
th:hover {{ color: #58a6ff; }}
td {{ padding: 4px 8px; border-bottom: 1px solid #21262d; white-space: nowrap; }}
tr:hover td {{ background: #161b22; }}
.badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }}
.badge-供股 {{ background: #da3633; color: #fff; }}
.badge-配售 {{ background: #1f6feb; color: #fff; }}
.badge-代價發行 {{ background: #3fb950; color: #000; }}
.badge-先舊後新 {{ background: #d2991d; color: #000; }}
.signal {{ font-weight: 700; font-size: 12px; padding: 3px 8px; border-radius: 4px; text-align: center; display: inline-block; min-width: 55px; }}
.trade-buy {{ background: #1a3a1a; color: #3fb950; border: 1px solid #3fb950; }}
.trade-wait {{ background: #3a2e0a; color: #d2991d; border: 1px solid #d2991d; }}
.trade-avoid {{ background: #3a1111; color: #f85149; border: 1px solid #f85149; }}
.conviction {{ display: inline-flex; gap: 2px; }}
.conviction span {{ font-size: 14px; }}
.issuer-badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 700; }}
.issuer-high {{ background: #3a1111; color: #f85149; border: 1px solid #f85149; }}
.issuer-neutral {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
.issuer-low {{ background: #1a3a1a; color: #3fb950; border: 1px solid #3fb950; }}
.issuer-stack {{ display:flex; flex-direction:column; gap:3px; }}
.issuer-react-up {{ background: #122b18; color: #3fb950; border: 1px solid #3fb950; }}
.issuer-react-neutral {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
.issuer-react-down {{ background: #3a1111; color: #f85149; border: 1px solid #f85149; }}
.supply-stock {{ background: #122b18; color: #3fb950; border: 1px solid #3fb950; }}
.supply-cash {{ background: #3a1111; color: #f85149; border: 1px solid #f85149; }}
.supply-watch {{ background: #3a2e0a; color: #d2991d; border: 1px solid #d2991d; }}
.supply-ended {{ background: #21262d; color: #8b949e; border: 1px solid #30363d; }}
.year-open-up {{ background: #122b18; color: #3fb950; border: 1px solid #3fb950; }}
.year-open-down {{ background: #3a1111; color: #f85149; border: 1px solid #f85149; }}
.year-open-mixed {{ background: #1f2937; color: #d2a8ff; border: 1px solid #6e40c9; }}
.year-open-missing {{ background: #21262d; color: #8b949e; border: 1px solid #30363d; }}
.year-open-col {{ min-width:74px; line-height:1.25; white-space:normal; font-size:10px; }}
.year-open-col .year {{ display:block; color:#8b949e; }}
.year-open-col .price {{ display:block; color:#c9d1d9; }}
.year-open-col .dist {{ display:block; font-weight:700; }}
.year-open-col .up {{ color:#3fb950; }}
.year-open-col .dn {{ color:#f85149; }}
.year-open-col .missing {{ color:#8b949e; }}
.thesis {{ max-width: 280px; overflow: hidden; text-overflow: ellipsis; color: #8b949e; font-size: 10px; white-space: normal; }}
.risk {{ color: #f85149; font-size: 10px; }}
.jump-green {{ color: #3fb950; font-weight: bold; }}
.jump-gray {{ color: #484f58; }}
.jump-wait {{ color: #d2991d; }}
.footer {{ padding: 12px; text-align: center; color: #484f58; font-size: 10px; border-top: 1px solid #21262d; margin-top: 10px; line-height: 1.6; }}
@media (max-width: 720px) {{
  body {{ font-size: 10px; }}
  .summary {{ gap: 6px; padding: 6px; }}
  .card {{ min-width: 55px; padding: 6px 8px; }}
  .card .value {{ font-size: 14px; }}
  th, td {{ padding: 3px 4px; font-size: 10px; }}
  table {{ min-width: 800px; }}
}}
</style>
</head>
<body>

<div class="nav">
  <a href="index.html">🇭🇰 港股版</a>
  <a href="watchlist.html">⭐ 自選</a>
  <a href="history.html">🕐 歷史</a>
  <a href="gap_fvg.html">⤴ Gap/FVG</a>
  <a href="fundflow.html">💰 資金</a>
  <a href="rights_analysis.html" class="active">📋 供配股</a>
  <a href="docs/ccass-warroom.html">⚡ 戰情室</a>
  <a href="guide.html">📖 說明書</a>
</div>

<div class="summary" id="rightsSummary">
  <div class="card buy"><div class="label">🟢 跟</div><div class="value">{g_count}</div></div>
  <div class="card wait"><div class="label">🟡 等</div><div class="value">{y_count}</div></div>
  <div class="card avoid"><div class="label">🔴 避</div><div class="value">{r_count}</div></div>
  <div class="card"><div class="label">💡 核心理念</div><div class="value" style="font-size:10px;color:#58a6ff;line-height:1.5">配售本體 -EV (median -11.8%, 62%輸錢)<br>唯一實證: 配售後5日內收市升穿+8%=跳升確認<br>跳升組 16% 60日內翻倍, 係冇跳組 2.4x</div></div>
</div>

<div class="tabs">
  <div class="tab active" onclick="filter('all')">全部<span class="count">{len(data)}</span></div>
  <div class="tab" onclick="filter('🟢')">🟢 跟<span class="count">{g_count}</span></div>
  <div class="tab" onclick="filter('🟡')">🟡 等<span class="count">{y_count}</span></div>
  <div class="tab" onclick="filter('🔴')">🔴 避<span class="count">{r_count}</span></div>
  <div class="tab" onclick="filter('供股')">供股<span class="count">{rights_count}</span></div>
  <div class="tab" onclick="filter('先舊後新')">先舊後新<span class="count">{topup_count}</span></div>
</div>

<div class="search-box">
  <input type="text" placeholder="🔍 股票代碼或名稱..." oninput="doSearch(this)">
</div>

<div class="table-wrap">
<table id="mainTable">
<thead>
<tr>
  <th onclick="sortTable(0)">日期</th>
  <th onclick="sortTable(1)">代碼</th>
  <th onclick="sortTable(2)">名稱</th>
  <th onclick="sortTable(3)">類別</th>
  <th onclick="sortTable(4)">配售價</th>
  <th onclick="sortTable(5)">市價</th>
  <th onclick="sortTable(6)">折讓</th>
  <th onclick="sortTable(7)">🚀跳升</th>
  <th onclick="sortTable(8)">攤薄</th>
  <th onclick="sortTable(9)">訊號</th>
  <th onclick="sortTable(10)">公告拆解</th>
  <th onclick="sortTable(11)">YO</th>
  <th onclick="sortTable(12)">PY</th>
  <th onclick="sortTable(13)">現價對發行價</th>
  <th onclick="sortTable(14)">公告日至今</th>
  <th>邏輯</th>
</tr>
</thead>
<tbody id="tableBody"><tr><td colspan="16" style="padding:18px;color:#8b949e">⏳ 載入數據中…</td></tr></tbody>
</table>
</div>

<div class="footer">
  📊 402條配售真實統計: median 事後% -11.8% · 62% 輸錢 · 6.5% 升超過100%<br>跳升確認後: &gt;100% 比率 16%（vs 冇跳升 7%）｜ 數據: 自家 track_outcomes 每日回填<br>⚠️ 08120 (+318%) 係 6.5% 嘅倖存者，唔係常態
</div>

<script>
let DATA = [];
let DATA_READY = false;
const DATA_URL = 'data/rights_analysis.json?v={build_stamp}';

function fmtAmt(n) {{
  if (n >= 1e8) return (n/1e8).toFixed(1)+'億';
  if (n >= 1e7) return (n/1e7).toFixed(0)+'千萬';
  return n ? String(n) : '-';
}}

const AGENT_KEYWORDS = ['Guotai','KGI','Haitong','CLSA','UBS','Citi',
  'Goldman','Morgan','Macquarie','Futu','Tiger','CMBI','CCB','BOC',
  'Huatai','Essence','Ping An','CITIC','Shenwan','Hongyuan','Deutsche',
  'Nomura','DBS','OCBC','Soochow','Guosen','國泰','海通','中銀','建銀','華泰','平安',
  '中信','申萬','宏源','興證','招銀','光大'];

function extractAgentFromName(text) {{
  if (!text) return null;
  for (const kw of AGENT_KEYWORDS) {{
    if (text.toLowerCase().includes(kw.toLowerCase())) return kw;
  }}
  return null;
}}

function esc(v) {{
  return String(v ?? '').replace(/[&<>"']/g, ch => ({{
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }}[ch]));
}}

function fmtOpenPrice(v) {{
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return '--';
  return n < 1 ? n.toFixed(3) : n.toFixed(2);
}}

function getYearOpenLevel(yearOpen, idx) {{
  const levels = Array.isArray(yearOpen && yearOpen.levels) ? yearOpen.levels : [];
  const targets = Array.isArray(yearOpen && yearOpen.target_years) ? yearOpen.target_years : [];
  const targetYear = targets.length ? Number(targets[idx]) : Number(levels[idx] && levels[idx].year);
  const byYear = new Map();
  levels.forEach(level => {{
    const year = Number(level && level.year);
    if (Number.isFinite(year)) byYear.set(year, level);
  }});
  if (Number.isFinite(targetYear)) return byYear.get(targetYear) || null;
  return levels[idx] || null;
}}

function formatSignedPct(v) {{
  const n = Number(v);
  if (!Number.isFinite(n)) return '--';
  return (n > 0 ? '+' : '') + n.toFixed(1) + '%';
}}

function formatYearOpenCell(yearOpen, idx) {{
  const label = idx === 0 ? 'YO' : 'PY';
  const level = getYearOpenLevel(yearOpen, idx);
  if (!level) return '<span class="missing">' + label + '<br>--</span>';
  const cls = level.status === 'above' ? 'up' : (level.status === 'below' ? 'dn' : 'missing');
  return '<span class="year">' + label + ' ' + esc(level.year || '') + '</span>' +
    '<span class="price">' + fmtOpenPrice(level.open) + '</span>' +
    '<span class="dist ' + cls + '">' + formatSignedPct(level.distance_pct) + '</span>';
}}

function yearOpenDistance(row, idx) {{
  const trade = row.trade || {{}};
  const supply = row.supply || trade.supply || {{}};
  const level = getYearOpenLevel(supply.year_open || null, idx);
  const dist = Number(level && level.distance_pct);
  return Number.isFinite(dist) ? dist : null;
}}

function updateRightsSummary(rows) {{
  let follow = 0, wait = 0, avoid = 0;
  rows.forEach(r => {{
    const sig = ((r.trade||{{}}).signal || '').toString();
    if (sig.includes('跟')) follow++;
    else if (sig.includes('避') || sig.includes('💀')) avoid++;
    else wait++;
  }});
  const el = document.getElementById('rightsSummary');
  if (el) {{
    el.innerHTML =
      '<span class="tag green">🟢 跟 ' + follow + '</span>' +
      '<span class="tag yellow">🟡 等 ' + wait + '</span>' +
      '<span class="tag red">🔴 避 ' + avoid + '</span>' +
      '<span class="tag gray">全部 ' + rows.length + '</span>';
  }}
}}

function render(rows) {{
  document.getElementById('tableBody').innerHTML = rows.map(d => {{
    let t = d.trade || {{}};
    let mp = d.market_price > 0 ? d.market_price.toFixed(2) : '-';
    let disc = d.discount_pct != null ? (d.discount_pct <= 0 ? d.discount_pct+'%' : '+'+d.discount_pct+'%') : '-';
    let discStyle = '';
    if (d.discount_pct != null) {{
      if (d.discount_pct <= -15) discStyle = 'color:#d2991d';
      else if (d.discount_pct <= 0) discStyle = 'color:#8b949e';
      else discStyle = 'color:#f85149';
    }}
    
    // Jump column
    let jumpHtml = '';
    let jp = d.jump_8d_pct;
    let js = t.jump_status || 'no_data';
    if (js === 'jumped') jumpHtml = '<span class="jump-green">🚀 +' + jp.toFixed(1) + '%</span>';
    else if (js === 'waiting') jumpHtml = '<span class="jump-wait">⏳ ' + (jp != null ? '+' + jp.toFixed(1) + '%' : '—') + '</span>';
    else if (js === 'no_jump') jumpHtml = '<span class="jump-gray">✗ +' + (jp != null ? jp.toFixed(1) : '0') + '%</span>';
    else jumpHtml = '<span class="jump-gray">—</span>';
    const issuer = d.issuer || {{score: 50, label: '中性', cls: 'issuer-neutral', shareholder_pressure: {{score: 50, label: '中性', cls: 'issuer-neutral'}}, reaction: {{pct: null, label: '未足夠數據', cls: 'issuer-react-neutral'}}}};
    const shareholder = issuer.shareholder_pressure || {{score: issuer.score || 50, label: issuer.label || '中性', cls: issuer.cls || 'issuer-neutral'}};
    const reaction = issuer.reaction || {{pct: null, label: '未足夠數據', cls: 'issuer-react-neutral'}};
    const supply = d.supply || t.supply || {{label: '待確認', cls: 'supply-watch', basis: '未有足夠除淨/完成後證據'}};
    const yearOpen = supply.year_open || {{badge: '不足', cls: 'year-open-missing', summary: '今年/前年年開線不足'}};
    const yoCell = formatYearOpenCell(yearOpen, 0);
    const pyCell = formatYearOpenCell(yearOpen, 1);
    const reactionPct = reaction.pct != null ? (reaction.pct >= 0 ? '+' : '') + reaction.pct.toFixed(1) + '%' : '—';
    const annRet = d.announcement_return_pct != null ? d.announcement_return_pct : null;
    const annRetPct = annRet != null ? (annRet >= 0 ? '+' : '') + annRet.toFixed(1) + '%' : '—';
    
    // 現價對發行價 = latest raw close vs issue price (not stale placements_enriched current_return_pct)
    let ret = null;
    if (d.manual_return_pct != null) {{
      ret = d.manual_return_pct;
    }} else {{
      const latestPx = d.latest_price;
      if (latestPx != null && d.price_num > 0) {{
        ret = (latestPx / d.price_num - 1) * 100;
      }} else if (d.current_return_pct != null) {{
        ret = d.current_return_pct;
      }}
    }}
    
    let risks = (t.risks||[]).map(r => '<div class="risk">'+esc(r)+'</div>').join('');
    let comment = t.comment || t.thesis || '';
    const categoryText = d.category_display || d.category || '';
    const stageText = d.announcement_stage || '未分類';
    const termsSource = d.terms_source_date ? '<span class="issuer-badge issuer-neutral">條款 ' + esc(d.terms_source_date) + '</span>' : '';
    
    return `<tr>
      <td>${{d.date}}</td>
      <td>${{d.code}}</td>
      <td>${{d.name}}</td>
      <td><span class="badge badge-${{d.category}}">${{esc(categoryText)}}</span></td>
      <td>${{d.price}}</td>
      <td>${{mp}}</td>
      <td style="${{discStyle}}">${{disc}}</td>
      <td>${{jumpHtml}}</td>
      <td>${{d.pct_num > 0 ? d.pct_num.toFixed(1)+'%' : '-'}}</td>
      <td><span class="signal ${{t.sig_class||''}}">${{t.signal||'➖'}}</span></td>
      <td>
        <div class="issuer-stack" title="公告拆解只顯示階段與分數；圈股/圈錢原因放右邊邏輯欄；YO/PY 另外用獨立欄排序">
          <span class="issuer-badge issuer-neutral">階段 ${{esc(stageText)}}</span>
          ${{termsSource}}
          <span class="issuer-badge ${{issuer.cls}}">發行方有利度 ${{issuer.label}} ${{issuer.score}}</span>
          <span class="issuer-badge ${{shareholder.cls}}">股東短期壓力 ${{shareholder.label}} ${{shareholder.score}}</span>
          <span class="issuer-badge ${{reaction.cls}}">公告後價格反應 ${{reactionPct}} ${{reaction.label}}</span>
        </div>
      </td>
      <td class="year-open-col" title="${{esc(yearOpen.summary || '')}}">${{yoCell}}</td>
      <td class="year-open-col" title="${{esc(yearOpen.summary || '')}}">${{pyCell}}</td>
      <td style="color:${{(ret||0) >= 0 ? '#3fb950' : '#f85149'}};font-weight:${{Math.abs(ret||0) > 20 ? 'bold' : 'normal'}}">${{ret != null ? (ret >= 0 ? '+' : '') + ret.toFixed(1) + '%' : '-'}}</td>
      <td style="color:${{(annRet||0) >= 0 ? '#3fb950' : '#f85149'}};font-weight:${{Math.abs(annRet||0) > 20 ? 'bold' : 'normal'}}">${{annRet != null ? annRetPct : '-'}}</td>
      <td>
        <div class="thesis">${{esc(comment)}}</div>
        ${{risks}}
      </td>
    </tr>`;
  }}).join('');
  updateRightsSummary(rows);
}}

let searchTerm = '';
let currentFilter = 'all';

function getFilteredRows() {{
  let rows = DATA;
  if (currentFilter !== 'all') {{
    if (currentFilter === '🟢')
      rows = rows.filter(d => (d.trade||{{}}).signal.startsWith('🟢'));
    else if (currentFilter === '🟡')
      rows = rows.filter(d => (d.trade||{{}}).signal.startsWith('🟡'));
    else if (currentFilter === '🔴')
      rows = rows.filter(d => (d.trade||{{}}).signal.startsWith('🔴') || (d.trade||{{}}).signal.startsWith('💀'));
    else
      rows = rows.filter(d => d.category === currentFilter);
  }}
  if (searchTerm) {{
    let s = searchTerm.toLowerCase();
    rows = rows.filter(d => d.code.includes(s) || d.name.toLowerCase().includes(s));
  }}
  return rows;
}}

function doSearch(el) {{
  searchTerm = el.value.trim();
  if (!DATA_READY) return;
  render(getFilteredRows());
}}

function filter(cat) {{
  currentFilter = cat;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  if (!DATA_READY) return;
  render(getFilteredRows());
}}

let sortCol = 7; let sortAsc = false;
function compareNumberMissingLast(va, vb) {{
  const aOk = Number.isFinite(va);
  const bOk = Number.isFinite(vb);
  if (!aOk && !bOk) return 0;
  if (!aOk) return 1;
  if (!bOk) return -1;
  return sortAsc ? va - vb : vb - va;
}}

function sortTable(col) {{
  sortAsc = sortCol === col ? !sortAsc : false;
  sortCol = col;
  if (!DATA_READY) return;
  let rows = getFilteredRows();
  const keys = ['date_parsed','code','name','category','price_num','market_price','discount_pct','jump_8d_pct','pct_num','trade.signal','issuer.score','yo_distance','py_distance','current_return_pct','announcement_return_pct'];
  rows.sort((a,b) => {{
    let va, vb;
    if (col === 7) {{ va = a.jump_8d_pct != null ? a.jump_8d_pct : (a.trade||{{}}).jump_status==='waiting' ? 999 : -999; vb = b.jump_8d_pct != null ? b.jump_8d_pct : (b.trade||{{}}).jump_status==='waiting' ? 999 : -999; }}
    else if (col === 6) {{ va = a.discount_pct != null ? a.discount_pct : 999; vb = b.discount_pct != null ? b.discount_pct : 999; }}
    else if (col === 10) {{ va = (a.issuer || {{score: 50}}).score; vb = (b.issuer || {{score: 50}}).score; }}
    else if (col === 11) {{ return compareNumberMissingLast(yearOpenDistance(a, 0), yearOpenDistance(b, 0)); }}
    else if (col === 12) {{ return compareNumberMissingLast(yearOpenDistance(a, 1), yearOpenDistance(b, 1)); }}
    else if (col === 5) {{ va = a.market_price||0; vb = b.market_price||0; }}
    else if (col === 9) {{
      const order = {{'🟢 跟!': 0, '🟢 跟': 0, '🟡 等': 1, '🔴 避': 2, '💀 走': 3, '—': 4, '': 4}};
      const as = (a.trade||{{}}).signal || '—';
      const bs = (b.trade||{{}}).signal || '—';
      va = order[as] != null ? order[as] : 4;
      vb = order[bs] != null ? order[bs] : 4;
    }}
    else if (col === 13) {{ va = a.current_return_pct != null ? a.current_return_pct : -999; vb = b.current_return_pct != null ? b.current_return_pct : -999; }}
    else if (col === 14) {{ va = a.announcement_return_pct != null ? a.announcement_return_pct : -999; vb = b.announcement_return_pct != null ? b.announcement_return_pct : -999; }}
    else {{ va = a[keys[col]]||''; vb = b[keys[col]]||''; }}
    if (typeof va === 'number') return sortAsc ? va - vb : vb - va;
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  }});
  render(rows);
}}

async function loadData() {{
  try {{
    const res = await fetch(DATA_URL, {{cache: 'no-store'}});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    DATA = await res.json();
    DATA_READY = true;
    render(DATA);
  }} catch (err) {{
    const body = document.getElementById('tableBody');
    if (body) body.innerHTML = '<tr><td colspan="16" style="padding:18px;color:#f85149">載入失敗：' + err.message + '</td></tr>';
  }}
}}

loadData();
</script>
</body>
</html>'''

with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rights_analysis.html'), 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Generated rights_analysis.html ({len(html)} bytes)")
