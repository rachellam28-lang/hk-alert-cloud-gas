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
    .setTitle('Signal Dashboard Pro · HK')
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
    const url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(symbol) + '?interval=1d&range=5d';
    const json = JSON.parse(UrlFetchApp.fetch(url, { muteHttpExceptions: true }).getContentText());
    const r = json.chart.result[0];
    const meta = r.meta;
    const last = meta.regularMarketPrice;
    const prev = meta.chartPreviousClose || meta.previousClose;
    const change = (last != null && prev) ? last - prev : null;
    const changePct = (change != null && prev) ? change / prev * 100 : null;
    return { value: last, change: change, changePct: changePct, source: 'Yahoo Finance (' + symbol + ')', stale: false };
  } catch (err) {
    return { value: null, change: null, changePct: null, source: 'Yahoo Finance (' + symbol + ')', stale: true };
  }
}

function getHsiPe_() {
  try {
    const html = UrlFetchApp.fetch('https://worldperatio.com/area/hong-kong/', { muteHttpExceptions: true }).getContentText();
    const m = html.match(/Hong Kong Stock Market[\s\S]{0,600}?P\/E Ratio[\s\S]{0,300}?(\d{1,3}\.\d{1,2})/i)
      || html.match(/Hong Kong Stock Market[\s\S]{0,600}?(\d{1,3}\.\d{1,2})/i)
      || html.match(/P\/E Ratio[\s\S]{0,300}?(\d{1,3}\.\d{1,2})/i);
    return { value: m ? Number(m[1]) : null, change: null, changePct: null, source: 'World PE Ratio · Hong Kong', stale: !m };
  } catch (err) {
    return { value: null, change: null, changePct: null, source: 'World PE Ratio · Hong Kong', stale: true };
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

function categoryLabel_(cat) {
  if (cat === 'poc') return 'POC突破';
  if (cat === 'ipo') return 'IPO突破';
  if (cat === 'corp_action') return '披露易公告';
  return cat || '其他';
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
  return '<div class="kpi">'
    + '<div class="krow"><div class="klabel">' + esc_(label) + '</div>'
    + '<div class="khint">' + esc_(hint) + '</div></div>'
    + '<div class="kvalue">' + v + (chgHtml ? ' ' + chgHtml : '') + '</div>'
    + '<div class="ksource">' + esc_(item.source) + (item.stale ? ' · stale' : '') + '</div>'
    + '</div>';
}

function render_(alerts, snap) {
  // Counts by category.
  const counts = { all: alerts.length, poc: 0, ipo: 0, corp_action: 0 };
  alerts.forEach(function (a) {
    const k = a.category || 'other';
    counts[k] = (counts[k] || 0) + 1;
  });

  // Group alerts by stock code.
  const groupsMap = {};
  alerts.forEach(function (a) {
    const code = String(a.code || '').trim() || '—';
    const name = String(a.name || '');
    if (!groupsMap[code]) {
      groupsMap[code] = { code: code, name: name, items: [], categories: {} };
    }
    if (name && !groupsMap[code].name) groupsMap[code].name = name;
    groupsMap[code].items.push(a);
    const cat = a.category || 'other';
    groupsMap[code].categories[cat] = (groupsMap[code].categories[cat] || 0) + 1;
  });
  const groups = Object.keys(groupsMap).map(function (k) { return groupsMap[k]; });
  groups.sort(function (a, b) {
    const ta = a.items[0] && a.items[0].created_at ? new Date(a.items[0].created_at).getTime() : 0;
    const tb = b.items[0] && b.items[0].created_at ? new Date(b.items[0].created_at).getTime() : 0;
    return tb - ta;
  });

  // Render group rows. Each row carries data-cats so client-side filter can show/hide.
  const rowsHtml = groups.map(function (g) {
    const cats = Object.keys(g.categories);
    const catsAttr = cats.join(' ');
    const pillsCount = cats.map(function (c) {
      return '<span class="pill pill-' + esc_(c) + '">' + esc_(categoryLabel_(c)) + ' ×' + g.categories[c] + '</span>';
    }).join(' ');
    // Show up to 6 most recent signal pills.
    const recentPills = g.items.slice(0, 6).map(function (a) {
      const cat = a.category || 'other';
      const tip = (a.signal || '') + (a.message ? ' — ' + a.message : '');
      const link = a.chart_url || a.source_url;
      const text = a.signal || categoryLabel_(cat);
      const pillBody = '<span class="pill pill-' + esc_(cat) + ' pill-sm" title="' + esc_(tip) + '">' + esc_(text) + '</span>';
      return link ? '<a class="plink" href="' + esc_(link) + '" target="_blank" rel="noopener">' + pillBody + '</a>' : pillBody;
    }).join(' ');
    const last = g.items[0] || {};
    const tv = 'https://www.tradingview.com/chart/?symbol=HKEX%3A' + encodeURIComponent(String(g.code).replace(/^0+/, ''));
    return ''
      + '<tr class="grow" data-code="' + esc_(g.code) + '" data-name="' + esc_(g.name) + '" data-cats="' + esc_(catsAttr) + '">'
      + '<td class="cell-code"><div class="code">' + esc_(g.code) + '</div><div class="name">' + esc_(g.name) + '</div></td>'
      + '<td class="cell-counts">' + pillsCount + '</td>'
      + '<td class="cell-recent">' + recentPills + '</td>'
      + '<td class="cell-time">' + esc_(fmtTime_(last.created_at)) + '</td>'
      + '<td class="cell-link"><a href="' + esc_(tv) + '" target="_blank" rel="noopener">TradingView</a></td>'
      + '</tr>';
  }).join('');

  const empty = groups.length === 0
    ? '<tr><td colspan="5" class="empty">暫時未有 alert。等候掃描器寫入 Alerts sheet。</td></tr>'
    : '';

  return '<!doctype html>\n'
    + '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
    + '<meta http-equiv="refresh" content="120">\n'
    + '<title>Signal Dashboard Pro · HK</title>\n'
    + '<style>\n'
    + ':root{--bg:#0b1220;--bg2:#101a2c;--card:#101827;--border:#1f2a3d;--mute:#94a3b8;--text:#e5e7eb;--accent:#60a5fa;--up:#22c55e;--down:#ef4444}\n'
    + '*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,Segoe UI,Inter,Arial,sans-serif}\n'
    + '.topbar{background:#0a1530;border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;gap:16px}\n'
    + '.brand{display:flex;align-items:center;gap:10px}.dot{width:10px;height:10px;border-radius:50%;background:#60a5fa;box-shadow:0 0 0 4px rgba(96,165,250,.18)}\n'
    + '.brand h1{margin:0;font-size:16px;font-weight:600;letter-spacing:.2px}.brand .sub{color:var(--mute);font-size:11px}\n'
    + '.topright{color:var(--mute);font-size:12px;text-align:right}\n'
    + '.wrap{padding:18px 24px;max-width:1400px;margin:0 auto}\n'
    + '.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}\n'
    + '.kpi{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px}\n'
    + '.krow{display:flex;justify-content:space-between;align-items:center}\n'
    + '.klabel{font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:.6px}\n'
    + '.khint{font-size:11px;color:var(--mute)}\n'
    + '.kvalue{font:700 22px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;margin:8px 0 4px;display:flex;align-items:baseline;gap:8px}\n'
    + '.kchg{font:600 12px/1 ui-monospace,monospace;padding:2px 6px;border-radius:6px}\n'
    + '.kchg.up{color:#bbf7d0;background:rgba(34,197,94,.15)}.kchg.down{color:#fecaca;background:rgba(239,68,68,.15)}\n'
    + '.ksource{font-size:11px;color:var(--mute)}\n'
    + '.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:18px 0 10px}\n'
    + '.tabs{display:flex;gap:6px;flex-wrap:wrap}\n'
    + '.tab{background:var(--card);border:1px solid var(--border);color:var(--text);padding:6px 12px;border-radius:999px;font-size:12px;cursor:pointer}\n'
    + '.tab.active{background:#1d4ed8;border-color:#2563eb;color:#fff}\n'
    + '.tab .badge{background:rgba(255,255,255,.12);border-radius:999px;padding:1px 7px;margin-left:6px;font-size:11px}\n'
    + '.search{margin-left:auto;display:flex;gap:8px;align-items:center}\n'
    + '.search input{background:var(--card);border:1px solid var(--border);color:var(--text);padding:7px 10px;border-radius:8px;font-size:13px;min-width:220px}\n'
    + '.tablecard{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-top:6px}\n'
    + 'table{width:100%;border-collapse:collapse}thead th{background:#0e1828;color:var(--mute);font-size:11px;text-align:left;padding:10px 12px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}\n'
    + 'tbody td{padding:10px 12px;border-bottom:1px solid #182338;vertical-align:top}tbody tr:last-child td{border-bottom:none}\n'
    + 'tbody tr:hover{background:rgba(96,165,250,.04)}\n'
    + '.cell-code .code{font:600 13px ui-monospace,monospace;color:#e5e7eb}.cell-code .name{font-size:12px;color:var(--mute)}\n'
    + '.cell-time{color:var(--mute);font-size:12px;white-space:nowrap}\n'
    + '.cell-link a{color:var(--accent);font-size:12px;text-decoration:none}.cell-link a:hover{text-decoration:underline}\n'
    + '.pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:600;margin:1px 2px 1px 0;border:1px solid transparent}\n'
    + '.pill-sm{font-size:11px;padding:2px 7px}\n'
    + '.pill-poc{background:rgba(96,165,250,.12);color:#bfdbfe;border-color:rgba(96,165,250,.35)}\n'
    + '.pill-ipo{background:rgba(245,158,11,.14);color:#fde68a;border-color:rgba(245,158,11,.4)}\n'
    + '.pill-corp_action{background:rgba(244,114,182,.14);color:#fbcfe8;border-color:rgba(244,114,182,.4)}\n'
    + '.pill-other{background:rgba(148,163,184,.14);color:#e2e8f0;border-color:rgba(148,163,184,.35)}\n'
    + '.plink{text-decoration:none}.plink:hover .pill{filter:brightness(1.2)}\n'
    + '.empty{text-align:center;color:var(--mute);padding:28px}\n'
    + '@media (max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}.search input{min-width:140px}.cell-recent{display:none}}\n'
    + '@media (max-width:600px){.cell-link{display:none}}\n'
    + '</style></head><body>\n'
    + '<header class="topbar">\n'
    + '<div class="brand"><span class="dot"></span><div><h1>Signal Dashboard Pro · HK</h1><div class="sub">GitHub Actions · Apps Script · Telegram · Real data only</div></div></div>\n'
    + '<div class="topright">Updated ' + esc_(fmtTime_(snap.updated_at)) + '<br>Auto-refresh 120s</div>\n'
    + '</header>\n'
    + '<main class="wrap">\n'
    + '<section class="kpis">'
    + kpi_('HSI', 'Hang Seng Index', snap.hsi, 0)
    + kpi_('HSI PE', 'Hong Kong PE', snap.hsi_pe, 2)
    + kpi_('DXY', 'US Dollar Index', snap.dxy, 2)
    + kpi_('VIX', 'Volatility', snap.vix, 2)
    + '</section>\n'
    + '<section class="toolbar">\n'
    + '<div class="tabs">'
    + '<button class="tab active" data-cat="all">全部 <span class="badge">' + counts.all + '</span></button>'
    + '<button class="tab" data-cat="poc">POC突破 <span class="badge">' + (counts.poc || 0) + '</span></button>'
    + '<button class="tab" data-cat="ipo">IPO突破 <span class="badge">' + (counts.ipo || 0) + '</span></button>'
    + '<button class="tab" data-cat="corp_action">披露易公告 <span class="badge">' + (counts.corp_action || 0) + '</span></button>'
    + '</div>\n'
    + '<div class="search"><input id="q" type="search" placeholder="搜尋代號 / 名稱…" autocomplete="off"></div>\n'
    + '</section>\n'
    + '<section class="tablecard"><table><thead><tr>'
    + '<th>股票</th><th>分類數量</th><th>最近訊號</th><th>最近時間</th><th>圖表</th>'
    + '</tr></thead><tbody id="rows">' + rowsHtml + empty + '</tbody></table></section>\n'
    + '</main>\n'
    + '<script>\n'
    + '(function(){var cat="all";var q="";var tabs=document.querySelectorAll(".tab");var rows=document.querySelectorAll("#rows .grow");\n'
    + 'function apply(){rows.forEach(function(r){var cats=(r.getAttribute("data-cats")||"").split(/\\s+/);var name=(r.getAttribute("data-name")||"").toLowerCase();var code=(r.getAttribute("data-code")||"").toLowerCase();var matchCat=(cat==="all"||cats.indexOf(cat)>=0);var matchQ=(!q||name.indexOf(q)>=0||code.indexOf(q)>=0);r.style.display=(matchCat&&matchQ)?"":"none";});}\n'
    + 'tabs.forEach(function(t){t.addEventListener("click",function(){tabs.forEach(function(x){x.classList.remove("active");});t.classList.add("active");cat=t.getAttribute("data-cat")||"all";apply();});});\n'
    + 'var qi=document.getElementById("q");if(qi){qi.addEventListener("input",function(){q=qi.value.trim().toLowerCase();apply();});}\n'
    + '})();\n'
    + '</script>\n'
    + '</body></html>';
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
