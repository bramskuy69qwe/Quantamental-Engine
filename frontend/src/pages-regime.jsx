/* v3.0 — Regime page (P6). Ported from the Meridian reference
   (pages-regime.jsx) and WIRED to real data — the regime surface was ALREADY
   all-JSON (verify-first verdict: zero ?format=json doors needed):
     · header / Current pane ← GET /api/regime/current (60s poll; source-aware:
       live → computed_at, db → row date, none → dormant badge)
     · timeline / distribution / recent changes ← GET /api/regime/timeline
       (?from_date= per range; distribution + label-change rows derived
       client-side, Jinja parity)
     · signal cards ← GET /api/regime/signals?signal_name=&from_date= per card
       + GET /api/regime/coverage (empty-state discrimination: rows>0 → "no
       data for range", 0 → "not yet backfilled" + CTA, Task-124 parity)
     · thresholds (marklines + Config tab) ← GET /api/regime/thresholds
       (client-side presentation map over SERVER values — no hardcoded numbers)
     · sizing multipliers ← GET /api/regime/multipliers (the P6 additive
       endpoint; /current carries only the CURRENT label's multiplier)
     · backfill ← POST /api/regime/backfill → poll
       GET /api/regime/backfill-status/{id} every 1500ms (Jinja cadence)
     · reclassify ← POST /api/regime/reclassify {} (upsert recompute — the UI
       never sends dates, so the delete lane is unreachable; CONFIRM-GATED
       here per the house convention [P6 audit L4 fold] — a named deviation
       from Jinja, which fires with no confirm) [P8 doc wave: this line had
       claimed the opposite of shipped behavior — audit L5-LOW-1]
     · news ← GET /api/news/feed?limit=80 (15s) · calendar ← GET /api/calendar
       (now±30d, 60s) · manual POST /api/news/refresh — NOTE: the News tab
       binds /api/news/* + /api/calendar, NOT /api/regime/* (the plan row's
       "all 4 sub-tabs on /api/regime/*" was literally false here; no new
       backend was needed, just different endpoints).
   Named deviations vs the design mock (engine truth wins):
   - SIX signal cards, not seven: btc_dominance has NO engine source (no fetch
     step in RegimeFetcher.fetch_all; migration core/database.py:1001 deletes
     its rows) — the design/Jinja card could only ever render "not backfilled".
   - Multipliers come from config via /api/regime/multipliers (1.2/1.0/1.0/
     0.7/0.4) — the design mock's 0.6×/0.25× for choppy/panic were wrong.
   - Backfill "Full" hint is honest: the UI-triggered fetcher has no exchange
     adapter, so OI/funding rows come from the engine scheduler only; Full
     still classifies with whatever crypto rows exist.
   - Design foot={} telemetry lines are mock ornaments — not ported (P1-P5
     parity). The economic-calendar impact filter is client-side (Jinja
     parity — the server's ?impact= param goes unused there too).
   - Frozen demo clock stripped: rel-times/NOW marker use real Date.now()
     (60s re-render tick; the 1s UTC clock is the isolated LiveClock leaf).
   - Transition context strip's from→to multipliers read the server map.
   - /api/regime/transitions (5×5 matrix) stays unbound — unbound in Jinja
     and absent from the design; creative-latitude extra → deferred (§7).
   - News items carry a neutral CATEGORY chip, not the red/amber impact
     palette — engine news has no impact field (audit L3); impact pills
     stay on the economic calendar, which does. The Jinja List+Detail
     pane (image_url + full detail) is NOT ported — the article link
     survives as "open ↗" on expanded items (audit M4).
   - Coverage table synthesizes count-0 rows for un-backfilled signals
     (the server endpoint GROUP-BYs existing rows only — audit M6b).
   - Decision-tree copy corrected vs the design/Jinja to match the REAL
     classify_regime cascade (audit MED-1 — panic second leg, HY risk-on
     gate, full-vs-macro trending lanes).
   Named residues: header badge/multiplier refresh ≤60s after a backfill
   (page poll; Jinja reloaded immediately); the calendar ±30d window is
   fixed at tab mount; re-clicking the SAME range value is a visual no-op
   (no forced refetch); news view/expand state resets on tab exit
   (component state — Jinja kept module globals).
   Reuses concatenated-scope globals: _ptJson (P3), useAnaJson (P5),
   LiveClock/EmptyState/Badge/RegimeBadge/PeriodSelector/FieldList/DataList/
   Pane/PageHeader/TabStrip/GridWorkspace/GridItem/Spinner (P0),
   QE_ECHARTS_THEME/_qeResolveColor/_axis/useECharts (P0 charts). */

const REGIME_KEYS = ['risk_on_trending', 'risk_on_choppy', 'neutral', 'risk_off_defensive', 'risk_off_panic'];
const REGIME_INFO = {
  risk_on_trending:   { label: 'Risk-On Trending',   short: 'TREND', tone: 'trend', color: 'var(--qe-green)', bg: 'color-mix(in srgb, var(--qe-green) 10%, transparent)' },
  risk_on_choppy:     { label: 'Risk-On Choppy',     short: 'CHOP',  tone: 'chop',  color: 'var(--qe-cyan)',  bg: 'color-mix(in srgb, var(--qe-cyan) 10%, transparent)' },
  neutral:            { label: 'Neutral',            short: 'NEUT',  tone: 'neut',  color: 'var(--qe-sub)',   bg: 'color-mix(in srgb, var(--qe-sub) 6%, transparent)' },
  risk_off_defensive: { label: 'Risk-Off Defensive', short: 'DEF',   tone: 'def',   color: 'var(--qe-amber)', bg: 'color-mix(in srgb, var(--qe-amber) 10%, transparent)' },
  risk_off_panic:     { label: 'Risk-Off Panic',     short: 'PANIC', tone: 'panic', color: 'var(--qe-red)',   bg: 'color-mix(in srgb, var(--qe-red) 10%, transparent)' },
};
// Regime → ECharts hex (DESIGN.md §8 — sourced from QE_ECHARTS_THEME, the
// single token→hex map; canvas can't read CSS vars).
const REGIME_THEME_KEY = {
  risk_on_trending: 'green', risk_on_choppy: 'cyan', neutral: 'muted',
  risk_off_defensive: 'amber', risk_off_panic: 'red',
};
const REGIME_HEX = Object.fromEntries(
  REGIME_KEYS.map((k) => [k, QE_ECHARTS_THEME[REGIME_THEME_KEY[k]]])
);

const _rgMult = (mults, key) => (mults && mults[key] != null ? `${mults[key]}×` : '—');
const _rgFromDate = (days) => {
  if (!days) return '';
  const d = new Date(Date.now() - days * 86400000);
  return d.toISOString().slice(0, 10);
};
const _rgRel = (iso, nowMs) => {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '—';
  const diff = Math.max(0, Math.floor((nowMs - t) / 1000));
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// The 6 REAL engine signals (core.regime_classifier.ALL_SIGNALS) with the
// presentation map. Threshold VALUES come from /api/regime/thresholds; only
// the color/label pairing is client-side.
const _rgThr = (v, c, l) => (v == null ? null : { v, c, l });
const RG_SIGNALS = [
  { key: 'vix_close', label: 'VIX', unit: '', color: 'var(--qe-red)', decimals: 1,
    thr: (t) => [_rgThr(t.vix_panic, 'var(--qe-red)', 'Panic'), _rgThr(t.vix_defensive, 'var(--qe-amber)', 'Def'), _rgThr(t.vix_risk_on, 'var(--qe-green)', 'Risk-On')] },
  { key: 'us10y_yield', label: 'US 10Y Yield', unit: '%', color: 'var(--qe-blue)', decimals: 2, thr: () => [] },
  { key: 'hy_spread', label: 'HY Spread', unit: '%', color: 'var(--qe-amber)', decimals: 2,
    thr: (t) => [_rgThr(t.hy_spread_panic, 'var(--qe-red)', 'Panic'), _rgThr(t.hy_spread_defensive, 'var(--qe-amber)', 'Def'), _rgThr(t.hy_spread_risk_on, 'var(--qe-green)', 'Risk-On')] },
  { key: 'btc_rvol_ratio', label: 'BTC RVol (30d/7d)', unit: '', color: 'var(--qe-purple)', decimals: 2,
    thr: (t) => [_rgThr(t.rvol_ratio_choppy, 'var(--qe-amber)', 'Chop'), _rgThr(t.rvol_ratio_trending, 'var(--qe-green)', 'Trend')] },
  { key: 'agg_oi_change', label: 'Aggregate OI Change', unit: '%', color: 'var(--qe-green)', decimals: 2,
    thr: () => [{ v: 0, c: 'var(--qe-muted)', l: 'Zero' }] },
  { key: 'avg_funding', label: 'Avg Funding Rate', unit: '', color: 'var(--qe-cyan)', decimals: 5,
    thr: (t) => [{ v: 0, c: 'var(--qe-muted)', l: 'Zero' }, _rgThr(t.funding_panic, 'var(--qe-red)', 'Panic')] },
];
const _rgSigThr = (sig, thresholds) => (thresholds ? sig.thr(thresholds).filter(Boolean) : []);

const RG_THRESHOLD_LABELS = {
  vix_panic: 'VIX Panic', vix_defensive: 'VIX Defensive', vix_risk_on: 'VIX Risk-On', vix_choppy: 'VIX Choppy',
  hy_spread_panic: 'HY Spread Panic', hy_spread_defensive: 'HY Spread Defensive', hy_spread_neutral: 'HY Spread Neutral', hy_spread_risk_on: 'HY Spread Risk-On',
  rvol_ratio_choppy: 'RVol Choppy', rvol_ratio_trending: 'RVol Trending',
  funding_panic: 'Funding Panic',
  btc_dom_change_bull: 'BTC Dom Bull', btc_dom_change_bear: 'BTC Dom Bear',
};

/* JSON POST helper (backfill/reclassify take JSON bodies; news/refresh none).
   NEVER rejects — an unreachable engine returns {ok:false,status:0} so busy
   states always resolve (audit M1: the P2 idiom; Jinja wrapped all three). */
/* Backfill-status poll cadence — one literal, feeding both the scheduler and
   the read deadline derived from it (warm-hang sweep, 2026-08-01). The "4
   consecutive failures ≈ 6 s" terminal rule below counts on this number, and
   a hung status read used to stall that counter indefinitely with Start
   disabled — the job never resolved either way. */
const RG_BACKFILL_MS = 1500;

const _rgPost = async (url, body) => {
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: body != null ? { 'Content-Type': 'application/json' } : {},
      body: body != null ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await r.json(); } catch (e) { /* non-JSON error body */ }
    return { ok: r.ok, status: r.status, data };
  } catch (e) {
    return { ok: false, status: 0, data: null };
  }
};

/* ── Timeline — ECharts, 5 styles (swim · bars · blocks · heat · stack) ──── */
const _regimeSegs = (data) => {
  const segs = []; let cur = { label: data[0].label, start: 0, days: 1 };
  for (let i = 1; i < data.length; i++) {
    if (data[i].label === cur.label) cur.days++;
    else { segs.push(cur); cur = { label: data[i].label, start: i, days: 1 }; }
  }
  segs.push(cur);
  return segs;
};
const _fmtDay = (data, i) => (data[i] && data[i].date) ? data[i].date : `#${i}`;

const TimelineSvg = ({ data, style = 'swim' }) => {
  const ref = React.useRef(null);
  const empty = !data || !data.length;
  const n = empty ? 0 : data.length;

  const { opts, height } = React.useMemo(() => {
    if (empty) return { opts: null, height: 120 };
    const muted = QE_ECHARTS_THEME.muted, sub = QE_ECHARTS_THEME.sub, line = QE_ECHARTS_THEME.line;
    const segs = _regimeSegs(data);
    const tip = {
      trigger: 'item', backgroundColor: QE_ECHARTS_THEME.bg, borderColor: QE_ECHARTS_THEME.cyan, borderWidth: 1, padding: [4, 8],
      textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
      formatter: (p) => (p.data && p.data._meta ? p.data._meta : ''),
    };

    // Out-of-set labels must degrade, not throw (audit M3 — Jinja guarded):
    const infoOf = (l) => REGIME_INFO[l] || { label: l, short: String(l).slice(0, 5).toUpperCase(), color: 'var(--qe-sub)' };
    const hexOf = (l) => REGIME_HEX[l] || QE_ECHARTS_THEME.sub;

    if (style === 'swim') {
      const lanes = REGIME_KEYS;
      const bgItems = lanes.map((r, li) => ({ value: [0, n, li], itemStyle: { color: REGIME_HEX[r], opacity: 0.07 } }));
      const segItems = segs
        .filter((s) => lanes.indexOf(s.label) >= 0)
        .map((s) => ({
          value: [s.start, s.start + s.days, lanes.indexOf(s.label)],
          itemStyle: { color: hexOf(s.label), opacity: 0.92 },
          _meta: `${infoOf(s.label).label} · ${s.days}d · ${_fmtDay(data, s.start)} → ${_fmtDay(data, Math.min(s.start + s.days - 1, n - 1))}`,
        }));
      const swimRect = (frac) => (params, api) => {
        const x0 = api.coord([api.value(0), api.value(2)]);
        const x1 = api.coord([api.value(1), api.value(2)]);
        const bandH = api.size([0, 1])[1];
        const h = Math.max(bandH * frac, 2);
        return { type: 'rect', shape: { x: x0[0], y: x0[1] - h / 2, width: Math.max(x1[0] - x0[0], 1), height: h }, style: api.style() };
      };
      return {
        height: lanes.length * 18 + 12,
        opts: {
          backgroundColor: 'transparent', animation: false,
          grid: { left: 54, right: 10, top: 6, bottom: 6 },
          tooltip: tip,
          xAxis: { type: 'value', min: 0, max: n, show: false },
          yAxis: { type: 'category', inverse: true, data: lanes.map((r) => REGIME_INFO[r].short),
            axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
            axisLabel: { color: (val, idx) => REGIME_HEX[lanes[idx]], fontSize: 9, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' } },
          series: [
            { type: 'custom', silent: true, z: 1, renderItem: swimRect(0.86), encode: { x: [0, 1], y: 2 }, data: bgItems },
            { type: 'custom', z: 2, renderItem: swimRect(0.86), encode: { x: [0, 1], y: 2 }, data: segItems },
          ],
        },
      };
    }

    if (style === 'bars') {
      const items = data.map((d, i) => ({ value: [i, i + 1, 0], itemStyle: { color: hexOf(d.label), opacity: 0.92 },
        _meta: `${infoOf(d.label).label} · ${d.date || ('#' + i)}` }));
      return {
        height: 56,
        opts: {
          backgroundColor: 'transparent', animation: false,
          grid: { left: 10, right: 10, top: 8, bottom: 8 },
          tooltip: tip,
          xAxis: { type: 'value', min: 0, max: n, show: false },
          yAxis: { type: 'category', data: [''], show: false },
          series: [{ type: 'custom',
            renderItem: (params, api) => {
              const x0 = api.coord([api.value(0), 0]);
              const x1 = api.coord([api.value(1), 0]);
              const bandH = api.size([0, 1])[1];
              return { type: 'rect', shape: { x: x0[0], y: x0[1] - bandH * 0.42, width: Math.max(x1[0] - x0[0], 0.6), height: bandH * 0.84 }, style: api.style() };
            },
            encode: { x: [0, 1], y: 2 }, data: items }],
        },
      };
    }

    if (style === 'blocks') {
      const items = segs.map((s) => ({ value: [s.start, s.start + s.days, 0],
        itemStyle: { color: hexOf(s.label), opacity: 0.9 },
        _label: s.days > 6 ? `${infoOf(s.label).short} ${s.days}d` : infoOf(s.label).short,
        _meta: `${infoOf(s.label).label} · ${s.days}d · ${_fmtDay(data, s.start)} → ${_fmtDay(data, Math.min(s.start + s.days - 1, n - 1))}` }));
      return {
        height: 52,
        opts: {
          backgroundColor: 'transparent', animation: false,
          grid: { left: 10, right: 10, top: 8, bottom: 8 },
          tooltip: tip,
          xAxis: { type: 'value', min: 0, max: n, show: false },
          yAxis: { type: 'category', data: [''], show: false },
          series: [{ type: 'custom',
            renderItem: (params, api) => {
              const x0 = api.coord([api.value(0), 0]);
              const x1 = api.coord([api.value(1), 0]);
              const bandH = api.size([0, 1])[1];
              const w = Math.max(x1[0] - x0[0], 1);
              const rect = { type: 'rect', shape: { x: x0[0] + 0.5, y: x0[1] - bandH * 0.45, width: Math.max(w - 1, 0.6), height: bandH * 0.9 }, style: api.style() };
              const lbl = params.data && params.data._label;
              if (w > 42 && lbl) {
                return { type: 'group', children: [rect, { type: 'text',
                  style: { text: lbl, x: x0[0] + w / 2, y: x0[1], fill: QE_ECHARTS_THEME.bg, opacity: 0.6,
                    font: '700 9px JetBrains Mono, monospace', textAlign: 'center', textVerticalAlign: 'middle' } }] };
              }
              return rect;
            },
            encode: { x: [0, 1], y: 2 }, data: items }],
        },
      };
    }

    if (style === 'heat') {
      const cells = data.map((d) => [d.date, REGIME_KEYS.indexOf(d.label)]);
      return {
        height: 132,
        opts: {
          backgroundColor: 'transparent', animation: false,
          tooltip: { ...tip, formatter: (p) => { const k = REGIME_KEYS[p.data[1]]; return `${p.data[0]}\n${(REGIME_INFO[k] || {}).label || '—'}`; } },
          visualMap: { show: false, type: 'piecewise', dimension: 1, seriesIndex: 0,
            pieces: REGIME_KEYS.map((r, i) => ({ value: i, color: REGIME_HEX[r] })) },
          calendar: { top: 24, left: 34, right: 10, bottom: 6, cellSize: ['auto', 15],
            range: [data[0].date, data[n - 1].date],
            orient: 'horizontal',
            itemStyle: { color: QE_ECHARTS_THEME.bg, borderColor: QE_ECHARTS_THEME.bg, borderWidth: 1.5 },
            dayLabel: { color: muted, fontSize: 8, fontFamily: 'JetBrains Mono, monospace', firstDay: 1 },
            monthLabel: { color: sub, fontSize: 9, fontFamily: 'JetBrains Mono, monospace' },
            yearLabel: { show: false },
            splitLine: { lineStyle: { color: line, width: 1 } } },
          series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: cells,
            itemStyle: { borderColor: QE_ECHARTS_THEME.bg, borderWidth: 1.5 } }],
        },
      };
    }

    // stack — rolling 14d regime composition
    const WIN = 14, step = Math.max(1, Math.floor(n / 200));
    const buckets = [], labels = [];
    for (let bi = WIN; bi <= n; bi += step) {
      const slice = data.slice(bi - WIN, bi);
      const c = {}; REGIME_KEYS.forEach((r) => { c[r] = 0; });
      slice.forEach((d) => { if (c[d.label] != null) c[d.label]++; });
      buckets.push(c); labels.push(_fmtDay(data, bi - 1));
    }
    const series = REGIME_KEYS.map((r) => ({
      name: REGIME_INFO[r].short, type: 'line', stack: 'comp', smooth: 0.2, symbol: 'none',
      lineStyle: { width: 0 }, areaStyle: { color: REGIME_HEX[r], opacity: 0.85 },
      emphasis: { focus: 'series' },
      data: buckets.map((b) => +((b[r] / WIN) * 100).toFixed(1)),
    }));
    return {
      height: 130,
      opts: {
        backgroundColor: 'transparent', animation: false,
        grid: { left: 38, right: 10, top: 10, bottom: 20 },
        tooltip: { trigger: 'axis', backgroundColor: QE_ECHARTS_THEME.bg, borderColor: QE_ECHARTS_THEME.cyan, borderWidth: 1, padding: [6, 9],
          textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
          axisPointer: { type: 'line', lineStyle: { color: QE_ECHARTS_THEME.cyan, opacity: 0.4 } },
          formatter: (ps) => {
            const head = ps[0] ? ps[0].axisValue : '';
            const rows = ps.filter((p) => p.value > 0).reverse()
              .map((p) => `${p.marker} ${p.seriesName} ${p.value.toFixed(0)}%`).join('<br/>');
            return `${head}<br/>${rows}`;
          } },
        xAxis: { type: 'category', boundaryGap: false, data: labels,
          ..._axis({ axisLabel: { color: muted, fontSize: 9, fontFamily: 'JetBrains Mono, monospace',
            interval: Math.ceil(labels.length / 6) }, splitLine: { show: false } }) },
        yAxis: { type: 'value', min: 0, max: 100,
          ..._axis({ axisLabel: { color: muted, fontSize: 9, fontFamily: 'JetBrains Mono, monospace', formatter: (v) => v + '%' },
            splitLine: { lineStyle: { color: QE_ECHARTS_THEME.faint, opacity: 0.4, type: [2, 3] } } }) },
        series,
      },
    };
  }, [data, style, empty, n]);

  useECharts(ref, opts, [opts]);

  if (empty) {
    return <EmptyState tone="info" glyph="〇" msg="No regime data yet"
      cta={<span style={{ fontSize: '0.6rem', color: 'var(--qe-sub)', fontFamily: 'var(--qe-mono)' }}>use Backfill tab to fetch macro signals</span>} />;
  }

  const showTimeAxis = style === 'swim' || style === 'bars' || style === 'blocks';
  const padL = style === 'swim' ? 54 : 10;
  const ticks = (() => {
    if (!showTimeAxis) return [];
    const fmt = (s) => (typeof s === 'string' && s.length >= 10) ? s.slice(5) : s;
    const idxs = [0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(t * (n - 1)));
    return [...new Set(idxs)].map((i) => fmt(_fmtDay(data, i)));
  })();

  return (
    <div style={{ width: '100%' }}>
      <div ref={ref} style={{ width: '100%', height }} />
      {showTimeAxis && ticks.length > 1 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', paddingLeft: padL, paddingRight: 10, marginTop: 2,
          fontFamily: 'var(--qe-mono)', fontSize: '0.52rem', color: 'var(--qe-muted)', letterSpacing: '0.02em' }}>
          {ticks.map((t, i) => <span key={i}>{t}</span>)}
        </div>
      )}
    </div>
  );
};

const RegimeLegend = () => (
  <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontFamily: 'var(--qe-mono)' }}>
    {REGIME_KEYS.map((r) => (
      <span key={r} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.58rem' }}>
        <span style={{ width: 8, height: 8, background: REGIME_HEX[r], display: 'inline-block' }} />
        <span style={{ color: REGIME_HEX[r] }}>{REGIME_INFO[r].label}</span>
      </span>
    ))}
  </div>
);

/* ── Signal chart + card ─────────────────────────────────────────────────── */
const SignalChart = ({ data, color, thresholds = [], decimals = 2, unit = '', height = 84 }) => {
  const ref = React.useRef(null);
  const c = _qeResolveColor(color);
  const opts = React.useMemo(() => {
    const lo = Math.min(...data), hi = Math.max(...data);
    const pad = (hi - lo) * 0.6 || 1;
    const inBand = thresholds.filter((t) => t.v >= lo - pad && t.v <= hi + pad);
    return {
      backgroundColor: 'transparent', animation: false,
      grid: { left: 42, right: 8, top: 8, bottom: 6 },
      tooltip: { trigger: 'axis', backgroundColor: QE_ECHARTS_THEME.bg, borderColor: QE_ECHARTS_THEME.cyan, borderWidth: 1, padding: [3, 7],
        textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
        axisPointer: { type: 'line', lineStyle: { color: c, opacity: 0.5 } },
        formatter: (ps) => { const v = ps[0].value;
          return `${(+v).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${unit ? (' ' + unit) : ''}`; } },
      xAxis: { type: 'category', show: false, boundaryGap: false, data: data.map((_, i) => i) },
      yAxis: { type: 'value', scale: true,
        ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 8, fontFamily: 'JetBrains Mono, monospace',
          formatter: (v) => (+v).toLocaleString('en-US', { maximumFractionDigits: decimals }) },
          splitLine: { lineStyle: { color: QE_ECHARTS_THEME.faint, opacity: 0.35, type: [2, 3] } } }) },
      series: [{
        type: 'line', data, smooth: 0.18, symbol: 'none',
        lineStyle: { color: c, width: 1.4 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
          { offset: 0, color: c + '40' }, { offset: 1, color: c + '00' }] } },
        markLine: inBand.length ? {
          symbol: 'none', silent: true,
          data: inBand.map((t) => ({ yAxis: t.v,
            lineStyle: { color: _qeResolveColor(t.c), type: 'dashed', width: 1, opacity: 0.8 },
            label: { show: true, position: 'insideStartTop', formatter: t.l, color: _qeResolveColor(t.c),
              fontSize: 8, fontFamily: 'JetBrains Mono, monospace' } })),
        } : undefined,
      }],
    };
  }, [data, c, thresholds, decimals, unit]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} style={{ width: '100%', height }} />;
};

// globalSel = {v, n} — n bumps on every global click so cards re-sync even to
// the same value; a per-card override calls onOverride() to clear the global
// highlight (Task-136 precedence semantics).
const SignalCard = ({ sig, globalSel, coverageRows, thresholds, onOverride, onGoBackfill }) => {
  const [range, setRange] = React.useState(globalSel.v);
  React.useEffect(() => { setRange(globalSel.v); }, [globalSel]);
  const from = _rgFromDate(range);
  const { data, err } = useAnaJson(
    `/api/regime/signals?signal_name=${encodeURIComponent(sig.key)}${from ? `&from_date=${from}` : ''}`);
  // coverageRows === null → still loading (indeterminate — audit L2: don't
  // flash the warn CTA while the discriminator is in flight)
  const covLoading = coverageRows == null;
  const covered = (coverageRows || []).some((c) => c.signal_name === sig.key && (c.count || 0) > 0);
  // memoized — unstable identities re-init all 6 ECharts canvases on every
  // parent render incl. the page's 60s current-poll (audit MED-2)
  const series = React.useMemo(
    () => (Array.isArray(data) ? data.map((d) => d.value).filter((v) => v != null) : null),
    [data]);
  const last = series && series.length ? series[series.length - 1] : null;
  const thr = React.useMemo(() => _rgSigThr(sig, thresholds), [sig, thresholds]);
  const pick = (v) => { setRange(v); onOverride(); };
  return (
    <div style={{ background: 'var(--qe-card)', border: '1px solid var(--qe-line)', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 6, height: 6, background: sig.color, display: 'inline-block' }} />
        <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--qe-text)' }}>{sig.label}</span>
        <span className="qe-mono" style={{ fontSize: '0.74rem', color: 'var(--qe-text)', fontWeight: 700, marginLeft: 4 }}>
          {last != null ? last.toLocaleString('en-US', { minimumFractionDigits: sig.decimals, maximumFractionDigits: sig.decimals }) + (sig.unit ? ' ' + sig.unit : '') : ''}
        </span>
        <span style={{ marginLeft: 'auto' }}>
          <PeriodSelector options={[[30, '30d'], [90, '90d'], [365, '1y'], [1825, '5y'], [0, 'All']]} value={range} onChange={pick} />
        </span>
      </div>
      {series == null ? (
        err
          ? <EmptyState tone="warn" glyph="⚠" msg="signal fetch failed" hint="engine unreachable?" />
          : <div style={{ height: 84, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--qe-muted)', fontSize: '0.6rem', fontFamily: 'var(--qe-mono)' }}>loading…</div>
      ) : series.length === 0 ? (
        covLoading
          ? <div style={{ height: 84, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--qe-muted)', fontSize: '0.6rem', fontFamily: 'var(--qe-mono)' }}>loading…</div>
          : covered
            ? <EmptyState tone="info" glyph="◇" msg="No data for range" hint="widen the range" />
            : <EmptyState tone="warn" glyph="∅" msg="Not yet backfilled"
                cta={<button className="qe-btn qe-btn-sm" onClick={onGoBackfill}>Use Backfill tab →</button>} />
      ) : (
        <React.Fragment>
          <SignalChart data={series} color={sig.color} thresholds={thr} decimals={sig.decimals} unit={sig.unit} height={84} />
          {thr.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: '0.54rem', fontFamily: 'var(--qe-mono)' }}>
              {thr.map((t) => (
                <span key={t.l} style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: t.c }}>
                  <span style={{ width: 8, height: 0, borderTop: `1px dashed ${t.c}`, display: 'inline-block' }} />
                  {t.l} {t.v}{sig.unit && ' ' + sig.unit}
                </span>
              ))}
            </div>
          )}
        </React.Fragment>
      )}
    </div>
  );
};

/* ── Tab: Overview ───────────────────────────────────────────────────────── */
const RegimeTabOverview = ({ current, curFoot, mults, multsFoot, onGoBackfill }) => {
  const [tlStyle, setTlStyle] = React.useState('swim');
  const [tlRange, setTlRange] = React.useState(365);
  const [globalSel, setGlobalSel] = React.useState({ v: 365, n: 0 });
  const [globalActive, setGlobalActive] = React.useState(true);
  const [selChange, setSelChange] = React.useState(null);

  const tlFrom = _rgFromDate(tlRange);
  const { data: tlData, err: tlErr, foot: tlFoot } = useAnaJson(
    `/api/regime/timeline${tlFrom ? `?from_date=${tlFrom}` : ''}`);
  const { data: coverage, foot: covFoot } = useAnaJson('/api/regime/coverage');
  const { data: thresholds } = useAnaJson('/api/regime/thresholds');

  const timeline = Array.isArray(tlData) ? tlData : [];
  const counts = {}; REGIME_KEYS.forEach((r) => { counts[r] = 0; });
  timeline.forEach((d) => { if (counts[d.label] != null) counts[d.label]++; });
  const total = timeline.length;

  // label-change rows (newest first, capped 25 — Jinja parity)
  const changes = React.useMemo(() => {
    const out = [];
    for (let i = 1; i < timeline.length; i++) {
      if (timeline[i].label !== timeline[i - 1].label) {
        out.push({ ...timeline[i], _prev: timeline[i - 1].label });
      }
    }
    return out.reverse().slice(0, 25);
  }, [timeline]);

  const curInfo = current && current.label ? (REGIME_INFO[current.label] || REGIME_INFO.neutral) : null;
  const sigOf = (row, k) => (row.signals && row.signals[k] != null ? row.signals[k] : null);
  const fmtSig = (v, d = 2, suf = '') => (v == null ? '—' : (+v).toFixed(d) + suf);
  // VIX severity coloring off the SERVER thresholds (audit L3 — hardcoded
  // 25/20 would silently drift from config)
  const t = thresholds || {};
  const vixColor = (v) => (v == null ? 'var(--qe-muted)'
    : t.vix_defensive != null && v >= t.vix_defensive ? 'var(--qe-red)'
    : t.vix_risk_on != null && v >= t.vix_risk_on ? 'var(--qe-amber)' : 'var(--qe-text)');

  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={6} h={7} minW={4} minH={4}>
        <Pane title="Current Regime" hot style={{ height: '100%' }}
          foot={curFoot}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, padding: '8px 0' }}>
            {curInfo
              ? <RegimeBadge tone={curInfo.tone} label={curInfo.label.toUpperCase()} />
              : <RegimeBadge tone="neut" label="NO DATA" />}
            <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '1.8rem', fontWeight: 700, color: curInfo ? curInfo.color : 'var(--qe-muted)', lineHeight: 1 }}>
              {current && current.multiplier != null && current.source !== 'none' ? `${current.multiplier}×` : '—'}
            </span>
            <span style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>sizing multiplier</span>
            {current && current.source === 'live' && (
              <span style={{ fontSize: '0.54rem', color: 'var(--qe-sub)', fontFamily: 'var(--qe-mono)' }}>
                {current.mode} · {current.confidence} confidence · {current.stability_bars}d stable
              </span>
            )}
            {current && current.source === 'db' && (
              <span style={{ fontSize: '0.54rem', color: 'var(--qe-sub)', fontFamily: 'var(--qe-mono)' }}>
                from stored labels · {current.date || '—'}
              </span>
            )}
          </div>
        </Pane>
      </GridItem>

      <GridItem x={6} y={0} w={12} h={7} minW={6} minH={4}>
        <Pane title="Regime Distribution" tag={tlRange === 0 ? 'ALL' : `${tlRange}d`} style={{ height: '100%' }}
          right={<span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{total} days observed</span>}
          foot={tlFoot}>
          {total === 0 ? (
            <EmptyState fill tone={tlErr ? 'warn' : 'info'} glyph="〇"
              msg={tlErr ? 'timeline fetch failed' : 'no regime labels in window'}
              hint={tlErr ? 'engine unreachable?' : 'run a backfill to classify history'} />
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 6 }}>
              {REGIME_KEYS.map((r) => {
                const c = counts[r] || 0;
                const pct = total > 0 ? (c / total) * 100 : 0;
                const info = REGIME_INFO[r];
                return (
                  <div key={r} style={{ padding: '6px 4px', background: info.bg, border: '1px solid color-mix(in srgb, ' + info.color + ' 27%, transparent)', textAlign: 'center' }}>
                    <div style={{ fontSize: '0.56rem', fontWeight: 700, color: info.color, letterSpacing: '0.08em' }}>{info.short}</div>
                    <div style={{ fontFamily: 'var(--qe-mono)', fontSize: '1rem', fontWeight: 700, color: info.color }}>{pct.toFixed(1)}%</div>
                    <div style={{ fontSize: '0.52rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{c}d</div>
                  </div>
                );
              })}
            </div>
          )}
        </Pane>
      </GridItem>

      <GridItem x={18} y={0} w={6} h={7} minW={4} minH={4}>
        <Pane title="Sizing Multipliers" style={{ height: '100%' }} foot={multsFoot}>
          <FieldList rows={REGIME_KEYS.map((r) => {
            const info = REGIME_INFO[r];
            return {
              label: info.label.replace('Risk-On ', '').replace('Risk-Off ', ''),
              value: _rgMult(mults, r),
              color: info.color,
            };
          })} />
          <div style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)', marginTop: 6 }}>
            applied to base size at calc time
          </div>
        </Pane>
      </GridItem>

      <GridItem x={0} y={7} w={24} h={8} minW={10} minH={5}>
        <Pane title="Regime Timeline" tag={tlStyle.toUpperCase()} style={{ height: '100%' }}
          right={<>
            <span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', letterSpacing: '0.08em', fontFamily: 'var(--qe-mono)' }}>STYLE</span>
            <PeriodSelector options={[['swim', 'Swim'], ['bars', 'Bars'], ['blocks', 'Blocks'], ['heat', 'Heat'], ['stack', 'Stack']]} value={tlStyle} onChange={setTlStyle} />
            <span style={{ color: 'var(--qe-muted)' }}>│</span>
            <PeriodSelector options={[[30, '30d'], [90, '90d'], [365, '1y'], [0, 'All']]} value={tlRange} onChange={setTlRange} />
          </>}
          foot={tlFoot}>
          {timeline.length === 0 && tlErr ? (
            <EmptyState fill tone="warn" glyph="⚠" msg="timeline fetch failed" hint="engine unreachable?" />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <TimelineSvg data={timeline} style={tlStyle} />
              <RegimeLegend />
            </div>
          )}
        </Pane>
      </GridItem>

      <GridItem x={0} y={15} w={24} h={10} minW={10} minH={5}>
        <Pane title="Macro Signals" count={RG_SIGNALS.length} style={{ height: '100%' }}
          right={<>
            <span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', letterSpacing: '0.08em', fontFamily: 'var(--qe-mono)' }}
              title="cards inherit the All range until individually overridden; a per-card range clears the global highlight">ALL</span>
            <PeriodSelector options={[[30, '30d'], [90, '90d'], [365, '1y'], [1825, '5y'], [0, 'All']]}
              value={globalActive ? globalSel.v : null}
              onChange={(v) => { setGlobalSel((s) => ({ v, n: s.n + 1 })); setGlobalActive(true); }} />
          </>}
          foot={covFoot}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
            {RG_SIGNALS.map((sig) => (
              <SignalCard key={sig.key} sig={sig} globalSel={globalSel}
                coverageRows={Array.isArray(coverage) ? coverage : null}
                thresholds={thresholds}
                onOverride={() => setGlobalActive(false)}
                onGoBackfill={onGoBackfill} />
            ))}
          </div>
        </Pane>
      </GridItem>

      <GridItem x={0} y={25} w={24} h={10} minW={10} minH={5}>
        <Pane title="Recent Regime Changes" count={changes.length} style={{ height: '100%' }} bodyStyle={{ padding: 0 }}
          foot={tlFoot}>
          <DataList
            selKey="date"            onClick={(r) => setSelChange((s) => (s === r.date ? null : r.date))}
            selected={selChange}
            columns={[
              { key: 'date', label: 'DATE', cell: 'dim' },
              { key: 'label', label: 'REGIME', filter: true,
                filterVal: (r) => (REGIME_INFO[r.label] || REGIME_INFO.neutral).label,
                render: (r) => { const info = REGIME_INFO[r.label] || REGIME_INFO.neutral; return <span style={{ color: info.color, fontWeight: 700 }}>{info.label}</span>; } },
              { key: 'mode', label: 'MODE', cell: 'dim', filter: true },
              // vix/hy/rvol/funding are NOT row fields — sigOf() reads the row's
              // signal map at render time, so every one of these headers sorted on
              // undefined. sortVal exposes the real number.
              { key: 'vix', label: 'VIX', align: 'right', sortVal: (r) => sigOf(r, 'vix_close'),
                render: (r) => { const v = sigOf(r, 'vix_close'); return <span style={{ color: vixColor(v) }}>{fmtSig(v, 1)}</span>; } },
              { key: 'hy', label: 'HY SPREAD', align: 'right', sortVal: (r) => sigOf(r, 'hy_spread'),
                render: (r) => fmtSig(sigOf(r, 'hy_spread'), 2, '%') },
              { key: 'rvol', label: 'RVOL', align: 'right', sortVal: (r) => sigOf(r, 'btc_rvol_ratio'),
                render: (r) => fmtSig(sigOf(r, 'btc_rvol_ratio'), 2) },
              { key: 'funding', label: 'FUNDING', align: 'right', sortVal: (r) => sigOf(r, 'avg_funding'),
                render: (r) => { const v = sigOf(r, 'avg_funding'); return v == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <span style={{ color: v >= 0 ? 'var(--qe-green)' : 'var(--qe-red)' }}>{(v * 100).toFixed(3)}%</span>; } },
            ]}
            rows={changes}
            emptyMsg="no regime transitions in window"
          />
          {selChange && (() => {
            const i = changes.findIndex((r) => r.date === selChange);
            const row = changes[i];
            if (!row) return null;
            const to = REGIME_INFO[row.label] || REGIME_INFO.neutral;
            const from = row._prev ? (REGIME_INFO[row._prev] || REGIME_INFO.neutral) : null;
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '5px 10px', borderTop: '1px solid var(--qe-line)', background: 'var(--qe-panel)', fontFamily: 'var(--qe-mono)', fontSize: '0.62rem', flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--qe-muted)', letterSpacing: '0.1em', fontSize: '0.5rem', fontWeight: 700 }}>SIGNAL CONTEXT</span>
                <span style={{ color: 'var(--qe-sub)' }}>{row.date}</span>
                <span>
                  {from && <React.Fragment><span style={{ color: from.color, fontWeight: 700 }}>{from.short}</span><span style={{ color: 'var(--qe-muted)' }}> → </span></React.Fragment>}
                  <span style={{ color: to.color, fontWeight: 700 }}>{to.short}</span>
                </span>
                <span style={{ color: 'var(--qe-muted)' }}>size {from ? <span style={{ color: from.color }}>{_rgMult(mults, row._prev)}</span> : '—'} → <span style={{ color: to.color, fontWeight: 700 }}>{_rgMult(mults, row.label)}</span></span>
                <span style={{ color: 'var(--qe-muted)' }}>VIX <span style={{ color: vixColor(sigOf(row, 'vix_close')) }}>{fmtSig(sigOf(row, 'vix_close'), 1)}</span></span>
                <span style={{ color: 'var(--qe-muted)' }}>HY <span style={{ color: 'var(--qe-text)' }}>{fmtSig(sigOf(row, 'hy_spread'), 2, '%')}</span></span>
                <span style={{ color: 'var(--qe-muted)' }}>RVOL <span style={{ color: 'var(--qe-text)' }}>{fmtSig(sigOf(row, 'btc_rvol_ratio'), 2)}</span></span>
                <span style={{ color: 'var(--qe-muted)' }}>FUND {(() => { const v = sigOf(row, 'avg_funding'); return v == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <span style={{ color: v >= 0 ? 'var(--qe-green)' : 'var(--qe-red)' }}>{(v * 100).toFixed(3)}%</span>; })()}</span>
                <span className="qe-grow" />
                <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => setSelChange(null)}>✕</button>
              </div>
            );
          })()}
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Tab: Backfill ───────────────────────────────────────────────────────── */
// Expected source per signal for synthesized pending rows (Jinja parity —
// audit M6b: /api/regime/coverage GROUP-BYs EXISTING rows, so an un-backfilled
// signal never appears and count can never be 0; the fetch plan must render).
const RG_SIGNAL_SOURCE = {
  vix_close: 'yfinance', us10y_yield: 'FRED', hy_spread: 'FRED',
  btc_rvol_ratio: 'derived', agg_oi_change: 'Binance', avg_funding: 'Binance',
};

// job state + poll live in RegimePage (audit M6a) so a sub-tab switch doesn't
// orphan a running server job; this tab only renders + starts.
const RegimeTabBackfill = ({ job, onStart }) => {
  const [mode, setMode] = React.useState('macro_only');
  const [since, setSince] = React.useState('2020-01-01');
  const [until, setUntil] = React.useState(() => new Date().toISOString().slice(0, 10));
  const { data: coverage, err: covErr, reload: reloadCoverage, foot: covFoot } = useAnaJson('/api/regime/coverage');

  // refresh coverage the moment the (page-owned) job completes while this
  // tab is mounted; a later remount refetches on mount anyway.
  const jobStatus = job && job.status;
  React.useEffect(() => {
    if (jobStatus === 'completed') reloadCoverage();
  }, [jobStatus, reloadCoverage]);

  const running = job && (job.status === 'running' || job.status === 'starting');
  const results = job && job.results;
  const srvRows = Array.isArray(coverage) ? coverage : [];
  const covRows = srvRows.concat(
    RG_SIGNALS.filter((s) => !srvRows.some((r) => r.signal_name === s.key))
      .map((s) => ({ signal_name: s.key, source: RG_SIGNAL_SOURCE[s.key] || '—',
                     min_date: null, max_date: null, count: 0 })));
  const labelOf = (key) => { const s = RG_SIGNALS.find((x) => x.key === key); return s ? s.label : key; };

  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={8} h={14} minW={5} minH={6}>
        <Pane title="Backfill Macro Data" style={{ height: '100%' }}
          foot={!job ? { tone: 'ok', msg: 'local' }
            : (job.status === 'starting' || job.status === 'running')
              ? { tone: 'sub', busy: true, msg: `backfill ${Math.round(job.pct || 0)}%` }
              : job.status === 'failed'
                ? { tone: 'err', msg: job.detail || 'backfill failed' }
                : { tone: 'ok', msg: 'backfill completed' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <p style={{ fontSize: '0.62rem', color: 'var(--qe-sub)', lineHeight: 1.5, margin: 0 }}>
              Macro Only fetches VIX (yfinance) + yields/spreads (FRED) + derives BTC RVol — works for deep
              history. Full additionally classifies with any existing Binance OI/funding rows; those crypto
              series are refreshed by the engine scheduler, not this fetch.
            </p>
            <div>
              <Lbl>Mode</Lbl>
              <select className="qe-input qe-select" value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="macro_only">Macro Only · VIX · FRED · RVol</option>
                <option value="full">Full · + existing OI / funding rows</option>
              </select>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              <div><Lbl>From</Lbl><input type="date" className="qe-input" value={since} onChange={(e) => setSince(e.target.value)} /></div>
              <div><Lbl>To</Lbl><input type="date" className="qe-input" value={until} onChange={(e) => setUntil(e.target.value)} /></div>
            </div>
            <button className="qe-btn qe-btn-primary qe-btn-lg" style={{ width: '100%', justifyContent: 'center' }}
              disabled={running} onClick={() => onStart({ mode, since, until })}>
              {running ? <Spinner size="0.7rem" /> : '▶ Start Backfill'}
            </button>

            {job && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.6rem', fontFamily: 'var(--qe-mono)' }}>
                  <span style={{ color: job.status === 'failed' ? 'var(--qe-red)' : 'var(--qe-sub)' }}>
                    {job.status === 'failed' ? 'Backfill failed — data unchanged' : (job.detail || job.status)}
                  </span>
                  <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{Math.round(job.pct || 0)}%</span>
                </div>
                {/* FE-MED-031 idiom: friendly first line, dim diagnostic second */}
                {job.status === 'failed' && job.detail && (
                  <div style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{job.detail}</div>
                )}
                <div style={{ height: 4, background: 'var(--qe-panel)', border: '1px solid var(--qe-line)' }}>
                  <div style={{ width: `${Math.max(0, Math.min(100, job.pct || 0))}%`, height: '100%', background: job.status === 'failed' ? 'var(--qe-red)' : 'var(--qe-cyan)' }} />
                </div>
                {job.status === 'completed' && results && (
                  <div style={{ fontSize: '0.58rem', color: 'var(--qe-green)', fontFamily: 'var(--qe-mono)', lineHeight: 1.6 }}>
                    done — {Object.entries(results).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                  </div>
                )}
              </div>
            )}
          </div>
        </Pane>
      </GridItem>

      <GridItem x={8} y={0} w={16} h={20} minW={8} minH={6}>
        <Pane title="Signal Coverage" count={covRows.length} style={{ height: '100%' }}
          right={<button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={reloadCoverage}>↻</button>}
          bodyStyle={{ padding: 0 }}
          foot={covFoot}>
          {covErr && srvRows.length === 0 ? (
            <EmptyState fill tone="warn" glyph="⚠" msg="coverage fetch failed" hint="engine unreachable?" />
          ) : (
            <DataList
              selKey="signal_name"              columns={[
                { key: 'signal_name', label: 'SIGNAL', render: (r) => <span style={{ color: (r.count || 0) > 0 ? 'var(--qe-text)' : 'var(--qe-sub)', fontWeight: 600 }}>{labelOf(r.signal_name)}</span> },
                { key: 'source', label: 'SOURCE', cell: 'dim', filter: true,
                  filterVal: (r) => String(r.source || '—').toUpperCase() },
                { key: 'min_date', label: 'FROM', cell: 'dim', render: (r) => r.min_date || <span style={{ color: 'var(--qe-muted)' }}>—</span> },
                { key: 'max_date', label: 'TO', cell: 'dim', render: (r) => r.max_date || <span style={{ color: 'var(--qe-muted)' }}>—</span> },
                { key: 'count', label: 'ROWS', align: 'right', render: (r) => (r.count || 0) > 0
                  ? <span style={{ color: 'var(--qe-green)', fontWeight: 700 }}>{(+r.count).toLocaleString()}</span>
                  : <Badge tone="warn">NOT BACKFILLED</Badge> },
              ]}
              rows={covRows}
            />
          )}
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Tab: News ───────────────────────────────────────────────────────────── */
const NEWS_SRC_STYLE = {
  finnhub: { color: 'var(--qe-blue)', background: 'var(--qe-bg-blue)' },
  bwe:     { color: 'var(--qe-amber)', background: 'var(--qe-bg-amber)' },
};
const IMPACT_STYLE = {
  high:   { color: 'var(--qe-red)', background: 'var(--qe-bg-red)' },
  medium: { color: 'var(--qe-amber)', background: 'var(--qe-bg-amber)' },
};
const RG_DEFAULT_PILL = { color: 'var(--qe-sub)', background: 'var(--qe-panel)' };
const srcPill = (source) => NEWS_SRC_STYLE[source] || RG_DEFAULT_PILL;
const impactPill = (impact) => IMPACT_STYLE[impact] || RG_DEFAULT_PILL;

const NewsItem = ({ n, hero = false, expanded, onClick, nowMs }) => {
  const srcStyle = srcPill(n.source);
  // engine news carries CATEGORY, not impact (db_news has no impact column) —
  // neutral chip, not the red/amber impact palette (audit L3); the impact
  // pills stay on the economic calendar, which DOES have the field.
  const catStyle = RG_DEFAULT_PILL;
  const catLbl = (n.category || 'news');
  const relTime = _rgRel(n.published_at, nowMs);
  const tickers = (n.tickers || '').split(',').map((t) => t.trim()).filter(Boolean);
  const openLink = n.url ? (
    <a href={n.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
      style={{ fontSize: '0.56rem', color: 'var(--qe-cyan)', fontFamily: 'var(--qe-mono)', textDecoration: 'none' }}>
      open ↗
    </a>
  ) : null;
  if (hero) {
    return (
      <div onClick={onClick} style={{
        background: 'var(--qe-card)',
        border: `1px solid ${expanded ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
        padding: '12px 14px', cursor: 'pointer',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <span style={{ ...srcStyle, padding: '1px 6px', fontSize: '0.56rem', fontWeight: 700, letterSpacing: '0.06em', fontFamily: 'var(--qe-mono)' }}>{(n.source || '?').toUpperCase()}</span>
          <Badge tone="info">TOP STORY</Badge>
          <span style={{ ...catStyle, padding: '1px 6px', fontSize: '0.54rem', fontWeight: 700, fontFamily: 'var(--qe-mono)' }}>{catLbl.toUpperCase()}</span>
          <span style={{ marginLeft: 'auto', fontSize: '0.58rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{relTime}</span>
        </div>
        <h2 style={{ fontSize: '0.94rem', fontWeight: 800, color: 'var(--qe-text)', lineHeight: 1.35, marginBottom: 6, fontFamily: 'var(--qe-ui)', letterSpacing: '-0.01em' }}>{n.headline}</h2>
        {n.summary ? <p style={{ fontSize: '0.7rem', color: 'var(--qe-sub)', lineHeight: 1.6, margin: 0 }}>{n.summary}</p> : null}
        {expanded && tickers.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
            {tickers.map((t) => (
              <span key={t} style={{ padding: '1px 6px', fontFamily: 'var(--qe-mono)', fontSize: '0.56rem', background: 'var(--qe-panel)', border: '1px solid var(--qe-line)', color: 'var(--qe-sub)' }}>{t}</span>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: 10, marginTop: 6, alignItems: 'baseline' }}>
          <span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{expanded ? '▲ Collapse' : '▼ Expand'}</span>
          {expanded && openLink}
        </div>
      </div>
    );
  }
  return (
    <div onClick={onClick} style={{
      background: 'var(--qe-card)',
      border: `1px solid ${expanded ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
      padding: expanded ? '10px 12px' : '6px 10px',
      cursor: 'pointer',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <span style={{ ...srcStyle, padding: '1px 5px', fontSize: '0.5rem', fontWeight: 700, letterSpacing: '0.06em', fontFamily: 'var(--qe-mono)', flexShrink: 0 }}>{(n.source || '?').toUpperCase()}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: expanded ? '0.74rem' : '0.68rem', fontWeight: expanded ? 700 : 600, color: 'var(--qe-text)', lineHeight: 1.4 }}>{n.headline}</div>
          {expanded && n.summary ? <p style={{ fontSize: '0.66rem', color: 'var(--qe-sub)', lineHeight: 1.6, margin: '6px 0 0 0' }}>{n.summary}</p> : null}
          {expanded && (tickers.length > 0 || openLink) && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6, alignItems: 'baseline' }}>
              {tickers.map((t) => (
                <span key={t} style={{ padding: '1px 5px', fontFamily: 'var(--qe-mono)', fontSize: '0.54rem', background: 'var(--qe-panel)', border: '1px solid var(--qe-line)', color: 'var(--qe-sub)' }}>{t}</span>
              ))}
              {openLink}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3, flexShrink: 0 }}>
          <span style={{ ...catStyle, padding: '1px 5px', fontSize: '0.5rem', fontWeight: 700, fontFamily: 'var(--qe-mono)' }}>{catLbl.toUpperCase()}</span>
          <span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)', whiteSpace: 'nowrap' }}>{relTime}</span>
        </div>
      </div>
    </div>
  );
};

const RegimeTabNews = () => {
  const [expanded, setExpanded] = React.useState(null);
  const [newsView, setNewsView] = React.useState('magazine');
  const [calFilter, setCalFilter] = React.useState('');       // '' | 'high' | 'high,medium'
  const [refreshMsg, setRefreshMsg] = React.useState(null);
  const [, setTick] = React.useState(0);                       // 60s rel-time re-render

  // "last fetch" in words. A raw '2026-06-09 06:12:45' does not read as
  // ALARMING; "59d ago" does, and that is the whole point of showing it.
  const _calRel = (ts) => {
    if (!ts) return 'never';
    const ms = Date.parse(String(ts).replace(' ', 'T') + (String(ts).endsWith('Z') ? '' : 'Z'));
    if (!Number.isFinite(ms)) return String(ts);
    const mins = Math.floor((Date.now() - ms) / 60000);
    if (mins < 2) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
    return `${Math.floor(mins / 1440)}d ago`;
  };

  const [calUrl] = React.useState(() => {
    const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
    return `/api/calendar?from_date=${iso(Date.now() - 30 * 86400000)}&to_date=${iso(Date.now() + 30 * 86400000)}`;
  });
  const { data: feedData, err: feedErr, reload: reloadFeed, foot: feedFoot } = useAnaJson('/api/news/feed?limit=80', 15_000);
  // `err: calErr` was NOT destructured here until 2026-08-07 — the calendar
  // threw its error state away, which is the root of the whole defect below.
  const { data: calData, err: calErr, reload: reloadCal, foot: calFoot } = useAnaJson(calUrl, 60_000);
  React.useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 60_000); return () => clearInterval(t); }, []);

  const nowMs = Date.now();
  const news = Array.isArray(feedData) ? feedData : [];
  // /api/calendar returns an ENVELOPE now ({events, meta}) — a bare array
  // could not distinguish "nothing scheduled" from "the feed stopped writing
  // two months ago", and the pane spent that whole time asserting the former.
  const calAll = (calData && Array.isArray(calData.events)) ? calData.events : [];
  const calMeta = (calData && calData.meta) || {};
  // Has a response with a real envelope ARRIVED? Distinguishes "not answered
  // yet / old shape" from "answered, and the store is genuinely empty" —
  // without it `calMeta.stored_total === 0` is `undefined === 0` = false on
  // first mount and the pane falls through to the stale-window branch.
  const calHasMeta = typeof calMeta.stored_total === 'number';
  const cal = calFilter ? calAll.filter((e) => calFilter.split(',').includes(e.impact)) : calAll;

  const refresh = async () => {
    setRefreshMsg('refreshing…');
    const r = await _rgPost('/api/news/refresh');
    if (r.ok && r.data) {
      setRefreshMsg(`+${r.data.news_added || 0} news · +${r.data.calendar_added || 0} events`);
      reloadFeed(); reloadCal();
    } else {
      setRefreshMsg(r.status ? `refresh failed (HTTP ${r.status})` : 'refresh failed — engine unreachable?');
    }
  };
  // auto-clear the refresh status line (audit N5 — Jinja toasts auto-dismissed)
  React.useEffect(() => {
    if (!refreshMsg || refreshMsg === 'refreshing…') return undefined;
    const t = setTimeout(() => setRefreshMsg(null), 6000);
    return () => clearTimeout(t);
  }, [refreshMsg]);

  // scroll the calendar to the NOW marker on mount + filter change (audit M5
  // — Jinja parity; ±30d ASC puts the marker mid-list)
  const nowRef = React.useRef(null);
  const calReady = cal.length > 0;
  React.useEffect(() => {
    if (nowRef.current) {
      try { nowRef.current.scrollIntoView({ block: 'center' }); } catch (e) { /* older engines */ }
    }
  }, [calReady, calFilter]);

  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={16} h={24} minW={8} minH={8}>
        <Pane title="Market News" count={news.length} style={{ height: '100%' }}
          right={<>
            {refreshMsg && <span style={{ fontSize: '0.54rem', color: 'var(--qe-sub)', fontFamily: 'var(--qe-mono)' }}>{refreshMsg}</span>}
            <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={refresh}>↻</button>
            <PeriodSelector options={[['magazine', 'Magazine'], ['detail', 'Detail']]} value={newsView} onChange={setNewsView} />
            {feedErr ? <StatusDot tone="warn" label="STALE — retrying" /> : <StatusDot tone="info" label="15s refresh" />}
          </>}
          bodyStyle={{ padding: newsView === 'magazine' ? 6 : 0 }}
          foot={feedFoot}>
          {news.length === 0 ? (
            <EmptyState fill tone={feedErr ? 'warn' : 'info'} glyph="📰"
              msg={feedErr ? 'news fetch failed' : 'no news items stored yet'}
              hint={feedErr ? 'engine unreachable?' : 'press ↻ to fetch from finnhub (needs an API key in Connections)'} />
          ) : newsView === 'magazine' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <NewsItem n={news[0]} hero nowMs={nowMs} expanded={expanded === news[0].id}
                onClick={() => setExpanded(expanded === news[0].id ? null : news[0].id)} />
              {news.slice(1).map((n) => (
                <NewsItem key={n.id} n={n} nowMs={nowMs} expanded={expanded === n.id}
                  onClick={() => setExpanded(expanded === n.id ? null : n.id)} />
              ))}
            </div>
          ) : (
            <DataList
              selKey="id" dense              onClick={(n) => { setNewsView('magazine'); setExpanded(n.id); }}
              columns={[
                { key: 'published_at', label: 'TIME', cell: 'dim', render: (n) => _rgRel(n.published_at, nowMs) },
                { key: 'source', label: 'SRC', filter: true,
                  filterVal: (n) => (n.source || '?').toUpperCase(),
                  render: (n) => <span style={{ ...srcPill(n.source), padding: '1px 5px', fontSize: '0.5rem', fontWeight: 700, fontFamily: 'var(--qe-mono)', letterSpacing: '0.06em' }}>{(n.source || '?').toUpperCase()}</span> },
                // The engine's news rows carry CATEGORY (not impact — see the
                // Magazine cards, which already render it). Surfacing it as a
                // column gives this pane a second, genuinely categorical facet.
                { key: 'category', label: 'CAT', cell: 'dim', filter: true,
                  filterVal: (n) => (n.category || 'news').toUpperCase(),
                  render: (n) => <span style={{ fontSize: '0.52rem', color: 'var(--qe-sub)', fontFamily: 'var(--qe-mono)', letterSpacing: '0.05em' }}>{(n.category || 'news').toUpperCase()}</span> },
                { key: 'headline', label: 'HEADLINE', render: (n) => <span style={{ color: 'var(--qe-text)', fontWeight: 600 }}>{n.headline}</span> },
                { key: 'tickers', label: 'TICKERS', cell: 'dim', render: (n) => <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.56rem' }}>{n.tickers || '—'}</span> },
              ]}
              rows={news}
            />
          )}
        </Pane>
      </GridItem>

      <GridItem x={16} y={0} w={8} h={24} minW={6} minH={8}>
        <Pane title="Economic Calendar" count={cal.length} style={{ height: '100%' }} tag="NOW MARKER"
          right={<>
            <PeriodSelector options={[['', 'All'], ['high', 'High'], ['high,medium', 'High+Med']]} value={calFilter} onChange={setCalFilter} />
            {/* Standing provenance: what this calendar IS, always on screen.
                `qe-badge` is load-bearing, not cosmetic — e2e's headTitle()
                (e2e/lib/inpage.ts) derives each pane's CONTROL ID from its
                head text and strips `.qe-badge`. A bare span would rename the
                pane 'economic calendar us fred - - utc' and orphan all four
                of its registered control ids in e2e/manifest/controls.json. */}
            <span className="qe-badge qe-mono" style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', letterSpacing: '0.08em' }}>US · FRED</span>
            <LiveClock id="regime-news-clock" style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }} />
          </>}
          bodyStyle={{ padding: 6 }}
          foot={calFoot}>
          {/* FOUR states, because "empty" had four different causes and the
              pane asserted the same wrong one for all of them. It rendered
              "no calendar events stored" while 6,278 events WERE stored —
              just none inside the ±30d window, because the provider had been
              answering 403 since June. DESIGN.md: an affirmative WRONG signal
              is worse than no signal. */}
          {calErr && calAll.length === 0 ? (
            <EmptyState fill tone="err" glyph="✗" msg="calendar feed unavailable"
              hint={qeFootCause(calErr)}
              cta={<button className="qe-btn qe-btn-sm" onClick={reloadCal}>Retry</button>} />
          ) : calAll.length === 0 && !calHasMeta ? (
            /* Nothing has ANSWERED yet (first mount, or a response without the
               envelope — e.g. a service-worker replay of the old bare-array
               shape). Saying anything about the store here would be a claim we
               cannot support: the pre-fix version rendered "undefined stored ·
               last fetch never" on every single page load, which is the same
               affirmative-wrong-signal class the rest of this pane fixes. */
            <EmptyState fill tone="info" glyph="◫" msg="loading calendar…" />
          ) : calAll.length === 0 && calMeta.stored_total === 0 ? (
            <EmptyState fill tone="info" glyph="◫" msg="no calendar events stored"
              hint="US releases via FRED — check the FRED key in Config ▸ Connections" />
          ) : calAll.length === 0 ? (
            <EmptyState fill tone="warn" glyph="◫" msg="no events in this ±30d window"
              hint={`${calMeta.stored_total} stored · last fetch ${_calRel(calMeta.last_fetch)} · ${calMeta.coverage || 'US releases via FRED'}`} />
          ) : cal.length === 0 ? (
            <EmptyState fill tone="info" glyph="◫"
              msg={`no ${calFilter === 'high' ? 'high' : 'high or medium'}-impact events in this window`}
              hint={`${calAll.length} events of all impacts — clear the filter to see them`} />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {(() => {
                const out = [];
                let nowInserted = false;
                const marker = (
                  <div key="now-marker" ref={nowRef} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0' }}>
                    <hr style={{ flex: 1, border: 'none', borderTop: '1px solid var(--qe-cyan)', opacity: 0.5 }} />
                    <span style={{ fontSize: '0.54rem', fontWeight: 700, color: 'var(--qe-cyan)', letterSpacing: '0.12em', fontFamily: 'var(--qe-mono)' }}>● NOW</span>
                    <hr style={{ flex: 1, border: 'none', borderTop: '1px solid var(--qe-cyan)', opacity: 0.5 }} />
                  </div>
                );
                cal.forEach((e, i) => {
                  const evMs = Date.parse(e.event_time);
                  if (!nowInserted && Number.isFinite(evMs) && evMs >= nowMs) {
                    nowInserted = true;
                    out.push(marker);
                  }
                  const isPast = Number.isFinite(evMs) && evMs < nowMs;
                  const minsAway = Number.isFinite(evMs) ? Math.round((evMs - nowMs) / 60000) : 0;
                  const isNear = !isPast && Math.abs(minsAway) <= 240;
                  const timeLbl = !Number.isFinite(evMs) ? '—'
                    : isPast
                      ? (minsAway < -60 ? `${Math.round(-minsAway / 60)}h ago` : `${-minsAway}m ago`)
                      : (minsAway < 60 ? `in ${minsAway}m` : `in ${Math.round(minsAway / 60)}h`);
                  const est = e.estimate, act = e.actual;
                  const surprise = act != null && est != null && Math.abs(+est) > 0 ? Math.abs(act - est) / Math.abs(est) : 0;
                  const actColor = act == null ? 'var(--qe-sub)' : surprise > 0.10 ? (act > est ? 'var(--qe-green)' : 'var(--qe-red)') : 'var(--qe-text)';
                  // Jinja fmtNum parity (audit N6): 2dp, exponential for tiny
                  const fmtNum = (v) => (v == null ? '—'
                    : (Math.abs(+v) > 0 && Math.abs(+v) < 0.01) ? (+v).toExponential(1) : (+v).toFixed(2));
                  const impactStyle = impactPill(e.impact);
                  out.push(
                    <div key={e.id != null ? e.id : i} style={{
                      padding: '5px 7px',
                      /* rgba amber near-wash — the tint carve-out (DESIGN.md §2) */
                      background: isNear ? 'rgba(255,174,0,0.06)' : 'var(--qe-panel)',
                      border: `1px solid ${isNear ? 'color-mix(in srgb, var(--qe-amber) 50%, transparent)' : 'var(--qe-line)'}`,
                      opacity: isPast ? 0.55 : 1,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 3 }}>
                        <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.58rem', color: isNear ? 'var(--qe-amber)' : 'var(--qe-muted)', fontWeight: 700 }}>{timeLbl}</span>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{e.country || '—'}</span>
                          <span style={{ ...impactStyle, padding: '1px 4px', fontSize: '0.5rem', fontWeight: 700, fontFamily: 'var(--qe-mono)' }}>{e.impact === 'medium' ? 'MED' : (e.impact || '?').toUpperCase()}</span>
                        </span>
                      </div>
                      <div style={{ fontSize: '0.66rem', fontWeight: 600, color: isPast ? 'var(--qe-sub)' : 'var(--qe-text)', lineHeight: 1.3, marginBottom: 3 }}>
                        {e.event_name}{e.unit ? <span style={{ color: 'var(--qe-muted)', fontSize: '0.56rem' }}> ({e.unit})</span> : null}
                      </div>
                      <div style={{ display: 'flex', gap: 10, fontFamily: 'var(--qe-mono)', fontSize: '0.58rem' }}>
                        <span><span style={{ color: 'var(--qe-muted)' }}>est </span><span style={{ color: 'var(--qe-sub)' }}>{fmtNum(est)}</span></span>
                        <span><span style={{ color: 'var(--qe-muted)' }}>act </span><span style={{ color: actColor, fontWeight: 700 }}>{fmtNum(act)}</span></span>
                        {e.previous != null && <span><span style={{ color: 'var(--qe-muted)' }}>prev </span><span style={{ color: 'var(--qe-sub)' }}>{fmtNum(e.previous)}</span></span>}
                      </div>
                    </div>
                  );
                });
                if (!nowInserted) out.push(marker);   // all-past window (audit N3)
                return out;
              })()}
            </div>
          )}
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Tab: Config ─────────────────────────────────────────────────────────── */
const RegimeTabConfig = ({ mults }) => {
  const { data: thresholds, err: thrErr, foot: thrFoot } = useAnaJson('/api/regime/thresholds');
  const [reclass, setReclass] = React.useState(null);   // {busy} | {msg} | {err}

  const reclassify = async () => {
    // house confirm-gate convention (P2/P4): reclassify rewrites every
    // historical regime_labels row (deterministic recompute — recoverable,
    // but a one-click full-history rewrite deserves the gate; audit L4)
    if (!window.confirm('Reclassify ALL dates? This recomputes every historical regime label from stored signals.')) return;
    setReclass({ busy: true });
    const r = await _rgPost('/api/regime/reclassify', {});
    if (r.ok && r.data) setReclass({ msg: `reclassified ${r.data.labels_classified} labels` });
    else setReclass({ err: r.status ? `failed (HTTP ${r.status})` : 'failed — engine unreachable?' });
  };

  const t = thresholds || {};
  const V = ({ k }) => (
    <span style={{ color: 'var(--qe-text)', fontWeight: 700 }}>
      {t[k] != null ? t[k] : '—'}
    </span>
  );
  // Rule copy verified against core/regime_classifier.py classify_regime
  // (audit MED-1 — the design's copy misstated three lanes):
  //  · panic needs VIX>panic AND (HY>defensive OR full-mode funding<panic);
  //    VIX>panic alone lands DEFENSIVE
  //  · both risk-on lanes are gated by HY < risk_on
  //  · full-mode trending = low VIX + leverage expanding (RVol optional);
  //    the RVol test is the MACRO-mode lane
  const rules = [
    { label: 'Panic', key: 'risk_off_panic',
      body: <>VIX &gt; <V k="vix_panic" /> AND (HY Spread &gt; <V k="hy_spread_defensive" /> OR full-mode Funding &lt; <V k="funding_panic" />)</> },
    { label: 'Defensive', key: 'risk_off_defensive',
      body: <>VIX &gt; <V k="vix_defensive" /> OR HY Spread &gt; <V k="hy_spread_defensive" /> <span style={{ color: 'var(--qe-muted)' }}>(also VIX &gt; <V k="vix_panic" /> when the panic second leg fails)</span></> },
    { label: 'Trending', key: 'risk_on_trending',
      body: <>HY &lt; <V k="hy_spread_risk_on" /> AND VIX &lt; <V k="vix_risk_on" /> AND <span style={{ color: 'var(--qe-muted)' }}>[macro:</span> RVol &lt; <V k="rvol_ratio_trending" /> <span style={{ color: 'var(--qe-muted)' }}>· full: OI rising AND funding &gt; 0]</span></> },
    { label: 'Choppy', key: 'risk_on_choppy',
      body: <>HY &lt; <V k="hy_spread_risk_on" /> AND VIX &lt; <V k="vix_choppy" /> AND RVol &gt; <V k="rvol_ratio_choppy" /></> },
    { label: 'Neutral', key: 'neutral',
      body: <span style={{ color: 'var(--qe-muted)' }}>default fallback; HY Spread ≥ <V k="hy_spread_neutral" /> floors any risk-on day to neutral</span> },
  ];

  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={8} h={18} minW={5} minH={6}>
        <Pane title="Classifier Thresholds" style={{ height: '100%' }}
          right={<button className="qe-btn qe-btn-sm" disabled={reclass && reclass.busy} onClick={reclassify}>
            {reclass && reclass.busy ? <Spinner size="0.62rem" /> : '↻ Reclassify all dates'}
          </button>}
          foot={thrFoot}>
          <p style={{ fontSize: '0.6rem', color: 'var(--qe-sub)', margin: '0 0 6px 0', lineHeight: 1.5 }}>
            Threshold values used by the rule-based classifier (config constants — read-only;
            reclassify recomputes historical labels from stored signals).
          </p>
          {reclass && reclass.msg && <div style={{ fontSize: '0.6rem', color: 'var(--qe-green)', fontFamily: 'var(--qe-mono)', marginBottom: 4 }}>{reclass.msg}</div>}
          {reclass && reclass.err && <div style={{ fontSize: '0.6rem', color: 'var(--qe-red)', fontFamily: 'var(--qe-mono)', marginBottom: 4 }}>{reclass.err}</div>}
          {thresholds == null ? (
            <div style={{ fontSize: '0.6rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{thrErr ? 'thresholds fetch failed' : 'loading…'}</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {Object.entries(thresholds).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '3px 6px', borderBottom: '1px dotted var(--qe-faint)' }}>
                  <span style={{ fontSize: '0.62rem', color: 'var(--qe-sub)' }}>{RG_THRESHOLD_LABELS[k] || k}</span>
                  <span className="qe-mono" style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--qe-text)' }}>{v}</span>
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 10 }}>
            <SecLbl rule>Sizing Multipliers</SecLbl>
            <FieldList rows={REGIME_KEYS.map((r) => ({
              label: REGIME_INFO[r].short, value: _rgMult(mults, r), color: REGIME_INFO[r].color,
            }))} dense />
          </div>
        </Pane>
      </GridItem>

      <GridItem x={8} y={0} w={16} h={18} minW={8} minH={6}>
        <Pane title="Decision Tree Rules" style={{ height: '100%' }}
          right={<span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>evaluated top→bottom · first match wins</span>}
          foot={thrFoot}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {rules.map((rule) => {
              const info = REGIME_INFO[rule.key];
              return (
                <div key={rule.key} style={{
                  background: info.bg, border: '1px solid color-mix(in srgb, ' + info.color + ' 33%, transparent)', borderLeft: `3px solid ${info.color}`,
                  padding: '7px 10px',
                }}>
                  <span style={{ color: info.color, fontWeight: 700, fontSize: '0.72rem', fontFamily: 'var(--qe-mono)' }}>{rule.label}:</span>
                  <span style={{ color: 'var(--qe-sub)', fontSize: '0.66rem', marginLeft: 6, fontFamily: 'var(--qe-mono)' }}>{rule.body}</span>
                </div>
              );
            })}
          </div>
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Page shell ──────────────────────────────────────────────────────────── */
const REGIME_TABS = [
  ['overview', 'Overview'],
  ['backfill', 'Backfill'],
  ['news', 'News'],
  ['config', 'Config'],
];

const RegimePage = () => {
  const [tab, setTab] = React.useState('overview');
  const { data: current, foot: curFoot } = useAnaJson('/api/regime/current', 60_000);
  const { data: mults, foot: multsFoot } = useAnaJson('/api/regime/multipliers');

  // Backfill job lives at PAGE level (audit M6a) — a sub-tab switch must not
  // orphan the running server job (jobs are in-memory server-side).
  const [bfJob, setBfJob] = React.useState(null);
  const bfBusyRef = React.useRef(false);
  const startBackfill = React.useCallback(async ({ mode, since, until }) => {
    if (bfBusyRef.current) return;               // double-submit guard (audit L4)
    bfBusyRef.current = true;
    setBfJob({ id: null, status: 'starting', pct: 0, detail: '' });
    const r = await _rgPost('/api/regime/backfill', { mode, since_date: since, until_date: until });
    if (!r.ok || !r.data || r.data.job_id == null) {
      bfBusyRef.current = false;
      setBfJob({ id: null, status: 'failed', pct: 0,
        detail: (r.data && (r.data.error || r.data.detail)) || (r.status ? `HTTP ${r.status}` : 'engine unreachable') });
      return;
    }
    setBfJob({ id: r.data.job_id, status: 'running', pct: 0, detail: '', fails: 0 });
  }, []);
  const bfId = bfJob && bfJob.id;
  const bfStatus = bfJob && bfJob.status;
  React.useEffect(() => {
    if (bfStatus !== 'running' || bfId == null) { bfBusyRef.current = bfStatus === 'starting'; return undefined; }
    const t = setInterval(async () => {
      try {
        const s = await _ptJson(`/api/regime/backfill-status/${bfId}`, qePollDeadline(RG_BACKFILL_MS));
        setBfJob((j) => (j && j.id === bfId ? { ...j, ...s, id: bfId, fails: 0 } : j));
      } catch (e) {
        // Jobs are in-memory server-side: a restart 404s forever. Terminal
        // after 4 consecutive failures (~6s) instead of polling into the
        // void with Start disabled (audit M2).
        setBfJob((j) => {
          if (!j || j.id !== bfId) return j;
          const fails = (j.fails || 0) + 1;
          if (fails >= 4) return { ...j, status: 'failed', fails, detail: 'job lost — engine restarted?' };
          return { ...j, fails };
        });
      }
    }, RG_BACKFILL_MS);
    return () => clearInterval(t);
  }, [bfId, bfStatus]);
  React.useEffect(() => {
    if (bfStatus === 'completed' || bfStatus === 'failed') bfBusyRef.current = false;
  }, [bfStatus]);

  const goBackfill = React.useCallback(() => setTab('backfill'), []);
  const content = {
    overview: <RegimeTabOverview current={current} curFoot={curFoot} mults={mults} multsFoot={multsFoot} onGoBackfill={goBackfill} />,
    backfill: <RegimeTabBackfill job={bfJob} onStart={startBackfill} />,
    news: <RegimeTabNews />,
    config: <RegimeTabConfig mults={mults} />,
  };
  const tabSubtitles = {
    overview: 'current regime · distribution · timeline · macro signals · changes',
    backfill: 'fetch historical macro signals · signal coverage',
    news: 'finnhub + bwe streams · economic calendar',
    config: 'classifier thresholds · decision tree rules',
  };
  const curInfo = current && current.label ? (REGIME_INFO[current.label] || REGIME_INFO.neutral) : null;
  const asOf = current
    ? (current.source === 'live' && current.computed_at ? String(current.computed_at).slice(0, 16).replace('T', ' ') + ' UTC'
      : current.source === 'db' ? `${current.date || '—'} (stored)` : null)
    : null;

  return (
    <div className="qe-scope" data-screen-label="07 Regime" style={{
      width: '100%', height: '100%', background: 'var(--qe-bg)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      <TopNavStd page="Regime" variant="line" dense />

      <PageHeader title="Regime" subtitle={tabSubtitles[tab]}>
        {curInfo
          ? <RegimeBadge tone={curInfo.tone} label={curInfo.label.toUpperCase()} />
          : <RegimeBadge tone="neut" label="NO DATA" />}
        {current && current.multiplier != null && current.source !== 'none' && (
          <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.6rem', color: 'var(--qe-cyan)', fontWeight: 700 }}>
            {current.multiplier}× size
          </span>
        )}
        {asOf && <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.54rem', color: 'var(--qe-muted)' }}>as of {asOf}</span>}
      </PageHeader>

      <TabStrip value={tab} onChange={setTab} tabs={REGIME_TABS} />

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        {content[tab]}
      </div>
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { RegimePage });
