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
    ['rights_analysis.html', '\u4e8b\u4ef6'],
    ['watchlist.html', '\u81ea\u9078'],
  ];
  const guide = ['guide.html', '\u8aaa\u660e'];
  const groups = [
    ['\u63c0\u80a1', [
      ['rotation_matrix.html', '\u677f\u584a\u8f2a\u52d5'],
      ['fundflow.html', '\u8cc7\u91d1\u6d41'],
    ]],
    ['\u6642\u5e8f', [
      ['timing_stack.html', '\u6642\u6a5f\u758a\u52a0'],
      ['vqc_analysis.html', '\u6210\u4ea4\u8f49\u52e2\u65e5'],
      ['timing_analysis.html', '\u6642\u9593\u7a97\u53e3'],
      ['jieqi_analysis.html', '\u7bc0\u6c23\u7a97\u53e3'],
      ['distribution_day.html', '\u5206\u4f48\u65e5'],
    ]],
    ['\u8a18\u9304', [
      ['docs/ccass-warroom.html', 'CCASS \u6230\u60c5\u5ba4'],
      ['history.html', '\u8a0a\u865f\u6b77\u53f2'],
    ]],
  ];

  const path = location.pathname.toLowerCase().replace(/\/+$/, '');
  const darkTools = ['/kbar_matrix', '/kbar_matrix.html', '/docs/ccass-warroom', '/docs/ccass-warroom.html'];
  const useUnifiedLightTheme = !darkTools.some(item => path.endsWith(item));
  document.documentElement.classList.toggle('suite-light', useUnifiedLightTheme);
  const active = href => {
    const rel = href.toLowerCase().replace(/^\.\//, '');
    const cleanRel = rel.endsWith('.html') ? rel.slice(0, -5) : rel;
    return path.endsWith('/' + rel)
      || path.endsWith('/' + cleanRel)
      || (rel === 'index.html' && (path.endsWith('/') || !path));
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
    </details>
    <div class="suite-nav-guide">${link(guide)}</div>`;

  if (!document.getElementById('sharedNavStyles')) {
    const style = document.createElement('style');
    style.id = 'sharedNavStyles';
    style.textContent = `
      #sharedSiteNav{position:sticky;top:0;z-index:80;display:flex;align-items:center;gap:6px;padding:6px 10px;background:#11191d;border-bottom:1px solid #2b393e;font:600 12px/1.2 system-ui,sans-serif;overflow:visible}
      #sharedSiteNav .suite-nav-primary{display:flex;align-items:center;gap:3px;min-width:0;overflow-x:auto;scrollbar-width:none}
      #sharedSiteNav .suite-nav-primary::-webkit-scrollbar{display:none}
      #sharedSiteNav a,#sharedSiteNav summary{display:inline-flex;align-items:center;min-height:30px;padding:6px 9px;border-radius:5px;color:#b4c0c4;text-decoration:none;white-space:nowrap;cursor:pointer;transition:background .18s,color .18s,transform .1s}
      #sharedSiteNav a:hover,#sharedSiteNav summary:hover{background:#1d2a2f;color:#fff}
      #sharedSiteNav a:active,#sharedSiteNav summary:active{transform:translateY(1px)}
      #sharedSiteNav a:focus-visible,#sharedSiteNav summary:focus-visible{outline:2px solid #63c7ca;outline-offset:2px}
      #sharedSiteNav a.active,#sharedSiteNav summary.active{background:#153d3d;color:#83ddd5}
      #sharedSiteNav .suite-nav-more{position:relative;margin-left:auto;flex:0 0 auto}
      #sharedSiteNav .suite-nav-guide{flex:0 0 auto}
      #sharedSiteNav summary{list-style:none}
      #sharedSiteNav summary::-webkit-details-marker{display:none}
      #sharedSiteNav summary::after{content:'\\25be';margin-left:6px;font-size:9px}
      #sharedSiteNav .suite-nav-panel{position:absolute;right:0;top:36px;width:min(620px,calc(100vw - 16px));display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:10px;background:#11191d;border:1px solid #35454b;border-radius:7px;box-shadow:0 16px 40px rgba(10,18,20,.28)}
      #sharedSiteNav .suite-nav-group{display:grid;align-content:start;gap:2px}
      #sharedSiteNav .suite-nav-group strong{padding:4px 9px;color:#7f90a7;font-size:10px}
      body{font-variant-numeric:tabular-nums}
      html.suite-light{
        color-scheme:light;
        --bg:#edf1f2!important;--surface:#fff!important;--surface-2:#f5f7f7!important;
        --surface-soft:#f5f7f7!important;--panel:#fff!important;--panel2:#f5f7f7!important;
        --text:#172126!important;--txt:#172126!important;--text-soft:#3f4d53!important;
        --soft:#3f4d53!important;--muted:#68777d!important;--dim:#68777d!important;
        --mute:#68777d!important;--mute-2:#8b989d!important;--line:#d5dddf!important;
        --line-soft:#e7ecec!important;--primary:#0b7475!important;--primary-soft:#e1f1ef!important;
        --primary-border:#9ccfca!important;--up:#157a4b!important;--up-soft:#e2f2e9!important;
        --up-border:#9dd3b5!important;--down:#b43a42!important;--down-soft:#f7e6e7!important;
        --down-border:#e5a7ab!important;--amber:#986308!important;--amber-soft:#fff1d8!important;
        --amber-border:#e3c27c!important;--violet:#6c5f91!important;--violet-soft:#eeeaf5!important;
        --violet-border:#c7bedc!important;--info:#286f91!important;--info-soft:#e5f0f5!important;
        --teal:#0b7475!important;--green:#157a4b!important;--red:#b43a42!important;
        --blue:#286f91!important;--gold:#986308!important;--yellow:#986308!important;
        --accent:#0b7475!important;--accent2:#286f91!important;--pos:#157a4b!important;
        --neg:#b43a42!important;--positive:#157a4b!important;--negative:#b43a42!important;
        --shadow:0 1px 2px rgba(31,48,52,.06)!important
      }
      html.suite-light body{background:#edf1f2!important;color:#172126!important}
      html.suite-light .hero,html.suite-light .card,html.suite-light .panel,html.suite-light .mini,
      html.suite-light .detail,html.suite-light .event-card,html.suite-light .action-btn,
      html.suite-light .control,html.suite-light .pager button,html.suite-light .inspector-empty,
      html.suite-light .market-cell,html.suite-light .day-section,html.suite-light .summary-item{
        background:#fff!important;color:#172126!important;border-color:#d5dddf!important;box-shadow:none!important
      }
      html.suite-light .topbar,html.suite-light .nav,html.suite-light .day-header,
      html.suite-light th,html.suite-light thead th,html.suite-light .drawer-head{
        background:#f5f7f7!important;color:#68777d!important;border-color:#d5dddf!important
      }
      html.suite-light td,html.suite-light .lane,html.suite-light .detail-section,
      html.suite-light .market-tape,html.suite-light .context-band,html.suite-light .table-wrap,
      html.suite-light .rotation-row,html.suite-light .timeline-row{
        border-color:#d5dddf!important
      }
      html.suite-light tbody tr:hover,html.suite-light tbody tr.selected,
      html.suite-light .action-btn:hover,html.suite-light .card-head:hover{
        background:#f3f8f7!important;color:#172126!important
      }
      html.suite-light .action-btn.active,html.suite-light .tab.active,
      html.suite-light .setup-btn.active{background:#e4f2f1!important;color:#075f66!important;border-color:#70aaa9!important}
      html.suite-light input,html.suite-light select,html.suite-light button{
        background:#fff!important;color:#172126!important;border-color:#cbd5d6!important
      }
      html.suite-light .search-box input,html.suite-light .search-row input,html.suite-light .tab,
      html.suite-light .btn,html.suite-light .fbtn{
        background:#fff!important;color:#3f4d53!important;border-color:#d5dddf!important
      }
      html.suite-light .btn.active,html.suite-light .btn.blue,html.suite-light .btn.teal{
        background:#e4f2f1!important;color:#075f66!important;border-color:#70aaa9!important
      }
      html.suite-light .btn.gold{background:#fff4d6!important;color:#8a6100!important;border-color:#dfbd57!important}
      html.suite-light .btn.red{background:#fde9eb!important;color:#a52b34!important;border-color:#df949a!important}
      html.suite-light .subtitle,html.suite-light .hero-meta,html.suite-light .section-note,
      html.suite-light .lead,html.suite-light .stamp,html.suite-light .quiet,
      html.suite-light .thesis,html.suite-light .footer,html.suite-light .foot{
        color:#68777d!important
      }
      html.suite-light .log-track{background:#e3e9ee!important;border-color:#cbd5dd!important}
      html.suite-light .trade-buy,html.suite-light .supply-stock,html.suite-light .issuer-low,
      html.suite-light .issuer-react-up,html.suite-light .year-open-up{background:#e5f5ea!important;color:#19733c!important}
      html.suite-light .trade-wait,html.suite-light .supply-watch{background:#fff4d6!important;color:#8a6100!important}
      html.suite-light .trade-avoid,html.suite-light .supply-cash,html.suite-light .issuer-high,
      html.suite-light .issuer-react-down,html.suite-light .year-open-down{background:#fde9eb!important;color:#a52b34!important}
      html.suite-light .issuer-neutral,html.suite-light .issuer-react-neutral,
      html.suite-light .supply-ended,html.suite-light .year-open-missing{background:#f1f4f6!important;color:#697887!important}
      html.suite-light .sc-desk{background:#fff!important;color:#172126!important;border-color:#d5dddf!important;box-shadow:none!important}
      html.suite-light .sc-desk-head,html.suite-light .sc-desk-tools{background:#fff!important;border-color:#d5dddf!important}
      html.suite-light .sc-desk-title strong,html.suite-light .sc-pick-code{color:#172126!important}
      html.suite-light .sc-desk-title span,html.suite-light .sc-desk-truth,
      html.suite-light .sc-pulse-label,html.suite-light .sc-pulse-note,
      html.suite-light .sc-pick-rank,html.suite-light .sc-pick-name,
      html.suite-light .sc-pick .sc-metric-label{color:#68777d!important}
      html.suite-light .sc-desk-pulse,html.suite-light .sc-desk-list{background:#d5dddf!important;border-color:#d5dddf!important}
      html.suite-light .sc-pulse,html.suite-light .sc-pick,html.suite-light .sc-desk-empty{background:#fff!important;color:#172126!important;border-color:#d5dddf!important}
      html.suite-light .sc-pulse-value,html.suite-light .sc-pick .sc-metric-value{color:#3f4d53!important}
      html.suite-light .sc-pick:hover{background:#f3f8f7!important}
      html.suite-light .sc-desk-tab{background:transparent!important;color:#68777d!important}
      html.suite-light .sc-desk-tab:hover{background:#f5f7f7!important;color:#172126!important}
      html.suite-light .sc-desk-tab.active{background:#e1f1ef!important;color:#075f60!important;border-color:#78b9b4!important}
      html.suite-light .sc-reason{background:#f5f7f7!important;color:#59686e!important;border-color:#d5dddf!important}
      html.suite-light .sc-reason.good,html.suite-light .sc-score{background:#e2f2e9!important;color:#157a4b!important;border-color:#9dd3b5!important}
      html.suite-light .sc-reason.warn,html.suite-light .sc-score.wait{background:#fff1d8!important;color:#986308!important;border-color:#e3c27c!important}
      html.suite-light .sc-reason.bad,html.suite-light .sc-score.risk{background:#f7e6e7!important;color:#b43a42!important;border-color:#e5a7ab!important}
      html.suite-light .tag-up,html.suite-light .pill.yes,html.suite-light .evidence-chip.yes{
        background:var(--up-soft)!important;color:var(--up)!important;border-color:var(--up-border)!important
      }
      html.suite-light .tag-dn,html.suite-light .pill.risk,html.suite-light .evidence-chip.risk,
      html.suite-light .state.risk{
        background:var(--down-soft)!important;color:var(--down)!important;border-color:var(--down-border)!important
      }
      html.suite-light .tag-warn,html.suite-light .pill.wait,html.suite-light .card.wait{
        background:var(--amber-soft)!important;color:var(--amber)!important;border-color:var(--amber-border)!important
      }
      html.suite-light .pill.info{background:var(--info-soft)!important;color:var(--info)!important;border-color:#a9cad9!important}
      html.suite-light .pill.off{
        color:var(--muted)!important;border-color:var(--line)!important
      }
      .status-loading,.status-error,.status-empty{padding:18px;text-align:center;border:1px solid #d8dee8;border-radius:6px;background:#f6f8fb;color:#64748b}
      .status-error{border-color:#efb5b9;background:#fff1f2;color:#a52b34}
      button,a,input,select,summary{transition:border-color .18s,background-color .18s,color .18s,transform .1s}
      button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid #0f7f87;outline-offset:2px}
      @media(max-width:640px){#sharedSiteNav{padding:5px 6px;gap:2px}#sharedSiteNav a,#sharedSiteNav summary{min-height:28px;padding:5px 7px;font-size:11px}#sharedSiteNav .nav-desktop{display:none}#sharedSiteNav .suite-nav-primary{flex:1 1 auto;overflow-x:auto}#sharedSiteNav .suite-nav-panel{position:fixed;top:40px;right:6px;grid-template-columns:1fr 1fr;max-height:calc(100dvh - 50px);overflow:auto}}
    `;
    document.head.appendChild(style);
  }

  document.addEventListener('click', event => {
    const more = nav.querySelector('.suite-nav-more');
    if (more && more.open && !more.contains(event.target)) more.open = false;
  });
})();
