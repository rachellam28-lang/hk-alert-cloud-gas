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
  const normalized = path.replace(/\/+$/, '');
  nav.innerHTML = items.map(([href, label]) => {
    const rel = href.toLowerCase().replace(/^\.\//, '');
    const active = normalized.endsWith('/' + rel) || (rel === 'index.html' && path.endsWith('/'));
    return `<a href="${base}${href}"${active ? ' class="active"' : ''}>${label}</a>`;
  }).join('');

  let patchTimer = null;
  const patchLabels = () => {
    const rightsBtn = document.getElementById('filterRights');
    if (rightsBtn && rightsBtn.textContent.trim() === '供股') rightsBtn.textContent = '供股公告';

    const dualBtn = document.getElementById('conBtnDual');
    if (dualBtn && dualBtn.textContent.indexOf('雙向') !== -1 && !dualBtn.textContent.includes('訊號')) {
      dualBtn.textContent = '💎雙向訊號';
    }

    document.querySelectorAll('.cpill-rights').forEach(el => {
      if (el.dataset.labelPatched === '1') return;
      el.innerHTML = el.innerHTML.replace(/供股(?!公告)/g, '供股公告');
      el.dataset.labelPatched = '1';
    });

    document.querySelectorAll('.cpill-con-dual').forEach(el => {
      if (el.dataset.labelPatched === '1') return;
      el.innerHTML = el.innerHTML.replace(/💎雙向(?!訊號)/g, '💎雙向訊號');
      el.dataset.labelPatched = '1';
    });

    document.querySelectorAll('.scnt').forEach(el => {
      if (el.dataset.labelPatched === '1') return;
      if (el.textContent.trim().startsWith('供股 ')) {
        el.innerHTML = el.innerHTML.replace('供股 ', '供股公告 ');
        el.dataset.labelPatched = '1';
      }
    });
  };

  const schedulePatch = () => {
    clearTimeout(patchTimer);
    patchTimer = setTimeout(patchLabels, 25);
  };

  schedulePatch();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedulePatch, { once: true });
  }
  new MutationObserver(schedulePatch).observe(document.documentElement, { childList: true, subtree: true });
})();
