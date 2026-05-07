const SPREADSHEET_ID = '129IieKTIfssX18O_PfnRoxbx3c12UoCPQ_MxxBizgeA';
const ALERT_SHEET = 'Alerts';
const GAS_SECRET = 'CHANGE_ME_TO_REPO_SECRET';

const HEADERS = [
  'created_at', 'source', 'category', 'code', 'symbol', 'name', 'signal',
  'timeframe', 'price', 'message', 'strategy', 'chart_url', 'source_url',
  'tags', 'poc_6m', 'poc_12m', 'priority', 'raw'
];

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');
    if (GAS_SECRET && GAS_SECRET !== 'CHANGE_ME_TO_REPO_SECRET' && payload.secret !== GAS_SECRET) {
      return json_({ ok: false, error: 'secret_mismatch' }, 401);
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
    return json_({ ok: false, error: String(err) }, 500);
  }
}

function doGet() {
  const alerts = getAlerts_();
  const snap = getMarketSnapshot_();
  return HtmlService.createHtmlOutput(render_(alerts, snap))
    .setTitle('HK Alert Cloud Dashboard')
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
  }).reverse().slice(0, 300);
}

function fetchYahoo_(symbol) {
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=5d`;
    const json = JSON.parse(UrlFetchApp.fetch(url, { muteHttpExceptions: true }).getContentText());
    const r = json.chart.result[0];
    const meta = r.meta;
    const last = meta.regularMarketPrice;
    const prev = meta.chartPreviousClose || meta.previousClose;
    const change = (last != null && prev) ? last - prev : null;
    const changePct = (change != null && prev) ? change / prev * 100 : null;
    return { value: last, change, changePct, source: `Yahoo Finance (${symbol})`, stale: false };
  } catch (err) {
    return { value: null, change: null, changePct: null, source: `Yahoo Finance (${symbol})`, stale: true };
  }
}

function getFearGreed_() {
  try {
    const json = JSON.parse(UrlFetchApp.fetch('https://production.dataviz.cnn.io/index/fearandgreed/graphdata', { muteHttpExceptions: true }).getContentText());
    const v = Number(json.fear_and_greed.score);
    return { value: v, source: 'CNN Fear & Greed', stale: false };
  } catch (err) {
    return { value: null, source: 'CNN Fear & Greed', stale: true };
  }
}

function getHsiPe_() {
  try {
    const html = UrlFetchApp.fetch('https://worldperatio.com/area/hong-kong/', { muteHttpExceptions: true }).getContentText();
    const m = html.match(/Hong Kong Stock Market[\s\S]{0,600}?P\/E Ratio[\s\S]{0,300}?(\d{1,3}\.\d{1,2})/i)
      || html.match(/Hong Kong Stock Market[\s\S]{0,600}?(\d{1,3}\.\d{1,2})/i)
      || html.match(/P\/E Ratio[\s\S]{0,300}?(\d{1,3}\.\d{1,2})/i);
    return { value: m ? Number(m[1]) : null, source: 'World PE Ratio - Hong Kong', stale: !m };
  } catch (err) {
    return { value: null, source: 'World PE Ratio - Hong Kong', stale: true };
  }
}

function getMarketSnapshot_() {
  return {
    hsi_pe: getHsiPe_(),
    fear_greed: getFearGreed_(),
    dxy: fetchYahoo_('DX-Y.NYB'),
    vix: fetchYahoo_('^VIX'),
    updated_at: new Date().toISOString()
  };
}

function n_(v, d) {
  if (v == null || v === '') return '—';
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

function esc_(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function kpi_(label, hint, item, decimals) {
  return `<div class="kpi"><div class="klabel">${label}</div><div class="khint">${hint}</div><div class="kvalue">${n_(item.value, decimals)}</div><div class="ksource">${esc_(item.source)}${item.stale ? ' · stale' : ''}</div></div>`;
}

function render_(alerts, snap) {
  const counts = alerts.reduce((acc, a) => {
    const k = a.category || 'unknown';
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
  const rows = alerts.map(a => `
    <article class="alert ${esc_(a.category)}">
      <div class="top"><span class="badge">${esc_(a.category)}</span><span class="code">${esc_(a.code)} ${esc_(a.name)}</span><span class="time">${esc_(a.created_at)}</span></div>
      <h3>${esc_(a.signal)}</h3>
      <p>${esc_(a.message)}</p>
      <div class="meta">Price ${esc_(a.price)} · POC6M ${esc_(a.poc_6m)} · POC12M ${esc_(a.poc_12m)}</div>
      <div class="links">${a.chart_url ? `<a href="${esc_(a.chart_url)}" target="_blank">TradingView</a>` : ''}${a.source_url ? `<a href="${esc_(a.source_url)}" target="_blank">Source</a>` : ''}</div>
    </article>`).join('');
  return `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>HK Alert Cloud Dashboard</title>
<style>
body{margin:0;background:#090d12;color:#e5e7eb;font-family:Inter,Arial,sans-serif}
header{padding:18px 24px;border-bottom:1px solid #1f2937;display:flex;justify-content:space-between;gap:16px}
h1{font-size:18px;margin:0}.sub{font-size:12px;color:#94a3b8}.wrap{padding:18px 24px;max-width:1400px;margin:auto}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.kpi,.summary,.alert{background:#111820;border:1px solid #1f2937;border-radius:12px;padding:14px}
.klabel{font-size:11px;color:#93c5fd;text-transform:uppercase}.khint,.ksource,.meta,.time{font-size:11px;color:#94a3b8}.kvalue{font:700 24px ui-monospace,monospace;margin:8px 0}
.summary{margin:14px 0;display:flex;gap:28px}.summary b{color:#fbbf24}
.feed{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.top{display:flex;gap:10px;align-items:center}.badge{background:#f59e0b;color:#111827;border-radius:5px;padding:3px 7px;font-size:11px;font-weight:700}.code{font-weight:700}
h3{font-size:15px;color:#5eead4;margin:10px 0 8px}.alert p{font-size:13px;color:#cbd5e1}.links a{color:#60a5fa;margin-right:12px;font-size:12px}
@media(max-width:800px){.grid,.feed{grid-template-columns:1fr}header{display:block}.summary{display:grid;grid-template-columns:repeat(2,1fr)}}
</style></head>
<body><header><div><h1>HK Alert Cloud Dashboard</h1><div class="sub">GitHub Actions · Google Apps Script · Telegram · Real data only</div></div><div class="sub">Updated ${esc_(snap.updated_at)}</div></header>
<main class="wrap">
<section class="grid">${kpi_('HSI PE','Hong Kong',snap.hsi_pe,2)}${kpi_('Fear & Greed','CNN',snap.fear_greed,0)}${kpi_('DXY','US Dollar Index',snap.dxy,2)}${kpi_('VIX','Volatility',snap.vix,2)}</section>
<section class="summary"><div>Total <b>${alerts.length}</b></div><div>IPO <b>${counts.ipo||0}</b></div><div>POC <b>${counts.poc||0}</b></div><div>公告 <b>${counts.corp_action||0}</b></div></section>
<section class="feed">${rows || '<div class="alert">暫時未有 alert。</div>'}</section>
</main></body></html>`;
}

function json_(obj, status) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
