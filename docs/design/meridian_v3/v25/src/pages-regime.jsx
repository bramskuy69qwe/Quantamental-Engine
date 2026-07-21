/* QE v2.5 — Regime page
   Mirrors templates/regime.html — 4 sub-tabs:
   Overview · Backfill · News · Config
   All built from Pane / PaneFoot / DataList primitives. */

// ─────────────────────────────────────────────────────────────────────────
// Mock data
// ─────────────────────────────────────────────────────────────────────────
const REGIME_KEYS = ['risk_on_trending','risk_on_choppy','neutral','risk_off_defensive','risk_off_panic'];
const REGIME_INFO = {
  risk_on_trending:   { label:'Risk-On Trending',   short:'TREND', tone:'trend', color:'var(--qe-green)', bg:'color-mix(in srgb, var(--qe-green) 10%, transparent)', mult:'1.2×' },
  risk_on_choppy:     { label:'Risk-On Choppy',     short:'CHOP',  tone:'chop',  color:'var(--qe-cyan)',  bg:'color-mix(in srgb, var(--qe-cyan) 10%, transparent)', mult:'0.6×' },
  neutral:            { label:'Neutral',            short:'NEUT',  tone:'neut',  color:'var(--qe-sub)',   bg:'color-mix(in srgb, var(--qe-sub) 6%, transparent)', mult:'1.0×' },
  risk_off_defensive: { label:'Risk-Off Defensive', short:'DEF',   tone:'def',   color:'var(--qe-amber)', bg:'color-mix(in srgb, var(--qe-amber) 10%, transparent)', mult:'0.7×' },
  risk_off_panic:     { label:'Risk-Off Panic',     short:'PANIC', tone:'panic', color:'var(--qe-red)',   bg:'color-mix(in srgb, var(--qe-red) 10%, transparent)', mult:'0.25×' },
};

// 365 days of synthetic timeline data (selectors slice the last 30/90/365)
const MOCK_REGIME_TIMELINE = (() => {
  const days = 365;
  const out = [];
  let cur = 'neutral';
  const start = new Date('2025-04-26').getTime();
  for (let i = 0; i < days; i++) {
    if (Math.random() < 0.07) {
      cur = REGIME_KEYS[Math.floor(Math.random() * REGIME_KEYS.length)];
    }
    out.push({
      date: new Date(start + i*86400000).toISOString().slice(0,10),
      label: cur,
      mode: 'full',
      vix: 12 + Math.random()*14,
      hy:  3.0 + Math.random()*2.5,
      rvol: 0.6 + Math.random()*0.9,
      funding: (Math.random()-0.5)*0.02,
    });
  }
  return out;
})();

const MOCK_REGIME = {
  current: {
    label:'risk_on_choppy', mode:'full', computed:'2026-04-25 20:07 UTC',
  },
  signals: [
    {key:'vix_close',      label:'VIX',                 unit:'',   value:13.8,  color:'var(--qe-red)',     decimals:1, tone:'dn', thresholds:[{v:30,c:'var(--qe-red)',l:'Panic'},{v:25,c:'var(--qe-amber)',l:'Def'},{v:20,c:'var(--qe-green)',l:'Risk-On'}], backfilled:true},
    {key:'us10y_yield',    label:'US 10Y Yield',        unit:'%',  value:4.21,  color:'var(--qe-blue)',    decimals:2, tone:'up', thresholds:[],                                                                                                                          backfilled:true},
    {key:'hy_spread',      label:'HY Spread',           unit:'%',  value:3.42,  color:'var(--qe-amber)',   decimals:2, tone:'dn', thresholds:[{v:5,c:'var(--qe-red)',l:'Panic'},{v:4.5,c:'var(--qe-amber)',l:'Def'},{v:3.5,c:'var(--qe-green)',l:'Risk-On'}],          backfilled:true},
    {key:'btc_dominance',  label:'BTC Market Cap',      unit:'$B', value:1870,  color:'var(--qe-amber)',   decimals:0, tone:'up', thresholds:[],                                                                                                                          backfilled:false},
    {key:'btc_rvol_ratio', label:'BTC RVol (30d/7d)',   unit:'',   value:1.41,  color:'var(--qe-purple)',  decimals:2, tone:'up', thresholds:[{v:1.3,c:'var(--qe-amber)',l:'Chop'},{v:1.2,c:'var(--qe-green)',l:'Trend'}],                                              backfilled:true},
    {key:'agg_oi_change',  label:'Aggregate OI Change', unit:'%',  value:+1.82, color:'var(--qe-green)',   decimals:2, tone:'up', thresholds:[{v:0,c:'var(--qe-muted)',l:'Zero'}],                                                                                       backfilled:false},
    {key:'avg_funding',    label:'Avg Funding Rate',    unit:'',   value:0.00012, color:'var(--qe-cyan)',  decimals:5, tone:'up', thresholds:[{v:0,c:'var(--qe-muted)',l:'Zero'},{v:-0.01,c:'var(--qe-red)',l:'Panic'}],                                              backfilled:true},
  ],
  coverage: [
    {key:'vix_close',      source:'yfinance',  from:'2020-01-01', to:'2026-04-25', rows:1572},
    {key:'us10y_yield',    source:'FRED',      from:'2020-01-01', to:'2026-04-25', rows:1648},
    {key:'hy_spread',      source:'FRED',      from:'2020-01-01', to:'2026-04-25', rows:1648},
    {key:'btc_dominance',  source:'CoinGecko', from:null,         to:null,         rows:0},
    {key:'btc_rvol_ratio', source:'derived',   from:'2020-01-08', to:'2026-04-25', rows:1564},
    {key:'agg_oi_change',  source:'Binance',   from:null,         to:null,         rows:0},
    {key:'avg_funding',    source:'Binance',   from:'2023-01-01', to:'2026-04-25', rows:826},
  ],
  thresholds: {
    vix_panic:30, vix_defensive:25, vix_risk_on:20, vix_choppy:22,
    hy_spread_panic:5.0, hy_spread_defensive:4.5, hy_spread_neutral:3.8, hy_spread_risk_on:3.5,
    rvol_ratio_choppy:1.3, rvol_ratio_trending:1.2,
    funding_panic:-0.01,
    btc_dom_change_bull:-0.5, btc_dom_change_bear:0.5,
  },
  recentChanges: [
    {date:'2026-04-25', label:'risk_on_choppy',   mode:'full', vix:13.8, hy:3.42, rvol:1.41, funding:+0.00012},
    {date:'2026-04-18', label:'risk_on_trending', mode:'full', vix:12.4, hy:3.21, rvol:1.08, funding:+0.00018},
    {date:'2026-04-09', label:'risk_off_defensive',mode:'full',vix:25.8, hy:4.62, rvol:1.51, funding:-0.00021},
    {date:'2026-04-04', label:'risk_on_choppy',   mode:'full', vix:18.4, hy:3.84, rvol:1.42, funding:+0.00041},
    {date:'2026-03-22', label:'neutral',          mode:'full', vix:16.2, hy:3.71, rvol:1.04, funding:+0.00008},
    {date:'2026-03-14', label:'risk_on_trending', mode:'full', vix:13.1, hy:3.18, rvol:0.94, funding:+0.00024},
  ],
  news: [
    {id:1, source:'finnhub', impact:'high', headline:'Fed minutes hint at slower pace of cuts; equities ease into close',
      summary:'Federal Reserve minutes for the March meeting showed officials becoming more cautious about further rate cuts as core PCE proves sticky. Two-year yields jumped 8bp; the dollar strengthened across G10. Risk assets pared session gains.',
      tickers:'SPY,TLT,BTC,DXY', published_at:'2026-04-25T18:42:00Z'},
    {id:2, source:'bwe', impact:'medium', headline:'BTC ETF inflows snap 3-day streak as price stalls near $93k',
      summary:'Spot Bitcoin ETF net flows turned negative for the first time this week. BlackRock and Fidelity saw outflows; Bitwise held positive.',
      tickers:'BTC,IBIT,FBTC', published_at:'2026-04-25T16:08:00Z'},
    {id:3, source:'finnhub', impact:'medium', headline:'Oil drops 2% on surprise inventory build, OPEC+ tensions',
      summary:'EIA reported a 4.2M-barrel build vs expectations of a draw. WTI fell back below $72; Brent under $76.',
      tickers:'CL,USO,XLE', published_at:'2026-04-25T14:31:00Z'},
    {id:4, source:'bwe', impact:'low', headline:'Solana validator outage resolved within 2 hours, network back online',
      summary:'A configuration push caused 18% of validators to fork; manual rollback restored consensus by 12:45 UTC.',
      tickers:'SOL', published_at:'2026-04-25T13:02:00Z'},
    {id:5, source:'finnhub', impact:'high', headline:'PCE inflation in line with estimates, core ticks up 0.1pp YoY',
      summary:'March PCE deflator at 2.4% YoY (in line); core at 2.8% (slight upside). Personal income +0.5%, spending +0.7%.',
      tickers:'SPY,DXY,TLT', published_at:'2026-04-25T12:31:00Z'},
    {id:6, source:'bwe', impact:'low', headline:'Ether ETF approval timeline pushed to Q3 per Bloomberg sources',
      summary:'SEC reportedly seeking additional 19b-4 amendments; July decision deadline now seen as unlikely.',
      tickers:'ETH,ETHE', published_at:'2026-04-25T10:47:00Z'},
  ],
  calendar: [
    {time:'2026-04-25T20:30:00Z', country:'US', impact:'high',   name:'Initial Jobless Claims',     est:215,  act:212,   unit:'K'},
    {time:'2026-04-25T22:00:00Z', country:'US', impact:'high',   name:'Core PCE Price Index (MoM)', est:0.30, act:0.30,  unit:'%'},
    {time:'2026-04-26T01:00:00Z', country:'US', impact:'medium', name:'Univ. of Michigan Sentiment',est:80.0, act:null,  unit:''},
    {time:'2026-04-26T08:00:00Z', country:'EU', impact:'high',   name:'ECB Lagarde Speech',         est:null, act:null,  unit:''},
    {time:'2026-04-26T13:00:00Z', country:'US', impact:'medium', name:'FOMC Member Powell Speech',  est:null, act:null,  unit:''},
  ],
};

// ─────────────────────────────────────────────────────────────────────────
// Timeline · SVG renderer (5 styles)
// ─────────────────────────────────────────────────────────────────────────
// Regime → ECharts hex. Canvas can't read CSS vars, so we source the resolved
// hex from QE_ECHARTS_THEME (the single token→hex map in charts.jsx) keyed by
// each regime's token — no hardcoded hex, one source of truth.
const REGIME_THEME_KEY = {
  risk_on_trending:'green', risk_on_choppy:'cyan', neutral:'muted',
  risk_off_defensive:'amber', risk_off_panic:'red',
};
const REGIME_HEX = Object.fromEntries(
  REGIME_KEYS.map(k => [k, QE_ECHARTS_THEME[REGIME_THEME_KEY[k]]])
);
// Build consecutive same-label runs → [{label, start, days}]
const _regimeSegs = (data) => {
  const segs = []; let cur = {label:data[0].label, start:0, days:1};
  for (let i=1; i<data.length; i++) {
    if (data[i].label === cur.label) cur.days++;
    else { segs.push(cur); cur = {label:data[i].label, start:i, days:1}; }
  }
  segs.push(cur);
  return segs;
};
const _fmtDay = (data, i) => (data[i] && data[i].date) ? data[i].date : `#${i}`;

// ECharts regime timeline — 5 styles (swim · bars · blocks · heat · stack)
const TimelineSvg = ({data, style='swim'}) => {
  const ref = React.useRef(null);
  const empty = !data || !data.length;
  const n = empty ? 0 : data.length;

  const { opts, height } = React.useMemo(() => {
    if (empty) return { opts:null, height:120 };
    const muted = QE_ECHARTS_THEME.muted, sub = QE_ECHARTS_THEME.sub, line = QE_ECHARTS_THEME.line;
    const segs = _regimeSegs(data);

    // ── SWIM — one lane per regime, colored runs along time ──────────────
    if (style === 'swim') {
      const lanes = REGIME_KEYS;             // top→bottom (inverse axis)
      const bgItems = lanes.map((r, li) => ({ value:[0, n, li], itemStyle:{ color:REGIME_HEX[r], opacity:0.07 } }));
      const segItems = [];
      // active runs
      segs.forEach(s => {
        const li = lanes.indexOf(s.label);
        segItems.push({ value:[s.start, s.start+s.days, li],
          itemStyle:{ color:REGIME_HEX[s.label], opacity:0.92 },
          _meta:`${REGIME_INFO[s.label].label} · ${s.days}d · ${_fmtDay(data, s.start)} → ${_fmtDay(data, Math.min(s.start+s.days-1, n-1))}` });
      });
      const swimRect = (frac) => (params, api) => {
        const x0 = api.coord([api.value(0), api.value(2)]);
        const x1 = api.coord([api.value(1), api.value(2)]);
        const bandH = api.size([0,1])[1];
        const h = Math.max(bandH * frac, 2);
        return { type:'rect',
          shape:{ x:x0[0], y:x0[1]-h/2, width:Math.max(x1[0]-x0[0], 1), height:h },
          style: api.style() };
      };
      return {
        height: lanes.length * 18 + 12,
        opts: {
          backgroundColor:'transparent', animation:false,
          grid:{ left:54, right:10, top:6, bottom:6 },
          tooltip:{ trigger:'item', backgroundColor:'#000', borderColor:QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[4,8],
            textStyle:{ color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace' },
            formatter: p => p.data && p.data._meta ? p.data._meta : '' },
          xAxis:{ type:'value', min:0, max:n, show:false },
          yAxis:{ type:'category', inverse:true, data:lanes.map(r=>REGIME_INFO[r].short),
            axisLine:{show:false}, axisTick:{show:false}, splitLine:{show:false},
            axisLabel:{ color: (val, idx) => REGIME_HEX[lanes[idx]], fontSize:9, fontWeight:700, fontFamily:'JetBrains Mono, monospace', formatter:(v,idx)=>v } },
          series:[
            // faint lane backgrounds — silent so they never swallow the tooltip
            { type:'custom', silent:true, z:1, renderItem: swimRect(0.86), encode:{ x:[0,1], y:2 }, data:bgItems },
            // active runs — full lane-height hit area for easy hover
            { type:'custom', z:2, renderItem: swimRect(0.86), encode:{ x:[0,1], y:2 }, data:segItems },
          ],
        },
      };
    }

    // ── BARS — dense per-day color columns (single row) ──────────────────
    if (style === 'bars') {
      const items = data.map((d,i) => ({ value:[i, i+1, 0], itemStyle:{ color:REGIME_HEX[d.label], opacity:0.92 },
        _meta:`${REGIME_INFO[d.label].label} · ${d.date||('#'+i)}` }));
      return {
        height: 56,
        opts: {
          backgroundColor:'transparent', animation:false,
          grid:{ left:10, right:10, top:8, bottom:8 },
          tooltip:{ trigger:'item', backgroundColor:'#000', borderColor:QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[4,8],
            textStyle:{ color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace' },
            formatter: p => p.data && p.data._meta ? p.data._meta : '' },
          xAxis:{ type:'value', min:0, max:n, show:false },
          yAxis:{ type:'category', data:[''], show:false },
          series:[{ type:'custom',
            renderItem:(params, api) => {
              const x0 = api.coord([api.value(0), 0]);
              const x1 = api.coord([api.value(1), 0]);
              const bandH = api.size([0,1])[1];
              return { type:'rect',
                shape:{ x:x0[0], y:x0[1]-bandH*0.42, width:Math.max(x1[0]-x0[0], 0.6), height:bandH*0.84 },
                style: api.style() };
            },
            encode:{ x:[0,1], y:2 }, data:items }],
        },
      };
    }

    // ── BLOCKS — labeled segment blocks ──────────────────────────────────
    if (style === 'blocks') {
      const items = segs.map(s => ({ value:[s.start, s.start+s.days, 0],
        itemStyle:{ color:REGIME_HEX[s.label], opacity:0.9 },
        _label: s.days > 6 ? `${REGIME_INFO[s.label].short} ${s.days}d` : REGIME_INFO[s.label].short,
        _meta:`${REGIME_INFO[s.label].label} · ${s.days}d · ${_fmtDay(data, s.start)} → ${_fmtDay(data, Math.min(s.start+s.days-1, n-1))}` }));
      return {
        height: 52,
        opts: {
          backgroundColor:'transparent', animation:false,
          grid:{ left:10, right:10, top:8, bottom:8 },
          tooltip:{ trigger:'item', backgroundColor:'#000', borderColor:QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[4,8],
            textStyle:{ color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace' },
            formatter: p => p.data && p.data._meta ? p.data._meta : '' },
          xAxis:{ type:'value', min:0, max:n, show:false },
          yAxis:{ type:'category', data:[''], show:false },
          series:[{ type:'custom',
            renderItem:(params, api) => {
              const x0 = api.coord([api.value(0), 0]);
              const x1 = api.coord([api.value(1), 0]);
              const bandH = api.size([0,1])[1];
              const w = Math.max(x1[0]-x0[0], 1);
              const rect = { type:'rect',
                shape:{ x:x0[0]+0.5, y:x0[1]-bandH*0.45, width:Math.max(w-1,0.6), height:bandH*0.9 },
                style: api.style() };
              const lbl = params.data && params.data._label;
              if (w > 42 && lbl) {
                return { type:'group', children:[ rect, { type:'text',
                  style:{ text:lbl, x:x0[0]+w/2, y:x0[1], fill:'#000', opacity:0.6,
                    font:'700 9px JetBrains Mono, monospace', textAlign:'center', textVerticalAlign:'middle' } } ] };
              }
              return rect;
            },
            encode:{ x:[0,1], y:2 }, data:items }],
        },
      };
    }

    // ── HEAT — calendar heatmap, cell colored by regime ──────────────────
    if (style === 'heat') {
      const cells = data.map(d => [d.date, REGIME_KEYS.indexOf(d.label)]);
      return {
        height: 132,
        opts: {
          backgroundColor:'transparent', animation:false,
          tooltip:{ trigger:'item', backgroundColor:'#000', borderColor:QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[4,8],
            textStyle:{ color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace' },
            formatter: p => { const k = REGIME_KEYS[p.data[1]]; return `${p.data[0]}\n${REGIME_INFO[k].label}`; } },
          visualMap:{ show:false, type:'piecewise', dimension:1, seriesIndex:0,
            pieces: REGIME_KEYS.map((r,i)=>({ value:i, color:REGIME_HEX[r] })) },
          calendar:{ top:24, left:34, right:10, bottom:6, cellSize:['auto', 15],
            range:[data[0].date, data[n-1].date],
            orient:'horizontal',
            itemStyle:{ color:'#0a0d14', borderColor:'#000', borderWidth:1.5 },
            dayLabel:{ color:muted, fontSize:8, fontFamily:'JetBrains Mono, monospace', firstDay:1 },
            monthLabel:{ color:sub, fontSize:9, fontFamily:'JetBrains Mono, monospace' },
            yearLabel:{ show:false },
            splitLine:{ lineStyle:{ color:line, width:1 } } },
          series:[{ type:'heatmap', coordinateSystem:'calendar', data:cells,
            itemStyle:{ borderColor:'#000', borderWidth:1.5 } }],
        },
      };
    }

    // ── STACK — rolling 14d regime composition (stacked area) ────────────
    const WIN = 14, step = Math.max(1, Math.floor(n/200));
    const buckets = [], labels = [];
    for (let bi = WIN; bi <= n; bi += step) {
      const slice = data.slice(bi-WIN, bi);
      const c = {}; REGIME_KEYS.forEach(r => c[r] = 0);
      slice.forEach(d => { if (c[d.label] != null) c[d.label]++; });
      buckets.push(c); labels.push(_fmtDay(data, bi-1));
    }
    const series = REGIME_KEYS.map(r => ({
      name: REGIME_INFO[r].short, type:'line', stack:'comp', smooth:0.2, symbol:'none',
      lineStyle:{ width:0 }, areaStyle:{ color:REGIME_HEX[r], opacity:0.85 },
      emphasis:{ focus:'series' },
      data: buckets.map(b => +(b[r]/WIN*100).toFixed(1)),
    }));
    return {
      height: 130,
      opts: {
        backgroundColor:'transparent', animation:false,
        grid:{ left:38, right:10, top:10, bottom:20 },
        tooltip:{ trigger:'axis', backgroundColor:'#000', borderColor:QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[6,9],
          textStyle:{ color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace' },
          axisPointer:{ type:'line', lineStyle:{ color:QE_ECHARTS_THEME.cyan, opacity:0.4 } },
          formatter: ps => {
            const head = ps[0] ? ps[0].axisValue : '';
            const rows = ps.filter(p=>p.value>0).reverse()
              .map(p => `${p.marker} ${p.seriesName} ${p.value.toFixed(0)}%`).join('<br/>');
            return `${head}<br/>${rows}`;
          } },
        xAxis:{ type:'category', boundaryGap:false, data:labels,
          ..._axis({ axisLabel:{ color:muted, fontSize:9, fontFamily:'JetBrains Mono, monospace',
            interval: Math.ceil(labels.length/6) }, splitLine:{show:false} }) },
        yAxis:{ type:'value', min:0, max:100,
          ..._axis({ axisLabel:{ color:muted, fontSize:9, fontFamily:'JetBrains Mono, monospace', formatter:v=>v+'%' },
            splitLine:{ lineStyle:{ color:QE_ECHARTS_THEME.faint, opacity:0.4, type:[2,3] } } }) },
        series,
      },
    };
  }, [data, style, empty, n]);

  useECharts(ref, opts, [opts]);

  if (empty) return <EmptyState tone="info" glyph="〇" msg="No regime data yet" cta={<span style={{fontSize:'0.6rem',color:'var(--qe-sub)',fontFamily:'var(--qe-mono)'}}>use Backfill tab to fetch macro signals</span>}/>;

  // Time annotation — only for the styles whose chart hides its own x-axis.
  // (heat shows month labels, stack shows a date x-axis already.)
  const showTimeAxis = style === 'swim' || style === 'bars' || style === 'blocks';
  const padL = style === 'swim' ? 54 : 10;
  const ticks = (() => {
    if (!showTimeAxis) return [];
    const fmt = s => (typeof s === 'string' && s.length >= 10) ? s.slice(5) : s;  // MM-DD
    const idxs = [0, 0.25, 0.5, 0.75, 1].map(t => Math.round(t * (n - 1)));
    return [...new Set(idxs)].map(i => fmt(_fmtDay(data, i)));
  })();

  return (
    <div style={{width:'100%'}}>
      <div ref={ref} style={{width:'100%', height}}/>
      {showTimeAxis && ticks.length > 1 && (
        <div style={{display:'flex', justifyContent:'space-between', paddingLeft:padL, paddingRight:10, marginTop:2,
          fontFamily:'var(--qe-mono)', fontSize:'0.52rem', color:'var(--qe-muted)', letterSpacing:'0.02em'}}>
          {ticks.map((t,i) => <span key={i}>{t}</span>)}
        </div>
      )}
    </div>
  );
};

const RegimeLegend = () => (
  <div style={{display:'flex', gap:14, flexWrap:'wrap', fontFamily:'var(--qe-mono)'}}>
    {REGIME_KEYS.map(r => (
      <span key={r} style={{display:'inline-flex', alignItems:'center', gap:4, fontSize:'0.58rem'}}>
        <span style={{width:8, height:8, background:REGIME_HEX[r], display:'inline-block'}}/>
        <span style={{color:REGIME_HEX[r]}}>{REGIME_INFO[r].label}</span>
      </span>
    ))}
  </div>
);

// ─────────────────────────────────────────────────────────────────────────
// Tab: Overview
// ─────────────────────────────────────────────────────────────────────────
const RegimeTabOverview = () => {
  const [tlStyle, setTlStyle] = React.useState('swim');
  const [tlRange, setTlRange] = React.useState(365);   // 0 = All
  const [allRange, setAllRange] = React.useState(365);
  const [selChange, setSelChange] = React.useState(null); // selected transition (date key)

  const cur = REGIME_INFO[MOCK_REGIME.current.label];
  const data = tlRange === 0 ? MOCK_REGIME_TIMELINE : MOCK_REGIME_TIMELINE.slice(-tlRange);

  // distribution
  const counts = {}; REGIME_KEYS.forEach(r => counts[r] = 0);
  data.forEach(d => counts[d.label]++);
  const total = data.length;

  return (
    <GridWorkspace>

        {/* Row 1: current + distribution + multipliers */}
        <GridItem x={0} y={0} w={6} h={7} minW={4} minH={4}>
        <Pane title="Current Regime" hot style={{height:'100%'}}
          foot={{tone:'info', id:4001, msg:`${MOCK_REGIME.current.mode} mode · computed ${MOCK_REGIME.current.computed}`, ms:6}}>
          <div style={{display:'flex', flexDirection:'column', alignItems:'center', gap:6, padding:'8px 0'}}>
            <RegimeBadge tone={cur.tone} label={cur.label.toUpperCase()}/>
            <span style={{fontFamily:'var(--qe-mono)', fontSize:'1.8rem', fontWeight:700, color:cur.color, lineHeight:1}}>{cur.mult}</span>
            <span style={{fontSize:'0.56rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>sizing multiplier</span>
          </div>
        </Pane>
        </GridItem>

        <GridItem x={6} y={0} w={12} h={7} minW={6} minH={4}>
        <Pane title="Regime Distribution" tag={tlRange===0?'ALL':`${tlRange}d`} style={{height:'100%'}}
          foot={{tone:'sub', id:4002, msg:`${total} days observed · over selected window`, ms:2}}>
          <div style={{display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:6}}>
            {REGIME_KEYS.map(r => {
              const c = counts[r] || 0;
              const pct = total > 0 ? (c/total*100) : 0;
              const info = REGIME_INFO[r];
              return (
                <div key={r} style={{padding:'6px 4px', background:info.bg, border:'1px solid color-mix(in srgb, '+info.color+' 27%, transparent)', textAlign:'center'}}>
                  <div style={{fontSize:'0.56rem', fontWeight:700, color:info.color, letterSpacing:'0.08em'}}>{info.short}</div>
                  <div style={{fontFamily:'var(--qe-mono)', fontSize:'1rem', fontWeight:700, color:info.color}}>{pct.toFixed(1)}%</div>
                  <div style={{fontSize:'0.52rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>{c}d</div>
                </div>
              );
            })}
          </div>
        </Pane>
        </GridItem>

        <GridItem x={18} y={0} w={6} h={7} minW={4} minH={4}>
        <Pane title="Sizing Multipliers" style={{height:'100%'}}
          foot={{tone:'sub', id:4003, msg:'applied to base position size at calc time', ms:0}}>
          <FieldList rows={REGIME_KEYS.map(r => {
            const info = REGIME_INFO[r];
            return {
              label: info.label.replace('Risk-On ','').replace('Risk-Off ',''),
              value: info.mult,
              color: info.color,
            };
          })}/>
        </Pane>
        </GridItem>

        {/* Row 2: timeline */}
        <GridItem x={0} y={7} w={24} h={8} minW={10} minH={5}>
        <Pane title="Regime Timeline" tag={tlStyle.toUpperCase()} style={{height:'100%'}}
        right={<>
          <span style={{fontSize:'0.54rem', color:'var(--qe-muted)', letterSpacing:'0.08em', fontFamily:'var(--qe-mono)'}}>STYLE</span>
          <PeriodSelector options={[['swim','Swim'],['bars','Bars'],['blocks','Blocks'],['heat','Heat'],['stack','Stack']]} value={tlStyle} onChange={setTlStyle}/>
          <span style={{color:'var(--qe-muted)'}}>│</span>
          <PeriodSelector options={[[30,'30d'],[90,'90d'],[365,'1y'],[0,'All']]} value={tlRange} onChange={setTlRange}/>
        </>}
        foot={{tone:'ok', id:4004, msg:`${data.length} regime labels · last transition 7d ago · ${REGIME_INFO[data[data.length-1].label].label}`, ms:14}}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          <TimelineSvg data={data} style={tlStyle}/>
          <RegimeLegend/>
        </div>
      </Pane>
        </GridItem>

        {/* Row 3: macro signals grid */}
        <GridItem x={0} y={15} w={24} h={10} minW={10} minH={5}>
        <Pane title="Macro Signals" count={MOCK_REGIME.signals.length} style={{height:'100%'}}
        right={<>
          <span style={{fontSize:'0.54rem', color:'var(--qe-muted)', letterSpacing:'0.08em', fontFamily:'var(--qe-mono)'}}>ALL</span>
          <PeriodSelector options={[[30,'30d'],[90,'90d'],[365,'1y'],[1825,'5y'],[0,'All']]} value={allRange} onChange={setAllRange}/>
        </>}
        foot={{tone:'info', id:4005, msg:'cards inherit "All" range until individual override; per-card range clears global', ms:1}}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:6}}>
          {MOCK_REGIME.signals.map(s => <SignalCard key={s.key} sig={s} defaultRange={allRange}/>)}
        </div>
      </Pane>
        </GridItem>

        {/* Row 4: recent regime changes */}
        <GridItem x={0} y={25} w={24} h={10} minW={10} minH={5}>
        <Pane title="Recent Regime Changes" count={MOCK_REGIME.recentChanges.length} style={{height:'100%'}}
        foot={{tone:'sub', id:4006, msg:'transitions only · sorted by recency · click a row to see signal context', ms:4}}
        bodyStyle={{padding:0}}>
        <DataList
          selKey="date"
          onClick={r => setSelChange(s => s === r.date ? null : r.date)}
          selected={selChange}
          columns={[
            {key:'date',  label:'DATE',     cell:'dim'},
            {key:'label', label:'REGIME',   render:r=>{const info=REGIME_INFO[r.label];return <span style={{color:info.color, fontWeight:700}}>{info.label}</span>}},
            {key:'mode',  label:'MODE',     cell:'dim'},
            {key:'vix',   label:'VIX',      align:'right', render:r=><span style={{color: r.vix>=25?'var(--qe-red)':r.vix>=20?'var(--qe-amber)':'var(--qe-text)'}}>{r.vix.toFixed(1)}</span>},
            {key:'hy',    label:'HY SPREAD',align:'right', render:r=>r.hy.toFixed(2)+'%'},
            {key:'rvol',  label:'RVOL',     align:'right', render:r=>r.rvol.toFixed(2)},
            {key:'funding',label:'FUNDING', align:'right', render:r=><span style={{color: r.funding>=0?'var(--qe-green)':'var(--qe-red)'}}>{(r.funding*100).toFixed(3)}%</span>},
          ]}
          rows={MOCK_REGIME.recentChanges}
        />
        {selChange && (() => {
          const list = MOCK_REGIME.recentChanges;
          const i = list.findIndex(r => r.date === selChange);
          const row = list[i];
          if (!row) return null;
          const prev = list[i + 1] || null;             // next row down = previous regime
          const to = REGIME_INFO[row.label];
          const from = prev ? REGIME_INFO[prev.label] : null;
          return (
            <div style={{display:'flex', alignItems:'center', gap:14, padding:'5px 10px', borderTop:'1px solid var(--qe-line)', background:'var(--qe-panel)', fontFamily:'var(--qe-mono)', fontSize:'0.62rem', flexWrap:'wrap'}}>
              <span style={{color:'var(--qe-muted)', letterSpacing:'0.1em', fontSize:'0.5rem', fontWeight:700}}>SIGNAL CONTEXT</span>
              <span style={{color:'var(--qe-sub)'}}>{row.date}</span>
              <span>
                {from && <React.Fragment><span style={{color:from.color, fontWeight:700}}>{from.short}</span><span style={{color:'var(--qe-muted)'}}> → </span></React.Fragment>}
                <span style={{color:to.color, fontWeight:700}}>{to.short}</span>
              </span>
              <span style={{color:'var(--qe-muted)'}}>size {from ? <span style={{color:from.color}}>{from.mult}</span> : '—'} → <span style={{color:to.color, fontWeight:700}}>{to.mult}</span></span>
              <span style={{color:'var(--qe-muted)'}}>VIX <span style={{color: row.vix>=25?'var(--qe-red)':row.vix>=20?'var(--qe-amber)':'var(--qe-text)'}}>{row.vix.toFixed(1)}</span></span>
              <span style={{color:'var(--qe-muted)'}}>HY <span style={{color:'var(--qe-text)'}}>{row.hy.toFixed(2)}%</span></span>
              <span style={{color:'var(--qe-muted)'}}>RVOL <span style={{color:'var(--qe-text)'}}>{row.rvol.toFixed(2)}</span></span>
              <span style={{color:'var(--qe-muted)'}}>FUND <span style={{color: row.funding>=0?'var(--qe-green)':'var(--qe-red)'}}>{(row.funding*100).toFixed(3)}%</span></span>
              <span className="qe-grow"/>
              <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => setSelChange(null)}>✕</button>
            </div>
          );
        })()}
      </Pane>
        </GridItem>
    </GridWorkspace>
  );
};

// SignalChart — ECharts area line w/ value tooltip + in-chart threshold marklines
const SignalChart = ({data, color, thresholds=[], decimals=2, unit='', height=84}) => {
  const ref = React.useRef(null);
  const c = _qeResolveColor(color);
  const opts = React.useMemo(() => {
    const lo = Math.min(...data), hi = Math.max(...data);
    // only draw threshold lines that fall within (or just outside) the data band
    const pad = (hi - lo) * 0.6 || 1;
    const inBand = thresholds.filter(t => t.v >= lo - pad && t.v <= hi + pad);
    return {
      backgroundColor:'transparent', animation:false,
      grid:{ left:42, right:8, top:8, bottom:6 },
      tooltip:{ trigger:'axis', backgroundColor:'#000', borderColor:QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[3,7],
        textStyle:{ color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace' },
        axisPointer:{ type:'line', lineStyle:{ color:c, opacity:0.5 } },
        formatter: ps => { const v = ps[0].value;
          return `${(+v).toLocaleString('en-US',{minimumFractionDigits:decimals, maximumFractionDigits:decimals})}${unit?(' '+unit):''}`; } },
      xAxis:{ type:'category', show:false, boundaryGap:false, data:data.map((_,i)=>i) },
      yAxis:{ type:'value', scale:true,
        ..._axis({ axisLabel:{ color:QE_ECHARTS_THEME.muted, fontSize:8, fontFamily:'JetBrains Mono, monospace',
          formatter:v => (+v).toLocaleString('en-US',{maximumFractionDigits:decimals}) },
          splitLine:{ lineStyle:{ color:QE_ECHARTS_THEME.faint, opacity:0.35, type:[2,3] } } }) },
      series:[{
        type:'line', data, smooth:0.18, symbol:'none',
        lineStyle:{ color:c, width:1.4 },
        areaStyle:{ color:{ type:'linear', x:0,y:0,x2:0,y2:1, colorStops:[
          { offset:0, color:c+'40' }, { offset:1, color:c+'00' } ] } },
        markLine: inBand.length ? {
          symbol:'none', silent:true,
          data: inBand.map(t => ({ yAxis:t.v,
            lineStyle:{ color:_qeResolveColor(t.c), type:'dashed', width:1, opacity:0.8 },
            label:{ show:true, position:'insideStartTop', formatter:t.l, color:_qeResolveColor(t.c),
              fontSize:8, fontFamily:'JetBrains Mono, monospace' } })),
        } : undefined,
      }],
    };
  }, [data, c, thresholds, decimals, unit]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} style={{width:'100%', height}}/>;
};

// SignalCard — individual macro signal panel (chart + range buttons + thresholds + empty state)
const SignalCard = ({sig, defaultRange}) => {
  const [range, setRange] = React.useState(defaultRange);
  React.useEffect(() => { setRange(defaultRange); }, [defaultRange]);
  // synthesize a STABLE series per signal+range (seeded): re-renders must not
  // reshuffle the chart — only a range change regenerates it.
  const n = Math.min(range || 1500, 200);
  const data = React.useMemo(() => {
    let s = (sig.key.split('').reduce((a, c) => a + c.charCodeAt(0), 17) * 7919 + (range || 9973)) % 233280;
    const rnd = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
    let v = sig.value;
    const arr = [];
    for (let i = 0; i < n; i++) { v += (rnd() - 0.5) * sig.value * 0.04; arr.push(+v.toFixed(4)); }
    arr.push(sig.value);
    return arr;
  }, [sig.key, sig.value, range, n]);
  if (!sig.backfilled) {
    return (
      <div style={{background:'var(--qe-card)', border:'1px solid var(--qe-line)', padding:'8px 10px', display:'flex', flexDirection:'column', gap:6}}>
        <div style={{display:'flex', alignItems:'center', gap:6}}>
          <span style={{width:6, height:6, background:sig.color, display:'inline-block'}}/>
          <span style={{fontSize:'0.7rem', fontWeight:600, color:'var(--qe-text)'}}>{sig.label}</span>
          <span style={{marginLeft:'auto', fontSize:'0.56rem', color:'var(--qe-amber)', fontFamily:'var(--qe-mono)'}}>not backfilled</span>
        </div>
        <EmptyState tone="warn" glyph="∅" msg="Not yet backfilled"
          cta={<button className="qe-btn qe-btn-sm">Use Backfill tab →</button>}/>
      </div>
    );
  }
  return (
    <div style={{background:'var(--qe-card)', border:'1px solid var(--qe-line)', padding:'8px 10px', display:'flex', flexDirection:'column', gap:6}}>
      <div style={{display:'flex', alignItems:'center', gap:6}}>
        <span style={{width:6, height:6, background:sig.color, display:'inline-block'}}/>
        <span style={{fontSize:'0.7rem', fontWeight:600, color:'var(--qe-text)'}}>{sig.label}</span>
        <span className="qe-mono" style={{fontSize:'0.74rem', color:'var(--qe-text-dim)', fontWeight:700, marginLeft:4}}>
          {sig.value.toLocaleString('en-US',{minimumFractionDigits:sig.decimals, maximumFractionDigits:sig.decimals})}{sig.unit && ' '+sig.unit}
        </span>
        <span style={{marginLeft:'auto'}}>
          <PeriodSelector options={[[30,'30d'],[90,'90d'],[365,'1y'],[1825,'5y'],[0,'All']]} value={range} onChange={setRange}/>
        </span>
      </div>
      <SignalChart data={data} color={sig.color} thresholds={sig.thresholds} decimals={sig.decimals} unit={sig.unit} height={84}/>
      {sig.thresholds && sig.thresholds.length > 0 && (
        <div style={{display:'flex', flexWrap:'wrap', gap:6, fontSize:'0.54rem', fontFamily:'var(--qe-mono)'}}>
          {sig.thresholds.map(t => (
            <span key={t.l} style={{display:'inline-flex', alignItems:'center', gap:3, color:t.c}}>
              <span style={{width:8, height:0, borderTop:`1px dashed ${t.c}`, display:'inline-block'}}/>
              {t.l} {t.v}{sig.unit && ' '+sig.unit}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// Tab: Backfill
// ─────────────────────────────────────────────────────────────────────────
const RegimeTabBackfill = () => {
  const [mode,  setMode]  = React.useState('macro_only');
  const [progress, setProgress] = React.useState({running:false, pct:0, msg:''});
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={8} h={14} minW={5} minH={6}>
      <Pane title="Backfill Macro Data" style={{height:'100%'}}
        foot={{tone:'sub', id:4101, msg:'fetches yfinance (VIX) + FRED (yields/spreads) + CoinGecko (BTC dom) + optional Binance (OI/funding)', ms:0}}>
        <div style={{display:'flex', flexDirection:'column', gap:8}}>
          <p style={{fontSize:'0.62rem', color:'var(--qe-sub)', lineHeight:1.5, margin:0}}>
            Macro Only works for deep history (5-30+ years). Full adds Binance OI / funding (~2-3 years).
          </p>
          <div>
            <Lbl>Mode</Lbl>
            <select className="qe-input qe-select" value={mode} onChange={e=>setMode(e.target.value)}>
              <option value="macro_only">Macro Only · VIX · FRED · BTC dom</option>
              <option value="full">Full · + Binance OI · Funding</option>
            </select>
          </div>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
            <div><Lbl>From</Lbl><input type="date" className="qe-input" defaultValue="2020-01-01"/></div>
            <div><Lbl>To</Lbl><input type="date" className="qe-input" defaultValue="2026-04-25"/></div>
          </div>
          <button className="qe-btn qe-btn-primary qe-btn-lg" style={{width:'100%', justifyContent:'center'}}
            onClick={()=>setProgress({running:true, pct:42, msg:'fetching FRED hy_spread · 2020-01-01 → 2026-04-25'})}>
            ▶ Start Backfill
          </button>

          {progress.running && (
            <div style={{display:'flex', flexDirection:'column', gap:4, marginTop:4}}>
              <div style={{display:'flex', justifyContent:'space-between', fontSize:'0.6rem', fontFamily:'var(--qe-mono)'}}>
                <span style={{color:'var(--qe-sub)'}}>{progress.msg}</span>
                <span style={{color:'var(--qe-cyan)', fontWeight:700}}>{progress.pct}%</span>
              </div>
              <div className="qe-gauge-track" style={{height:4}}>
                <div className="qe-gauge-fill" style={{width: progress.pct+'%'}}/>
              </div>
            </div>
          )}
        </div>
      </Pane>
      </GridItem>

      <GridItem x={8} y={0} w={16} h={20} minW={8} minH={6}>
      <Pane title="Signal Coverage" count={MOCK_REGIME.coverage.length} style={{height:'100%'}}
        foot={{tone:'info', id:4102, msg:`${MOCK_REGIME.coverage.filter(c=>c.rows>0).length} / ${MOCK_REGIME.coverage.length} signals backfilled · 2 pending`, ms:8}}
        bodyStyle={{padding:0}}>
        <DataList
          selKey="key"
          columns={[
            {key:'key',    label:'SIGNAL', render:r=>{
              const sig = MOCK_REGIME.signals.find(s=>s.key===r.key);
              return <span style={{color: r.rows>0?'var(--qe-text)':'var(--qe-sub)', fontWeight:600}}>{sig?.label || r.key}</span>;
            }},
            {key:'source', label:'SOURCE', cell:'dim'},
            {key:'from',   label:'FROM',   cell:'dim', render:r=>r.from || <span style={{color:'var(--qe-muted)'}}>—</span>},
            {key:'to',     label:'TO',     cell:'dim', render:r=>r.to   || <span style={{color:'var(--qe-muted)'}}>—</span>},
            {key:'rows',   label:'ROWS',   align:'right', render:r=>r.rows>0
              ? <span style={{color:'var(--qe-green)',fontWeight:700}}>{r.rows.toLocaleString()}</span>
              : <Badge tone="warn">NOT BACKFILLED</Badge>},
          ]}
          rows={MOCK_REGIME.coverage}
        />
      </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// Tab: News
// ─────────────────────────────────────────────────────────────────────────
// Canonical pill palettes — mapped to --qe-* tokens (single source of truth).
const NEWS_SRC_STYLE = {
  finnhub: {color:'var(--qe-blue)',  background:'var(--qe-bg-blue)'},
  bwe:     {color:'var(--qe-amber)', background:'var(--qe-bg-amber)'},
};
const IMPACT_STYLE = {
  high:   {color:'var(--qe-red)',   background:'var(--qe-bg-red)'},
  medium: {color:'var(--qe-amber)', background:'var(--qe-bg-amber)'},
};
const DEFAULT_PILL = {color:'var(--qe-sub)', background:'var(--qe-panel)'};
const srcPill    = (source) => NEWS_SRC_STYLE[source] || DEFAULT_PILL;
const impactPill = (impact) => IMPACT_STYLE[impact]    || DEFAULT_PILL;

const NewsItem = ({n, hero=false, expanded, onClick}) => {
  const srcStyle = srcPill(n.source);
  const impactStyle = impactPill(n.impact);
  const relTime = (() => {
    const d = new Date(n.published_at);
    const diff = Math.floor((Date.parse('2026-04-25T20:08:00Z') - d.getTime())/1000);
    if (diff < 3600) return Math.floor(diff/60)+'m ago';
    if (diff < 86400) return Math.floor(diff/3600)+'h ago';
    return Math.floor(diff/86400)+'d ago';
  })();
  if (hero) {
    return (
      <div onClick={onClick} style={{
        background:'var(--qe-card)',
        border:`1px solid ${expanded?'var(--qe-cyan)':'var(--qe-line)'}`,
        padding:'12px 14px', cursor:'pointer',
      }}>
        <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:8}}>
          <span style={{...srcStyle, padding:'1px 6px', fontSize:'0.56rem', fontWeight:700, letterSpacing:'0.06em', fontFamily:'var(--qe-mono)'}}>{n.source.toUpperCase()}</span>
          <Badge tone="info">TOP STORY</Badge>
          <span style={{...impactStyle, padding:'1px 6px', fontSize:'0.54rem', fontWeight:700, fontFamily:'var(--qe-mono)'}}>{n.impact.toUpperCase()}</span>
          <span style={{marginLeft:'auto', fontSize:'0.58rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>{relTime}</span>
        </div>
        <h2 style={{fontSize:'0.94rem', fontWeight:800, color:'var(--qe-text)', lineHeight:1.35, marginBottom:6, fontFamily:'var(--qe-ui)', letterSpacing:'-0.01em'}}>{n.headline}</h2>
        <p style={{fontSize:'0.7rem', color:'var(--qe-sub)', lineHeight:1.6, margin:0}}>{n.summary}</p>
        {expanded && n.tickers && (
          <div style={{display:'flex', flexWrap:'wrap', gap:4, marginTop:8}}>
            {n.tickers.split(',').map(t => (
              <span key={t} style={{padding:'1px 6px', fontFamily:'var(--qe-mono)', fontSize:'0.56rem', background:'var(--qe-panel)', border:'1px solid var(--qe-line)', color:'var(--qe-sub)'}}>{t.trim()}</span>
            ))}
          </div>
        )}
        <div style={{fontSize:'0.54rem', color:'var(--qe-muted)', marginTop:6, fontFamily:'var(--qe-mono)'}}>{expanded?'▲ Collapse':'▼ Expand'}</div>
      </div>
    );
  }
  return (
    <div onClick={onClick} style={{
      background:'var(--qe-card)',
      border:`1px solid ${expanded?'var(--qe-cyan)':'var(--qe-line)'}`,
      padding: expanded ? '10px 12px' : '6px 10px',
      cursor:'pointer',
    }}>
      <div style={{display:'flex', alignItems:'flex-start', gap:8}}>
        <span style={{...srcStyle, padding:'1px 5px', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.06em', fontFamily:'var(--qe-mono)', flexShrink:0}}>{n.source.toUpperCase()}</span>
        <div style={{flex:1, minWidth:0}}>
          <div style={{fontSize: expanded?'0.74rem':'0.68rem', fontWeight: expanded?700:600, color:'var(--qe-text)', lineHeight:1.4}}>{n.headline}</div>
          {expanded && <p style={{fontSize:'0.66rem', color:'var(--qe-sub)', lineHeight:1.6, margin:'6px 0 0 0'}}>{n.summary}</p>}
          {expanded && n.tickers && (
            <div style={{display:'flex', flexWrap:'wrap', gap:4, marginTop:6}}>
              {n.tickers.split(',').map(t => (
                <span key={t} style={{padding:'1px 5px', fontFamily:'var(--qe-mono)', fontSize:'0.54rem', background:'var(--qe-panel)', border:'1px solid var(--qe-line)', color:'var(--qe-sub)'}}>{t.trim()}</span>
              ))}
            </div>
          )}
        </div>
        <div style={{display:'flex', flexDirection:'column', alignItems:'flex-end', gap:3, flexShrink:0}}>
          <span style={{...impactStyle, padding:'1px 5px', fontSize:'0.5rem', fontWeight:700, fontFamily:'var(--qe-mono)'}}>{n.impact==='medium'?'MED':n.impact.toUpperCase()}</span>
          <span style={{fontSize:'0.54rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', whiteSpace:'nowrap'}}>{relTime}</span>
        </div>
      </div>
    </div>
  );
};

const RegimeTabNews = () => {
  const [expanded, setExpanded] = React.useState(null);
  const [newsView, setNewsView] = React.useState('magazine'); // magazine | detail
  const nowMs = Date.parse('2026-04-25T20:08:00Z');
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={16} h={24} minW={8} minH={8}>
      <Pane title="Market News" count={MOCK_REGIME.news.length} style={{height:'100%'}}
        right={<>
          <PeriodSelector options={[['magazine','Magazine'],['detail','Detail']]} value={newsView} onChange={setNewsView}/>
          <StatusDot tone="info" label="LIVE"/>
        </>}
        foot={{tone:'info', id:4201, msg: newsView==='magazine' ? 'finnhub + bwe streams · auto-refresh 60s · click to expand summary' : 'finnhub + bwe streams · dense stream view · newest first', ms:42}}
        bodyStyle={{padding: newsView==='magazine' ? 6 : 0}}>
        {newsView==='magazine' ? (
        <div style={{display:'flex', flexDirection:'column', gap:4}}>
          <NewsItem n={MOCK_REGIME.news[0]} hero expanded={expanded===MOCK_REGIME.news[0].id} onClick={()=>setExpanded(expanded===MOCK_REGIME.news[0].id?null:MOCK_REGIME.news[0].id)}/>
          {MOCK_REGIME.news.slice(1).map(n => (
            <NewsItem key={n.id} n={n} expanded={expanded===n.id} onClick={()=>setExpanded(expanded===n.id?null:n.id)}/>
          ))}
        </div>
        ) : (
        <DataList
          selKey="id" dense tools={false}
          onClick={n => { setNewsView('magazine'); setExpanded(n.id); }}
          columns={[
            {key:'published_at', label:'TIME', cell:'dim', render:n => {
              const mins = Math.max(0, Math.round((nowMs - Date.parse(n.published_at)) / 60000));
              return mins < 60 ? `${mins}m ago` : `${Math.round(mins/60)}h ago`;
            }},
            {key:'source', label:'SRC', render:n => <span style={{...srcPill(n.source), padding:'1px 5px', fontSize:'0.5rem', fontWeight:700, fontFamily:'var(--qe-mono)', letterSpacing:'0.06em'}}>{n.source.toUpperCase()}</span>},
            {key:'impact', label:'IMPACT', render:n => <span style={{...impactPill(n.impact), padding:'1px 5px', fontSize:'0.5rem', fontWeight:700, fontFamily:'var(--qe-mono)'}}>{n.impact==='medium'?'MED':n.impact.toUpperCase()}</span>},
            {key:'headline', label:'HEADLINE', render:n => <span style={{color:'var(--qe-text)', fontWeight:600}}>{n.headline}</span>},
            {key:'tickers', label:'TICKERS', cell:'dim', render:n => <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.56rem'}}>{n.tickers}</span>},
          ]}
          rows={MOCK_REGIME.news}
        />
        )}
      </Pane>
      </GridItem>

      <GridItem x={16} y={0} w={8} h={24} minW={6} minH={8}>
      <Pane title="Economic Calendar" count={MOCK_REGIME.calendar.length} style={{height:'100%'}} tag="NOW MARKER"
        foot={{tone:'warn', id:4202, msg:'2 high-impact events within next 24h · ECB Lagarde 08:00 UTC tomorrow', ms:12}}
        bodyStyle={{padding:6}}>
        <div style={{display:'flex', flexDirection:'column', gap:4}}>
          {(() => {
            const out = [];
            let nowMarkerInserted = false;
            MOCK_REGIME.calendar.forEach((e, i) => {
              const evMs = Date.parse(e.time);
              if (!nowMarkerInserted && evMs >= nowMs) {
                nowMarkerInserted = true;
                out.push(
                  <div key="now-marker" style={{display:'flex', alignItems:'center', gap:6, padding:'4px 0'}}>
                    <hr style={{flex:1, border:'none', borderTop:'1px solid var(--qe-cyan)', opacity:0.5}}/>
                    <span style={{fontSize:'0.54rem', fontWeight:700, color:'var(--qe-cyan)', letterSpacing:'0.12em', fontFamily:'var(--qe-mono)'}}>● NOW</span>
                    <hr style={{flex:1, border:'none', borderTop:'1px solid var(--qe-cyan)', opacity:0.5}}/>
                  </div>
                );
              }
              const isPast = evMs < nowMs;
              const minsAway = Math.round((evMs - nowMs)/60000);
              const isNear = !isPast && Math.abs(minsAway) <= 240;
              const timeLbl = isPast
                ? (minsAway < -60 ? `${Math.round(-minsAway/60)}h ago` : `${-minsAway}m ago`)
                : (minsAway < 60 ? `in ${minsAway}m` : `in ${Math.round(minsAway/60)}h`);
              const surprise = e.act!=null && e.est!=null && Math.abs(e.est)>0 ? Math.abs(e.act-e.est)/Math.abs(e.est) : 0;
              const actColor = e.act==null ? 'var(--qe-sub)' : surprise>0.10 ? (e.act>e.est?'var(--qe-green)':'var(--qe-red)') : 'var(--qe-text)';
              const impactStyle = impactPill(e.impact);
              out.push(
                <div key={i} style={{
                  padding:'5px 7px',
                  background: isNear ? 'rgba(255,174,0,0.06)' : 'var(--qe-panel)',
                  border: `1px solid ${isNear?'rgba(255,174,0,0.5)':'var(--qe-line)'}`,
                  opacity: isPast ? 0.55 : 1,
                }}>
                  <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:3}}>
                    <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.58rem', color: isNear?'var(--qe-amber)':'var(--qe-muted)', fontWeight:700}}>{timeLbl}</span>
                    <span style={{display:'inline-flex', alignItems:'center', gap:4}}>
                      <span style={{fontSize:'0.54rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>{e.country}</span>
                      <span style={{...impactStyle, padding:'1px 4px', fontSize:'0.5rem', fontWeight:700, fontFamily:'var(--qe-mono)'}}>{e.impact==='medium'?'MED':e.impact.toUpperCase()}</span>
                    </span>
                  </div>
                  <div style={{fontSize:'0.66rem', fontWeight:600, color: isPast?'var(--qe-sub)':'var(--qe-text)', lineHeight:1.3, marginBottom:3}}>
                    {e.name}{e.unit && <span style={{color:'var(--qe-muted)', fontSize:'0.56rem'}}> ({e.unit})</span>}
                  </div>
                  <div style={{display:'flex', gap:10, fontFamily:'var(--qe-mono)', fontSize:'0.58rem'}}>
                    <span><span style={{color:'var(--qe-muted)'}}>est </span><span style={{color:'var(--qe-sub)'}}>{e.est==null?'—':e.est}</span></span>
                    <span><span style={{color:'var(--qe-muted)'}}>act </span><span style={{color: actColor, fontWeight:700}}>{e.act==null?'—':e.act}</span></span>
                  </div>
                </div>
              );
            });
            return out;
          })()}
        </div>
      </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// Tab: Config
// ─────────────────────────────────────────────────────────────────────────
const THRESHOLD_LABELS = {
  vix_panic:'VIX Panic', vix_defensive:'VIX Defensive', vix_risk_on:'VIX Risk-On', vix_choppy:'VIX Choppy',
  hy_spread_panic:'HY Spread Panic', hy_spread_defensive:'HY Spread Defensive', hy_spread_neutral:'HY Spread Neutral', hy_spread_risk_on:'HY Spread Risk-On',
  rvol_ratio_choppy:'RVol Choppy', rvol_ratio_trending:'RVol Trending',
  funding_panic:'Funding Panic',
  btc_dom_change_bull:'BTC Dom Bull', btc_dom_change_bear:'BTC Dom Bear',
};

const RegimeTabConfig = () => {
  const t = MOCK_REGIME.thresholds;
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={8} h={18} minW={5} minH={6}>
      <Pane title="Classifier Thresholds" style={{height:'100%'}}
        right={<button className="qe-btn qe-btn-sm">↻ Reclassify all dates</button>}
        foot={{tone:'sub', id:4301, msg:'edit individual thresholds in account_settings; reclassify rewrites historical labels', ms:0}}>
        <p style={{fontSize:'0.6rem', color:'var(--qe-sub)', margin:'0 0 6px 0', lineHeight:1.5}}>
          Current threshold values used by the rule-based classifier.
        </p>
        <div style={{display:'flex', flexDirection:'column', gap:1}}>
          {Object.entries(t).map(([k,v]) => (
            <div key={k} style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', padding:'3px 6px', borderBottom:'1px dotted var(--qe-faint)'}}>
              <span style={{fontSize:'0.62rem', color:'var(--qe-sub)'}}>{THRESHOLD_LABELS[k] || k}</span>
              <span className="qe-mono" style={{fontSize:'0.74rem', fontWeight:700, color:'var(--qe-text)'}}>{v}</span>
            </div>
          ))}
        </div>
      </Pane>
      </GridItem>

      <GridItem x={8} y={0} w={16} h={18} minW={8} minH={6}>
      <Pane title="Decision Tree Rules" style={{height:'100%'}}
        foot={{tone:'sub', id:4302, msg:'evaluated top→bottom; first match wins. neutral is the default fallback', ms:0}}>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {[
            {
              label:'Panic', tone:'panic', body:(
                <>VIX &gt; <em>{t.vix_panic}</em> AND (HY Spread &gt; <em>{t.hy_spread_panic}</em> OR Funding &lt; <em>{t.funding_panic}</em>)</>
              ),
            },
            {
              label:'Defensive', tone:'def', body:(
                <>VIX &gt; <em>{t.vix_defensive}</em> OR HY Spread &gt; <em>{t.hy_spread_defensive}</em> OR BTC Dom rising &gt; <em>{t.btc_dom_change_bear}</em>%/wk</>
              ),
            },
            {
              label:'Trending', tone:'trend', body:(
                <>VIX &lt; <em>{t.vix_risk_on}</em> AND RVol &lt; <em>{t.rvol_ratio_trending}</em> <span style={{color:'var(--qe-muted)'}}>(+ OI rising, funding &gt; 0 in full mode)</span></>
              ),
            },
            {
              label:'Choppy', tone:'chop', body:(
                <>VIX &lt; <em>{t.vix_choppy}</em> AND RVol &gt; <em>{t.rvol_ratio_choppy}</em></>
              ),
            },
            {
              label:'Neutral', tone:'neut', body:(
                <span style={{color:'var(--qe-muted)'}}>default fallback when no other rule triggers</span>
              ),
            },
          ].map((rule, i) => {
            const info = REGIME_INFO[REGIME_KEYS.find(k => REGIME_INFO[k].tone === rule.tone)] || REGIME_INFO.neutral;
            return (
              <div key={i} style={{
                background: info.bg, border:'1px solid color-mix(in srgb, '+info.color+' 33%, transparent)', borderLeft: `3px solid ${info.color}`,
                padding:'7px 10px',
              }}>
                <span style={{color:info.color, fontWeight:700, fontSize:'0.72rem', fontFamily:'var(--qe-mono)'}}>{rule.label}:</span>
                <span style={{color:'var(--qe-sub)', fontSize:'0.66rem', marginLeft:6, fontFamily:'var(--qe-mono)'}}>{rule.body}</span>
              </div>
            );
          })}
        </div>
        <style>{`.qe-scope em { color: var(--qe-text); font-style: normal; font-weight: 700; }`}</style>
      </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// Page shell
// ─────────────────────────────────────────────────────────────────────────
const REGIME_TABS = [
  ['overview','Overview'],
  ['backfill','Backfill'],
  ['news','News'],
  ['config','Config'],
];

const RegimePage = () => {
  const [tab, setTab] = React.useState('overview');
  const content = {
    overview: <RegimeTabOverview/>,
    backfill: <RegimeTabBackfill/>,
    news:     <RegimeTabNews/>,
    config:   <RegimeTabConfig/>,
  };
  const tabSubtitles = {
    overview:'current regime · distribution · timeline · macro signals · changes',
    backfill:'fetch historical macro signals · signal coverage',
    news:'finnhub + bwe streams · economic calendar',
    config:'classifier thresholds · decision tree rules',
  };
  return (
    <div className="qe-scope" data-screen-label="07 Regime" style={{
      width:'100%', height:'100%', background:'var(--qe-bg)',
      display:'flex', flexDirection:'column', overflow:'hidden',
    }}>
      <TopNavStd page="Regime" variant="line" dense/>

      <PageHeader title="Regime" subtitle={tabSubtitles[tab]}>
        <RegimeBadge tone={REGIME_INFO[MOCK_REGIME.current.label].tone} label={REGIME_INFO[MOCK_REGIME.current.label].label.toUpperCase()}/>
        <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.6rem', color:'var(--qe-cyan)', fontWeight:700}}>
          {REGIME_INFO[MOCK_REGIME.current.label].mult} size
        </span>
        <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-muted)'}}>as of {MOCK_REGIME.current.computed}</span>
      </PageHeader>

      <TabStrip value={tab} onChange={setTab} tabs={REGIME_TABS}/>

      <div style={{flex:1, minHeight:0, overflow:'auto', display:'flex', flexDirection:'column'}}>
        {content[tab]}
      </div>
      <StatusFooter/>
    </div>
  );
};

Object.assign(window, {
  RegimePage,
  // exported for pages-regime-v2.jsx — a proposed alternative loaded only by
  // the v25/index.html design canvas, not by the v3.0 app
  REGIME_KEYS, REGIME_INFO, REGIME_HEX,
  MOCK_REGIME, MOCK_REGIME_TIMELINE,
  TimelineSvg, RegimeLegend,
  RegimeTabBackfill, RegimeTabConfig, RegimeTabNews,
});
