/* QE v2.5 — Application shell & router
   Turns the standalone page components into one navigable, wired website.
   Nav clicks (TopNavStd → window.qeNav) switch the active page; the active
   page is persisted to the URL hash + localStorage. The whole app lives inside
   a single NotificationProvider so the bell, banner and toasts work everywhere. */

/* ── LiveValueDemo — wraps a LiveValue with a setInterval ticker so the
   Primitives spec card visibly shows live updates. Demo-only. ───────────── */
const LiveValueDemo = ({id, base, jitter=2, fmt, style}) => {
  const [v, setV] = React.useState(base);
  React.useEffect(() => {
    const t = setInterval(() => {
      setV(prev => +(prev + (Math.random()-0.5) * jitter).toFixed(4));
    }, 900 + Math.random()*700);
    return () => clearInterval(t);
  }, []);
  return <LiveValue id={id} value={v} format={fmt} style={style}/>;
};

/* ── Primitives page — the design-system reference, a dedicated dev page ─── */
const PrimitivesPage = () => (
  <div className="qe-scope" data-screen-label="00 Primitives" style={{
    width:'100%', height:'100%', background:'var(--qe-bg)', display:'flex', flexDirection:'column', overflow:'hidden',
  }}>
    <TopNavStd page="Primitives" variant="line" dense/>
    <PageHeader title="Primitives" subtitle="standardized component vocabulary · every page is composed from these">
      <Badge tone="warn">DEV · NOT IN PRODUCTION NAV</Badge>
    </PageHeader>
    <div style={{flex:1, minHeight:0, overflow:'auto', padding:14}}>
      <div style={{display:'grid', gridTemplateColumns:'minmax(0,1fr) minmax(0,1fr)', gap:14}}>

        {/* Tokens */}
        <Card pad>
          <SecLbl rule>Color tokens · neon on black</SecLbl>
          <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:8}}>
            {[
              ['--qe-green','GREEN','long · win · ok'],
              ['--qe-red','RED','short · loss · halt'],
              ['--qe-amber','AMBER','warn · defensive'],
              ['--qe-cyan','CYAN','primary accent · live'],
              ['--qe-blue','BLUE','secondary action'],
              ['--qe-magenta','MAGENTA','reserved · neutral hot'],
              ['--qe-text','TEXT','primary'],
              ['--qe-sub','SUB','secondary'],
            ].map(([v,n,d]) => (
              <div key={v} style={{border:'1px solid var(--qe-line)', padding:6}}>
                <div style={{height:22, background:`var(${v})`, marginBottom:4}}/>
                <div style={{fontFamily:'var(--qe-mono)', fontSize:'0.58rem', fontWeight:700}}>{n}</div>
                <div style={{fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-muted)'}}>{d}</div>
              </div>
            ))}
          </div>
        </Card>

        {/* Type */}
        <Card pad>
          <SecLbl rule>Type</SecLbl>
          <div style={{display:'flex', flexDirection:'column', gap:8}}>
            <div className="qe-hero-val">82.20<span className="qe-hero-cents">.001</span></div>
            <div className="qe-mono" style={{fontSize:'1.4rem', fontWeight:700}}>BTCUSDT 93,412.10</div>
            <div className="qe-mono" style={{fontSize:'0.86rem'}}>0.012  ·  1,120.94 USDT  ·  -1.18%</div>
            <div className="qe-mono" style={{fontSize:'0.66rem', color:'var(--qe-sub)'}}>Tabular numbers, sharp corners, no anti-aliased curves.</div>
            <div className="qe-lbl">section label · uppercase · letter-spaced</div>
          </div>
        </Card>

        {/* Badges + status */}
        <Card pad>
          <SecLbl rule>Badges · status</SecLbl>
          <div className="spec-row">
            <span className="l">Badges</span>
            <div style={{display:'flex', gap:4, flexWrap:'wrap'}}>
              <Badge tone="ok">OK</Badge><Badge tone="warn">WARN</Badge><Badge tone="err">LIMIT</Badge>
              <Badge tone="info">LIVE</Badge><Badge tone="blue">PAPER</Badge><Badge tone="mag">SHADOW</Badge>
              <Badge tone="mute">—</Badge>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Regimes</span>
            <div style={{display:'flex', gap:4, flexWrap:'wrap'}}>
              <RegimeBadge tone="trend"/><RegimeBadge tone="chop"/><RegimeBadge tone="neut"/>
              <RegimeBadge tone="def"/><RegimeBadge tone="panic"/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Status dots</span>
            <div style={{display:'flex', gap:14, flexWrap:'wrap'}}>
              <StatusDot tone="ok"  label="WS"  value="93ms"/>
              <StatusDot tone="warn" label="DD" value="WARN"/>
              <StatusDot tone="err"  label="HALT" value="LIMIT"/>
              <StatusDot tone="info" label="LIVE"/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Deltas</span>
            <div style={{display:'flex', gap:14, flexWrap:'wrap'}}>
              <Delta value="+1.93" pct="+2.18"/><Delta value="-1.04" pct="-1.18"/><Delta value="0.00" pct="0.00"/>
            </div>
          </div>
        </Card>

        {/* Buttons + inputs */}
        <Card pad>
          <SecLbl rule>Controls</SecLbl>
          <div className="spec-row">
            <span className="l">Buttons</span>
            <div style={{display:'flex', gap:6, flexWrap:'wrap'}}>
              <button className="qe-btn qe-btn-primary">Primary</button>
              <button className="qe-btn">Secondary</button>
              <button className="qe-btn qe-btn-success">Success</button>
              <button className="qe-btn qe-btn-danger">Danger</button>
              <button className="qe-btn qe-btn-ghost">Ghost</button>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Period selector</span>
            <PeriodSelector options={[['7d','7D'],['30d','30D'],['90d','90D'],['ytd','YTD'],['all','ALL']]} value="30d" onChange={()=>{}}/>
          </div>
          <div className="spec-row">
            <span className="l">Inputs</span>
            <div style={{display:'flex', gap:6}}>
              <input className="qe-input" placeholder="symbol" style={{maxWidth:140}}/>
              <select className="qe-input qe-select" style={{maxWidth:120}}><option>LIMIT</option><option>MARKET</option></select>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Stepper input</span>
            <div style={{display:'flex', gap:6}}>
              <div style={{width:110}}><StepperInput defaultValue="94100.00" step={0.1} decimals={2} min={0} color="var(--qe-green)"/></div>
              <div style={{width:80}}><StepperInput defaultValue="2.5" step={0.1} decimals={1} min={0}/></div>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Workspace lock</span>
            <div style={{display:'flex', alignItems:'center', gap:10, flexWrap:'wrap'}}>
              <LockButton locked={false} onToggle={()=>{}}/>
              <LockButton locked={true} onToggle={()=>{}}/>
              <span className="qe-mono" style={{fontSize:'0.56rem', color:'var(--qe-muted)', maxWidth:260, lineHeight:1.5}}>
                single control in the top nav (left of the account picker) · freezes drag + resize on <strong style={{color:'var(--qe-text)'}}>every</strong> workspace via <code style={{color:'var(--qe-cyan)'}}>grid.setStatic()</code> · universal &amp; persisted across tabs
              </span>
            </div>
          </div>
        </Card>

        {/* Gauges */}
        <Card pad>
          <SecLbl rule>Gauges (single primitive · color shifts at 60/80%)</SecLbl>
          <div style={{display:'flex', flexDirection:'column', gap:14}}>
            <Gauge label="Exposure"   value={1.2} max={5}  current="24%" maxLabel="5.0× cap"/>
            <Gauge label="Drawdown"   value={6.2} max={10} current="6.2%" maxLabel="10.0% limit" ticks={[5,8]}/>
            <Gauge label="Halt approach" value={9.1} max={10} current="9.1%" maxLabel="hard stop"/>
          </div>
        </Card>

        {/* EmptyState */}
        <Card pad>
          <SecLbl rule>Empty states (single primitive · 3 tones · replaces 7 ad-hoc)</SecLbl>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:8}}>
            <EmptyState tone="neutral" glyph="◇" msg="No open positions"/>
            <EmptyState tone="info" glyph="〇" msg="No data in window" cta={<button className="qe-btn qe-btn-sm qe-btn-primary">Open Calc →</button>}/>
            <EmptyState tone="warn" glyph="∅" msg="Not backfilled" hint="Run backfill to populate this signal." cta={<button className="qe-btn qe-btn-sm">Backfill →</button>}/>
          </div>
        </Card>

        {/* Card variants */}
        <Card pad>
          <SecLbl rule>Card variants</SecLbl>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
            <Card>
              <Lbl>default</Lbl>
              <div className="qe-mono" style={{fontSize:'0.7rem', color:'var(--qe-sub)'}}>padding 6/8 · 1px border</div>
            </Card>
            <Card tight>
              <Lbl>tight</Lbl>
              <div className="qe-mono" style={{fontSize:'0.7rem', color:'var(--qe-sub)'}}>padding 4/6</div>
            </Card>
            <Card pad>
              <Lbl>pad</Lbl>
              <div className="qe-mono" style={{fontSize:'0.7rem', color:'var(--qe-sub)'}}>padding 10/12 · for hero content</div>
            </Card>
            <Card ticks>
              <Lbl>ticks</Lbl>
              <div className="qe-mono" style={{fontSize:'0.7rem', color:'var(--qe-sub)'}}>corner-tick decoration</div>
            </Card>
            <Card hot style={{gridColumn:'1/-1'}}>
              <Lbl>hot</Lbl>
              <div className="qe-mono" style={{fontSize:'0.7rem', color:'var(--qe-sub)'}}>cyan border · used to signal primary focus</div>
            </Card>
          </div>
        </Card>

        {/* PaneFoot */}
        <Card pad>
          <SecLbl rule>PaneFoot · last-response line</SecLbl>
          <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginBottom:8, lineHeight:1.5}}>
            16px footer mirroring the latest <code style={{color:'var(--qe-cyan)'}}>engine_events</code> row driving the pane.
            Wire each <code style={{color:'var(--qe-cyan)'}}>#pane-foot-X</code> to SSE for the live "tail -f" feel.
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:2, border:'1px solid var(--qe-line)'}}>
            <PaneFoot tone="ok"   id={1841} msg="snapshot persisted · eq=82.20 · n=1247"       ms={8}/>
            <PaneFoot tone="info" id={1842} msg="WS kline · last tick C=82.30 · stream age 1.2s" ms={0}/>
            <PaneFoot tone="warn" id={1846} msg="period pnl negative · -11.18 · winrate 38.7%"  ms={6}/>
            <PaneFoot tone="err"  id={1849} msg="exchange ws disconnected · attempt 3/5"         ms={null}/>
            <PaneFoot tone="sub"  id={1847} msg="preset SWING · dd window 30d · mode advisory"  ms={1}/>
          </div>
        </Card>

        {/* Pane */}
        <Card pad style={{gridColumn:'1 / span 2'}}>
          <SecLbl rule>Pane · canonical tile container</SecLbl>
          <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginBottom:8, lineHeight:1.5}}>
            Every tile in the engine is a <code style={{color:'var(--qe-cyan)'}}>{`<Pane>`}</code>.
            Layout = head (20px, title + count + tag + right slot, then the auto <code style={{color:'var(--qe-cyan)'}}>↻</code> reload + <code style={{color:'var(--qe-cyan)'}}>···</code>) + body (scrolling) + foot (16px, optional) + resize grip.
            Click <code style={{color:'var(--qe-cyan)'}}>↻</code> to reload a single pane; if its body throws it self-heals to a recoverable error state.
            <br/>Spacing: the pane gutter is the token <code style={{color:'var(--qe-cyan)'}}>--qe-pane-gap</code> (4px) — <code style={{color:'var(--qe-cyan)'}}>GridWorkspace</code> applies half as tile margin (neighbours sit one gap apart) and half as edge padding (workspace edges match). Pages never add their own padding around a workspace.
          </div>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, height:160}}>
            <Pane title="Open Positions" count={5}
              right={<Badge tone="ok">LIVE</Badge>}
              foot={{tone:'info', id:1844, msg:'reconciler synced · 5 positions · 4 working orders', ms:42}}>
              <div className="qe-mono" style={{fontSize:'0.66rem', color:'var(--qe-sub)'}}>pane body — fills, scrolls independently</div>
            </Pane>
            <Pane title="Regime · ATR" hot tag="VIEW"
              foot={{tone:'ok', id:2010, msg:'regime fresh · atr_c=1.84', ms:42}}>
              <div className="qe-mono" style={{fontSize:'0.66rem', color:'var(--qe-sub)'}}>hot variant = cyan border for primary focus pane</div>
            </Pane>
          </div>
        </Card>

        {/* Reload + loading spinner — the engine standard */}
        <Card pad style={{gridColumn:'1 / span 2', borderColor:'var(--qe-cyan)'}}>
          <SecLbl rule>Reload + loading · the braille spinner standard (engine-wide)</SecLbl>
          <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginBottom:10, lineHeight:1.55}}>
            Loading is <strong style={{color:'var(--qe-text)'}}>always</strong> the square 2×2 braille spinner — <code style={{color:'var(--qe-cyan)'}}>{'<Spinner>'}</code> / <code style={{color:'var(--qe-cyan)'}}>BrailleSquares</code>, the one busy indicator (boot splash, pane reloads, anywhere). The reload button rests as the circular arrow and swaps to the spinner while reloading; the veil darkens the body but the <code style={{color:'var(--qe-cyan)'}}>PaneFoot</code> stays lit. No alternatives.
          </div>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10}}>
            <Pane title="Open Positions" count={5} right={<Badge tone="ok">LIVE</Badge>} resizable={false} style={{height:108}}
              foot={{tone:'info', id:1844, msg:'reconciler synced · click ↻ to reload', ms:42}}>
              <FieldList rows={[
                {label:'BTCUSDT', value:'+2.02', color:'green'},
                {label:'ETHUSDT', value:'+3.47', color:'green'},
                {label:'SOLUSDT', value:'-0.85', color:'red'},
              ]}/>
            </Pane>
            <div style={{display:'flex', flexDirection:'column', justifyContent:'center', gap:12, padding:'0 4px'}}>
              <div style={{fontSize:'0.5rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', letterSpacing:'0.1em'}}>
                {'<Spinner size label color> · the one loading indicator'}
              </div>
              <div style={{display:'flex', alignItems:'center', gap:22, flexWrap:'wrap'}}>
                <Spinner size="0.8rem"/>
                <Spinner label="loading"/>
                <Spinner size="1.1rem" label="fetching" color="var(--qe-green)"/>
                <Spinner size="1.4rem" label="computing" color="var(--qe-amber)"/>
              </div>
              <div style={{fontSize:'0.5rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', lineHeight:1.5}}>
                click the pane's <span style={{color:'var(--qe-text-dim)'}}>↻</span> to see the reload state — same spinner, engine-wide
              </div>
            </div>
          </div>
        </Card>

        {/* LiveValue */}
        <Card pad style={{gridColumn:'1 / span 2', borderColor:'var(--qe-cyan)'}}>
          <SecLbl rule>LiveValue · the refresh standard</SecLbl>
          <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginBottom:8, lineHeight:1.6}}>
            <strong style={{color:'var(--qe-cyan)'}}>Rule:</strong> async streams must target the <em style={{color:'var(--qe-text)'}}>value</em>, never the surrounding card / row / pane.
            Swapping a whole body causes layout reflow + visible flicker. Each streamed number/string is wrapped in a
            <code style={{color:'var(--qe-cyan)', margin:'0 4px'}}>{`<LiveValue id="…">`}</code>
            with a stable <code style={{color:'var(--qe-cyan)'}}>data-live-id</code>. SSE/htmx OOB swaps target just that span.
          </div>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:12}}>
            <div>
              <Lbl>example values</Lbl>
              <div style={{display:'grid', gridTemplateColumns:'140px 1fr', rowGap:6, columnGap:10, marginTop:6, fontSize:'0.64rem'}}>
                <span style={{color:'var(--qe-sub)', fontFamily:'var(--qe-mono)'}}>pos.BTC.mark</span>
                <LiveValueDemo id="demo.btc.mark" base={93580.40} fmt={v=>v.toFixed(2)} style={{fontSize:'0.78rem',fontWeight:700,color:'var(--qe-text)'}}/>
                <span style={{color:'var(--qe-sub)', fontFamily:'var(--qe-mono)'}}>pos.BTC.pnl</span>
                <LiveValueDemo id="demo.btc.pnl" base={2.02} jitter={0.4} fmt={v=>(v>=0?'+':'')+v.toFixed(2)} style={{fontSize:'0.78rem',fontWeight:700, color:'var(--qe-green)'}}/>
                <span style={{color:'var(--qe-sub)', fontFamily:'var(--qe-mono)'}}>regime.score</span>
                <LiveValueDemo id="demo.regime.score" base={0.62} jitter={0.02} fmt={v=>v.toFixed(2)} style={{fontSize:'0.78rem',fontWeight:700, color:'var(--qe-cyan)'}}/>
                <span style={{color:'var(--qe-sub)', fontFamily:'var(--qe-mono)'}}>ws.latency.ms</span>
                <LiveValueDemo id="demo.ws.latency" base={93} jitter={8} fmt={v=>Math.round(v)+'ms'} style={{fontSize:'0.78rem',fontWeight:700, color:'var(--qe-green)'}}/>
                <span style={{color:'var(--qe-sub)', fontFamily:'var(--qe-mono)'}}>fund.next</span>
                <LiveValue id="demo.fund.next" value="04-25 16:00" style={{fontSize:'0.78rem',fontWeight:700,color:'var(--qe-amber)'}}/>
                <span style={{color:'var(--qe-sub)', fontFamily:'var(--qe-mono)'}}>stale signal</span>
                <LiveValue id="demo.btc.dom" value="58.12" stale style={{fontSize:'0.78rem',fontWeight:700}}/>
              </div>
            </div>
            <div>
              <Lbl>server-side wire (htmx OOB)</Lbl>
              <pre style={{
                fontFamily:'var(--qe-mono)', fontSize:'0.58rem', color:'var(--qe-text-dim)',
                background:'var(--qe-bg)', border:'1px solid var(--qe-line)', padding:8, margin:'6px 0 0',
                lineHeight:1.5, overflow:'auto',
              }}>{`{# server emits, every tick: #}
<span data-live-id="pos.BTC.mark"
      hx-swap-oob="innerHTML:[data-live-id='pos.BTC.mark']">
  93,580.40
</span>

{# or via SSE: #}
event: live.pos.BTC.mark
data: 93580.40`}</pre>
              <div style={{fontSize:'0.6rem', color:'var(--qe-sub)', marginTop:6, lineHeight:1.5}}>
                Card body, pane chrome, table row — none of them re-render.
                Only the inner span morphs. Flash green/red is local + free.
              </div>
            </div>
          </div>
        </Card>

        {/* DataList */}
        <Card pad>
          <SecLbl rule>DataList · canonical row table</SecLbl>
          <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginBottom:8, lineHeight:1.5}}>
            Replaces ad-hoc <code style={{color:'var(--qe-cyan)'}}>{`<table>`}</code>. Column schema + render fns + optional summary footer. Built-in <strong style={{color:'var(--qe-text)'}}>search · click-to-sort headers · auto filters</strong> — on automatically for record lists (≥5 rows, or ≥3 with a categorical column). Force with <code style={{color:'var(--qe-cyan)'}}>tools</code>; opt a column out with <code style={{color:'var(--qe-cyan)'}}>filter:false</code> / <code style={{color:'var(--qe-cyan)'}}>sort:false</code>.
          </div>
          <div style={{margin:'0 -12px -10px'}}>
            <DataList
              selKey="sym"
              tools
              columns={[
                {key:'sym',  label:'SYM',  render:r=><span style={{color:'var(--qe-cyan)',fontWeight:700}}>{r.sym}</span>},
                {key:'dir',  label:'SIDE', render:r=><Badge tone={r.dir==='L'?'ok':'err'}>{r.dir==='L'?'LONG':'SHORT'}</Badge>},
                {key:'pnl',  label:'PnL',  align:'right', render:r=><span style={{color:r.pnl>=0?'var(--qe-green)':'var(--qe-red)',fontWeight:700}}>{r.pnl>=0?'+':''}{r.pnl}</span>},
                {key:'pct',  label:'%',    align:'right', render:r=><span style={{color:r.pct>=0?'var(--qe-green)':'var(--qe-red)'}}>{r.pct>=0?'+':''}{r.pct}%</span>},
              ]}
              rows={[
                {sym:'BTCUSDT', dir:'L', pnl:+2.02, pct:+0.18},
                {sym:'ETHUSDT', dir:'S', pnl:+3.47, pct:+0.19},
                {sym:'SOLUSDT', dir:'L', pnl:-0.85, pct:-0.42},
                {sym:'MKRUSDT', dir:'S', pnl:+1.10, pct:+0.07},
                {sym:'BNBUSDT', dir:'L', pnl:+0.54, pct:+0.21},
                {sym:'ADAUSDT', dir:'S', pnl:-1.20, pct:-0.63},
              ]}
              summary={<><span>6 / 20</span><span style={{color:'var(--qe-green)'}}>Σ +5.08</span></>}
            />
          </div>
        </Card>

        {/* FieldList */}
        <Card pad>
          <SecLbl rule>FieldList · canonical key→value rows</SecLbl>
          <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginBottom:8, lineHeight:1.5}}>
            The vertical sibling of <code style={{color:'var(--qe-cyan)'}}>DataList</code>: one record's fields stacked as label → value. Single-line rows lock to the 20px pane-head height. Replaces <code style={{color:'var(--qe-cyan)'}}>VRow</code> + the Active Parameters / Correlated Exposure / Performance Ratios variants.
          </div>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:14}}>
            <div>
              <div style={{fontSize:'0.5rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', marginBottom:4}}>value tones · meta col · bar · emphasis</div>
              <FieldList rows={[
                {label:'Risk/trade',     value:'1.00%', color:'cyan'},
                {label:'Max DD',         value:'10.0%'},
                {label:'Crypto · Majors', value:'+1,120.94', color:'green', meta:'50% cap', bar:{pct:42, color:'var(--qe-green)'}},
                {label:'BTC Market Cap', value:'1,870 $B', color:'amber'},
                {label:'New (BTC)',      value:'+1,120.94 USDT', emphasis:true},
              ]}/>
            </div>
            <div>
              <div style={{fontSize:'0.5rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', marginBottom:4}}>hint sublabels · cols=2</div>
              <FieldList cols={2} rows={[
                {label:'Sharpe',   hint:'annualized',     value:'2.18', color:'green'},
                {label:'Sortino',  hint:'downside σ',     value:'2.48', color:'green'},
                {label:'Profit F.',hint:'Σw / |Σl|',      value:'0.74', color:'red'},
                {label:'Expect.',  hint:'mean R',         value:'-0.36R', color:'red'},
              ]}/>
            </div>
          </div>
        </Card>

        {/* NewsTickerBar */}
        <Card pad>
          <SecLbl rule>NewsTickerBar · footer marquee</SecLbl>
          <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginBottom:8, lineHeight:1.5}}>
            Single-line async news feed. Holds ~1s then scrolls one full pass; pauses on hover. <code style={{color:'var(--qe-cyan)'}}>React.memo</code> + inlined runs keep the animation from restarting under parent re-renders. Defaults to the Regime feed; pass <code style={{color:'var(--qe-cyan)'}}>news</code> to override.
          </div>
          <NewsTickerBar
            label="NEWS"
            meta="DEMO FEED"
            news={[
              {id:'s1', source:'finnhub', impact:'high',   headline:'CPI prints cooler than expected; rate-cut odds firm up', tickers:'SPY,TLT', published_at:'2026-04-25T18:42:00Z'},
              {id:'s2', source:'bwe',     impact:'medium', headline:'BTC reclaims $94k as ETF inflows resume', tickers:'BTC,IBIT', published_at:'2026-04-25T18:05:00Z'},
              {id:'s3', source:'finnhub', impact:'low',    headline:'Dollar steadies ahead of Friday payrolls', tickers:'DXY', published_at:'2026-04-25T17:20:00Z'},
            ]}
          />
        </Card>

        {/* Strip + Tabs */}
        <Card pad>
          <SecLbl rule>Strip · info ticker</SecLbl>
          <Strip items={[
            {label:'EXCH',  value:'Binance'},
            {label:'LAT',   value:'93ms', color:'var(--qe-green)'},
            {label:'REGIME',value:<RegimeBadge tone="chop"/>},
            {label:'P&L·D', value:<Delta value="-0.00" pct="-0.00" flat/>},
          ]}/>
          <SecLbl rule style={{marginTop:14}}>Tabs</SecLbl>
          <Tabs value="overview" onChange={()=>{}} tabs={[
            ['overview','Overview', null],
            ['equity','Equity Curve', null],
            ['pairs','Pairs', 8],
            ['mfemae','MFE / MAE', null],
          ]}/>
        </Card>

        {/* HeroNumber + Stat + FlashCell */}
        <Card pad>
          <SecLbl rule>Number primitives</SecLbl>
          <div className="spec-row">
            <span className="l">HeroNumber</span>
            <HeroNumber value="82.20" ccy="USDT" size="1.8rem"/>
          </div>
          <div className="spec-row">
            <span className="l">Stat</span>
            <div style={{display:'flex', gap:14}}>
              <Stat label="Available" value="82.20" sub="USDT"/>
              <Stat label="DD 30d" value="0.00%" sub="limit 10%" color="var(--qe-green)"/>
              <Stat label="Win Rate" value="38.7%" sub="12W · 19L"/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">FlashCell</span>
            <div style={{display:'flex', alignItems:'center', gap:8}}>
              <FlashCell value={93580.40} formatter={v=>v.toFixed(2)} style={{fontSize:'0.84rem',fontWeight:700,color:'var(--qe-text)'}}/>
              <span className="qe-mono" style={{fontSize:'0.56rem', color:'var(--qe-muted)'}}>flashes green/red on change · wire to SSE</span>
            </div>
          </div>
        </Card>

        {/* Regime ribbon + heat strip */}
        <Card pad>
          <SecLbl rule>Regime ribbon · Heat strip</SecLbl>
          <div className="spec-row">
            <span className="l">RegimeRibbon</span>
            <div style={{width:'100%'}}>
              <RegimeRibbon height={20} segments={[
                {tone:'neut',t:3},{tone:'chop',t:5},{tone:'trend',t:2},{tone:'chop',t:6},{tone:'def',t:1},{tone:'chop',t:7},{tone:'panic',t:1},{tone:'def',t:2},
              ]}/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">HeatStrip</span>
            <div style={{width:'100%'}}>
              <HeatStrip height={20} data={Array.from({length:30},(_,i)=>({date:`04-${i+1}`, pnl:(Math.random()-0.55)*2}))}/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Gauge tone</span>
            <div style={{width:'100%', display:'flex', flexDirection:'column', gap:10}}>
              <Gauge label="OK"   value={1.2} max={5}  current="24%" maxLabel="cap"/>
              <Gauge label="WARN" value={6.5} max={10} current="65%" maxLabel="limit"/>
              <Gauge label="ERR"  value={9.1} max={10} current="91%" maxLabel="hard stop"/>
            </div>
          </div>
        </Card>

        {/* Notifications */}
        <Card pad style={{gridColumn:'1 / span 2', borderColor:'var(--qe-cyan)'}}>
          <SecLbl rule>Notifications · new primitives (Switch · Chip · Banner · Toast · Bell · Row)</SecLbl>
          <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginBottom:8, lineHeight:1.5}}>
            Added with the notification system. <code style={{color:'var(--qe-cyan)'}}>Switch</code> = boolean toggle ·
            <code style={{color:'var(--qe-cyan)'}}> Chip</code> = muteable filter pill ·
            <code style={{color:'var(--qe-cyan)'}}> Banner</code> = pinned alert bar (under nav) ·
            <code style={{color:'var(--qe-cyan)'}}> Toast</code> = transient corner popup, severity rail + auto-dismiss countdown ·
            <code style={{color:'var(--qe-cyan)'}}> NotifBell</code> = nav icon + unread badge ·
            <code style={{color:'var(--qe-cyan)'}}> NotifRow</code> = notification-center list item. The priority filter reuses
            <code style={{color:'var(--qe-cyan)'}}> PeriodSelector</code>; buttons/empty-state reuse existing primitives.
          </div>
          <div className="spec-row">
            <span className="l">Switch</span>
            <div style={{display:'flex', gap:18}}>
              <Switch label="Sound" checked={true}/>
              <Switch label="Desktop" checked={true} accent="var(--qe-green)"/>
              <Switch label="DND" checked={false}/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Chip · filter</span>
            <div style={{display:'flex', gap:5, flexWrap:'wrap'}}>
              <Chip label="All" count={8} active={true}/>
              <Chip label="Fills" count={3} onMute={()=>{}}/>
              <Chip label="Risk" count={2} onMute={()=>{}}/>
              <Chip label="News" count={1} muted={true} onMute={()=>{}}/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Bell</span>
            <div style={{display:'flex', alignItems:'center', gap:10}}>
              <NotifBell/>
              <span className="qe-mono" style={{fontSize:'0.56rem', color:'var(--qe-muted)'}}>+ red unread-count badge when count &gt; 0</span>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Banner · alert</span>
            <div style={{width:'100%', border:'1px solid var(--qe-line)'}}>
              <Banner tone="err" tag="HALT" title="TRADING HALTED" detail="Daily hard-stop 5.04% > 5.00% cap · positions frozen" time="14:31:06" releaseIn="0d 19h 21m 16s"/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">Toast</span>
            <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
              <Toast tone="ok"   tag="FILLS" time="14:31:06" title="FILLED · BUY 0.0420 BTC" detail="@ 93,580.4 · order #A1903"/>
              <Toast tone="warn" tag="RISK"  time="14:30:18" title="Weekly loss 78% of limit" detail="−$1,840 of −$2,360"/>
              <Toast tone="err"  tag="RISK"  time="14:31:06" title="TRADING HALTED — hard-stop breached" detail="DD 5.04% > 5.00% cap"/>
            </div>
          </div>
          <div className="spec-row">
            <span className="l">NotifRow</span>
            <div style={{width:'100%', border:'1px solid var(--qe-line)'}}>
              <NotifRow ev={{id:'x1', ch:'REGIME', pri:'risk', head:'Regime → RISK-OFF PANIC', detail:'was DEFENSIVE · size ×1.0 → ×0.25', ts:Date.now()-48000, unread:true}}  now={Date.now()} muted={false} onRead={()=>{}} onDismiss={()=>{}}/>
              <NotifRow ev={{id:'x2', ch:'SYSTEM', pri:'routine', head:'Market WS reconnected', detail:'2 streams · 93ms · gap 1.4s recovered', ts:Date.now()-240000, unread:false}} now={Date.now()} muted={false} onRead={()=>{}} onDismiss={()=>{}}/>
            </div>
          </div>
        </Card>

      </div>
    </div>
    <StatusFooter/>
  </div>
);

/* ── App router ───────────────────────────────────────────────────────── */
const QE_PAGES = {
  Dashboard:  DashTiled,
  'Pre-Trade': CalculatorPage,
  Linkage:    DashLinkA,
  History:    HistoryPage,
  Analytics:  AnalyticsPage,
  Models:     ModelsPage,
  Regime:     RegimePage,
  Config:     ConfigPage,
  Primitives: PrimitivesPage,
};

const readHashPage = () => {
  const h = decodeURIComponent((window.location.hash || '').replace(/^#/, ''));
  return QE_PAGES[h] ? h : null;
};

const App = () => {
  const [page, setPage] = React.useState(() => {
    const fromHash = readHashPage();
    if (fromHash) return fromHash;
    try { const s = localStorage.getItem('qe.page'); if (QE_PAGES[s]) return s; } catch (e) {}
    return 'Dashboard';
  });

  // Expose the global navigator immediately so TopNavStd clicks route on first paint.
  window.qeNav = (p) => { if (QE_PAGES[p]) setPage(p); };

  React.useEffect(() => {
    const onHash = () => { const p = readHashPage(); if (p) setPage(p); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  React.useEffect(() => {
    try { localStorage.setItem('qe.page', page); } catch (e) {}
    if (readHashPage() !== page) { try { history.replaceState(null, '', '#' + page); } catch (e) {} }
    document.title = 'Meridian v3.0 — ' + page;
  }, [page]);

  const PageComp = QE_PAGES[page] || DashTiled;
  return (
    <NotificationProvider>
      <PageComp/>
    </NotificationProvider>
  );
};

const _qeRoot = ReactDOM.createRoot(document.getElementById('root'));
_qeRoot.render(<App/>);

Object.assign(window, { App, PrimitivesPage, LiveValueDemo, QE_PAGES });
