/* v3.0 P7 — Models data layer. NO mock data: the design reference's
   _synthReport / MOCK_MODELS / MOCK_IMPORT_PREVIEW are deliberately NOT
   ported (mock-strip discipline, plan §4). Everything here is helpers over
   the REAL backend surfaces:

     GET  /api/models/overview                     G-M3 feed (models+latest run+spark)
     GET  /api/models/{id}                          model detail (decoded blobs)
     GET  /api/models/{id}/runs                     imported-run list (summary only)
     GET  /api/models/{id}/runs/{run}/report        G-M1 verbatim capture + equity + trades
     GET  /api/models/{id}/usage                    G-M6 reverse attribution
     POST /api/models · PUT/DELETE /api/models/{id} CRUD (JSON)
     POST /models/{id}/backtest-upload?format=json[&dry_run=1]
     POST /api/models/import[?dry_run=1]            G-M5 create+import / form preview

   The verbatim capture ("workbook.v1") is rendered by LABEL-LOOKUP AT RENDER
   TIME (plan §2 G-M2): sheet → sections → tables, derived here, formatted in
   pages-models-report.jsx. Cell encoding (see core/backtest_adapters/
   workbook_capture.py): bare scalars, {"t":"n","v":…,"f":fmt} styled numbers
   (v may be "nan"/"inf"/"-inf" strings), {"t":"dt","v":iso} datetimes,
   {"t":"str","v":…} exotics. */

/* ── fetch plumbing (the _ptJson error-tagging contract: err.status /
      err.corrupt feed qeFootState) ─────────────────────────────────────── */
const _mdlSend = async (url, method, body) => {
  let r;
  try {
    r = await fetch(url, {
      method,
      headers: body != null ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: body != null ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    const err = new Error(url + ' unreachable'); err.status = 0; throw err;
  }
  let data = null;
  try { data = await r.json(); }
  catch (e) {
    const err = new Error(url + ' corrupt response'); err.corrupt = true; throw err;
  }
  if (!r.ok || (data && data.error)) {
    const err = new Error((data && data.error) || (url + ' ' + r.status));
    err.status = r.status; throw err;
  }
  return data;
};

const _mdlUpload = async (url, formData) => {
  let r;
  try { r = await fetch(url, { method: 'POST', body: formData, headers: { Accept: 'application/json' } }); }
  catch (e) { const err = new Error(url + ' unreachable'); err.status = 0; throw err; }
  let data = null;
  try { data = await r.json(); }
  catch (e) { const err = new Error(url + ' corrupt response'); err.corrupt = true; throw err; }
  if (!r.ok || (data && data.error)) {
    const err = new Error((data && data.error) || (url + ' ' + r.status));
    err.status = r.status; throw err;
  }
  return data;
};

/* ── formatting atoms ────────────────────────────────────────────────────── */
const _mdlMoney = (v, dp = 2) => (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
const _mdlPl = (v) => (v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)');
const _mdlDate = (iso) => (iso ? String(iso).slice(0, 10) : '—');
const _mdlDt = (iso) => (iso ? String(iso).slice(0, 16).replace('T', ' ') : '—');
const _mdlMs = (ms) => (ms ? new Date(ms).toISOString().slice(0, 16).replace('T', ' ') : '—');

/* model type: stored lowercase (macro|micro|both), displayed capitalized */
const MDL_TYPES = [['macro', 'Macro'], ['micro', 'Micro'], ['both', 'Both']];
const mdlTypeLabel = (t) => (({ macro: 'Macro', micro: 'Micro', both: 'Both' })[t] || t || '—');

/* ── capture-cell utilities ──────────────────────────────────────────────── */
/* Unwrap a captured cell to its raw value. Wrapped non-finite numbers
   ("nan"/"inf"/"-inf") come back as null — nothing renderable. */
const mdlCellVal = (c) => {
  if (c == null) return null;
  if (typeof c !== 'object') return c;
  if (c.t === 'n') return typeof c.v === 'number' ? c.v : null;
  return c.v != null ? c.v : null;
};
/* Numeric view of a cell (wrapped or bare); null when not a number. */
const mdlCellNum = (c) => {
  const v = mdlCellVal(c);
  return typeof v === 'number' ? v : null;
};
/* True when the cell's own number-format string marks it a percent. */
const mdlCellIsPct = (c) => !!(c && typeof c === 'object' && c.t === 'n' && typeof c.f === 'string' && c.f.indexOf('%') >= 0);
const mdlCellIsDt = (c) => !!(c && typeof c === 'object' && c.t === 'dt');
/* Display text for a cell that isn't run through MCNum (dt → "date time"). */
const mdlCellText = (c) => {
  if (mdlCellIsDt(c)) return _mdlDt(c.v);
  const v = mdlCellVal(c);
  return v == null ? '' : String(v);
};

/* ── sheet access ────────────────────────────────────────────────────────── */
const mdlSheet = (report, name) => {
  if (!report || !report.sheets) return null;
  const s = report.sheets.find((x) => x.name === name);
  return s && s.rows && s.rows.length ? s : null;
};

/* Sectionize a captured sheet: MultiCharts separates blocks with blank rows
   and titles them with single-cell rows; a row of ≥2 strings with an empty
   first cell is a column-header row ("All Trades / Long Trades / Short
   Trades"). This renders ANY label/value sheet faithfully — the render-as-is
   fallback that survives label moves (plan §2). */
const mdlSections = (rows) => {
  const secs = [];
  let cur = null;
  const isEmptyRow = (r) => !r || !r.length || r.every((c) => { const v = mdlCellVal(c); return v == null || v === ''; });
  for (const r of rows || []) {
    if (isEmptyRow(r)) { cur = null; continue; }
    const vals = r.map(mdlCellVal);
    const filled = [];
    vals.forEach((v, i) => { if (v != null && v !== '') filled.push(i); });
    if (filled.length === 1 && typeof vals[filled[0]] === 'string' && r.length <= filled[0] + 1) {
      cur = { title: String(vals[filled[0]]), header: null, rows: [] };
      secs.push(cur);
      continue;
    }
    const headerish = (vals[0] == null || vals[0] === '') && filled.length >= 2
      && filled.every((i) => typeof vals[i] === 'string');
    if (headerish) {
      if (!cur) { cur = { title: null, header: null, rows: [] }; secs.push(cur); }
      cur.header = vals.map((v) => (v == null ? '' : String(v)));
      continue;
    }
    if (!cur) { cur = { title: null, header: null, rows: [] }; secs.push(cur); }
    cur.rows.push(r);
  }
  return secs.filter((s) => s.rows.length || s.title);
};

/* Width (max cell count) across a section's data rows. */
const mdlSectionWidth = (sec) => Math.max(1, ...sec.rows.map((r) => r.length));

/* Label → {cells} lookup across a whole sheet (first match wins). */
const mdlFindRow = (rows, label) => {
  for (const r of rows || []) {
    if (r && typeof mdlCellVal(r[0]) === 'string' && String(mdlCellVal(r[0])).trim() === label) return r;
  }
  return null;
};

/* ── label → display-format lookup (design taxonomy + heuristics) ────────── */
const MDL_FMT = {
  'Profit Factor': 'pf', 'Adjusted Profit Factor': 'pf', 'Select Profit Factor': 'pf',
  'Total # of Trades': 'int', 'Max # Contracts Held': 'int',
  'Number Winning Trades': 'int', 'Number Losing Trades': 'int',
  'Number of Outliers': 'int',
  'Max Consec. Winners': 'int', 'Max Consec. Losers': 'int',
  '% Profitable': 'pct', 'Return on Account': 'pct', 'Return on Initial Capital': 'pct',
  'Annual Rate of Return': 'pct', 'Monthly Rate of Return': 'pct',
  'Percent in the Market': 'pct',
  'Return on Max Strategy Drawdown': 'num', 'Monthly Return StdDev': 'num',
  'Sharpe Ratio': 'num', 'Annualized Sharpe Ratio': 'num', 'Sortino Ratio': 'num',
  'Calmar Ratio': 'num', 'Sterling Ratio': 'num', 'RINA Index': 'num',
  'Upside Potential Ratio': 'num', 'Fouse Ratio': 'num',
  'Z-score': 'num', 'Confidence Limit': 'num',
};
const mdlFmtFor = (label, cell) => {
  if (mdlCellIsPct(cell)) return 'pct';
  const l = String(label || '').trim();
  if (MDL_FMT[l]) return MDL_FMT[l];
  if (/\(%\)$/.test(l)) return 'pct';
  if (/^(#|Number|Avg #|Max #)/.test(l) || /# of/.test(l)) return 'int';
  if (/Ratio|Index|Z-score|StdDev|Std\. Deviation|Deviation/i.test(l)) return 'num';
  return 'usd';
};

/* ── List of Trades pairing (client twin of the backend parser, run against
      the verbatim capture so the design's entry/exit-stacked table renders
      from the file's own rows; null → caller falls back to the generic
      sheet render) ──────────────────────────────────────────────────────── */
const mdlPairTrades = (sheet) => {
  if (!sheet) return null;
  const rows = sheet.rows;
  let headIdx = -1, head = null;
  for (let i = 0; i < rows.length; i++) {
    const cells = (rows[i] || []).map((c) => String(mdlCellVal(c) == null ? '' : mdlCellVal(c)).trim());
    if (cells.indexOf('Trade #') >= 0 && cells.indexOf('Type') >= 0) { headIdx = i; head = cells; break; }
  }
  if (headIdx < 0) return null;
  const col = {};
  head.forEach((name, i) => { if (name) col[name] = i; });
  const get = (r, name) => (col[name] != null && col[name] < r.length ? r[col[name]] : null);
  const dtSplit = (c) => {
    if (mdlCellIsDt(c)) { const iso = String(c.v); return [iso.slice(0, 10), iso.slice(11, 19)]; }
    const v = mdlCellVal(c);
    return [v == null ? '' : String(v), ''];
  };
  const trades = [];
  let pending = null;
  for (let i = headIdx + 1; i < rows.length; i++) {
    const r = rows[i] || [];
    const typ = String(mdlCellVal(get(r, 'Type')) || '').trim();
    if (typ.indexOf('Entry') === 0) {
      const [d, t] = dtSplit(get(r, 'Date') != null ? get(r, 'Date') : get(r, 'Time'));
      pending = {
        n: mdlCellNum(get(r, 'Trade #')) || trades.length + 1,
        side: typ.indexOf('Long') >= 0 ? 'L' : 'S',
        entryType: typ, entrySignal: mdlCellText(get(r, 'Signal')),
        entryOrder: mdlCellNum(get(r, 'Order #')),
        entryDate: d, entryTime: t,
        entryPrice: mdlCellNum(get(r, 'Price')),
        contracts: mdlCellNum(get(r, 'Contracts')),
        profit: mdlCellNum(get(r, 'Profit ($)')),
        profitPct: mdlCellNum(get(r, 'Profit (%)')),
        cum: mdlCellNum(get(r, 'Cum. Profit ($)')),
        cumPct: mdlCellNum(get(r, 'Cum. Profit (%)')),
        runup: mdlCellNum(get(r, 'Run-up ($)')),
        runupPct: mdlCellNum(get(r, 'Run-up (%)')),
        dd: mdlCellNum(get(r, 'Drawdown ($)')),
        ddPct: mdlCellNum(get(r, 'Drawdown (%)')),
      };
    } else if (typ.indexOf('Exit') === 0) {
      if (!pending) continue;  // exit with no entry — mirror the parser's skip
      const [d, t] = dtSplit(get(r, 'Date') != null ? get(r, 'Date') : get(r, 'Time'));
      trades.push({
        ...pending,
        exitType: typ, exitSignal: mdlCellText(get(r, 'Signal')),
        exitOrder: mdlCellNum(get(r, 'Order #')),
        exitDate: d, exitTime: t,
        exitPrice: mdlCellNum(get(r, 'Price')),
      });
      pending = null;
    }
  }
  return trades;  // trailing unpaired Entry (open at export) drops, like the parser
};

/* Hour-of-day P/L buckets derived from paired trades (the file's own trade
   list) — feeds the Periodical bar chart honestly even though the
   "Periodical Analysis" sheet layout varies. */
const mdlHourly = (trades) => {
  if (!trades || !trades.length) return [];
  const by = {};
  trades.forEach((t) => {
    if (!t.entryTime) return;
    const h = t.entryTime.slice(0, 2) + ':00';
    (by[h] = by[h] || []).push(t);
  });
  return Object.keys(by).sort().map((h) => {
    const ts = by[h];
    const wins = ts.filter((t) => (t.profit || 0) > 0);
    const net = ts.reduce((a, t) => a + (t.profit || 0), 0);
    return { hour: h, profit: +net.toFixed(2), trades: ts.length, winPct: ts.length ? +(wins.length / ts.length * 100).toFixed(1) : 0 };
  });
};

/* ── derived-summary KPIs (the backend's normalized aggregate) ───────────── */
const mdlRunKpis = (summary) => {
  const s = summary || {};
  return {
    net: s.net_profit != null ? s.net_profit : 0,
    pf: s.profit_factor != null ? Math.abs(s.profit_factor) : 0,
    winPct: +((s.win_rate || 0) * 100).toFixed(1),
    maxDDPct: +((s.max_drawdown_pct || 0) * 100).toFixed(2),
    maxDD: s.max_drawdown != null ? s.max_drawdown : 0,
    sharpe: s.sharpe != null ? s.sharpe : 0,
    nTrades: s.total_trades != null ? s.total_trades : 0,
  };
};

const mdlLatestKpis = (m) => (m && m.latest_run ? mdlRunKpis(m.latest_run.summary) : null);

Object.assign(window, {
  _mdlSend, _mdlUpload, _mdlMoney, _mdlPl, _mdlDate, _mdlDt, _mdlMs,
  MDL_TYPES, mdlTypeLabel,
  mdlCellVal, mdlCellNum, mdlCellIsPct, mdlCellIsDt, mdlCellText,
  mdlSheet, mdlSections, mdlSectionWidth, mdlFindRow, mdlFmtFor,
  mdlPairTrades, mdlHourly, mdlRunKpis, mdlLatestKpis,
});
