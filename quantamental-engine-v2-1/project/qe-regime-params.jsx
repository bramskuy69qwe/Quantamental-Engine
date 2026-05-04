// QE Regime + Params Pages

// ── Regime ────────────────────────────────────────────────────────────────

const REGIME_TIMELINE = (() => {
  const regimes = ['risk_on_trending', 'risk_on_choppy', 'neutral', 'neutral', 'neutral', 'risk_off_defensive', 'neutral', 'risk_on_choppy', 'neutral', 'risk_off_panic'];
  const data = [];
  for (let i = 0; i < 365; i++) {
    const d = new Date(2025, 3, 25);d.setDate(d.getDate() + i);
    data.push({
      date: d.toISOString().slice(0, 10),
      regime: regimes[Math.floor(Math.random() * regimes.length)]
    });
  }
  return data;
})();

const REGIME_DIST = { risk_on_trending: 0.8, risk_on_choppy: 32.9, neutral: 60.2, risk_off_defensive: 6.9, risk_off_panic: 0.0 };

const SIGNALS = [
{ key: 'vix', label: 'VIX', val: '10.7', color: QEC.red, data: mockEquityData(60, 18, 6) },
{ key: 'us10y', label: 'US 10Y Yield', val: '4.38%', color: QEC.cyan, data: mockEquityData(60, 4.2, 0.3) },
{ key: 'hy', label: 'HY Spread', val: '2.86%', color: QEC.amber, data: mockEquityData(60, 3.2, 0.8) },
{ key: 'btcdom', label: 'BTC Market Cap', val: '—', color: QEC.amber, data: [] },
{ key: 'rvol', label: 'BTC RVol (30d/7d)', val: '1.21', color: QEC.purple, data: mockEquityData(60, 1.15, 0.2) },
{ key: 'oi', label: 'Aggregate OI Change', val: '—', color: QEC.green, data: [] },
{ key: 'funding', label: 'Avg Funding Rate', val: '0.00005', color: QEC.blue, data: mockEquityData(60, 0.00005, 0.00003) }];


const COVERAGE = [
{ signal: 'VIX', source: 'yfinance', from: '2020-01-02', to: '2026-04-24', rows: 1586 },
{ signal: 'US 10Y Yield', source: 'FRED', from: '2020-01-02', to: '2026-04-23', rows: 1578 },
{ signal: 'HY Spread', source: 'FRED', from: '2020-01-02', to: '2026-04-23', rows: 1661 },
{ signal: 'BTC Market Cap', source: 'CoinGecko', from: '—', to: '—', rows: null },
{ signal: 'BTC RVol (30d/7d)', source: 'derived', from: '2024-05-11', to: '2026-04-10', rows: 700 },
{ signal: 'Aggregate OI Chg', source: 'Binance', from: '—', to: '—', rows: null },
{ signal: 'Avg Funding Rate', source: 'Binance', from: '2020-01-01', to: '2026-04-25', rows: 2383 }];


const THRESHOLDS = [
{ label: 'VIX Panic', key: 'vix_panic', val: 30 },
{ label: 'VIX Defensive', key: 'vix_defensive', val: 25 },
{ label: 'VIX Risk-On', key: 'vix_risk_on', val: 20 },
{ label: 'VIX Choppy', key: 'vix_choppy', val: 22 },
{ label: 'HY Spread Panic', key: 'hy_spread_panic', val: 5 },
{ label: 'HY Spread Defensive', key: 'hy_spread_defensive', val: 4.5 },
{ label: 'HY Spread Neutral', key: 'hy_spread_neutral', val: 4 },
{ label: 'HY Spread Risk-On', key: 'hy_spread_risk_on', val: 3.5 },
{ label: 'RVol Choppy', key: 'rvol_ratio_choppy', val: 1.3 },
{ label: 'RVol Trending', key: 'rvol_ratio_trending', val: 1.2 },
{ label: 'Funding Panic', key: 'funding_panic', val: -0.01 },
{ label: 'BTC Dom Bull', key: 'btc_dom_change_bull', val: 0.5 },
{ label: 'BTC Dom Bear', key: 'btc_dom_change_bear', val: 0.5 }];


const TL_COLOR = {
  risk_on_trending: '#00c855', risk_on_choppy: '#00b4d8',
  neutral: '#4a6888', risk_off_defensive: '#e89020', risk_off_panic: '#e83535'
};

// Collapse consecutive same-regime days into segments
function buildSegments(data) {
  if (!data.length) return [];
  const segs = [];
  let cur = { regime: data[0].regime, start: 0, end: 0, days: 1 };
  for (let i = 1; i < data.length; i++) {
    if (data[i].regime === cur.regime) {cur.end = i;cur.days++;} else
    {segs.push(cur);cur = { regime: data[i].regime, start: i, end: i, days: 1 };}
  }
  segs.push(cur);
  return segs;
}

const REGIME_ORDER = ['risk_on_trending', 'risk_on_choppy', 'neutral', 'risk_off_defensive', 'risk_off_panic'];

// ① Bars — classic vertical strip
const TLBars = ({ data }) => {
  const W = 1000,H = 50,n = data.length,bw = W / n;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: `${H}px`, display: 'block', borderRadius: '3px', overflow: 'hidden' }}>
      {data.map((d, i) =>
      <rect key={i} x={i * bw} y={0} width={Math.max(bw, 0.5)} height={H}
      fill={TL_COLOR[d.regime] || '#4a6888'} opacity="0.9" />
      )}
    </svg>);

};

// ② Blocks — segmented bar; each run is one labeled rectangle
const TLBlocks = ({ data }) => {
  const W = 1000,H = 40,n = data.length;
  const segs = buildSegments(data);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: `${H}px`, display: 'block' }}>
      {segs.map((s, i) => {
        const x = s.start / n * W;
        const w = s.days / n * W;
        const c = TL_COLOR[s.regime] || '#4a6888';
        const lbl = REGIME_META[s.regime]?.short || '?';
        return (
          <g key={i}>
            <rect x={x + 0.5} y={0} width={Math.max(w - 1, 0.5)} height={H} fill={c} opacity="0.85" rx="2" />
            {w > 40 &&
            <text x={x + w / 2} y={H / 2 + 4} textAnchor="middle"
            fill="#000" fillOpacity="0.55" fontSize="9" fontWeight="700" fontFamily="JetBrains Mono,monospace">
                {s.days > 6 ? `${lbl} ${s.days}d` : lbl}
              </text>
            }
          </g>);

      })}
    </svg>);

};

// ③ Swim — swimlanes with external labels
const TLSwim = ({ data }) => {
  const LANE = 16,GAP = 3,n = data.length;
  const segs = buildSegments(data);
  return (
    <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
      {/* External labels */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: `${GAP}px`, flexShrink: 0, paddingTop: '1px' }}>
        {REGIME_ORDER.map((r) =>
        <div key={r} style={{
          height: `${LANE}px`, display: 'flex', alignItems: 'center',
          fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.06em',
          color: TL_COLOR[r], whiteSpace: 'nowrap', fontFamily: 'JetBrains Mono,monospace'
        }}>
            {REGIME_META[r]?.short}
          </div>
        )}
      </div>
      {/* Chart */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <svg viewBox={`0 0 1000 ${REGIME_ORDER.length * (LANE + GAP)}`}
        style={{ width: '100%', height: `${REGIME_ORDER.length * (LANE + GAP)}px`, display: 'block' }}>
          {REGIME_ORDER.map((r, li) =>
          <rect key={r} x={0} y={li * (LANE + GAP)} width={1000} height={LANE}
          fill={TL_COLOR[r]} opacity="0.07" style={{ width: "1500px" }} />
          )}
          {segs.map((s, i) => {
            const li = REGIME_ORDER.indexOf(s.regime);
            if (li < 0) return null;
            const x = s.start / n * 1000;
            const w = Math.max(s.days / n * 1000 - 0.5, 1);
            return (
              <rect key={i} x={x} y={li * (LANE + GAP) + 1} width={w} height={LANE - 2}
              fill={TL_COLOR[s.regime]} opacity="0.92" rx="1" />);

          })}
        </svg>
      </div>
    </div>);

};

// ④ Heat — calendar-style dot grid, one cell per day
const TLHeat = ({ data }) => {
  const CELL = 11,GAP = 2,COLS = 52; // ~1 year = 52 weeks
  const rows = 7;
  // pad to start on Monday
  const firstDay = data[0] ? new Date(data[0].date).getDay() : 0;
  const pad = firstDay === 0 ? 6 : firstDay - 1; // monday=0
  const cells = [...Array(pad).fill(null), ...data];
  const weeks = Math.ceil(cells.length / rows);

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${weeks * (CELL + GAP)} ${rows * (CELL + GAP)}`}
      style={{ width: `${Math.min(weeks * (CELL + GAP), 900)}px`, height: `${rows * (CELL + GAP)}px`, display: 'block' }}>
        {cells.map((d, i) => {
          const col = Math.floor(i / rows);
          const row = i % rows;
          const x = col * (CELL + GAP);
          const y = row * (CELL + GAP);
          const c = d ? TL_COLOR[d.regime] || '#4a6888' : '#12202e';
          return (
            <rect key={i} x={x} y={y} width={CELL} height={CELL} rx="2"
            fill={c} opacity={d ? 0.88 : 0.3} />);

        })}
      </svg>
    </div>);

};

// ⑤ Stack — rolling regime proportion as stacked columns
const TLStack = ({ data }) => {
  const W = 1000,H = 60,WIN = 14; // 14-day rolling window
  const buckets = [];
  for (let i = WIN; i <= data.length; i += 3) {
    const slice = data.slice(i - WIN, i);
    const counts = {};
    REGIME_ORDER.forEach((r) => counts[r] = 0);
    slice.forEach((d) => {if (counts[d.regime] != null) counts[d.regime]++;});
    buckets.push({ idx: i, counts, total: WIN });
  }
  const BW = W / buckets.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: `${H}px`, display: 'block' }}>
      {buckets.map((b, bi) => {
        let y = H;
        return REGIME_ORDER.map((r) => {
          const h = b.counts[r] / b.total * H;
          y -= h;
          return <rect key={r} x={bi * BW} y={y} width={Math.max(BW - 0.5, 0.5)} height={h}
          fill={TL_COLOR[r]} opacity="0.88" />;
        });
      })}
    </svg>);

};

const RegimeTimeline = ({ style = 'swim' }) => {
  if (style === 'bars') return <TLBars data={REGIME_TIMELINE} />;
  if (style === 'blocks') return <TLBlocks data={REGIME_TIMELINE} />;
  if (style === 'heat') return <TLHeat data={REGIME_TIMELINE} />;
  if (style === 'stack') return <TLStack data={REGIME_TIMELINE} />;
  return <TLSwim data={REGIME_TIMELINE} />;
};

const RegimeOverview = () => {
  const [tlRange, setTlRange] = React.useState(365);
  const [tlStyle, setTlStyle] = React.useState('swim');
  const [sigRange, setSigRange] = React.useState(365);
  const rm = REGIME_META.neutral;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {/* Top row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr 1fr', gap: '6px' }}>
        {/* Current regime */}
        <Card p="10px 12px" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
          <Lbl>Current Regime</Lbl>
          <Badge color={rm.text} bg={rm.bg} style={{ fontSize: '0.78rem', padding: '5px 12px', letterSpacing: '0.06em' }}>
            Neutral
          </Badge>
          <div style={{ fontSize: '0.6rem', color: QEC.sub }}>As of 2026-04-25</div>
          <div style={{ fontSize: '0.6rem', color: QEC.sub }}>full mode</div>
        </Card>

        {/* Distribution */}
        <Card p="10px 12px">
          <Lbl style={{ marginBottom: '8px' }}>Regime Distribution</Lbl>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: '4px' }}>
            {Object.entries(REGIME_DIST).map(([key, pct]) => {
              const m = REGIME_META[key];
              if (!m) return null;
              return (
                <div key={key} style={{ textAlign: 'center', background: `${m.bg}`, borderRadius: '4px', padding: '6px 4px' }}>
                  <div style={{ fontSize: '0.6rem', color: m.text, fontWeight: 700, marginBottom: '2px' }}>{m.short}</div>
                  <Mono size="0.88rem" color={m.text}>{pct.toFixed(1)}%</Mono>
                  <div style={{ fontSize: '0.58rem', color: QEC.sub, marginTop: '1px' }}>
                    {Math.round(pct * 3.65)}d
                  </div>
                </div>);

            })}
          </div>
        </Card>

        {/* Sizing multipliers */}
        <Card p="10px 12px">
          <Lbl style={{ marginBottom: '8px' }}>Sizing Multipliers</Lbl>
          {[
          { label: 'Trending', color: QEC.green, mult: '1.2×' },
          { label: 'Choppy', color: QEC.cyan, mult: '1.0×' },
          { label: 'Neutral', color: QEC.sub, mult: '1.0×' },
          { label: 'Defensive', color: QEC.amber, mult: '0.7×' },
          { label: 'Panic', color: QEC.red, mult: '0.4×' }].
          map((r) =>
          <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
              <span style={{ fontSize: '0.72rem', color: r.color }}>{r.label}</span>
              <Mono size="0.78rem">{r.mult}</Mono>
            </div>
          )}
        </Card>
      </div>

      {/* Timeline */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px', flexWrap: 'wrap', gap: '4px' }}>
          <Mono size="0.82rem">Regime Timeline</Mono>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            {/* Style picker */}
            <div style={{ display: 'flex', gap: '2px', borderRight: `1px solid ${QEC.border}`, paddingRight: '6px', marginRight: '2px' }}>
              {[['swim', 'Swim'], ['bars', 'Bars'], ['blocks', 'Blocks'], ['heat', 'Heat'], ['stack', 'Stack']].map(([id, lbl]) =>
              <button key={id} onClick={() => setTlStyle(id)} style={{
                padding: '2px 8px', border: `1px solid ${tlStyle === id ? QEC.blue : QEC.border}`, borderRadius: '3px', cursor: 'pointer',
                background: tlStyle === id ? '#0d2050' : 'transparent',
                color: tlStyle === id ? QEC.blue : QEC.sub, fontSize: '0.62rem', fontWeight: tlStyle === id ? 700 : 500
              }}>{lbl}</button>
              )}
            </div>
            {/* Range picker */}
            {[30, 90, 365, 0].map((d, i) =>
            <button key={d} onClick={() => setTlRange(d)} style={{
              padding: '2px 7px', border: `1px solid ${QEC.border}`, borderRadius: '3px', cursor: 'pointer',
              background: tlRange === d ? '#1a3060' : QEC.panel,
              color: tlRange === d ? '#93c5fd' : QEC.sub, fontSize: '0.62rem', fontWeight: 600
            }}>{['30d', '90d', '1y', 'All'][i]}</button>
            )}
          </div>
        </div>
        <RegimeTimeline style={tlStyle} />
        {tlStyle !== 'swim' && tlStyle !== 'stack' &&
        <div style={{ display: 'flex', gap: '12px', marginTop: '6px', flexWrap: 'wrap' }}>
            {Object.entries(REGIME_META).map(([k, m]) =>
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.62rem' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: m.text, display: 'inline-block' }}></span>
                <span style={{ color: m.text }}>{m.label}</span>
              </div>
          )}
          </div>
        }
      </Card>

      {/* Signal cards */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '2px' }}>
        <Mono size="0.82rem">Macro Signals</Mono>
        <div style={{ display: 'flex', gap: '3px' }}>
          {[30, 90, 365, 1825, 0].map((d, i) =>
          <button key={d} onClick={() => setSigRange(d)} style={{
            padding: '2px 7px', border: `1px solid ${QEC.border}`, borderRadius: '3px', cursor: 'pointer',
            background: sigRange === d ? '#1a3060' : QEC.panel,
            color: sigRange === d ? '#93c5fd' : QEC.sub, fontSize: '0.62rem', fontWeight: 600
          }}>{['30d', '90d', '1y', '5y', 'All'][i]}</button>
          )}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: '6px' }}>
        {SIGNALS.map((sig) =>
        <Card key={sig.key} p="8px 10px">
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '5px' }}>
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: sig.color, display: 'inline-block', flexShrink: 0 }}></span>
              <span style={{ fontSize: '0.7rem', fontWeight: 600, color: QEC.text }}>{sig.label}</span>
              <Mono size="0.72rem" color={sig.val === '—' ? QEC.sub : QEC.text}>{sig.val}</Mono>
            </div>
            {sig.data.length > 0 ?
          <Sparkline data={sig.data} color={sig.color} height={70} showFill={true} /> :
          <div style={{ height: '70px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.65rem', color: QEC.sub }}>
                  No data — signal not yet backfilled
                </div>
          }
          </Card>
        )}
      </div>
    </div>);

};

const RegimeBackfill = () =>
<div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '6px', alignItems: 'start' }}>
    <Card p="10px 12px">
      <SecLabel>Backfill Macro Data</SecLabel>
      <div style={{ fontSize: '0.72rem', color: QEC.sub, marginBottom: '10px', lineHeight: 1.5 }}>
        Fetch historical macro signals from free data sources. Macro-only works for deep history (5-30+ years). Full adds Binance OI/funding (~2-3 years).
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <Sel label="Mode">
          <option>Macro Only (VIX, FRED, BTC dom)</option>
          <option>Full (+ Binance OI, Funding)</option>
        </Sel>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
          <Inp label="From" type="date" defaultValue="2020-01-01" />
          <Inp label="To" type="date" />
        </div>
        <Btn variant="primary" size="md" style={{ width: '100%', marginTop: '2px' }}>Start Backfill</Btn>
      </div>
    </Card>
    <Card p="10px 12px">
      <SecLabel>Signal Coverage</SecLabel>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>
          {['Signal', 'Source', 'From', 'To', 'Rows'].map((h) =>
          <th key={h} style={{ color: QEC.sub, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase',
            padding: '5px 8px', borderBottom: `1px solid ${QEC.border}`, textAlign: 'left' }}>{h}</th>
          )}
        </tr></thead>
        <tbody>
          {COVERAGE.map((r, i) =>
        <tr key={i} style={{ opacity: r.rows == null ? 0.45 : 1 }}>
              <td style={{ padding: '5px 8px', borderBottom: `1px solid ${QEC.border}`, fontSize: '0.72rem', color: QEC.text }}>{r.signal}</td>
              <td style={{ padding: '5px 8px', borderBottom: `1px solid ${QEC.border}`, fontSize: '0.65rem', color: QEC.sub, fontFamily: 'monospace' }}>{r.source}</td>
              <td style={{ padding: '5px 8px', borderBottom: `1px solid ${QEC.border}`, fontSize: '0.65rem', color: QEC.sub, fontFamily: 'monospace' }}>{r.from}</td>
              <td style={{ padding: '5px 8px', borderBottom: `1px solid ${QEC.border}`, fontSize: '0.65rem', color: QEC.sub, fontFamily: 'monospace' }}>{r.to}</td>
              <td style={{ padding: '5px 8px', borderBottom: `1px solid ${QEC.border}`, fontSize: '0.72rem', fontFamily: 'JetBrains Mono,monospace',
            color: r.rows != null ? QEC.green : QEC.sub }}>{r.rows != null ? r.rows.toLocaleString() : '—'}</td>
            </tr>
        )}
        </tbody>
      </table>
    </Card>
  </div>;


const RegimeConfig = () =>
<div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '6px', alignItems: 'start' }}>
    <Card p="10px 12px">
      <SecLabel>Classifier Thresholds</SecLabel>
      <div style={{ fontSize: '0.65rem', color: QEC.sub, marginBottom: '8px' }}>Current threshold values used by the rule-based regime classifier.</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
        {THRESHOLDS.map((t) =>
      <div key={t.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '4px 8px', borderRadius: '3px', transition: 'background 0.1s' }}
      onMouseOver={(e) => e.currentTarget.style.background = QEC.hover}
      onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}>
            <span style={{ fontSize: '0.7rem', color: QEC.sub }}>{t.label}</span>
            <Mono size="0.78rem">{t.val}</Mono>
          </div>
      )}
      </div>
      <Divider />
      <Btn variant="secondary" size="md" style={{ width: '100%' }}>Reclassify All Dates</Btn>
    </Card>

    <Card p="10px 12px">
      <SecLabel>Decision Tree Rules</SecLabel>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {[
      { color: QEC.red, bg: '#200808', label: 'Panic', rule: 'VIX > 30 AND (HY Spread > 5 OR Funding < -0.01)' },
      { color: QEC.amber, bg: '#201000', label: 'Defensive', rule: 'VIX > 25 OR HY Spread > 4.5 OR BTC Dom rising > 0.5%/wk' },
      { color: QEC.green, bg: '#072018', label: 'Trending', rule: 'VIX < 20 AND RVol < 1.2 (+ OI rising, funding > 0 in full mode)' },
      { color: QEC.cyan, bg: '#052020', label: 'Choppy', rule: 'VIX < 22 AND RVol > 1.3' },
      { color: QEC.sub, bg: QEC.panel, label: 'Neutral', rule: 'default fallback when no other rule triggers' }].
      map((r) =>
      <div key={r.label} style={{ background: r.bg, border: `1px solid ${r.color}30`, borderRadius: '4px', padding: '8px 10px' }}>
            <span style={{ color: r.color, fontWeight: 700, fontSize: '0.75rem' }}>{r.label}:</span>
            <span style={{ color: QEC.sub, fontSize: '0.72rem', marginLeft: '6px' }}>{r.rule}</span>
          </div>
      )}
      </div>
    </Card>
  </div>;


const RegimePage = ({ tabStyle = 'line' }) => {
  const [panel, setPanel] = React.useState('overview');
  const tabs = [['overview', 'Overview'], ['backfill', 'Backfill'], ['config', 'Config']];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', padding: '8px' }}>
      <TabBar
        tabs={[['overview', 'Overview'], ['backfill', 'Backfill'], ['config', 'Config']]}
        active={panel} onChange={setPanel}
        variant={tabStyle}
        style={{ marginBottom: '6px' }} />
      
      {panel === 'overview' && <RegimeOverview />}
      {panel === 'backfill' && <RegimeBackfill />}
      {panel === 'config' && <RegimeConfig />}
    </div>);

};

// ── Params ────────────────────────────────────────────────────────────────

const WS_LOG = [
'[19:58:04] No market streams to subscribe — sleeping 10s.',
'[19:58:14] No market streams to subscribe — sleeping 10s.',
'[19:58:24] No market streams to subscribe — sleeping 10s.',
'[19:58:34] No market streams to subscribe — sleeping 10s.',
'[19:58:44] No market streams to subscribe — sleeping 10s.',
'[19:58:54] No market streams to subscribe — sleeping 10s.',
'[19:59:04] No market streams to subscribe — sleeping 10s.',
'[19:59:14] No market streams to subscribe — sleeping 10s.',
'[19:59:24] Market WS connecting (2 streams, attempt 1)',
'[19:59:24] Market WS connected.'];


const ParamsPage = () => {
  const [saved, setSaved] = React.useState(false);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', padding: '8px' }}>

      <Card>
        <SecLabel>Risk Parameters</SecLabel>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: '8px' }}>
          <div>
            <Inp label="Individual Risk / Trade (%)" type="number" defaultValue="0.01" />
            <div style={{ fontSize: '0.6rem', color: QEC.sub, marginTop: '2px' }}>Fraction of equity per trade (e.g. 0.01 = 1%)</div>
          </div>
          <div>
            <Inp label="Max Weekly Loss (%)" type="number" defaultValue="0.05" />
            <div style={{ fontSize: '0.6rem', color: QEC.sub, marginTop: '2px' }}>e.g. 0.05 = 5% — resets every Monday BOD</div>
          </div>
          <Inp label="Max Drawdown (%)" type="number" defaultValue="0.1" />
          <Inp label="Max Exposure (×Equity)" type="number" defaultValue="5.0" />
          <Inp label="Max Open Positions" type="number" defaultValue="10" />
          <div>
            <Inp label="Max Correlated Exposure (Fraction of Equity)" type="number" defaultValue="0.5" />
            <div style={{ fontSize: '0.6rem', color: QEC.sub, marginTop: '2px' }}>Default 0.5 = 50% of equity per sector</div>
          </div>
          <Inp label="Auto Export Every (Hours)" type="number" defaultValue="24" />
        </div>
      </Card>

      <Card>
        <SecLabel>Soft / Hard Stop Thresholds</SecLabel>
        <div style={{ fontSize: '0.65rem', color: QEC.sub, marginBottom: '8px' }}>
          Warning triggers at X% of the limit. Hard stop triggers at Y% of the limit.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: '8px' }}>
          <Inp label="Weekly Loss Warning (% of Max)" type="number" defaultValue="0.8" />
          <Inp label="Weekly Loss Hard Stop (% of Max)" type="number" defaultValue="0.95" />
          <Inp label="DD Warning (% of Max)" type="number" defaultValue="0.8" />
          <Inp label="DD Hard Stop (% of Max)" type="number" defaultValue="0.95" />
        </div>
      </Card>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Btn variant="primary" size="lg" onClick={() => {setSaved(true);setTimeout(() => setSaved(false), 2000);}}>
          Save Parameters
        </Btn>
        {saved && <span style={{ fontSize: '0.72rem', color: QEC.green }}>✓ Parameters persisted to data/params.json</span>}
        {!saved && <span style={{ fontSize: '0.65rem', color: QEC.sub }}>Parameters are persisted to data/params.json</span>}
      </div>

      <Card>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <SecLabel style={{ marginBottom: 0 }}>Account Management</SecLabel>
          <Btn variant="primary" size="sm">+ Add Account</Btn>
        </div>
        <table style={{width:'100%',borderCollapse:'collapse'}}>
          <thead><tr>
            {['Name','Exchange','Type','Broker Account ID','Status','Actions'].map(h => (
              <th key={h} style={{color:QEC.sub,fontSize:'0.6rem',fontWeight:700,letterSpacing:'0.07em',
                textTransform:'uppercase',padding:'5px 8px',borderBottom:`1px solid ${QEC.border}`,textAlign:'left'}}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            <tr>
              <td style={{padding:'7px 8px',borderBottom:`1px solid ${QEC.border}`,fontSize:'0.78rem',color:QEC.text,fontWeight:600}}>Account 1 (Binance Futures)</td>
              <td style={{padding:'7px 8px',borderBottom:`1px solid ${QEC.border}`,fontSize:'0.75rem',color:QEC.sub}}>Binance</td>
              <td style={{padding:'7px 8px',borderBottom:`1px solid ${QEC.border}`,fontSize:'0.75rem',color:QEC.sub}}>Futures</td>
              <td style={{padding:'7px 8px',borderBottom:`1px solid ${QEC.border}`}}>
                <input defaultValue="binancefutures_1234"
                  title="Quantower account ID for fill routing"
                  style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:QEC.sub,
                    borderRadius:'4px',padding:'2px 6px',fontSize:'0.68rem',
                    fontFamily:'JetBrains Mono,monospace',width:'170px',height:'24px'}}
                  onMouseOver={e=>e.target.style.borderColor=QEC.borderFoc}
                  onMouseOut={e=>e.target.style.borderColor=QEC.border}
                />
              </td>
              <td style={{padding:'7px 8px',borderBottom:`1px solid ${QEC.border}`}}>
                <Badge color={QEC.green} bg="#072018">● Active</Badge>
              </td>
              <td style={{padding:'7px 8px',borderBottom:`1px solid ${QEC.border}`}}>
                <Btn variant="ghost" size="sm">Test</Btn>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card>
        <SecLabel>WebSocket Log (Last 30 entries)</SecLabel>
        <div style={{
          fontFamily: 'JetBrains Mono,monospace', fontSize: '0.65rem', color: QEC.sub,
          background: QEC.panel, borderRadius: '4px', padding: '8px',
          maxHeight: '150px', overflowY: 'auto', lineHeight: 1.7
        }}>
          {WS_LOG.map((l, i) => <div key={i}>{l}</div>)}
        </div>
      </Card>
    </div>);

};

Object.assign(window, { RegimePage, ParamsPage });