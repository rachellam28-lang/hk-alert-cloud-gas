(function () {
  const nav = document.getElementById('sharedSiteNav') || document.querySelector('nav.site-nav');
  if (!nav) return;
  nav.id = 'sharedSiteNav';
  nav.classList.add('site-nav');

  const base = (nav.dataset.base || './').replace(/\/+$/, '/');
  const primary = [
    ['trading_desk.html', '交易台'],
    ['index.html', 'Market'],
    ['signals.html', '\u8a0a\u865f'],
    ['smallcap_playbook.html', '\u7d30\u50f9\u80a1'],
    ['kbar_matrix.html', 'Kbar'],
    ['momentum_list.html', '\u52d5\u91cf', 'nav-desktop'],
    ['watchlist.html', '\u81ea\u9078', 'nav-desktop'],
  ];
  const groups = [
    ['\u63c0\u80a1', [
      ['momentum_list.html', '\u52d5\u91cf\u540d\u55ae'],
      ['rotation_matrix.html', '\u677f\u584a\u8f2a\u52d5'],
      ['fundflow.html', '\u8cc7\u91d1\u6d41'],
      ['watchlist.html', '\u81ea\u9078\u80a1'],
    ]],
    ['\u4e8b\u4ef6', [
      ['rights_analysis.html', '\u4f9b\u914d\u80a1'],
      ['docs/ccass-warroom.html', 'CCASS \u6230\u60c5\u5ba4'],
    ]],
    ['\u6642\u5e8f', [
      ['vqc_analysis.html', '\u6210\u4ea4\u8f49\u52e2\u65e5'],
      ['timing_analysis.html', '\u6642\u9593\u7a97\u53e3'],
      ['jieqi_analysis.html', '\u7bc0\u6c23\u7a97\u53e3'],
      ['distribution_day.html', '\u5206\u4f48\u65e5'],
    ]],
    ['\u8a18\u9304', [
      ['history.html', '\u8a0a\u865f\u6b77\u53f2'],
      ['guide.html', '\u7cfb\u7d71\u8aaa\u660e'],
    ]],
  ];

  const path = location.pathname.toLowerCase().replace(/\/+$/, '');
  const darkTools = ['/kbar_matrix', '/kbar_matrix.html', '/docs/ccass-warroom', '/docs/ccass-warroom.html'];
  const useUnifiedLightTheme = !darkTools.some(item => path.endsWith(item));
  document.documentElement.classList.toggle('suite-light', useUnifiedLightTheme);
  const active = href => {
    const rel = href.toLowerCase().replace(/^\.\//, '');
    return path.endsWith('/' + rel) || (rel === 'index.html' && (path.endsWith('/') || !path));
  };
  const link = ([href, label, extraClass]) => {
    const classes = [extraClass, active(href) ? 'active' : ''].filter(Boolean).join(' ');
    return `<a href="${base}${href}"${classes ? ` class="${classes}"` : ''}${active(href) ? ' aria-current="page"' : ''}>${label}</a>`;
  };
  const primaryActive = primary.some(([href]) => active(href));
  const secondaryActive = !primaryActive && groups.some(([, items]) => items.some(([href]) => active(href)));
  const groupMarkup = groups.map(([label, items]) => `
    <section class="suite-nav-group">
      <strong>${label}</strong>
      ${items.map(link).join('')}
    </section>`).join('');
  nav.setAttribute('aria-label', '\u4e3b\u5c0e\u822a');
  nav.innerHTML = `
    <div class="suite-nav-primary">${primary.map(link).join('')}</div>
    <details class="suite-nav-more">
      <summary${secondaryActive ? ' class="active"' : ''}>\u66f4\u591a</summary>
      <div class="suite-nav-panel">${groupMarkup}</div>
    </details>`;

  if (!document.getElementById('sharedNavStyles')) {
    const style = document.createElement('style');
    style.id = 'sharedNavStyles';
    style.textContent = `
      #sharedSiteNav{position:sticky;top:0;z-index:80;display:flex;align-items:center;gap:6px;padding:6px 10px;background:#101827;border-bottom:1px solid #263247;font:600 12px/1.2 system-ui,sans-serif;overflow:visible}
      #sharedSiteNav .suite-nav-primary{display:flex;align-items:center;gap:3px;min-width:0;overflow-x:auto;scrollbar-width:none}
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
      #sharedSiteNav .suite-nav-panel{position:absolute;right:0;top:36px;width:min(720px,calc(100vw - 16px));display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:10px;background:#101827;border:1px solid #334155;border-radius:7px;box-shadow:0 16px 40px rgba(4,10,20,.28)}
      #sharedSiteNav .suite-nav-group{display:grid;align-content:start;gap:2px}
      #sharedSiteNav .suite-nav-group strong{padding:4px 9px;color:#7f90a7;font-size:10px}
      body{font-variant-numeric:tabular-nums}
      html.suite-light{
        color-scheme:light;
        --bg:#edf1f3!important;--surface:#fff!important;--surface-2:#f5f7f8!important;
        --surface-soft:#f5f7f8!important;--panel:#fff!important;--panel2:#f5f7f8!important;
        --text:#17202b!important;--txt:#17202b!important;--text-soft:#3d4b59!important;
        --soft:#3d4b59!important;--muted:#697887!important;--dim:#697887!important;
        --mute:#697887!important;--mute-2:#8b98a5!important;--line:#d5dde4!important;
        --line-soft:#e6ebef!important;--shadow:0 1px 2px rgba(31,45,58,.06)!important
      }
      html.suite-light body{background:#edf1f3!important;color:#17202b!important}
      html.suite-light .hero,html.suite-light .card,html.suite-light .panel,html.suite-light .mini,
      html.suite-light .detail,html.suite-light .event-card,html.suite-light .action-btn,
      html.suite-light .control,html.suite-light .pager button,html.suite-light .inspector-empty,
      html.suite-light .market-cell,html.suite-light .day-section,html.suite-light .summary-item{
        background:#fff!important;color:#17202b!important;border-color:#d5dde4!important;box-shadow:none!important
      }
      html.suite-light .topbar,html.suite-light .nav,html.suite-light .day-header,
      html.suite-light th,html.suite-light thead th,html.suite-light .drawer-head{
        background:#f5f7f8!important;color:#697887!important;border-color:#d5dde4!important
      }
      html.suite-light td,html.suite-light .lane,html.suite-light .detail-section,
      html.suite-light .market-tape,html.suite-light .context-band,html.suite-light .table-wrap,
      html.suite-light .rotation-row,html.suite-light .timeline-row{
        border-color:#d5dde4!important
      }
      html.suite-light tbody tr:hover,html.suite-light tbody tr.selected,
      html.suite-light .action-btn:hover,html.suite-light .card-head:hover{
        background:#f3f7f8!important;color:#17202b!important
      }
      html.suite-light .action-btn.active,html.suite-light .tab.active,
      html.suite-light .setup-btn.active{background:#e4f2f1!important;color:#075f66!important;border-color:#70aaa9!important}
      html.suite-light input,html.suite-light select,html.suite-light button{
        background:#fff!important;color:#17202b!important;border-color:#cbd5dd!important
      }
      html.suite-light .search-box input,html.suite-light .search-row input,html.suite-light .tab,
      html.suite-light .btn,html.suite-light .fbtn{
        background:#fff!important;color:#3d4b59!important;border-color:#d5dde4!important
      }
      html.suite-light .btn.active,html.suite-light .btn.blue,html.suite-light .btn.teal{
        background:#e4f2f1!important;color:#075f66!important;border-color:#70aaa9!important
      }
      html.suite-light .btn.gold{background:#fff4d6!important;color:#8a6100!important;border-color:#dfbd57!important}
      html.suite-light .btn.red{background:#fde9eb!important;color:#a52b34!important;border-color:#df949a!important}
      html.suite-light .subtitle,html.suite-light .hero-meta,html.suite-light .section-note,
      html.suite-light .lead,html.suite-light .stamp,html.suite-light .quiet,
      html.suite-light .thesis,html.suite-light .footer,html.suite-light .foot{
        color:#697887!important
      }
      html.suite-light .log-track{background:#e3e9ee!important;border-color:#cbd5dd!important}
      html.suite-light .trade-buy,html.suite-light .supply-stock,html.suite-light .issuer-low,
      html.suite-light .issuer-react-up,html.suite-light .year-open-up{background:#e5f5ea!important;color:#19733c!important}
      html.suite-light .trade-wait,html.suite-light .supply-watch{background:#fff4d6!important;color:#8a6100!important}
      html.suite-light .trade-avoid,html.suite-light .supply-cash,html.suite-light .issuer-high,
      html.suite-light .issuer-react-down,html.suite-light .year-open-down{background:#fde9eb!important;color:#a52b34!important}
      html.suite-light .issuer-neutral,html.suite-light .issuer-react-neutral,
      html.suite-light .supply-ended,html.suite-light .year-open-missing{background:#f1f4f6!important;color:#697887!important}
      .status-loading,.status-error,.status-empty{padding:18px;text-align:center;border:1px solid #d8dee8;border-radius:6px;background:#f6f8fb;color:#64748b}
      .status-error{border-color:#efb5b9;background:#fff1f2;color:#a52b34}
      button,a,input,select,summary{transition:border-color .18s,background-color .18s,color .18s,transform .1s}
      button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid #0f7f87;outline-offset:2px}
      @media(max-width:640px){#sharedSiteNav{padding:5px 6px;gap:2px}#sharedSiteNav a,#sharedSiteNav summary{min-height:28px;padding:5px 7px;font-size:11px}#sharedSiteNav .nav-desktop{display:none}#sharedSiteNav .suite-nav-primary{overflow:visible}#sharedSiteNav .suite-nav-panel{position:fixed;top:40px;right:6px;grid-template-columns:1fr 1fr;max-height:calc(100dvh - 50px);overflow:auto}}
    `;
    document.head.appendChild(style);
  }

  document.addEventListener('click', event => {
    const more = nav.querySelector('.suite-nav-more');
    if (more && more.open && !more.contains(event.target)) more.open = false;
  });
})();
