(function initTimingRegime(global) {
  'use strict';

  const phases = [
    ['復', 1, '一陽初生'],
    ['臨', 2, '陽氣漸長'],
    ['泰', 3, '陰陽交泰'],
    ['大壯', 4, '陽勢擴張'],
    ['夬', 5, '陽盛待變'],
    ['乾', 6, '純陽極盛'],
    ['姤', 5, '一陰初生'],
    ['遯', 4, '陽退陰進'],
    ['否', 3, '陰陽不交'],
    ['觀', 2, '陰勢漸長'],
    ['剝', 1, '陽氣將盡'],
    ['坤', 0, '純陰極盛'],
  ].map((row, phase) => Object.freeze({
    phase,
    name: row[0],
    yang: row[1],
    note: row[2],
  }));

  function guaForTermIndex(index) {
    const normalized = ((Number(index) || 0) + 1) % 24;
    return phases[Math.floor(normalized / 2)];
  }

  function annotateTerms(terms) {
    return Object.values(terms || {})
      .filter(term => term && term.date)
      .sort((a, b) => String(a.date).localeCompare(String(b.date)))
      .map((term, index) => ({ ...term, gua: guaForTermIndex(index) }));
  }

  global.HKTimingRegime = Object.freeze({
    phases: Object.freeze(phases),
    guaForTermIndex,
    annotateTerms,
  });
}(window));
