/* v3.0 — ECharts wrappers
   All charts share a single dark/neon theme. Sharp corners, no animations
   (anim=false everywhere — render speed comes first). */

// Resolve CSS-var strings to hex for ECharts (canvas can't read --vars)
const _qeResolveColor = (c) => {
  if (typeof c !== 'string') return c;
  const m = c.match(/^var\(\s*(--[\w-]+)\s*\)(.*)$/);
  if (!m) return c;
  const v = getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim();
  return v + (m[2] || '');
};

// Pull the live token values from CSS so the chart theme follows tokens.css.
// Computed lazily so changes to :root vars take effect on next chart init.
const _qeReadVar = (name, fallback) => {
  if (typeof document === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
};

const QE_ECHARTS_THEME = new Proxy({}, {
  get(_, key) {
    const map = {
      bg:    ['--qe-bg',     '#000000'],
      text:  ['--qe-text',   '#ffffff'],
      sub:   ['--qe-sub',    '#b6c8df'],
      muted: ['--qe-muted',  '#8298b4'],
      line:  ['--qe-line',   '#36486a'],
      faint: ['--qe-faint',  '#2c3a52'],
      green: ['--qe-green',  '#00ff7f'],
      red:   ['--qe-red',    '#ff2d4a'],
      cyan:  ['--qe-cyan',   '#00e7ff'],
      amber: ['--qe-amber',  '#ffae00'],
      blue:  ['--qe-blue',   '#2a8fff'],
    };
    const pair = map[key];
    if (!pair) return undefined;
    return _qeReadVar(pair[0], pair[1]);
  },
});

const _baseChart = (opts={}) => ({
  backgroundColor: 'transparent',
  animation: false,
  textStyle: { fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: QE_ECHARTS_THEME.text, fontWeight: 500 },
  grid: { left: 38, right: 8, top: 6, bottom: 18, ...opts.grid },
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#000',
    borderColor: QE_ECHARTS_THEME.cyan,
    borderWidth: 1,
    padding: [4,8],
    textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', fontWeight: 500 },
    axisPointer: { lineStyle: { color: QE_ECHARTS_THEME.cyan, type:'solid', opacity:0.4 }, crossStyle: { color: QE_ECHARTS_THEME.cyan } },
  },
});

const _axis = (extra={}) => ({
  axisLine:  { lineStyle: { color: QE_ECHARTS_THEME.line } },
  axisTick:  { lineStyle: { color: QE_ECHARTS_THEME.line } },
  axisLabel: { color: QE_ECHARTS_THEME.sub, fontSize: 10, fontFamily: 'JetBrains Mono, monospace', fontWeight: 500 },
  splitLine: { lineStyle: { color: QE_ECHARTS_THEME.line, opacity: 0.5, type:[2,3] } },
  ...extra,
});

// hook — create + destroy + resize an echarts instance
function useECharts(ref, opts, deps=[]) {
  React.useEffect(() => {
    if (!ref.current || !window.echarts) return;
    const chart = window.echarts.init(ref.current, null, { renderer:'canvas' });
    chart.setOption(opts);
    // guard against init-before-layout: re-measure on the next frame
    const raf = requestAnimationFrame(() => { try { chart.resize(); } catch(e){} });
    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    // observe container resize too
    let ro = null;
    if (window.ResizeObserver) {
      ro = new ResizeObserver(() => chart.resize());
      ro.observe(ref.current);
    }
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
      if (ro) ro.disconnect();
      chart.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

// ── Candlestick chart ───────────────────────────────────────────────────
// data: [[t, o, c, l, h], ...]
const CandlestickChart = ({data, height='100%', volume=false, logScale=false}) => {
  const ref = React.useRef(null);
  const opts = React.useMemo(() => {
    const cats = data.map(d => new Date(d[0]));
    const oclh = data.map(d => [d[1], d[2], d[3], d[4]]);
    return {
      ..._baseChart({grid:{left:44, right:8, top:6, bottom:18}}),
      xAxis: {
        type: 'category', boundaryGap: true,
        data: cats.map(d => `${('0'+(d.getUTCMonth()+1)).slice(-2)}-${('0'+d.getUTCDate()).slice(-2)} ${('0'+d.getUTCHours()).slice(-2)}:00`),
        ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.sub, fontSize: 10, fontFamily: 'JetBrains Mono, monospace', fontWeight: 500, interval: Math.max(1, Math.floor(data.length/6)) } }),
      },
      yAxis: {
        type: logScale ? 'log' : 'value', scale: true, position: 'left',
        ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.sub, fontSize: 10, fontFamily: 'JetBrains Mono, monospace', fontWeight: 500,
          formatter: v => v.toFixed(2) } }),
      },
      series: [{
        type: 'candlestick', data: oclh,
        itemStyle: {
          color:       QE_ECHARTS_THEME.green,    // up body fill
          color0:      'transparent',              // down body fill (hollow)
          borderColor: QE_ECHARTS_THEME.green,
          borderColor0:QE_ECHARTS_THEME.red,
          borderWidth: 1,
        },
        emphasis: { itemStyle: { borderWidth: 1.5 } },
        barWidth: '60%',
      }],
    };
  }, [data, logScale]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} className="qe-chart" style={{height}}/>;
};

// ── Equity area chart ───────────────────────────────────────────────────
const EquityChart = ({data, height='100%', color=QE_ECHARTS_THEME.green, baseline=null}) => {
  const ref = React.useRef(null);
  color = _qeResolveColor(color);
  const opts = React.useMemo(() => ({
    ..._baseChart({grid:{left:40, right:8, top:6, bottom:18}}),
    xAxis: { type: 'category', boundaryGap: false,
      data: data.map((_,i) => i),
      ..._axis({ axisLabel: { show: false }, axisTick: { show: false } }),
    },
    yAxis: { type: 'value', scale: true,
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.sub, fontSize: 10, fontFamily: 'JetBrains Mono, monospace', fontWeight: 500,
        formatter: v => v.toFixed(2) } }),
    },
    series: [{
      type: 'line', data, smooth: 0.15,
      symbol: 'none', lineStyle: { color, width: 1.4 },
      areaStyle: { color: {
        type: 'linear', x:0,y:0,x2:0,y2:1,
        colorStops: [
          { offset:0, color: color+'40' },
          { offset:1, color: color+'00' },
        ],
      }},
      markLine: baseline != null ? {
        symbol: 'none', silent: true,
        data: [{ yAxis: baseline, lineStyle: { color: QE_ECHARTS_THEME.muted, type:'dashed', width:1 },
          label: { show: false } }],
      } : undefined,
    }],
  }), [data, color, baseline]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} className="qe-chart" style={{height}}/>;
};

// ── Sparkline — for embedding in cards/rows ─────────────────────────────
const Sparkline = ({data, color=QE_ECHARTS_THEME.green, height=24, area=true, width='100%'}) => {
  const ref = React.useRef(null);
  color = _qeResolveColor(color);
  const opts = React.useMemo(() => ({
    backgroundColor: 'transparent', animation: false,
    grid: { left: 0, right: 0, top: 1, bottom: 1 },
    xAxis: { type: 'category', show: false, boundaryGap: false, data: data.map((_,i)=>i) },
    yAxis: { type: 'value', show: false, scale: true },
    series: [{
      type: 'line', data, smooth: 0.2, symbol:'none',
      lineStyle: { color, width: 1.1 },
      areaStyle: area ? { color: color+'25' } : undefined,
    }],
    tooltip: { show: false },
  }), [data, color, area]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} style={{width, height}}/>;
};

// ── Bar chart (compact, for win/loss/distribution) ──────────────────────
const BarChart = ({data, color=QE_ECHARTS_THEME.cyan, height='100%', categories=null}) => {
  const ref = React.useRef(null);
  color = _qeResolveColor(color);
  const opts = React.useMemo(() => ({
    ..._baseChart({grid:{left:36, right:8, top:6, bottom:18}}),
    xAxis: { type: 'category', data: categories || data.map((_,i)=>i),
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.sub, fontSize: 10, fontFamily: 'JetBrains Mono, monospace', fontWeight: 500 } }),
    },
    yAxis: { type: 'value', ..._axis() },
    series: [{
      type: 'bar', data,
      itemStyle: { color: (p) => p.value >= 0 ? QE_ECHARTS_THEME.green : QE_ECHARTS_THEME.red },
      barWidth: '60%',
    }],
  }), [data, color, categories]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} className="qe-chart" style={{height}}/>;
};

// ── Regime ribbon — stacked horizontal segments showing regime over time ─
const RegimeRibbon = ({segments, height=22, width='100%'}) => {
  // segments = [{tone, t, label}, ...] where t is duration weight
  const total = segments.reduce((a,s) => a + s.t, 0);
  const colors = {
    trend: 'var(--qe-green)', chop: 'var(--qe-cyan)', neut: 'var(--qe-sub)',
    def: 'var(--qe-amber)', panic: 'var(--qe-red)',
  };
  return (
    <div style={{display:'flex', width, height, border:'1px solid var(--qe-line)'}}>
      {segments.map((s,i) => (
        <div key={i} title={s.label}
          style={{
            flex: s.t / total,
            background: colors[s.tone] || 'var(--qe-sub)',
            opacity: 0.85,
            borderRight: i < segments.length-1 ? '1px solid var(--qe-bg)' : 'none',
          }}/>
      ))}
    </div>
  );
};

// ── Heat strip — for calendar PnL ───────────────────────────────────────
const HeatStrip = ({data, height=18}) => {
  // data: [{date, pnl}, ...]
  const max = Math.max(...data.map(d => Math.abs(d.pnl)));
  return (
    <div style={{display:'flex', height, gap:1}}>
      {data.map((d,i) => {
        const mag = Math.abs(d.pnl) / max;
        const col = d.pnl >= 0 ? `rgba(0,255,127,${0.15 + mag*0.85})` : `rgba(255,45,74,${0.15 + mag*0.85})`;
        return <div key={i} title={`${d.date}: ${d.pnl >=0 ?'+':''}${d.pnl}`}
          style={{flex:1, background: col}}/>;
      })}
    </div>
  );
};

// ── Scatter chart (for MFE/MAE etc.) ────────────────────────────────────
// points: [{x, y, profit:bool, label?}]
const ScatterChart = ({points, height='100%', xName='X', yName='Y'}) => {
  const ref = React.useRef(null);
  const opts = React.useMemo(() => {
    const profitable = points.filter(p => p.profit);
    const losses     = points.filter(p => !p.profit);
    return {
      ..._baseChart({grid:{left:48, right:14, top:18, bottom:38}}),
      tooltip: { trigger:'item', backgroundColor:'#000', borderColor: QE_ECHARTS_THEME.cyan, borderWidth:1,
        textStyle:{color: QE_ECHARTS_THEME.text, fontSize:11, fontFamily:'JetBrains Mono, monospace'},
        formatter: (p) => {
          const d = p.data;
          return `<div style="padding:4px 8px;">
            <b>${d[2]||''}</b><br/>
            ${xName}: ${d[0].toFixed(2)}<br/>
            ${yName}: ${d[1].toFixed(2)}
          </div>`;
        }},
      xAxis: { type:'value', scale:true, name: xName, nameLocation:'center', nameGap:24,
        nameTextStyle:{ color: QE_ECHARTS_THEME.sub, fontSize: 10 },
        ..._axis(),
      },
      yAxis: { type:'value', scale:true, name: yName, nameLocation:'middle', nameGap:36, nameRotate:90,
        nameTextStyle:{ color: QE_ECHARTS_THEME.sub, fontSize: 10 },
        ..._axis(),
      },
      series: [
        { name:'Profitable', type:'scatter',
          data: profitable.map(d => [d.x, d.y, d.label]),
          itemStyle:{ color: QE_ECHARTS_THEME.green, opacity:0.8 },
          symbolSize: 7,
        },
        { name:'Loss', type:'scatter',
          data: losses.map(d => [d.x, d.y, d.label]),
          itemStyle:{ color: QE_ECHARTS_THEME.red, opacity:0.8 },
          symbolSize: 7,
        },
      ],
    };
  }, [points, xName, yName]);
  useECharts(ref, opts, [opts]);
  return <div ref={ref} className="qe-chart" style={{height}}/>;
};

Object.assign(window, {
  QE_ECHARTS_THEME,
  CandlestickChart, EquityChart, Sparkline, BarChart,
  RegimeRibbon, HeatStrip, ScatterChart,
});
