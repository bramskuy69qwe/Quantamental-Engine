/* v3.0 P7 — per-model detail: Overview tab (risk/source/strategy/runs/usage
   chrome) + ModelView (nested section tabs mirroring the MultiCharts report
   sheets + run selector). Data: the model row comes from the overview feed
   (ModelsPage); runs / usage / the per-run report are fetched here via
   useAnaJson, whose qeFootState `foot` binds every pane (DESIGN.md §5). */

const _MdlFieldRow = ({ l, v, color }) => (
  <div style={{ display: 'grid', gridTemplateColumns: '104px 1fr', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--qe-faint)' }}>
    <span style={{ fontFamily: 'var(--qe-ui)', fontSize: '0.54rem', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--qe-muted)' }}>{l}</span>
    <span className="qe-mono" style={{ fontSize: '0.62rem', color: color || 'var(--qe-text)', textWrap: 'pretty' }}>{v}</span>
  </div>
);

const _mdlOr = (v, suffix = '') => (v != null && v !== '' ? String(v) + suffix : '—');

/* ── Overview tab — model chrome ─────────────────────────────────────────── */
const ModelOverviewTab = ({ m, runs, runsFoot, usage, usageFoot, ovFoot, onOpenRun, onImport, onLoadCalc }) => {
  const r = m.risk_preset || {};
  const s = m.strategy || {};
  const src = m.source || {};
  const hasSrc = Object.keys(src).length > 0;
  const closed = (usage && usage.closed) || [];
  const plans = (usage && usage.plans) || [];
  return (
    <GridWorkspace key={'ov-' + m.id}>
      <GridItem x={0} y={0} w={8} h={11} minW={5} minH={8}>
        <Pane title="Risk, Sizing & Source" style={{ height: '100%' }} foot={ovFoot}>
          <_MdlFieldRow l="Risk / trade" v={r.risk_pct != null ? (+r.risk_pct).toFixed(2) + '%' : '—'} color="var(--qe-cyan)" />
          <_MdlFieldRow l="Sizing rule" v={_mdlOr(r.sizing_rule)} />
          <_MdlFieldRow l="Match window" v={r.window_seconds != null ? r.window_seconds + 's' : '—'} />
          <_MdlFieldRow l="TP method" v={_mdlOr(r.tp_methodology)} />
          <_MdlFieldRow l="SL method" v={_mdlOr(r.sl_methodology)} />
          <_MdlFieldRow l="Regime mult." v={r.apply_regime_multiplier ? 'ON' : 'OFF'} color={r.apply_regime_multiplier ? 'var(--qe-green)' : 'var(--qe-muted)'} />
          <_MdlFieldRow l="Size override" v={r.size_override_default != null ? '$' + r.size_override_default : '—'} />
          {hasSrc && (
            <React.Fragment>
              <div style={{ margin: '7px 0 3px', fontFamily: 'var(--qe-ui)', fontSize: '0.5rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--qe-cyan)' }}>Source · {src.app || '—'}</div>
              <_MdlFieldRow l="Symbol" v={_mdlOr(src.symbol)} color="var(--qe-cyan)" />
              <_MdlFieldRow l="Resolution" v={_mdlOr(src.resolution)} />
              <_MdlFieldRow l="Point value" v={src.point_value != null ? '$' + src.point_value + (src.currency ? ' / ' + src.currency : '') : '—'} />
              <_MdlFieldRow l="Init capital" v={src.initial_capital != null ? '$' + Number(src.initial_capital).toLocaleString() : '—'} />
              <_MdlFieldRow l="Commission" v={_mdlOr(src.commission)} />
              <_MdlFieldRow l="Slippage" v={_mdlOr(src.slippage)} />
            </React.Fragment>
          )}
          <button className="qe-btn qe-btn-sm qe-btn-on" style={{ marginTop: 8, width: '100%', justifyContent: 'center' }} onClick={onLoadCalc}>↪ Load into Pre-Trade</button>
        </Pane>
      </GridItem>

      <GridItem x={0} y={11} w={8} h={6} minW={5} minH={6}>
        <Pane title="Strategy Definition" style={{ height: '100%' }} foot={ovFoot}>
          {s.notes && <div style={{ fontSize: '0.6rem', color: 'var(--qe-sub)', lineHeight: 1.5, marginBottom: 7, textWrap: 'pretty' }}>{s.notes}</div>}
          <_MdlFieldRow l="Entry logic" v={_mdlOr(s.entry_logic)} />
          <_MdlFieldRow l="Exit logic" v={_mdlOr(s.exit_logic)} />
          <_MdlFieldRow l="Universe" v={_mdlOr(s.target_universe)} color="var(--qe-cyan)" />
          <_MdlFieldRow l="Regime cfg" v={_mdlOr(s.regime_config)} />
        </Pane>
      </GridItem>

      <GridItem x={8} y={0} w={16} h={8} minW={9} minH={7}>
        <Pane title="Backtest Runs" count={(runs || []).length} style={{ height: '100%' }}
          right={<button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onImport}>⤓ Import Report</button>}
          foot={runsFoot} bodyStyle={{ padding: 0 }}>
          {(runs || []).length ? (
            <DataList selKey="id" onClick={(row) => { if (row.status === 'completed') onOpenRun(row); }}
              columns={[
                { key: 'source_app', label: 'SOURCE', filter: true,
                  filterVal: (r2) => String(r2.source_app || '—').toUpperCase(),
                  render: (r2) => <Badge tone="info">{r2.source_app || '—'}</Badge> },
                // FILE/WINDOW render values that live off the row (summary.source_file,
                // a date RANGE), which is why they had opted out entirely. The
                // accessors reach exactly what the cell shows.
                { key: 'file', label: 'FILE',
                  sortVal:   (r2) => (r2.summary && r2.summary.source_file) || r2.name || '',
                  searchVal: (r2) => (r2.summary && r2.summary.source_file) || r2.name || '',
                  render: (r2) => <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-sub)' }}>{(r2.summary && r2.summary.source_file) || r2.name || '—'}</span> },
                { key: 'window', label: 'WINDOW', sortVal: (r2) => r2.date_from || '', render: (r2) => <span className="qe-mono" style={{ fontSize: '0.54rem' }}>{_mdlDate(r2.date_from)} → {_mdlDate(r2.date_to)}</span> },
                { key: 'net', label: 'NET P/L', align: 'right', sortVal: (r2) => mdlRunKpis(r2.summary).net, render: (r2) => { const k = mdlRunKpis(r2.summary); return <span className="qe-mono" style={{ color: _mdlPl(k.net), fontWeight: 700 }}>{_mdlMoney(k.net, 0)}</span>; } },
                { key: 'pf', label: 'PF', align: 'right', sortVal: (r2) => mdlRunKpis(r2.summary).pf, render: (r2) => <span className="qe-mono">{mdlRunKpis(r2.summary).pf.toFixed(2)}</span> },
                { key: 'win', label: 'WIN%', align: 'right', sortVal: (r2) => mdlRunKpis(r2.summary).winPct, render: (r2) => <span className="qe-mono">{mdlRunKpis(r2.summary).winPct}%</span> },
                { key: 'dd', label: 'MAX DD', align: 'right', sortVal: (r2) => mdlRunKpis(r2.summary).maxDDPct, render: (r2) => <span className="qe-mono" style={{ color: 'var(--qe-red)' }}>{mdlRunKpis(r2.summary).maxDDPct}%</span> },
                { key: 'n', label: 'TRADES', align: 'right', sortVal: (r2) => mdlRunKpis(r2.summary).nTrades, render: (r2) => <span className="qe-mono">{mdlRunKpis(r2.summary).nTrades}</span> },
                { key: 'status', label: 'STATUS', filter: true,
                  filterVal: (r2) => (r2.status || '—').toUpperCase(),
                  render: (r2) => <Badge tone={r2.status === 'completed' ? 'ok' : r2.status === 'failed' ? 'err' : 'warn'}>{(r2.status || '—').toUpperCase()}</Badge> },
                { key: 'created_at', label: 'IMPORTED', align: 'right', render: (r2) => <span className="qe-mono" style={{ fontSize: '0.54rem', color: 'var(--qe-muted)' }}>{_mdlDt(r2.created_at)}</span> },
              ]}
              rows={runs} />
          ) : (
            <div style={{ padding: 10, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <EmptyState tone="warn" glyph="⤓" msg="No backtests imported yet"
                hint="Performance only ever comes from imported reports (MultiCharts .xlsx / .xml)."
                cta={<button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onImport}>⤓ Import a report</button>} />
            </div>
          )}
        </Pane>
      </GridItem>

      <GridItem x={8} y={8} w={16} h={9} minW={9} minH={6}>
        <Pane title="Usage / Attribution" count={closed.length + plans.length} style={{ height: '100%' }}
          foot={usageFoot} bodyStyle={{ padding: 0 }}>
          {(closed.length || plans.length) ? (
            <div>
              {closed.length > 0 && (
                <React.Fragment>
                  <SecLbl rule style={{ margin: '6px 7px 2px' }}>Closed positions</SecLbl>
                  <DataList selKey="id"
                    columns={[
                      { key: 'terminal_position_id', label: 'POSITION', render: (u) => <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontSize: '0.56rem' }}>{u.terminal_position_id || ('#' + u.id)}</span> },
                      { key: 'symbol', label: 'SYMBOL' },
                      { key: 'direction', label: 'SIDE', render: (u) => <Badge tone={u.direction === 'long' ? 'ok' : u.direction === 'short' ? 'err' : 'mute'}>{(u.direction || '—').toUpperCase()}</Badge> },
                      { key: 'net_pnl', label: 'NET PnL', align: 'right', sortVal: (u) => u.net_pnl, render: (u) => (u.net_pnl == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <span className="qe-mono" style={{ color: _mdlPl(u.net_pnl), fontWeight: 700 }}>{(u.net_pnl >= 0 ? '+' : '') + (+u.net_pnl).toFixed(2)}</span>) },
                      { key: 'exit_time_ms', label: 'CLOSED', align: 'right', render: (u) => <span className="qe-mono" style={{ color: 'var(--qe-muted)', fontSize: '0.54rem' }}>{_mdlMs(u.exit_time_ms)}</span> },
                    ]}
                    rows={closed} />
                </React.Fragment>
              )}
              {plans.length > 0 && (
                <React.Fragment>
                  <SecLbl rule style={{ margin: '6px 7px 2px' }}>Pre-trade plans</SecLbl>
                  <DataList selKey="id"
                    columns={[
                      { key: 'calc_id', label: 'CALC', render: (u) => <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontSize: '0.56rem' }}>{u.calc_id || ('#' + u.id)}</span> },
                      { key: 'ticker', label: 'TICKER' },
                      { key: 'side', label: 'SIDE', render: (u) => <Badge tone={/long|buy/i.test(u.side || '') ? 'ok' : /short|sell/i.test(u.side || '') ? 'err' : 'mute'}>{(u.side || '—').toUpperCase()}</Badge> },
                      // forced: COMPLETED_VIA_POSITION exceeds DL_VALUE_MAXLEN(16),
                      // so auto-derivation refuses this column outright.
                      { key: 'status', label: 'STATUS', filter: true,
                        filterVal: (u) => (u.status || '—').toUpperCase(),
                        render: (u) => <Badge tone="mute">{(u.status || '—').toUpperCase()}</Badge> },
                      { key: 'timestamp', label: 'PLANNED', align: 'right', render: (u) => <span className="qe-mono" style={{ color: 'var(--qe-muted)', fontSize: '0.54rem' }}>{_mdlDt(u.timestamp)}</span> },
                    ]}
                    rows={plans} />
                </React.Fragment>
              )}
            </div>
          ) : (
            <div style={{ padding: 10, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <EmptyState tone="neutral" glyph="∅" msg="Not used by any positions yet"
                hint="Closed positions and pre-trade plans tagged with this model appear here (open positions appear once closed)." />
            </div>
          )}
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

const MODEL_SECTIONS = [
  ['overview', 'Overview'],
  ['strategy', 'Strategy Analysis'],
  ['graphs', 'Graphs'],
  ['trades', 'List of Trades'],
  ['analysis', 'Trade Analysis'],
  ['periodical', 'Periodical'],
  ['settings', 'Settings'],
];

/* ── ModelView — nested tab shell + run selector ─────────────────────────── */
const ModelView = ({ m, ovFoot, onImport, onLoadCalc }) => {
  const [section, setSection] = React.useState('overview');
  const [runId, setRunId] = React.useState(null);

  const { data: runsData, foot: runsFoot, reload: reloadRuns } = useAnaJson(`/api/models/${m.id}/runs`);
  const { data: usage, foot: usageFoot, reload: reloadUsage } = useAnaJson(`/api/models/${m.id}/usage`);
  const allRuns = (runsData && runsData.runs) || [];
  const runs = allRuns.filter((r) => r.status === 'completed');

  React.useEffect(() => { setSection('overview'); setRunId(null); }, [m.id]);

  const run = runs.find((r) => r.id === runId) || runs[0] || null;
  const effRunId = run ? run.id : null;
  const { data: rep, err: repErr, reload: reloadRep, foot: repFoot } = useAnaJson(
    effRunId != null ? `/api/models/${m.id}/runs/${effRunId}/report` : null);
  const report = effRunId != null && rep && rep.run ? rep : null;
  const needsRun = section !== 'overview' && !report;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <TabStrip value={section} onChange={setSection} tabs={MODEL_SECTIONS}
        right={run && section !== 'overview' ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 8 }}>
            <span style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Run</span>
            {runs.length > 1 ? (
              <select className="qe-input qe-select" value={effRunId} onChange={(e) => setRunId(+e.target.value)} style={{ width: 190, height: 18, alignSelf: 'center' }}>
                {runs.map((r) => <option key={r.id} value={r.id}>#{r.id} · {(r.summary && r.summary.source_file) || r.name || r.source_app}</option>)}
              </select>
            ) : (
              <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-cyan)', alignSelf: 'center' }}>#{run.id} · {(run.summary && run.summary.source_file) || run.name || run.source_app}</span>
            )}
          </div>
        ) : null} />

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {section === 'overview' && (
          <ModelOverviewTab m={m} runs={allRuns} runsFoot={runsFoot} usage={usage} usageFoot={usageFoot} ovFoot={ovFoot}
            onImport={() => onImport(() => { reloadRuns(); reloadUsage(); })}
            onLoadCalc={onLoadCalc}
            onOpenRun={(r) => { setRunId(r.id); setSection('strategy'); }} />
        )}
        {needsRun && (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
            {run && repErr ? (
              // MED-2 fold: a failed report fetch is a TERMINAL state on
              // this one-shot pipe — name the cause (tier 3), offer retry.
              <EmptyState tone="err" glyph="✗" msg="run report unavailable"
                hint={qeFootCause(repErr)}
                cta={<button className="qe-btn qe-btn-sm" onClick={reloadRep}>Retry</button>} />
            ) : run ? (
              <Spinner label="loading run report" />
            ) : (
              <EmptyState tone="warn" glyph="⤓" msg="No imported run to report on"
                hint="This model has no completed backtest import yet. Import a MultiCharts report (.xlsx / .xml) to populate Strategy Analysis, trades, and the rest."
                cta={<button className="qe-btn qe-btn-sm qe-btn-primary" onClick={() => onImport(() => { reloadRuns(); reloadUsage(); })}>⤓ Import a report</button>} />
            )}
          </div>
        )}
        {!needsRun && section === 'strategy' && <StrategyAnalysisTab rep={report} foot={repFoot} />}
        {!needsRun && section === 'graphs' && <GraphsTab rep={report} foot={repFoot} />}
        {!needsRun && section === 'trades' && <TradesTab rep={report} foot={repFoot} />}
        {!needsRun && section === 'analysis' && <AnalysisTab rep={report} foot={repFoot} />}
        {!needsRun && section === 'periodical' && <PeriodicalTab rep={report} foot={repFoot} />}
        {!needsRun && section === 'settings' && <SettingsTab rep={report} foot={repFoot} />}
      </div>
    </div>
  );
};

Object.assign(window, { ModelView, ModelOverviewTab });
