(function () {
  const nav = document.getElementById('sharedSiteNav');
  if (!nav) return;
  const base = (nav.dataset.base || './').replace(/\/+$/, '/');

  const items = [
    ['index.html', '📦 Market'],
    ['signals.html', '🔔 訊號'],
    ['watchlist.html', '⭐ 自選'],
    ['history.html', '🕐 歷史'],
    ['gap_fvg.html', '⤴ Gap/FVG'],
    ['fundflow.html', '💰 資金'],
    ['rights_analysis.html', '📋 供配股'],
    ['daily_trade_prompt.html', '🚦 每日提示'],
    ['timing_analysis.html', '⏱ 時間窗口'],
    ['distribution_day.html', '📉 分佈日'],
    ['vqc_analysis.html', '📈 成交轉勢日'],
    ['docs/ccass-warroom.html', '⚡ 戰情室'],
    ['us.html', '🇺🇸 美股'],
    ['guide.html', '📖 說明'],
  ];

  const path = location.pathname.toLowerCase();
  nav.innerHTML = items.map(([href, label]) => {
    const rel = href.toLowerCase().replace(/^\.\//, '');
    const active = path.endsWith('/' + rel) || (path === '/' && rel === 'index.html');
    return `<a href="${base}${href}"${active ? ' class="active"' : ''}>${label}</a>`;
  }).join('');
})();
