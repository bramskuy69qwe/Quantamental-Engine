/* v3.0 — Analytics page (P5). Ported from the Meridian reference
   (pages.jsx AnalyticsPage + pages-analytics-exec.jsx) and WIRED to real data:
     · Overview      ← /fragments/analytics/overview?format=json (+daily_equity)
     · Equity Curve  ← /api/analytics/equity_ohlc (the pre-existing JSON — no
       door on the equity fragment; its ctx is Jinja render knobs)
     · Distributions ← /api/analytics/distributions (G-O4; client bins, design parity)
     · Calendar PnL  ← /fragments/analytics/calendar?format=json (own month nav)
     · Traded Pairs  ← /fragments/analytics/pairs?format=json
     · MFE/MAE       ← /fragments/analytics/excursions?format=json (server dir filter)
     · R-Multiples   ← /fragments/analytics/r_multiples?format=json
     · Risk Metrics  ← /fragments/analytics/var?format=json (≥20-returns gate)
     · Execution     ← /api/analytics/execution (G-O4; fills JOIN pre_trade_log)
     · Funding       ← /fragments/analytics/funding?format=json (30s poll)
     · Beta          ← /fragments/analytics/beta?format=json
   Named deviations vs the design mock (engine truth wins):
   - Equity tf presets are the ENGINE set (1W/2W/1M/3M/6M/1Y/all), not 1h/4h/1d.
   - Execution "latency" is TIME-TO-FILL (fills.timestamp_ms − orders.created_at_ms,
     engine-observed): no signal→fill source exists in the observe-only
     architecture; bins are adaptive (ms→hours), the 40 ms target line is dropped.
   - Maker/taker static fee-rate footer dropped (no engine source).
   - Beta β-adj exposure is UNSIGNED (abs notional × beta — engine/Jinja parity;
     the mock's signed SHORT exposure has no engine source).
   - Funding per-8h/day/week are unsigned magnitudes + adverse flag; the signed
     display (and signed Σ) is derived client-side from `adverse`.
   - Sortino/PF 999.0 = the engine "no downside/no losers" sentinel → rendered ∞.
   - PaneFoot telemetry lines from the design are mock ornaments — not ported
     (P1-P4 parity). Period default is 'monthly' (the account's saved
     analytics_default_period is not fetched — residue).
   - PERIOD nav (‹ ›) is ENABLED for month/week/quarter/year (real offset nav —
     the reference disabled it only because its demo dataset was frozen).
   - Execution slippage is RESIDUAL-vs-plan (audit H-1): fills.slippage_actual
     is measured against the impact-ADJUSTED predicted fill (effective_entry),
     so the calibration reference is 0, not the est line — the scatter's y=x
     from the design becomes a y=0 line, the per-fill BIAS column collapses
     into RESIDUAL, and est_slippage renders as "predicted impact" context.
   - Smaller unannotated-in-v1 divergences (audit N6): Overview drops the
     design's "Daily Avg PnL %" row + under-chart start/%/end strip; Equity
     drops "Adj Chg"; Beta preset pane shows raw engine sector keys; the
     per-fill filter row has no reduce_only button (such fills show under
     "all" only). Keep-last-good means a dead engine freezes tabs on stale
     numbers (P4 parity) — only Funding, the live tab, flips its dot to a
     STALE warning on poll failure. */

const ANA_TABS = [
  ['overview',   'Overview'],
  ['equity',     'Equity Curve'],
  ['dist',       'Distributions'],
  ['calendar',   'Calendar PnL'],
  ['pairs',      'Traded Pairs'],
  ['excursions', 'MFE / MAE'],
  ['rmultiples', 'R-Multiples'],
  ['risk',       'Risk Metrics'],
  ['execution',  'Execution Quality'],
  ['funding',    'Funding'],
  ['beta',       'Beta Exposure'],
];
// FE-MED-018 contract: these tabs consume the page-level period; the bar dims
// (disabled) on the rest — a dead control must look dead.
const ANA_PERIOD_TABS = new Set(['overview', 'dist', 'pairs', 'excursions', 'rmultiples', 'risk']);
const ANA_NO_NAV = new Set(['rolling_30d', 'rolling_90d', 'all_time']);

const _anaPnl = (v) => (v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)');
const _anaQS = (period, offset) => `period=${encodeURIComponent(period)}&offset=${offset}`;
const _anaRatio = (v) => (v == null ? '—' : (v >= 999 ? '∞' : (+v).toFixed(2)));
const _anaMs = (ms) => {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}m`;
  return `${(ms / 3_600_000).toFixed(1)}h`;
};

/* fetch hook — seq stale-guard + keep-last-good (P4 idioms) */
const useAnaJson = (url, intervalMs = 0) => {
  const [data, setData] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const seqRef = React.useRef(0);
  const load = React.useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      const d = await _ptJson(url);
      if (seq === seqRef.current) { setData(d); setErr(null); }
    } catch (e) {
      if (seq === seqRef.current) { setErr(String((e && e.message) || e)); }  // keep last-good
    }
    if (seq === seqRef.current) setLoading(false);
  }, [url]);
  React.useEffect(() => { setLoading(true); load(); }, [load]);
  React.useEffect(() => {
    if (!intervalMs) return undefined;
    const t = setInterval(load, intervalMs);
    return () => clearInterval(t);
  }, [load, intervalMs]);
  return { data, err, loading, reload: load };
};

/* report the server period_label up to the PeriodNav */
const useAnaLabel = (data, onLabel) => {
  React.useEffect(() => {
    if (data && data.period_label && onLabel) onLabel(data.period_label);
  }, [data, onLabel]);
};

const AnaEmpty = ({ err, msg }) => (
  <div style={{ padding: 4, height: '100%' }}>
    <EmptyState tone={err ? 'warn' : 'neutral'} glyph={err ? '⚠' : '◇'}
      msg={err ? 'analytics fetch failed — engine unreachable?' : msg}
      hint={err || undefined} />
  </div>
);

const AnaKv = ({ label, value, color }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
    <Lbl>{label}</Lbl>
    <span className="qe-mono" style={{ fontSize: '0.82rem', fontWeight: 700, color: color || 'var(--qe-text)' }}>{value}</span>
  </div>
);

const AnaVRow = ({ label, value, color }) => (
  <div className="qe-fl-row">
    <div className="qe-fl-l"><span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</span></div>
    <div className="qe-fl-v" style={color ? { color } : undefined}>{value}</div>
  </div>
);

/* ── period bar (design PeriodNav; real offset nav, server label) ───────── */
const AnaPeriodNav = ({ period, onPeriod, onNav, disabled, label }) => {
  const presets = [['monthly', 'Month'], ['weekly', 'Week'], ['quarterly', 'Quarter'],
    ['yearly', 'Year'], ['rolling_30d', '30D'], ['rolling_90d', '90D'], ['all_time', 'All']];
  const noNav = ANA_NO_NAV.has(period);
  return (
    <div title={disabled ? "Period filter doesn't apply to this sub-tab — it has its own controls." : ''}
      style={{ display: 'flex', alignItems: 'center', gap: 6, opacity: disabled ? 0.4 : 1, pointerEvents: disabled ? 'none' : 'auto' }}>
      <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={noNav} style={noNav ? { opacity: 0.45 } : undefined} onClick={() => onNav(-1)}>‹</button>
      <span className="qe-mono" style={{ fontSize: '0.74rem', fontWeight: 700, minWidth: 120, textAlign: 'center', color: 'var(--qe-text)' }}>{label || '…'}</span>
      <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={noNav} style={noNav ? { opacity: 0.45 } : undefined} onClick={() => onNav(+1)}>›</button>
      <span style={{ color: 'var(--qe-muted)', margin: '0 2px' }}>│</span>
      <PeriodSelector options={presets} value={period} onChange={onPeriod} />
    </div>
  );
};

/* ── page-local ECharts (ported from pages-analytics-exec.jsx) ──────────── */

// Histogram — bars + top value labels. divergent colors by bin.pos.
const AnaHistChart = ({ bins, color = 'var(--qe-cyan)', height = '100%', unit = '', divergent = false, noun = 'trade', tip = null }) => {
  const ref = React.useRef(null);
  const c = _qeResolveColor(color);
  const green = QE_ECHARTS_THEME.green, red = QE_ECHARTS_THEME.red;
  const opts = React.useMemo(() => ({
    ..._baseChart({ grid: { left: 30, right: 10, top: 18, bottom: 20 } }),
    tooltip: {
      trigger: 'axis', backgroundColor: '#000', borderColor: QE_ECHARTS_THEME.cyan, borderWidth: 1, padding: [4, 8],
      textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
      axisPointer: { type: 'shadow', shadowStyle: { color: (divergent ? green : c) + '22' } },
      formatter: (p) => {
        const v = p[0].data.value ?? p[0].data;
        if (tip) return tip(p[0].axisValue, v);
        return `${p[0].axisValue || '—'}${unit} · ${v} ${noun}${v === 1 ? '' : 's'}`;
      },
    },
    xAxis: {
      type: 'category', data: bins.map((b) => b.label),
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 9, fontFamily: 'JetBrains Mono, monospace' }, splitLine: { show: false } }),
    },
    yAxis: {
      type: 'value', minInterval: 1,
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 9, fontFamily: 'JetBrains Mono, monospace' },
        splitLine: { lineStyle: { color: QE_ECHARTS_THEME.faint, opacity: 0.4, type: [2, 3] } } }),
    },
    series: [{
      type: 'bar', barWidth: '62%',
      data: bins.map((b) => ({ value: b.count, itemStyle: { color: divergent ? (b.pos ? green : red) : c, opacity: 0.82 } })),
      emphasis: { itemStyle: { opacity: 1 } },
      label: { show: true, position: 'top', fontSize: 9, fontFamily: 'JetBrains Mono, monospace',
        color: divergent ? QE_ECHARTS_THEME.sub : c,
        formatter: (x) => (x.value > 0 ? x.value : '') },
    }],
  }), [bins, c, unit, divergent, noun]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} className="qe-chart" style={{ height }} />;
};

// Diverging bars around zero (avg PnL by DoW), green up / red down.
const AnaDivergingBars = ({ rows, height = '100%', fmt = (v) => v.toFixed(2) }) => {
  const ref = React.useRef(null);
  const green = QE_ECHARTS_THEME.green, red = QE_ECHARTS_THEME.red;
  const opts = React.useMemo(() => ({
    ..._baseChart({ grid: { left: 34, right: 10, top: 16, bottom: 30 } }),
    tooltip: {
      trigger: 'axis', backgroundColor: '#000', borderColor: QE_ECHARTS_THEME.cyan, borderWidth: 1, padding: [4, 8],
      textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
      axisPointer: { type: 'shadow', shadowStyle: { color: QE_ECHARTS_THEME.text + '10' } },
      formatter: (p) => { const r = rows[p[0].dataIndex]; return `${r.label} · ${(r.v >= 0 ? '+' : '') + fmt(r.v)} · ${r.n} trade${r.n === 1 ? '' : 's'}`; },
    },
    xAxis: {
      type: 'category', data: rows.map((r) => r.label),
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 9, fontFamily: 'JetBrains Mono, monospace' }, splitLine: { show: false } }),
    },
    yAxis: {
      type: 'value',
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 9, fontFamily: 'JetBrains Mono, monospace', formatter: (v) => v.toFixed(1) },
        splitLine: { lineStyle: { color: QE_ECHARTS_THEME.faint, opacity: 0.4, type: [2, 3] } } }),
    },
    series: [{
      type: 'bar', barWidth: '56%',
      data: rows.map((r) => ({ value: r.n > 0 ? r.v : 0, itemStyle: { color: r.v >= 0 ? green : red, opacity: 0.82 } })),
      markLine: { symbol: 'none', silent: true, data: [{ yAxis: 0, lineStyle: { color: QE_ECHARTS_THEME.line, width: 1 }, label: { show: false } }] },
      emphasis: { itemStyle: { opacity: 1 } },
      label: { show: true, fontSize: 9, fontFamily: 'JetBrains Mono, monospace', color: QE_ECHARTS_THEME.sub,
        position: 'top', formatter: (x) => { const r = rows[x.dataIndex]; return (r.n > 0 && Math.abs(r.v) > 0.005) ? (r.v >= 0 ? '+' : '') + fmt(r.v) : ''; } },
    }],
  }), [rows, fmt]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} className="qe-chart" style={{ height }} />;
};

const ANA_FT_COLOR = {
  entry: 'var(--qe-blue)', tp: 'var(--qe-green)', sl: 'var(--qe-red)',
  manual: 'var(--qe-muted)', reduce_only: 'var(--qe-sub)',
};

// Entry scatter — predicted impact (bp, x) vs residual-vs-plan (bp, y).
// Calibration reference is the y=0 line (audit H-1): the residual is measured
// against the impact-ADJUSTED predicted fill, so a perfect model lands at 0.
const AnaExecScatter = ({ points, height = '100%' }) => {
  const ref = React.useRef(null);
  const opts = React.useMemo(() => {
    const maxX = Math.max(...points.map((p) => p.est), 1) * 1.18;
    const maxY = Math.max(...points.map((p) => p.act), 1) * 1.18;
    const minY = Math.min(0, ...points.map((p) => p.act)) * 1.18;
    const data = points.map((p) => ({
      value: [p.est, p.act], name: p.id,
      itemStyle: {
        color: _qeResolveColor(ANA_FT_COLOR[p.ft] || 'var(--qe-sub)'), opacity: 0.82,
        borderColor: p.act > 0 ? QE_ECHARTS_THEME.red : 'transparent',
        borderWidth: p.act > 0 ? 1.6 : 0,
      },
      _ft: p.ft,
    }));
    return {
      ..._baseChart({ grid: { left: 46, right: 16, top: 14, bottom: 40 } }),
      tooltip: {
        trigger: 'item', backgroundColor: '#000', borderColor: QE_ECHARTS_THEME.cyan, borderWidth: 1, padding: [4, 8],
        textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
        formatter: (o) => {
          const d = o.data;
          return `<b>${d.name}</b> · ${d._ft}<br/>impact est ${d.value[0].toFixed(2)}bp<br/>residual&nbsp;&nbsp;${(d.value[1] >= 0 ? '+' : '') + d.value[1].toFixed(2)}bp vs plan`;
        },
      },
      xAxis: { type: 'value', min: 0, max: maxX, name: 'Predicted impact (bp)', nameLocation: 'center', nameGap: 24,
        nameTextStyle: { color: QE_ECHARTS_THEME.sub, fontSize: 10 }, ..._axis() },
      yAxis: { type: 'value', min: minY, max: maxY, name: 'Residual vs plan (bp)', nameLocation: 'middle', nameGap: 32, nameRotate: 90,
        nameTextStyle: { color: QE_ECHARTS_THEME.sub, fontSize: 10 }, ..._axis() },
      series: [
        { type: 'line', silent: true, symbol: 'none', data: [[0, 0], [maxX, 0]],
          lineStyle: { color: QE_ECHARTS_THEME.muted, type: 'dashed', width: 1 }, tooltip: { show: false }, z: 1 },
        { type: 'scatter', data, symbolSize: 11, z: 2, emphasis: { scale: 1.3, itemStyle: { opacity: 1 } } },
      ],
    };
  }, [points]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} className="qe-chart" style={{ height }} />;
};

/* ── Overview ───────────────────────────────────────────────────────────── */
const AnaTabOverview = ({ period, offset, onLabel }) => {
  const { data, err } = useAnaJson(`/fragments/analytics/overview?format=json&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return <AnaEmpty err={err} msg="loading overview…" />;
  const s = data.stats || {}, b = data.boundaries || {}, c = data.cumulative || {}, ra = data.ratios || {};
  const lbl = data.period_label || '';
  const days = data.trading_days || 0;
  const pnl = s.total_pnl || 0;
  const initial = b.initial_equity || 0;
  const pnlPct = initial > 0 ? (pnl / initial) * 100 : null;
  const total = s.total_trades || 0;
  const wins = s.winning_trades || 0;
  const winrate = total > 0 ? (wins / total) * 100 : 0;
  const rr = (s.avg_profit && s.avg_loss) ? Math.abs(s.avg_profit / s.avg_loss) : null;
  const eqSeries = (data.daily_equity || []).map((r) => r.total_equity).filter((v) => v != null);
  // PF/Expectancy are R-derived: with zero R-linked closes the route's 0.0
  // default is "no data", not "catastrophic" — render em-dash (audit L1).
  const noR = (data.r_count || 0) === 0;
  const ratioRows = [
    ['Sharpe', ra.sharpe, 'annualized'],
    ['Sharpe (MFE)', ra.sharpe_mfe, 'mfe / notional'],
    ['Sortino', ra.sortino, 'downside σ · ∞ = no downside days'],
    ['Sortino (MAE)', ra.sortino_mae, 'mae / notional'],
    ['Profit Factor', noR ? null : ra.profit_factor, 'Σ gross w / |Σ gross l| · ∞ = no losers'],
    ['Expectancy', noR ? null : ra.expectancy, 'mean R-multiple', 'R'],
  ].map(([l, v, d, suf]) => {
    const empty = v == null;
    const inf = !empty && v >= 999;
    const color = empty ? 'sub' : (inf || v >= 2 ? 'green' : v >= 1 ? 'amber' : 'red');
    return { label: l, hint: d, value: empty ? '—' : (inf ? '∞' : (+v).toFixed(2) + (suf || '')), color };
  });
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={8} h={6} minW={5} minH={5}>
        <Pane title="Volume & Activity" tag={lbl} style={{ height: '100%' }}
          foot={{ tone: 'sub', msg: 'from exchange_history · funding/transfers excluded' }}>
          <AnaVRow label="Trading Volume" value={`$${(s.trading_volume || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
          <AnaVRow label="Fees Paid" value={`$${(s.total_fees || 0).toFixed(2)}`} />
          <AnaVRow label="No. of Longs" value={s.num_longs || 0} color="var(--qe-green)" />
          <AnaVRow label="No. of Shorts" value={s.num_shorts || 0} color="var(--qe-red)" />
          <div style={{ marginTop: 8 }}>
            <Lbl>Top Pairs</Lbl>
            <div className="qe-mono" style={{ fontSize: '0.68rem', color: 'var(--qe-sub)', marginTop: 2 }}>
              {(data.top_pairs || []).length ? data.top_pairs.join(' · ') : '—'}
            </div>
          </div>
        </Pane>
      </GridItem>

      <GridItem x={8} y={0} w={16} h={7} minW={8} minH={5}>
        <Pane title="Equity & PnL" tag={lbl} style={{ height: '100%' }} bodyStyle={{ padding: 0 }}
          foot={{ tone: pnl >= 0 ? 'ok' : 'warn', msg: `${days} trading days · period pnl ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(200px,0.9fr) 1px 1.3fr', gap: 0, height: '100%' }}>
            <div style={{ padding: '7px 12px 7px 8px' }}>
              <FieldList rows={[
                { label: 'Initial Equity', value: `$${initial.toFixed(2)}` },
                { label: 'Final Equity', value: `$${(b.final_equity || 0).toFixed(2)}` },
                { label: 'Period PnL', value: `$${pnl.toFixed(2)}`, color: _anaPnl(pnl) },
                { label: 'Period PnL %', value: pnlPct == null ? '—' : `${pnlPct.toFixed(2)}%`, color: _anaPnl(pnlPct || 0) },
                { label: 'Daily Avg PnL', value: days ? `$${(pnl / days).toFixed(2)}` : '—', color: _anaPnl(pnl) },
                { label: 'Trading Days', value: days },
              ]} />
            </div>
            <div style={{ background: 'var(--qe-line)' }} />
            <div style={{ padding: '7px 8px 7px 12px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <Lbl>Equity Curve · {lbl}</Lbl>
              <div style={{ flex: 1, minHeight: 0, marginTop: 2 }}>
                {eqSeries.length >= 2
                  ? <EquityChart data={eqSeries} color={_anaPnl(pnl)} baseline={initial || null} height="100%" />
                  : <div className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-muted)', padding: 8 }}>not enough snapshots in window</div>}
              </div>
            </div>
          </div>
        </Pane>
      </GridItem>

      <GridItem x={0} y={6} w={8} h={10} minW={5} minH={6}>
        <Pane title="Trade Statistics" style={{ height: '100%' }}
          foot={{ tone: 'sub', msg: `${total} trades · win ${winrate.toFixed(1)}%` }}>
          <AnaVRow label="Total Trades" value={total} />
          <AnaVRow label="Winning" value={wins} color="var(--qe-green)" />
          <AnaVRow label="Losing" value={s.losing_trades || 0} color="var(--qe-red)" />
          <AnaVRow label="Win Rate" value={`${winrate.toFixed(1)}%`} color={winrate >= 50 ? 'var(--qe-green)' : 'var(--qe-red)'} />
          <AnaVRow label="Avg W / L" value={rr == null ? '—' : `${rr.toFixed(2)}×`} />
          <AnaVRow label="Avg Profit" value={`$${(s.avg_profit || 0).toFixed(2)}`} color="var(--qe-green)" />
          <AnaVRow label="Avg Loss" value={`$${(s.avg_loss || 0).toFixed(2)}`} color="var(--qe-red)" />
          <AnaVRow label="Biggest Win" value={`$${(s.biggest_profit || 0).toFixed(2)}`} color="var(--qe-green)" />
          <AnaVRow label="Biggest Loss" value={`$${(s.biggest_loss || 0).toFixed(2)}`} color="var(--qe-red)" />
          <AnaVRow label="Max Drawdown" value={`${((b.max_drawdown || 0) * 100).toFixed(2)}%`} color="var(--qe-red)" />
        </Pane>
      </GridItem>

      <GridItem x={8} y={7} w={16} h={5} minW={8} minH={5}>
        <Pane title="Performance Ratios" style={{ height: '100%' }}>
          <FieldList cols={2} rows={ratioRows} />
        </Pane>
      </GridItem>

      <GridItem x={8} y={12} w={16} h={4} minW={8} minH={4}>
        <Pane title="Cash & Cumulative" style={{ height: '100%' }}>
          <FieldList cols={2} rows={[
            { label: 'Deposits (window)', value: `$${(s.deposits || 0).toFixed(2)}` },
            { label: 'Withdrawals (window)', value: `$${(s.withdrawals || 0).toFixed(2)}` },
            { label: 'Cumulative PnL (all-time)', value: `$${(c.total_pnl || 0).toFixed(2)}`, color: _anaPnl(c.total_pnl || 0) },
            { label: 'Cumulative PnL %', value: c.total_pnl_percent == null ? '—' : `${(+c.total_pnl_percent).toFixed(2)}%`, color: _anaPnl(c.total_pnl_percent || 0) },
          ]} />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Equity Curve ───────────────────────────────────────────────────────── */
const AnaTabEquity = () => {
  const [tf, setTf] = React.useState('1M');
  const [logScale, setLogScale] = React.useState(false);
  const [ddMode, setDdMode] = React.useState(false);
  const { data, err } = useAnaJson(`/api/analytics/equity_ohlc?tf=${encodeURIComponent(tf)}`);
  const candles = (data && data.candles) || [];
  const ddSeries = React.useMemo(() => {
    let peak = -Infinity;
    return candles.map((d) => {
      if (d.c != null) peak = Math.max(peak, d.c);
      return peak > 0 && d.c != null ? +(((d.c - peak) / peak) * 100).toFixed(2) : 0;
    });
  }, [candles]);
  if (!data) return <AnaEmpty err={err} msg="loading equity curve…" />;
  if (!candles.length) return <AnaEmpty err={err} msg="no equity snapshots yet" />;
  const last = candles[candles.length - 1];
  const prev = candles.length > 1 ? candles[candles.length - 2] : last;
  const chg = (last.c != null && prev.c != null) ? last.c - prev.c : 0;
  const chgPct = prev.c ? (chg / prev.c) * 100 : 0;
  const ohlcRow = [
    ['O', last.o, 'var(--qe-text)'], ['H', last.h, 'var(--qe-green)'],
    ['L', last.l, 'var(--qe-red)'], ['C', last.c, 'var(--qe-text)'],
  ];
  return (
    <div style={{ padding: 4, height: '100%' }}>
      <Pane title="Equity Curve" hot tag={ddMode ? 'DRAWDOWN %' : 'OHLC'}
        right={
          <>
            <PeriodSelector options={[['1W', '1W'], ['2W', '2W'], ['1M', '1M'], ['3M', '3M'], ['6M', '6M'], ['1Y', '1Y'], ['all', 'All']]} value={tf} onChange={setTf} />
            <button className={`qe-btn qe-btn-sm ${logScale && !ddMode ? 'qe-btn-on' : 'qe-btn-ghost'}`}
              disabled={ddMode} style={ddMode ? { opacity: 0.4 } : undefined}
              onClick={() => setLogScale((v) => !v)}>log scale</button>
            <button className={`qe-btn qe-btn-sm ${ddMode ? 'qe-btn-on' : 'qe-btn-ghost'}`}
              onClick={() => setDdMode((v) => !v)}>drawdown %</button>
          </>
        }
        style={{ height: '100%' }} bodyStyle={{ padding: 6 }}
        foot={{ tone: 'info', msg: `${candles.length} buckets · tf=${tf} · /api/analytics/equity_ohlc` }}>
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          <div className="qe-mono" style={{ fontSize: '0.62rem', display: 'flex', gap: 14, flexWrap: 'wrap', padding: '2px 4px', alignItems: 'baseline' }}>
            {ohlcRow.map(([k, v, col]) => (
              <span key={k}><span style={{ color: 'var(--qe-muted)' }}>{k}</span> <span style={{ color: col }}>{v == null ? '—' : `$${(+v).toFixed(2)}`}</span></span>
            ))}
            <span><span style={{ color: 'var(--qe-muted)' }}>Chg</span> <span style={{ color: _anaPnl(chg) }}>{`${chg >= 0 ? '+' : ''}$${chg.toFixed(2)} (${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%)`}</span></span>
            <span><span style={{ color: 'var(--qe-muted)' }}>Bar Range</span> <span>{(last.h != null && last.l != null) ? `$${(last.h - last.l).toFixed(2)}` : '—'}</span></span>
            <span><span style={{ color: 'var(--qe-muted)' }}>Cash Flow</span> <span style={{ color: 'var(--qe-blue)' }}>{last.cf ? `${last.cf >= 0 ? '+' : '-'}$${Math.abs(+last.cf).toFixed(2)}` : '+$0.00'}</span></span>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            {ddMode
              ? <EquityChart data={ddSeries} color="var(--qe-red)" baseline={0} />
              : <CandlestickChart data={candles.map((d) => [d.x, d.o, d.c, d.l, d.h])} logScale={logScale} />}
          </div>
        </div>
      </Pane>
    </div>
  );
};

/* ── Distributions (G-O4) ───────────────────────────────────────────────── */
const AnaTabDistributions = ({ period, offset, onLabel }) => {
  const { data, err } = useAnaJson(`/api/analytics/distributions?${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return <AnaEmpty err={err} msg="loading distributions…" />;
  const trades = data.trades || [];
  if (!trades.length) return <AnaEmpty err={err} msg="no closed trades in window" />;
  const lbl = data.period_label || '';

  // PnL bins — adaptive width (~12 bins over the data range, 'nice' step).
  const pnls = trades.map((t) => t.pnl).filter((v) => v != null);
  const lo = Math.min(...pnls, 0), hi = Math.max(...pnls, 0);
  const rawStep = (hi - lo) / 12 || 1;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= rawStep) || 10 * mag;
  const b0 = Math.floor(lo / step) * step;
  const nBins = Math.max(1, Math.ceil((hi - b0) / step) || 1);
  const pnlBins = Array.from({ length: nBins }, (_, i) => {
    const a = b0 + i * step;
    return {
      label: `${a >= 0 ? '+' : ''}${+a.toFixed(2)}`,
      count: pnls.filter((v) => v >= a && v < a + step).length,
      pos: a >= 0,
    };
  });

  const holds = trades.map((t) => t.hold_min).filter((v) => v != null);
  const HOLD_EDGES = [[0, 10], [10, 30], [30, 60], [60, 120], [120, 240], [240, 480], [480, Infinity]];
  const holdBins = HOLD_EDGES.map(([a, b]) => ({
    label: b === Infinity ? `${a}+` : `${a}-${b}`,
    count: holds.filter((v) => v >= a && v < b).length,
  }));

  const hourBins = Array.from({ length: 24 }, (_, h) => ({
    label: h % 3 === 0 ? `${h}h` : '',
    count: trades.filter((t) => t.hour === h).length,
  }));

  const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const dowRows = DOW.map((label, i) => {
    const ts = trades.filter((t) => t.dow === i && t.pnl != null);
    return { label, v: ts.length ? ts.reduce((s, t) => s + t.pnl, 0) / ts.length : 0, n: ts.length };
  });

  const wrHourBins = Array.from({ length: 24 }, (_, h) => {
    const tr = trades.filter((t) => t.hour === h && t.pnl != null);
    const w = tr.filter((t) => t.pnl > 0).length;
    return {
      label: h % 3 === 0 ? `${h}h` : '',
      count: tr.length ? Math.round((w / tr.length) * 100) : 0,
      pos: tr.length > 0 && w / tr.length >= 0.5,
    };
  });

  const rBins = (data.r_histogram || []).map((b) => ({ label: b.label, count: b.count, pos: b.pos }));

  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={12} h={6} minW={6} minH={5}>
        <Pane title="PnL Distribution" style={{ height: '100%' }} tag={lbl || `$${step} bins`}
          foot={{ tone: 'sub', msg: `n=${trades.length} closed trades · $${step} bins` }}>
          <AnaHistChart bins={pnlBins} divergent noun="trade" />
        </Pane>
      </GridItem>
      <GridItem x={12} y={0} w={12} h={6} minW={6} minH={5}>
        <Pane title="R-Multiple Distribution" style={{ height: '100%' }} tag="1R bins"
          right={<span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>n={(data.r_values || []).length} · positional R from plan SL</span>}>
          {rBins.length ? <AnaHistChart bins={rBins} divergent noun="trade" /> : <EmptyState msg="no R-multiples in window" />}
        </Pane>
      </GridItem>
      <GridItem x={0} y={6} w={12} h={6} minW={6} minH={5}>
        <Pane title="Hold Time Distribution" style={{ height: '100%' }} tag="min">
          {holds.length ? <AnaHistChart bins={holdBins} color="var(--qe-blue)" noun="trade" /> : <EmptyState msg="no hold-time data (open_time unknown)" />}
        </Pane>
      </GridItem>
      <GridItem x={12} y={6} w={12} h={6} minW={6} minH={5}>
        <Pane title="Trades by Hour of Day" style={{ height: '100%' }} tag="account tz">
          <AnaHistChart bins={hourBins} color="var(--qe-cyan)" noun="trade" />
        </Pane>
      </GridItem>
      <GridItem x={0} y={12} w={12} h={6} minW={6} minH={5}>
        <Pane title="Avg PnL by Day of Week" style={{ height: '100%' }} tag="$">
          <AnaDivergingBars rows={dowRows} />
        </Pane>
      </GridItem>
      <GridItem x={12} y={12} w={12} h={6} minW={6} minH={5}>
        <Pane title="Win Rate by Hour of Day" style={{ height: '100%' }} tag="%">
          <AnaHistChart bins={wrHourBins} divergent unit="%"
            tip={(l, v) => `${l || 'hour'} · ${v}% win rate`} />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Calendar PnL ───────────────────────────────────────────────────────── */
const AnaTabCalendar = () => {
  // '' = server default (current month in ACCOUNT tz); the Next clamp uses
  // the door's month/current_month so a client↔account tz month-boundary
  // mismatch can't dead-end or overrun the nav (audit L7).
  const [ym, setYm] = React.useState('');
  const { data, err } = useAnaJson(`/fragments/analytics/calendar?format=json&month=${encodeURIComponent(ym)}`);
  if (!data) return <AnaEmpty err={err} msg="loading calendar…" />;
  const weeks = data.calendar_grid || [];
  const maxAbs = data.max_abs_pnl || 1;
  const atCurrent = data.month >= data.current_month;
  return (
    <div style={{ padding: 4, height: '100%' }}>
      <Pane title="Calendar PnL"
        right={
          <>
            <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => setYm(data.prev_month)}>‹ Prev</button>
            <span className="qe-mono" style={{ fontSize: '0.74rem', fontWeight: 700, padding: '0 6px' }}>{data.month_label}</span>
            <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={atCurrent} style={atCurrent ? { opacity: 0.4 } : undefined}
              title={atCurrent ? 'Already at the current month' : ''} onClick={() => setYm(data.next_month)}>Next ›</button>
          </>
        }
        style={{ height: '100%' }}
        foot={{ tone: (data.avg_daily || 0) >= 0 ? 'ok' : 'warn',
          msg: `${data.trading_days || 0} trading days · best $${(data.best_day || 0).toFixed(2)} · worst $${(data.worst_day || 0).toFixed(2)}` }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, height: '100%' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 2 }}>
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => (
              <div key={d} style={{ textAlign: 'center', fontSize: '0.54rem', color: 'var(--qe-muted)', textTransform: 'uppercase', padding: '2px 0', letterSpacing: '0.1em' }}>{d}</div>
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 2, flex: 1, minHeight: 0, alignContent: 'start' }}>
            {weeks.flat().map((cell, i) => {
              if (!cell || !cell.day) return <div key={i} />;
              if (cell.pnl == null) {
                return (
                  <div key={i} title={`${cell.date}: no trades`} style={{
                    background: 'var(--qe-panel)', border: '1px solid color-mix(in srgb, var(--qe-text) 4%, transparent)',
                    padding: '4px 6px', minHeight: 46, opacity: 0.45,
                  }}>
                    <span style={{ fontSize: '0.6rem', fontFamily: 'var(--qe-mono)', color: 'var(--qe-muted)' }}>{cell.day}</span>
                  </div>
                );
              }
              const intensity = Math.min(Math.abs(cell.pnl) / maxAbs, 1);
              /* rgba magnitude-heat — the HeatStrip carve-out (DESIGN.md §2) */
              const bg = cell.pnl > 0 ? `rgba(0,255,127,${0.12 + intensity * 0.6})`
                : cell.pnl < 0 ? `rgba(255,45,74,${0.12 + intensity * 0.6})` : 'var(--qe-panel)';
              const tc = cell.pnl >= 0 ? 'var(--qe-green)' : 'var(--qe-red)';
              return (
                <div key={i} title={`${cell.date}: $${cell.pnl.toFixed(2)} · ${cell.trades || 0}T · ${((cell.win_rate || 0) * 100).toFixed(0)}% WR`}
                  style={{ background: bg, border: '1px solid color-mix(in srgb, var(--qe-text) 4%, transparent)', padding: '4px 6px', display: 'flex', flexDirection: 'column', minHeight: 46 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.6rem', fontFamily: 'var(--qe-mono)' }}>
                    <span style={{ color: tc, fontWeight: 600 }}>{cell.day}</span>
                    {cell.trades > 0 && <span style={{ color: tc, opacity: 0.7 }}>{((cell.win_rate || 0) * 100).toFixed(0)}%</span>}
                  </div>
                  <div style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.7rem', fontWeight: 700, color: tc, marginTop: 3 }}>
                    {cell.pnl >= 0 ? '+' : '-'}${Math.abs(cell.pnl).toFixed(2)}
                  </div>
                  <div className="qe-grow" />
                  {cell.trades > 0 && (
                    <div style={{ fontSize: '0.52rem', color: tc, opacity: 0.75, fontFamily: 'var(--qe-mono)' }}>{cell.trades}T</div>
                  )}
                </div>
              );
            })}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, padding: '6px 4px', borderTop: '1px solid var(--qe-line)' }}>
            <AnaKv label="Trading Days" value={data.trading_days || 0} />
            <AnaKv label="Avg Daily PnL" value={`$${(data.avg_daily || 0).toFixed(2)}`} color={_anaPnl(data.avg_daily || 0)} />
            <AnaKv label="Best Day" value={`$${(data.best_day || 0).toFixed(2)}`} color="var(--qe-green)" />
            <AnaKv label="Worst Day" value={`$${(data.worst_day || 0).toFixed(2)}`} color="var(--qe-red)" />
          </div>
        </div>
      </Pane>
    </div>
  );
};

/* ── Traded Pairs ───────────────────────────────────────────────────────── */
const AnaTabPairs = ({ period, offset, onLabel }) => {
  const { data, err } = useAnaJson(`/fragments/analytics/pairs?format=json&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return <AnaEmpty err={err} msg="loading pairs…" />;
  const rows = data.rows || [];
  if (!rows.length) return <AnaEmpty err={err} msg="no trades in window" />;
  const totals = {
    trades: rows.reduce((s, r) => s + (r.total || 0), 0),
    pnl: rows.reduce((s, r) => s + (r.pnl_total || 0), 0),
    fees: rows.reduce((s, r) => s + (r.fees_total || 0), 0),
    vol: rows.reduce((s, r) => s + (r.volume || 0), 0),
  };
  const pnlCell = (v, bold) => (
    <span style={{ color: v >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: bold ? 700 : undefined }}>
      {v === 0 ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2)}
    </span>
  );
  return (
    <div style={{ padding: 4, height: '100%' }}>
      <Pane title="Traded Pairs" count={`${rows.length} symbols`} tag={data.period_label} style={{ height: '100%' }} bodyStyle={{ padding: 0 }}
        foot={{ tone: totals.pnl >= 0 ? 'ok' : 'warn', msg: `${totals.trades} trades · Σ ${totals.pnl >= 0 ? '+' : ''}${totals.pnl.toFixed(2)} · fees ${totals.fees.toFixed(2)}` }}>
        <DataList
          selKey="symbol" dense={false} tools={false}
          columns={[
            { key: 'symbol', label: 'SYMBOL', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.symbol}</span> },
            { key: 'total', label: 'TRADES', align: 'right' },
            { key: 'longs', label: 'LONGS', align: 'right', cell: 'up' },
            { key: 'shorts', label: 'SHORTS', align: 'right', cell: 'dn' },
            { key: 'pnl_long', label: 'PnL (L)', align: 'right', render: (r) => pnlCell(r.pnl_long || 0) },
            { key: 'pnl_short', label: 'PnL (S)', align: 'right', render: (r) => pnlCell(r.pnl_short || 0) },
            { key: 'pnl_total', label: 'PnL TOTAL', align: 'right', render: (r) => pnlCell(r.pnl_total || 0, true) },
            { key: 'win_rate', label: 'WIN RATE', align: 'right', render: (r) => <span style={{ color: (r.win_rate || 0) >= 0.5 ? 'var(--qe-green)' : 'var(--qe-red)' }}>{((r.win_rate || 0) * 100).toFixed(1)}%</span> },
            { key: 'avg_win', label: 'AVG WIN', align: 'right', render: (r) => <span style={{ color: 'var(--qe-green)' }}>{r.avg_win ? r.avg_win.toFixed(2) : '—'}</span> },
            { key: 'avg_loss', label: 'AVG LOSS', align: 'right', cell: 'dn', render: (r) => (r.avg_loss ? r.avg_loss.toFixed(2) : '—') },
            { key: 'fees_total', label: 'FEES', align: 'right', cell: 'dim', render: (r) => (r.fees_total || 0).toFixed(2) },
            { key: 'volume', label: 'VOLUME', align: 'right', cell: 'dim', render: (r) => (r.volume || 0).toLocaleString(undefined, { maximumFractionDigits: 0 }) },
          ]}
          rows={rows}
          summary={<>
            <span><span style={{ color: 'var(--qe-muted)' }}>TOTAL</span> <span style={{ color: 'var(--qe-text)', fontWeight: 700 }}>{totals.trades} trades</span></span>
            <span style={{ color: totals.pnl >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700 }}>Σ PnL {totals.pnl >= 0 ? '+' : ''}{totals.pnl.toFixed(2)} · fees {totals.fees.toFixed(2)} · vol {totals.vol.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
          </>}
        />
      </Pane>
    </div>
  );
};

/* ── MFE / MAE ──────────────────────────────────────────────────────────── */
const AnaTabExcursions = ({ period, offset, onLabel }) => {
  const [dir, setDir] = React.useState('all');
  const { data, err } = useAnaJson(`/fragments/analytics/excursions?format=json&dir=${encodeURIComponent(dir)}&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return <AnaEmpty err={err} msg="loading excursions…" />;
  const trades = data.trades || [];
  const points = (data.scatter_data || []).map((p) => ({ x: p.x, y: p.y, profit: (p.z || 0) >= 0, label: p.sym }));
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={16} h={16} minW={8} minH={6}>
        <Pane title="MFE / MAE Scatter" tag={data.period_label}
          right={<PeriodSelector options={[['all', 'All'], ['LONG', 'Long'], ['SHORT', 'Short']]} value={dir} onChange={setDir} />}
          style={{ height: '100%' }} bodyStyle={{ padding: 6 }}
          foot={{ tone: 'info', msg: `${points.length} reconciled trades · server-side ${dir === 'all' ? 'no' : dir} filter` }}>
          {points.length ? <ScatterChart points={points} xName="MFE ($)" yName="MAE ($)" /> : <EmptyState msg="no reconciled excursions in window" />}
        </Pane>
      </GridItem>
      <GridItem x={16} y={0} w={8} h={5} minW={5} minH={4}>
        <Pane title="Excursion Summary" style={{ height: '100%' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 14px' }}>
            <AnaKv label="Avg MFE" value={`$${(data.avg_mfe || 0).toFixed(2)}`} color="var(--qe-green)" />
            <AnaKv label="Avg |MAE|" value={`$${(data.avg_mae_abs || 0).toFixed(2)}`} color="var(--qe-red)" />
            <AnaKv label="Avg ME-Ratio" value={(data.avg_mer || 0).toFixed(2)} />
            <AnaKv label="MFE > 2× MAE" value={`${data.pct_favorable || 0}%`} color="var(--qe-green)" />
          </div>
        </Pane>
      </GridItem>
      <GridItem x={16} y={5} w={8} h={11} minW={5} minH={5}>
        <Pane title="Per-Trade Excursions"
          count={points.length > trades.length ? `${trades.length} of ${points.length}` : trades.length}
          style={{ height: '100%' }} bodyStyle={{ padding: 0 }}>
          <DataList
            selKey="trade_key" tools={false}
            columns={[
              { key: 'symbol', label: 'SYMBOL', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.symbol}</span> },
              { key: 'direction', label: 'DIR', render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{r.direction}</Badge> },
              { key: 'mfe', label: 'MFE', align: 'right', cell: 'up', render: (r) => (r.mfe || 0).toFixed(2) },
              { key: 'mae', label: 'MAE', align: 'right', cell: 'dn', render: (r) => (r.mae || 0).toFixed(2) },
              { key: 'mer', label: 'ME-R', align: 'right', render: (r) => (r.mae ? Math.abs((r.mfe || 0) / r.mae).toFixed(2) : '—') },
              { key: 'income', label: 'PnL', align: 'right', render: (r) => <span style={{ color: (r.income || 0) >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700 }}>{(r.income || 0) >= 0 ? '+' : ''}{(r.income || 0).toFixed(2)}</span> },
              { key: 'hold_ms', label: 'HOLD', align: 'right', cell: 'dim', render: (r) => _hDur(r.hold_ms) },
            ]}
            rows={trades}
            emptyMsg="no excursions in window"
          />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── R-Multiples ────────────────────────────────────────────────────────── */
const AnaTabRMultiples = ({ period, offset, onLabel }) => {
  const { data, err } = useAnaJson(`/fragments/analytics/r_multiples?format=json&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return <AnaEmpty err={err} msg="loading r-multiples…" />;
  const st = data.r_stats || {};
  const bins = (data.histogram || []).map((b) => ({ label: b.label, count: b.count, pos: b.pos }));
  if (!st.count) return <AnaEmpty err={err} msg="no R-multiples in window (needs plan-linked closes)" />;
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={16} h={12} minW={8} minH={6}>
        <Pane title="R-Multiple Distribution" tag={data.period_label} style={{ height: '100%' }}
          foot={{ tone: (st.expectancy || 0) >= 0 ? 'ok' : 'warn', msg: `${st.count} trades · expectancy ${(st.expectancy || 0).toFixed(3)}R` }}>
          <AnaHistChart bins={bins} divergent noun="trade" />
        </Pane>
      </GridItem>
      <GridItem x={16} y={0} w={8} h={12} minW={5} minH={6}>
        <Pane title="R-Multiple Stats" style={{ height: '100%' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <AnaKv label="Total Trades" value={st.count} />
            <AnaKv label="Win Rate" value={`${((st.win_rate || 0) * 100).toFixed(1)}%`} color={(st.win_rate || 0) >= 0.5 ? 'var(--qe-green)' : 'var(--qe-red)'} />
            <AnaKv label="Expectancy" value={`${(st.expectancy || 0).toFixed(3)}R`} color={_anaPnl(st.expectancy || 0)} />
            <AnaKv label="Profit Factor" value={_anaRatio(st.profit_factor)} color={(st.profit_factor || 0) >= 1.5 ? 'var(--qe-green)' : (st.profit_factor || 0) >= 1 ? 'var(--qe-amber)' : 'var(--qe-red)'} />
            <AnaKv label="Avg Win R" value={`${(st.avg_win_r || 0).toFixed(2)}R`} color="var(--qe-green)" />
            <AnaKv label="Avg Loss R" value={`${(st.avg_loss_r || 0).toFixed(2)}R`} color="var(--qe-red)" />
            <AnaKv label="Best R" value={`${(st.best || 0).toFixed(2)}R`} color="var(--qe-green)" />
            <AnaKv label="Worst R" value={`${(st.worst || 0).toFixed(2)}R`} color="var(--qe-red)" />
            <AnaKv label="Median R" value={`${(st.median || 0).toFixed(2)}R`} />
            <AnaKv label="Mean R" value={`${(st.mean || 0).toFixed(3)}R`} />
          </div>
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Risk Metrics (VaR) ─────────────────────────────────────────────────── */
const AnaVarCard = ({ label, val, equity, desc }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 10, background: 'var(--qe-panel)', border: '1px solid var(--qe-line)' }} title={desc}>
    <Lbl>{label}</Lbl>
    <span className="qe-mono" style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--qe-red)' }}>{Math.abs(val * 100).toFixed(2)}%</span>
    <span style={{ fontSize: '0.62rem', color: 'var(--qe-sub)', fontFamily: 'var(--qe-mono)' }}>${Math.abs(val * (equity || 0)).toFixed(0)}</span>
  </div>
);

const AnaTabRisk = ({ period, offset, onLabel }) => {
  const { data, err } = useAnaJson(`/fragments/analytics/var?format=json&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return <AnaEmpty err={err} msg="loading risk metrics…" />;
  if (!data.has_data) {
    return (
      <div style={{ padding: 4, height: '100%' }}>
        <EmptyState tone="info" glyph="σ"
          msg={`VaR needs ≥20 daily returns in the window — have ${(data.returns || []).length}`}
          hint="widen the period (90D / All) or come back after more trading days" />
      </div>
    );
  }
  // historical_var returns a NEGATIVE loss threshold — no sign flip
  // (audit H1: negating it painted every mid-range day red).
  const varThreshPct = (data.var95 || 0) * 100;
  const histBins = (data.hist_data || []).map((b) => ({
    label: `${b.x.toFixed(1)}%`, count: b.y, pos: b.x > varThreshPct,
  }));
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={24} h={5} minW={10} minH={5}>
        <Pane title="Value at Risk · Risk Metrics" tag={data.period_label} style={{ height: '100%' }}
          foot={{ tone: 'sub', msg: `95% VaR ${Math.abs((data.var95 || 0) * 100).toFixed(2)}% · n=${(data.returns || []).length} daily returns` }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8 }}>
            <AnaVarCard label="Historical VaR (95%)" val={data.var95 || 0} equity={data.cur_equity} desc="Worst daily loss exceeded 5% of the time" />
            <AnaVarCard label="Historical VaR (99%)" val={data.var99 || 0} equity={data.cur_equity} desc="Worst daily loss exceeded 1% of the time" />
            <AnaVarCard label="CVaR / ES (95%)" val={data.cvar95 || 0} equity={data.cur_equity} desc="Expected Shortfall — average loss on worst 5% of days" />
            <AnaVarCard label="Parametric VaR (95%)" val={data.pvar95 || 0} equity={data.cur_equity} desc="Gaussian VaR (μ − 1.645σ)" />
          </div>
        </Pane>
      </GridItem>
      <GridItem x={0} y={5} w={24} h={12} minW={10} minH={6}>
        <Pane title="Daily Return Distribution" style={{ height: '100%' }}
          right={<span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>red = below the 95% VaR threshold · n={(data.returns || []).length} days</span>}>
          <AnaHistChart bins={histBins} divergent unit="%" noun="day" />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Execution Quality (G-O4) ───────────────────────────────────────────── */
const ANA_LINK_META = {
  auto:      { label: 'Auto-linked', color: 'var(--qe-green)', bg: 'rgba(0,255,127,0.06)' },
  confirmed: { label: 'Confirmed',   color: 'var(--qe-cyan)',  bg: 'rgba(0,231,255,0.05)' },
  partial:   { label: 'Partial',     color: 'var(--qe-amber)', bg: 'rgba(255,174,0,0.06)' },
  unlinked:  { label: 'Unlinked',    color: 'var(--qe-red)',   bg: 'rgba(255,45,74,0.06)' },
  na:        { label: 'n/a (close/manual)', color: 'var(--qe-muted)', bg: 'transparent' },
};
const _anaLinkKey = (r) => {
  if (r.link_status === 'linked') return r.link_confirmed ? 'confirmed' : 'auto';
  if (r.link_status === 'partial') return 'partial';
  if (r.link_status === 'unlinked') return 'unlinked';
  return 'na';
};

const AnaTabExecution = () => {
  const [ftFilter, setFtFilter] = React.useState('all');
  const { data, err } = useAnaJson('/api/analytics/execution?limit=500');
  if (!data) return <AnaEmpty err={err} msg="loading execution quality…" />;
  const rows = data.rows || [];
  const sum = data.summary || {};
  if (!rows.length) return <AnaEmpty err={err} msg="no fills recorded yet" />;

  const entryN = (sum.by_fill_type && sum.by_fill_type.entry) || 0;
  // coverage numerator = LINKED ENTRIES only (audit L5: a linked
  // reduce_only fill must not push coverage past 100%)
  const linkedEntries = rows.filter((r) => r.fill_type === 'entry' && r.link_status === 'linked').length;
  const linkCov = entryN > 0 ? (linkedEntries / entryN) * 100 : null;
  const calcPct = sum.total ? (sum.calc_backed / sum.total) * 100 : 0;
  const bias = sum.bias_bp;

  const linkBreak = ['auto', 'confirmed', 'partial', 'unlinked', 'na'].map((k) => ({
    key: k, ...ANA_LINK_META[k], n: rows.filter((r) => _anaLinkKey(r) === k).length,
  }));

  const ftStats = ['entry', 'tp', 'sl', 'manual', 'reduce_only'].map((ft) => {
    const es = rows.filter((r) => r.fill_type === ft && r.slippage_cost != null);
    return { ft, n: es.length, avgBp: es.length ? es.reduce((s, r) => s + Math.abs(r.slippage_cost), 0) / es.length * 10000 : 0 };
  });
  const maxFtBp = Math.max(...ftStats.map((f) => f.avgBp), 0.1);

  const scatterPts = rows
    .filter((r) => r.est_slippage != null && r.slippage_cost != null)
    .map((r) => ({ est: r.est_slippage * 10000, act: r.slippage_cost * 10000, ft: r.fill_type || 'entry', id: r.exchange_fill_id || String(r.fill_id) }));

  const ttfs = rows.map((r) => r.time_to_fill_ms).filter((v) => v != null);
  const TTF_EDGES = [[0, 1e3, '<1s'], [1e3, 1e4, '1-10s'], [1e4, 6e4, '10-60s'], [6e4, 6e5, '1-10m'], [6e5, 36e5, '10-60m'], [36e5, Infinity, '1h+']];
  const ttfBins = TTF_EDGES.map(([a, b, label]) => ({ label, count: ttfs.filter((v) => v >= a && v < b).length }));

  const entryCosts = rows.filter((r) => r.fill_type === 'entry' && r.slippage_cost != null).map((r) => r.slippage_cost * 10000);
  // clamped at 100bp + overflow bin (audit L4: one corrupt outlier must not
  // explode the bin count / render pass)
  const SLIP_STEP = 5;
  const slipMax = Math.min(100, Math.max(SLIP_STEP, Math.ceil(Math.max(...entryCosts, 0) / SLIP_STEP) * SLIP_STEP));
  const slipBins = [{ label: '<0', count: entryCosts.filter((v) => v < 0).length }]
    .concat(Array.from({ length: slipMax / SLIP_STEP }, (_, i) => {
      const a = i * SLIP_STEP;
      return { label: `${a}-${a + SLIP_STEP}`, count: entryCosts.filter((v) => v >= a && v < a + SLIP_STEP).length };
    }))
    .concat(entryCosts.some((v) => v >= slipMax) ? [{ label: `${slipMax}+`, count: entryCosts.filter((v) => v >= slipMax).length }] : []);

  const otKeys = Object.keys(sum.by_order_type || {}).sort((a, b) => (sum.by_order_type[b] || 0) - (sum.by_order_type[a] || 0));
  const otColor = (ot) => {
    const u = ot.toUpperCase();
    return u === 'LIMIT' ? 'var(--qe-green)' : u === 'MARKET' ? 'var(--qe-blue)' : u.includes('STOP') ? 'var(--qe-red)' : 'var(--qe-sub)';
  };

  const tableRows = (ftFilter === 'all' ? rows : rows.filter((r) => r.fill_type === ftFilter));

  const kpis = [
    { l: 'Exec Link Coverage', v: linkCov == null ? '—' : `${linkCov.toFixed(1)}%`, sub: `${linkedEntries}/${entryN} entry fills auto+confirmed`,
      tone: linkCov == null ? 'var(--qe-sub)' : linkCov > 80 ? 'var(--qe-green)' : 'var(--qe-amber)' },
    { l: 'Calc-Backed Fills', v: `${calcPct.toFixed(0)}%`, sub: `${sum.calc_backed}/${sum.total} carry calc_id`, tone: 'var(--qe-blue)' },
    { l: 'Entry Residual (vs plan)', v: sum.avg_cost_bp == null ? '—' : `${sum.avg_cost_bp >= 0 ? '+' : ''}${sum.avg_cost_bp.toFixed(2)}bp`,
      sub: sum.avg_est_bp == null ? 'no calc-backed entries' : `predicted impact ${sum.avg_est_bp.toFixed(2)}bp · n=${sum.entry_n}`, tone: 'var(--qe-text)' },
    { l: 'Slip Bias', v: bias == null ? '—' : `${bias >= 0 ? '+' : ''}${bias.toFixed(2)}bp`,
      sub: bias == null ? 'needs calc-backed entries' : bias > 0 ? 'fills run worse than plan' : 'fills run better than plan',
      tone: bias == null ? 'var(--qe-sub)' : Math.abs(bias) < 0.5 ? 'var(--qe-green)' : 'var(--qe-amber)' },
    { l: 'Time to Fill (p95)', v: _anaMs(sum.ttf_p95_ms), sub: `avg ${_anaMs(sum.ttf_avg_ms)} · max ${_anaMs(sum.ttf_max_ms)} · n=${sum.ttf_n}`, tone: 'var(--qe-cyan)' },
  ];

  return (
    <GridWorkspace>
      {kpis.map(({ l, v, sub, tone }, i) => (
        <GridItem key={l} x={i < 4 ? i * 4 : 16} y={0} w={i === 4 ? 8 : 4} h={3} minW={3} minH={3}>
          <Pane title={l} style={{ height: '100%' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div className="qe-mono" style={{ fontSize: '1.1rem', fontWeight: 700, color: tone, lineHeight: 1.1 }}>{v}</div>
              <div style={{ fontSize: '0.58rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)', lineHeight: 1.4 }}>{sub}</div>
            </div>
          </Pane>
        </GridItem>
      ))}

      <GridItem x={0} y={3} w={12} h={6} minW={6} minH={6}>
        <Pane title="Exec Link Status" style={{ height: '100%' }}>
          <div style={{ display: 'flex', height: 12, marginBottom: 8, gap: 1, background: 'var(--qe-panel)' }}>
            {linkBreak.filter((b) => b.n > 0).map((b) => (
              <div key={b.key} title={`${b.label}: ${b.n}`} style={{ flex: b.n, background: b.color, opacity: 0.85 }} />
            ))}
          </div>
          {linkBreak.map((b) => (
            <div key={b.key} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '3px 6px', background: b.bg, marginBottom: 2, borderLeft: `2px solid ${b.color}`,
            }}>
              <span className="qe-mono" style={{ fontSize: '0.62rem', fontWeight: 700, color: b.color }}>{b.label}</span>
              <div style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
                <span className="qe-mono" style={{ fontSize: '0.66rem', color: b.color, fontWeight: 700 }}>{b.n}</span>
                <span className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-muted)' }}>{rows.length ? ((b.n / rows.length) * 100).toFixed(0) : 0}%</span>
              </div>
            </div>
          ))}
          <div style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', lineHeight: 1.5, marginTop: 6, borderTop: '1px solid var(--qe-faint)', paddingTop: 4 }}>
            Link status needs <span className="qe-mono" style={{ color: 'var(--qe-cyan)' }}>calc_id</span> on the fill
            (entry fills only — close/manual fills report n/a).
          </div>
        </Pane>
      </GridItem>

      <GridItem x={12} y={3} w={12} h={6} minW={6} minH={6}>
        <Pane title="Avg |Slippage| by Fill Type" tag="bp" style={{ height: '100%' }}>
          {ftStats.map(({ ft, n, avgBp }) => (
            <div key={ft} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span className="qe-mono" style={{ fontSize: '0.62rem', fontWeight: 700, color: ANA_FT_COLOR[ft], width: 76, flexShrink: 0 }}>{ft}</span>
              <div style={{ flex: 1, height: 10, background: 'var(--qe-panel)', border: '1px solid var(--qe-faint)' }}>
                <div style={{ width: n > 0 ? `${((avgBp / maxFtBp) * 100).toFixed(1)}%` : '0%', height: '100%', background: ANA_FT_COLOR[ft], opacity: 0.8 }} />
              </div>
              <span className="qe-mono" style={{ fontSize: '0.62rem', fontWeight: 700, color: ANA_FT_COLOR[ft], width: 52, textAlign: 'right', flexShrink: 0 }}>
                {n > 0 ? avgBp.toFixed(1) + 'bp' : '—'}
              </span>
              <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', width: 26, textAlign: 'right', flexShrink: 0 }}>×{n}</span>
            </div>
          ))}
          <div className="qe-divider-h" style={{ margin: '6px 0' }} />
          <div style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', lineHeight: 1.5 }}>
            sl slippage is measured against the stop trigger; entry against the plan's effective entry.
          </div>
        </Pane>
      </GridItem>

      <GridItem x={0} y={9} w={24} h={8} minW={10} minH={7}>
        <Pane title="Entry Slippage: Predicted Impact vs Residual" tag="calc-backed entries" style={{ height: '100%' }}
          right={
            <span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)' }}>
              y=0 = fill exactly at the plan's predicted price · red ring = worse than plan
            </span>
          }
          bodyStyle={{ padding: '8px 10px' }}>
          {scatterPts.length ? <AnaExecScatter points={scatterPts} /> : <EmptyState msg="no calc-backed entries with both estimate and residual yet" />}
        </Pane>
      </GridItem>

      <GridItem x={0} y={17} w={12} h={6} minW={6} minH={5}>
        <Pane title="Time-to-Fill Distribution" tag="order→fill" style={{ height: '100%' }} bodyStyle={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            {ttfs.length ? <AnaHistChart bins={ttfBins} color="var(--qe-cyan)" noun="fill" /> : <EmptyState msg="no order-linked fills yet" />}
          </div>
          <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: '0.58rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>
            <span>avg {_anaMs(sum.ttf_avg_ms)}</span>
            <span>p95 {_anaMs(sum.ttf_p95_ms)}</span>
            <span>max {_anaMs(sum.ttf_max_ms)}</span>
            <span style={{ marginLeft: 'auto' }}>engine-observed (order persisted → fill) · resting limits skew high</span>
          </div>
        </Pane>
      </GridItem>

      <GridItem x={12} y={17} w={12} h={6} minW={6} minH={5}>
        <Pane title="Entry Residual Distribution" tag="bp vs plan" style={{ height: '100%' }} bodyStyle={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            {entryCosts.length ? <AnaHistChart bins={slipBins} color="var(--qe-blue)" noun="fill" /> : <EmptyState msg="no calc-backed entry fills yet" />}
          </div>
          <div style={{ fontSize: '0.58rem', color: 'var(--qe-muted)', marginTop: 6, fontFamily: 'var(--qe-mono)' }}>
            {'<0 = filled better than plan · '}n={entryCosts.length}
          </div>
        </Pane>
      </GridItem>

      <GridItem x={0} y={23} w={12} h={5} minW={6} minH={5}>
        <Pane title="Order Type Mix" style={{ height: '100%' }}>
          {otKeys.length ? otKeys.map((ot) => {
            const n = sum.by_order_type[ot] || 0;
            const c = otColor(ot);
            return (
              <div key={ot} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span className="qe-mono" style={{ fontSize: '0.62rem', color: c, width: 110, flexShrink: 0 }}>{ot.toUpperCase()}</span>
                <div style={{ flex: 1, height: 8, background: 'var(--qe-panel)', border: '1px solid var(--qe-faint)' }}>
                  <div style={{ width: `${((n / (sum.total || 1)) * 100).toFixed(1)}%`, height: '100%', background: c, opacity: 0.8 }} />
                </div>
                <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-text)', width: 24, textAlign: 'right', flexShrink: 0 }}>{n}</span>
                <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', width: 34, textAlign: 'right', flexShrink: 0 }}>{((n / (sum.total || 1)) * 100).toFixed(0)}%</span>
              </div>
            );
          }) : <EmptyState msg="no order metadata" />}
          <div style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', marginTop: 4 }}>
            "unknown" = fill without a tracked parent order.
          </div>
        </Pane>
      </GridItem>

      <GridItem x={12} y={23} w={12} h={5} minW={6} minH={5}>
        <Pane title="Maker / Taker Split" style={{ height: '100%' }}>
          {[['maker', sum.maker || 0, 'var(--qe-green)'], ['taker', sum.taker || 0, 'var(--qe-amber)']].map(([role, n, c]) => (
            <div key={role} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span className="qe-mono" style={{ fontSize: '0.62rem', color: c, width: 60, flexShrink: 0 }}>{role.toUpperCase()}</span>
              <div style={{ flex: 1, height: 8, background: 'var(--qe-panel)', border: '1px solid var(--qe-faint)' }}>
                <div style={{ width: `${((n / (sum.total || 1)) * 100).toFixed(1)}%`, height: '100%', background: c, opacity: 0.8 }} />
              </div>
              <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-text)', width: 24, textAlign: 'right', flexShrink: 0 }}>{n}</span>
              <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', width: 34, textAlign: 'right', flexShrink: 0 }}>{((n / (sum.total || 1)) * 100).toFixed(0)}%</span>
            </div>
          ))}
          <div style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', marginTop: 4 }}>
            role stamped per fill by the exchange stream; maker rebates lower fee drag.
          </div>
        </Pane>
      </GridItem>

      <GridItem x={0} y={28} w={24} h={14} minW={10} minH={8}>
        <Pane title="Per-Fill Log" count={tableRows.length} tag={`newest ${data.limit}`}
          style={{ height: '100%' }}
          foot={{ tone: 'sub', msg: `aggregates cover this window (newest ${data.limit}), not all-time` }}
          right={
            <div style={{ display: 'flex', gap: 3 }}>
              {['all', 'entry', 'tp', 'sl', 'manual'].map((f) => (
                <button key={f} onClick={() => setFtFilter(f)}
                  className={`qe-btn qe-btn-sm ${ftFilter === f ? 'qe-btn-primary' : ''}`}
                  style={{ color: ftFilter === f ? 'var(--qe-bg)' : (ANA_FT_COLOR[f] || 'var(--qe-sub)'), textTransform: 'uppercase', letterSpacing: '0.04em' }}>{f}</button>
              ))}
            </div>
          }
          bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
          <DataList
            selKey="fill_id" tools={false}
            columns={[
              { key: 'time_ms', label: 'TIME', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{_hFmtTs(r.time_ms)}</span> },
              { key: 'symbol', label: 'SYM', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.symbol}</span> },
              { key: 'fill_type', label: 'FILL', render: (r) => <span style={{ color: ANA_FT_COLOR[r.fill_type] || 'var(--qe-muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', fontSize: '0.58rem' }}>{r.fill_type || '—'}</span> },
              { key: 'order_type', label: 'TYPE', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{(r.order_type || '—').toUpperCase()}</span> },
              { key: 'est_slippage', label: 'EST IMPACT', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{r.est_slippage != null ? (r.est_slippage * 10000).toFixed(1) + 'bp' : '—'}</span> },
              { key: 'slippage_cost', label: 'RESIDUAL', align: 'right', render: (r) => {
                // residual vs plan (entries) / vs trigger (tp+sl) — the
                // design's separate BIAS column collapsed into this (H-1)
                if (r.slippage_cost == null) return <span style={{ color: 'var(--qe-muted)' }}>—</span>;
                const bp = r.slippage_cost * 10000;
                return <span style={{ color: bp > 5 ? 'var(--qe-amber)' : bp < 0 ? 'var(--qe-green)' : 'var(--qe-text)', fontWeight: 700 }}>{(bp >= 0 ? '+' : '') + bp.toFixed(1)}bp</span>;
              } },
              { key: 'time_to_fill_ms', label: 'TTF', align: 'right', render: (r) => <span style={{ color: 'var(--qe-text)' }}>{_anaMs(r.time_to_fill_ms)}</span> },
              { key: 'role', label: 'ROLE', render: (r) => (r.role ? <Badge tone={r.role === 'maker' ? 'ok' : 'warn'}>{r.role.toUpperCase()}</Badge> : <span style={{ color: 'var(--qe-muted)' }}>—</span>) },
              { key: 'link_status', label: 'LINK', render: (r) => { const m = ANA_LINK_META[_anaLinkKey(r)]; return <span style={{ color: m.color, fontWeight: 700, fontSize: '0.58rem' }}>{m.label}</span>; } },
              { key: 'calc_id', label: 'CALC ID', render: (r) => <span style={{ color: r.calc_id ? 'var(--qe-sub)' : 'var(--qe-muted)' }}>{r.calc_id ? String(r.calc_id).slice(-8) : '—'}</span> },
            ]}
            rows={tableRows}
            emptyMsg="No fills match this filter"
            summary={<>
              <span>{tableRows.length} fills · {sum.maker || 0} maker · {sum.taker || 0} taker</span>
              <span style={{ color: 'var(--qe-cyan)' }}>ttf avg {_anaMs(sum.ttf_avg_ms)} · p95 {_anaMs(sum.ttf_p95_ms)}</span>
            </>}
          />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Funding ────────────────────────────────────────────────────────────── */
const AnaTabFunding = () => {
  const { data, err } = useAnaJson('/fragments/analytics/funding?format=json', 30_000);
  if (!data) return <AnaEmpty err={err} msg="loading funding…" />;
  const raw = data.rows || [];
  if (!raw.length) return <AnaEmpty err={err} msg="no open positions — funding exposure is live-position-based" />;
  // composite key: HEDGE mode carries LONG+SHORT rows on one ticker (audit M1)
  const rows = raw.map((r) => ({ ...r, _k: `${r.ticker}·${r.direction}` }));
  const sgn = (r, v) => (r.adverse ? -v : v);           // sign derived from adverse
  const tot8h = rows.reduce((s, r) => s + sgn(r, r.per_8h || 0), 0);
  const totDay = rows.reduce((s, r) => s + sgn(r, r.per_day || 0), 0);
  const money = (v, d = 4) => <span style={{ color: v >= 0 ? 'var(--qe-green)' : 'var(--qe-red)' }}>{v >= 0 ? '+' : '-'}${Math.abs(v).toFixed(d)}</span>;
  return (
    <div style={{ padding: 4, height: '100%' }}>
      <Pane title="Funding Rate Exposure · Live"
        right={err
          ? <StatusDot tone="warn" label="STALE — retrying" />
          : <StatusDot tone="info" label="30s refresh" />}
        style={{ height: '100%' }} bodyStyle={{ padding: 0 }}
        foot={{ tone: tot8h >= 0 ? 'ok' : 'warn', msg: `${rows.length} positions · net per 8h ${tot8h >= 0 ? '+' : '-'}$${Math.abs(tot8h).toFixed(4)}` }}>
        <DataList
          selKey="_k" dense={false} tools={false}
          columns={[
            { key: 'ticker', label: 'SYMBOL', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.ticker}</span> },
            { key: 'direction', label: 'DIR', render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{r.direction}</Badge> },
            { key: 'notional', label: 'NOTIONAL', align: 'right', cell: 'dim', render: (r) => `$${(r.notional || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}` },
            { key: 'funding_rate', label: 'FUNDING RATE', align: 'right', render: (r) => <span style={{ color: r.adverse ? 'var(--qe-red)' : 'var(--qe-green)' }}>{((r.funding_rate || 0) * 100).toFixed(4)}%</span> },
            { key: 'per_8h', label: 'PER 8h', align: 'right', render: (r) => money(sgn(r, r.per_8h || 0)) },
            { key: 'per_day', label: 'PER DAY', align: 'right', render: (r) => money(sgn(r, r.per_day || 0), 3) },
            { key: 'per_week', label: 'PER WEEK', align: 'right', cell: 'dim', render: (r) => money(sgn(r, r.per_week || 0), 2) },
            { key: 'next_funding', label: 'NEXT FUNDING', cell: 'dim' },
            { key: 'impact', label: 'IMPACT', render: (r) => (r.adverse ? <Badge tone="err">PAY</Badge> : <Badge tone="ok">EARN</Badge>) },
          ]}
          rows={rows}
          summary={<>
            <span style={{ color: 'var(--qe-muted)' }}>Σ NET EXPOSURE</span>
            <span style={{ color: tot8h >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700 }}>
              per 8h {tot8h >= 0 ? '+' : '-'}${Math.abs(tot8h).toFixed(4)} · per day {totDay >= 0 ? '+' : '-'}${Math.abs(totDay).toFixed(3)}
            </span>
          </>}
        />
        <div style={{ padding: '4px 8px', borderTop: '1px solid var(--qe-line)', fontSize: '0.56rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>
          Binance settles funding every 8h (00:00 · 08:00 · 16:00 UTC). LONG pays when rate &gt; 0; SHORT pays when rate &lt; 0.
        </div>
      </Pane>
    </div>
  );
};

/* ── Beta Exposure ──────────────────────────────────────────────────────── */
const AnaTabBeta = () => {
  const { data, err } = useAnaJson('/fragments/analytics/beta?format=json', 60_000);
  if (!data) return <AnaEmpty err={err} msg="loading beta…" />;
  const raw = data.rows || [];
  if (!raw.length) return <AnaEmpty err={err} msg="no open positions — beta exposure is live-position-based" />;
  // composite key: HEDGE mode carries LONG+SHORT rows on one ticker (audit M1)
  const rows = raw.map((r) => ({ ...r, _k: `${r.ticker}·${r.direction}` }));
  const sectors = Object.entries(data.sector_totals || {});
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={14} h={13} minW={8} minH={6}>
        <Pane title="Beta-Weighted Exposure vs BTC" count={rows.length}
          right={<span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>β from 30d OHLCV · sector preset fallback · unsigned notional</span>}
          style={{ height: '100%' }} bodyStyle={{ padding: 0 }}
          foot={{ tone: 'info', msg: `portfolio β ${(data.port_beta || 0).toFixed(2)} · Σ β-adj $${(data.total_beta_exp || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} · 60s poll` }}>
          <DataList
            selKey="_k" dense={false} tools={false}
            columns={[
              { key: 'ticker', label: 'SYMBOL', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.ticker}</span> },
              { key: 'direction', label: 'DIR', render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{r.direction}</Badge> },
              { key: 'sector', label: 'SECTOR', cell: 'dim' },
              { key: 'notional', label: 'NOTIONAL', align: 'right', render: (r) => `$${(r.notional || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}` },
              { key: 'beta', label: 'β vs BTC', align: 'right', render: (r) => <span style={{ color: r.beta > 1.5 ? 'var(--qe-amber)' : r.beta <= 1 ? 'var(--qe-green)' : 'var(--qe-text)' }}>{(r.beta || 0).toFixed(2)}</span> },
              { key: 'beta_adj_exp', label: 'β-ADJ. EXP.', align: 'right', render: (r) => <span style={{ fontWeight: 700 }}>${(r.beta_adj_exp || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span> },
            ]}
            rows={rows}
            summary={<>
              <span><span style={{ color: 'var(--qe-muted)' }}>PORTFOLIO TOTAL</span> <span style={{ color: 'var(--qe-text)', fontWeight: 700 }}>${(data.total_notional || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span></span>
              <span style={{ fontWeight: 700 }}>β = <span style={{ color: Math.abs(data.port_beta || 0) > 1.5 ? 'var(--qe-amber)' : 'var(--qe-text)' }}>{(data.port_beta || 0).toFixed(2)}</span> · β-adj. ${(data.total_beta_exp || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            </>}
          />
        </Pane>
      </GridItem>
      <GridItem x={14} y={0} w={10} h={7} minW={6} minH={4}>
        <Pane title="Sector β-Adjusted Breakdown" style={{ height: '100%' }}>
          {sectors.length ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              {sectors.map(([sec, exp]) => {
                const pct = data.total_beta_exp ? Math.abs((exp / data.total_beta_exp) * 100) : 0;
                return (
                  <div key={sec} style={{ padding: 6, background: 'var(--qe-panel)', border: '1px solid var(--qe-line)' }}>
                    <Lbl>{sec}</Lbl>
                    <div className="qe-mono" style={{ fontSize: '0.86rem', fontWeight: 700, color: 'var(--qe-text)' }}>${(+exp).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
                    <div style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{pct.toFixed(1)}%</div>
                  </div>
                );
              })}
            </div>
          ) : <EmptyState msg="no sector data" />}
        </Pane>
      </GridItem>
      <GridItem x={14} y={7} w={10} h={6} minW={6} minH={4}>
        <Pane title="Sector Preset Betas · Fallback" style={{ height: '100%' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.62rem', fontFamily: 'var(--qe-mono)' }}>
            {[['big_two_crypto', '1.0'], ['top_twenty_alts', '1.5'], ['commodities', '0.4'], ['other_alts', '2.0']].map(([s, v]) => (
              <div key={s} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: '1px dotted var(--qe-faint)' }}>
                <span style={{ color: 'var(--qe-sub)' }}>{s}</span>
                <span style={{ color: 'var(--qe-text)', fontWeight: 700 }}>{v}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', marginTop: 6 }}>
            used when &lt;10 aligned daily returns exist for the empirical 30d β.
          </div>
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── page shell ─────────────────────────────────────────────────────────── */
const AnalyticsPage = () => {
  const [tab, setTab] = React.useState('overview');
  const [period, setPeriod] = React.useState('monthly');
  const [offset, setOffset] = React.useState(0);
  const [srvLabel, setSrvLabel] = React.useState('');
  const periodEnabled = ANA_PERIOD_TABS.has(tab);
  const onLabel = React.useCallback((l) => setSrvLabel(l), []);
  const setP = (p) => { setPeriod(p); setOffset(0); setSrvLabel(''); };
  const nav = (d) => { setOffset((o) => o + d); setSrvLabel(''); };

  const common = { period, offset, onLabel };
  const tabContent = {
    overview: <AnaTabOverview {...common} />,
    equity: <AnaTabEquity />,
    dist: <AnaTabDistributions {...common} />,
    calendar: <AnaTabCalendar />,
    pairs: <AnaTabPairs {...common} />,
    excursions: <AnaTabExcursions {...common} />,
    rmultiples: <AnaTabRMultiples {...common} />,
    risk: <AnaTabRisk {...common} />,
    execution: <AnaTabExecution />,
    funding: <AnaTabFunding />,
    beta: <AnaTabBeta />,
  };

  return (
    <div className="qe-scope" data-screen-label="05 Analytics" style={{
      width: '100%', height: '100%', background: 'var(--qe-bg)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      <TopNavStd page="Analytics" variant="line" dense />
      <PageHeader title="Analytics" subtitle="portfolio performance · equity curve · distributions · execution · funding · beta">
        <AnaPeriodNav period={period} onPeriod={setP} onNav={nav} disabled={!periodEnabled} label={srvLabel} />
      </PageHeader>
      <TabStrip value={tab} onChange={setTab} tabs={ANA_TABS.map(([id, l]) => [id, l])} />
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        {tabContent[tab]}
      </div>
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { AnalyticsPage });
