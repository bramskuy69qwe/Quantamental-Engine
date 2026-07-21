/* QE v2.5 — Dashboard "TILED WORKSPACE" — canonical layout
   Multi-pane grid using Pane / PaneFoot / DataList primitives, driven by
   GridStack.js for true tiling-window behaviour:
     · step / discrete resizing  — panes snap to 12-col × 12-row cells
     · grid snapping on resize    — edges lock to valid multiplier intervals
     · edge snapping              — drag/resize snaps to the cell lattice
     · tiling window management   — float:false ⇒ panes never overlap, they
                                    push / compact to fill space (no gaps)
     · gapless proportional       — margin:0 ⇒ neighbours sit perfectly flush
   The grid is isolated in a memoized <TiledGrid> that renders ONCE; all live
   tickers live in self-contained leaf components so React never re-renders
   the grid markup out from under GridStack. */

// Hero number that ticks. Splits cents into dim color (HeroNumber style)
// but the integer & fraction parts are individual LiveValue spans so only
// the digits morph — no card reflow.
const LiveHero = ({id, base, jitter=0.04, ccy='USDT', size='1.9rem', value=null}) => {
  const own = useLiveTicker(base, {jitter, intervalMs: 1200, decimals: 3, clamp:[base-2, base+2]});
  const v = value != null ? value : own;
  const [int, dec] = v.toFixed(2).split('.');
  return (
    <div className="qe-hero-val" style={{fontSize: size}}>
      <LiveValue id={`${id}.int`} value={+int} format={x=>x.toLocaleString()}/>
      <span className="qe-hero-cents">.<LiveValue id={`${id}.cents`} value={dec} format={x=>x}/></span>
      <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.36em', color:'var(--qe-sub)', fontWeight:600, marginLeft:8, verticalAlign:'middle'}}>{ccy}</span>
    </div>
  );
};

// LiveDelta — wraps the Delta visual but its number ticks. Tone follows sign.
// liveKey binds it to a shared QE_LIVE metric so every surface agrees.
const LiveDelta = ({id, base, jitter=0.05, size='var(--qe-fs-md)', liveKey=null, value=null, suffix=''}) => {
  const shared = window.useQeLive(liveKey || 'lat');
  const own = useLiveTicker(base, {jitter, intervalMs: 1500, decimals: 2});
  const v = value != null ? value : (liveKey ? shared : own);
  const dir = v > 0.001 ? 'up' : v < -0.001 ? 'dn' : 'flat';
  const col = dir==='up' ? 'var(--qe-green)' : dir==='dn' ? 'var(--qe-red)' : 'var(--qe-sub)';
  const sign = v > 0 ? '+' : '';
  return (
    <span className="qe-mono" style={{color: col, fontSize: size, fontWeight: 700, display:'inline-flex', alignItems:'center', gap: 4}}>
      {dir==='up' ? <span className="qe-tick qe-tick-up"/> : dir==='dn' ? <span className="qe-tick qe-tick-dn"/> : null}
      <LiveValue id={id} value={v} format={x=>sign+x.toFixed(2)+suffix} style={{color:col, fontWeight:700}}/>
    </span>
  );
};

// Live mini-log: prepend a new event every few seconds, shifting older ones down.
const useLiveLog = (initial, {intervalMs=4200}={}) => {
  const [rows, setRows] = React.useState(initial);
  React.useEffect(() => {
    const TAGS = [
      {tag:'WS',   tone:'info', tpl: () => `kline tick · last C=${(82+Math.random()).toFixed(2)} · age 1.2s`},
      {tag:'REG',  tone:'sub',  tpl: () => `regime score ${(0.5+Math.random()*0.3).toFixed(2)} · ×0.6`},
      {tag:'ENG',  tone:'ok',   tpl: () => `snapshot persisted · n=${1247 + Math.floor(Math.random()*40)}`},
      {tag:'RISK', tone:'sub',  tpl: () => `dd 30d 11.97% > 10% cap · ADVISORY · no auto-halt`},
      {tag:'OM',   tone:'sub',  tpl: () => `order ${504678000+Math.floor(Math.random()*999)} ack · maker`},
    ];
    const id = setInterval(() => {
      const pick = TAGS[Math.floor(Math.random()*TAGS.length)];
      const now = new Date(Date.now() + (window.QE_CLOCK_OFFSET || 0));
      const t = now.toISOString().slice(11,19);
      setRows(prev => [{t, tag:pick.tag, tone:pick.tone, msg:pick.tpl()}, ...prev].slice(0,12));
    }, intervalMs + Math.random()*1500);
    return () => clearInterval(id);
  }, []);
  return rows;
};

// ─────────────────────────────────────────────────────────────────────────
// GridItem lives in grid-workspace.jsx (shared). Below, TiledGrid composes
// the dashboard panes inside a shared <GridWorkspace>.
// ─────────────────────────────────────────────────────────────────────────

// PANE 1+2 (Equity) — unified: equity data on the LEFT, OHLC chart on the RIGHT.
// Extracted as a leaf so its period-selector + streaming tickers re-render here,
// never in TiledGrid.
// Position row cells — all derive from the shared per-symbol mark walk.
const PosMark = ({r}) => { const {mark} = window.useQePosMark(r); const d = (r.mark.split('.')[1]||'').length;
  return <LiveValue id={`pos.${r.sym}.mark`} value={mark} format={x=>x.toLocaleString(undefined,{minimumFractionDigits:d, maximumFractionDigits:d})} style={{color:'var(--qe-text)', fontWeight:700}}/>; };
const PosPnl = ({r}) => { const {pnl} = window.useQePosMark(r);
  return <LiveValue id={`pos.${r.sym}.pnl`} value={pnl} format={x=>(x>=0?'+':'')+x.toFixed(2)} style={{color: pnl>=0?'var(--qe-green)':'var(--qe-red)', fontWeight:700}}/>; };
const PosPct = ({r}) => { const {pct} = window.useQePosMark(r);
  return <LiveValue id={`pos.${r.sym}.pct`} value={pct} format={x=>(x>=0?'+':'')+x.toFixed(2)+'%'} style={{color: pct>=0?'var(--qe-green)':'var(--qe-red)', fontWeight:600}}/>; };
const PosUnrealSum = () => { const s = window.useQeUnrealSum();
  return <span style={{color: s>=0?'var(--qe-green)':'var(--qe-red)'}}>Σ unrealized {(s>=0?'+':'')}{s.toFixed(2)} USDT</span>; };
// MFE/MAE ratchet against the live PnL — an excursion extreme can never be
// inside the current PnL (impossible state otherwise).
const PosMfeMae = ({r}) => { const {pnl} = window.useQePosMark(r);
  const mfe = Math.max(r.mfe, pnl), mae = Math.min(r.mae, pnl);
  return <span style={{fontSize:'0.6rem'}}><span style={{color:'var(--qe-green)'}}>+{mfe.toFixed(2)}</span><span style={{color:'var(--qe-muted)'}}> / </span><span style={{color:'var(--qe-red)'}}>{mae.toFixed(2)}</span></span>; };
// Tape price for a symbol that also sits in the position book — reads the SAME
// shared mark walk, so the tape can never disagree with the blotter.
const TapeSharedPrice = ({w, decs}) => {
  const {mark} = window.useQePosMark(MOCK.positionsOpen.find(p => p.sym === w.sym));
  return <LiveValue id={`tape.${w.sym}`} value={mark}
    format={x => x.toLocaleString(undefined,{minimumFractionDigits:decs, maximumFractionDigits:decs})}
    style={{color:'var(--qe-text)', fontWeight:600}}/>;
};

const EquityStatsPane = () => {
  const pnlD = window.useQeLive('pnlD');
  const unreal = window.useQeUnrealSum();
  const total = +(82.20 * (1 + pnlD / 100)).toFixed(3);
  return (
  <Pane title="Equity" style={{height:'100%'}}
    right={<Badge tone="ok">LIVE</Badge>}
    foot={{tone:'info', id:1841, msg:`snapshot persisted · eq=${total.toFixed(2)} · n=1247`, ms:8}}>
    <div style={{display:'flex', flexDirection:'column', gap:8}}>
      <div>
        <Lbl>Total</Lbl>
        <LiveHero id="acct.eq" base={82.20} value={total} ccy={MOCK.account.ccy} size="1.9rem"/>
      </div>
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
        <div><Lbl>Daily</Lbl><LiveDelta id="eq.daily" base={-0.00} liveKey="pnlD" suffix="%"/></div>
        <div><Lbl>Weekly</Lbl><LiveDelta id="eq.weekly" base={-0.02} liveKey="pnlW" suffix="%"/></div>
        <div><Lbl>April</Lbl><LiveDelta id="eq.april" base={-11.18} liveKey="pnlM"/></div>
        <div><Lbl>Unrealized</Lbl><LiveValue id="eq.unreal" value={unreal} format={x=>(x>=0?'+':'')+x.toFixed(2)} style={{color: unreal>=0?'var(--qe-green)':'var(--qe-red)', fontWeight:700, fontSize:'var(--qe-fs-md)'}}/></div>
      </div>
      <div className="qe-divider-h"/>
      <FieldList cols={2} dense rows={MOCK.equityBlocks.map(b => ({label:b.label, value:
        b.label==='Unrealized'   ? (unreal>=0?'+':'')+unreal.toFixed(2)
        : b.label==='Min Eq (BOD)' ? Math.min(82.20, total).toFixed(2)
        : b.label==='Max Eq (BOD)' ? Math.max(82.20, total).toFixed(2)
        : b.value}))}/>
    </div>
  </Pane>
  );
};

const EquityCurvePane = () => {
  const [tf, setTf] = React.useState('1h');
  const wsAge = useLiveTicker(1.2, {jitter:0.4, intervalMs:900, decimals:1, clamp:[0.1,3.5]});
  // session OHLC derives from the same shared equity (open 82.20 · C = live eq)
  const pnlD = window.useQeLive('pnlD');
  const total = +(82.20 * (1 + pnlD / 100)).toFixed(2);
  const hRef = React.useRef(83.41); if (total > hRef.current) hRef.current = total;
  const lRef = React.useRef(81.62); if (total < lRef.current) lRef.current = total;
  return (
    <Pane title="Equity Curve" hot tag="OHLC" style={{height:'100%'}}
      right={<PeriodSelector options={[['1h','1H'],['4h','4H'],['1d','1D'],['1w','1W']]} value={tf} onChange={setTf}/>}
      foot={{tone:'info', id:1842, msg:`equity_ohlc refresh · last C=$${total.toFixed(2)} · cash flow $0.00 · n=1247`, ms:12}}
      bodyStyle={{padding:6}}>
      <div style={{height:'100%', display:'flex', flexDirection:'column'}}>
        <div className="qe-mono" style={{fontSize:'0.62rem', display:'flex', gap:14, flexWrap:'wrap', padding:'2px 4px', alignItems:'baseline'}}>
          <span><span style={{color:'var(--qe-muted)'}}>O</span> <span style={{color:'var(--qe-text)'}}>$82.20</span></span>
          <span><span style={{color:'var(--qe-muted)'}}>H</span> <LiveValue id="ohlc.h" value={hRef.current} format={x=>'$'+x.toFixed(2)} style={{color:'var(--qe-green)', fontWeight:700}}/></span>
          <span><span style={{color:'var(--qe-muted)'}}>L</span> <LiveValue id="ohlc.l" value={lRef.current} format={x=>'$'+x.toFixed(2)} style={{color:'var(--qe-red)', fontWeight:700}}/></span>
          <span><span style={{color:'var(--qe-muted)'}}>C</span> <LiveValue id="ohlc.c" value={total} format={x=>'$'+x.toFixed(2)} style={{color:'var(--qe-text)', fontWeight:700}}/></span>
          <span><span style={{color:'var(--qe-muted)'}}>Chg</span> <LiveDelta id="ohlc.chg" value={+(total - 82.20).toFixed(2)}/></span>
          <span><span style={{color:'var(--qe-muted)'}}>Cash Flow</span> <span style={{color:'var(--qe-blue)'}}>+$0.00</span></span>
          <span style={{marginLeft:'auto', display:'inline-flex', alignItems:'center', gap:4}}>
            <span className="qe-live" style={{color:'var(--qe-cyan)'}}>streaming</span>
            <LiveValue id="ohlc.age" value={wsAge} format={x=>x.toFixed(1)+'s'} style={{color:'var(--qe-muted)', fontSize:'0.56rem'}}/>
          </span>
        </div>
        <div style={{flex:1, minHeight:0}}>
          <CandlestickChart data={MOCK.ohlc}/>
        </div>
      </div>
    </Pane>
  );
};

// PANE 8 (Engine Log) body — owns its own prepending log state.
const EngineLogBody = () => {
  const liveLogs = useLiveLog(MOCK.logs);
  return (
    <div style={{fontFamily:'var(--qe-mono)', fontSize:'0.62rem', lineHeight:1.5}}>
      {liveLogs.map((l,i) => (
        <div key={`${l.t}-${i}`} style={{display:'grid', gridTemplateColumns:'56px 38px 1fr', gap:6, opacity: i===0 ? 1 : Math.max(0.45, 1 - i*0.06), animation: i===0 ? 'qe-fade-in 0.4s ease' : 'none'}}>
          <span style={{color:'var(--qe-muted)'}}>{l.t}</span>
          <span style={{color: l.tone==='ok'?'var(--qe-green)':l.tone==='info'?'var(--qe-cyan)':'var(--qe-sub)'}}>[{l.tag}]</span>
          <span style={{color:'var(--qe-text-dim)'}}>{l.msg}</span>
        </div>
      ))}
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// TiledGrid — the dashboard workspace, composed inside the shared
// <GridWorkspace>. Memoized with NO props so it renders exactly once; all live
// tickers live in leaf tiles, so GridStack owns the DOM uninterrupted.
// ─────────────────────────────────────────────────────────────────────────
const TiledGrid = React.memo(function TiledGrid() {
  return (
    <GridWorkspace persistId="dashboard">

        {/* ── PANE 1: Equity stats ────────────────────────────────── */}
        <GridItem x={0} y={0} w={8} h={8} minW={6} minH={6}>
          <EquityStatsPane/>
        </GridItem>

        {/* ── PANE 2: Equity curve chart ──────────────────────────── */}
        <GridItem x={8} y={0} w={16} h={8} minW={8} minH={6}>
          <EquityCurvePane/>
        </GridItem>

        {/* ── PANE 3: Risk gauges ─────────────────────────────────── */}
        <GridItem x={0} y={8} w={6} h={8} minW={4} minH={6}>
          <Pane title="Risk Monitor" style={{height:'100%'}}
            right={<Badge tone="info">ADVISORY</Badge>}
            foot={{tone:'warn', id:1843, msg:'net exp 2.93× in cap · dd 11.97% > 10.0% limit — ADVISORY, no auto-halt', ms:3}}>
            <div style={{display:'flex', flexDirection:'column', gap:14}}>
              <Gauge label="Net Exposure" value={MOCK.risk.exposure.v} max={MOCK.risk.exposure.max} current={MOCK.risk.exposure.current} maxLabel="5.0× cap"/>
              <Gauge label="Drawdown 30d" value={Math.min(MOCK.risk.drawdown.v, MOCK.risk.drawdown.max)} max={MOCK.risk.drawdown.max} current={MOCK.risk.drawdown.current} maxLabel="10.0% limit" ticks={[5,8]}/>
              <Gauge label="Weekly Loss"  value={MOCK.risk.weeklyDD.v} max={MOCK.risk.weeklyDD.max} current={MOCK.risk.weeklyDD.current} maxLabel="5.0%"/>
              <Gauge label="Positions"    value={MOCK.risk.positions.open} max={MOCK.risk.positions.max} current={`${MOCK.risk.positions.open}/${MOCK.risk.positions.max}`} maxLabel="capacity"/>
              <div className="qe-divider-h"/>
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
                <div><Lbl>DD STATE</Lbl><Badge tone="warn">ADVISORY</Badge></div>
                <div><Lbl>WEEKLY</Lbl><Badge tone="ok">OK</Badge></div>
                <div><Lbl>SECTOR</Lbl><Badge tone="ok">IN CAP</Badge></div>
                <div><Lbl>FUNDING</Lbl><Badge tone="mute">+0.02/8h</Badge></div>
              </div>
            </div>
          </Pane>
        </GridItem>

        {/* ── PANE 4: Open positions ──────────────────────────────── */}
        <GridItem x={6} y={8} w={12} h={8} minW={8} minH={6}>
          <Pane title="Open Positions" count={MOCK.positionsOpen.length} style={{height:'100%'}}
            right={<button className="qe-btn qe-btn-sm" title="Size a new position in Pre-Trade" onClick={()=>window.qeNav && window.qeNav('Pre-Trade')}>+ Calc</button>}
            foot={{tone:'info', id:1844, msg:'reconciler synced · 5 positions · 4 working orders', ms:42}}
            bodyStyle={{padding:0, display:'flex', flexDirection:'column'}}>
            <DataList
              selKey="sym"
              columns={[
                {key:'sym',   label:'SYM',   render:r=><span style={{color:'var(--qe-cyan)',fontWeight:700}}>{r.sym}</span>},
                {key:'dir',   label:'SIDE',  render:r=><Badge tone={r.dir==='L'?'ok':'err'}>{r.dir==='L'?'LONG':'SHORT'}</Badge>},
                {key:'size',  label:'SIZE',  align:'right'},
                {key:'entry', label:'ENTRY', align:'right', cell:'dim'},
                {key:'mark',  label:'MARK',  align:'right', render:r=><PosMark r={r}/>},
                {key:'pnl',   label:'PnL',   align:'right', render:r=><PosPnl r={r}/>},
                {key:'pct',   label:'%',     align:'right', render:r=><PosPct r={r}/>},
                {key:'tpsl',  label:'TP / SL', align:'right', render:r=><span style={{fontSize:'0.6rem'}}><span style={{color:'var(--qe-green)'}}>{r.tp}</span><span style={{color:'var(--qe-muted)'}}> / </span><span style={{color:'var(--qe-red)'}}>{r.sl}</span></span>},
                {key:'mm',    label:'MFE/MAE', align:'right', render:r=><PosMfeMae r={r}/>},
                {key:'age',   label:'AGE',   align:'right', cell:'dim'},
              ]}
              rows={MOCK.positionsOpen}
              emptyMsg="No open positions"
              summary={<>
                <span>{MOCK.positionsOpen.length} / 20 positions · 3 long · 2 short</span>
                <PosUnrealSum/>
              </>}
            />
          </Pane>
        </GridItem>

        {/* ── PANE 5: Macro signals ───────────────────────────────── */}
        <GridItem x={18} y={8} w={6} h={8} minW={4} minH={6}>
          <Pane title="Macro Signals" count={MOCK.signals.length} style={{height:'100%'}}
            right={<PeriodSelector options={[['1d','D'],['1w','W'],['1m','M']]} value="1d" onChange={()=>{}}/>}
            foot={{tone:'info', id:1845, msg:'fred refresh · 10Y +2bp · next pull 4m 12s', ms:118}}>
            <div style={{display:'flex', flexDirection:'column', gap:6}}>
              {MOCK.signals.map((s,i) => {
                const nv = parseFloat(s.v.replace(/[^0-9.\-]/g,''));
                const isNum = !isNaN(nv);
                return (
                  <div key={s.key} style={{display:'grid', gridTemplateColumns:'68px 1fr 56px 50px', alignItems:'center', gap:6, padding:'3px 0', borderBottom:'1px dotted var(--qe-faint)'}}>
                    <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.6rem', color:'var(--qe-sub)', letterSpacing:'0.04em'}}>{s.key}</span>
                    <Sparkline data={mockSpark(28, 0, 1)} color={s.tone==='up'?'var(--qe-green)':'var(--qe-red)'} height={14}/>
                    {isNum
                      ? <LiveNumber id={`sig.${s.key}`} base={nv} jitter={Math.abs(nv)*0.002 + 0.01} intervalMs={1800+i*70} decimals={(s.v.split('.')[1]||'').replace(/[^\d]/g,'').length || 2}
                          format={x => s.v.startsWith('$') ? '$'+x.toFixed(2) : s.v.endsWith('%') ? x.toFixed(2)+'%' : x.toFixed(2)}
                          style={{fontSize:'0.68rem', fontWeight:700, textAlign:'right', display:'block'}}/>
                      : <span className="qe-mono" style={{fontSize:'0.68rem', fontWeight:700, textAlign:'right'}}>{s.v}</span>}
                    <span className="qe-mono" style={{fontSize:'0.56rem', textAlign:'right', color: s.tone==='up'?'var(--qe-green)':'var(--qe-red)'}}>{s.d}</span>
                  </div>
                );
              })}
            </div>
          </Pane>
        </GridItem>

        {/* ── PANE 6: April summary + bars ────────────────────────── */}
        <GridItem x={0} y={16} w={12} h={8} minW={8} minH={6}>
          <Pane title="Monthly Analytics Preview" style={{height:'100%'}}
            right={<PeriodSelector options={[['mtd','MTD'],['week','WK'],['qtr','QTR'],['ytd','YTD']]} value="mtd" onChange={()=>{}}/>}
            foot={{tone:'warn', id:1846, msg:'period pnl negative · -11.18 · 31 trades · winrate 38.7%', ms:6}}
            bodyStyle={{padding:0}}>
            <div style={{display:'grid', gridTemplateColumns:'minmax(190px,200px) 1px 1fr', gap:0, height:'100%'}}>
              <div style={{padding:'7px 12px 7px 8px', minWidth:0}}>
                <FieldList rows={[
                  {label:'Period PnL',  value:<>{MOCK.april.pnl>=0?'+':''}{MOCK.april.pnl} <span style={{color:'var(--qe-muted)', fontSize:'0.6rem'}}>({MOCK.april.pnlPct>=0?'+':''}{MOCK.april.pnlPct}%)</span></>, color: MOCK.april.pnl<0?'red':'green'},
                  {label:'Trades',      value:<>{MOCK.april.trades} <span style={{color:'var(--qe-green)', fontSize:'0.62rem'}}>·{MOCK.april.wins}W</span> <span style={{color:'var(--qe-red)', fontSize:'0.62rem'}}>·{MOCK.april.losses}L</span></>},
                  {label:'Winrate / R', value:`${MOCK.april.winrate}% / ${MOCK.april.avgRR}R`},
                  {label:'Max DD',      value:`-${MOCK.april.maxDD}%`, color:'red'},
                ]}/>
              </div>
              <div style={{background:'var(--qe-line)'}}/>
              <div style={{padding:'7px 8px 7px 12px', display:'flex', flexDirection:'column', gap:6, minWidth:0}}>
                <Lbl>Daily PnL · Apr 1 — 30</Lbl>
                <div style={{flex:1, minHeight:0}}>
                  <BarChart data={Array.from({length:30}, () => +(((Math.random()-0.55)*2)).toFixed(2))}
                    categories={Array.from({length:30}, (_,i)=>i+1)}/>
                </div>
              </div>
            </div>
          </Pane>
        </GridItem>

        {/* ── PANE 7: Active params ───────────────────────────────── */}
        <GridItem x={12} y={16} w={6} h={8} minW={4} minH={6}>
          <Pane title="Active Parameters" tag="VIEW" style={{height:'100%'}}
            right={<button className="qe-btn qe-btn-sm qe-btn-ghost" title="Edit risk parameters in Configuration" onClick={()=>window.qeNav && window.qeNav('Config')}>Edit</button>}
            foot={{tone:'sub', id:1847, msg:'preset SWING · dd window 30d · mode advisory', ms:1}}>
            <div style={{display:'flex', flexDirection:'column', gap:6}}>
              <FieldList rows={MOCK.params.map(p => ({
                label: p.label, value: p.value, color: p.tone==='cyan' ? 'cyan' : undefined,
              }))}/>
              <div className="qe-divider-h"/>
              <div style={{display:'flex', gap:6, flexWrap:'wrap'}}>
                <Badge tone="info">PRESET: SWING</Badge>
                <Badge tone="mute">WINDOW: 30d</Badge>
              </div>
            </div>
          </Pane>
        </GridItem>

        {/* ── PANE 8: Engine log ──────────────────────────────────── */}
        <GridItem x={18} y={16} w={6} h={8} minW={4} minH={6}>
          <Pane title="Engine Log" tag="SSE" style={{height:'100%'}}
            right={<StatusDot tone="ok" label="LIVE"/>}
            foot={{tone:'ok', id:1848, msg:'WS · market stream connected (2 streams)', ms:0}}
            bodyStyle={{padding:'4px 6px', fontFamily:'var(--qe-mono)'}}>
            <EngineLogBody/>
          </Pane>
        </GridItem>

      </GridWorkspace>
  );
});

// ─────────────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────────
// NewsTickerBar lives in primitives.jsx (shared). The dashboard renders it as
// a footer line; with no props it pulls from the Regime feed (MOCK_REGIME.news).
// ─────────────────────────────────────────────────────────────────────────

const DashTiled = () => {
  const lat     = window.useQeLive('lat');
  const eventsK = window.useQeLive('eventsK');

  return (
    <div className="qe-scope" data-screen-label="01 Dashboard" style={{
      width:'100%', height:'100%', background:'var(--qe-bg)',
      display:'flex', flexDirection:'column', overflow:'hidden',
    }}>
      <TopNavStd page="Dashboard" variant="line" dense/>

      <PageHeader title="Dashboard" subtitle="live positions · watchlist · equity · risk · open orders">
        <StatusDot tone="ok" label="WS" value={<LiveValue id="dash.hdr.lat" value={lat} format={x=>Math.round(x)+'ms'}/>}/>
        <StatusDot tone="info" label="REGIME" value="CHOP ×0.6"/>
        <StatusDot tone="ok" label="GATE" value="READY"/>
      </PageHeader>

      {/* Ticker tape — horizontal-scroll watchlist strip */}
      <div style={{
        display:'flex', alignItems:'center', gap:0,
        background:'var(--qe-bg)', borderBottom:'1px solid var(--qe-line)',
        padding:'0 4px', height:22, flexShrink:0,
        fontFamily:'var(--qe-mono)', fontSize:'0.62rem',
        overflow:'hidden', whiteSpace:'nowrap',
      }}>
        {MOCK_WATCHLIST.map((w,i) => {
          const base = parseFloat(w.last);
          const jit  = base * 0.0005;
          const decs = (w.last.split('.')[1] || '').length;
          return (
            <span key={w.sym} style={{display:'inline-flex', alignItems:'baseline', gap:5, padding:'0 9px', borderRight: i<MOCK_WATCHLIST.length-1 ? '1px solid var(--qe-faint)' : 'none'}}>
              <span style={{color:'var(--qe-cyan)', fontWeight:700, letterSpacing:'0.02em'}}>{w.sym.replace('USDT','')}</span>
              {MOCK.positionsOpen.some(p => p.sym === w.sym)
                ? <TapeSharedPrice w={w} decs={decs}/>
                : <LiveNumber id={`tape.${w.sym}`} base={base} jitter={jit} intervalMs={1100+i*120} decimals={decs}
                    format={x => x.toLocaleString(undefined,{minimumFractionDigits:decs, maximumFractionDigits:decs})}
                    style={{color:'var(--qe-text)', fontWeight:600}}/>}
              <LivePct id={`tape.${w.sym}.d`} base={w.d} jitter={0.04} intervalMs={1500+i*90}
                style={{fontSize:'0.56rem', fontWeight:600}}/>
              <span style={{color:'var(--qe-muted)', fontSize:'0.52rem'}}>{w.vol}</span>
            </span>
          );
        })}
      </div>

      {/* Tiling workspace — GridStack-driven, isolated from re-renders */}
      <TiledGrid/>

      {/* News ticker footer — live headlines from the Regime news feed */}
      <NewsTickerBar/>

      <StatusFooter/>
    </div>
  );
};

Object.assign(window, { DashTiled });
