const SPREADSHEET_ID = '129IieKTIfssX18O_PfnRoxbx3c12UoCPQ_MxxBizgeA';
const ALERT_SHEET = 'Alerts';
const CHART_FOLDER_NAME = 'HK Alert Charts';
const WATCHLIST_SHEET = 'Watchlist';
const WATCHLIST_HEADERS = ['code', 'name', 'types', 'ann_date', 'added_at'];

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
  'tags', 'poc_6m', 'poc_12m', 'poc_2y', 'poc_3y',
  'chart_image_url', 'chart_drive_id', 'priority', 'announcement_date',
  'release_time', 'raw'
];

function doGet(e) {
  e = e || {};
  const params = e.parameter || {};
  if (params.mode === 'watchlist') {
    const expected = getGasSecret_();
    if (expected && params.secret !== expected) {
      return ContentService.createTextOutput(JSON.stringify({ error: 'unauthorized' }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    return ContentService.createTextOutput(JSON.stringify(getActiveWatchlist_()))
      .setMimeType(ContentService.MimeType.JSON);
  }
  // Existing dashboard serving (unchanged below).
  const cache = safeCache_();
  if (cache) {
    const cached = cache.get('dashboard_html_v3');
    if (cached) {
      return HtmlService.createHtmlOutput(cached)
        .setTitle('港股訊號儀表板')
        .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
    }
  }
  try {
    const alerts = getAlerts_();
    const snap = getMarketSnapshotCached_();
    const html = render_(alerts, snap);
    if (cache) {
      try { cache.put('dashboard_html_v3', html, HTML_CACHE_TTL_SECONDS); } catch (e) { /* ignore */ }
    }
    return HtmlService.createHtmlOutput(html)
      .setTitle('港股訊號儀表板')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  } catch (err) {
    return HtmlService.createHtmlOutput(
      '<pre style="color:red;font-family:monospace;padding:20px;white-space:pre-wrap">'
      + 'Dashboard Error:\n' + String(err) + '\n\nStack:\n' + (err.stack || 'n/a')
      + '</pre>'
    ).setTitle('Error').setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');
    const expected = getGasSecret_();
    if (expected && payload.secret !== expected) {
      return json_({ ok: false, error: 'secret_mismatch' });
    }
    // Route watchlist entries to separate handler.
    if (payload.type === 'watchlist') {
      return handleWatchlistPost_(payload);
    }
    // Save chart PNG to Drive when scanner sent base64 chart bytes; on any failure
    // the alert still records without a chart image (fallback to sparkline in UI).
    const chartInfo = saveChartToDrive_(payload);
    if (chartInfo) {
      payload.chart_image_url = chartInfo.url;
      payload.chart_drive_id = chartInfo.id;
    }
    delete payload.chart_image_b64;
    delete payload.chart_image_name;
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sh = ensureSheet_(ss);
    const headers = readHeaders_(sh);
    const row = headers.map(h => {
      if (h === 'created_at') return payload.created_at || new Date().toISOString();
      if (h === 'tags' && Array.isArray(payload.tags)) return payload.tags.join(',');
      if (h === 'raw') return payload.raw || JSON.stringify(payload);
      return payload[h] == null ? '' : payload[h];
    });
    sh.appendRow(row);
    return json_({ ok: true, chart_image_url: payload.chart_image_url || '' });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function saveChartToDrive_(payload) {
  try {
    const b64 = payload && payload.chart_image_b64;
    if (!b64) return null;
    const fileName = (payload.chart_image_name && String(payload.chart_image_name)) ||
      ((payload.code || 'chart') + '_' + Date.now() + '.png');
    const bytes = Utilities.base64Decode(b64);
    const blob = Utilities.newBlob(bytes, 'image/png', fileName);
    const folder = getOrCreateFolder_(CHART_FOLDER_NAME);
    const file = folder.createFile(blob);
    try {
      file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    } catch (shareErr) {
      // Some Workspace policies block link-sharing; we still keep the file ID
      // and the UI will gracefully fall back to the sparkline.
    }
    const id = file.getId();
    return { id: id, url: 'https://drive.google.com/thumbnail?id=' + id + '&sz=w300' };
  } catch (err) {
    return null;
  }
}

function getOrCreateFolder_(name) {
  const it = DriveApp.getFoldersByName(name);
  if (it.hasNext()) return it.next();
  return DriveApp.createFolder(name);
}

function ensureWatchlistSheet_(ss) {
  ss = ss || SpreadsheetApp.openById(SPREADSHEET_ID);
  let sh = ss.getSheetByName(WATCHLIST_SHEET);
  if (!sh) {
    sh = ss.insertSheet(WATCHLIST_SHEET);
    sh.getRange(1, 1, 1, WATCHLIST_HEADERS.length).setValues([WATCHLIST_HEADERS]);
    sh.setFrozenRows(1);
  }
  return sh;
}

function handleWatchlistPost_(payload) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sh = ensureWatchlistSheet_(ss);
    const code = String(payload.code || '').padStart(5, '0');
    const name = payload.name || '';
    const types = Array.isArray(payload.types) ? payload.types.join(',') : String(payload.types || '');
    const annDate = payload.ann_date || '';
    const addedAt = new Date().toISOString();
    // Dedupe: overwrite existing row for this code if present.
    const lastRow = sh.getLastRow();
    if (lastRow > 1) {
      const codes = sh.getRange(2, 1, lastRow - 1, 1).getValues().map(function(r) { return String(r[0]); });
      const idx = codes.indexOf(code);
      if (idx >= 0) {
        const dataRow = idx + 2;
        sh.getRange(dataRow, 1, 1, WATCHLIST_HEADERS.length).setValues([[code, name, types, annDate, addedAt]]);
        return json_({ ok: true, action: 'updated' });
      }
    }
    sh.appendRow([code, name, types, annDate, addedAt]);
    return json_({ ok: true, action: 'added' });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function getActiveWatchlist_() {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sh = ss.getSheetByName(WATCHLIST_SHEET);
    if (!sh || sh.getLastRow() <= 1) return [];
    const expiryDays = 5;
    const cutoff = new Date(Date.now() - expiryDays * 86400000);
    const lastRow = sh.getLastRow();
    const data = sh.getRange(2, 1, lastRow - 1, WATCHLIST_HEADERS.length).getValues();
    const out = [];
    for (let i = 0; i < data.length; i++) {
      const row = data[i];
      const code = String(row[0] || '').padStart(5, '0');
      if (!code || code === '00000') continue;
      const addedAt = row[4] ? new Date(row[4]) : null;
      if (addedAt && addedAt < cutoff) continue;
      const typesRaw = String(row[2] || '');
      out.push({
        code: code,
        name: String(row[1] || ''),
        types: typesRaw ? typesRaw.split(',') : [],
        ann_date: String(row[3] || ''),
        added_at: row[4] ? String(row[4]) : '',
      });
    }
    return out;
  } catch (err) {
    return [];
  }
}

function readHeaders_(sh) {
  const maxCol = sh.getMaxColumns();
  const target = Math.min(maxCol, Math.max(sh.getLastColumn(), HEADERS.length));
  if (target <= 0) return HEADERS.slice();
  const first = sh.getRange(1, 1, 1, target).getValues()[0].map(String);
  // Drop trailing empty cells past the canonical header so appendRow stays aligned.
  while (first.length > HEADERS.length && first[first.length - 1] === '') first.pop();
  return first;
}

// Initial render is capped to the latest N grouped stock codes so doGet returns
// quickly on mobile. Older history stays in the sheet but is not embedded in
// the first paint to keep DOM and outbound fetches bounded.
const DASHBOARD_MAX_GROUPS = 120;
// Read at most this many recent alert rows from the sheet before grouping.
// 600 rows * (≤4 alerts per code) gives a comfortable headroom for ~120 groups.
const DASHBOARD_MAX_ALERTS = 600;
// Cache TTLs (seconds). HTML cache absorbs repeat loads; snapshot cache shields
// us from upstream Yahoo / worldperatio latency on every page load.
const HTML_CACHE_TTL_SECONDS = 115;
const SNAPSHOT_CACHE_TTL_SECONDS = 300;
// Hard upper-bound on how many codes we batch-query Yahoo for as a fallback
// when the scanner did not save a chart_image_url. Each adds an outbound HTTP
// request, so we keep this small to avoid blocking doGet on mobile.
const YAHOO_FALLBACK_MAX_CODES = 25;
// 最近公告 list size — the N most recent HKEXnews corp-action alerts shown on
// the dashboard with date + label + HKEX link only (no long titles).
const RECENT_CORPS_LIMIT = 20;


function safeCache_() {
  try { return CacheService.getScriptCache(); } catch (e) { return null; }
}

function ensureSheet_(ss) {
  let sh = ss.getSheetByName(ALERT_SHEET);
  if (!sh) sh = ss.insertSheet(ALERT_SHEET);
  const lastCol = sh.getLastColumn();
  if (lastCol === 0) {
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
    sh.setFrozenRows(1);
    return sh;
  }
  const maxCol = sh.getMaxColumns();
  const readCols = Math.min(maxCol, Math.max(lastCol, HEADERS.length));
  const first = sh.getRange(1, 1, 1, readCols).getValues()[0].map(String);
  // If first row is fully blank, write our canonical header.
  if (first.every(function (v) { return v === ''; })) {
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
    sh.setFrozenRows(1);
    return sh;
  }
  // Append any missing canonical headers to the right WITHOUT touching existing data.
  const existing = {};
  first.forEach(function (h) { if (h) existing[h] = true; });
  const missing = HEADERS.filter(function (h) { return !existing[h]; });
  if (missing.length) {
    let nextCol = first.length + 1;
    // Strip trailing empty cells in the header row before appending.
    while (nextCol > 1 && (first[nextCol - 2] === '' || first[nextCol - 2] == null)) nextCol--;
    sh.getRange(1, nextCol, 1, missing.length).setValues([missing]);
    sh.setFrozenRows(1);
  }
  return sh;
}

function getAlerts_() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sh = ensureSheet_(ss);
  const lastRow = sh.getLastRow();
  const lastCol = sh.getLastColumn();
  if (lastRow <= 1 || lastCol <= 0) return [];
  const headers = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
  // Read only the trailing window we actually need, instead of the whole sheet.
  const startRow = Math.max(2, lastRow - DASHBOARD_MAX_ALERTS + 1);
  const numRows = lastRow - startRow + 1;
  if (numRows <= 0) return [];
  const values = sh.getRange(startRow, 1, numRows, lastCol).getValues();
  const out = new Array(values.length);
  for (let i = 0; i < values.length; i++) {
    const r = values[i];
    const o = {};
    for (let j = 0; j < headers.length; j++) o[headers[j]] = r[j];
    out[i] = o;
  }
  // Newest-first so grouping picks up the latest chart_image_url per code.
  return out.reverse();
}

// Batch-fetch closing series for many HK stock symbols in one parallel call.
// Returns map: code -> { value, changePct, series }. Missing/failed symbols are omitted.
function fetchYahooBatch_(codes) {
  if (!codes || !codes.length) return {};
  const symbols = codes.map(function (c) {
    const num = String(c || '').replace(/[^0-9]/g, '');
    if (!num) return null;
    const padded = ('0000' + num).slice(-4);
    return { code: c, symbol: padded + '.HK' };
  }).filter(function (x) { return !!x; });
  const requests = symbols.map(function (s) {
    return {
      url: 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(s.symbol) + '?interval=1d&range=30d',
      muteHttpExceptions: true
    };
  });
  const out = {};
  if (!requests.length) return out;
  let responses;
  try {
    responses = UrlFetchApp.fetchAll(requests);
  } catch (err) {
    return out;
  }
  for (let i = 0; i < responses.length; i++) {
    const s = symbols[i];
    try {
      const j = JSON.parse(responses[i].getContentText());
      const r = j.chart && j.chart.result && j.chart.result[0];
      if (!r) continue;
      const meta = r.meta || {};
      const last = meta.regularMarketPrice;
      const prev = meta.chartPreviousClose || meta.previousClose;
      const changePct = (last != null && prev) ? (last - prev) / prev * 100 : null;
      let series = [];
      const closes = r.indicators && r.indicators.quote && r.indicators.quote[0] && r.indicators.quote[0].close;
      if (Array.isArray(closes)) {
        series = closes.filter(function (v) { return v != null && !isNaN(v); }).slice(-20);
      }
      out[s.code] = { value: last == null ? null : Number(last), changePct: changePct, series: series, symbol: s.symbol };
    } catch (e) {
      // skip; row will render without sparkline
    }
  }
  return out;
}

function getMarketSnapshot_() {
  // Run the four upstream calls in parallel via fetchAll so a slow source
  // (notably worldperatio.com) cannot serialize doGet latency.
  const yahooReqs = [
    { url: 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent('^HSI') + '?interval=1d&range=30d', muteHttpExceptions: true },
    { url: 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent('DX-Y.NYB') + '?interval=1d&range=30d', muteHttpExceptions: true },
    { url: 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent('^VIX') + '?interval=1d&range=30d', muteHttpExceptions: true },
    { url: 'https://worldperatio.com/area/hong-kong/', muteHttpExceptions: true }
  ];
  let responses = [];
  try { responses = UrlFetchApp.fetchAll(yahooReqs); } catch (e) { responses = []; }
  return {
    hsi: parseYahooResp_(responses[0], '^HSI'),
    dxy: parseYahooResp_(responses[1], 'DX-Y.NYB'),
    vix: parseYahooResp_(responses[2], '^VIX'),
    hsi_pe: parseHsiPeResp_(responses[3]),
    updated_at: new Date().toISOString()
  };
}

function parseYahooResp_(resp, symbol) {
  try {
    if (!resp) return { value: null, change: null, changePct: null, source: 'Yahoo (' + symbol + ')', stale: true, series: [] };
    const j = JSON.parse(resp.getContentText());
    const r = j.chart && j.chart.result && j.chart.result[0];
    if (!r) return { value: null, change: null, changePct: null, source: 'Yahoo (' + symbol + ')', stale: true, series: [] };
    const meta = r.meta || {};
    const last = meta.regularMarketPrice;
    const prev = meta.chartPreviousClose || meta.previousClose;
    const change = (last != null && prev) ? last - prev : null;
    const changePct = (change != null && prev) ? change / prev * 100 : null;
    let series = [];
    const closes = r.indicators && r.indicators.quote && r.indicators.quote[0] && r.indicators.quote[0].close;
    if (Array.isArray(closes)) {
      series = closes.filter(function (v) { return v != null && !isNaN(v); }).slice(-20);
    }
    return { value: last, change: change, changePct: changePct, source: 'Yahoo (' + symbol + ')', stale: false, series: series };
  } catch (e) {
    return { value: null, change: null, changePct: null, source: 'Yahoo (' + symbol + ')', stale: true, series: [] };
  }
}

function parseHsiPeResp_(resp) {
  try {
    if (!resp) return { value: null, change: null, changePct: null, source: 'World PE Ratio', stale: true, series: [] };
    const html = resp.getContentText();
    const m = html.match(/Hong Kong Stock Market[\s\S]{0,600}?P\/E Ratio[\s\S]{0,300}?(\d{1,3}\.\d{1,2})/i)
      || html.match(/Hong Kong Stock Market[\s\S]{0,600}?(\d{1,3}\.\d{1,2})/i)
      || html.match(/P\/E Ratio[\s\S]{0,300}?(\d{1,3}\.\d{1,2})/i);
    return { value: m ? Number(m[1]) : null, change: null, changePct: null, source: 'World PE Ratio', stale: !m, series: [] };
  } catch (e) {
    return { value: null, change: null, changePct: null, source: 'World PE Ratio', stale: true, series: [] };
  }
}

function getMarketSnapshotCached_() {
  const cache = safeCache_();
  if (cache) {
    const raw = cache.get('market_snapshot_v2');
    if (raw) {
      try { return JSON.parse(raw); } catch (e) { /* fall through */ }
    }
  }
  const snap = getMarketSnapshot_();
  if (cache) {
    try { cache.put('market_snapshot_v2', JSON.stringify(snap), SNAPSHOT_CACHE_TTL_SECONDS); } catch (e) { /* ignore */ }
  }
  return snap;
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

// Render a clean close-price sparkline (line + soft area fill) from a real closing series.
// Color is chosen by caller via `dir`: 'up' (green), 'down' (red), or 'flat' (grey).
function sparkline_(series, dir, w, h) {
  w = w || 110; h = h || 36;
  if (!series || series.length < 2) return '';
  const pad = 3;
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
  let stroke = '#94a3b8', fill = 'rgba(148,163,184,0.12)';
  if (dir === 'up')   { stroke = '#16a34a'; fill = 'rgba(22,163,74,0.12)'; }
  if (dir === 'down') { stroke = '#dc2626'; fill = 'rgba(220,38,38,0.12)'; }
  const lastX = (pad + (series.length - 1) * stepX).toFixed(1);
  const baseY = (h - pad).toFixed(1);
  const area = pts + ' ' + lastX + ',' + baseY + ' ' + pad.toFixed(1) + ',' + baseY;
  const lastPt = coords[coords.length - 1];
  return '<svg class="spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
    + '<polygon points="' + area + '" fill="' + fill + '" stroke="none"/>'
    + '<polyline fill="none" stroke="' + stroke + '" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" points="' + pts + '"/>'
    + '<circle cx="' + lastPt[0].toFixed(1) + '" cy="' + lastPt[1].toFixed(1) + '" r="1.8" fill="' + stroke + '"/>'
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
  let sparkDir = up == null ? 'flat' : (up ? 'up' : 'down');
  if (item.series && item.series.length >= 2) {
    const first = item.series[0], last = item.series[item.series.length - 1];
    sparkDir = last > first ? 'up' : (last < first ? 'down' : 'flat');
  }
  const spark = sparkline_(item.series || [], sparkDir, 96, 28);
  const stale = item.stale ? '<span class="stale">過時</span>' : '';
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
  const tags = String(a.tags || '');
  const sig = String(a.signal || '') + ' ' + String(a.message || '');
  const blob = (tags + ' ' + sig);
  if (/大手轉倉|大宗交易|場外轉讓|股份轉讓/.test(blob)) return 'block';
  if (/股東增持|增持/.test(blob)) return 'increase';
  if (/配股|配售|認購新股|發行股份|認購事項/.test(blob)) return 'placement';
  if (/供股|公開發售/.test(blob)) return 'rights';
  return 'other';
}

function corpTypeLabel_(t) {
  if (t === 'placement') return '配股';
  if (t === 'increase') return '增持';
  if (t === 'rights') return '供股';
  if (t === 'block') return '大手轉倉';
  return '公告';
}

// Best-effort: pull the announcement's release date out of the row. Prefers
// the explicit announcement_date column, then release_time (HKEXnews
// dd/mm/yyyy format), then the alert's created_at as last resort.
function corpAnnouncementDate_(a) {
  const explicit = String(a.announcement_date || '').trim();
  if (explicit) {
    if (/^\d{4}-\d{2}-\d{2}/.test(explicit)) return explicit.slice(0, 10);
    const m = explicit.match(/^(\d{2})\/(\d{2})\/(\d{4})/);
    if (m) return m[3] + '-' + m[2] + '-' + m[1];
  }
  const rt = String(a.release_time || '').trim();
  if (rt) {
    const m = rt.match(/^(\d{2})\/(\d{2})\/(\d{4})/);
    if (m) return m[3] + '-' + m[2] + '-' + m[1];
  }
  return fmtDate_(a.created_at);
}

function render_(alerts, snap) {
  // Group every alert by stock code into a single unified row per code.
  // Each group tracks: technical signal labels, corp-action types, latest time, links.
  const groupsMap = {};
  alerts.forEach(function (a) {
    const code = String(a.code || '').trim();
    if (!code) return; // unified table is per-code; skip rows without a code
    if (!groupsMap[code]) {
      groupsMap[code] = {
        code: code,
        name: String(a.name || ''),
        items: [],
        techCount: 0,
        corpCount: 0,
        signals: [],            // ordered unique technical-signal labels (with link)
        signalSeen: {},
        corpTypes: {},          // 'placement'|'increase'|'rights'|'other' -> { count, link }
        latest: 0,              // most-recent created_at timestamp
        latestRaw: '',
        tvLink: '',
        hkexLink: '',
        chartImageUrl: '',
        chartCaption: '',
        latestPrice: null
      };
    }
    const g = groupsMap[code];
    if (!g.name && a.name) g.name = String(a.name);
    g.items.push(a);

    const ts = a.created_at ? new Date(a.created_at).getTime() : 0;
    if (ts > g.latest) {
      g.latest = ts;
      g.latestRaw = a.created_at;
      // Track the alert price (scanner-verified, same as Telegram message).
      const ap = parseFloat(a.price);
      if (!isNaN(ap) && ap > 0) g.latestPrice = ap;
      // Adopt the latest alert's saved chart image as the row thumbnail.
      const url = String(a.chart_image_url || '').trim();
      if (url) {
        g.chartImageUrl = url;
        g.chartCaption = String(a.signal || a.category || '');
      }
    } else if (!g.chartImageUrl) {
      const url = String(a.chart_image_url || '').trim();
      if (url) {
        g.chartImageUrl = url;
        g.chartCaption = String(a.signal || a.category || '');
      }
    }

    const isCorp = a.category === 'corp_action';
    if (isCorp) {
      g.corpCount++;
      const t = corpType_(a);
      if (!g.corpTypes[t]) g.corpTypes[t] = { count: 0, link: '' };
      g.corpTypes[t].count++;
      const cl = a.source_url || a.chart_url || '';
      if (cl && !g.corpTypes[t].link) g.corpTypes[t].link = cl;
      if (cl && !g.hkexLink) g.hkexLink = cl;
    } else {
      g.techCount++;
      const label = String(a.signal || a.category || '').trim() || '訊號';
      if (!g.signalSeen[label]) {
        g.signalSeen[label] = true;
        const link = a.chart_url || a.source_url || '';
        g.signals.push({ label: label, link: link });
      }
      if (!g.tvLink) {
        const cu = a.chart_url || '';
        if (cu) g.tvLink = cu;
      }
    }
  });

  // Build "最近公告" list: latest N HKEX corp-action alerts with date + label +
  // HKEX link only (no long titles). Dedupe by source_url so the same release
  // touching N stocks renders once. Alerts list is already newest-first, so a
  // simple forward pass preserves recency.
  const recentCorps = [];
  const seenCorpUrls = {};
  for (let i = 0; i < alerts.length && recentCorps.length < RECENT_CORPS_LIMIT; i++) {
    const a = alerts[i];
    if (!a || a.category !== 'corp_action') continue;
    const url = String(a.source_url || a.chart_url || '').trim();
    const dedupeKey = url || ('row|' + i);
    if (seenCorpUrls[dedupeKey]) continue;
    seenCorpUrls[dedupeKey] = true;
    recentCorps.push({
      code: String(a.code || '').trim(),
      name: String(a.name || ''),
      type: corpType_(a),
      date: corpAnnouncementDate_(a),
      url: url,
      created_at: a.created_at || ''
    });
  }
  recentCorps.sort(function (x, y) {
    if (x.date < y.date) return 1;
    if (x.date > y.date) return -1;
    return String(y.created_at).localeCompare(String(x.created_at));
  });

  let groups = Object.keys(groupsMap).map(function (k) { return groupsMap[k]; });
  groups.sort(function (a, b) { return b.latest - a.latest; });
  // Cap initial render to the latest N groups so doGet stays fast on mobile.
  // Older entries remain in the sheet and reappear once newer rows expire.
  if (groups.length > DASHBOARD_MAX_GROUPS) groups = groups.slice(0, DASHBOARD_MAX_GROUPS);

  // Aggregate corp-action counts for the toolbar summary (over rendered groups).
  let cntPlacement = 0, cntIncrease = 0, cntRights = 0, cntBlock = 0;
  groups.forEach(function (g) {
    if (g.corpTypes.placement) cntPlacement += g.corpTypes.placement.count;
    if (g.corpTypes.increase) cntIncrease += g.corpTypes.increase.count;
    if (g.corpTypes.rights) cntRights += g.corpTypes.rights.count;
    if (g.corpTypes.block) cntBlock += g.corpTypes.block.count;
  });

  // Only fall back to Yahoo for codes that have no scanner-saved chart image.
  // Skipping codes with chart_image_url avoids hundreds of HTTP requests on
  // page load — the dominant cause of the previous mobile timeout.
  const codesNeedingPrice = [];
  groups.forEach(function (g) {
    if (!g.chartImageUrl && g.code) codesNeedingPrice.push(g.code);
  });
  const priceMap = fetchYahooBatch_(codesNeedingPrice.slice(0, YAHOO_FALLBACK_MAX_CODES));

  const rows = groups.map(function (g) {
    const codeStr = String(g.code || '').trim();
    const codeNum = codeStr.replace(/^0+/, '');
    const hkexHref = g.hkexLink || '';

    // Real price + chart from Yahoo batch (if available).
    const p = priceMap[codeStr];
    let chartHtml = '<span class="nochart">—</span>';
    let priceHtml = '';
    // Prefer the scanner's saved real chart (matplotlib OHLC sent via Telegram + Drive).
    if (g.chartImageUrl) {
      const cap = g.chartCaption ? esc_(g.chartCaption) : (esc_(codeStr) + ' chart');
      // onerror swaps the broken image for a "no chart" placeholder so a
      // missing/forbidden Drive file never breaks page layout.
      chartHtml = '<a class="chartimg-link" href="' + esc_(g.chartImageUrl) + '" target="_blank" rel="noopener">'
        + '<img class="chartimg" src="' + esc_(g.chartImageUrl) + '" alt="' + cap + '" loading="lazy" decoding="async" width="140" height="60" referrerpolicy="no-referrer"'
        + ' onerror="this.onerror=null;this.parentNode.outerHTML=&quot;<span class=\\&quot;nochart\\&quot;>—</span>&quot;;">'
        + '</a>';
    } else if (p && p.series && p.series.length >= 2) {
      const first = p.series[0], last = p.series[p.series.length - 1];
      const dir = last > first ? 'up' : (last < first ? 'down' : 'flat');
      chartHtml = '<div class="minichart minichart-' + dir + '">' + sparkline_(p.series, dir, 110, 36) + '</div>';
    } else if (p && p.series && p.series.length === 1) {
      chartHtml = '<span class="nochart">單點</span>';
    }
    // Use alert payload price (scanner-verified, same as Telegram) as primary source.
    // Fall back to Yahoo Finance value only if no alert price is available.
    const alertPrice = g.latestPrice;
    if (alertPrice != null && alertPrice > 0) {
      priceHtml = '<div class="price flat">'
        + '<span class="pv">' + n_(alertPrice, (alertPrice < 1 ? 3 : 2)) + '</span>'
        + '</div>';
    } else if (p && p.value != null) {
      // Sanity-check Yahoo % change — values > 30% are almost certainly stale/wrong data.
      const pct = (p.changePct == null || Math.abs(p.changePct) > 30) ? null : p.changePct;
      const dir = pct == null ? 'flat' : (pct >= 0 ? 'up' : 'down');
      const pctStr = pct == null ? '' : (pct >= 0 ? '+' : '') + n_(pct, 2) + '%';
      priceHtml = '<div class="price ' + dir + '">'
        + '<span class="pv">' + n_(p.value, (p.value < 1 ? 3 : 2)) + '</span>'
        + (pctStr ? '<span class="pc">' + pctStr + '</span>' : '')
        + '</div>';
    }

    // Signal pills (technical).
    const sigPills = g.signals.slice(0, 4).map(function (s) {
      const body = '<span class="spill">' + esc_(s.label) + '</span>';
      return s.link
        ? '<a class="splink" href="' + esc_(s.link) + '" target="_blank" rel="noopener">' + body + '</a>'
        : body;
    }).join(' ');

    // HKEX corp-action pills (no long content, only labels with link).
    const corpOrder = ['placement', 'increase', 'rights', 'block', 'other'];
    const corpPills = corpOrder.filter(function (t) { return g.corpTypes[t]; }).map(function (t) {
      const c = g.corpTypes[t];
      const body = '<span class="cpill cpill-' + t + '">'
        + corpTypeLabel_(t)
        + (c.count > 1 ? ' <em>×' + c.count + '</em>' : '')
        + '</span>';
      return c.link
        ? '<a class="cplink" href="' + esc_(c.link) + '" target="_blank" rel="noopener">' + body + '</a>'
        : body;
    }).join(' ');

    const hasCorp = g.corpCount > 0 ? '1' : '0';
    const hasTech = g.techCount > 0 ? '1' : '0';

    const lastTime = fmtTime_(g.latestRaw);
    const lastDate = fmtDate_(g.latestRaw);

    const linkBits = [];
    if (hkexHref) linkBits.push('<a class="lnk lnk-hk" href="' + esc_(hkexHref) + '" target="_blank" rel="noopener" title="HKEX 披露易">HKEX</a>');

    return ''
      + '<tr class="urow"'
      + ' data-code="' + esc_(codeStr) + '"'
      + ' data-name="' + esc_(g.name) + '"'
      + ' data-date="' + esc_(lastDate) + '"'
      + ' data-corp="' + hasCorp + '"'
      + ' data-tech="' + hasTech + '"'
      + '>'
      + '<td class="cell-code">'
      +   '<div class="code">' + esc_(codeStr) + '</div>'
      +   (g.name ? '<div class="name">' + esc_(g.name) + '</div>' : '')
      + '</td>'
      + '<td class="cell-chart">' + chartHtml + '</td>'
      + '<td class="cell-price">' + (priceHtml || '<span class="muted">—</span>') + '</td>'
      + '<td class="cell-pills">'
      +   (sigPills || '<span class="muted">—</span>')
      +   (corpPills ? '<div class="cpillrow">' + corpPills + '</div>' : '')
      + '</td>'
      + '<td class="cell-num"><span class="cnum">' + (g.techCount + g.corpCount) + '</span></td>'
      + '<td class="cell-time">' + esc_(lastTime) + '</td>'
      + '<td class="cell-link">' + (linkBits.join(' ') || '—') + '</td>'
      + '</tr>';
  }).join('');

  const empty = groups.length === 0
    ? '<tr><td colspan="7" class="empty">暫無代號數據</td></tr>'
    : '';

  // 最近公告: compact list of latest HKEX corp-action releases. Shows only
  // label + date + code/name + HKEX link. No long titles or message bodies.
  const recentRows = recentCorps.map(function (r) {
    const t = r.type;
    const labelHtml = '<span class="cpill cpill-' + t + '">' + corpTypeLabel_(t) + '</span>';
    const codeBlock = r.code
      ? '<span class="ra-code">' + esc_(r.code) + '</span>'
        + (r.name ? '<span class="ra-name">' + esc_(r.name) + '</span>' : '')
      : '<span class="muted">—</span>';
    const shortDate = r.date ? r.date.slice(5) : '—';  // YYYY-MM-DD → MM-DD
    const dateHtml = '<span class="ra-date" title="' + esc_(r.date || '') + '">' + esc_(shortDate) + '</span>';
    const linkHtml = r.url
      ? '<a class="ra-link" href="' + esc_(r.url) + '" target="_blank" rel="noopener">HKEX</a>'
      : '<span class="muted">—</span>';
    return '<li class="ra-item">'
      + '<span class="ra-label">' + labelHtml + '</span>'
      + dateHtml
      + '<span class="ra-stk">' + codeBlock + '</span>'
      + linkHtml
      + '</li>';
  }).join('');
  const recentHtml = recentCorps.length
    ? '<ul class="ra-list">' + recentRows + '</ul>'
    : '<div class="ra-empty">暫無公告</div>';

  return '<!doctype html>\n'
    + '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
    + '<!-- auto-refresh via JS to preserve scroll position -->\n'
    + '<title>港股訊號儀表板</title>\n'
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
    + '.muted{color:var(--mute-2)}\n'
    + '.topbar{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.85);backdrop-filter:saturate(180%) blur(8px);-webkit-backdrop-filter:saturate(180%) blur(8px);border-bottom:1px solid var(--line)}\n'
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
    + '.wrap{max-width:1440px;margin:0 auto;padding:18px 20px 36px}\n'
    + '.section-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:20px 0 10px}\n'
    + '.section-head h2{margin:0;display:flex;align-items:center;gap:8px;font-size:11px;font-weight:600;color:var(--mute);text-transform:uppercase;letter-spacing:.16em}\n'
    + '.section-head h2 .ico{display:inline-flex;width:18px;height:18px;border-radius:6px;background:var(--primary-soft);color:var(--primary);align-items:center;justify-content:center}\n'
    + '.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}\n'
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
    + '.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}\n'
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
    + 'table{width:100%;border-collapse:collapse;table-layout:auto}\n'
    + 'thead th{background:var(--surface-soft);color:var(--mute);font-size:10px;text-align:left;padding:9px 14px;text-transform:uppercase;letter-spacing:.14em;font-weight:600;border-bottom:1px solid var(--line);white-space:nowrap}\n'
    + 'tbody td{padding:10px 14px;border-bottom:1px solid var(--line-soft);vertical-align:middle}\n'
    + 'tbody tr:last-child td{border-bottom:none}\n'
    + 'tbody tr:hover{background:var(--surface-soft)}\n'
    + '.cell-code{min-width:120px}\n'
    + '.cell-code .code{font:600 13px var(--font-mono);color:var(--text);font-variant-numeric:tabular-nums}\n'
    + '.cell-code .name{font-size:12px;color:var(--mute);margin-top:2px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n'
    + '.cell-chart{width:148px}\n'
    + '.minichart{display:block;width:110px;height:36px;border-radius:6px;background:var(--surface-soft);border:1px solid var(--line-soft);padding:1px;overflow:hidden}\n'
    + '.minichart .spark{display:block;width:100%;height:100%}\n'
    + '.minichart-up{border-color:var(--up-border)}\n'
    + '.minichart-down{border-color:var(--down-border)}\n'
    + '.chartimg-link{display:block;line-height:0}\n'
    + '.chartimg{display:block;width:140px;height:60px;object-fit:cover;border-radius:6px;border:1px solid var(--line-soft);background:#0b1220}\n'
    + '.chartimg-link:hover .chartimg{border-color:var(--primary-border);box-shadow:0 0 0 2px rgba(2,132,199,.18)}\n'
    + '.nochart{font-size:10px;color:var(--mute-2)}\n'
    + '.cell-price{width:96px;white-space:nowrap}\n'
    + '.price{display:flex;flex-direction:column;align-items:flex-start;gap:1px;font-variant-numeric:tabular-nums}\n'
    + '.price .pv{font:600 13px var(--font-mono);color:var(--text)}\n'
    + '.price .pc{font:600 11px var(--font-mono)}\n'
    + '.price.up .pc{color:var(--up)}\n'
    + '.price.down .pc{color:var(--down)}\n'
    + '.price.flat .pc{color:var(--mute-2)}\n'
    + '.cell-pills{min-width:220px}\n'
    + '.cell-time{color:var(--mute);font:500 12px var(--font-mono);font-variant-numeric:tabular-nums;white-space:nowrap}\n'
    + '.cell-num{font:600 13px var(--font-mono);color:var(--text);font-variant-numeric:tabular-nums;text-align:center}\n'
    + '.cell-num .cnum{display:inline-flex;align-items:center;justify-content:center;min-width:24px;padding:2px 8px;border-radius:999px;background:var(--surface-soft);border:1px solid var(--line);font-size:11px}\n'
    + '.cell-link{font-size:12px;white-space:nowrap}\n'
    + '.cell-link .lnk{display:inline-flex;align-items:center;justify-content:center;padding:3px 8px;border-radius:6px;border:1px solid var(--line);background:var(--surface);font:600 10px var(--font-sans);letter-spacing:.06em;color:var(--text-soft);margin-right:4px;text-decoration:none}\n'
    + '.cell-link .lnk:hover{border-color:var(--primary-border);background:var(--primary-soft);color:var(--primary);text-decoration:none}\n'
    + '.cell-link .lnk-hk:hover{border-color:var(--violet-border);background:var(--violet-soft);color:var(--violet)}\n'
    + '.spill{display:inline-flex;align-items:center;background:var(--primary-soft);color:#075985;border:1px solid var(--primary-border);font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px;margin:1px 3px 1px 0;line-height:1.5;white-space:nowrap}\n'
    + '.splink{text-decoration:none}.splink:hover .spill{filter:brightness(.97)}\n'
    + '.cpillrow{margin-top:4px;display:flex;flex-wrap:wrap;gap:3px}\n'
    + '.cplink{text-decoration:none}.cplink:hover .cpill{filter:brightness(.97)}\n'
    + '.cpill{display:inline-flex;align-items:center;font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:999px;line-height:1.5;border:1px solid transparent;letter-spacing:.02em}\n'
    + '.cpill em{font-style:normal;font-weight:600;margin-left:3px;opacity:.85}\n'
    + '.cpill-placement{background:var(--down-soft);color:var(--down);border-color:var(--down-border)}\n'
    + '.cpill-increase{background:var(--up-soft);color:var(--up);border-color:var(--up-border)}\n'
    + '.cpill-rights{background:var(--violet-soft);color:var(--violet);border-color:var(--violet-border)}\n'
    + '.cpill-block{background:var(--amber-soft);color:var(--amber);border-color:var(--amber-border)}\n'
    + '.cpill-other{background:var(--surface-soft);color:var(--mute);border-color:var(--line)}\n'
    + '.cnt.block{border-color:var(--amber-border);background:var(--amber-soft);color:var(--amber)}\n'
    + '.cnt.block b{color:var(--amber)}\n'
    + '.recent-card{padding:2px 0}\n'
    + '.ra-list{list-style:none;margin:0;padding:4px 10px;display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:0}\n'
    + '.ra-item{display:flex;align-items:center;gap:7px;padding:4px 4px;font-size:11.5px;border-bottom:1px solid var(--line-soft);min-width:0}\n'
    + '.ra-item:last-child{border-bottom:none}\n'
    + '.ra-label{flex:0 0 auto}\n'
    + '.ra-date{flex:0 0 auto;font:600 11px var(--font-mono);color:var(--text-soft);font-variant-numeric:tabular-nums;min-width:44px}\n'
    + '.ra-stk{flex:1 1 auto;display:flex;align-items:baseline;gap:5px;min-width:0;overflow:hidden}\n'
    + '.ra-code{font:600 11.5px var(--font-mono);color:var(--text);font-variant-numeric:tabular-nums}\n'
    + '.ra-name{color:var(--mute);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n'
    + '.ra-link{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;padding:2px 6px;border-radius:5px;border:1px solid var(--violet-border);background:var(--violet-soft);color:var(--violet);font:600 9px var(--font-sans);letter-spacing:.06em;text-decoration:none}\n'
    + '.ra-link:hover{filter:brightness(.97);text-decoration:none}\n'
    + '.ra-empty{padding:12px;color:var(--mute);text-align:center;font-size:12px}\n'
    + '@media (max-width:520px){.ra-list{grid-template-columns:1fr}}\n'
    + '.empty{text-align:center;color:var(--mute);padding:40px 16px;font-size:13px}\n'
    + '.foot{margin-top:24px;padding-top:14px;border-top:1px solid var(--line);text-align:center;color:var(--mute-2);font-size:11px}\n'
    + '@media (max-width:1024px){.kpis{grid-template-columns:repeat(2,1fr)}}\n'
    + '@media (max-width:820px){.cell-num,thead th:nth-child(5){display:none}}\n'
    + '@media (max-width:720px){.topbar-inner{padding:10px 14px;gap:10px}.brand-sub{display:none}.refresh-tag{display:none}.wrap{padding:14px}.toolbar{padding:10px}.input.search-in{min-width:140px}.cell-price,thead th:nth-child(3){display:none}.cell-time,thead th:nth-child(6){display:none}}\n'
    + '@media (max-width:520px){.cell-chart,thead th:nth-child(2){display:none}}\n'
    + '@media (prefers-color-scheme:dark){'
    + ':root{'
    + '--bg:#0f172a;--surface:#1e293b;--surface-soft:#162032;'
    + '--text:#f1f5f9;--text-soft:#cbd5e1;--mute:#64748b;--mute-2:#475569;'
    + '--line:#334155;--line-soft:#1e293b;'
    + '--primary:#38bdf8;--primary-soft:#0c2d44;--primary-border:#0369a1;'
    + '--up:#4ade80;--up-soft:#052e16;--up-border:#166534;'
    + '--down:#f87171;--down-soft:#2d0a0a;--down-border:#991b1b;'
    + '--violet:#a78bfa;--violet-soft:#1e1040;--violet-border:#5b21b6;'
    + '--amber:#fbbf24;--amber-soft:#1c0f00;--amber-border:#92400e}'
    + '.topbar{background:rgba(15,23,42,.92)}'
    + '.tabs{background:#1e293b}'
    + '.tab.active{background:#0f172a}'
    + '.input{background:var(--surface);color:var(--text)}'
    + 'tbody tr:hover{background:#162032}'
    + '}\n'
    + '</style></head><body>\n'
    + '<header class="topbar"><div class="topbar-inner">\n'
    + '<div class="brand">'
    + '<div class="logo"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 17 9 11 13 15 21 7"/><polyline points="14 7 21 7 21 14"/></svg></div>'
    + '<div class="brand-meta">'
    + '<span class="brand-title">港股訊號儀表板</span>'
    + '<span class="brand-sub">港股訊號 · HKEX</span>'
    + '</div></div>\n'
    + '<div class="topright">'
    + '<span class="dot" aria-hidden="true"></span>'
    + '<span class="tabular">更新於 ' + esc_(fmtTime_(snap.updated_at)) + '</span>'
    + '<span class="refresh-tag">自動更新 120秒</span>'
    + '</div>\n'
    + '</div></header>\n'
    + '<main class="wrap">\n'
    + '<div class="section-head"><h2><span class="ico"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></span>市場快照</h2></div>\n'
    + '<section class="kpis">'
    + kpi_('恒生指數', '恒指', snap.hsi, 0)
    + kpi_('恒指市盈率', '港股市盈率', snap.hsi_pe, 2)
    + kpi_('美匯指數', '美匯指數 (DXY)', snap.dxy, 2)
    + kpi_('波幅指數', '波幅指數 (VIX)', snap.vix, 2)
    + '</section>\n'
    + '<div class="section-head"><h2><span class="ico"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></span>代號彙總</h2></div>\n'
    + '<section class="card">\n'
    + '<div class="toolbar">\n'
    + '<div class="tlabel">代號彙總</div>\n'
    + '<div class="summary">'
    + '<span class="cnt placement">配股 <b>' + cntPlacement + '</b></span>'
    + '<span class="cnt increase">增持 <b>' + cntIncrease + '</b></span>'
    + '<span class="cnt rights">供股 <b>' + cntRights + '</b></span>'
    + '<span class="cnt block">大手轉倉 <b>' + cntBlock + '</b></span>'
    + '</div>\n'
    + '<div class="spacer"></div>\n'
    + '<div class="tabs" id="ftabs" role="tablist">'
    + '<button class="tab active" data-ftype="all">全部</button>'
    + '<button class="tab" data-ftype="tech">技術信號</button>'
    + '<button class="tab" data-ftype="corp">披露易</button>'
    + '<button class="tab" data-ftype="placement">配股</button>'
    + '<button class="tab" data-ftype="increase">增持</button>'
    + '<button class="tab" data-ftype="rights">供股</button>'
    + '<button class="tab" data-ftype="block">大手轉倉</button>'
    + '</div>\n'
    + '<div class="search">'
    + '<input id="tq" class="input search-in" type="search" placeholder="搜尋代號 / 名稱…" autocomplete="off">'
    + '<input id="tdate" class="input" type="date" title="篩選日期">'
    + '<button class="btn-ghost" id="tclear" type="button">清除</button>'
    + '</div>\n'
    + '</div>\n'
    + '<table><thead><tr>'
    + '<th>代號 / 名稱</th>'
    + '<th>走勢圖</th>'
    + '<th>價格</th>'
    + '<th>信號 / 公告</th>'
    + '<th>次數</th>'
    + '<th>最後出現</th>'
    + '<th>連結</th>'
    + '</tr></thead><tbody id="urows">' + rows + empty + '</tbody></table>\n'
    + '</section>\n'
    + '<div class="section-head"><h2><span class="ico"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l18-8-8 18-2-8-8-2z"/></svg></span>最近公告 (' + recentCorps.length + '/' + RECENT_CORPS_LIMIT + ')</h2></div>\n'
    + '<section class="card recent-card">' + recentHtml + '</section>\n'
    + '<div class="foot">港股訊號雲 · Google Apps Script · 真實數據</div>\n'
    + '</main>\n'
    + '<script>\n'
    + '(function(){\n'
    + 'var rows=document.querySelectorAll("#urows .urow");\n'
    + 'var ftabs=document.querySelectorAll("#ftabs .tab");\n'
    + 'var tq=document.getElementById("tq");\n'
    + 'var td=document.getElementById("tdate");\n'
    + 'var tc=document.getElementById("tclear");\n'
    + 'var ftype="all";\n'
    + 'function apply(){\n'
    + '  var q=(tq&&tq.value||"").trim().toLowerCase();\n'
    + '  var d=(td&&td.value||"").trim();\n'
    + '  rows.forEach(function(r){\n'
    + '    var name=(r.getAttribute("data-name")||"").toLowerCase();\n'
    + '    var code=(r.getAttribute("data-code")||"").toLowerCase();\n'
    + '    var date=(r.getAttribute("data-date")||"");\n'
    + '    var hasCorp=r.getAttribute("data-corp")==="1";\n'
    + '    var hasTech=r.getAttribute("data-tech")==="1";\n'
    + '    var hasPlacement=!!r.querySelector(".cpill-placement");\n'
    + '    var hasIncrease=!!r.querySelector(".cpill-increase");\n'
    + '    var hasRights=!!r.querySelector(".cpill-rights");\n'
    + '    var hasBlock=!!r.querySelector(".cpill-block");\n'
    + '    var ftOK=true;\n'
    + '    if(ftype==="tech")ftOK=hasTech;\n'
    + '    else if(ftype==="corp")ftOK=hasCorp;\n'
    + '    else if(ftype==="placement")ftOK=hasPlacement;\n'
    + '    else if(ftype==="increase")ftOK=hasIncrease;\n'
    + '    else if(ftype==="rights")ftOK=hasRights;\n'
    + '    else if(ftype==="block")ftOK=hasBlock;\n'
    + '    var mq=(!q||name.indexOf(q)>=0||code.indexOf(q)>=0);\n'
    + '    var md=(!d||date===d);\n'
    + '    r.style.display=(ftOK&&mq&&md)?"":"none";\n'
    + '  });\n'
    + '}\n'
    + 'ftabs.forEach(function(t){t.addEventListener("click",function(){ftabs.forEach(function(x){x.classList.remove("active");});t.classList.add("active");ftype=t.getAttribute("data-ftype")||"all";apply();});});\n'
    + 'if(tq)tq.addEventListener("input",apply);\n'
    + 'if(td)td.addEventListener("change",apply);\n'
    + 'if(tc)tc.addEventListener("click",function(){if(tq)tq.value="";if(td)td.value="";ftabs.forEach(function(x){x.classList.remove("active");});var allBtn=document.querySelector("#ftabs .tab[data-ftype=\\"all\\"]");if(allBtn)allBtn.classList.add("active");ftype="all";apply();});\n'
    + '})();\n'
    + '(function(){\n'
    + 'var saved=sessionStorage.getItem("dashScroll");\n'
    + 'if(saved){window.scrollTo(0,parseInt(saved,10));sessionStorage.removeItem("dashScroll");}\n'
    + 'setTimeout(function(){sessionStorage.setItem("dashScroll",String(window.scrollY));location.reload();},120000);\n'
    + '})();\n'
    + '</script>\n'
    + '</body></html>';
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
