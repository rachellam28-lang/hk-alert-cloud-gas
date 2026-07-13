const UPSTREAM_HOST = 'web.ifzq.gtimg.cn';
const MAX_BARS = 260;

function json(payload, status = 200, cacheControl = 'no-store') {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': cacheControl,
      'x-content-type-options': 'nosniff',
    },
  });
}

function normalizeCode(value) {
  const digits = String(value || '').trim();
  if (!/^\d{1,5}$/.test(digits)) return '';
  return String(Number.parseInt(digits, 10)).padStart(5, '0');
}

function finitePositive(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function normalizeBar(row) {
  if (!Array.isArray(row) || row.length < 6) return null;
  const time = String(row[0] || '').slice(0, 10);
  const open = finitePositive(row[1]);
  const close = finitePositive(row[2]);
  const high = finitePositive(row[3]);
  const low = finitePositive(row[4]);
  const volume = Number(row[5]);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(time) || [open, close, high, low].some(value => value === null)) return null;
  if (high < Math.max(open, close, low) || low > Math.min(open, close, high)) return null;
  return {
    time,
    open,
    high,
    low,
    close,
    volume: Number.isFinite(volume) && volume >= 0 ? volume : 0,
    turnover: null,
  };
}

export async function onRequestGet(context) {
  const code = normalizeCode(context.params.code);
  if (!code) return json({ error: 'invalid_hk_code' }, 400);

  const requestUrl = new URL(context.request.url);
  const requestedCount = Number.parseInt(requestUrl.searchParams.get('count') || String(MAX_BARS), 10);
  const count = Math.max(30, Math.min(MAX_BARS, Number.isFinite(requestedCount) ? requestedCount : MAX_BARS));
  const upstreamSymbol = `hk${code}`;
  const upstreamUrl = new URL(`https://${UPSTREAM_HOST}/appstock/app/kline/kline`);
  upstreamUrl.searchParams.set('param', `${upstreamSymbol},day,,,${count}`);

  let upstream;
  try {
    upstream = await fetch(upstreamUrl.toString(), {
      headers: { accept: 'application/json' },
      cf: { cacheEverything: true, cacheTtl: 300 },
    });
  } catch (error) {
    return json({ error: 'upstream_unreachable', detail: String(error && error.message || error) }, 502);
  }
  if (!upstream.ok) return json({ error: 'upstream_http_error', status: upstream.status }, 502);

  let payload;
  try {
    payload = await upstream.json();
  } catch {
    return json({ error: 'upstream_invalid_json' }, 502);
  }
  const node = payload && payload.data && payload.data[upstreamSymbol];
  const bars = (node && Array.isArray(node.day) ? node.day : []).map(normalizeBar).filter(Boolean).slice(-count);
  if (!bars.length) return json({ error: 'symbol_or_kbar_not_found', code }, 404, 'public, max-age=60, s-maxage=300');

  bars.sort((a, b) => a.time.localeCompare(b.time));
  const last = bars[bars.length - 1];
  const previous = bars.length > 1 ? bars[bars.length - 2] : last;
  const changeValue = last.close - previous.close;
  const qt = node && node.qt && Array.isArray(node.qt[upstreamSymbol]) ? node.qt[upstreamSymbol] : [];
  const symbol = `${Number.parseInt(code, 10)}.HK`;
  const now = new Date().toISOString();
  return json({
    updated_at: now,
    source: 'Tencent public HK daily K-line (unadjusted)',
    entry: {
      symbol,
      label: String(qt[1] || code),
      market: 'hk',
      aliases: [code, String(Number.parseInt(code, 10)), `HKEX:${code}`, `HKEX:${Number.parseInt(code, 10)}`],
      quote: {
        symbol,
        last: last.close,
        open: last.open,
        high: last.high,
        low: last.low,
        prev_close: previous.close,
        change_value: changeValue,
        change_percentage: previous.close ? changeValue / previous.close * 100 : null,
        volume: last.volume,
        turnover: null,
        status: 'on-demand-cache',
        trade_date: last.time,
      },
      series: { '1d': bars },
      series_meta: {
        '1d': { count: bars.length, stale: false, error: null, source: 'Tencent public HK daily K-line (unadjusted)' },
      },
      ccass: null,
    },
  }, 200, 'public, max-age=300, s-maxage=300, stale-while-revalidate=600');
}
