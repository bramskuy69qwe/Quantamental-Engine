/* QE v2.5 — Analytics: Execution Quality + Distributions
   Ported from prior qe-analytics-exec.jsx and qe-analytics.jsx (Distributions tab).
   Uses v25 standardized primitives: Pane, Card, DataList, Lbl, SecLbl, Badge.
   ────────────────────────────────────────────────────────────────────────
   v2.4 schema: execution_log.{calc_id, fill_type, slippage_actual},
                 pre_trade_log.{calc_id, est_fill_price}
   Tolerance:  EXEC_LINK_PRICE_TOL = 0.0005 (0.05%)
*/

// ── Execution data ───────────────────────────────────────────────────────
const EXEC_DATA = [
  // entry fills
  {id:'EX-0841',time:'04-04 15:13',sym:'JCTUSDT',  ft:'entry',se:0.0021,sa:0.0031,lat:12.4,ot:'LIMIT',      role:'Maker',calcId:'CALC-7f3a',link:'auto'},
  {id:'EX-0831',time:'04-04 12:44',sym:'BTCUSDT',  ft:'entry',se:0.0010,sa:0.0012,lat:8.1, ot:'LIMIT',      role:'Maker',calcId:'CALC-8a12',link:'auto'},
  {id:'EX-0801',time:'04-03 13:09',sym:'STOUSDT',  ft:'entry',se:0.0015,sa:0.0018,lat:15.2,ot:'LIMIT',      role:'Maker',calcId:'CALC-9c44',link:'auto'},
  {id:'EX-0821',time:'04-04 12:42',sym:'AIOTUSDT', ft:'entry',se:0.0028,sa:0.0041,lat:22.7,ot:'LIMIT',      role:'Maker',calcId:'CALC-5d91',link:'confirmed'},
  {id:'EX-0891',time:'04-05 13:10',sym:'PUFFERUSDT',ft:'entry',se:0.0018,sa:0.0025,lat:5.3, ot:'MARKET',     role:'Taker',calcId:'CALC-2e78',link:'auto'},
  {id:'EX-0836',time:'04-02 16:36',sym:'STOUSDT',  ft:'entry',se:0.0018,sa:0.0021,lat:11.8,ot:'LIMIT',      role:'Maker',calcId:'CALC-1b56',link:'auto'},
  {id:'EX-0855',time:'04-07 10:20',sym:'STOUSDT',  ft:'entry',se:0.0012,sa:0.0010,lat:9.8, ot:'LIMIT',      role:'Maker',calcId:'CALC-6b77',link:'auto'},
  {id:'EX-0866',time:'04-09 08:45',sym:'STOUSDT',  ft:'entry',se:0.0018,sa:0.0022,lat:16.3,ot:'LIMIT',      role:'Maker',calcId:'CALC-7c88',link:'auto'},
  {id:'EX-0877',time:'04-11 11:10',sym:'STOUSDT',  ft:'entry',se:0.0015,sa:0.0028,lat:31.2,ot:'LIMIT',      role:'Maker',calcId:'CALC-8d99',link:'confirmed'},
  {id:'EX-0888',time:'04-14 10:55',sym:'STOUSDT',  ft:'entry',se:0.0010,sa:0.0008,lat:7.4, ot:'LIMIT',      role:'Maker',calcId:'CALC-9e11',link:'auto'},
  {id:'EX-0899',time:'04-15 10:05',sym:'STOUSDT',  ft:'entry',se:0.0016,sa:0.0019,lat:13.1,ot:'LIMIT',      role:'Maker',calcId:'CALC-0f22',link:'auto'},
  {id:'EX-0910',time:'04-16 09:12',sym:'STOUSDT',  ft:'entry',se:0.0020,sa:0.0035,lat:44.7,ot:'LIMIT',      role:'Maker',calcId:'CALC-1a33',link:'partial_2'},
  // tp fills
  {id:'EX-0842',time:'04-04 15:16',sym:'JCTUSDT',  ft:'tp',   se:0.0008,sa:0.0009,lat:4.2, ot:'LIMIT',      role:'Maker',calcId:'CALC-7f3a',link:'auto'},
  {id:'EX-0802',time:'04-03 13:15',sym:'STOUSDT',  ft:'tp',   se:0.0012,sa:0.0011,lat:6.8, ot:'MARKET',     role:'Taker',calcId:'CALC-9c44',link:'auto'},
  {id:'EX-0822',time:'04-04 12:43',sym:'AIOTUSDT', ft:'tp',   se:0.0010,sa:0.0013,lat:3.9, ot:'MARKET',     role:'Taker',calcId:'CALC-5d91',link:'auto'},
  // sl fills (stop market)
  {id:'EX-0838',time:'04-02 16:37',sym:'STOUSDT',  ft:'sl',   se:0.0022,sa:0.0048,lat:18.4,ot:'STOP_MARKET',role:'Taker',calcId:'CALC-1b56',link:'auto'},
  {id:'EX-0918',time:'04-08 11:22',sym:'STOUSDT',  ft:'sl',   se:0.0025,sa:0.0062,lat:24.1,ot:'STOP_MARKET',role:'Taker',calcId:'CALC-3f22',link:'partial_1'},
  {id:'EX-0932',time:'04-10 14:55',sym:'STOUSDT',  ft:'sl',   se:0.0020,sa:0.0031,lat:14.6,ot:'STOP_MARKET',role:'Taker',calcId:'CALC-4a88',link:'auto'},
  // manual / pre-v2.4 fills — no calc_id, excluded from bias
  {id:'EX-0911',time:'04-06 09:15',sym:'STOUSDT',  ft:'manual',se:null,sa:0.0055,lat:8.2, ot:'MARKET',     role:'Taker',calcId:null,        link:'unlinked'},
  {id:'EX-0944',time:'04-12 16:30',sym:'BTCUSDT',  ft:'manual',se:null,sa:0.0022,lat:6.1, ot:'MARKET',     role:'Taker',calcId:null,        link:'unlinked'},
];

const FT_COLOR = {
  entry:  'var(--qe-blue)',
  tp:     'var(--qe-green)',
  sl:     'var(--qe-red)',
  manual: 'var(--qe-muted)',
};
const EXEC_LINK_META = {
  auto:      {label:'Auto-linked (3/3)', color:'var(--qe-green)', bg:'rgba(0,255,127,0.06)'},
  confirmed: {label:'Confirmed',         color:'var(--qe-cyan)',  bg:'rgba(0,231,255,0.05)'},
  partial_2: {label:'Partial 2/3',       color:'var(--qe-amber)', bg:'rgba(255,174,0,0.06)'},
  partial_1: {label:'Partial 1/3',       color:'color-mix(in srgb, var(--qe-amber) 65%, var(--qe-red))', bg:'color-mix(in srgb, var(--qe-amber) 7%, transparent)'},
  unlinked:  {label:'Unlinked',          color:'var(--qe-red)',   bg:'rgba(255,45,74,0.06)'},
};

// ── shared helpers ───────────────────────────────────────────────────────
const _lerp = (v,i0,i1,o0,o1) => i1===i0 ? (o0+o1)/2 : o0+((v-i0)/(i1-i0))*(o1-o0);

// ═════════════════════════════════════════════════════════════════════════
// ECharts — execution-quality charts (theme/helpers shared from charts.jsx)
// ═════════════════════════════════════════════════════════════════════════

// Histogram (latency / slippage / generic distribution) — bars + top value labels.
// divergent: color each bar green/red by its `.pos` flag (PnL/R-multiple/win-rate).
// noun: tooltip unit noun (default "fill"). unit: axis-value suffix (e.g. "ms","bp").
const ExecHistChart = ({bins, color='var(--qe-cyan)', height=120, unit='', divergent=false, noun='fill'}) => {
  const ref = React.useRef(null);
  const c = _qeResolveColor(color);
  const green = QE_ECHARTS_THEME.green, red = QE_ECHARTS_THEME.red;
  const barColor = i => divergent ? (bins[i] && bins[i].pos ? green : red) : c;
  const opts = React.useMemo(() => ({
    ..._baseChart({grid:{left:30, right:10, top:18, bottom:20}}),
    tooltip: {
      trigger:'axis', backgroundColor:'#000', borderColor: QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[4,8],
      textStyle:{color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace'},
      axisPointer:{ type:'shadow', shadowStyle:{ color: (divergent?green:c)+'22' } },
      formatter: p => `${p[0].axisValue || '—'}${unit} · ${p[0].data} ${noun}${p[0].data===1?'':'s'}`,
    },
    xAxis: { type:'category', data: bins.map(b=>b.label),
      ..._axis({ axisLabel:{ color:QE_ECHARTS_THEME.muted, fontSize:9, fontFamily:'JetBrains Mono, monospace' }, splitLine:{show:false} }) },
    yAxis: { type:'value', minInterval:1,
      ..._axis({ axisLabel:{ color:QE_ECHARTS_THEME.muted, fontSize:9, fontFamily:'JetBrains Mono, monospace' },
        splitLine:{ lineStyle:{ color:QE_ECHARTS_THEME.faint, opacity:0.4, type:[2,3] } } }) },
    series: [{ type:'bar', barWidth:'62%',
      data: bins.map((b,i) => ({ value:b.count, itemStyle:{ color:barColor(i), opacity:0.82 } })),
      emphasis:{ itemStyle:{ opacity:1 } },
      label:{ show:true, position:'top', fontSize:9, fontFamily:'JetBrains Mono, monospace',
        color: divergent ? QE_ECHARTS_THEME.sub : c,
        formatter: x => x.value>0 ? x.value : '' } }],
  }), [bins, c, unit, divergent, noun]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} style={{width:'100%', height}}/>;
};

// Diverging bars around a zero midline (avg-PnL-by-DoW style), green up / red down.
const ExecDivergingBars = ({rows, height=120, fmt = v=>v.toFixed(2)}) => {
  const ref = React.useRef(null);
  const green = QE_ECHARTS_THEME.green, red = QE_ECHARTS_THEME.red;
  const opts = React.useMemo(() => ({
    ..._baseChart({grid:{left:34, right:10, top:16, bottom:30}}),
    tooltip:{ trigger:'axis', backgroundColor:'#000', borderColor:QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[4,8],
      textStyle:{color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace'},
      axisPointer:{ type:'shadow', shadowStyle:{ color:'#ffffff10' } },
      formatter: p => { const r = rows[p[0].dataIndex];
        return `${r.label} · ${(r.v>=0?'+':'')+fmt(r.v)} · ${r.n} trade${r.n===1?'':'s'}`; } },
    xAxis:{ type:'category', data: rows.map(r=>r.label),
      ..._axis({ axisLabel:{ color:QE_ECHARTS_THEME.muted, fontSize:9, fontFamily:'JetBrains Mono, monospace' }, splitLine:{show:false} }) },
    yAxis:{ type:'value',
      ..._axis({ axisLabel:{ color:QE_ECHARTS_THEME.muted, fontSize:9, fontFamily:'JetBrains Mono, monospace', formatter:v=>v.toFixed(1) },
        splitLine:{ lineStyle:{ color:QE_ECHARTS_THEME.faint, opacity:0.4, type:[2,3] } } }) },
    series:[{ type:'bar', barWidth:'56%',
      data: rows.map(r => ({ value:r.n>0?r.v:0,
        itemStyle:{ color: r.v>=0?green:red, opacity:0.82 } })),
      markLine:{ symbol:'none', silent:true,
        data:[{ yAxis:0, lineStyle:{ color:QE_ECHARTS_THEME.line, width:1 }, label:{show:false} }] },
      emphasis:{ itemStyle:{ opacity:1 } },
      label:{ show:true, fontSize:9, fontFamily:'JetBrains Mono, monospace', color:QE_ECHARTS_THEME.sub,
        position:'top', formatter: x => { const r=rows[x.dataIndex];
          return (r.n>0 && Math.abs(r.v)>0.005) ? (r.v>=0?'+':'')+fmt(r.v) : ''; } } }],
  }), [rows, fmt]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} style={{width:'100%', height}}/>;
};

// Slippage scatter — estimated vs actual, colored by fill type, y=x no-bias line
const ExecScatterChart = ({points, maxBp, height=240}) => {
  const ref = React.useRef(null);
  const opts = React.useMemo(() => {
    const data = points.map(p => {
      const eb = p.se*10000, ab = p.sa*10000, above = ab>eb;
      return { value:[eb, ab], name:p.id,
        itemStyle:{ color:_qeResolveColor(FT_COLOR[p.ft]||'var(--qe-sub)'), opacity:0.82,
          borderColor: above ? QE_ECHARTS_THEME.red : 'transparent', borderWidth: above?1.6:0 },
        _ft:p.ft, _est:eb, _act:ab };
    });
    return {
      ..._baseChart({grid:{left:46, right:16, top:14, bottom:40}}),
      tooltip:{ trigger:'item', backgroundColor:'#000', borderColor:QE_ECHARTS_THEME.cyan, borderWidth:1, padding:[4,8],
        textStyle:{color:QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace'},
        formatter: o => { const d=o.data; const bias=d._act-d._est;
          return `<b>${d.name}</b> · ${d._ft}<br/>est&nbsp;&nbsp;&nbsp;${d._est.toFixed(2)}bp<br/>actual ${d._act.toFixed(2)}bp<br/>bias&nbsp;&nbsp;${(bias>=0?'+':'')+bias.toFixed(2)}bp`; } },
      xAxis:{ type:'value', min:0, max:maxBp, name:'Estimated (bp)', nameLocation:'center', nameGap:24,
        nameTextStyle:{color:QE_ECHARTS_THEME.sub, fontSize:10}, ..._axis() },
      yAxis:{ type:'value', min:0, max:maxBp, name:'Actual (bp)', nameLocation:'middle', nameGap:32, nameRotate:90,
        nameTextStyle:{color:QE_ECHARTS_THEME.sub, fontSize:10}, ..._axis() },
      series:[
        { type:'line', silent:true, symbol:'none', data:[[0,0],[maxBp,maxBp]],
          lineStyle:{ color:QE_ECHARTS_THEME.muted, type:'dashed', width:1 }, tooltip:{show:false}, z:1 },
        { type:'scatter', data, symbolSize:11, z:2,
          emphasis:{ scale:1.3, itemStyle:{ opacity:1 } } },
      ],
    };
  }, [points, maxBp]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} style={{width:'100%', height}}/>;
};

// ═════════════════════════════════════════════════════════════════════════
// EXECUTION QUALITY TAB
// ═════════════════════════════════════════════════════════════════════════
const TabExecution = () => {
  const [ftFilter, setFtFilter] = React.useState('all');

  const total = EXEC_DATA.length;
  const linked = EXEC_DATA.filter(e => e.link==='auto' || e.link==='confirmed').length;
  const calcBkd = EXEC_DATA.filter(e => e.calcId).length;

  // Bias calc — entry fills with calc_id only
  const entryCalc = EXEC_DATA.filter(e => e.ft==='entry' && e.se != null);
  const avgActBp = entryCalc.reduce((s,e)=>s+e.sa, 0)/entryCalc.length * 10000;
  const avgEstBp = entryCalc.reduce((s,e)=>s+e.se, 0)/entryCalc.length * 10000;
  const biasBp   = avgActBp - avgEstBp;

  const lats   = [...EXEC_DATA.map(e=>e.lat)].sort((a,b)=>a-b);
  const avgLat = lats.reduce((s,v)=>s+v,0)/lats.length;
  const p95Lat = lats[Math.floor(lats.length*0.95)];
  const maxLat = Math.max(...lats);

  const linkBreak = Object.keys(EXEC_LINK_META).map(k => ({
    key:k, ...EXEC_LINK_META[k],
    n: EXEC_DATA.filter(e=>e.link===k).length,
  }));

  const ftStats = ['entry','tp','sl','manual'].map(ft => {
    const es = EXEC_DATA.filter(e=>e.ft===ft && e.sa != null);
    return {ft, n:es.length, avgBp: es.length ? es.reduce((s,e)=>s+e.sa,0)/es.length*10000 : 0};
  });
  const maxFtBp = Math.max(...ftStats.map(f=>f.avgBp), 0.1);

  const latBins = [[0,5],[5,10],[10,20],[20,30],[30,50],[50,200]].map(([lo,hi]) => ({
    label: hi===200 ? `${lo}+` : `${lo}-${hi}`,
    count: EXEC_DATA.filter(e => e.lat>=lo && e.lat<hi).length,
  }));

  // 5bp-wide bins spanning the actual entry-slippage range (avg ~22bp)
  const SLIP_STEP = 5;
  const slipMax = Math.max(5, Math.ceil(Math.max(...entryCalc.map(e=>e.sa*10000), 0)/SLIP_STEP)*SLIP_STEP);
  const slipBins = Array.from({length: slipMax/SLIP_STEP}, (_,i) => {
    const lo = i*SLIP_STEP, hi = lo+SLIP_STEP;
    return {
      label: `${lo}-${hi}`,
      count: entryCalc.filter(e => { const bp = e.sa*10000; return bp>=lo && bp<hi; }).length,
    };
  });

  // Scatter geometry
  const scatter = EXEC_DATA.filter(e => e.se != null && e.sa != null);
  const maxSBp = Math.max(...scatter.flatMap(e => [e.se, e.sa].map(v => v*10000)), 1) * 1.18;
  const SH = 180, SP = 32;
  const sx = v => SP + _lerp(v, 0, maxSBp, 0, 1000-2*SP);
  const sy = v => SH - SP - _lerp(v, 0, maxSBp, 0, SH-2*SP);

  // Per-fill table data
  const tableData = ftFilter==='all' ? EXEC_DATA : EXEC_DATA.filter(e => e.ft===ftFilter);
  const tableRows = [...tableData].sort((a,b) => b.time.localeCompare(a.time));

  return (
    <GridWorkspace>

      {/* ── KPI strip — 5 panes ── */}
      {[
        {l:'Exec Link Coverage', v:`${(linked/total*100).toFixed(1)}%`, sub:`${linked}/${total} fully linked`,
         tone: linked/total>0.8 ? 'var(--qe-green)' : 'var(--qe-amber)',
         foot:{tone:'ok', id:4201, msg:`reconciler ok · ${linked}/${total} linked auto+confirmed`, ms:6}},
        {l:'Calc-Backed Fills',  v:`${(calcBkd/total*100).toFixed(0)}%`, sub:`${calcBkd} with calc_id · v2.4+`,
         tone:'var(--qe-blue)',
         foot:{tone:'sub', id:4202, msg:`${total-calcBkd} pre-v2.4 / manual excluded from bias`, ms:1}},
        {l:'Avg Entry Slip',     v:`${avgActBp.toFixed(2)}bp`, sub:`estimated ${avgEstBp.toFixed(2)}bp`,
         tone:'var(--qe-text)',
         foot:{tone:'info', id:4203, msg:`n=${entryCalc.length} entry fills · calc-backed only`, ms:2}},
        {l:'Slip Bias',          v:`${biasBp>=0?'+':''}${biasBp.toFixed(2)}bp`,
         sub: biasBp > 0 ? 'model underestimates' : 'model overestimates',
         tone: Math.abs(biasBp)<0.5 ? 'var(--qe-green)' : 'var(--qe-amber)',
         foot:{tone:'warn', id:4204, msg:`feeds v2.6 backtest slippage model calibration`, ms:4}},
        {l:'P95 Latency',        v:`${p95Lat.toFixed(0)}ms`, sub:`avg ${avgLat.toFixed(1)}ms · max ${maxLat.toFixed(0)}ms`,
         tone: p95Lat > 40 ? 'var(--qe-amber)' : 'var(--qe-green)',
         foot:{tone: p95Lat>40?'warn':'ok', id:4205, msg:`signal→fill latency · ${EXEC_DATA.length} samples`, ms:p95Lat>40?12:3}},
      ].map(({l, v, sub, tone, foot}, i) => (
        <GridItem key={l} x={i<4 ? i*4 : 16} y={0} w={i===4?8:4} h={3} minW={3} minH={3}>
        <Pane title={l} style={{height:'100%'}}
          foot={foot}>
          <div style={{display:'flex', flexDirection:'column', gap:4}}>
            <div className="qe-mono" style={{fontSize:'1.1rem', fontWeight:700, color:tone, lineHeight:1.1}}>{v}</div>
            <div style={{fontSize:'0.58rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', lineHeight:1.4}}>{sub}</div>
          </div>
        </Pane>
        </GridItem>
      ))}

      {/* ── Exec link breakdown ── */}
      <GridItem x={0} y={3} w={12} h={6} minW={6} minH={6}>
      <Pane title="Exec Link Status" style={{height:'100%'}}
        foot={{tone:'sub', id:4210, msg:`reconciler tolerance EXEC_LINK_PRICE_TOL=0.0005`, ms:0}}>
        {/* stacked bar */}
        <div style={{display:'flex', height:12, marginBottom:8, gap:1, background:'var(--qe-panel)'}}>
          {linkBreak.filter(b=>b.n>0).map(b => (
            <div key={b.key} title={`${b.label}: ${b.n}`} style={{flex:b.n, background:b.color, opacity:0.85}}/>
          ))}
        </div>
        {linkBreak.map(b => (
          <div key={b.key} style={{
            display:'flex', alignItems:'center', justifyContent:'space-between',
            padding:'3px 6px', background:b.bg, marginBottom:2,
            borderLeft:`2px solid ${b.color}`,
          }}>
            <span className="qe-mono" style={{fontSize:'0.62rem', fontWeight:700, color:b.color}}>{b.label}</span>
            <div style={{display:'flex', gap:10, alignItems:'baseline'}}>
              <span className="qe-mono" style={{fontSize:'0.66rem', color:b.color, fontWeight:700}}>{b.n}</span>
              <span className="qe-mono" style={{fontSize:'0.58rem', color:'var(--qe-muted)'}}>{(b.n/total*100).toFixed(0)}%</span>
            </div>
          </div>
        ))}
        <div style={{fontSize:'0.56rem', color:'var(--qe-muted)', lineHeight:1.5, marginTop:6,
                     borderTop:'1px solid var(--qe-faint)', paddingTop:4}}>
          Requires <span className="qe-mono" style={{color:'var(--qe-cyan)'}}>calc_id</span> in
          <span className="qe-mono" style={{color:'var(--qe-sub)'}}> execution_log</span>.
          Pre-v2.4 and manual fills surface as Unlinked.
        </div>
      </Pane>
      </GridItem>

      {/* ── Slippage by fill type ── */}
      <GridItem x={12} y={3} w={12} h={6} minW={6} minH={6}>
      <Pane title="Avg Slippage by Fill Type" tag="bp" style={{height:'100%'}}
        foot={{tone:'info', id:4211, msg:'sl highest — stop_market in volatile conds; tp lowest — resting limit', ms:1}}>
        {ftStats.map(({ft, n, avgBp}) => (
          <div key={ft} style={{display:'flex', alignItems:'center', gap:8, marginBottom:6}}>
            <span className="qe-mono" style={{fontSize:'0.62rem', fontWeight:700, color:FT_COLOR[ft], width:56, flexShrink:0}}>{ft}</span>
            <div style={{flex:1, height:10, background:'var(--qe-panel)', border:'1px solid var(--qe-faint)'}}>
              <div style={{width: n>0 ? `${(avgBp/maxFtBp*100).toFixed(1)}%`:'0%', height:'100%', background:FT_COLOR[ft], opacity:0.8}}/>
            </div>
            <span className="qe-mono" style={{fontSize:'0.62rem', fontWeight:700, color:FT_COLOR[ft], width:48, textAlign:'right', flexShrink:0}}>
              {n>0 ? avgBp.toFixed(1)+'bp' : '—'}
            </span>
            <span className="qe-mono" style={{fontSize:'0.56rem', color:'var(--qe-muted)', width:26, textAlign:'right', flexShrink:0}}>×{n}</span>
          </div>
        ))}
        <div className="qe-divider-h" style={{margin:'6px 0'}}/>
        <div style={{fontSize:'0.56rem', color:'var(--qe-muted)', lineHeight:1.5}}>
          Entry slippage distribution (below) feeds the v2.6 backtest slippage model.
        </div>
      </Pane>
      </GridItem>

      {/* ── Scatter: estimated vs actual ── */}
      <GridItem x={0} y={9} w={24} h={8} minW={10} minH={7}>
      <Pane title="Slippage: Estimated vs Actual" tag="calc-backed"
        style={{height:'100%'}}
        right={
          <div style={{display:'flex', gap:10, alignItems:'center'}}>
            {['entry','tp','sl'].map(ft => (
              <span key={ft} style={{display:'inline-flex', alignItems:'center', gap:4, fontSize:'0.56rem', color:FT_COLOR[ft]}}>
                <span style={{display:'inline-block', width:6, height:6, borderRadius:'50%', background:FT_COLOR[ft]}}/>{ft}
              </span>
            ))}
            <span style={{fontSize:'0.54rem', color:'var(--qe-muted)'}}>○ red ring = actual {'>'} estimated</span>
          </div>
        }
        foot={{tone: Math.abs(biasBp)<0.5?'ok':'warn', id:4220,
               msg:`bias ${biasBp>=0?'+':''}${biasBp.toFixed(2)}bp · n=${scatter.length} calc-backed fills`, ms:8}}
        bodyStyle={{padding:'8px 10px'}}>
        <ExecScatterChart points={scatter} maxBp={maxSBp} height="100%"/>
      </Pane>
      </GridItem>

      {/* ── Latency distribution ── */}
      <GridItem x={0} y={17} w={12} h={6} minW={6} minH={5}>
      <Pane title="Latency Distribution" tag="ms"
        style={{height:'100%'}}
        bodyStyle={{display:'flex', flexDirection:'column'}}
        foot={{tone:'sub', id:4230, msg:`signal→fill confirmation · avg ${avgLat.toFixed(1)}ms · p95 ${p95Lat.toFixed(0)}ms`, ms:1}}>
        <div style={{flex:1, minHeight:0}}><ExecHistChart bins={latBins} color="var(--qe-cyan)" unit="ms" height="100%"/></div>
        <div style={{display:'flex', gap:14, marginTop:6, fontSize:'0.58rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>
          <span>avg {avgLat.toFixed(1)}ms</span>
          <span>p95 {p95Lat.toFixed(0)}ms</span>
          <span>max {maxLat.toFixed(0)}ms</span>
          <span style={{marginLeft:'auto', color:p95Lat>40?'var(--qe-amber)':'var(--qe-green)'}}>p95 {p95Lat>40?'WARN':'OK'} ≤ 40ms target</span>
        </div>
      </Pane>
      </GridItem>

      {/* ── Entry slip distribution ── */}
      <GridItem x={12} y={17} w={12} h={6} minW={6} minH={5}>
      <Pane title="Entry Slippage Distribution" tag="bp"
        style={{height:'100%'}}
        bodyStyle={{display:'flex', flexDirection:'column'}}
        foot={{tone:'sub', id:4231, msg:`calc-backed entry fills · avg ${avgActBp.toFixed(2)}bp`, ms:0}}>
        <div style={{flex:1, minHeight:0}}><ExecHistChart bins={slipBins} color="var(--qe-blue)" unit="bp" height="100%"/></div>
        <div style={{fontSize:'0.58rem', color:'var(--qe-muted)', marginTop:6, fontFamily:'var(--qe-mono)'}}>
          {(() => {
            const std = Math.sqrt(entryCalc.reduce((s,e)=>{const d=e.sa*10000-avgActBp;return s+d*d;},0)/entryCalc.length);
            return `avg ${avgActBp.toFixed(2)}bp · std ${std.toFixed(2)}bp · n=${entryCalc.length}`;
          })()}
        </div>
      </Pane>
      </GridItem>

      {/* ── Order Type Mix ── */}
      <GridItem x={0} y={23} w={12} h={5} minW={6} minH={5}>
      <Pane title="Order Type Mix" style={{height:'100%'}}
        foot={{tone:'sub', id:4240, msg:'LIMIT = maker preferred (rebate); STOP_MARKET = SL execution', ms:0}}>
        {['LIMIT','MARKET','STOP_MARKET'].map(ot => {
          const n = EXEC_DATA.filter(e=>e.ot===ot).length;
          const c = ot==='LIMIT' ? 'var(--qe-green)' : ot==='MARKET' ? 'var(--qe-blue)' : 'var(--qe-red)';
          return (
            <div key={ot} style={{display:'flex', alignItems:'center', gap:8, marginBottom:6}}>
              <span className="qe-mono" style={{fontSize:'0.62rem', color:c, width:110, flexShrink:0}}>{ot}</span>
              <div style={{flex:1, height:8, background:'var(--qe-panel)', border:'1px solid var(--qe-faint)'}}>
                <div style={{width:`${(n/total*100).toFixed(1)}%`, height:'100%', background:c, opacity:0.8}}/>
              </div>
              <span className="qe-mono" style={{fontSize:'0.62rem', color:'var(--qe-text)', width:24, textAlign:'right', flexShrink:0}}>{n}</span>
              <span className="qe-mono" style={{fontSize:'0.56rem', color:'var(--qe-muted)', width:34, textAlign:'right', flexShrink:0}}>{(n/total*100).toFixed(0)}%</span>
            </div>
          );
        })}
      </Pane>
      </GridItem>

      {/* ── Maker / Taker Split ── */}
      <GridItem x={12} y={23} w={12} h={5} minW={6} minH={5}>
      <Pane title="Maker / Taker Split" style={{height:'100%'}}
        foot={{tone:'sub', id:4241, msg:'maker rebates lower effective fee drag', ms:0}}>
        {['Maker','Taker'].map(role => {
          const n = EXEC_DATA.filter(e=>e.role===role).length;
          const c = role==='Maker' ? 'var(--qe-green)' : 'var(--qe-amber)';
          return (
            <div key={role} style={{display:'flex', alignItems:'center', gap:8, marginBottom:6}}>
              <span className="qe-mono" style={{fontSize:'0.62rem', color:c, width:60, flexShrink:0}}>{role}</span>
              <div style={{flex:1, height:8, background:'var(--qe-panel)', border:'1px solid var(--qe-faint)'}}>
                <div style={{width:`${(n/total*100).toFixed(1)}%`, height:'100%', background:c, opacity:0.8}}/>
              </div>
              <span className="qe-mono" style={{fontSize:'0.62rem', color:'var(--qe-text)', width:24, textAlign:'right', flexShrink:0}}>{n}</span>
              <span className="qe-mono" style={{fontSize:'0.56rem', color:'var(--qe-muted)', width:34, textAlign:'right', flexShrink:0}}>{(n/total*100).toFixed(0)}%</span>
            </div>
          );
        })}
        <div className="qe-divider-h" style={{margin:'8px 0 4px'}}/>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6, fontSize:'0.58rem', fontFamily:'var(--qe-mono)'}}>
          <div style={{display:'flex', justifyContent:'space-between'}}>
            <span style={{color:'var(--qe-muted)'}}>maker fee</span>
            <span style={{color:'var(--qe-green)'}}>0.020%</span>
          </div>
          <div style={{display:'flex', justifyContent:'space-between'}}>
            <span style={{color:'var(--qe-muted)'}}>taker fee</span>
            <span style={{color:'var(--qe-amber)'}}>0.050%</span>
          </div>
        </div>
      </Pane>
      </GridItem>

      {/* ── Per-fill log table ── */}
      <GridItem x={0} y={28} w={24} h={14} minW={10} minH={8}>
      <Pane title="Per-Fill Log" count={tableRows.length} tag="SSE"
        style={{height:'100%'}}
        right={
          <div style={{display:'flex', gap:3}}>
            {['all','entry','tp','sl','manual'].map(f => (
              <button key={f} onClick={()=>setFtFilter(f)}
                className={`qe-btn qe-btn-sm ${ftFilter===f?'qe-btn-primary':''}`}
                style={{
                  color: ftFilter===f ? 'var(--qe-bg)' : (FT_COLOR[f] || 'var(--qe-sub)'),
                  textTransform:'uppercase', letterSpacing:'0.04em',
                }}>{f}</button>
            ))}
          </div>
        }
        foot={{tone:'info', id:4250, msg:`execution_log stream · ${tableRows.length} rows · last EX-${tableRows[0]?.id?.slice(3)||'—'}`, ms:14}}
        bodyStyle={{padding:0, display:'flex', flexDirection:'column'}}>
        <DataList
          selKey="id"
          columns={[
            {key:'time',  label:'TIME',   render:r => <span style={{color:'var(--qe-sub)'}}>{r.time}</span>},
            {key:'sym',   label:'SYM',    render:r => <span style={{color:'var(--qe-cyan)', fontWeight:700}}>{r.sym}</span>},
            {key:'ft',    label:'FILL',   render:r => <span style={{color:FT_COLOR[r.ft], fontWeight:700, textTransform:'uppercase', letterSpacing:'0.04em', fontSize:'0.58rem'}}>{r.ft}</span>},
            {key:'ot',    label:'TYPE',   render:r => <span style={{color:'var(--qe-muted)'}}>{r.ot}</span>},
            {key:'se',    label:'EST',    align:'right', render:r => <span style={{color:'var(--qe-sub)'}}>{r.se!=null ? (r.se*10000).toFixed(1)+'bp' : '—'}</span>},
            {key:'sa',    label:'ACTUAL', align:'right', render:r => {
              const bp = r.sa*10000;
              return <span style={{color: bp>5 ? 'var(--qe-amber)' : 'var(--qe-text)', fontWeight:700}}>{bp.toFixed(1)}bp</span>;
            }},
            {key:'bias',  label:'BIAS',   align:'right', render:r => {
              if (r.se == null) return <span style={{color:'var(--qe-muted)'}}>—</span>;
              const bias = (r.sa-r.se)*10000;
              return <span style={{color: bias>0 ? 'var(--qe-red)' : 'var(--qe-green)', fontWeight:700}}>{(bias>=0?'+':'')+bias.toFixed(1)+'bp'}</span>;
            }},
            {key:'lat',   label:'LAT',    align:'right', render:r => <span style={{color: r.lat>30 ? 'var(--qe-amber)' : 'var(--qe-text)'}}>{r.lat.toFixed(1)}ms</span>},
            {key:'role',  label:'ROLE',   render:r => <Badge tone={r.role==='Maker'?'ok':'warn'}>{r.role.toUpperCase()}</Badge>},
            {key:'link',  label:'LINK',   render:r => {
              const m = EXEC_LINK_META[r.link];
              return <span style={{color:m.color, fontWeight:700, fontSize:'0.58rem'}}>{m.label}</span>;
            }},
            {key:'calcId',label:'CALC ID',render:r => <span style={{color: r.calcId ? 'var(--qe-sub)' : 'var(--qe-muted)'}}>{r.calcId ? r.calcId.slice(-8) : '—'}</span>},
          ]}
          rows={tableRows}
          emptyMsg="No fills match this filter"
          summary={<>
            <span>{tableRows.length} fills · {EXEC_DATA.filter(e=>e.role==='Maker').length} maker · {EXEC_DATA.filter(e=>e.role==='Taker').length} taker</span>
            <span style={{color:'var(--qe-cyan)'}}>avg lat {avgLat.toFixed(1)}ms · p95 {p95Lat.toFixed(0)}ms</span>
          </>}
        />
      </Pane>
      </GridItem>

    </GridWorkspace>
  );
};

// ═════════════════════════════════════════════════════════════════════════
// DISTRIBUTIONS TAB
// ═════════════════════════════════════════════════════════════════════════
const TabDistributions = ({periodLbl}) => {
  // Mock trade list — derived from MOCK_ANALYTICS pairs for consistency
  // hour: 0-23, dow: 0=Mon..6=Sun, hold: minutes, r: R-multiple
  const TRADES = React.useMemo(() => {
    // Generate 31 trades reproducible from a seed
    let s = 1;
    const rnd = () => { s = (s * 9301 + 49297) % 233280; return s/233280; };
    return Array.from({length:31}, (_,i) => {
      const pnl = +((rnd()-0.55) * 3.4).toFixed(2);
      const r = +(pnl/1.20).toFixed(2);
      return {
        pnl, r,
        hold: Math.round(10 + rnd()*470),
        hour: Math.floor(rnd()*24),
        dow:  Math.floor(rnd()*7),
      };
    });
  }, []);

  const PNL_EDGES = [-5,-4,-3,-2,-1,0,1,2,3,4,5,6,7,8];
  const pnlBins = PNL_EDGES.slice(0,-1).map((lo,i) => ({
    label: `${lo>0?'+':''}${lo}`,
    count: TRADES.filter(t=>t.pnl>=lo && t.pnl<PNL_EDGES[i+1]).length,
    pos: lo >= 0,
  }));

  const R_EDGES = [-4,-3,-2,-1,0,1,2,3,4,5];
  const rBins = R_EDGES.slice(0,-1).map((lo,i) => ({
    label: `${lo}`,
    count: TRADES.filter(t=>t.r>=lo && t.r<R_EDGES[i+1]).length,
    pos: lo >= 0,
  }));

  const HOLD_EDGES = [[0,10],[10,30],[30,60],[60,120],[120,240],[240,480],[480,Infinity]];
  const holdBins = HOLD_EDGES.map(([lo,hi]) => ({
    label: hi===Infinity ? `${lo}+` : `${lo}-${hi}`,
    count: TRADES.filter(t=>t.hold>=lo && t.hold<hi).length,
  }));

  const hourBins = Array.from({length:24}, (_,h) => ({
    label: h%3===0 ? `${h}h` : '',
    count: TRADES.filter(t=>t.hour===h).length,
  }));

  const DOW = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const dowRows = DOW.map((label,i) => {
    const ts = TRADES.filter(t=>t.dow===i);
    return {label, v: ts.length ? ts.reduce((s,t)=>s+t.pnl,0)/ts.length : 0, n: ts.length};
  });

  const wrHourRows = Array.from({length:24}, (_,h) => {
    const tr = TRADES.filter(t=>t.hour===h);
    return {
      label: h%3===0 ? `${h}h` : '',
      count: tr.length ? Math.round(tr.filter(t=>t.pnl>0).length/tr.length*100) : 0,
      pos: tr.length>0 && (tr.filter(t=>t.pnl>0).length/tr.length) >= 0.5,
      n: tr.length,
    };
  });

  return (
    <GridWorkspace>

      <GridItem x={0} y={0} w={12} h={6} minW={6} minH={5}>
      <Pane title="PnL Distribution" style={{height:'100%'}} tag={periodLbl||'$1 bins'}
        foot={{tone:'sub', id:5101, msg:`n=${TRADES.length} closed trades · fat-tailed, slight negative skew`, ms:1}}>
        <ExecHistChart bins={pnlBins} height="100%" divergent noun="trade"/>
      </Pane>
      </GridItem>

      <GridItem x={12} y={0} w={12} h={6} minW={6} minH={5}>
      <Pane title="R-Multiple Distribution" style={{height:'100%'}} tag="1R bins"
        foot={{tone:'sub', id:5102, msg:'1R = risk per trade (1.00% account)', ms:0}}>
        <ExecHistChart bins={rBins} height="100%" divergent noun="trade"/>
      </Pane>
      </GridItem>

      <GridItem x={0} y={6} w={12} h={6} minW={6} minH={5}>
      <Pane title="Hold Time Distribution" style={{height:'100%'}} tag="min"
        foot={{tone:'sub', id:5103, msg:'most trades < 2h — intraday horizon', ms:0}}>
        <ExecHistChart bins={holdBins} height="100%" color="var(--qe-blue)" noun="trade"/>
      </Pane>
      </GridItem>

      <GridItem x={12} y={6} w={12} h={6} minW={6} minH={5}>
      <Pane title="Trades by Hour of Day" style={{height:'100%'}} tag="UTC"
        foot={{tone:'sub', id:5104, msg:'concentration window: identify session bias', ms:1}}>
        <ExecHistChart bins={hourBins} height="100%" color="var(--qe-cyan)" noun="trade"/>
      </Pane>
      </GridItem>

      <GridItem x={0} y={12} w={12} h={6} minW={6} minH={5}>
      <Pane title="Avg PnL by Day of Week" style={{height:'100%'}} tag="$"
        foot={{tone:'info', id:5105, msg:'weekday vs weekend execution patterns', ms:0}}>
        <ExecDivergingBars rows={dowRows} height="100%"/>
      </Pane>
      </GridItem>

      <GridItem x={12} y={12} w={12} h={6} minW={6} minH={5}>
      <Pane title="Win Rate by Hour of Day" style={{height:'100%'}} tag="%"
        foot={{tone:'sub', id:5106, msg:`active hours only · winrate >= 50% in green`, ms:0}}>
        <ExecHistChart bins={wrHourRows} height="100%" divergent unit="%" noun="win"/>
      </Pane>
      </GridItem>

    </GridWorkspace>
  );
};

Object.assign(window, { TabExecution, TabDistributions, EXEC_DATA });
