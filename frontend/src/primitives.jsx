/* v3.0 — Primitives. Standardize the audit's "drift" findings:
   one Card, one Stat, one Badge, one StatusDot, one EmptyState,
   one PeriodSelector, one Gauge, one Table.
   Everything is a React component for portability into htmx templates. */

// ── mock data helpers ─────────────────────────────────────────────────────
const mockOhlc = (n=60, base=82.2, vol=2) => {
  let c = base, out = [];
  // bars END at the frozen mock "now" (04-25 20:00) — never in the future
  const now = Date.UTC(2026,3,25,20,0,0) - (n-1)*3600_000;
  for (let i=0; i<n; i++) {
    const o = c;
    c = Math.max(base*0.86, Math.min(base*1.16, c + (Math.random()-0.49)*vol));
    const h = Math.max(o,c) + Math.random()*vol*0.4;
    const l = Math.min(o,c) - Math.random()*vol*0.4;
    out.push([now + i*3600_000, +o.toFixed(3), +c.toFixed(3), +l.toFixed(3), +h.toFixed(3)]);
  }
  // rescale so the series CLOSES at base — the live equity readouts (eq=82.20,
  // session C) and the chart then tell one story
  const f = base / out[out.length-1][2];
  return out.map(r => [r[0], +(r[1]*f).toFixed(3), +(r[2]*f).toFixed(3), +(r[3]*f).toFixed(3), +(r[4]*f).toFixed(3)]);
};
const mockEquity = (n=80, base=82.2, vol=0.8) => {
  let v = base; const out = [];
  for (let i=0; i<n; i++) {
    v += (Math.random()-0.49) * vol;
    v = Math.max(base*0.86, Math.min(base*1.18, v));
    out.push(+v.toFixed(3));
  }
  return out;
};
const mockSpark = (n=24, base=0, range=1) => {
  let v = base, out = [];
  for (let i=0; i<n; i++) { v += (Math.random()-0.5)*range; out.push(+v.toFixed(3)); }
  return out;
};

// ── Atoms ────────────────────────────────────────────────────────────────
const Lbl = ({children, bracket=false, style={}}) => (
  <div className={`qe-lbl ${bracket?'qe-lbl-bracket':''}`} style={style}>{children}</div>
);

const SecLbl = ({children, count=null, rule=false, right=null, style={}}) => (
  <div className="qe-sec-lbl" style={{marginBottom: 6, ...style}}>
    <span>{children}</span>
    {count != null && <span className="qe-sec-count">·  {count}</span>}
    {rule && <span className="qe-sec-rule"/>}
    {right && <span style={{marginLeft:'auto'}}>{right}</span>}
  </div>
);

// KV — compact key/value cell. label (uppercase micro) over a mono value.
// Lay several in a CSS grid for a detail block. `span` makes it full-width.
const KV = ({l, v, color, span, style={}}) => (
  <div style={{minWidth:0, gridColumn: span ? '1 / -1' : 'auto', ...style}}>
    <div style={{fontFamily:'var(--qe-ui)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.1em', textTransform:'uppercase', color:'var(--qe-muted)'}}>{l}</div>
    <div className="qe-mono" style={{fontSize:'0.6rem', color: color||'var(--qe-text)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</div>
  </div>
);

const Card = ({children, tight=false, pad=false, hot=false, ticks=false, style={}, className=''}) => (
  <div className={[
    'qe-card',
    tight && 'qe-card-tight',
    pad && 'qe-card-pad',
    hot && 'qe-card-hot',
    ticks && 'qe-card-ticks',
    className,
  ].filter(Boolean).join(' ')} style={style}>{children}</div>
);

const Stat = ({label, value, sub, color, size}) => (
  <div className="qe-stat">
    <Lbl>{label}</Lbl>
    <div className="qe-stat-val" style={{color: color, fontSize: size}}>{value}</div>
    {sub && <div className="qe-stat-sub">{sub}</div>}
  </div>
);

// HeroNumber — split cents to dim color, optional delta + sparkline
const HeroNumber = ({value, ccy='USDT', size='var(--qe-fs-3xl)'}) => {
  const s = String(value);
  const [int, dec] = s.includes('.') ? s.split('.') : [s, null];
  return (
    <div className="qe-hero-val" style={{fontSize: size}}>
      {int}
      {dec && <span className="qe-hero-cents">.{dec}</span>}
      <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.36em', color:'var(--qe-sub)', fontWeight:600, marginLeft:8, verticalAlign:'middle'}}>{ccy}</span>
    </div>
  );
};

// Delta — directional value with arrow + color
const Delta = ({value, pct=null, size='var(--qe-fs-md)', flat=false}) => {
  const v = parseFloat(value);
  const dir = v > 0 ? 'up' : v < 0 ? 'dn' : 'flat';
  const col = dir==='up' ? 'var(--qe-green)' : dir==='dn' ? 'var(--qe-red)' : 'var(--qe-sub)';
  const sign = v > 0 ? '+' : '';
  return (
    <span className="qe-mono" style={{color: col, fontSize: size, fontWeight: 700, display:'inline-flex', alignItems:'center', gap: 4}}>
      {!flat && (dir==='up' ? <span className="qe-tick qe-tick-up"/> : dir==='dn' ? <span className="qe-tick qe-tick-dn"/> : null)}
      {sign}{value}
      {pct != null && <span style={{color: col, opacity:0.7, fontWeight:600}}>({sign}{pct}%)</span>}
    </span>
  );
};

// StatusDot — single primitive that REPLACES all ad-hoc status indicators
// (Plugin OFF, WS, Connected, Standalone, etc.)
const StatusDot = ({tone='off', label, value=null, sq=false}) => (
  <span className={`qe-dot ${sq?'qe-dot-sq':''} qe-dot-${tone}`}>
    <span style={{color: 'inherit'}}>{label}</span>
    {value != null && <span style={{color:'var(--qe-text)', fontWeight:600}}>{value}</span>}
  </span>
);

// Badge — single primitive. tone: ok | warn | err | info | blue | mag | mute
const Badge = ({children, tone='mute', solid=false, style={}}) => (
  <span className={`qe-badge ${solid?'qe-badge-solid':''} qe-badge-${tone}`} style={style}>{children}</span>
);

// RegimeBadge — special case mapping
const REGIME = {
  trend:  ['qe-rg-trend','TREND'],
  chop:   ['qe-rg-chop','CHOP'],
  neut:   ['qe-rg-neut','NEUT'],
  def:    ['qe-rg-def','DEF'],
  panic:  ['qe-rg-panic','PANIC'],
};
const RegimeBadge = ({tone='neut', label=null}) => {
  const [cls, dl] = REGIME[tone] || REGIME.neut;
  return <span className={`qe-badge ${cls}`}>{label || dl}</span>;
};

// PeriodSelector — REPLACES the 4 ad-hoc selectors
const PeriodSelector = ({options, value, onChange, style={}}) => (
  <div className="qe-period" style={style}>
    {options.map(opt => {
      const [val, lbl] = Array.isArray(opt) ? opt : [opt, opt];
      return (
        <button key={val} className={value===val?'on':''} onClick={()=>onChange(val)}>{lbl}</button>
      );
    })}
  </div>
);

// Gauge — REPLACES drift across "exposure bar", "capacity bar", "DD bar"
const Gauge = ({label, value, max, current, maxLabel, ticks=[], hint=null}) => {
  const pct = Math.min(value/max*100, 100);
  const tone = pct > 80 ? 'err' : pct > 60 ? 'warn' : 'ok';
  return (
    <div className="qe-gauge">
      <div className="qe-gauge-head">
        <Lbl>{label}</Lbl>
        <span className="qe-mono" style={{fontSize:'var(--qe-fs-md)', fontWeight:700, color:'var(--qe-text)'}}>{current}</span>
      </div>
      <div className="qe-gauge-track">
        <div className={`qe-gauge-fill ${tone}`} style={{width: pct+'%'}}/>
        {ticks.map((t,i) => <div key={i} className="qe-gauge-tick" style={{left: (t/max*100)+'%'}}/>)}
      </div>
      <div className="qe-gauge-foot">
        <span>{hint || `0`}</span>
        <span>{maxLabel}</span>
      </div>
    </div>
  );
};

// EmptyState — REPLACES the 7 ad-hoc treatments
// tones: info | warn | err | neutral
const EmptyState = ({tone='neutral', glyph='∅', msg, hint, cta=null}) => (
  <div className={`qe-empty ${tone==='neutral'?'':tone}`}>
    <div className="qe-empty-glyph">{glyph}</div>
    <div className="qe-empty-msg">{msg}</div>
    {hint && <div style={{fontSize:'var(--qe-fs-xs)', color:'var(--qe-muted)', textAlign:'center'}}>{hint}</div>}
    {cta && <div className="qe-empty-cta">{cta}</div>}
  </div>
);

// Tabs — single primitive (optional style for embedding in composite strips)
const Tabs = ({tabs, value, onChange, style=null}) => (
  <div className="qe-tabs" style={style || undefined}>
    {tabs.map(([id, lbl, count]) => (
      <button key={id} className={value===id?'on':''} onClick={()=>onChange(id)}>
        {lbl}
        {count != null && <span style={{color:'var(--qe-muted)', marginLeft:5, fontFamily:'var(--qe-mono)'}}>{count}</span>}
      </button>
    ))}
  </div>
);

// TabStrip — THE canonical sub-tab navigator bar (one per page/section).
// Full-width rule bar: --qe-page bg · '0 4px' padding · 1px bottom rule.
// The Tabs sit inside a hidden-scrollbar h-scroller WITH their own
// border-bottom, so the active underline's 1px overlap renders identically
// whether or not the strip overflows. `right` = controls pinned at the end
// (run selector, + button, …). Never compose this bar by hand.
const TabStrip = ({tabs, value, onChange, right=null, style={}}) => (
  <div style={{display:'flex', alignItems:'stretch', padding:'0 4px', background:'var(--qe-page)', borderBottom:'1px solid var(--qe-line)', flexShrink:0, ...style}}>
    <div className="qe-hscroll" style={{flex:1, minWidth:0, display:'flex'}}>
      <Tabs value={value} onChange={onChange} tabs={tabs} style={{minWidth:'max-content', flex:1}}/>
    </div>
    {right}
  </div>
);
Object.assign(window, { TabStrip });

// Strip — REPLACES exchange info row + active params row + secondary stats row
// all into one consistent primitive
const Strip = ({items, dense=false, style={}}) => (
  <div className="qe-strip" style={style}>
    {items.map((it, i) => (
      <div key={i} className="qe-strip-cell" style={dense ? {padding:'3px 8px'} : {}}>
        <span className="lbl">{it.label}</span>
        <span className="val" style={{color: it.color}}>{it.value}</span>
      </div>
    ))}
  </div>
);

// FlashCell — wraps a number; flashes on change
const FlashCell = ({value, formatter=String, style={}, className=''}) => {
  const prev = React.useRef(value);
  const ref  = React.useRef(null);
  React.useEffect(() => {
    if (!ref.current) return;
    if (value > prev.current) {
      ref.current.classList.remove('qe-flash-dn','qe-flash-up');
      void ref.current.offsetWidth;
      ref.current.classList.add('qe-flash-up');
    } else if (value < prev.current) {
      ref.current.classList.remove('qe-flash-up','qe-flash-dn');
      void ref.current.offsetWidth;
      ref.current.classList.add('qe-flash-dn');
    }
    prev.current = value;
  }, [value]);
  return <span ref={ref} className={`qe-mono ${className}`} style={style}>{formatter(value)}</span>;
};

// ─────────────────────────────────────────────────────────────────────────
// LiveValue — canonical "refresh-just-the-value" primitive
// Renders ONLY the value text inside a stable wrapper. The element keeps a
// data-live-id attribute matching its server-side stream key so htmx (or
// any morph engine) can target THIS span and swap just the innerText.
// Flashes green/red on numeric change. Stale state available.
//
// Server-side: <span data-live-id="pos.BTCUSDT.mark"
//                    hx-swap-oob="innerHTML:[data-live-id='pos.BTCUSDT.mark']">
//                93,580.40
//              </span>
// or via SSE event with the same id targeting the element.
//
// Use this anywhere a value comes from async streams. NEVER swap the
// surrounding card/row/pane — it causes whole-tile flicker. Swap the
// LiveValue ONLY.
//
// props:
//   id        stream key (e.g. "pos.BTCUSDT.mark", "regime.confidence")
//   value     current value (numeric OR string)
//   format    optional formatter: v => string. default String(v)
//   tone      'up' | 'dn' | 'auto' (auto = compare to prev numeric value)
//   stale     boolean — adds dimmed appearance + dotted underline
//   style/className passthroughs
// ─────────────────────────────────────────────────────────────────────────
const LiveValue = ({id, value, format=String, tone='auto', stale=false, style={}, className=''}) => {
  const prev = React.useRef(value);
  const ref  = React.useRef(null);
  React.useEffect(() => {
    if (!ref.current) return;
    if (tone === 'up') {
      ref.current.classList.remove('qe-flash-dn');
      void ref.current.offsetWidth;
      ref.current.classList.add('qe-flash-up');
    } else if (tone === 'dn') {
      ref.current.classList.remove('qe-flash-up');
      void ref.current.offsetWidth;
      ref.current.classList.add('qe-flash-dn');
    } else {
      // auto: numeric compare
      const pv = parseFloat(prev.current);
      const cv = parseFloat(value);
      if (!isNaN(pv) && !isNaN(cv)) {
        if (cv > pv) {
          ref.current.classList.remove('qe-flash-dn','qe-flash-up');
          void ref.current.offsetWidth;
          ref.current.classList.add('qe-flash-up');
        } else if (cv < pv) {
          ref.current.classList.remove('qe-flash-up','qe-flash-dn');
          void ref.current.offsetWidth;
          ref.current.classList.add('qe-flash-dn');
        }
      }
    }
    prev.current = value;
  }, [value, tone]);
  return (
    <span
      ref={ref}
      data-live-id={id}
      className={`qe-mono qe-live-value ${stale?'qe-live-stale':''} ${className}`}
      style={style}
    >{format(value)}</span>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// useLiveTicker — drives a numeric value with a random-walk jitter on an
// interval. Used to make LiveNumber elements visibly tick in mocked
// dashboards (in production these come from SSE, not this hook).
//   base       starting value
//   jitter     max absolute step per tick (random walk)
//   intervalMs ms between ticks (default 1100)
//   decimals   round to N decimals
//   clamp      [min, max] optional bounds
// ─────────────────────────────────────────────────────────────────────────
const useLiveTicker = (base, {jitter=1, intervalMs=1100, decimals=2, clamp=null}={}) => {
  const [v, setV] = React.useState(base);
  React.useEffect(() => {
    const id = setInterval(() => {
      setV(prev => {
        let next = prev + (Math.random()-0.5) * jitter * 2;
        if (clamp) next = Math.max(clamp[0], Math.min(clamp[1], next));
        return +next.toFixed(decimals);
      });
    }, intervalMs + Math.random()*400);
    return () => clearInterval(id);
  }, []);
  return v;
};

// LiveNumber — convenience: useLiveTicker + LiveValue together.
// Drop-in for any dashboard number that should pulse.
const LiveNumber = ({id, base, jitter=1, intervalMs=1100, decimals=2, clamp=null,
                     format, style={}, className=''}) => {
  const v = useLiveTicker(base, {jitter, intervalMs, decimals, clamp});
  const fmt = format || (x => (decimals > 0 ? x.toFixed(decimals) : String(Math.round(x))));
  return <LiveValue id={id} value={v} format={fmt} style={style} className={className}/>;
};

// LivePct — signed percent with green/red color & sign
const LivePct = ({id, base, jitter=0.05, intervalMs=1300, decimals=2, style={}}) => {
  const v = useLiveTicker(base, {jitter, intervalMs, decimals});
  const col = v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)';
  const sign = v > 0 ? '+' : '';
  return <LiveValue id={id} value={v} format={x => sign + x.toFixed(decimals) + '%'}
                    style={{color: col, fontWeight:700, ...style}}/>;
};

// LiveClock — wall clock that ticks every second (string LiveValue, no flash)
const LiveClock = ({id='clock', style={}, format=null}) => {
  const [t, setT] = React.useState(() => new Date());
  React.useEffect(() => {
    const i = setInterval(() => setT(new Date()), 1000);
    return () => clearInterval(i);
  }, []);
  const s = format ? format(t) :
    t.toISOString().slice(0,10) + ' ' + t.toISOString().slice(11,19) + ' UTC';
  return <LiveValue id={id} value={s} format={x=>x} style={style}/>;
};

// Ascii spark — for very dense tables
const ASCII_SPARK = '▁▂▃▄▅▆▇█';
const asciiSpark = (vals) => {
  if (!vals?.length) return '';
  const min = Math.min(...vals), max = Math.max(...vals);
  const rng = (max-min) || 1;
  return vals.map(v => ASCII_SPARK[Math.floor(((v-min)/rng) * (ASCII_SPARK.length-1))]).join('');
};

// ─────────────────────────────────────────────────────────────────────────
// PANE — canonical tile container. Every tile in the engine is a <Pane>.
//
// props:
//   title    ALWAYS-UPPERCASE pane name (rendered uppercase by CSS)
//   count    optional row/item count shown next to the title
//   right    optional right-aligned controls (period selector, badges)
//   hot      highlight pane with cyan border (use for "primary focus")
//   tag      optional info-tone badge in the title bar (e.g. SSE, VIEW)
//   foot     optional {tone, id, msg, ms} — last engine_events row for this pane
//   children pane body content
//
// Layout: head (20px) + body (flex:1, scrolls) + foot (16px, optional) + grip
// ─────────────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────────
// Reload / loading — THE engine standard. Loading is ALWAYS the square 2×2
// braille spinner (BrailleSquares / Spinner below). The resting reload-button
// glyph is the circular-arrow ReloadIconSVG; while reloading it swaps to the
// braille spinner over a darken veil that clears the foot (last-response line
// stays lit). No alternatives — one principle, used everywhere.
// ─────────────────────────────────────────────────────────────────────────
const RELOAD_MS = 620;   // how long a pane reload takes (ms)
const FOOT_H    = 17;    // PaneFoot height (16) + 1px top border — body veil stops here
// Monotonic engine-event sequence — a reload emits a new event, so the foot's
// "last response" advances like the real event log. Shared across panes (one log).
let QE_EVENT_SEQ = 0;
const nextEventId = (base=0) => {
  QE_EVENT_SEQ = Math.max(QE_EVENT_SEQ, base|0) + 2 + Math.floor(Math.random()*6);
  return QE_EVENT_SEQ;
};

// ReloadIconSVG — the canonical circular-arrow reload mark (matches the brief):
// a ~290° ring with a round end at ~2 o'clock and a bold right-pointing
// arrowhead at top. Uses currentColor + 1em box so it inherits the button's
// color/size. The viewBox is centered on the CIRCLE's center (not the whole
// icon) so it sits true. This is the resting reload glyph; loading swaps to braille.
const ReloadIconSVG = () => (
  <svg className="qe-reload-svg" viewBox="-0.1 1.2 24.2 24.2" fill="none" aria-hidden="true" focusable="false">
    <path d="M19.86 9.8 A8.6 8.6 0 1 1 10.51 4.83" stroke="currentColor" strokeWidth="2.7" strokeLinecap="round"/>
    <path d="M11.2 1.4 L17.4 5.2 L11.2 9 Z" fill="currentColor"/>
  </svg>
);

// useSpinFrame — drives a text-frame spinner (braille/ascii). One source of
// truth for frame cycling, shared by ReloadGlyph and the standalone Spinner.
const useSpinFrame = (frames, active=true, ms=110) => {
  const [i, setI] = React.useState(0);
  React.useEffect(() => {
    if (!active) { setI(0); return; }
    // respect reduced-motion — hold a single frame instead of cycling
    const reduce = typeof window !== 'undefined' && window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) { setI(0); return; }
    let k = 0;
    const iv = setInterval(() => { k = (k + 1) % frames.length; setI(k); }, ms);
    return () => clearInterval(iv);
  }, [active, ms, frames]);
  return frames[i] || frames[0];
};

// BrailleSquares — the 2×2 braille spinner redrawn with SHARP square dots
// (the engine has no rounded corners; unicode braille dots are round). 2×2 grid;
// two adjacent squares (one edge) are lit and rotate clockwise. Content is
// centered in the viewBox so it sits true in any box and aligns to adjacent
// text. Scales with font-size (svg box = 1em).
const SQUARE_POS   = { TL:[1,1], TR:[6,1], BR:[6,6], BL:[1,6] };
const SQUARE_EDGES = [['TL','TR'], ['TR','BR'], ['BR','BL'], ['BL','TL']];
const BrailleSquares = ({active=true, style={}}) => {
  const pair = useSpinFrame(SQUARE_EDGES, active);
  return (
    <svg className="qe-braille-sq" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true" style={style}>
      {pair.map(k => { const [x, y] = SQUARE_POS[k]; return <rect key={k} x={x} y={y} width="3" height="3"/>; })}
    </svg>
  );
};

// ReloadGlyph — the reload mark. Resting = the circular-arrow ReloadIconSVG;
// while spinning = the square braille loading spinner. Shared by the head
// button AND the body veil so they always match.
const ReloadGlyph = ({spinning=false, size=null, style={}}) => (
  <span className="qe-refresh-ic" aria-hidden="true"
        style={size ? {fontSize:size, ...style} : style}>
    {spinning ? <BrailleSquares/> : <ReloadIconSVG/>}
  </span>
);

// ─────────────────────────────────────────────────────────────────────────
// Spinner — the engine's ONE standardized loading / busy indicator. Same square
// 2×2 braille spinner as a pane reload (centered, one edge rotating). Use it
// anywhere a "loading / fetching / computing" state needs an indicator instead
// of hand-rolling a glyph or "…".
//   size   spinner box size (default 0.9rem)  ·  label  optional caption
//   color  defaults to cyan                   ·  gap    glyph↔label gap
// ─────────────────────────────────────────────────────────────────────────
const Spinner = ({size='0.9rem', label=null, color='var(--qe-cyan)', gap=7, style={}}) => (
  <span className="qe-spinner" role="status" aria-label={label || 'loading'}
    style={{display:'inline-flex', alignItems:'center', gap, color, fontFamily:'var(--qe-mono)', ...style}}>
    <BrailleSquares style={{fontSize:size}}/>
    {label && <span style={{fontSize:'0.58rem', letterSpacing:'0.18em', textTransform:'uppercase', lineHeight:1}}>{label}</span>}
  </span>
);

// ─────────────────────────────────────────────────────────────────────────
// RefreshButton — canonical async-reload control. Lives in every Pane head
// (left of the ··· menu) and drives per-pane error recovery. Resting glyph is
// the circular arrow; while reloading it shows the braille loading spinner.
//   onClick   () => void   (stopPropagation handled so it can't drag a tile)
//   spinning  bool · tone 'default' | 'warn' | 'err'  (err = pane errored)
// ─────────────────────────────────────────────────────────────────────────
const RefreshButton = ({onClick, spinning=false, tone='default', title='Reload pane', size=16, style={}}) => {
  const color = tone==='err' ? 'var(--qe-red)' : tone==='warn' ? 'var(--qe-amber)' : 'var(--qe-muted)';
  return (
    <button
      type="button"
      className={`qe-refresh${spinning?' on':''}${tone==='err'?' err':''}`}
      title={title}
      aria-label={title}
      onMouseDown={(e)=>e.stopPropagation()}
      onClick={(e)=>{ e.stopPropagation(); if (onClick) onClick(e); }}
      style={{width:size, height:size, color, ...style}}>
      <ReloadGlyph spinning={spinning}/>
    </button>
  );
};

// PaneReloadBody — darken veil over the pane body while reloading, with the
// braille loading spinner + RELOADING. Stops above the foot (bottom:FOOT_H) so
// the last-response line stays lit.
const PaneReloadBody = ({hasFoot=false}) => (
  <div className="qe-pane-refresh" style={{bottom: hasFoot ? FOOT_H : 0}}>
    <ReloadGlyph spinning size="1rem"/>
    <span>RELOADING</span>
  </div>
);

// PaneErrorBoundary — isolates a pane body so ONE failed tile shows a
// recoverable error state (with a Reload CTA) instead of blanking the whole
// app. Reset by remounting (the Pane bumps a key on reload).
class PaneErrorBoundary extends React.Component {
  constructor(props){ super(props); this.state = {hasError:false, msg:null}; }
  static getDerivedStateFromError(err){ return {hasError:true, msg:(err && err.message) ? err.message : String(err)}; }
  componentDidCatch(err, info){ if (this.props.onError) this.props.onError(err, info); }
  render(){
    if (this.state.hasError) {
      return (
        <EmptyState tone="err" glyph="⚠"
          msg={`${this.props.title || 'Pane'} failed to render`}
          hint={this.state.msg}
          cta={<button type="button" className="qe-btn qe-btn-sm qe-btn-danger" onClick={this.props.onReload}>
            <span className="qe-refresh-ic" style={{marginRight:5, fontSize:'0.92em'}}><ReloadIconSVG/></span> Reload
          </button>}/>
      );
    }
    return this.props.children;
  }
}

const PaneHead = ({title, count=null, right=null, hot=false, tag=null, onRefresh=null, refreshing=false, refreshTone='default'}) => {
  const dots = <span className="qe-pane-dots" style={{color:'var(--qe-muted)', fontSize:'0.66rem', letterSpacing:'0.1em', cursor:'pointer'}}>···</span>;
  return (
    <div className="qe-pane-head" style={{
      display:'flex', alignItems:'center', gap:6,
      padding:'2px 6px',
      background: hot ? 'color-mix(in srgb, var(--qe-cyan) 4%, transparent)' : 'var(--qe-panel)',
      borderBottom: '1px solid var(--qe-line)',
      height: 20, flexShrink:0,
    }}>
      <span style={{
        fontFamily:'var(--qe-mono)', fontSize:'0.56rem', fontWeight:700,
        letterSpacing:'0.14em', textTransform:'uppercase', flexShrink:0,
        color: hot ? 'var(--qe-cyan)' : 'var(--qe-text-dim)',
      }}>{title}</span>
      {count != null && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-muted)', flexShrink:0}}>·  {count}</span>}
      {tag && <Badge tone="info">{tag}</Badge>}
      {onRefresh ? (
        // Tile pane: title-bar info sits beside the title; the right edge holds
        // ONLY the reload + ··· controls.
        <React.Fragment>
          {right && <span className="qe-pane-info" style={{display:'inline-flex', alignItems:'center', gap:6, minWidth:0}}>{right}</span>}
          <div className="qe-grow"/>
          <RefreshButton onClick={onRefresh} spinning={refreshing} tone={refreshTone}/>
          {dots}
        </React.Fragment>
      ) : (
        // Legacy / modal use (e.g. ModalShell close ✕): keep right-slot on the right.
        <React.Fragment>
          <div className="qe-grow"/>
          {right}
          {dots}
        </React.Fragment>
      )}
    </div>
  );
};

// PaneFoot — last response from the pane's process. Mirrors the engine_events
// row that drove this pane's last update. Tones: ok | info | warn | err | sub.
// `busy` swaps the glyph for the braille loading spinner (used during reload).
const PaneFoot = ({tone='info', id, msg, ms, busy=false}) => {
  const toneColors = {
    ok:   { fg: 'var(--qe-green)', bg: 'rgba(0,255,127,0.06)',  glyph:'✓' },
    info: { fg: 'var(--qe-cyan)',  bg: 'rgba(0,231,255,0.05)',  glyph:'i' },
    warn: { fg: 'var(--qe-amber)', bg: 'rgba(255,174,0,0.06)',  glyph:'!' },
    err:  { fg: 'var(--qe-red)',   bg: 'rgba(255,45,74,0.06)',  glyph:'✗' },
    sub:  { fg: 'var(--qe-sub)',   bg: 'transparent',           glyph:'·' },
  };
  const t = toneColors[tone] || toneColors.info;
  return (
    <div style={{
      display:'flex', alignItems:'center', gap:6, flexShrink:0,
      borderTop:'1px solid var(--qe-line)', background: t.bg,
      padding:'0 6px', height:16,
      fontFamily:'var(--qe-mono)', fontSize:'0.54rem', lineHeight:1,
    }}>
      {busy ? (
        <span style={{display:'inline-flex', alignItems:'center', justifyContent:'center', width:11, height:11, color:t.fg}}>
          <BrailleSquares style={{fontSize:'0.62rem'}}/>
        </span>
      ) : (
        <span style={{
          display:'inline-flex', alignItems:'center', justifyContent:'center',
          width:11, height:11, border:`1px solid ${t.fg}`,
          color: t.fg, fontWeight:700, fontSize:'0.52rem',
        }}>{t.glyph}</span>
      )}
      {id != null && <span style={{color:'var(--qe-muted)'}}>[{String(id).padStart(5,'0')}]</span>}
      <span style={{color: t.fg, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', flex:1, minWidth:0}}>{msg}</span>
      {ms != null && <span style={{color:'var(--qe-muted)'}}>{ms}ms</span>}
    </div>
  );
};

const Pane = ({title, count, right, hot, tag, foot=null, resizable=true, onRefresh=null, children, bodyStyle={}, style={}}) => {
  const [nonce, setNonce]         = React.useState(0);
  const [refreshing, setRefresh]  = React.useState(false);
  const [errored, setErrored]     = React.useState(false);
  const [reloadFoot, setRFoot]    = React.useState(null);  // last reload's event (overrides foot prop until a real new event)
  const timer = React.useRef(null);
  const startRef = React.useRef(0);
  const footRef = React.useRef(foot);
  footRef.current = foot;
  React.useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  // A genuine new engine event (the foot prop's content changing — e.g. a period
  // switch or recompute) supersedes the reload event, so the foot stops showing
  // "reloaded" and reflects live state again. Keyed on content, not identity
  // (the prop is a fresh object each render).
  const footKey = foot ? `${foot.tone}|${foot.id}|${foot.msg}|${foot.ms}` : '';
  const lastFootKey = React.useRef(footKey);
  React.useEffect(() => {
    if (footKey !== lastFootKey.current) { lastFootKey.current = footKey; setRFoot(null); }
  }, [footKey]);

  // Async reload: spin briefly, then remount the body subtree (key bump) so
  // streams/effects re-run and any caught error is cleared. The reload is itself
  // an engine event, so the foot's "last response" line advances to reflect it:
  // a fresh id, real elapsed ms, and an ok ✓ resynced message (or err on catch).
  // `onRefresh` (if given) is the hook for real re-fetch logic.
  const doRefresh = React.useCallback(() => {
    setRefresh(true);
    startRef.current = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
      const elapsed = Math.max(1, Math.round(now - startRef.current));
      const f = footRef.current;
      // optimistic: the reload emits a fresh "resynced" event. If the remounted
      // body throws again, the boundary flips `errored` and the effFoot err
      // branch overrides this line. (Only meaningful for panes that have a foot.)
      setErrored(false);
      if (f) setRFoot({tone:'ok', id: nextEventId(f.id), msg:'reloaded · resynced from source', ms: elapsed});
      setNonce(n => n + 1);
      setRefresh(false);
      if (onRefresh) { try { onRefresh(); } catch (e) {} }
    }, RELOAD_MS);
  }, [onRefresh]);

  // Effective foot — reload lifecycle layered over the foot prop. Gated on the
  // pane HAVING a foot: footless panes stay footless (reload still shows the
  // head spinner + body veil, just no status line).
  let effFoot = null;
  if (foot) {
    if (refreshing)   effFoot = {tone:'info', busy:true, id:(reloadFoot||foot).id, msg:'reloading…', ms:null};
    else if (errored) effFoot = {tone:'err', id:foot.id, msg:`${title || 'pane'} render failed · reload to recover`, ms:foot.ms};
    else              effFoot = reloadFoot || foot;
  }

  return (
    <div style={{
      display:'flex', flexDirection:'column',
      background:'var(--qe-card)', border:'1px solid var(--qe-line)',
      minWidth:0, minHeight:0, position:'relative',
      ...style,
    }}>
      <PaneHead title={title} count={count} right={right} hot={hot} tag={tag}
        onRefresh={doRefresh} refreshing={refreshing} refreshTone={errored ? 'err' : 'default'}/>
      <div style={{flex:1, minHeight:0, padding:'5px 7px', overflow:'auto', ...bodyStyle}}>
        <PaneErrorBoundary key={nonce} title={title} onReload={doRefresh} onError={() => setErrored(true)}>
          {children}
        </PaneErrorBoundary>
      </div>
      {effFoot && <PaneFoot {...effFoot}/>}
      {refreshing && <PaneReloadBody hasFoot={!!effFoot}/>}
      {resizable && <span className="qe-grip" title="resize" style={{pointerEvents:'none'}}/>}
    </div>
  );
};

// ── DataList tooling helpers (search / sort / filter) ─────────────────────
// Thresholds that govern the AUTO behaviour. Tools light up on any list with
// >= DL_AUTO_MIN rows; categorical columns with a small distinct-value set
// auto-become facet filters.
const DL_AUTO_MIN        = 5;   // rows to auto-enable tools on ANY table (search+sort)
const DL_AUTO_MIN_FACET  = 3;   // rows to auto-enable when a categorical column exists
const DL_FACET_AUTO_MAX  = 6;   // max distinct values for an AUTO facet
const DL_FACET_AUTO_ABS  = 4;   // distinct <= this always qualifies (side/status/type)
const DL_FACET_CARD_RATIO= 0.6; // larger sets must group (distinct <= rows*ratio)
const DL_FACET_FORCE_MAX = 16;  // max distinct values for a forced facet
const DL_VALUE_MAXLEN    = 16;  // values longer than this never auto-facet
const DL_TOOLS_H         = 28;  // fixed toolbar height (px) → sticky <thead> offset

const _dlText = (v) => (v == null ? '' : typeof v === 'string' ? v : String(v));
// Parse a cell to a number for numeric sort/compare. Tolerates currency, %,
// thousands separators and a trailing unit (R, x, bps…). Datetimes and mixed
// strings (multiple separators) intentionally fail → fall back to text sort.
const _dlNum = (v) => {
  if (typeof v === 'number') return v;
  if (typeof v !== 'string') return NaN;
  let s = v.trim();
  if (!s) return NaN;
  s = s.replace(/[$\s]/g, '').replace(/,/g, '').replace(/%$/, '').replace(/[a-zA-Z]+$/, '');
  return /^[-+]?\d*\.?\d+$/.test(s) ? parseFloat(s) : NaN;
};

// Inspect columns × rows and return the categorical columns that should become
// facet filters. Keys off RAW row data (not rendered output), so badge / JSX
// columns facet correctly. Per-column opt-out: filter:false. Force: filter:true
// or filter:{label?, options?}.
const _dlDeriveFacets = (columns, rows) => {
  const out = [];
  columns.forEach((col, ci) => {
    if (col.filter === false) return;
    const get = col.filterVal ? col.filterVal : (col.key != null ? (r => r[col.key]) : null);
    if (!get) return;
    const forced = col.filter === true || (col.filter && typeof col.filter === 'object');
    const counts = new Map();
    let defined = 0, numericN = 0, tooLong = false, hasObj = false;
    for (const row of rows) {
      const raw = get(row);
      if (raw == null || raw === '') continue;
      if (typeof raw === 'object') { hasObj = true; break; }
      defined++;
      const s = String(raw);
      if (s.length > DL_VALUE_MAXLEN) tooLong = true;
      if (Number.isFinite(_dlNum(s))) numericN++;
      counts.set(s, (counts.get(s) || 0) + 1);
    }
    if (hasObj || defined === 0) return;
    if (tooLong && !forced) return;
    const distinct = [...counts.keys()];
    if (distinct.length < 2) return;
    if (forced) {
      if (distinct.length > DL_FACET_FORCE_MAX) return;
    } else {
      // Numeric columns are continuous, not categorical → never auto-facet.
      if (numericN / defined >= 0.7) return;
      if (distinct.length > DL_FACET_AUTO_MAX) return;
      // Larger value sets must show real grouping (drops ids / timestamps that
      // are ~unique-per-row); small enumerations (<= ABS) always qualify.
      if (distinct.length > DL_FACET_AUTO_ABS && distinct.length > rows.length * DL_FACET_CARD_RATIO) return;
      if (defined / rows.length < 0.5) return;
    }
    const allNum = distinct.every(d => Number.isFinite(_dlNum(d)));
    distinct.sort(allNum ? (a, b) => _dlNum(a) - _dlNum(b) : (a, b) => a.localeCompare(b));
    const opts = (col.filter && typeof col.filter === 'object' && Array.isArray(col.filter.options))
      ? col.filter.options.map(String) : distinct;
    out.push({
      key: col.key != null ? col.key : (typeof col.label === 'string' ? col.label : 'facet' + ci),
      label: (col.filter && col.filter.label) || (typeof col.label === 'string' ? col.label
        : String(col.key || '').toUpperCase()),
      options: opts,
      get,
    });
  });
  return out;
};

// ─────────────────────────────────────────────────────────────────────────
// DataList — canonical tabular data presentation inside a Pane.
// Replaces ad-hoc <table> markup. Use this for positions, orders, trades,
// events, signals — anywhere there's "rows of records with columns".
//
// columns: [{ key, label, align?, render?(row, idx), width?, cell?,
//             sort?:false, sortVal?(row),          // sort opt-out / custom key
//             filter?:false|true|{label?,options?}, filterVal?(row),
//             search?:false, searchVal?(row) }]
// rows:    array of records
// dense:   default true (uses qe-table.tight). false = qe-table
// onClick: (row, origIndex) => void   // origIndex is stable under sort/filter
// selKey:  field on row used as row id for selection
// selected: matched against selKey for the .sel highlight
// emptyMsg: shown when rows is empty (uses EmptyState primitive)
// summary: optional summary line under the table (e.g. "5 / 20 · Σ +5.49")
// tools:   undefined → AUTO (toolbar shows past DL_AUTO_MIN rows)
//          true / false → force on / off
//          {search?, sort?, filter?} → force on with granular control
//
// When tools are active the DataList gains: a live cross-column SEARCH box,
// click-to-SORT headers (asc → desc → off, numeric-aware), and auto-derived
// FILTER dropdowns for categorical columns. Sort/filter/search all operate on
// the raw row data, so they work even for columns rendered as badges/JSX.
// The toolbar is sticky; the header row sticks just beneath it.
// ─────────────────────────────────────────────────────────────────────────
const DataList = ({columns, rows, dense=true, onClick, selKey='id', selected=null, emptyMsg='no rows', summary=null, tools}) => {
  const allRows = rows || [];

  // ── tool state (hooks run unconditionally — keep above any early return) ──
  const [q, setQ]             = React.useState('');
  const [sort, setSort]       = React.useState({key:null, dir:null});
  const [facetSel, setFacet]  = React.useState({});

  const toolsObj  = tools && typeof tools === 'object' ? tools : null;

  // Facets are derived up-front (cheap) so they can also inform the AUTO
  // decision: a list with a categorical column is a "record list" and earns
  // tools at a low row count; a column-less numeric table needs more rows.
  const facetsAll = React.useMemo(() => _dlDeriveFacets(columns, allRows), [columns, allRows]);
  const autoOn = allRows.length >= DL_AUTO_MIN
              || (allRows.length >= DL_AUTO_MIN_FACET && facetsAll.length > 0);
  const toolsOn   = tools === false ? false
                  : (tools === true || toolsObj) ? true
                  : autoOn;
  const showSearch = toolsOn && (!toolsObj || toolsObj.search !== false);
  const showSort   = toolsOn && (!toolsObj || toolsObj.sort   !== false);
  const showFilter = toolsOn && (!toolsObj || toolsObj.filter !== false);

  const facets = showFilter ? facetsAll : [];

  // (toolbar is a fixed DL_TOOLS_H tall, so the sticky <thead> offset is a
  //  constant — no fragile measurement against GridStack's settling width.)

  // Columns whose key actually carries data (excludes computed/render-only
  // columns) — these are the ones eligible to sort & search.
  const presentKeys = React.useMemo(() => {
    const s = new Set();
    columns.forEach(c => { if (c.key != null && allRows.some(r => r[c.key] != null)) s.add(c.key); });
    return s;
  }, [columns, allRows]);

  const colId      = (col) => (col.key != null ? col.key : (typeof col.label === 'string' ? col.label : null));
  const sortableOf = (col) => showSort && col.sort !== false && (col.sortVal || presentKeys.has(col.key));

  // ── pipeline: facet filter → search → sort (over {row,_i} wrappers) ──────
  let view = allRows.map((row, _i) => ({row, _i}));
  if (showFilter) {
    for (const f of facets) {
      const sel = facetSel[f.key];
      if (sel == null || sel === '') continue;
      view = view.filter(({row}) => _dlText(f.get(row)) === sel);
    }
  }
  const needle = showSearch ? q.trim().toLowerCase() : '';
  if (needle) {
    const scols = columns.filter(c => c.search !== false && (c.searchVal || presentKeys.has(c.key)));
    view = view.filter(({row}) =>
      scols.some(c => _dlText(c.searchVal ? c.searchVal(row) : row[c.key]).toLowerCase().includes(needle)));
  }
  if (showSort && sort.key) {
    const col = columns.find(c => colId(c) === sort.key);
    if (col) {
      const get = (w) => (col.sortVal ? col.sortVal(w.row) : w.row[col.key]);
      const raw = view.map(get);
      const numeric = raw.some(v => Number.isFinite(_dlNum(v)))
                   && raw.every(v => v == null || v === '' || Number.isFinite(_dlNum(v)));
      const sgn = sort.dir === 'desc' ? -1 : 1;
      view = [...view].sort((wa, wb) => {
        const a = get(wa), b = get(wb);
        const ae = a == null || a === '', be = b == null || b === '';
        if (ae && be) return 0;
        if (ae) return 1;
        if (be) return -1;
        if (numeric) return (_dlNum(a) - _dlNum(b)) * sgn;
        return _dlText(a).localeCompare(_dlText(b)) * sgn;
      });
    }
  }

  // ── truly-empty data → canonical EmptyState (no toolbar) ──
  if (!allRows.length) {
    return <EmptyState tone="neutral" glyph="◇" msg={emptyMsg}/>;
  }

  const fixed     = columns.some(c => c.width);
  const anyActive = !!needle || Object.values(facetSel).some(v => v) || !!sort.key;
  const clearAll  = () => { setQ(''); setFacet({}); setSort({key:null, dir:null}); };
  const cycleSort = (id) => setSort(s =>
    s.key === id ? (s.dir === 'asc' ? {key:id, dir:'desc'} : {key:null, dir:null}) : {key:id, dir:'asc'});

  return (
    <>
      {toolsOn && (
        <div className="qe-dl-tools">
          {showSearch && (
            <div className="qe-dl-search">
              <span className="qe-dl-search-ic" aria-hidden="true">⌕</span>
              <input
                value={q}
                onChange={e => setQ(e.target.value)}
                placeholder="search…"
                spellCheck={false}
                onKeyDown={e => { if (e.key === 'Escape') { setQ(''); e.currentTarget.blur(); } }}/>
              {q && <button type="button" title="clear search" onClick={() => setQ('')}>✕</button>}
            </div>
          )}
          {showFilter && facets.map(f => (
            <label key={f.key} className="qe-dl-facet">
              <span>{f.label}</span>
              <select
                className="qe-input qe-select"
                value={facetSel[f.key] ?? ''}
                onChange={e => setFacet(s => ({...s, [f.key]: e.target.value}))}>
                <option value="">ALL</option>
                {f.options.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </label>
          ))}
          <span className="qe-grow"/>
          <span className="qe-dl-count">
            {view.length === allRows.length ? allRows.length : `${view.length} / ${allRows.length}`}
          </span>
          {anyActive && <button type="button" className="qe-dl-clear" onClick={clearAll}>CLEAR</button>}
        </div>
      )}
      {view.length ? (
        <table className={`qe-table ${dense?'tight':''}`} style={fixed ? {tableLayout:'fixed'} : undefined}>
          <thead>
            <tr>
              {columns.map((col, ci) => {
                // Edge columns keep their declared alignment; interior columns
                // are always centered so values read as columns, not edges.
                const isEdge  = ci === 0 || ci === columns.length - 1;
                const eff     = isEdge ? col.align : 'center';
                const canSort = sortableOf(col);
                const id      = colId(col);
                const active  = canSort && id != null && sort.key === id;
                const thStyle = {
                  ...(col.width ? {width: col.width} : null),
                  ...(toolsOn  ? {top: DL_TOOLS_H}  : null),
                };
                return (
                  <th
                    key={col.key ?? ci}
                    className={[eff==='right'?'r':eff==='center'?'c':'', canSort?'qe-sort':'', active?'on':''].filter(Boolean).join(' ')}
                    style={Object.keys(thStyle).length ? thStyle : undefined}
                    onClick={canSort ? () => cycleSort(id) : undefined}>
                    {col.label}
                    {canSort && <span className={`qe-sort-caret${active?'':' idle'}`} aria-hidden="true">{active ? (sort.dir==='desc'?'▼':'▲') : '↕'}</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {view.map(({row, _i}) => {
              const isSel = selected != null && row[selKey] === selected;
              return (
                <tr key={row[selKey] ?? _i}
                    className={isSel ? 'sel' : ''}
                    onClick={onClick ? () => onClick(row, _i) : undefined}
                    style={onClick ? {cursor:'pointer'} : undefined}>
                  {columns.map((col, ci) => {
                    const isEdge = ci === 0 || ci === columns.length - 1;
                    const eff = isEdge ? col.align : 'center';
                    const cls = [
                      eff==='right'?'r':eff==='center'?'c':'',
                      col.cell || '',
                    ].filter(Boolean).join(' ');
                    return (
                      <td key={col.key ?? ci} className={cls} style={col.width ? {width:col.width} : undefined}>
                        {col.render ? col.render(row, _i) : row[col.key]}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <div className="qe-dl-empty">
          no matches
          {anyActive && <> · <button type="button" onClick={clearAll}>clear</button></>}
        </div>
      )}
      {summary && (
        <div style={{
          padding:'3px 8px', borderTop:'1px solid var(--qe-line)',
          background:'var(--qe-panel)', flexShrink:0,
          display:'flex', justifyContent:'space-between',
          fontSize:'var(--qe-fs-xs)', fontFamily:'var(--qe-mono)',
          color:'var(--qe-sub)',
        }}>
          {typeof summary === 'string' ? <span>{summary}</span> : summary}
        </div>
      )}
    </>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// FieldList — canonical key→value rows. The vertical sibling of DataList:
// DataList = many records × columns (a table); FieldList = ONE record's fields
// stacked as label → value rows. Replaces the local VRow plus the ad-hoc
// label/value lists (Active Parameters, Correlated Exposure, Performance Ratios).
//
// rows: [{
//   label,                      // left label (uppercased by CSS)
//   value,                      // right value (mono, bold)
//   color?,                     // 'cyan'|'green'|'red'|'amber'|'sub' token, OR a raw CSS color
//   hint?,                      // small sublabel under the label (e.g. "annualized")
//   meta?,                      // 3rd right column (e.g. "50% cap")
//   bar?: { pct, color? },      // thin usage bar under the row
//   emphasis?,                  // highlighted callout row (cyan), no divider
// }]
// cols:  1 (default) or 2 — 2 lays rows out in a 2-up grid (Cash, Ratios)
// dense: tighter row height (17px vs the 20px pane-head default)
// ─────────────────────────────────────────────────────────────────────────
const FL_TONES = { cyan:'cyan', green:'green', red:'red', amber:'amber', sub:'sub' };
const FieldList = ({rows, cols=1, dense=false, style={}}) => (
  <div className={`qe-fl${cols===2?' qe-fl-2':''}${dense?' qe-fl-dense':''}`} style={style}>
    {rows.map((r, i) => {
      const tone = FL_TONES[r.color];
      const raw  = (!tone && r.color) ? r.color : undefined;   // allow raw CSS color
      return (
        <div key={r.label ?? i}
          className={`qe-fl-row${r.meta!=null?' qe-fl-meta3':''}${r.emphasis?' qe-fl-emph':''}`}
          title={r.hint || undefined}>
          <div className="qe-fl-l">
            <span style={{overflow:'hidden', textOverflow:'ellipsis'}}>{r.label}</span>
            {r.hint && <span className="qe-fl-hint">{r.hint}</span>}
          </div>
          <div className={`qe-fl-v${tone?' '+tone:''}`} style={raw?{color:raw}:undefined}>{r.value}</div>
          {r.meta != null && <div className="qe-fl-m">{r.meta}</div>}
          {r.bar && (
            <div className="qe-fl-bar">
              <span style={{width:`${Math.max(0,Math.min(100,r.bar.pct))}%`, background:r.bar.color||undefined}}/>
            </div>
          )}
        </div>
      );
    })}
  </div>
);

// ─────────────────────────────────────────────────────────────────────────
// StepperInput — qe-input with up/down increment buttons. `step` per click,
// `decimals` controls display precision, `min` clamps the floor, `color` tints
// the value. Holds its own value state. Use for nudgeable numeric fields
// (TP/SL price, TP/SL %, etc).
// ─────────────────────────────────────────────────────────────────────────
const StepperInput = ({defaultValue, step=1, decimals=2, min=null, color}) => {
  const [v, setV]       = React.useState(parseFloat(defaultValue));
  const [text, setText] = React.useState(() => parseFloat(defaultValue).toFixed(decimals));
  const clamp  = n => { let x = +(+n).toFixed(decimals); if (min != null && x < min) x = min; return x; };
  const commit = n => { const x = clamp(n); setV(x); setText(x.toFixed(decimals)); };
  const bump = d => commit(v + d*step);
  const btn = {
    width:16, flex:1, minHeight:0, padding:0, boxSizing:'border-box',
    display:'flex', alignItems:'center', justifyContent:'center',
    background:'transparent', border:'none', cursor:'pointer',
  };
  const triUp = {
    width:0, height:0,
    borderLeft:'3px solid transparent', borderRight:'3px solid transparent',
    borderBottom:'4px solid var(--qe-muted)',
  };
  const triDown = {
    width:0, height:0,
    borderLeft:'3px solid transparent', borderRight:'3px solid transparent',
    borderTop:'4px solid var(--qe-muted)',
  };
  return (
    <div style={{display:'flex', alignItems:'stretch', height:22, background:'var(--qe-panel)', border:'1px solid var(--qe-line)'}}>
      <input
        value={text}
        onChange={e => { setText(e.target.value); const n = parseFloat(e.target.value); if (!Number.isNaN(n)) setV(clamp(n)); }}
        onBlur={() => { const n = parseFloat(text); commit(Number.isNaN(n) ? v : n); }}
        onKeyDown={e => {
          if (e.key === 'Enter') e.currentTarget.blur();
          else if (e.key === 'ArrowUp')   { e.preventDefault(); bump(+1); }
          else if (e.key === 'ArrowDown') { e.preventDefault(); bump(-1); }
        }}
        style={{
          flex:1, minWidth:0, width:'100%', height:'100%', boxSizing:'border-box',
          background:'transparent', border:'none', outline:'none', padding:'0 7px',
          fontFamily:'var(--qe-mono)', fontSize:'0.7rem', fontWeight:600, color: color||'var(--qe-text)',
        }}/>
      <div style={{display:'flex', flexDirection:'column', height:'100%', borderLeft:'1px solid var(--qe-line)'}}>
        <button title="Increase" onClick={() => bump(+1)} style={{...btn, borderBottom:'1px solid var(--qe-line)'}}><span style={triUp}/></button>
        <button title="Decrease" onClick={() => bump(-1)} style={btn}><span style={triDown}/></button>
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// LockButton — workspace lock toggle. Compact pill that freezes / unfreezes a
// tiling workspace's drag + resize. `locked` is controlled; `onToggle()` flips
// it. Locked = cyan-accented closed padlock; unlocked = open padlock.
// Used in the top nav (left of the account picker); also a standalone primitive.
// ─────────────────────────────────────────────────────────────────────────
const LockButton = ({locked, onToggle, compact=false, style={}}) => (
  <button
    type="button"
    onClick={onToggle}
    className={`qe-btn qe-btn-sm qe-lockbtn${locked ? ' qe-btn-on' : ''}`}
    title={locked ? 'Workspace locked — click to edit layout' : 'Lock workspace layout'}
    aria-pressed={locked}
    style={{gap:4, ...style}}>
    <span style={{fontSize:'0.72rem', lineHeight:1}}>{locked ? '🔒' : '🔓'}</span>
    {!compact && <span style={{letterSpacing:'0.04em'}}>{locked ? 'LOCKED' : 'LOCK'}</span>}
  </button>
);

// ─────────────────────────────────────────────────────────────────────────
// NewsTickerBar — single-line footer news marquee. Async-fetches a headline
// feed and scrolls it continuously, holding ~1s at the start of each cycle.
//
// Wrapped in React.memo (stable props) so a busy parent can't re-render it —
// re-rendering would remount the animated run and restart the scroll (flicker).
// The async poll re-fetches on `pollMs` but only updates state when the
// headline set actually changes, so the marquee animation runs uninterrupted.
//
// Props:
//   news    — array of {id, source, impact, headline, tickers?, published_at}.
//             Defaults to the Regime feed (window.MOCK_REGIME.news).
//   label   — left chip text (default "NEWS")
//   meta    — right-side source tag (default "REGIME FEED · finnhub + bwe")
//   pollMs  — refetch cadence (default 4000)
// ─────────────────────────────────────────────────────────────────────────
const NewsTickerBar = React.memo(function NewsTickerBar({
  news, label = 'NEWS', meta = 'REGIME FEED · finnhub + bwe', pollMs = 4000,
}) {
  const sortFeed = () => {
    const feed = news || (window.MOCK_REGIME && window.MOCK_REGIME.news) || [];
    return [...feed].sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at));
  };
  // Seed synchronously on first render so the bar paints fully-populated.
  const [items, setItems] = React.useState(sortFeed);

  const fetchLatest = React.useCallback(async () => {
    await new Promise(r => setTimeout(r, 40));               // simulated latency
    return sortFeed();
  }, [news]);

  React.useEffect(() => {
    let alive = true;
    const key = arr => arr.map(n => n.id + ':' + n.published_at).join('|');
    (async function poll() {
      while (alive) {
        await new Promise(r => setTimeout(r, pollMs));
        const next = await fetchLatest();
        setItems(prev => (key(prev) === key(next) ? prev : next));
      }
    })();
    return () => { alive = false; };
  }, [fetchLatest, pollMs]);

  // Anchor "now" to the feed's own latest item (+18m) so relative times read
  // as a live stream.
  const nowMs = (items.length ? Date.parse(items[0].published_at) : Date.now()) + 18 * 60000;
  const impactColor = { high: 'var(--qe-red)', medium: 'var(--qe-amber)', low: 'var(--qe-muted)' };
  const rel = (iso) => {
    const m = Math.max(0, Math.round((nowMs - Date.parse(iso)) / 60000));
    if (m < 60) return m + 'm';
    const h = Math.round(m / 60);
    return h < 24 ? h + 'h' : Math.round(h / 24) + 'd';
  };

  // Build run content once; render twice (duplicate for a seamless loop).
  // Inlined — NOT a per-render component, so the animated node is never
  // recreated on re-render.
  const runItems = (prefix) => items.map((n, i) => (
    <span key={prefix + n.id + '-' + i} className="qe-newsticker-item">
      <span className="qe-newsticker-dot" style={{ background: impactColor[n.impact] || 'var(--qe-muted)' }}/>
      <span className="qe-newsticker-src">{n.source.toUpperCase()}</span>
      <span className="qe-newsticker-head">{n.headline}</span>
      {n.tickers && <span className="qe-newsticker-tk">{n.tickers}</span>}
      <span className="qe-newsticker-time">{rel(n.published_at)} ago</span>
      <span className="qe-newsticker-sep">◆</span>
    </span>
  ));

  return (
    <div className="qe-newsticker">
      <span className="qe-newsticker-label">
        <span className="qe-newsticker-live"/>{label}
      </span>
      <div className="qe-newsticker-track">
        <span className="qe-newsticker-run">{runItems('a')}</span>
        <span className="qe-newsticker-run" aria-hidden="true">{runItems('b')}</span>
      </div>
      {meta && <span className="qe-newsticker-meta">{meta}</span>}
    </div>
  );
});

// ─────────────────────────────────────────────────────────────────
// Switch — boolean toggle. The canonical on/off control (Sound, DND,
// auto-refresh, etc.). Distinct from LockButton (a button) and PeriodSelector.
// ─────────────────────────────────────────────────────────────────
const Switch = ({checked=false, onChange, label=null, title=null, accent='var(--qe-sub)'}) => (
  <div onClick={onChange} title={title} style={{display:'flex', alignItems:'center', gap:7, cursor:'pointer'}}>
    <span style={{width:26, height:14, background: checked?accent:'var(--qe-faint)', position:'relative', flexShrink:0, transition:'background .12s'}}>
      <span style={{position:'absolute', top:2, left: checked?14:2, width:10, height:10, background:'var(--qe-bg)', transition:'left .12s'}}/>
    </span>
    {label && <span style={{fontFamily:'var(--qe-ui)', fontSize:'0.6rem', fontWeight:600, color: checked?'var(--qe-text)':'var(--qe-muted)'}}>{label}</span>}
  </div>
);

// ─────────────────────────────────────────────────────────────────
// Chip — toggleable filter pill with optional count + per-chip mute.
// Used by notification + log filters. Distinct from PeriodSelector
// (single-select segmented) — Chips are independently muteable.
// ─────────────────────────────────────────────────────────────────
const Chip = ({label, count=null, active=false, muted=false, onClick, onMute=null}) => (
  <div onClick={onClick} style={{display:'inline-flex', alignItems:'center', gap:5, padding:'1px 4px 1px 7px', cursor:'pointer',
    border:`1px solid ${active?'var(--qe-line-2)':'var(--qe-faint)'}`, background: active?'var(--qe-panel)':'transparent'}}>
    <span style={{fontFamily:'var(--qe-ui)', fontWeight:600, fontSize:'0.56rem', letterSpacing:'0.04em', textTransform:'uppercase',
      color: active?'var(--qe-text)':'var(--qe-sub)', textDecoration: muted?'line-through':'none', opacity: muted?0.55:1}}>{label}</span>
    {count!=null && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:600, color:'var(--qe-muted)'}}>{count}</span>}
    {onMute && <span title={muted?'Unmute':'Mute'} onClick={(e)=>{e.stopPropagation();onMute();}}
      style={{width:14, height:14, display:'inline-flex', alignItems:'center', justifyContent:'center', fontSize:'0.62rem', lineHeight:1, color: muted?'var(--qe-amber)':'var(--qe-muted)'}}>{muted?'⊘':'♪'}</span>}
  </div>
);

// ─────────────────────────────────────────────────────────────────
// Banner — full-width pinned alert bar (sits under the nav). tone:
// err | warn | info | ok. Optional action button. Used for trading
// HALT, degraded-feed warnings, etc.
// ─────────────────────────────────────────────────────────────────
const _BANNER = {
  err:  ['var(--qe-red)',   'var(--qe-bg-red)'],
  warn: ['var(--qe-amber)', 'var(--qe-bg-amber)'],
  info: ['var(--qe-cyan)',  'var(--qe-bg-cyan)'],
  ok:   ['var(--qe-green)', 'var(--qe-bg-green)'],
};
const Banner = ({tone='err', tag=null, title, detail=null, time=null, releaseIn=null, releaseLabel='RELEASES IN', actionLabel='ACKNOWLEDGE', onAction=null}) => {
  const [c, bg] = _BANNER[tone] || _BANNER.err;
  return (
    <div style={{flexShrink:0, position:'relative', display:'flex', alignItems:'center', gap:12, height:30, padding:'0 12px', background:bg, borderBottom:`1px solid ${c}`}}>
      <span style={{position:'absolute', left:0, top:0, bottom:0, width:3, background:c}}/>
      {tag && <span className="qe-badge qe-badge-solid" style={{background:c}}>{tag}</span>}
      {time && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.62rem', fontWeight:600, color:'var(--qe-sub)', whiteSpace:'nowrap', letterSpacing:'0.02em'}}>{time}</span>}
      <span style={{fontFamily:'var(--qe-ui)', fontWeight:700, color:c, fontSize:'0.72rem', letterSpacing:'0.02em', whiteSpace:'nowrap'}}>{title}</span>
      {detail && <span style={{fontFamily:'var(--qe-mono)', color:'var(--qe-text-dim)', fontSize:'0.64rem', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis', minWidth:0}}>{detail}</span>}
      <span className="qe-grow"/>
      {releaseIn != null && (
        <React.Fragment>
          <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.14em', color:'var(--qe-muted)', whiteSpace:'nowrap'}}>{releaseLabel}</span>
          <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.72rem', fontWeight:700, color:c, whiteSpace:'nowrap', border:`1px solid ${c}`, padding:'1px 7px', background:'rgba(0,0,0,0.28)'}}>{releaseIn}</span>
        </React.Fragment>
      )}
      {onAction && <button className={`qe-btn qe-btn-sm ${tone==='err'?'qe-btn-danger':''}`} onClick={onAction}>{actionLabel}</button>}
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────
// Toast — transient corner popup. Severity rail (left) + auto-dismiss
// countdown bar (bottom, behind the rail). tone: ok|info|warn|err|mute.
// The .qe-toast-bar shrink animation drives the countdown (CSS in host).
// ─────────────────────────────────────────────────────────────────
const _TOASTC = { err:'var(--qe-red)', warn:'var(--qe-amber)', info:'var(--qe-cyan)', ok:'var(--qe-green)', mute:'var(--qe-line-2)' };
const Toast = ({tone='mute', tag=null, time=null, title, detail=null, onClose=null, onClick=null}) => {
  const c = _TOASTC[tone] || _TOASTC.mute;
  return (
    <div className="qe-toast" onClick={onClick} style={{position:'relative', width:300, background:'var(--qe-card)', borderTop:'1px solid var(--qe-line)', borderRight:'1px solid var(--qe-line)', boxShadow:'0 8px 24px rgba(0,0,0,0.55)', overflow:'hidden', cursor: onClick?'pointer':'default'}}>
      <div style={{position:'relative', zIndex:1, display:'flex', flexDirection:'column', gap:2, padding:'6px 9px 7px 11px'}}>
        <div style={{display:'flex', alignItems:'center', gap:7}}>
          {tag && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.14em', color:'var(--qe-muted)'}}>{tag}</span>}
          {time && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.5rem', letterSpacing:'0.02em', color:'var(--qe-muted)'}}>· {time}</span>}
          {tone!=='mute' && tone!=='info' && tone!=='ok' && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.1em', color:c}}>{tone==='err'?'HALT':'RISK'}</span>}
          <span className="qe-grow"/>
          {onClose && <span onClick={(e)=>{e.stopPropagation();onClose();}} style={{color:'var(--qe-muted)', fontSize:'0.85rem', lineHeight:1, cursor:'pointer'}}>×</span>}
        </div>
        <div style={{fontFamily:'var(--qe-ui)', fontWeight:600, fontSize:'0.7rem', color:'var(--qe-text)', lineHeight:1.2}}>{title}</div>
        {detail && <div style={{fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-sub)', lineHeight:1.28}}>{detail}</div>}
      </div>
      <span style={{position:'absolute', left:0, right:0, bottom:0, height:1, background:'var(--qe-line)', zIndex:1}}/>
      <span style={{position:'absolute', left:0, top:0, bottom:0, width:2, background:c, zIndex:2}}/>
      <div style={{position:'absolute', left:0, right:0, bottom:0, height:2, zIndex:2}}><div className="qe-toast-bar" style={{height:'100%', background:c, opacity:0.9}}/></div>
    </div>
  );
};

// ── PageHeader — standardized page title bar (title · subtitle · right slot) ──
// One source of truth for the per-page header used across every screen.
// Spacing/size/border/bg are fixed here so all pages stay in lockstep.
//   title    — page name (required)
//   subtitle — muted breadcrumb/feature list (optional)
//   left     — extra nodes rendered right after the subtitle, before the spacer
//   children — right-aligned nodes (status dots, period nav…) after a flex grow
const PageHeader = ({title, subtitle=null, left=null, children=null}) => (
  <div className="qe-page-header" style={{
    display:'flex', alignItems:'center', gap:12, padding:'0 10px', height:34, boxSizing:'border-box',
    borderBottom:'1px solid var(--qe-line)', background:'var(--qe-page)', flexShrink:0,
  }}>
    <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.78rem', fontWeight:700, color:'var(--qe-text)', whiteSpace:'nowrap', letterSpacing:'0.04em', textTransform:'uppercase'}}>{title}</span>
    {subtitle && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.56rem', color:'var(--qe-muted)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis', minWidth:0}}>{subtitle}</span>}
    {left}
    {children && <React.Fragment><div className="qe-grow"/>{children}</React.Fragment>}
  </div>
);

Object.assign(window, {
  mockOhlc, mockEquity, mockSpark,
  Lbl, SecLbl, KV, Card, Stat, HeroNumber, Delta,
  StatusDot, Badge, RegimeBadge, PeriodSelector, Gauge, EmptyState,
  Tabs, Strip, FlashCell, LiveValue, useLiveTicker, LiveNumber, LivePct, LiveClock,
  asciiSpark, ASCII_SPARK,
  Pane, PaneHead, PaneFoot, RefreshButton, ReloadGlyph, ReloadIconSVG, BrailleSquares, Spinner, useSpinFrame, RELOAD_MS, PaneErrorBoundary, DataList, FieldList, StepperInput, LockButton, NewsTickerBar,
  Switch, Chip, Banner, Toast, PageHeader,
});
