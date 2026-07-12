(function () {
  const nav = document.getElementById('sharedSiteNav') || document.querySelector('nav.site-nav');
  if (!nav) return;
  nav.id = 'sharedSiteNav';
  nav.classList.add('site-nav');

  const base = (nav.dataset.base || './').replace(/\/+$/, '/');
  const primary = [
    ['index.html', '\ud83d\udce6 Market'],
    ['signals.html', '\ud83d\udd02 \u8a0a\u865f'],
    ['watchlist.html', '\u2b50 \u81ea\u9078'],
    ['momentum_list.html', '\u26a1 \u52d5\u91cf\u540d\u55ae'],
    ['kbar_matrix.html', '\ud83d\udcc8 Kbar'],
    ['history.html', '\ud83d\udd52 \u6b77\u53f2'],
    ['daily_trade_prompt.html', '\ud83e\udebE \u6bcf\u65e5\u63d0\u793a'],
    ['gap_fvg.html', '\ud83e\udded Gap/FVG'],
    ['fundflow.html', '\ud83d\udcb5 \u8cc7\u91d1'],
    ['rights_analysis.html', '\ud83d\udcf5 \u4f9b\u914d\u80a1'],
    ['rotation_matrix.html', '\ud83d\udcc8 \u677f\u584a\u8f2a\u52d5'],
  ];
  const groups = [
    ['CCASS', [
      ['docs/ccass-warroom.html', '\u2694 \u6230\u60c5\u5ba4'],
    ]],
    ['\u6642\u9593', [
      ['timing_analysis.html', '\u23f0 \u6642\u9593\u7a97\u53e3'],
      ['jieqi_analysis.html', '\ud83e\udebB \u7bc0\u6c23\u7a97\u53e3'],
      ['distribution_day.html', '\ud83d\udcf2 \u5206\u4f48\u65e5'],
      ['vqc_analysis.html', '\ud83d\udcf1 \u6210\u4ea4\u8f49\u52e2\u65e5'],
    ]],
    ['\u8aaa\u660e', [['guide.html', '\ud83d\udcc9 \u7cfb\u7d71\u8aaa\u660e']]],
  ];

  const path = location.pathname.toLowerCase().replace(/\/+$/, '');
  const active = href => {
    const rel = href.toLowerCase().replace(/^\.\//, '');
    return path.endsWith('/' + rel) || (rel === 'index.html' && (path.endsWith('/') || !path));
  };
  const link = ([href, label]) => `<a href="${base}${href}"${active(href) ? ' class="active" aria-current="page"' : ''}>${label}</a>`;
  const secondaryActive = groups.some(([, items]) => items.some(([href]) => active(href)));
  const groupMarkup = groups.map(([label, items]) => `
    <section class="suite-nav-group">
      <strong>${label}</strong>
      ${items.map(link).join('')}
    </section>`).join('');
  nav.innerHTML = `
    <div class="suite-nav-primary">${primary.map(link).join('')}</div>
    <details class="suite-nav-more"${secondaryActive ? ' open' : ''}>
      <summary${secondaryActive ? ' class="active"' : ''}>\u66f4\u591a</summary>
      <div class="suite-nav-panel">${groupMarkup}</div>
    </details>`;

  if (!document.getElementById('sharedNavStyles')) {
    const style = document.createElement('style');
    style.id = 'sharedNavStyles';
    style.textContent = `
      #sharedSiteNav{position:sticky;top:0;z-index:80;display:flex;align-items:center;gap:6px;padding:6px 10px;background:#101827;border-bottom:1px solid #263247;font:600 12px/1.2 system-ui,sans-serif;overflow:visible}
      #sharedSiteNav .suite-nav-primary{display:flex;gap:3px;min-width:0;overflow-x:auto;scrollbar-width:none}
      #sharedSiteNav .suite-nav-primary::-webkit-scrollbar{display:none}
      #sharedSiteNav a,#sharedSiteNav summary{display:inline-flex;align-items:center;min-height:30px;padding:6px 9px;border-radius:5px;color:#aeb9c9;text-decoration:none;white-space:nowrap;cursor:pointer;transition:background .18s,color .18s,transform .1s}
      #sharedSiteNav a:hover,#sharedSiteNav summary:hover{background:#1b2739;color:#fff}
      #sharedSiteNav a:active,#sharedSiteNav summary:active{transform:translateY(1px)}
      #sharedSiteNav a:focus-visible,#sharedSiteNav summary:focus-visible{outline:2px solid #63c7ca;outline-offset:2px}
      #sharedSiteNav a.active,#sharedSiteNav summary.active{background:#16383c;color:#7de0db}
      #sharedSiteNav .suite-nav-more{position:relative;margin-left:auto;flex:0 0 auto}
      #sharedSiteNav summary{list-style:none}
      #sharedSiteNav summary::-webkit-details-marker{display:none}
      #sharedSiteNav summary::after{content:'\\25be';margin-left:6px;font-size:9px}
      #sharedSiteNav .suite-nav-panel{position:absolute;right:0;top:36px;width:min(520px,calc(100vw - 16px));display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:12px;background:#101827;border:1px solid #334155;border-radius:7px;box-shadow:0 16px 40px rgba(4,10,20,.28)}
      #sharedSiteNav .suite-nav-group{display:grid;align-content:start;gap:2px}
      #sharedSiteNav .suite-nav-group strong{padding:4px 9px;color:#65758a;font-size:10px;text-transform:uppercase}
      body{font-variant-numeric:tabular-nums}
      .status-loading,.status-error,.status-empty{padding:18px;text-align:center;border:1px solid #d8dee8;border-radius:6px;background:#f6f8fb;color:#64748b}
      .status-error{border-color:#efb5b9;background:#fff1f2;color:#a52b34}
      button,a,input,select,summary{transition:border-color .18s,background-color .18s,color .18s,transform .1s}
      button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid #0f7f87;outline-offset:2px}
      @media(max-width:640px){#sharedSiteNav{padding:5px 6px;gap:3px}#sharedSiteNav a,#sharedSiteNav summary{min-height:28px;padding:5px 7px;font-size:11px}#sharedSiteNav .suite-nav-panel{position:fixed;top:40px;right:6px;grid-template-columns:1fr 1fr;max-height:calc(100dvh - 50px);overflow:auto}}
    `;
    document.head.appendChild(style);
  }

  document.addEventListener('click', event => {
    const more = nav.querySelector('.suite-nav-more');
    if (more && more.open && !more.contains(event.target)) more.open = false;
  });
})();
