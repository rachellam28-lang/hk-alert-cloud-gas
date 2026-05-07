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

function sparkline_(series) {
  if (!series || series.length < 2) return '';
  const w = 92, h = 24, pad = 2;
  let min = Infinity, max = -Infinity;
  for (let i = 0; i < series.length; i++) {
    const v = series[i];
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === max) { min -= 1; max += 1; }
  const stepX = (w - pad * 2) / (series.length - 1);
  const pts = series.map(function (v, i) {
    const x = pad + i * stepX;
    const y = pad + (h - pad * 2) * (1 - (v - min) / (max - min));
    return x.toFixed(1) + ',' + y.toFixed(1);
  }).join(' ');
  const last = series[series.length - 1];
  const first = series[0];
  const up = last >= first;
  const stroke = up ? '#0ea5a4' : '#ef4444';
  return '<svg class="spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
    + '<polyline fill="none" stroke="' + stroke + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" points="' + pts + '"/>'
    + '</svg>';
}

function kpi_(label, hint, item, decimals) {
  const v = n_(item.value, decimals);
  let chgHtml = '';
  if (item.changePct != null && !isNaN(item.changePct)) {
    const up = item.changePct >= 0;
    const arrow = up ? '▲' : '▼';
    chgHtml = '<span class="kchg ' + (up ? 'up' : 'down') + '">' + arrow + ' '
      + n_(Math.abs(item.changePct), 2) + '%</span>';
  }
  const spark = sparkline_(item.series || []);
  return '<div class="kpi">'
    + '<div class="krow"><div class="klabel">' + esc_(label) + '</div>'
    + '<div class="khint">' + esc_(hint) + '</div></div>'
    + '<div class="kvalue">' + v + '</div>'
    + '<div class="kfoot">' + (chgHtml || '<span class="kchg flat">—</span>') + spark + '</div>'
    + '<div class="ksource">' + esc_(item.source) + (item.stale ? ' · stale' : '') + '</div>'
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
    + '<style>\n'
    + ':root{--bg:#f4f6fa;--surface:#ffffff;--text:#0f172a;--mute:#64748b;--line:#e5e9f0;--accent:#0d9488;--accent-soft:#ccfbf1;--blue:#2563eb;--blue-soft:#dbeafe;--red:#dc2626;--green:#059669;--up:#059669;--down:#dc2626;--nav:#0f1f3a}\n'
    + '*{box-sizing:border-box}html,body{margin:0;padding:0}body{background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,Segoe UI,Inter,"PingFang TC","Noto Sans TC",Arial,sans-serif;-webkit-font-smoothing:antialiased}\n'
    + 'a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}\n'
    + '.topbar{background:var(--nav);color:#fff;padding:10px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px}\n'
    + '.brand{display:flex;align-items:center;gap:10px;min-width:0}.brand h1{margin:0;font-size:15px;font-weight:600;letter-spacing:.2px;white-space:nowrap}\n'
    + '.btag{background:#1e3a8a;color:#bfdbfe;font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid #2952a3;white-space:nowrap}\n'
    + '.topright{color:#cbd5e1;font-size:12px;text-align:right;line-height:1.35;white-space:nowrap}\n'
    + '.wrap{padding:18px 20px;max-width:1280px;margin:0 auto}\n'
    + '.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}\n'
    + '.kpi{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 14px 12px 18px;box-shadow:0 1px 2px rgba(15,23,42,.04);overflow:hidden}\n'
    + '.kpi:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent);border-radius:10px 0 0 10px}\n'
    + '.krow{display:flex;justify-content:space-between;align-items:baseline;gap:8px}\n'
    + '.klabel{font-size:12px;color:var(--mute);font-weight:600;letter-spacing:.3px}\n'
    + '.khint{font-size:11px;color:#94a3b8}\n'
    + '.kvalue{font:700 26px/1.15 ui-monospace,SFMono-Regular,Menlo,monospace;color:#0f172a;margin:6px 0 4px}\n'
    + '.kfoot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:2px}\n'
    + '.kchg{font:600 12px/1 ui-monospace,monospace;padding:2px 7px;border-radius:6px}\n'
    + '.kchg.up{color:#065f46;background:#d1fae5}.kchg.down{color:#991b1b;background:#fee2e2}.kchg.flat{color:#94a3b8;background:#f1f5f9}\n'
    + '.spark{display:block}\n'
    + '.ksource{font-size:11px;color:#94a3b8;margin-top:6px}\n'
    + '.section-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:22px 0 10px}\n'
    + '.section-head h2{margin:0;font-size:15px;font-weight:600;color:#0f172a;display:flex;align-items:center;gap:8px}\n'
    + '.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;box-shadow:0 1px 2px rgba(15,23,42,.04);overflow:hidden}\n'
    + '.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--line);background:#fbfcfe}\n'
    + '.tlabel{font-weight:600;color:#0f172a;font-size:14px;display:flex;align-items:center;gap:6px}\n'
    + '.cnt{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#475569}\n'
    + '.cnt b{font-weight:700}\n'
    + '.cnt.placement b{color:var(--red)}\n'
    + '.cnt.increase b{color:var(--green)}\n'
    + '.cnt.rights b{color:#7c3aed}\n'
    + '.tabs{display:flex;gap:6px;flex-wrap:wrap}\n'
    + '.tab{background:#fff;border:1px solid var(--line);color:#334155;padding:5px 12px;border-radius:999px;font-size:12px;cursor:pointer;line-height:1.4}\n'
    + '.tab:hover{border-color:#cbd5e1}\n'
    + '.tab.active{background:var(--blue);border-color:var(--blue);color:#fff}\n'
    + '.spacer{flex:1}\n'
    + '.search{display:flex;gap:8px;align-items:center}\n'
    + '.search input{background:#fff;border:1px solid var(--line);color:#0f172a;padding:6px 10px;border-radius:8px;font-size:13px;min-width:220px;outline:none}\n'
    + '.search input:focus{border-color:#94a3b8}\n'
    + '.search input[type=date]{min-width:auto}\n'
    + 'table{width:100%;border-collapse:collapse}\n'
    + 'thead th{background:#f8fafc;color:#475569;font-size:11px;text-align:left;padding:9px 14px;text-transform:uppercase;letter-spacing:.6px;font-weight:600;border-bottom:1px solid var(--line)}\n'
    + 'tbody td{padding:10px 14px;border-bottom:1px solid #eef1f6;vertical-align:middle}\n'
    + 'tbody tr:last-child td{border-bottom:none}\n'
    + 'tbody tr:hover{background:#f8fafc}\n'
    + '.cell-code .code{font:600 13px ui-monospace,monospace;color:#0f172a}.cell-code .name{font-size:12px;color:var(--mute);margin-top:1px}\n'
    + '.cell-time{color:var(--mute);font-size:12px;white-space:nowrap}\n'
    + '.cell-num{font:600 13px ui-monospace,monospace;color:#0f172a}\n'
    + '.cell-msg{color:#334155;font-size:13px;max-width:520px}\n'
    + '.cell-link{font-size:12px;white-space:nowrap}\n'
    + '.spill{display:inline-block;background:var(--blue-soft);color:#1e40af;border:1px solid #bfdbfe;font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px;margin:1px 2px 1px 0;line-height:1.5;white-space:nowrap}\n'
    + '.splink{text-decoration:none}.splink:hover .spill{filter:brightness(.97)}\n'
    + '.cpill{display:inline-block;font-size:11px;font-weight:700;padding:2px 9px;border-radius:999px;line-height:1.5}\n'
    + '.cpill-placement{background:#fee2e2;color:#991b1b}\n'
    + '.cpill-increase{background:#d1fae5;color:#065f46}\n'
    + '.cpill-rights{background:#ede9fe;color:#5b21b6}\n'
    + '.cpill-other{background:#f1f5f9;color:#475569}\n'
    + '.empty{text-align:center;color:var(--mute);padding:32px;font-size:13px}\n'
    + '@media (max-width:960px){.kpis{grid-template-columns:repeat(2,1fr)}.search input{min-width:140px}.cell-msg{max-width:240px}}\n'
    + '@media (max-width:600px){.topbar{padding:10px 14px}.wrap{padding:14px}.toolbar{padding:10px}.cell-link,.cell-num{display:none}thead th:nth-child(2),thead th:nth-child(4){display:none}.cell-msg{max-width:none}}\n'
    + '</style></head><body>\n'
    + '<header class="topbar">\n'
    + '<div class="brand"><h1>📊 Signal Dashboard Pro</h1><span class="btag">技術信號・掘番易</span></div>\n'
    + '<div class="topright">Updated ' + esc_(fmtTime_(snap.updated_at)) + '<br>Auto-refresh 120s</div>\n'
    + '</header>\n'
    + '<main class="wrap">\n'
    + '<section class="kpis">'
    + kpi_('恒生指數', '^HSI', snap.hsi, 0)
    + kpi_('恒指 PE 估值', 'HK Market PE', snap.hsi_pe, 2)
    + kpi_('美匯指數', 'DXY', snap.dxy, 2)
    + kpi_('波動指數', 'VIX', snap.vix, 2)
    + '</section>\n'
    + '<div class="section-head"><h2>🏛️ 港交所掘番易</h2></div>\n'
    + '<section class="card">\n'
    + '<div class="toolbar">\n'
    + '<div class="tlabel">披露易公告</div>\n'
    + '<span class="cnt placement">配股 <b>' + cntPlacement + '</b></span>\n'
    + '<span class="cnt increase">增持 <b>' + cntIncrease + '</b></span>\n'
    + '<span class="cnt rights">供股 <b>' + cntRights + '</b></span>\n'
    + '<div class="spacer"></div>\n'
    + '<div class="tabs" id="ctabs">'
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
    + '<div class="section-head"><h2>⚡ TradingView 技術信號</h2></div>\n'
    + '<section class="card">\n'
    + '<div class="toolbar">\n'
    + '<div class="search">'
    + '<input id="tq" type="search" placeholder="搜尋代號 / 名稱…" autocomplete="off">'
    + '<input id="tdate" type="date" title="篩選日期">'
    + '<button class="tab" id="tclear" type="button">清除</button>'
    + '</div>\n'
    + '</div>\n'
    + '<table><thead><tr>'
    + '<th>代號</th><th>次數</th><th>最近信號</th><th>掘番</th><th>最後出現</th>'
    + '</tr></thead><tbody id="trows">' + techRows + techEmpty + '</tbody></table>\n'
    + '</section>\n'
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
