import React from 'react';
import { QEC, Card, SecLabel, Stat, Mono, Badge, OkBadge, Sparkline, mockEquityData } from './qe-shared.jsx';

const EQ_DATA = mockEquityData(80, 82.2, 4);

// ── Exchange status strip ─────────────────────────────────────────────────────
const ExchangeStrip = () =>
  <div style={{
    background: QEC.card, border: `1px solid ${QEC.border}`,
    borderRadius: '5px', padding: '6px 12px',
    display: 'flex', alignItems: 'center', gap: '0', flexWrap: 'wrap',
  }}>
    {[
      { label: 'EXCHANGE',    value: 'Binance',                  valueStyle: {} },
      { label: 'SERVER TIME', value: '2026-04-25 20:08:36 UTC',  valueStyle: { fontFamily: 'JetBrains Mono,monospace', fontSize: '0.78rem' } },
      { label: 'LATENCY',     value: '93.5 ms',                  valueStyle: { color: QEC.green } },
      { label: 'MAKER FEE',   value: '0.020%',                   valueStyle: {} },
      { label: 'TAKER FEE',   value: '0.050%',                   valueStyle: {} },
    ].map((item, i) =>
      <div key={i} style={{
        display: 'flex', alignItems: 'center', gap: '6px',
        padding: '0 12px',
        borderRight: i < 4 ? `1px solid ${QEC.border}` : 'none',
      }}>
        <span style={{ fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.sub }}>{item.label}</span>
        <span style={{ fontSize: '0.8rem', fontWeight: 600, color: QEC.text, ...item.valueStyle }}>{item.value}</span>
      </div>
    )}
  </div>;

// ── Progress gauge bar ────────────────────────────────────────────────────────
const Gauge = ({ value, max, color = QEC.blue, label, current, maxLabel, ok = true }) => {
  const pct = Math.min(value / max * 100, 100);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '4px' }}>
        <span style={{ fontSize: '0.62rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.sub }}>{label}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.82rem', fontWeight: 700, color: ok ? QEC.text : QEC.red }}>{current}</span>
          <OkBadge ok={ok} />
        </div>
      </div>
      <div style={{ height: '4px', background: QEC.muted, borderRadius: '2px', overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`, borderRadius: '2px',
          background: pct > 80 ? QEC.red : pct > 60 ? QEC.amber : color,
          transition: 'width 0.3s',
        }} />
      </div>
      <div style={{ fontSize: '0.58rem', color: QEC.muted, marginTop: '2px', fontFamily: 'monospace' }}>max {maxLabel}</div>
    </div>
  );
};

// ── Hero section ──────────────────────────────────────────────────────────────
const HeroSection = () => {
  const [chartTf, setChartTf] = React.useState('1h');
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '220px 1fr', gap: '0',
      background: QEC.card, border: `1px solid ${QEC.border}`, borderRadius: '5px', overflow: 'hidden',
    }}>
      {/* Left: key numbers */}
      <div style={{
        padding: '14px 16px', borderRight: `1px solid ${QEC.border}`,
        display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: QEC.sub, marginBottom: '4px' }}>Total Equity</div>
          <div style={{ fontFamily: 'JetBrains Mono,monospace', fontWeight: 700, color: QEC.text, lineHeight: 1, fontSize: '22px' }}>82.20</div>
          <div style={{ fontSize: '0.72rem', color: QEC.sub, marginTop: '2px', fontFamily: 'monospace' }}>USDT</div>
        </div>

        <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: `1px solid ${QEC.border}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <div style={{ fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.sub, marginBottom: '2px' }}>Daily PnL</div>
              <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '1.05rem', fontWeight: 700, color: QEC.sub }}>-0.00</div>
              <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.68rem', color: QEC.sub }}>(-0.00%)</div>
            </div>
            <div>
              <div style={{ fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.sub, marginBottom: '2px' }}>Weekly PnL</div>
              <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '1.05rem', fontWeight: 700, color: QEC.sub }}>-0.00</div>
              <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.68rem', color: QEC.sub }}>(-0.00%)</div>
            </div>
          </div>
        </div>

        <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: `1px solid ${QEC.border}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
            {[
              { label: 'Available',   value: '82.20' },
              { label: 'Margin Used', value: '0.00' },
              { label: 'Unrealized',  value: '0.00' },
              { label: 'BOD Equity',  value: '82.20' },
            ].map((s) =>
              <div key={s.label}>
                <div style={{ fontSize: '0.55rem', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', color: QEC.muted, marginBottom: '1px' }}>{s.label}</div>
                <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.78rem', fontWeight: 600, color: QEC.sub }}>{s.value}</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right: equity curve */}
      <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
          <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.62rem', color: QEC.sub, display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <span>O <span style={{ color: QEC.text }}>$82.20</span></span>
            <span>H <span style={{ color: QEC.green }}>$82.20</span></span>
            <span>L <span style={{ color: QEC.red }}>$82.20</span></span>
            <span>C <span style={{ color: QEC.text }}>$82.20</span></span>
            <span>Chg <span style={{ color: QEC.text }}>+$0.00</span></span>
          </div>
          <div style={{ display: 'flex', gap: '2px' }}>
            {['1h', '4h', '1d', '1w'].map((t) =>
              <button key={t} onClick={() => setChartTf(t)} style={{
                padding: '1px 7px', border: 'none', cursor: 'pointer', borderRadius: '3px',
                background: chartTf === t ? QEC.blue : QEC.panel,
                color: chartTf === t ? '#fff' : QEC.sub, fontSize: '0.6rem', fontWeight: 700,
              }}>{t}</button>
            )}
          </div>
        </div>
        <div style={{ flex: 1, minHeight: '110px' }}>
          <Sparkline data={EQ_DATA} color={QEC.green} height={110} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.58rem', color: QEC.muted, marginTop: '3px', fontFamily: 'monospace' }}>
          <span>Mar 28</span><span>Apr 5</span><span>Apr 12</span><span>Apr 19</span><span>Apr 25</span>
        </div>
      </div>
    </div>
  );
};

// ── Secondary stat row ────────────────────────────────────────────────────────
const SecondaryStats = () =>
  <div style={{
    background: QEC.card, border: `1px solid ${QEC.border}`, borderRadius: '5px',
    display: 'flex', overflow: 'hidden',
  }}>
    {[
      { label: 'SOW Equity',      value: '82.20' },
      { label: 'Max Equity (BOD)', value: '82.20' },
      { label: 'Min Equity (BOD)', value: '82.20' },
      { label: 'Total IP',        value: '0.00 USDT' },
      { label: 'Total GL',        value: '0.00 USDT' },
    ].map((s, i) =>
      <div key={i} style={{
        flex: 1, padding: '7px 10px',
        borderRight: i < 4 ? `1px solid ${QEC.border}` : 'none',
        minWidth: 0,
      }}>
        <div style={{ fontSize: '0.55rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.muted, marginBottom: '2px', whiteSpace: 'nowrap' }}>{s.label}</div>
        <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.82rem', fontWeight: 700, color: QEC.sub, whiteSpace: 'nowrap' }}>{s.value}</div>
      </div>
    )}
  </div>;

// ── Risk + positions row ──────────────────────────────────────────────────────
const RiskRow = () =>
  <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '6px' }}>
    {/* Risk gauges */}
    <div style={{ background: QEC.card, border: `1px solid ${QEC.border}`, borderRadius: '5px', padding: '10px 12px' }}>
      <div style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: QEC.sub, marginBottom: '10px' }}>Risk &amp; Exposure</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <Gauge label="Total Exposure" value={0} max={5}   color={QEC.blue}  current="0.00% equity" maxLabel="5.0×" ok={true} />
        <Gauge label="Drawdown"       value={0} max={10}  color={QEC.amber} current="0.00%"         maxLabel="10.0%" ok={true} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '10px', paddingTop: '10px', borderTop: `1px solid ${QEC.border}` }}>
        <div>
          <div style={{ fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.muted, marginBottom: '2px' }}>Weekly PnL State</div>
          <OkBadge ok={true} />
        </div>
        <div>
          <div style={{ fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.muted, marginBottom: '2px' }}>Drawdown State</div>
          <OkBadge ok={true} />
        </div>
        <div>
          <div style={{ fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.muted, marginBottom: '2px' }}>Funding Exposure</div>
          <div style={{ fontSize: '0.7rem', color: QEC.muted }}>No open positions.</div>
        </div>
        <div>
          <div style={{ fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.muted, marginBottom: '2px' }}>Sector Exposure</div>
          <div style={{ fontSize: '0.7rem', color: QEC.muted }}>No correlated exposure.</div>
        </div>
      </div>
    </div>

    {/* Open positions */}
    <div style={{ background: QEC.card, border: `1px solid ${QEC.border}`, borderRadius: '5px', padding: '10px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: QEC.sub }}>Open Positions</div>
        <span style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.72rem', color: QEC.sub }}>0 / 20</span>
      </div>
      <div style={{ height: '3px', background: QEC.muted, borderRadius: '2px', marginBottom: '12px' }}>
        <div style={{ width: '0%', height: '100%', background: QEC.blue, borderRadius: '2px' }} />
      </div>
      <div style={{ textAlign: 'center', padding: '20px 0', color: QEC.muted, fontSize: '0.78rem' }}>
        No open positions.
      </div>
    </div>
  </div>;

// ── Monthly summary row ───────────────────────────────────────────────────────
const MonthlyRow = () => {
  const stats = [
    { label: 'Total Trades', value: '31',     color: QEC.text },
    { label: 'Winning',      value: '12',     color: QEC.green },
    { label: 'Losing',       value: '19',     color: QEC.red },
    { label: 'Win Rate',     value: '38.7%',  color: QEC.text },
    { label: 'Avg R:R',      value: '1.20R',  color: QEC.text },
    { label: 'Avg Profit',   value: '1.23',   color: QEC.green },
    { label: 'Avg Loss',     value: '-1.02',  color: QEC.red },
    { label: 'Max Drawdown', value: '12.24%', color: QEC.red },
    { label: 'Monthly Vol',  value: '$2,168', color: QEC.text },
    { label: 'Broker Fee',   value: '$2.54',  color: QEC.sub },
    { label: 'No. Longs',    value: '19',     color: QEC.green },
    { label: 'No. Shorts',   value: '12',     color: QEC.red },
  ];

  return (
    <div style={{ background: QEC.card, border: `1px solid ${QEC.border}`, borderRadius: '5px', padding: '10px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: QEC.sub }}>April 2026 Summary</div>
        <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.92rem', fontWeight: 700, color: QEC.red }}>-$11.18 <span style={{ fontSize: '0.72rem', color: QEC.sub }}>(-11.97%)</span></div>
      </div>
      <div style={{ height: '4px', background: QEC.muted, borderRadius: '2px', marginBottom: '10px', overflow: 'hidden' }}>
        <div style={{ width: '38.7%', height: '100%', background: QEC.green, borderRadius: '2px' }} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(90px,1fr))', gap: '6px 12px' }}>
        {stats.map((s) =>
          <div key={s.label}>
            <div style={{ fontSize: '0.55rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.muted, marginBottom: '1px' }}>{s.label}</div>
            <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.88rem', fontWeight: 700, color: s.color }}>{s.value}</div>
          </div>
        )}
        <div style={{ gridColumn: '1/-1' }}>
          <div style={{ fontSize: '0.55rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: QEC.muted, marginBottom: '1px' }}>Top Pairs</div>
          <div style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.75rem', color: QEC.sub }}>STOUSDT · JCTUSDT · AIOTUSDT</div>
        </div>
      </div>
    </div>
  );
};

// ── Active Parameters strip ───────────────────────────────────────────────────
const ActiveParams = () =>
  <div style={{
    background: QEC.card, border: `1px solid ${QEC.border}`,
    borderRadius: '5px', padding: '7px 12px',
  }}>
    <div style={{ fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: QEC.sub, marginBottom: '6px' }}>
      Active Parameters <span style={{ color: QEC.muted, letterSpacing: '0.04em' }}>(view-only)</span>
    </div>
    <div style={{ display: 'flex', gap: '0', flexWrap: 'wrap' }}>
      {[
        { label: 'Risk/trade',    value: '1.00%', color: QEC.blue },
        { label: 'Max W-loss',    value: '5.0%',  color: null },
        { label: 'Max DD',        value: '10.0%', color: null },
        { label: 'Max exposure',  value: '5.0×',  color: null },
        { label: 'Max positions', value: '10',    color: null },
        { label: 'Max corr. exp', value: '50%',   color: null },
      ].map((p, i) =>
        <div key={i} style={{
          display: 'flex', alignItems: 'center', gap: '5px',
          padding: '0 12px',
          borderRight: i < 5 ? `1px solid ${QEC.border}` : 'none',
          marginBottom: '2px',
        }}>
          <span style={{ fontSize: '0.65rem', color: QEC.sub }}>{p.label}:</span>
          <span style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: '0.78rem', fontWeight: 700, color: p.color || QEC.text }}>{p.value}</span>
        </div>
      )}
    </div>
  </div>;

export const DashboardPage = () =>
  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', padding: '8px' }}>
    <ExchangeStrip />
    <HeroSection />
    <SecondaryStats />
    <RiskRow />
    <MonthlyRow />
    <ActiveParams />
  </div>;
