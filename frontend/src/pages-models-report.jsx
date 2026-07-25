/* v3.0 P7 — imported-run report tabs, rendered from the VERBATIM workbook
   capture (render-as-is, plan §2 G-M2): sheet → sections → tables via the
   generic sectionizer in pages-models-data.jsx, with label-lookup formatting.
   Bespoke panes exist only where they add real value (Key-Metrics KPIs,
   entry/exit-paired trade list, redrawn equity/drawdown, hourly P/L) and every
   one degrades to the generic sheet render / the normalized DB rows when the
   capture lacks its shape. `rep` = /api/models/{id}/runs/{run}/report payload
   ({run, report, equity, trades}); `foot` = the fetch's qeFootState line.

   Named deviation from the design reference: Strategy Analysis renders the
   sheet's OWN sections in one pane (+ the KPI row) instead of the reference's
   fixed Performance/Ratios/Time 3-pane split — section titles come from the
   file, so a hardcoded split would break on the first label move. */

/* ── MultiCharts-style number cell ────────────────────────────────────────
   Negatives render in (parens) and red; positives green; counts/ratios
   neutral. PF: magnitude, (parens)+red below 1 (MC exports it signed). */
const MCNum = ({ v, fmt = 'usd', bold }) => {
  if (v == null || v === '') return <span style={{ color: 'var(--qe-muted)' }}>n/a</span>;
  if (fmt === 'str') return <span className="qe-mono" style={{ color: 'var(--qe-text)' }}>{v}</span>;
  const num = typeof v === 'number' ? v : parseFloat(v);
  if (isNaN(num)) return <span className="qe-mono" style={{ color: 'var(--qe-text)' }}>{v}</span>;
  if (fmt === 'pf') {
    const a = Math.abs(num), lt1 = a < 1;
    return <span className="qe-mono" style={{ color: lt1 ? 'var(--qe-red)' : 'var(--qe-green)', fontWeight: bold ? 700 : 500, fontVariantNumeric: 'tabular-nums' }}>{lt1 ? '(' + a.toFixed(2) + ')' : a.toFixed(2)}</span>;
  }
  const neg = num < 0, zero = num === 0;
  let body;
  if (fmt === 'pct') body = (Math.abs(num) * 100).toFixed(2) + '%';
  else if (fmt === 'int') body = Math.round(Math.abs(num)).toLocaleString();
  else if (fmt === 'num') body = Math.abs(num).toFixed(2);
  else body = '$' + Math.abs(num).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const text = neg ? '(' + body + ')' : body;
  const color = (fmt === 'int' || zero) ? 'var(--qe-text)' : neg ? 'var(--qe-red)' : 'var(--qe-green)';
  return <span className="qe-mono" style={{ color, fontWeight: bold ? 700 : 500, fontVariantNumeric: 'tabular-nums' }}>{text}</span>;
};

/* Render one captured cell inside a section table. */
const MdlCellR = ({ cell, label, bold }) => {
  if (cell == null) return null;
  const n = mdlCellNum(cell);
  if (n == null) {
    const t = mdlCellText(cell);
    if (!t && typeof cell === 'object') return <span style={{ color: 'var(--qe-muted)' }}>n/a</span>;
    return <span className="qe-mono" style={{ color: 'var(--qe-text)' }}>{t}</span>;
  }
  return <MCNum v={n} fmt={mdlFmtFor(label, cell)} bold={bold} />;
};

/* ── generic sectioned sheet render (the render-as-is workhorse) ────────── */
const MdlSheetSections = ({ sheet, emptyMsg = 'sheet empty in this export' }) => {
  if (!sheet) {
    return <div style={{ padding: 8, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <EmptyState tone="neutral" glyph="◇" msg={emptyMsg} />
    </div>;
  }
  const secs = mdlSections(sheet.rows);
  if (!secs.length) {
    return <div style={{ padding: 8, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <EmptyState tone="neutral" glyph="◇" msg={emptyMsg} />
    </div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {secs.map((sec, si) => {
        const width = mdlSectionWidth(sec);
        const cols = [{
          key: 'label', label: (sec.header && sec.header[0]) || 'Metric', width: '40%',
          render: (r) => <span style={{ color: 'var(--qe-sub)', whiteSpace: 'normal' }}>{r.label}</span>,
        }];
        for (let i = 1; i < width; i++) {
          cols.push({
            key: 'c' + i,
            label: (sec.header && sec.header[i]) || '·',
            align: i === width - 1 ? 'right' : 'center',
            render: (r) => <MdlCellR cell={r.cells[i]} label={r.label} bold={i === 1} />,
          });
        }
        const rows = sec.rows.map((r, ri) => ({
          id: si + ':' + ri,
          label: mdlCellText(r[0]),
          cells: r,
        }));
        return (
          <div key={si}>
            {sec.title && <SecLbl rule style={{ margin: '8px 7px 2px' }}>{sec.title}</SecLbl>}
            {/* a title-only section (MC's "Title / blank / data" layout)
                renders its header alone — no false "no rows" band (LOW-1) */}
            {/* operator-bug #2: tools stay OFF here by design — this is the
                render-as-is backtest report (P7). Each section reproduces a
                MultiCharts workbook VERBATIM.
                tools were OFF here on the grounds that re-sorting a faithful
                capture breaks the reproduction. Lifted 2026-07-25 (operator
                directive: every DataList carries search + sort + filter): the
                capture still RENDERS in workbook order by default — sort is
                user-initiated and non-destructive, and search is the only
                practical way to find one metric in a long stat block. Facets
                simply do not derive on label/value sections, which is correct. */}
            {rows.length > 0 && <DataList columns={cols} rows={rows} dense={false} selKey="id" />}
          </div>
        );
      })}
    </div>
  );
};

/* ── Strategy Analysis ────────────────────────────────────────────────────── */
const StrategyAnalysisTab = ({ rep, foot }) => {
  const k = mdlRunKpis(rep.run && rep.run.summary);
  const sheet = mdlSheet(rep.report, 'Strategy Analysis');
  const acct = sheet ? mdlCellNum((mdlFindRow(sheet.rows, 'Account Size Required') || [])[1]) : null;
  return (
    <GridWorkspace key="sa">
      <GridItem x={0} y={0} w={24} h={6} minW={12} minH={5}>
        <Pane title="Key Metrics" style={{ height: '100%' }} foot={foot}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 7 }}>
            <KpiTile label="Net Profit" value={_mdlMoney(k.net, 0)} color={_mdlPl(k.net)} />
            <KpiTile label="Profit Factor" value={k.pf.toFixed(2)} color={k.pf >= 1 ? 'var(--qe-green)' : 'var(--qe-red)'} />
            <KpiTile label="% Profitable" value={k.winPct + '%'} />
            <KpiTile label="Max Drawdown" value={k.maxDDPct + '%'} color="var(--qe-red)" />
            <KpiTile label="Total Trades" value={k.nTrades} />
            <KpiTile label="Account Size" value={acct != null ? _mdlMoney(acct, 0) : '—'} />
          </div>
        </Pane>
      </GridItem>
      <GridItem x={0} y={6} w={24} h={18} minW={10} minH={10}>
        <Pane title="Strategy Performance" tag="AS IN FILE" style={{ height: '100%' }} bodyStyle={{ padding: 0 }} foot={foot}>
          <MdlSheetSections sheet={sheet} emptyMsg="no verbatim capture for this run — re-import to populate" />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Graphs (redrawn from the stored equity curve, not the source PNGs) ──── */
const GraphsTab = ({ rep, foot }) => {
  const eqRows = rep.equity || [];
  const k = mdlRunKpis(rep.run && rep.run.summary);
  const settings = ((rep.run || {}).summary || {}).settings || {};
  // tolerate "$"/comma-styled Settings strings (mirrors the backend's
  // _to_float — LOW-3: bare parseFloat turned "100,000" into 100)
  const initial = parseFloat(String(settings['Initial Capital'] != null ? settings['Initial Capital'] : '').replace(/[$,\s]/g, '')) || (eqRows.length ? eqRows[0].equity : 0);
  const eq = eqRows.length ? [initial, ...eqRows.map((r) => r.equity)] : [];
  const dd = eqRows.length ? [0, ...eqRows.map((r) => -Math.abs(r.drawdown))] : [];
  const empty = (msg) => (
    <div style={{ padding: 8, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <EmptyState tone="neutral" glyph="◇" msg={msg} />
    </div>
  );
  return (
    <GridWorkspace key="gr">
      <GridItem x={0} y={0} w={24} h={14} minW={10} minH={7}>
        <Pane title="Equity Curve" tag="CLOSED TRADES" style={{ height: '100%' }}
          right={<span className="qe-mono" style={{ fontSize: '0.54rem', color: 'var(--qe-muted)' }}>net {_mdlMoney(k.net, 0)}</span>}
          foot={foot} bodyStyle={{ padding: '4px 6px', display: 'flex', flexDirection: 'column' }}>
          {eq.length > 1
            ? <div style={{ flex: 1, minHeight: 0 }}><EquityChart data={eq} baseline={initial} color={k.net >= 0 ? 'var(--qe-green)' : 'var(--qe-red)'} /></div>
            : empty('no equity points on this run')}
        </Pane>
      </GridItem>
      <GridItem x={0} y={14} w={24} h={10} minW={10} minH={6}>
        <Pane title="Drawdown" tag="$ FROM PEAK" style={{ height: '100%' }} bodyStyle={{ padding: '4px 6px', display: 'flex', flexDirection: 'column' }}
          foot={foot}>
          {dd.length > 1
            ? <div style={{ flex: 1, minHeight: 0 }}><EquityChart data={dd} baseline={0} color="var(--qe-red)" /></div>
            : empty('no equity points on this run')}
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── List of Trades — entry/exit pair per DataList row, from the capture;
      falls back to the normalized DB trades, then to the generic sheet. ── */
const TradesTab = ({ rep, foot }) => {
  const [side, setSide] = React.useState('all');
  const sheet = mdlSheet(rep.report, 'List of Trades');
  const paired = React.useMemo(() => mdlPairTrades(sheet), [sheet]);

  if (!paired || !paired.length) {
    // Normalized fallback (legacy runs / unrecognized header).
    const rows = (rep.trades || []).map((t, i) => ({ ...t, _i: i + 1 }));
    return (
      <GridWorkspace key="tr-fb">
        <GridItem x={0} y={0} w={24} h={24} minW={12} minH={12}>
          <Pane title="List of Trades" count={rows.length} tag="NORMALIZED" style={{ height: '100%' }} bodyStyle={{ padding: 0 }} foot={foot}>
            {rows.length ? (
              <DataList selKey="_i" rows={rows} columns={[
                { key: '_i', label: '#', filter: false, render: (t) => <span className="qe-mono" style={{ color: 'var(--qe-muted)' }}>{t._i}</span> },
                { key: 'side', label: 'Side', filter: { label: 'SIDE' },
                  filterVal: (t) => (t.side || '—').toUpperCase(),
                  render: (t) => <Badge tone={t.side === 'long' ? 'ok' : 'err'}>{(t.side || '').toUpperCase()}</Badge> },
                { key: 'entry_dt', label: 'Entry', render: (t) => <span className="qe-mono" style={{ fontSize: '0.56rem' }}>{_mdlDt(t.entry_dt)}</span> },
                { key: 'exit_dt', label: 'Exit', render: (t) => <span className="qe-mono" style={{ fontSize: '0.56rem' }}>{_mdlDt(t.exit_dt)}</span> },
                { key: 'entry_price', label: 'Entry Px', align: 'right', render: (t) => <span className="qe-mono">{t.entry_price}</span> },
                { key: 'exit_price', label: 'Exit Px', align: 'right', render: (t) => <span className="qe-mono">{t.exit_price}</span> },
                { key: 'contracts', label: 'Cts', align: 'right', render: (t) => <span className="qe-mono">{t.contracts || '—'}</span> },
                { key: 'pnl_usdt', label: 'P/L $', align: 'right',
                  filter: { label: 'RESULT' },
                  filterVal: (t) => ((t.pnl_usdt || 0) > 0 ? 'WIN' : (t.pnl_usdt || 0) < 0 ? 'LOSS' : 'FLAT'),
                  render: (t) => <MCNum v={t.pnl_usdt} fmt="usd" bold /> },
                { key: 'exit_reason', label: 'Exit Reason', filter: true,
                  filterVal: (t) => String(t.exit_reason || '—') },
              ]} emptyMsg="no trades on this run" />
            ) : <MdlSheetSections sheet={sheet} emptyMsg="no trades on this run" />}
          </Pane>
        </GridItem>
      </GridWorkspace>
    );
  }

  const trades = paired.filter((t) => side === 'all' || t.side === side);
  const cols = [
    { key: 'n', label: '#', sortVal: (t) => t.n, render: (t) => <span className="qe-mono" style={{ color: 'var(--qe-muted)' }}>{t.n}</span> },
    { key: 'order', label: 'Order', sort: false, search: false,
      render: (t) => (<div className="qe-mc-stack">
        <span className="qe-mono" style={{ color: 'var(--qe-muted)' }}>{t.entryOrder != null ? t.entryOrder : '—'}</span>
        <span className="qe-mono" style={{ color: 'var(--qe-muted)', opacity: 0.6 }}>{t.exitOrder != null ? t.exitOrder : '—'}</span>
      </div>) },
    { key: 'side', label: 'Type', filter: false, sortVal: (t) => t.side, searchVal: (t) => `${t.entryType} ${t.exitType}`,
      render: (t) => (<div className="qe-mc-stack">
        <Badge tone={t.side === 'L' ? 'ok' : 'err'}>{(t.entryType || '').replace('Entry', '')}</Badge>
        <span style={{ fontSize: '0.5rem', color: 'var(--qe-muted)' }}>{(t.exitType || '').replace('Exit', 'Exit ')}</span>
      </div>) },
    { key: 'entrySignal', label: 'Signal', searchVal: (t) => `${t.entrySignal} ${t.exitSignal}`,
      render: (t) => (<div className="qe-mc-stack">
        <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontSize: '0.56rem' }}>{t.entrySignal}</span>
        <span className="qe-mono" style={{ color: 'var(--qe-sub)', fontSize: '0.56rem' }}>{t.exitSignal}</span>
      </div>) },
    { key: 'entryDate', label: 'Date', sortVal: (t) => t.entryDate, searchVal: (t) => `${t.entryDate} ${t.exitDate}`,
      render: (t) => (<div className="qe-mc-stack">
        <span className="qe-mono" style={{ color: 'var(--qe-muted)', fontSize: '0.54rem' }}>{t.entryDate}</span>
        <span className="qe-mono" style={{ color: 'var(--qe-muted)', fontSize: '0.54rem', opacity: 0.8 }}>{t.exitDate}</span>
      </div>) },
    { key: 'entryTime', label: 'Time', sortVal: (t) => t.entryTime, searchVal: (t) => `${t.entryTime} ${t.exitTime}`,
      render: (t) => (<div className="qe-mc-stack">
        <span className="qe-mono" style={{ color: 'var(--qe-muted)', fontSize: '0.54rem' }}>{t.entryTime}</span>
        <span className="qe-mono" style={{ color: 'var(--qe-muted)', fontSize: '0.54rem', opacity: 0.8 }}>{t.exitTime}</span>
      </div>) },
    { key: 'entryPrice', label: 'Price', align: 'right', sortVal: (t) => t.entryPrice,
      render: (t) => (<div className="qe-mc-stack">
        <span className="qe-mono">{t.entryPrice != null ? t.entryPrice : '—'}</span>
        <span className="qe-mono" style={{ color: 'var(--qe-muted)' }}>{t.exitPrice != null ? t.exitPrice : '—'}</span>
      </div>) },
    { key: 'contracts', label: 'Cts', align: 'right', render: (t) => <span className="qe-mono">{t.contracts != null ? t.contracts : '—'}</span> },
    { key: 'profit', label: 'Profit $', align: 'right', sortVal: (t) => t.profit,
      filter: { label: 'RESULT' },
      filterVal: (t) => ((t.profit || 0) > 0 ? 'WIN' : (t.profit || 0) < 0 ? 'LOSS' : 'FLAT'),
      render: (t) => <MCNum v={t.profit} fmt="usd" bold /> },
    { key: 'profitPct', label: 'Profit %', align: 'right', sortVal: (t) => t.profitPct, render: (t) => <MCNum v={t.profitPct} fmt="pct" /> },
    { key: 'cum', label: 'Cum $', align: 'right', sortVal: (t) => t.cum, render: (t) => <MCNum v={t.cum} fmt="usd" /> },
    { key: 'runup', label: 'Run-up $', align: 'right', sortVal: (t) => t.runup, render: (t) => <MCNum v={t.runup} fmt="usd" /> },
    { key: 'dd', label: 'Drawdn $', align: 'right', sortVal: (t) => t.dd, render: (t) => <MCNum v={t.dd} fmt="usd" /> },
  ];
  return (
    <GridWorkspace key="tr">
      <GridItem x={0} y={0} w={24} h={24} minW={12} minH={12}>
        <Pane title="List of Trades" count={trades.length} style={{ height: '100%' }} bodyStyle={{ padding: 0 }}
          foot={foot}
          right={<span style={{ display: 'flex', gap: 4 }}>{[['all', 'ALL'], ['L', 'LONG'], ['S', 'SHORT']].map(([v, l]) => (
            <button key={v} className={`qe-btn qe-btn-sm ${side === v ? 'qe-btn-on' : ''}`} onClick={() => setSide(v)}>{l}</button>))}</span>}>
          <div className="qe-mc-trades">
            <DataList selKey="n" columns={cols} rows={trades}
              emptyMsg={`no ${side === 'L' ? 'long ' : side === 'S' ? 'short ' : ''}trades in run`} />
          </div>
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Trade Analysis — the sheet as-is ────────────────────────────────────── */
const AnalysisTab = ({ rep, foot }) => (
  <GridWorkspace key="an">
    <GridItem x={0} y={0} w={24} h={24} minW={12} minH={10}>
      <Pane title="Trade Analysis" tag="AS IN FILE" style={{ height: '100%' }} bodyStyle={{ padding: 0 }} foot={foot}>
        <MdlSheetSections sheet={mdlSheet(rep.report, 'Trade Analysis')}
          emptyMsg="'Trade Analysis' sheet empty in this export" />
      </Pane>
    </GridItem>
  </GridWorkspace>
);

/* ── Periodical — hourly P/L derived from the trade list + the sheet ─────── */
const PeriodicalTab = ({ rep, foot }) => {
  const paired = React.useMemo(() => mdlPairTrades(mdlSheet(rep.report, 'List of Trades')), [rep.report]);
  const hourly = mdlHourly(paired);
  return (
    <GridWorkspace key="pe">
      <GridItem x={0} y={0} w={24} h={8} minW={10} minH={6}>
        <Pane title="Profit by Hour" tag="FROM TRADE LIST" style={{ height: '100%' }} bodyStyle={{ padding: '4px 6px', display: 'flex', flexDirection: 'column' }}
          foot={foot}>
          {hourly.length ? (
            <div style={{ flex: 1, minHeight: 0 }}><BarChart data={hourly.map((x) => x.profit)} categories={hourly.map((x) => x.hour)} color="var(--qe-cyan)" /></div>
          ) : (
            <div style={{ padding: 8, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <EmptyState tone="neutral" glyph="◇" msg="no timed trades to bucket" />
            </div>
          )}
        </Pane>
      </GridItem>
      <GridItem x={0} y={8} w={24} h={16} minW={10} minH={8}>
        <Pane title="Periodical Analysis" tag="AS IN FILE" style={{ height: '100%' }} bodyStyle={{ padding: 0 }} foot={foot}>
          <MdlSheetSections sheet={mdlSheet(rep.report, 'Periodical Analysis')}
            emptyMsg="'Periodical Analysis' sheet empty in this export" />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Settings — the sheet as-is (+ import provenance from the run row) ───── */
const SettingsTab = ({ rep, foot }) => {
  const run = rep.run || {};
  const summary = run.summary || {};
  return (
    <GridWorkspace key="se">
      <GridItem x={0} y={0} w={16} h={24} minW={8} minH={10}>
        <Pane title="Settings" tag="AS IN FILE" style={{ height: '100%' }} bodyStyle={{ padding: 0 }} foot={foot}>
          <MdlSheetSections sheet={mdlSheet(rep.report, 'Settings')}
            emptyMsg="'Settings' sheet empty in this export" />
        </Pane>
      </GridItem>
      <GridItem x={16} y={0} w={8} h={10} minW={6} minH={6}>
        <Pane title="Import Provenance" style={{ height: '100%' }} foot={foot}>
          <FieldList dense rows={[
            { label: 'Source file', value: summary.source_file || '—', color: 'cyan' },
            { label: 'Source app', value: run.source_app || '—' },
            { label: 'Imported', value: _mdlDt(run.created_at) },
            { label: 'Window', value: (run.date_from || '—') + ' → ' + (run.date_to || '—') },
            { label: 'Status', value: (run.status || '—').toUpperCase() },
          ]} />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

Object.assign(window, {
  MCNum, MdlCellR, MdlSheetSections,
  StrategyAnalysisTab, GraphsTab, TradesTab, AnalysisTab, PeriodicalTab, SettingsTab,
});
