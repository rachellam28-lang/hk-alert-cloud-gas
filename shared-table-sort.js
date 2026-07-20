(function () {
  'use strict';

  if (window.__suiteTableSortInstalled) return;
  window.__suiteTableSortInstalled = true;

  function addStyles() {
    if (document.getElementById('suiteTableSortStyles')) return;
    const style = document.createElement('style');
    style.id = 'suiteTableSortStyles';
    style.textContent = `
      th.suite-sortable,th[data-sort]{cursor:pointer;user-select:none;-webkit-tap-highlight-color:transparent;touch-action:manipulation}
      th.suite-sortable:hover,th[data-sort]:hover{color:var(--primary,#0b7475)}
      th.suite-sortable:focus-visible,th[data-sort]:focus-visible{outline:2px solid var(--primary,#0b7475);outline-offset:-2px}
      th.suite-sortable.sort-active,th[data-sort].sort-active{color:var(--primary,#0b7475)}
      .suite-sort-indicator{display:inline-block;min-width:10px;margin-left:4px;font-size:8px;line-height:1;opacity:.8;vertical-align:middle}
    `;
    document.head.appendChild(style);
  }

  function textOf(cell) {
    return String(cell?.dataset.sortValue ?? cell?.dataset.value ?? cell?.innerText ?? '')
      .replace(/\s+/g, ' ').trim();
  }

  function valueOf(cell) {
    const text = textOf(cell);
    if (!text || /^(?:—|--|－|N\/A|NA|未有|未回填|資料不足)$/i.test(text)) return null;

    const iso = text.match(/\b(20\d{2})[-\/.](\d{1,2})[-\/.](\d{1,2})\b/);
    if (iso) {
      const stamp = Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
      return { type: 'number', value: stamp };
    }

    const cleaned = text.replace(/,/g, '').replace(/[＋+]/g, '+').replace(/[−–—]/g, '-');
    const match = cleaned.match(/(?:^|[^\d.])(-?\d+(?:\.\d+)?)/) || cleaned.match(/^(-?\d+(?:\.\d+)?)/);
    if (match) {
      let value = Number(match[1]);
      if (Number.isFinite(value)) {
        const tail = cleaned.slice((match.index || 0) + match[0].length);
        const unitText = `${match[0]}${tail.slice(0, 3)}`;
        if (/萬/.test(unitText)) value *= 1e4;
        else if (/億/.test(unitText)) value *= 1e8;
        else if (/\bK\b/i.test(unitText)) value *= 1e3;
        else if (/\bM\b/i.test(unitText)) value *= 1e6;
        else if (/\bB\b/i.test(unitText)) value *= 1e9;
        return { type: 'number', value };
      }
    }

    return { type: 'text', value: text.toLocaleLowerCase('zh-HK') };
  }

  function compare(a, b, direction) {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    let result;
    if (a.type === 'number' && b.type === 'number') result = a.value - b.value;
    else result = String(a.value).localeCompare(String(b.value), 'zh-HK', { numeric: true, sensitivity: 'base' });
    return direction === 1 ? result : -result;
  }

  function dataRows(tbody, index) {
    return Array.from(tbody.children).filter(row => {
      if (row.tagName !== 'TR' || row.cells.length <= index) return false;
      return !(row.cells.length === 1 && row.cells[0].colSpan > 1);
    });
  }

  function updateRank(table) {
    const first = table.tHead?.rows?.[0]?.cells?.[0];
    if (!first || !/^#|排名$/.test(first.innerText.trim())) return;
    let rank = 1;
    table.querySelectorAll('tbody tr').forEach(row => {
      if (row.cells.length && !(row.cells.length === 1 && row.cells[0].colSpan > 1)) {
        row.cells[0].textContent = rank++;
      }
    });
  }

  function sortTable(table, header) {
    const index = Number(header.dataset.suiteSortIndex);
    if (!Number.isInteger(index)) return;
    const state = table.__suiteSortState || {};
    const sample = Array.from(table.tBodies).flatMap(body => dataRows(body, index))
      .map(row => valueOf(row.cells[index])).find(value => value != null);
    const direction = state.index === index ? -state.direction : (sample?.type === 'text' ? 1 : -1);
    table.__suiteSortState = { index, direction };

    Array.from(table.tBodies).forEach(tbody => {
      const rows = dataRows(tbody, index);
      rows.sort((a, b) => compare(valueOf(a.cells[index]), valueOf(b.cells[index]), direction));
      rows.forEach(row => tbody.appendChild(row));
    });

    table.querySelectorAll('thead th.suite-sortable').forEach(th => {
      const active = th === header;
      th.classList.toggle('sort-active', active);
      th.setAttribute('aria-sort', active ? (direction === 1 ? 'ascending' : 'descending') : 'none');
      const indicator = th.querySelector('.suite-sort-indicator');
      if (indicator) indicator.textContent = active ? (direction === 1 ? '▲' : '▼') : '';
    });
    updateRank(table);
    table.dispatchEvent(new CustomEvent('suite:table-sorted', { detail: { index, direction } }));
  }

  function decorateHeader(table, header) {
    if (header.dataset.noSort === 'true' || header.colSpan > 1) return;
    const label = header.innerText.trim();
    if (!label && !header.dataset.sort) return;
    header.classList.add('suite-sortable');
    header.setAttribute('role', 'button');
    header.setAttribute('tabindex', '0');
    if (!header.hasAttribute('aria-sort')) header.setAttribute('aria-sort', 'none');

    if (header.dataset.sort || header.hasAttribute('onclick') || header.dataset.suiteSortBound === 'true') return;
    header.dataset.suiteSortBound = 'true';
    header.dataset.suiteSortIndex = String(header.cellIndex);
    if (!header.querySelector('.suite-sort-indicator')) {
      const indicator = document.createElement('span');
      indicator.className = 'suite-sort-indicator';
      indicator.setAttribute('aria-hidden', 'true');
      header.appendChild(indicator);
    }
    header.addEventListener('click', () => sortTable(table, header));
    header.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        sortTable(table, header);
      }
    });
  }

  function install(root) {
    const tables = [];
    if (root?.matches?.('table')) tables.push(root);
    root?.querySelectorAll?.('table').forEach(table => tables.push(table));
    tables.forEach(table => table.querySelectorAll('thead th').forEach(header => decorateHeader(table, header)));
  }

  addStyles();
  install(document);
  new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
    if (node.nodeType === 1) install(node);
  }))).observe(document.documentElement, { childList: true, subtree: true });
})();
