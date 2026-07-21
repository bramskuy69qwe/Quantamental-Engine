/* QE v3.0 — Models tab: the per-model detailed view. A nested tab strip mirrors
   the MultiCharts report sheets and shows the selected run:
     Overview | Strategy Analysis | Graphs | List of Trades | Trade Analysis |
     Periodical | Settings
   Overview holds the model's own chrome (risk preset, strategy, runs, usage);
   the rest render the selected run via the section components in
   pages-models-report.jsx. Depends on pages-models-data / -lib / -report. */

const _FieldRow = ({l, v, color}) => (
  <div style={{display:'grid', gridTemplateColumns:'104px 1fr', gap:8, padding:'3px 0', borderBottom:'1px solid var(--qe-faint)'}}>
    <span style={{fontFamily:'var(--qe-ui)', fontSize:'0.54rem', fontWeight:600, letterSpacing:'0.06em', textTransform:'uppercase', color:'var(--qe-muted)'}}>{l}</span>
    <span className="qe-mono" style={{fontSize:'0.62rem', color: color || 'var(--qe-text)', textWrap:'pretty'}}>{v}</span>
  </div>
);

// ── Overview tab — model chrome (risk preset, strategy, runs, usage) ────────
const OverviewTab = ({m, onOpenRun, onImport, onLoadCalc}) => {
  const r = m.risk;
  return (
    <GridWorkspace key={'ov-'+m.id}>
      <GridItem x={0} y={0} w={8} h={11} minW={5} minH={8}>
        <Pane title="Risk, Sizing & Source" style={{height:'100%'}}
          foot={{tone:'info', id:5104, msg:'exchange-agnostic · pushed into the live calculator', ms:1}}>
          <_FieldRow l="Risk / trade" v={r.riskPct.toFixed(2) + '%'} color="var(--qe-cyan)"/>
          <_FieldRow l="Sizing rule" v={r.sizing}/>
          <_FieldRow l="Match window" v={r.matchWindow + 's'}/>
          <_FieldRow l="TP method" v={r.tp}/>
          <_FieldRow l="SL method" v={r.sl}/>
          <_FieldRow l="Regime mult." v={r.regimeMult ? 'ON' : 'OFF'} color={r.regimeMult ? 'var(--qe-green)' : 'var(--qe-muted)'}/>
          <_FieldRow l="Size override" v={r.sizeOverride != null ? '$' + r.sizeOverride : '—'}/>
          {m.source && (
            <>
              <div style={{margin:'7px 0 3px', fontFamily:'var(--qe-ui)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.12em', textTransform:'uppercase', color:'var(--qe-cyan)'}}>Source · {m.source.app}</div>
              <_FieldRow l="Symbol" v={m.source.symbol || '—'} color="var(--qe-cyan)"/>
              <_FieldRow l="Resolution" v={m.source.resolution || '—'}/>
              <_FieldRow l="Point value" v={m.source.pointValue ? '$' + m.source.pointValue + ' / ' + m.source.currency : '—'}/>
              <_FieldRow l="Init capital" v={m.source.initialCapital ? '$' + Number(m.source.initialCapital).toLocaleString() : '—'}/>
              <_FieldRow l="Commission" v={m.source.commission || '—'}/>
              <_FieldRow l="Slippage" v={m.source.slippage || '—'}/>
            </>
          )}
          <button className="qe-btn qe-btn-sm qe-btn-on" style={{marginTop:8, width:'100%', justifyContent:'center'}} onClick={onLoadCalc}>↪ Load into Pre-Trade</button>
        </Pane>
      </GridItem>

      <GridItem x={0} y={11} w={8} h={6} minW={5} minH={6}>
        <Pane title="Strategy Definition" style={{height:'100%'}}
          foot={{tone:'sub', id:5103, msg:'definition only · performance comes from imported runs', ms:0}}>
          <div style={{fontSize:'0.6rem', color:'var(--qe-sub)', lineHeight:1.5, marginBottom:7, textWrap:'pretty'}}>{m.strategy.notes}</div>
          <_FieldRow l="Entry logic" v={m.strategy.entry}/>
          <_FieldRow l="Exit logic" v={m.strategy.exit}/>
          <_FieldRow l="Universe" v={m.strategy.universe} color="var(--qe-cyan)"/>
          <_FieldRow l="Regime cfg" v={m.strategy.regimeCfg}/>
        </Pane>
      </GridItem>

      <GridItem x={8} y={0} w={16} h={8} minW={9} minH={7}>
        <Pane title="Backtest Runs" count={m.runs.length} style={{height:'100%'}}
          right={<button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onImport}>⤓ Import Report</button>}
          foot={{tone:'sub', id:5101, msg:'performance imported from 3rd-party reports — engine does not run backtests', ms:0}}
          bodyStyle={{padding:0}}>
          {m.runs.length ? (
            <DataList selKey="id" onClick={(row) => onOpenRun(row)}
              columns={[
                {key:'source', label:'SOURCE', render:r=><Badge tone="info">{r.source}</Badge>},
                {key:'window', label:'WINDOW', render:r=><span className="qe-mono" style={{fontSize:'0.58rem'}}>{r.window}</span>},
                {key:'net', label:'NET P/L', align:'right', render:r=>{const k=runKpis(r.report);return <span className="qe-mono" style={{color:_plColor(k.net), fontWeight:700}}>{_money(k.net,0)}</span>;}},
                {key:'pf', label:'PF', align:'right', render:r=><span className="qe-mono">{runKpis(r.report).pf.toFixed(2)}</span>},
                {key:'win', label:'WIN%', align:'right', render:r=><span className="qe-mono">{runKpis(r.report).winPct}%</span>},
                {key:'dd', label:'MAX DD', align:'right', render:r=><span className="qe-mono" style={{color:'var(--qe-red)'}}>{runKpis(r.report).maxDDPct}%</span>},
                {key:'n', label:'TRADES', align:'right', render:r=><span className="qe-mono">{runKpis(r.report).nTrades}</span>},
                {key:'imported', label:'IMPORTED', align:'right', render:r=><span className="qe-mono" style={{fontSize:'0.54rem', color:'var(--qe-muted)'}}>{r.imported}</span>},
              ]}
              rows={m.runs}/>
          ) : (
            <div style={{padding:10, height:'100%', display:'flex', alignItems:'center', justifyContent:'center'}}>
              <EmptyState tone="warn" glyph="⤓" msg="No backtests imported yet"
                hint="Performance only ever comes from imported reports (MultiCharts .xlsx / .xml)."
                cta={<button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onImport}>⤓ Import a report</button>}/>
            </div>
          )}
        </Pane>
      </GridItem>

      <GridItem x={8} y={8} w={16} h={9} minW={9} minH={6}>
        <Pane title="Usage / Attribution" count={m.usage.length} style={{height:'100%'}}
          foot={{tone:'info', id:5102, msg:'positions & plans tagged with this model', ms:3}} bodyStyle={{padding:0}}>
          {m.usage.length ? (
            <DataList selKey="posId"
              columns={[
                {key:'posId', label:'POSITION', render:r=><span className="qe-mono" style={{color:'var(--qe-cyan)', fontSize:'0.58rem'}}>{r.posId}</span>},
                {key:'sym', label:'SYMBOL'},
                {key:'status', label:'STATUS', render:r=><Badge tone={r.status==='open'?'ok':'mute'}>{r.status.toUpperCase()}</Badge>},
                {key:'pnl', label:'PnL', render:r=><span className="qe-mono" style={{color:_plColor(r.pnl), fontWeight:700}}>{(r.pnl>=0?'+':'')+r.pnl.toFixed(2)}</span>},
                {key:'date', label:'DATE', align:'right', render:r=><span className="qe-mono" style={{color:'var(--qe-muted)'}}>{r.date}</span>},
              ]}
              rows={m.usage}/>
          ) : (
            <div style={{padding:10, height:'100%', display:'flex', alignItems:'center', justifyContent:'center'}}>
              <EmptyState tone="neutral" glyph="∅" msg="Not used by any positions yet"
                hint="When a live or closed position is tagged with this model, it appears here."/>
            </div>
          )}
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

const MODEL_SECTIONS = [
  ['overview', 'Overview'],
  ['strategy', 'Strategy Analysis'],
  ['graphs', 'Graphs'],
  ['trades', 'List of Trades'],
  ['analysis', 'Trade Analysis'],
  ['periodical', 'Periodical'],
  ['settings', 'Settings'],
];

// ── ModelView — nested tab shell + run selector ────────────────────────────
const ModelView = ({m, onImport, onLoadCalc}) => {
  const [section, setSection] = React.useState('overview');
  const [runId, setRunId] = React.useState(m.runs[0] ? m.runs[0].id : null);

  // keep run selection valid if the model changes
  React.useEffect(() => { setSection('overview'); setRunId(m.runs[0] ? m.runs[0].id : null); }, [m.id]);

  const run = m.runs.find(r => r.id === runId) || m.runs[0] || null;
  const report = run ? run.report : null;
  const needsRun = section !== 'overview' && !report;

  return (
    <div style={{display:'flex', flexDirection:'column', flex:1, minHeight:0}}>
      {/* nested section tabs + run selector */}
      <TabStrip value={section} onChange={setSection} tabs={MODEL_SECTIONS}
        right={report && section !== 'overview' && (
          <div style={{display:'flex', alignItems:'center', gap:6, paddingLeft:8}}>
            <span style={{fontSize:'0.5rem', color:'var(--qe-muted)', textTransform:'uppercase', letterSpacing:'0.08em'}}>Run</span>
            {m.runs.length > 1 ? (
              <select className="qe-input qe-select" value={runId} onChange={e => setRunId(e.target.value)} style={{width:170, height:18}}>
                {m.runs.map(r => <option key={r.id} value={r.id}>{r.window} · {r.source}</option>)}
              </select>
            ) : (
              <span className="qe-mono" style={{fontSize:'0.56rem', color:'var(--qe-cyan)'}}>{run.window} · {run.source}</span>
            )}
          </div>
        )}/>

      <div style={{flex:1, minHeight:0, display:'flex', flexDirection:'column'}}>
        {section === 'overview' && (
          <OverviewTab m={m} onImport={onImport} onLoadCalc={onLoadCalc}
            onOpenRun={(r) => { setRunId(r.id); setSection('strategy'); }}/>
        )}
        {needsRun && (
          <div style={{height:'100%', display:'flex', alignItems:'center', justifyContent:'center', padding:24}}>
            <EmptyState tone="warn" glyph="⤓" msg="No imported run to report on"
              hint="This model has no backtest yet. Import a MultiCharts report (.xlsx / .xml) to populate Strategy Analysis, trades, and the rest."
              cta={<button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onImport}>⤓ Import a report</button>}/>
          </div>
        )}
        {!needsRun && section === 'strategy' && <StrategyAnalysisTab report={report}/>}
        {!needsRun && section === 'graphs' && <GraphsTab report={report}/>}
        {!needsRun && section === 'trades' && <TradesTab report={report}/>}
        {!needsRun && section === 'analysis' && <AnalysisTab report={report}/>}
        {!needsRun && section === 'periodical' && <PeriodicalTab report={report}/>}
        {!needsRun && section === 'settings' && <SettingsTab report={report}/>}
      </div>
    </div>
  );
};

Object.assign(window, { ModelView, OverviewTab });
