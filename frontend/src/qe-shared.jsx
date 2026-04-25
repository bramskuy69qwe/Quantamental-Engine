import React from 'react';

// Design tokens
export const QEC = {
  bg:        '#07080f',
  card:      '#0c1118',
  panel:     '#101826',
  hover:     '#141f2e',
  border:    '#18253a',
  borderFoc: '#2a4568',
  text:      '#e8f2ff',
  sub:       '#96b4d0',
  muted:     '#526a88',
  blue:      '#3c8ff5',
  green:     '#00c855',
  red:       '#e83535',
  amber:     '#e89020',
  cyan:      '#00b4d8',
  purple:    '#9b6ef5',
};

export const REGIME_META = {
  risk_on_trending:   { bg:'#0a2018', text:'#00c855', label:'Trending',  short:'TREND' },
  risk_on_choppy:     { bg:'#082028', text:'#00b4d8', label:'Choppy',    short:'CHOP'  },
  neutral:            { bg:'#101826', text:'#7090b0', label:'Neutral',   short:'NEUT'  },
  risk_off_defensive: { bg:'#251500', text:'#e89020', label:'Defensive', short:'DEF'   },
  risk_off_panic:     { bg:'#250808', text:'#e83535', label:'Panic',     short:'PANIC' },
};

// ── Atoms ────────────────────────────────────────────────────────────────────

export const Lbl = ({children, style={}}) => (
  <div style={{fontSize:'0.62rem',fontWeight:600,letterSpacing:'0.08em',textTransform:'uppercase',
    color:QEC.sub,marginBottom:'2px',...style}}>
    {children}
  </div>
);

export const Mono = ({children, color, size='0.95rem', style={}}) => (
  <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:size,fontWeight:700,
    color:color||QEC.text,lineHeight:1.1,...style}}>
    {children}
  </div>
);

export const Stat = ({label,value,color,size,sub}) => (
  <div>
    <Lbl>{label}</Lbl>
    <Mono color={color} size={size||'0.92rem'}>{value}</Mono>
    {sub && <div style={{fontSize:'0.6rem',color:QEC.sub,marginTop:'1px',fontFamily:'monospace'}}>{sub}</div>}
  </div>
);

export const Card = ({children, style={}, p='10px 12px'}) => (
  <div style={{background:QEC.card,border:`1px solid ${QEC.border}`,borderRadius:'5px',padding:p,...style}}>
    {children}
  </div>
);

export const SecLabel = ({children, style={}}) => (
  <div style={{fontSize:'0.6rem',fontWeight:700,letterSpacing:'0.1em',textTransform:'uppercase',
    color:QEC.sub,marginBottom:'7px',...style}}>
    {children}
  </div>
);

export const Badge = ({children, color=QEC.text, bg=QEC.muted, style={}}) => (
  <span style={{display:'inline-flex',alignItems:'center',padding:'2px 7px',borderRadius:'3px',
    fontSize:'0.62rem',fontWeight:700,letterSpacing:'0.05em',background:bg,color,...style}}>
    {children}
  </span>
);

export const OkBadge = ({ok, label}) => (
  <Badge color={ok ? QEC.green : QEC.red} bg={ok ? '#071a10' : '#200808'}>
    {label || (ok ? 'OK' : 'LIMIT')}
  </Badge>
);

export const Divider = ({style={}}) => (
  <div style={{height:'1px',background:QEC.border,margin:'8px 0',...style}}/>
);

export const Inp = ({label, ...props}) => (
  <div>
    {label && <Lbl>{label}</Lbl>}
    <input {...props} style={{
      background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text,
      borderRadius:'4px', padding:'5px 8px', width:'100%', height:'30px',
      fontFamily:"'JetBrains Mono',monospace", fontSize:'0.8rem',
      outline:'none', boxSizing:'border-box',
      ...props.style,
    }}
    onFocus={e => e.target.style.borderColor = QEC.borderFoc}
    onBlur={e => e.target.style.borderColor = QEC.border}
    />
  </div>
);

export const Sel = ({label, children, ...props}) => (
  <div>
    {label && <Lbl>{label}</Lbl>}
    <select {...props} style={{
      background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text,
      borderRadius:'4px', padding:'4px 6px', width:'100%', height:'30px',
      fontSize:'0.75rem', outline:'none', cursor:'pointer',
      ...props.style,
    }}>
      {children}
    </select>
  </div>
);

export const Btn = ({children, variant='secondary', size='md', onClick, style={}, disabled}) => {
  const variants = {
    primary:   {bg:QEC.blue,     color:'#fff',     hover:'#4a9eff'},
    secondary: {bg:QEC.panel,    color:QEC.text,   hover:QEC.hover},
    danger:    {bg:'#3a0808',    color:QEC.red,    hover:'#4a1010'},
    success:   {bg:'#072018',    color:QEC.green,  hover:'#0a2820'},
    ghost:     {bg:'transparent',color:QEC.sub,    hover:QEC.hover},
    amber:     {bg:'#251500',    color:QEC.amber,  hover:'#302000'},
  };
  const v = variants[variant] || variants.secondary;
  const sz = {sm:{padding:'3px 8px',fontSize:'0.65rem',height:'24px'}, md:{padding:'5px 12px',fontSize:'0.72rem',height:'28px'}, lg:{padding:'7px 16px',fontSize:'0.78rem',height:'34px'}}[size]||{};
  const [hov, setHov] = React.useState(false);
  return (
    <button onClick={onClick} disabled={disabled}
      onMouseOver={()=>setHov(true)} onMouseOut={()=>setHov(false)}
      style={{
        background: hov ? v.hover : v.bg,
        color: disabled ? QEC.sub : v.color,
        border: `1px solid ${QEC.border}`,
        borderRadius:'4px', cursor: disabled ? 'not-allowed' : 'pointer',
        fontFamily:"'Space Grotesk',sans-serif", fontWeight:600,
        transition:'all 0.1s', letterSpacing:'0.03em',
        opacity: disabled ? 0.5 : 1,
        ...sz, ...style,
      }}>
      {children}
    </button>
  );
};

export const Sparkline = ({data=[], color=QEC.green, height=60, showFill=true, gridLines=4}) => {
  if (!data.length) return null;
  const vals = data.map(d => typeof d === 'number' ? d : d.v);
  const min = Math.min(...vals), max = Math.max(...vals);
  const rng = (max - min) || 0.1;
  const W = 1000, H = height;
  const toX = i => (i / (vals.length - 1)) * W;
  const toY = v => H - ((v - min) / rng) * (H - 4) - 2;
  const pts = vals.map((v,i) => `${toX(i)},${toY(v)}`).join(' ');
  const fillPts = `0,${H} ${pts} ${W},${H}`;
  const grids = Array.from({length:gridLines+1},(_,i) => {
    const y = (i / gridLines) * H;
    const val = max - (i / gridLines) * rng;
    return {y, val};
  });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{width:'100%',height:`${height}px`,display:'block'}}>
      {grids.map((g,i) => (
        <line key={i} x1="0" y1={g.y} x2={W} y2={g.y} stroke={QEC.border} strokeWidth="0.5"/>
      ))}
      {showFill && <polygon points={fillPts} fill={`${color}18`}/>}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>
    </svg>
  );
};

export function mockEquityData(n=60, base=82.2, vol=3) {
  let v = base, data = [];
  for (let i = 0; i < n; i++) {
    v += (Math.random() - 0.52) * vol * 0.3;
    v = Math.max(base * 0.85, Math.min(base * 1.15, v));
    data.push(parseFloat(v.toFixed(2)));
  }
  return data;
}

export function fmtPnl(v) {
  if (v === null || v === undefined) return '—';
  const n = parseFloat(v);
  const s = n >= 0 ? '+' : '';
  return s + n.toFixed(2);
}

export function pnlColor(v) {
  if (v === null || v === undefined) return QEC.text;
  return parseFloat(v) >= 0 ? QEC.green : QEC.red;
}

// ── TabBar — 4 style variants ────────────────────────────────────────────────
export const TabBar = ({tabs, active, onChange, variant='line', style={}}) => {
  const [hov, setHov] = React.useState(null);

  const renderTab = (id, label) => {
    const isActive = active === id;
    const isHov    = hov === id;

    if (variant === 'line') return (
      <button key={id} onClick={()=>onChange(id)}
        onMouseOver={()=>setHov(id)} onMouseOut={()=>setHov(null)}
        style={{
          padding:'7px 13px', border:'none', cursor:'pointer', background:'transparent',
          color: isActive ? QEC.text : isHov ? QEC.sub : QEC.muted,
          fontSize:'0.72rem', fontWeight: isActive ? 700 : 500,
          fontFamily:"'Space Grotesk',sans-serif", whiteSpace:'nowrap',
          borderBottom: `2px solid ${isActive ? QEC.blue : 'transparent'}`,
          transition:'color 0.1s, border-color 0.1s',
          marginBottom:'-1px',
        }}>{label}</button>
    );

    if (variant === 'filled') return (
      <button key={id} onClick={()=>onChange(id)}
        onMouseOver={()=>setHov(id)} onMouseOut={()=>setHov(null)}
        style={{
          padding:'5px 13px', cursor:'pointer', whiteSpace:'nowrap',
          background: isActive ? QEC.card : isHov ? QEC.hover : 'transparent',
          color: isActive ? QEC.text : QEC.sub,
          fontSize:'0.72rem', fontWeight: isActive ? 700 : 500,
          fontFamily:"'Space Grotesk',sans-serif",
          border: `1px solid ${isActive ? QEC.border : 'transparent'}`,
          borderBottom: isActive ? `1px solid ${QEC.card}` : `1px solid transparent`,
          borderRadius:'4px 4px 0 0',
          transition:'all 0.1s', marginBottom:'-1px',
        }}>{label}</button>
    );

    if (variant === 'pill') return (
      <button key={id} onClick={()=>onChange(id)}
        onMouseOver={()=>setHov(id)} onMouseOut={()=>setHov(null)}
        style={{
          padding:'4px 12px', cursor:'pointer', whiteSpace:'nowrap',
          background: isActive ? QEC.blue : isHov ? QEC.hover : 'transparent',
          color: isActive ? '#fff' : isHov ? QEC.text : QEC.sub,
          fontSize:'0.7rem', fontWeight: isActive ? 700 : 500,
          fontFamily:"'Space Grotesk',sans-serif",
          border: `1px solid ${isActive ? QEC.blue : QEC.border}`,
          borderRadius:'99px', transition:'all 0.12s',
        }}>{label}</button>
    );

    if (variant === 'bracket') return (
      <button key={id} onClick={()=>onChange(id)}
        onMouseOver={()=>setHov(id)} onMouseOut={()=>setHov(null)}
        style={{
          padding:'5px 10px', cursor:'pointer', border:'none', background:'transparent',
          color: isActive ? QEC.blue : isHov ? QEC.text : QEC.sub,
          fontSize:'0.7rem', fontWeight: isActive ? 700 : 500,
          fontFamily:"'JetBrains Mono',monospace", whiteSpace:'nowrap',
          transition:'color 0.1s',
          letterSpacing: isActive ? '0.02em' : '0',
        }}>
        {isActive ? <span><span style={{color:QEC.muted,marginRight:'3px'}}>[</span>{label}<span style={{color:QEC.muted,marginLeft:'3px'}}>]</span></span> : label}
      </button>
    );
  };

  const wrapStyle = {
    display:'flex', gap: variant==='pill' ? '4px' : '0',
    alignItems:'center', flexWrap:'nowrap', overflowX:'auto', scrollbarWidth:'none',
    ...style,
  };

  const needsBorderBottom = variant === 'line' || variant === 'filled';

  return (
    <div style={{
      ...wrapStyle,
      ...(needsBorderBottom ? {borderBottom:`1px solid ${QEC.border}`} : {}),
    }}>
      {tabs.map(([id, label]) => renderTab(id, label))}
    </div>
  );
};
