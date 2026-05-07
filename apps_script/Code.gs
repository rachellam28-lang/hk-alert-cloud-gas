const SPREADSHEET_ID = '129IieKTIfssX18O_PfnRoxbx3c12UoCPQ_MxxBizgeA';
const ALERT_SHEET = 'Alerts';

// GAS_SECRET is read from Script Properties at runtime; never hardcode it here.
// In Apps Script editor: Project Settings → Script Properties → add key "GAS_SECRET".
function getGasSecret_() {
  try {
    return PropertiesService.getScriptProperties().getProperty('GAS_SECRET') || '';
  } catch (err) {
    return '';
  }
}

const HEADERS = [
  'created_at', 'source', 'category', 'code', 'symbol', 'name', 'signal',
  'timeframe', 'price', 'message', 'strategy', 'chart_url', 'source_url',
  'tags', 'poc_6m', 'poc_12m', 'priority', 'raw'
];

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');
    const expected = getGasSecret_();
    if (expected && payload.secret !== expected) {
      return json_({ ok: false, error: 'secret_mismatch' });
    }
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sh = ensureSheet_(ss);
    const row = HEADERS.map(h => {
      if (h === 'created_at') return payload.created_at || new Date().toISOString();
      if (h === 'tags' && Array.isArray(payload.tags)) return payload.tags.join(',');
      if (h === 'raw') return payload.raw || JSON.stringify(payload);
      return payload[h] == null ? '' : payload[h];
    });
    sh.appendRow(row);
    return json_({ ok: true });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function doGet() {
  const alerts = getAlerts_();
  const snap = getMarketSnapshot_();
  return HtmlService.createHtmlOutput(render_(alerts, snap))
    .setTitle('Signal Dashboard Pro')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function ensureSheet_(ss) {
  let sh = ss.getSheetByName(ALERT_SHEET);
  if (!sh) sh = ss.insertSheet(ALERT_SHEET);
  const first = sh.getRange(1, 1, 1, HEADERS.length).getValues()[0];
  if (first.join('') === '') {
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
    sh.setFrozenRows(1);
  }
  return sh;
}

function getAlerts_() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sh = ensureSheet_(ss);
  const values = sh.getDataRange().getValues();
  if (values.length <= 1) return [];
  const headers = values[0].map(String);
  return values.slice(1).map(r => {
    const o = {};
    headers.forEach((h, i) => o[h] = r[i]);
    return o;
  }).reverse().slice(0, 500);
}

function fetchYahoo_(symbol) {
  try {
    const url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(symbol) + '?interval=1d&range=30d';
    const json = JSON.parse(UrlFetchApp.fetch(url, { muteHttpExceptions: true }).getContentText());
    const r = json.chart.result[0];
    const meta = r.meta;
    const last = meta.regularMarketPrice;
    const prev = meta.chartPreviousClose || meta.previousClose;
    const change = (last != null && prev) ? last - prev : null;
    const changePct = (change != null && prev) ? change / prev * 100 : null;
    let series = [];
    try {
      const closes = r.indicators && r.indicators.quote && r.indicators.quote[0] && r.indicators.quote[0].close;
      if (Array.isArray(closes)) {
        series = closes.filter(function (v) { return v != null && !isNaN(v); }).slice(-20);
      }
    } catch (innerErr) { series = []; }
    return { value: last, change: change, changePct: changePct, source: 'Yahoo (' + symbol + ')', stale: false, series: series };
  } catch (err) {
    return { value: null, change: null, changePct: null, source: 'Yahoo (' + symbol + ')', stale: true, series: [] };
  }
}

function getHsiPe_() {
  try {
    const html = UrlFetchApp.fetch('https://worldperatio.com/area/hong-kong/', { muteHttpExceptions: true }).getContentText();
    const m = html.match(/Hong Kong Stock Market[\s\S]{0,600}?P\/E Ratio[\s\S]{0,300}?(\d{1,3}\.\d{1,2})/i)
      || html.match(/Hong Kong Stock Market[\s\S]{0,600}?(\d{1,3}\.\d{1,2})/i)
      || html.match(/P\/E Ratio[\s\S]{0,300}?(\d{1,3}\.\d{1,2})/i);
    return { value: m ? Number(m[1]) : null, change: null, changePct: null, source: 'World PE Ratio', stale: !m, series: [] };
  } catch (err) {
    return { value: null, change: null, changePct: null, source: 'World PE Ratio', stale: true, series: [] };
  }
}

function getMarketSnapshot_() {
  return {
    hsi: fetchYahoo_('^HSI'),
    hsi_pe: getHsiPe_(),
    dxy: fetchYahoo_('DX-Y.NYB'),
    vix: fetchYahoo_('^VIX'),
    updated_at: new Date().toISOString()
  };
}

function n_(v, d) {
  if (v == null || v === '' || isNaN(Number(v))) return '—';
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

function esc_(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
  });
}

function fmtTime_(s) {
  if (!s) return '—';
  try {
    const d = new Date(s);
    if (isNaN(d.getTime())) return String(s);
    const pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
      + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  } catch (err) {
    return String(s);
  }
}

function fmtDate_(s) {
  if (!s) return '—';
  try {
    const d = new Date(s);
    if (isNaN(d.getTime())) return String(s);
    const pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  } catch (err) {
    return String(s);
  }
}

function sparkline_(series, up) {
  if (!series || series.length < 2) return '';
  const w = 96, h = 28, pad = 2;
  let min = Infinity, max = -Infinity;
  for (let i = 0; i < series.length; i++) {
    const v = series[i];
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === max) { min -= 1; max += 1; }
  const stepX = (w - pad * 2) / (series.length - 1);
  const coords = series.map(function (v, i) {
    const x = pad + i * stepX;
    const y = pad + (h - pad * 2) * (1 - (v - min) / (max - min));
    return [x, y];
  });
  const pts = coords.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ');
  const stroke = up ? '#16a34a' : '#dc2626';
  const fill = up ? 'rgba(22,163,74,0.10)' : 'rgba(220,38,38,0.10)';
  const area = pts + ' ' + (pad + (series.length - 1) * stepX).toFixed(1) + ',' + (h - pad).toFixed(1) + ' ' + pad.toFixed(1) + ',' + (h - pad).toFixed(1);
  return '<svg class="spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
    + '<polygon points="' + area + '" fill="' + fill + '" stroke="none"/>'
    + '<polyline fill="none" stroke="' + stroke + '" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" points="' + pts + '"/>'
    + '</svg>';
}

function kpi_(label, hint, item, decimals) {
  const v = n_(item.value, decimals);
  let chgHtml = '';
  let up = null;
  if (item.changePct != null && !isNaN(item.changePct)) {
    up = item.changePct >= 0;
    const arrow = up
      ? '<svg class="tri" viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M1 8 L5 2 L9 8 Z" fill="currentColor"/></svg>'
      : '<svg class="tri" viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M1 2 L9 2 L5 8 Z" fill="currentColor"/></svg>';
    chgHtml = '<span class="kchg ' + (up ? 'up' : 'down') + '">' + arrow
      + '<span class="kchgnum">' + n_(Math.abs(item.changePct), 2) + '%</span></span>';
  }
  // Sparkline tone follows series direction (first→last) when available, else changePct sign.
  let sparkUp = up == null ? true : up;
  if (item.series && item.series.length >= 2) {
    sparkUp = item.series[item.series.length - 1] >= item.series[0];
  }
  const spark = sparkline_(item.series || [], sparkUp);
  const stale = item.stale ? '<span class="stale">stale</span>' : '';
  return '<div class="kpi">'
    + '<div class="krow">'
    + '<div class="klabels"><div class="klabel">' + esc_(label) + '</div>'
    + '<div class="khint">' + esc_(hint) + '</div></div>'
    + stale
    + '</div>'
    + '<div class="kmain">'
    + '<div class="kvalue">' + v + '</div>'
    + (chgHtml || '<span class="kchg flat">—</span>')
    + '</div>'
    + '<div class="kfoot">' + spark + '<div class="ksource">' + esc_(item.source) + '</div></div>'
    + '</div>';
}

// --- Corp action helpers (HKEX disclosure) ---
function corpType_(a) {
  // Look at tags first then signal text. Returns 'placement' | 'increase' | 'rights' | 'other'.
  const tags = String(a.tags || '');
  const sig = String(a.signal || '') + ' ' + String(a.message || '');
  const blob = (tags + ' ' + sig);
  if (/股東增持|增持/.test(blob)) return 'increase';
  if (/配股|配售|認購新股|發行股份|認購事項/.test(blob)) return 'placement';
  if (/供股|公開發售/.test(blob)) return 'rights';
  return 'other';
}

function corpTypeLabel_(t) {
  if (t === 'placement') return '配股';
  if (t === 'increase') return '增持';
  if (t === 'rights') return '供股';
  return '公告';
}

function render_(alerts, snap) {
  // Split alerts.
  const corpAlerts = [];
  const techAlerts = [];
  alerts.forEach(function (a) {
    if (a.category === 'corp_action') corpAlerts.push(a);
    else techAlerts.push(a);
  });

  // Corp counts.
  let cntPlacement = 0, cntIncrease = 0, cntRights = 0;
  const corpRows = corpAlerts.map(function (a) {
    const t = corpType_(a);
    if (t === 'placement') cntPlacement++;
    else if (t === 'increase') cntIncrease++;
    else if (t === 'rights') cntRights++;
    const link = a.source_url || a.chart_url || '';
    const codeStr = String(a.code || '').trim();
    const tv = codeStr ? 'https://www.tradingview.com/chart/?symbol=HKEX%3A' + encodeURIComponent(codeStr.replace(/^0+/, '')) : '';
    return ''
      + '<tr class="crow" data-type="' + t + '" data-code="' + esc_(codeStr) + '" data-name="' + esc_(a.name || '') + '">'
      + '<td class="cell-code"><div class="code">' + esc_(codeStr || '—') + '</div><div class="name">' + esc_(a.name || '') + '</div></td>'
      + '<td><span class="cpill cpill-' + t + '">' + corpTypeLabel_(t) + '</span></td>'
      + '<td class="cell-msg">' + esc_(a.message || a.signal || '') + '</td>'
      + '<td class="cell-time">' + esc_(fmtTime_(a.created_at)) + '</td>'
      + '<td class="cell-link">'
      + (link ? '<a href="' + esc_(link) + '" target="_blank" rel="noopener">原文</a>' : '')
      + (tv ? ' · <a href="' + esc_(tv) + '" target="_blank" rel="noopener">TV</a>' : '')
      + '</td>'
      + '</tr>';
  }).join('');

  // Group technical signals by code.
  const groupsMap = {};
  techAlerts.forEach(function (a) {
    const code = String(a.code || '').trim() || '—';
    if (!groupsMap[code]) {
      groupsMap[code] = { code: code, name: String(a.name || ''), items: [] };
    }
    if (!groupsMap[code].name && a.name) groupsMap[code].name = String(a.name);
    groupsMap[code].items.push(a);
  });
  const techGroups = Object.keys(groupsMap).map(function (k) { return groupsMap[k]; });
  techGroups.sort(function (a, b) {
    const ta = a.items[0] && a.items[0].created_at ? new Date(a.items[0].created_at).getTime() : 0;
    const tb = b.items[0] && b.items[0].created_at ? new Date(b.items[0].created_at).getTime() : 0;
    return tb - ta;
  });

  const techRows = techGroups.map(function (g) {
    const last = g.items[0] || {};
    const codeStr = String(g.code || '').trim();
    const tv = codeStr && codeStr !== '—'
      ? 'https://www.tradingview.com/chart/?symbol=HKEX%3A' + encodeURIComponent(codeStr.replace(/^0+/, ''))
      : '';
    // Up to 4 recent unique signal labels as pills.
    const seen = {};
    const pills = [];
    for (let i = 0; i < g.items.length && pills.length < 4; i++) {
      const a = g.items[i];
      const label = String(a.signal || a.category || '').trim() || '訊號';
      if (seen[label]) continue;
      seen[label] = true;
      const link = a.chart_url || a.source_url || '';
      const pillBody = '<span class="spill">' + esc_(label) + '</span>';
      pills.push(link
        ? '<a class="splink" href="' + esc_(link) + '" target="_blank" rel="noopener">' + pillBody + '</a>'
        : pillBody);
    }
    const lastDate = fmtDate_(last.created_at);
    const lastTime = fmtTime_(last.created_at);
    return ''
      + '<tr class="trow" data-code="' + esc_(codeStr) + '" data-name="' + esc_(g.name) + '" data-date="' + esc_(lastDate) + '">'
      + '<td class="cell-code"><div class="code">' + esc_(codeStr) + '</div><div class="name">' + esc_(g.name) + '</div></td>'
      + '<td class="cell-num">' + g.items.length + '</td>'
      + '<td class="cell-pills">' + pills.join(' ') + '</td>'
      + '<td class="cell-link">' + (tv ? '<a href="' + esc_(tv) + '" target="_blank" rel="noopener">TradingView</a>' : '—') + '</td>'
      + '<td class="cell-time">' + esc_(lastTime) + '</td>'
      + '</tr>';
  }).join('');

  const corpEmpty = corpAlerts.length === 0
    ? '<tr><td colspan="5" class="empty">暫無披露易公告</td></tr>'
    : '';
  const techEmpty = techGroups.length === 0
    ? '<tr><td colspan="5" class="empty">暫無技術信號</td></tr>'
    : '';

  return '<!doctype html>\n'
    + '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
    + '<meta http-equiv="refresh" content="120">\n'
    + '<title>Signal Dashboard Pro</title>\n'
    + '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    + '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    + '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">\n'
    + '<style>\n'
    + ':root{'
    + '--bg:#f5f7fa;--surface:#ffffff;--surface-soft:#f8fafc;'
    + '--text:#0f172a;--text-soft:#334155;--mute:#64748b;--mute-2:#94a3b8;'
    + '--line:#e2e8f0;--line-soft:#eef1f6;'
    + '--primary:#0284c7;--primary-soft:#e0f2fe;--primary-border:#bae6fd;'
    + '--up:#15803d;--up-soft:#dcfce7;--up-border:#86efac;'
    + '--down:#b91c1c;--down-soft:#fee2e2;--down-border:#fca5a5;'
    + '--violet:#6d28d9;--violet-soft:#ede9fe;--violet-border:#c4b5fd;'
    + '--amber:#b45309;--amber-soft:#fef3c7;--amber-border:#fcd34d;'
    + '--font-sans:Inter,system-ui,-apple-system,"PingFang TC","Noto Sans TC",Arial,sans-serif;'
    + '--font-mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;'
    + '--radius:10px;--shadow:0 1px 2px rgba(15,23,42,.04),0 1px 1px rgba(15,23,42,.03)}\n'
    + '*{box-sizing:border-box}html,body{margin:0;padding:0}\n'
    + 'body{background:var(--bg);color:var(--text);font:14px/1.55 var(--font-sans);-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}\n'
    + 'a{color:var(--primary);text-decoration:none}a:hover{text-decoration:underline}\n'
    + '.tabular{font-variant-numeric:tabular-nums}\n'
    + /* Header */
    '.topbar{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.85);backdrop-filter:saturate(180%) blur(8px);-webkit-backdrop-filter:saturate(180%) blur(8px);border-bottom:1px solid var(--line)}\n'
    + '.topbar-inner{max-width:1440px;margin:0 auto;padding:10px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px}\n'
    + '.brand{display:flex;align-items:center;gap:10px;min-width:0}\n'
    + '.brand .logo{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,#0284c7,#0ea5e9);display:flex;align-items:center;justify-content:center;color:#fff;flex-shrink:0}\n'
    + '.brand .logo svg{display:block}\n'
    + '.brand-meta{display:flex;flex-direction:column;min-width:0}\n'
    + '.brand-title{font-size:14px;font-weight:600;color:var(--text);letter-spacing:-.01em;white-space:nowrap}\n'
    + '.brand-sub{font-size:10px;font-weight:600;color:var(--mute);text-transform:uppercase;letter-spacing:.18em;white-space:nowrap}\n'
    + '.topright{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--mute);white-space:nowrap}\n'
    + '.dot{width:7px;height:7px;border-radius:999px;background:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.18)}\n'
    + '.refresh-tag{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:999px;background:var(--surface);border:1px solid var(--line);font-size:11px;color:var(--text-soft)}\n'
    + /* Layout */
    '.wrap{max-width:1440px;margin:0 auto;padding:18px 20px 36px}\n'
    + '.section-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:20px 0 10px}\n'
    + '.section-head h2{margin:0;display:flex;align-items:center;gap:8px;font-size:11px;font-weight:600;color:var(--mute);text-transform:uppercase;letter-spacing:.16em}\n'
    + '.section-head h2 .ico{display:inline-flex;width:18px;height:18px;border-radius:6px;background:var(--primary-soft);color:var(--primary);align-items:center;justify-content:center}\n'
    + /* KPI cards */
    '.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}\n'
    + '.kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 14px 12px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:8px}\n'
    + '.kpi .krow{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}\n'
    + '.klabels{display:flex;flex-direction:column;gap:2px;min-width:0}\n'
    + '.klabel{font-size:10px;font-weight:600;color:var(--mute);text-transform:uppercase;letter-spacing:.14em}\n'
    + '.khint{font-size:10px;color:var(--mute-2)}\n'
    + '.stale{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--amber);background:var(--amber-soft);border:1px solid var(--amber-border);padding:1px 6px;border-radius:999px}\n'
    + '.kmain{display:flex;align-items:baseline;gap:8px}\n'
    + '.kvalue{font:600 22px/1.1 var(--font-mono);color:var(--text);font-variant-numeric:tabular-nums;letter-spacing:-.01em}\n'
    + '.kchg{display:inline-flex;align-items:center;gap:3px;font:600 11px/1 var(--font-mono);font-variant-numeric:tabular-nums;padding:0;border:0;background:transparent}\n'
    + '.kchg .tri{display:block}\n'
    + '.kchg.up{color:var(--up)}\n'
    + '.kchg.down{color:var(--down)}\n'
    + '.kchg.flat{color:var(--mute-2);font-weight:500}\n'
    + '.kfoot{display:flex;align-items:flex-end;justify-content:space-between;gap:8px;margin-top:2px}\n'
    + '.spark{display:block}\n'
    + '.ksource{font-size:10px;color:var(--mute-2);text-align:right;line-height:1.3;max-width:55%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n'
    + /* Card / sections */
    '.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}\n'
    + '.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--line);background:var(--surface)}\n'
    + '.tlabel{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:var(--text)}\n'
    + '.summary{display:flex;flex-wrap:wrap;align-items:center;gap:6px}\n'
    + '.cnt{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--mute);padding:3px 8px;border-radius:999px;border:1px solid var(--line);background:var(--surface-soft)}\n'
    + '.cnt b{font:600 11px var(--font-mono);font-variant-numeric:tabular-nums}\n'
    + '.cnt.placement{border-color:var(--down-border);background:var(--down-soft);color:var(--down)}\n'
    + '.cnt.placement b{color:var(--down)}\n'
    + '.cnt.increase{border-color:var(--up-border);background:var(--up-soft);color:var(--up)}\n'
    + '.cnt.increase b{color:var(--up)}\n'
    + '.cnt.rights{border-color:var(--violet-border);background:var(--violet-soft);color:var(--violet)}\n'
    + '.cnt.rights b{color:var(--violet)}\n'
    + '.spacer{flex:1}\n'
    + '.tabs{display:inline-flex;gap:2px;padding:3px;background:#eef2f7;border-radius:8px}\n'
    + '.tab{appearance:none;background:transparent;border:0;color:var(--text-soft);padding:5px 12px;border-radius:6px;font:500 12px var(--font-sans);cursor:pointer;line-height:1.4;transition:background .15s,color .15s}\n'
    + '.tab:hover{color:var(--text)}\n'
    + '.tab.active{background:var(--surface);color:var(--text);box-shadow:0 1px 2px rgba(15,23,42,.06);font-weight:600}\n'
    + '.search{display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap}\n'
    + '.input{background:var(--surface);border:1px solid var(--line);color:var(--text);padding:6px 10px;border-radius:8px;font:400 12.5px var(--font-sans);outline:none;transition:border-color .15s,box-shadow .15s}\n'
    + '.input::placeholder{color:var(--mute-2)}\n'
    + '.input:focus{border-color:var(--primary);box-shadow:0 0 0 3px rgba(2,132,199,.15)}\n'
    + '.input.search-in{min-width:240px;padding-left:30px;background-image:url("data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2214%22 height=%2214%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%2394a3b8%22 stroke-width=%222%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22><circle cx=%2211%22 cy=%2211%22 r=%228%22/><path d=%22m21 21-4.3-4.3%22/></svg>");background-repeat:no-repeat;background-position:10px center}\n'
    + '.input[type=date]{font-family:var(--font-mono);font-size:12px}\n'
    + '.btn-ghost{appearance:none;background:transparent;border:1px solid var(--line);color:var(--text-soft);padding:5px 10px;border-radius:8px;font:500 12px var(--font-sans);cursor:pointer}\n'
    + '.btn-ghost:hover{background:var(--surface-soft);color:var(--text)}\n'
    + /* Table */
    'table{width:100%;border-collapse:collapse}\n'
    + 'thead th{background:var(--surface-soft);color:var(--mute);font-size:10px;text-align:left;padding:9px 14px;text-transform:uppercase;letter-spacing:.14em;font-weight:600;border-bottom:1px solid var(--line)}\n'
    + 'tbody td{padding:11px 14px;border-bottom:1px solid var(--line-soft);vertical-align:middle}\n'
    + 'tbody tr:last-child td{border-bottom:none}\n'
    + 'tbody tr:hover{background:var(--surface-soft)}\n'
    + '.cell-code .code{font:600 13px var(--font-mono);color:var(--text);font-variant-numeric:tabular-nums}\n'
    + '.cell-code .name{font-size:12px;color:var(--mute);margin-top:2px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n'
    + '.cell-time{color:var(--mute);font:500 12px var(--font-mono);font-variant-numeric:tabular-nums;white-space:nowrap}\n'
    + '.cell-num{font:600 13px var(--font-mono);color:var(--text);font-variant-numeric:tabular-nums}\n'
    + '.cell-msg{color:var(--text-soft);font-size:13px;max-width:560px;line-height:1.5}\n'
    + '.cell-link{font-size:12px;white-space:nowrap}\n'
    + '.cell-link a{display:inline-flex;align-items:center;gap:3px}\n'
    + /* Pills */
    '.spill{display:inline-flex;align-items:center;background:var(--primary-soft);color:#075985;border:1px solid var(--primary-border);font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px;margin:1px 3px 1px 0;line-height:1.5;white-space:nowrap}\n'
    + '.splink{text-decoration:none}.splink:hover .spill{filter:brightness(.97)}\n'
    + '.cpill{display:inline-flex;align-items:center;font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px;line-height:1.5;border:1px solid transparent}\n'
    + '.cpill-placement{background:var(--down-soft);color:var(--down);border-color:var(--down-border)}\n'
    + '.cpill-increase{background:var(--up-soft);color:var(--up);border-color:var(--up-border)}\n'
    + '.cpill-rights{background:var(--violet-soft);color:var(--violet);border-color:var(--violet-border)}\n'
    + '.cpill-other{background:var(--surface-soft);color:var(--mute);border-color:var(--line)}\n'
    + '.empty{text-align:center;color:var(--mute);padding:40px 16px;font-size:13px}\n'
    + /* Footer */
    '.foot{margin-top:24px;padding-top:14px;border-top:1px solid var(--line);text-align:center;color:var(--mute-2);font-size:11px}\n'
    + /* Responsive */
    '@media (max-width:1024px){.kpis{grid-template-columns:repeat(2,1fr)}}\n'
    + '@media (max-width:720px){.topbar-inner{padding:10px 14px;gap:10px}.brand-sub{display:none}.refresh-tag{display:none}.wrap{padding:14px}.toolbar{padding:10px}.input.search-in{min-width:160px}.cell-msg{max-width:none}.cell-link,.cell-num{display:none}thead th:nth-child(2),thead th:nth-child(4){display:none}}\n'
    + '</style></head><body>\n'
    + /* Header */
    '<header class="topbar"><div class="topbar-inner">\n'
    + '<div class="brand">'
    + '<div class="logo"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 17 9 11 13 15 21 7"/><polyline points="14 7 21 7 21 14"/></svg></div>'
    + '<div class="brand-meta">'
    + '<span class="brand-title">Signal Dashboard Pro</span>'
    + '<span class="brand-sub">TradingView · POC · HKEX</span>'
    + '</div></div>\n'
    + '<div class="topright">'
    + '<span class="dot" aria-hidden="true"></span>'
    + '<span class="tabular">Updated ' + esc_(fmtTime_(snap.updated_at)) + '</span>'
    + '<span class="refresh-tag">Auto-refresh 120s</span>'
    + '</div>\n'
    + '</div></header>\n'
    + '<main class="wrap">\n'
    + /* KPIs section */
    '<div class="section-head"><h2><span class="ico"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></span>市場快照 · Market Snapshot</h2></div>\n'
    + '<section class="kpis">'
    + kpi_('恒生指數', 'Hang Seng Index', snap.hsi, 0)
    + kpi_('恒指 PE', 'HK Market PE', snap.hsi_pe, 2)
    + kpi_('美匯指數', 'Dollar Index', snap.dxy, 2)
    + kpi_('波動指數', 'Volatility (VIX)', snap.vix, 2)
    + '</section>\n'
    + /* Corp actions section */
    '<div class="section-head"><h2><span class="ico"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M5 21V8l7-5 7 5v13"/><path d="M9 21V12h6v9"/></svg></span>港交所掘番易 · HKEX Disclosures</h2></div>\n'
    + '<section class="card">\n'
    + '<div class="toolbar">\n'
    + '<div class="tlabel">披露易公告</div>\n'
    + '<div class="summary">'
    + '<span class="cnt placement">配股 <b>' + cntPlacement + '</b></span>'
    + '<span class="cnt increase">增持 <b>' + cntIncrease + '</b></span>'
    + '<span class="cnt rights">供股 <b>' + cntRights + '</b></span>'
    + '</div>\n'
    + '<div class="spacer"></div>\n'
    + '<div class="tabs" id="ctabs" role="tablist">'
    + '<button class="tab active" data-ctype="all">全部</button>'
    + '<button class="tab" data-ctype="placement">配股</button>'
    + '<button class="tab" data-ctype="increase">增持</button>'
    + '<button class="tab" data-ctype="rights">供股</button>'
    + '</div>\n'
    + '</div>\n'
    + '<table><thead><tr>'
    + '<th>代號 / 名稱</th><th>類型</th><th>內容</th><th>時間</th><th>連結</th>'
    + '</tr></thead><tbody id="crows">' + corpRows + corpEmpty + '</tbody></table>\n'
    + '</section>\n'
    + /* Tech signals section */
    '<div class="section-head"><h2><span class="ico"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></span>TradingView 技術信號 · Signals</h2></div>\n'
    + '<section class="card">\n'
    + '<div class="toolbar">\n'
    + '<div class="tlabel">代號彙總</div>\n'
    + '<div class="spacer"></div>\n'
    + '<div class="search">'
    + '<input id="tq" class="input search-in" type="search" placeholder="搜尋代號 / 名稱…" autocomplete="off">'
    + '<input id="tdate" class="input" type="date" title="篩選日期">'
    + '<button class="btn-ghost" id="tclear" type="button">清除</button>'
    + '</div>\n'
    + '</div>\n'
    + '<table><thead><tr>'
    + '<th>代號</th><th>次數</th><th>最近信號</th><th>掘番</th><th>最後出現</th>'
    + '</tr></thead><tbody id="trows">' + techRows + techEmpty + '</tbody></table>\n'
    + '</section>\n'
    + '<div class="foot">HK Alert Cloud · Google Apps Script · Real data only</div>\n'
    + '</main>\n'
    + '<script>\n'
    + '(function(){\n'
    + 'var ctype="all";\n'
    + 'var crows=document.querySelectorAll("#crows .crow");\n'
    + 'var ctabs=document.querySelectorAll("#ctabs .tab");\n'
    + 'function applyC(){crows.forEach(function(r){var t=r.getAttribute("data-type")||"other";r.style.display=(ctype==="all"||ctype===t)?"":"none";});}\n'
    + 'ctabs.forEach(function(t){t.addEventListener("click",function(){ctabs.forEach(function(x){x.classList.remove("active");});t.classList.add("active");ctype=t.getAttribute("data-ctype")||"all";applyC();});});\n'
    + 'var tq=document.getElementById("tq");var td=document.getElementById("tdate");var tc=document.getElementById("tclear");\n'
    + 'var trows=document.querySelectorAll("#trows .trow");\n'
    + 'function applyT(){var q=(tq&&tq.value||"").trim().toLowerCase();var d=(td&&td.value||"").trim();trows.forEach(function(r){var name=(r.getAttribute("data-name")||"").toLowerCase();var code=(r.getAttribute("data-code")||"").toLowerCase();var date=(r.getAttribute("data-date")||"");var mq=(!q||name.indexOf(q)>=0||code.indexOf(q)>=0);var md=(!d||date===d);r.style.display=(mq&&md)?"":"none";});}\n'
    + 'if(tq)tq.addEventListener("input",applyT);if(td)td.addEventListener("change",applyT);if(tc)tc.addEventListener("click",function(){if(tq)tq.value="";if(td)td.value="";applyT();});\n'
    + '})();\n'
    + '</script>\n'
    + '</body></html>';
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
