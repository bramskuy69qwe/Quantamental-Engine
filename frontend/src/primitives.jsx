/* v3.0 — Primitives. Standardize the audit's "drift" findings:
   one Card, one Stat, one Badge, one StatusDot, one EmptyState,
   one PeriodSelector, one Gauge, one Table.
   Everything is a React component for portability into htmx templates. */

/* P8 wave 1: the mockOhlc/mockEquity/mockSpark generators are GONE — their
   only consumer was nav-and-data's MOCK dataset, deleted with the chrome
   rebind (chrome-live.js). The DEV proving ground uses its own deterministic
   DEMO_EQUITY series (app-shell.jsx). */

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
// `fill` = this empty state IS the pane's whole content, so the dashed frame
// surrounds the entire pane body, offset 2x the standard pane gap from the pane
// wall, content centred both axes (the no-data standard — see tokens.css
// ".qe-pane-body .qe-empty.fill"). OPT-IN, and deliberately so: an EmptyState
// rendered alongside siblings inside a pane body (a list's zero-state, a chart
// pane's "no series" notice above a legend) must stay in flow or it would cover
// them. The CSS additionally requires a .qe-pane-body ancestor, so passing
// `fill` in a modal or an inbox list is inert rather than destructive.
const EmptyState = ({tone='neutral', glyph='∅', msg, hint, cta=null, fill=false}) => (
  <div className={`qe-empty ${tone==='neutral'?'':tone}${fill?' fill':''}`}>
    <div className="qe-empty-glyph">{glyph}</div>
    <div className="qe-empty-msg">{msg}</div>
    {hint && <div style={{fontSize:'var(--qe-fs-xs)', color:'var(--qe-muted)', textAlign:'center'}}>{hint}</div>}
    {cta && <div className="qe-empty-cta">{cta}</div>}
  </div>
);

// ─────────────────────────────────────────────────────────────────
// HeatBar — THE excursion cell. One primitive for every MFE/MAE
// rendering, ported from the design's HistHeat (pages.jsx:56-73).
//
// THREE CHANNELS, and all three are load-bearing — the build previously
// shipped only the first and read as two disconnected bars:
//   1. centre ENTRY rule — the datum both excursions are measured from.
//      Without it the two halves float and the cell loses its meaning.
//   2. red extent LEFT = MAE (heat against) · green extent RIGHT = MFE
//      (heat in favour), both scaled to the row's own span.
//   3. bright EXIT tick — where the trade actually closed inside its own
//      range. This is the channel that turns the cell from "how far did
//      it swing" into "…and how much of that did we keep".
//
// Scale: span = max(|mfe|, |mae|, |pnl|), so the exit tick can never fall
// outside the box. Min extent 1.5% (design) keeps a measured-zero side
// visible as a sliver rather than vanishing.
//
// REAL-DATA GUARDS (not in the mock-fed design, keep them):
//   · mfe AND mae both null = NOT MEASURED → '—'. Never draw a zero-width
//     bar for unknown; the P8 audit's F2 finding was exactly this class of
//     fabricated certainty on un-backfilled rows.
//   · pnl null → the exit tick is OMITTED rather than parked at centre,
//     which would assert a break-even close that was never measured.
const HeatBar = ({mfe, mae, pnl = null, w = 84, h = 12}) => {
  if (mfe == null && mae == null) return <span style={{color:'var(--qe-muted)'}}>—</span>;
  const f = +mfe || 0, a = +mae || 0, p = pnl == null ? null : (+pnl || 0);
  const span = Math.max(Math.abs(f), Math.abs(a), Math.abs(p == null ? 0 : p)) || 1;
  const half = (v) => (v / span) * 50;
  const maeW = Math.max(1.5, -half(Math.min(0, a)));   // mae is <= 0 by convention
  const mfeW = Math.max(1.5,  half(Math.max(0, f)));
  const exit = p == null ? null : 50 + half(p);
  const title = `MFE +${Math.abs(f).toFixed(2)} / MAE ${a.toFixed(2)}`
    + (p == null ? '' : ` · exit ${p >= 0 ? '+' : ''}${p.toFixed(2)}`);
  return (
    <div title={title} style={{position:'relative', width:w, height:h, background:'var(--qe-panel)',
      border:'1px solid var(--qe-faint)', flexShrink:0, display:'inline-block', verticalAlign:'middle'}}>
      <div style={{position:'absolute', left:'50%', top:0, bottom:0, width:1, background:'var(--qe-line-2)'}}/>
      <div style={{position:'absolute', top:2, bottom:2, right:'50%', width:maeW + '%', background:'var(--qe-red)', opacity:0.42}}/>
      <div style={{position:'absolute', top:2, bottom:2, left:'50%',  width:mfeW + '%', background:'var(--qe-green)', opacity:0.42}}/>
      {exit != null && <div style={{position:'absolute', top:-1, bottom:-1, left:exit + '%', width:2,
        marginLeft:-1, background: p >= 0 ? 'var(--qe-green)' : 'var(--qe-red)'}}/>}
    </div>
  );
};

// HeatBarLabelled — the design's HistHeatLarge (pages.jsx:76-88): the same
// cell at detail size with its three values spelled out. Use in a detail /
// drilldown pane; the compact HeatBar stays the table cell.
const HeatBarLabelled = ({mfe, mae, pnl = null, pct = null, h = 16}) => (
  <div>
    <div style={{display:'flex', justifyContent:'space-between', fontFamily:'var(--qe-mono)',
      fontSize:'0.5rem', letterSpacing:'0.06em', marginBottom:3}}>
      <span style={{color:'var(--qe-red)'}}>MAE {mae == null ? '—' : (+mae).toFixed(2)}</span>
      <span style={{color:'var(--qe-muted)'}}>ENTRY</span>
      <span style={{color:'var(--qe-green)'}}>MFE {mfe == null ? '—' : '+' + Math.abs(+mfe).toFixed(2)}</span>
    </div>
    <HeatBar mfe={mfe} mae={mae} pnl={pnl} w={'100%'} h={h}/>
    {pnl != null && (
      <div style={{textAlign:'center', fontFamily:'var(--qe-mono)', fontSize:'0.5rem',
        color: (+pnl) >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', marginTop:3}}>
        ▲ exit {(+pnl) >= 0 ? '+' : ''}{(+pnl).toFixed(2)}
        {pct == null ? '' : ` (${(+pct) >= 0 ? '+' : ''}${(+pct).toFixed(2)}%)`}
      </div>
    )}
  </div>
);
Object.assign(window, { HeatBar, HeatBarLabelled });

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

/* P8 wave 1: useLiveTicker/LiveNumber/LivePct (the random-walk live-number
   family) are GONE — zero production callers existed and plan §4 lists them
   as strip targets. Live numbers bind LiveValue to real SSE/poll data
   (window.QE_SSE / useLiveId); the DEV proving ground's LiveValueDemo
   (app-shell.jsx) carries its own sanctioned demo ticker. */

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
//   foot     optional {tone, msg} — a TRUTHFUL pane status line (counts, poll
//            cadence, source attribution — DESIGN.md §5 PaneFoot policy).
//            id/ms are ACCEPTED for the DEV proving ground but never passed
//            by production pages: fabricated event-ids/latency are banned.
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
const RELOAD_MS = 620;   // how long the reload ANIMATION runs (ms) — not a measurement
const FOOT_H    = 17;    // PaneFoot height (16) + 1px top border — body veil stops here

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
        <EmptyState fill tone="err" glyph="⚠"
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

// ─────────────────────────────────────────────────────────────────────────
// qeFootState — the ONE production PaneFoot deriver (DESIGN.md §5, 4-tier
// data-state model; operator-ratified). Foots are DATA-STATE lines, never
// descriptive prose:
//   1 fine     → ok   `connected [12ms]` (real measured fetch ms)
//   2 degraded → warn data on screen but imperfect: `delayed [640ms]`
//                (ms > 500) · `response corrupt · showing last data` ·
//                `no network · showing last data · retrying`
//   3 error    → err  nothing usable to show; the CAUSE is named:
//                `endpoint not found (404)` · `no network — engine
//                unreachable` · `server error (500)` · `unauthorized (403)`
//                · `corrupt response`
//   4 attempt  → sub + busy (braille): `loading…` / `reconnecting…`
// 2-vs-3 rule: data on screen → tier 2 (warn, cause appended); no data →
// tier 3 (err, cause displayed). `empty` (successful fetch, zero rows) is
// accepted so callers can pass full state — it stays tier 1; the BODY owns
// empty-state display (EmptyState), the foot reports the pipe.
/* ── THE READ DEADLINE (2026-08-01, closes the filed WARM HANG) ────────────
 * `fetch` has no default timeout, and a promise that never settles runs
 * NEITHER the resolve nor the catch branch. So before this, a pipe that
 * answered once and went dark later kept its `{err:null, ms}` entry forever
 * and its foot read `ok · connected [12ms]` indefinitely — stale risk numbers
 * under an affirmative healthy signal, the one failure a data-state foot
 * exists to prevent. Nothing downstream could see it: every foot in the app
 * answers "did this pipe ever report?", never "did it report RECENTLY".
 *
 * The cure is at the REQUEST, not at the foot: give every read a deadline, so
 * a hang becomes a real rejection that flows through the `err` channel the
 * 4-tier deriver already renders correctly. That is why no foot call site
 * changes — and why the repaint happens at all. A timestamp-and-threshold
 * scheme (the shape originally filed) would need a clock to evaluate it, and
 * every clock available to a page — setInterval, setTimeout, a render tick —
 * is throttled by exactly the conditions that strand a pipe, so the detector
 * sleeps precisely when it is needed. See DESIGN.md § the deadline rule.
 *
 * Three further defects in this class die with the same change, each verified
 * at the line before being claimed:
 *   · chained-setTimeout pollers (Pre-Trade price 1 s / orderbook 2 s /
 *     link-window) reschedule AFTER the await, so one hang stopped them
 *     permanently — while their foots promised `· retrying`.
 *   · the notification poll's `inFlight` latch is released in a `finally`
 *     that a hang never reaches, silently killing the alert feed for the
 *     session.
 *   · hung requests held their connections, and Chrome's ~6-per-origin cap
 *     then queued every other same-origin poll behind them.
 *
 * READS ONLY, DELIBERATELY. The write helpers (_cfgPostForm / _cfgPostJson /
 * _lkForm / _rgPost / _mdlSend / _mdlUpload / _dashPostJson and the calculator
 * POSTs) keep today's unbounded behaviour: aborting a mutation in flight
 * cannot cancel what the server already did, so it would trade a stuck spinner
 * for "did my save land?" — a worse question, and a different defect class
 * from the one this closes. A read carries no such ambiguity: nothing happened,
 * ask again.
 */
const QE_READ_DEADLINE_MS = 30_000;   // one-shot reads (no successor coming)

// Duration for operator-facing text. Declared here rather than beside
// qeFootCause because _ptDeadlineErr below builds a message with it too, and
// two spellings of the same duration is how `no response in 0s` reaches a
// console while the foot says `300ms` (caught by executing the probe).
const _qeSecs = (ms) => (ms >= 1000 ? `${Math.round(ms / 1000)}s` : `${Math.round(ms)}ms`);

/* A POLLED read's deadline is its own interval, floored at 5 s.
 * Rationale, in one line: a request that has not answered by the time its
 * successor is due is already superseded — cancelling costs nothing (the
 * successor is going out anyway) and frees the connection it needs. The floor
 * keeps sub-second pollers (price 1 s, orderbook 2 s) from cancelling a merely
 * slow but healthy response. Derive this from the SAME literal that feeds
 * setInterval so the two cannot drift. */
const qePollDeadline = (intervalMs) => Math.max(intervalMs || 0, 5_000);

/* ★ A CLIENT DEADLINE MUST NEVER BE TIGHTER THAN THE ENGINE'S OWN UPSTREAM
 * BUDGET, or it kills requests the server was about to answer — and the pane
 * then never loads AT ALL, which is a worse lie in the other direction.
 * Two polled reads have a handler that makes a synchronous third-party call
 * (verified by walking every polled endpoint's handler, not by sampling):
 * `/api/price/{ticker}` and `/api/calculator/orderbook/{ticker}` both await
 * `fetch_orderbook` → the ccxt adapter, whose default timeout is 10 s with no
 * override and no retry. Under exchange latency or rate-limit backoff a
 * healthy 6-10 s response is normal there, and the 5 s poll floor would abort
 * every one of them forever. So those two get the upstream budget instead.
 * It costs nothing: both are chained-setTimeout pollers that reschedule only
 * AFTER their await, so each holds at most ONE outstanding request whatever
 * the deadline. Every other polled read is cache- or DB-backed. */
const QE_UPSTREAM_READ_DEADLINE_MS = 12_000;

/* Re-poll when the page comes back to the front, at most once a second.
 * WHY IT EXISTS: a hidden page's timers are throttled to ~1/min and a frozen
 * page's stop entirely, so no request is outstanding for a deadline to bound
 * and the last-painted frame keeps a `connected` foot over minute-old numbers.
 * Refreshing on return beats labelling it stale.
 * WHY IT IS RATE-LIMITED: `visibilitychange` fires on every transition, so
 * alt-tabbing quickly would burst one request per pipe per toggle against the
 * same ~6-connections-per-origin cap named above as the hang's aggravator.
 * Returns an unsubscribe, so a store with a lifecycle can unhook. */
const qeOnVisible = (fn, minGapMs = 1_000) => {
  let last = 0;
  const handler = () => {
    if (document.hidden) return;
    const now = Date.now();
    if (now - last < minGapMs) return;
    last = now;
    fn();
  };
  document.addEventListener('visibilitychange', handler);
  return () => document.removeEventListener('visibilitychange', handler);
};

const _ptDeadlineErr = (url, ms) => {
  const err = new Error(url + ' no response in ' + _qeSecs(ms));
  // `status: 0` keeps every existing consumer's network-sentinel branch
  // working unchanged; `timeoutMs` lets qeFootCause say something truer than
  // "no network" — the socket is fine, the ENGINE is not answering.
  err.status = 0;
  err.timeoutMs = ms;
  return err;
};

/* Aborts with the tagged error as the abort REASON, so `fetch` (and the body
   read) reject with exactly that object and the catches below can re-throw it
   untouched. The timer is cleared on settle — an AbortSignal.timeout() would
   leave one live timer per request, and the 1 Hz price poll issues 30 of them
   inside a single 30 s window. */
const _ptFetch = async (url, init, deadlineMs) => {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(_ptDeadlineErr(url, deadlineMs)), deadlineMs);
  try {
    return { r: await fetch(url, { ...init, signal: ac.signal }), t };
  } catch (e) {
    clearTimeout(t);
    throw e;
  }
};

/* Our own abort, whatever the engine did with the reason. `abort(reason)`
   rejects the fetch WITH that object, so the tag normally survives; a runtime
   that drops it still yields a DOMException named AbortError, and re-tagging
   here keeps the foot's cause right instead of falling through to the
   "no network" branch, which would name the wrong thing. */
const _ptDeadlineHit = (e, url, deadlineMs) => (
  e && e.timeoutMs != null ? e
    : (e && e.name === 'AbortError') ? _ptDeadlineErr(url, deadlineMs)
    : null
);

/* _ptJson — THE shared JSON-fetch plumbing (moved here from pages-pretrade
   in P8 wave 2, audit L1-F8: dash-tiled consumed it against load order).
   Errors carry `status` (HTTP code; 0 = network-level failure), `corrupt`
   (body was not JSON) and `timeoutMs` (the deadline that fired) for the
   qeFootState 4-tier deriver — ADDITIVE: plain catches see an Error exactly
   as before. `deadlineMs` defaults to the one-shot budget; POLLED callers
   pass qePollDeadline(theirInterval). */
const _ptJson = async (url, deadlineMs = QE_READ_DEADLINE_MS) => {
  let r, t;
  try {
    ({ r, t } = await _ptFetch(url, { headers: { Accept: 'application/json' } }, deadlineMs));
  } catch (e) {
    const hit = _ptDeadlineHit(e, url, deadlineMs);
    if (hit) throw hit;
    const err = new Error(url + ' unreachable');
    err.status = 0;
    throw err;
  }
  if (!r.ok) {
    clearTimeout(t);
    const err = new Error(url + ' ' + r.status);
    err.status = r.status;
    throw err;
  }
  try {
    return await r.json();
  } catch (e) {
    // The deadline covers the BODY too: headers sent then a stalled stream is
    // a hang like any other, and mapping it to `corrupt` would name the wrong
    // cause on the foot.
    const hit = _ptDeadlineHit(e, url, deadlineMs);
    if (hit) throw hit;
    const err = new Error(url + ' corrupt response');
    err.corrupt = true;
    throw err;
  } finally {
    clearTimeout(t);
  }
};

const qeFootCause = (err) => {
  if (!err) return 'unknown error';
  if (err.corrupt) return 'corrupt response';
  // BEFORE the status checks: a deadline error carries status 0 (the network
  // sentinel), and "no network — engine unreachable" would be a false
  // diagnosis. The connection was made; the engine did not answer on it.
  if (err.timeoutMs != null) return `no response in ${_qeSecs(err.timeoutMs)} — engine not answering`;
  const s = err.status;
  if (s === 404) return 'endpoint not found (404)';
  if (s === 401 || s === 403) return `unauthorized (${s})`;
  if (s >= 500) return `server error (${s})`;
  if (s == null || s === 0) return 'no network — engine unreachable';
  return `request failed (${s})`;
};
const qeFootState = ({ loading, err, corrupt, status, hasData, empty, ms, retrying }) => {
  // Compose the error DESCRIPTOR onto a plain object (never mutate the
  // caller's Error across renders); flat corrupt/status compose for callers
  // that track them apart from the thrown error. `status: 0` alone IS an
  // error (this codebase's network sentinel) — null-check, not truthiness.
  const e = (err || corrupt != null || status != null)
    ? {
        corrupt: (err && err.corrupt) != null ? err.corrupt : corrupt,
        status: (err && err.status) != null ? err.status : status,
        timeoutMs: err ? err.timeoutMs : undefined,
      }
    : null;
  if (loading && !hasData) {
    return { tone: 'sub', busy: true, msg: e ? 'reconnecting…' : 'loading…' };
  }
  if (e) {
    if (hasData) {
      // tier 2 — degraded, keep-last-good. `· retrying` only when the
      // caller genuinely re-polls (a one-shot fetch must not promise it).
      const suffix = retrying ? ' · retrying' : '';
      if (e.corrupt) return { tone: 'warn', msg: `response corrupt · showing last data${suffix}` };
      // Same precedence as qeFootCause, and for the same reason: a deadline
      // error's status is 0, so the network branch below would claim the
      // engine is unreachable when it is reachable and silent.
      if (e.timeoutMs != null) return { tone: 'warn', msg: `no response in ${_qeSecs(e.timeoutMs)} · showing last data${suffix}` };
      if (e.status == null || e.status === 0) return { tone: 'warn', msg: `no network · showing last data${suffix}` };
      return { tone: 'warn', msg: `${qeFootCause(e)} · showing last data${suffix}` };
    }
    return { tone: 'err', msg: qeFootCause(e) };
  }
  if (ms != null && ms > 500) return { tone: 'warn', msg: `delayed [${Math.round(ms)}ms]` };
  return { tone: 'ok', msg: `connected${ms != null ? ` [${Math.round(ms)}ms]` : ''}` };
};

// PaneFoot — the pane's DATA-STATE line (derive via qeFootState — see the
// 4-tier model above / DESIGN.md §5). Tones: ok | info | warn | err | sub.
// `id`/`ms` render when passed (DEV proving-ground demos) but production
// pages never pass them raw — the measured ms rides INSIDE qeFootState's msg.
// `busy` swaps the glyph for the braille loading spinner (tier 4 + reload).
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
  // streams/effects re-run and any caught error is cleared. The post-reload
  // foot line is HONEST (PaneFoot policy — the pre-policy shape minted a fake
  // event-id + a fake "elapsed" that was just the animation timer, and claimed
  // "resynced from source" even on panes whose data hooks live in the PARENT
  // and cannot re-run from a child remount): with an `onRefresh` hook the pane
  // genuinely refetches; without one, only the body remounted — say so.
  const doRefresh = React.useCallback(() => {
    setRefresh(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const f = footRef.current;
      // If the remounted body throws again, the boundary flips `errored` and
      // the effFoot err branch overrides this line.
      setErrored(false);
      if (f) setRFoot({tone:'ok', msg: onRefresh ? 'reloaded · refetched' : 'reloaded · body remounted'});
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
      {/* qe-pane-body + position:relative are the anchor for the no-data
          standard (tokens.css). position:relative is additive here: the reload
          veil is a SIBLING of this div (child of the pane root, below), and the
          DataList toolbar is position:sticky — which resolves against the
          scroll container, i.e. this div, unchanged. */}
      <div className="qe-pane-body" style={{flex:1, minHeight:0, padding:'5px 7px', overflow:'auto', position:'relative', ...bodyStyle}}>
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

// ── ModelDialog — shared overlay shell (scrim + centering + close ✕) ───────
// A Pane, layered as a modal. Hoisted here from pages-models.jsx
// (operator-bug #6) so any page can raise a confirm/detail dialog — the calc-
// cancel confirm on Linkage is the first non-Models consumer. Bare-identifier
// visible to every later module (single concatenated bundle scope) and also
// window-exported below. `footer` = right-aligned action row; `foot` = a
// PaneFoot state line; onClick-scrim + ✕ both close.
const ModelDialog = ({ title, onClose, width = 460, children, footer, foot = null, hot = true }) => (
  <div style={{ position: 'absolute', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.66)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}
    onClick={onClose}>
    <div onClick={(e) => e.stopPropagation()} style={{ width, maxWidth: '100%', maxHeight: '100%', display: 'flex', flexDirection: 'column', position: 'relative',
      background: 'var(--qe-card)', border: '1px solid var(--qe-line-2)', boxShadow: '0 24px 70px -16px var(--qe-bg)' }}>
      <PaneHead title={title} hot={hot}
        right={<button onClick={onClose} title="Close"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 14, height: 14,
            border: '1px solid var(--qe-faint)', background: 'transparent', color: 'var(--qe-muted)', cursor: 'pointer',
            fontSize: '0.7rem', lineHeight: 1, padding: 0 }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--qe-red)'; e.currentTarget.style.borderColor = 'var(--qe-red)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--qe-muted)'; e.currentTarget.style.borderColor = 'var(--qe-faint)'; }}>✕</button>} />
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 10 }}>{children}</div>
      {foot && <PaneFoot {...foot} />}
      {footer && <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6, padding: '7px 9px', borderTop: '1px solid var(--qe-line)', background: 'var(--qe-panel)', flexShrink: 0 }}>{footer}</div>}
      <span className="qe-grip" style={{ pointerEvents: 'none' }} />
    </div>
  </div>
);

// ── DataList tooling helpers (search / sort / filter) ─────────────────────
// Thresholds that govern the AUTO behaviour. Tools light up on any list with
// >= DL_AUTO_MIN rows; categorical columns with a small distinct-value set
// auto-become facet filters.
//
// operator-bug #2 follow-up: DL_AUTO_MIN was 5, tuned against the Meridian
// design's DENSE mock data (its tables carry 5-6 rows, so AUTO lit up). In
// production the live account is SPARSE — often 1-2 open positions — so the
// dashboard/linkage/analytics/regime tables stayed dark and the operator saw
// no search/sort/filter at all. Lowered to 1 so tools appear on any NON-empty
// data table (a truly-empty table still short-circuits to EmptyState above the
// toolbar, and facet dropdowns still require >= 2 distinct values, so a 1-row
// table shows just search + sortable headers — no empty chrome). This keeps
// the design's AUTO philosophy (only 1 explicit tools= override in the whole
// reference) and simply retunes the threshold for real data density.
const DL_AUTO_MIN        = 1;   // rows to auto-enable tools on ANY non-empty table
const DL_AUTO_MIN_FACET  = 1;   // (moot once DL_AUTO_MIN=1, kept for the OR clause)
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
    // A single distinct value carries no information for an AUTO-derived facet,
    // so auto still bails. A FORCED facet is different: the page author declared
    // that column the pane's filter axis, and the operator's rule is that every
    // DataList pane offers search + sort + filter at all times. Homogeneous data
    // (one open position, one regime) is the normal live shape here, and a
    // filter that vanishes exactly when the table is small is the complaint this
    // sweep exists to fix. [operator directive 2026-07-25]
    if (distinct.length < 2 && !forced) return;
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
//          {search?, sort?, filter?, scope?} → force on with granular control
//          scope: string — M9 (wiring inventory, 2026-08-04): on a
//          SERVER-PAGED table these tools refine only the rows in hand, and
//          nothing on screen said so — a filter that silently ignores the
//          other pages reads as "no matches elsewhere". Callers whose rows
//          are one page of a larger set pass e.g. scope:'loaded page only'
//          and the toolbar carries the caption beside the row count.
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
    return <EmptyState fill tone="neutral" glyph="◇" msg={emptyMsg}/>;
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
          {toolsObj && toolsObj.scope && (
            <span className="qe-dl-scope" title={
              // caller-agnostic default; a host whose full-set controls have
              // a specific shape supplies scopeTitle (audit LOW: the first
              // draft baked "controls above the table" into the primitive)
              toolsObj.scopeTitle
              || 'Search, sort and filter here act only on the rows currently loaded.'
            }>· {toolsObj.scope}</span>
          )}
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
/* StepperNumber — the CONTROLLED sibling of StepperInput.
   Same affordance (▲▼ buttons, ArrowUp/ArrowDown, min clamp, blur-commit
   rounding) but the value lives in the CALLER's state, which is why the
   uncontrolled StepperInput could not be used on the Pre-Trade form
   (pretrade-1): that form owns tpPrice/slPrice/tpPct/slPct and an internal
   useState would fight it — typing would work but any programmatic change
   (prefill from a model, Clear, a recalled setup) would not reach the input.

   Deliberately does NOT round while typing: `value` is echoed verbatim so an
   in-progress "0." or "1.2" is never rewritten under the cursor. Rounding to
   `decimals` happens on blur and on every button/arrow bump, matching
   StepperInput's commit semantics. */
const StepperNumber = ({value, onChange, step=1, decimals=2, min=null, id, placeholder, title, onKeyDown, style}) => {
  const clamp = (n) => { let x = +(+n).toFixed(decimals); if (min != null && x < min) x = min; return x; };
  const bump = (d) => {
    const n = parseFloat(value);
    onChange(String(clamp((Number.isNaN(n) ? 0 : n) + d * step)));
  };
  const btn = {
    width:16, flex:1, minHeight:0, padding:0, boxSizing:'border-box',
    display:'flex', alignItems:'center', justifyContent:'center',
    background:'transparent', border:'none', cursor:'pointer',
  };
  const tri = (up) => ({
    width:0, height:0,
    borderLeft:'3px solid transparent', borderRight:'3px solid transparent',
    [up ? 'borderBottom' : 'borderTop']: '4px solid var(--qe-muted)',
  });
  return (
    <div style={{display:'flex', alignItems:'stretch', height:22, background:'var(--qe-panel)', border:'1px solid var(--qe-line)', ...style}}>
      <input id={id} className="qe-input" value={value} placeholder={placeholder} title={title}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => { const n = parseFloat(value); if (!Number.isNaN(n)) onChange(String(clamp(n))); }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp')        { e.preventDefault(); bump(+1); }
          else if (e.key === 'ArrowDown') { e.preventDefault(); bump(-1); }
          else if (onKeyDown)             { onKeyDown(e); }
        }}
        style={{flex:1, minWidth:0, height:'100%', border:'none', background:'transparent'}}/>
      <div style={{display:'flex', flexDirection:'column', borderLeft:'1px solid var(--qe-line)'}}>
        <button type="button" tabIndex={-1} title="increase" onClick={() => bump(+1)} style={btn}><span style={tri(true)}/></button>
        <button type="button" tabIndex={-1} title="decrease" onClick={() => bump(-1)} style={{...btn, borderTop:'1px solid var(--qe-line)'}}><span style={tri(false)}/></button>
      </div>
    </div>
  );
};
Object.assign(window, { StepperNumber });

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
//   news    — array of {id, source, headline, tickers?, published_at, impact?}.
//             `impact` is OPTIONAL and the ENGINE DOES NOT SUPPLY IT (db_news
//             stores category, not impact) — the dot falls back to neutral.
//             Never synthesise one: a colour-coded severity nothing measured is
//             the fabrication class P8 wave 1 removed.
//             No default feed — pass real news rows (empty renders quiet).
//   label   — left chip text (default "NEWS")
//   meta    — right-side source tag (default "REGIME FEED · finnhub + bwe")
//   pollMs  — refetch cadence (default 4000)
// ─────────────────────────────────────────────────────────────────────────
const NewsTickerBar = React.memo(function NewsTickerBar({
  news, label = 'NEWS', meta = 'REGIME FEED · finnhub + bwe', pollMs = 4000,
  pxPerSec = 52,
}) {
  const sortFeed = () => {
    // P8 wave 1: the never-defined MOCK_REGIME fallback is gone — no prop,
    // no feed (callers pass real news).
    const feed = news || [];
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

  /* CONSTANT SPEED, not constant duration.
     The keyframe translates -100% of the RUN's own width, so a fixed duration
     makes the scroll rate depend on how much news there is: the reference's
     46s over its ~8 mock items is ~52 px/s, but the same 46s over a 40-item
     live feed is roughly five times faster — unreadable, which is exactly what
     the operator hit. Measure the run and derive the duration instead, so the
     text moves at `pxPerSec` no matter how many items arrive.
     The CSS keeps 46s as the fallback for the frame before measurement (and if
     the ref never resolves); prefers-reduced-motion still wins outright,
     because it drops `animation` entirely and an inline duration cannot revive
     a missing animation-name. */
  const runRef = React.useRef(null);
  const [runSec, setRunSec] = React.useState(null);
  React.useLayoutEffect(() => {
    const el = runRef.current;
    if (!el) return;
    const w = el.scrollWidth;
    if (w > 0) setRunSec(Math.max(8, Math.round(w / pxPerSec)));
  }, [items, pxPerSec]);
  const runStyle = runSec ? { animationDuration: runSec + 's' } : undefined;

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
        <span ref={runRef} className="qe-newsticker-run" style={runStyle}>{runItems('a')}</span>
        <span className="qe-newsticker-run" style={runStyle} aria-hidden="true">{runItems('b')}</span>
      </div>
      {meta && <span className="qe-newsticker-meta">{meta}</span>}
    </div>
  );
});

// ─────────────────────────────────────────────────────────────────
// Switch — boolean toggle. The canonical on/off control (Sound, DND,
// auto-refresh, etc.). Distinct from LockButton (a button) and PeriodSelector.
// ─────────────────────────────────────────────────────────────────
// `disabled` (added 2026-07-25, Meridian audit shell-chrome-2) is ADDITIVE and
// defaults false, so every existing call site is unchanged. Use it for a control
// whose capability is deliberately not shipped yet: a switch that renders live
// but cannot act is a misrepresentation, and hiding it loses the signal that the
// feature is planned. Disabled swallows onChange — it never silently no-ops
// through the caller's handler.
const Switch = ({checked=false, onChange, label=null, title=null, accent='var(--qe-sub)', disabled=false}) => (
  <div onClick={disabled ? undefined : onChange} title={title}
    style={{display:'flex', alignItems:'center', gap:7,
            cursor: disabled?'not-allowed':'pointer', opacity: disabled?0.45:1}}>
    <span style={{width:26, height:14, background: checked&&!disabled?accent:'var(--qe-faint)', position:'relative', flexShrink:0, transition:'background .12s'}}>
      <span style={{position:'absolute', top:2, left: checked&&!disabled?14:2, width:10, height:10, background:'var(--qe-bg)', transition:'left .12s'}}/>
    </span>
    {/* deliberately NOT line-through: that is Chip's `muted` idiom and reads as
        "the user silenced this", not "not shipped yet". Dimming alone + the
        not-allowed cursor + the title carry it. */}
    {label && <span style={{fontFamily:'var(--qe-ui)', fontSize:'0.6rem', fontWeight:600, color: checked&&!disabled?'var(--qe-text)':'var(--qe-muted)'}}>{label}</span>}
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
// `onDismiss` (additive, default null — no visual change for existing
// callers): an advisory banner the operator may wave away renders a slim ✕
// after the action. Enforcement banners (halt/clock) deliberately pass none.
const Banner = ({tone='err', tag=null, title, detail=null, time=null, releaseIn=null, releaseLabel='RELEASES IN', actionLabel='ACKNOWLEDGE', onAction=null, onDismiss=null}) => {
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
      {onDismiss && <button className="qe-btn qe-btn-sm qe-btn-ghost" title="Dismiss" onClick={onDismiss}>✕</button>}
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
  Lbl, SecLbl, KV, Card, Stat, HeroNumber, Delta,
  StatusDot, Badge, RegimeBadge, PeriodSelector, Gauge, EmptyState,
  Tabs, Strip, FlashCell, LiveValue, LiveClock,
  asciiSpark, ASCII_SPARK,
  Pane, PaneHead, PaneFoot, ModelDialog, qeFootState, qeFootCause, _ptJson, _ptFetch, qePollDeadline, QE_READ_DEADLINE_MS, RefreshButton, ReloadGlyph, ReloadIconSVG, BrailleSquares, Spinner, useSpinFrame, RELOAD_MS, PaneErrorBoundary, DataList, FieldList, StepperInput, LockButton, NewsTickerBar,
  Switch, Chip, Banner, Toast, PageHeader,
});
