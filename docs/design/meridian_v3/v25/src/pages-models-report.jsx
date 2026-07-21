/* QE v3.0 — Models tab: MultiCharts-shaped report sections. Renders a single
   run's report across the categories that mirror the XLSX sheets:
   Strategy Analysis · Graphs · List of Trades · Trade Analysis · Periodical ·
   Settings. All-trades / Long / Short three-column layout where the source has
   it. Depends on pages-models-data / -lib + primitives + charts + grid. */

// ── MultiCharts-style number cell ──────────────────────────────────────────
// Negatives render in (parens) and red; positives green; counts/ratios neutral.
const MCNum = ({v, fmt = 'usd', bold}) => {
  if (v == null || v === '') return <span style={{color:'var(--qe-muted)'}}>n/a</span>;
  if (fmt === 'str') return <span className="qe-mono" style={{color:'var(--qe-text)'}}>{v}</span>;
  const num = typeof v === 'number' ? v : parseFloat(v);
  if (isNaN(num)) return <span className="qe-mono" style={{color:'var(--qe-text)'}}>{v}</span>;
  // Profit Factor: MultiCharts exports it signed but displays the magnitude,
  // in (parens) + red when below 1 (sub-breakeven), plain green at/above 1.
  if (fmt === 'pf') {
    const a = Math.abs(num), lt1 = a < 1;
    return <span className="qe-mono" style={{color: lt1 ? 'var(--qe-red)' : 'var(--qe-green)', fontWeight: bold ? 700 : 500, fontVariantNumeric:'tabular-nums'}}>{lt1 ? '(' + a.toFixed(2) + ')' : a.toFixed(2)}</span>;
  }
  const neg = num < 0, zero = num === 0;
  let body;
  if (fmt === 'pct') body = (Math.abs(num) * 100).toFixed(2) + '%';
  else if (fmt === 'int') body = Math.round(Math.abs(num)).toLocaleString();
  else if (fmt === 'num') body = Math.abs(num).toFixed(2);
  else body = '$' + Math.abs(num).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
  const text = neg ? '(' + body + ')' : body;
  const color = (fmt === 'int' || zero) ? 'var(--qe-text)' : neg ? 'var(--qe-red)' : 'var(--qe-green)';
  return <span className="qe-mono" style={{color, fontWeight: bold ? 700 : 500, fontVariantNumeric:'tabular-nums'}}>{text}</span>;
};

// 3-column (All/Long/Short) grouped metric comparison. Each group renders as a
// SecLbl section header + its own DataList; fixed column widths keep every
// group's columns aligned across sections. (Was a hand-rolled grouped <table>.)
const _METRIC_COLS = [
  {key:'label', label:'Metric',       width:'40%', render:r=><span style={{color:'var(--qe-sub)', whiteSpace:'normal'}}>{r.label}</span>},
  {key:'all',   label:'All Trades',   align:'center', width:'20%', render:r=><MCNum v={r.all} fmt={r.fmt} bold/>},
  {key:'long',  label:'Long Trades',  align:'center', width:'20%', render:r=><MCNum v={r.long} fmt={r.fmt}/>},
  {key:'short', label:'Short Trades', align:'center', width:'20%', render:r=><MCNum v={r.short} fmt={r.fmt}/>},
];
const MetricTable = ({groups}) => (
  <div style={{display:'flex', flexDirection:'column'}}>
    {groups.map(g => (
      <div key={g.name}>
        <SecLbl rule style={{margin:'8px 7px 2px'}}>{g.name}</SecLbl>
        <DataList columns={_METRIC_COLS} rows={g.rows} dense={false} selKey="label" tools={false}/>
      </div>
    ))}
  </div>
);

// ── Strategy Analysis tab ──────────────────────────────────────────────────
const StrategyAnalysisTab = ({report}) => {
  const k = runKpis(report);
  return (
    <GridWorkspace key="sa">
      <GridItem x={0} y={0} w={24} h={6} minW={12} minH={5}>
        <Pane title="Key Metrics" style={{height:'100%'}}
          foot={{tone:'sub', id:5210, msg:'headline figures from the selected imported run', ms:0}}>
          <div style={{display:'grid', gridTemplateColumns:'repeat(6, minmax(0, 1fr))', gap:7}}>
            <KpiTile label="Net Profit" value={_money(k.net,0)} color={_plColor(k.net)}/>
            <KpiTile label="Profit Factor" value={k.pf.toFixed(2)} color={k.pf>=1?'var(--qe-green)':'var(--qe-red)'}/>
            <KpiTile label="% Profitable" value={k.winPct + '%'}/>
            <KpiTile label="Max Drawdown" value={k.maxDDPct + '%'} color="var(--qe-red)"/>
            <KpiTile label="Total Trades" value={k.nTrades}/>
            <KpiTile label="Account Size" value={_money((report.strategy.groups.find(g=>g.name==='Capital & Volatility').rows.find(r=>r.label==='Account Size Required')||{}).all||0,0)}/>
          </div>
        </Pane>
      </GridItem>

      <GridItem x={0} y={6} w={16} h={18} minW={9} minH={10}>
        <Pane title="Strategy Performance" tag="ALL / LONG / SHORT" style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'sub', id:5201, msg:'imported verbatim — engine does not recompute', ms:0}}>
          <MetricTable groups={report.strategy.groups}/>
        </Pane>
      </GridItem>

      <GridItem x={16} y={6} w={8} h={10} minW={6} minH={7}>
        <Pane title="Performance Ratios" tag="ALL TRADES" style={{height:'100%'}}
          foot={{tone:'sub', id:5211, msg:'risk-adjusted ratios · imported verbatim', ms:0}}>
          <FieldList dense rows={report.strategy.ratios.map(r => ({label:r.label, value:<MCNum v={r.all} fmt="num"/>}))}/>
        </Pane>
      </GridItem>

      <GridItem x={16} y={16} w={8} h={8} minW={6} minH={6}>
        <Pane title="Time Analysis" style={{height:'100%'}}
          foot={{tone:'sub', id:5212, msg:'exposure & holding-time stats for the run', ms:0}}>
          <FieldList dense rows={report.strategy.time.map(r => ({label:r.label, value:<MCNum v={r.val} fmt={r.fmt}/>}))}/>
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

// ── Strategy Analysis Graphs tab (redrawn, not the PNGs) ───────────────────
const GraphsTab = ({report}) => {
  const k = runKpis(report);
  const eq = runEquity(report), dd = runDrawdown(report);
  return (
    <GridWorkspace key="gr">
      <GridItem x={0} y={0} w={24} h={14} minW={10} minH={7}>
        <Pane title="Equity Curve" tag="CLOSED TRADES" style={{height:'100%'}}
          right={<span className="qe-mono" style={{fontSize:'0.54rem', color:'var(--qe-muted)'}}>net {_money(k.net,0)}</span>}
          foot={{tone:'sub', id:5213, msg:'redrawn from closed-trade equity · not the source PNG', ms:0}}
          bodyStyle={{padding:'4px 6px', display:'flex', flexDirection:'column'}}>
          <div style={{flex:1, minHeight:0}}><EquityChart data={eq} baseline={k.startEq} color={k.net>=0?'var(--qe-green)':'var(--qe-red)'}/></div>
        </Pane>
      </GridItem>
      <GridItem x={0} y={14} w={24} h={10} minW={10} minH={6}>
        <Pane title="Drawdown" tag="$ FROM PEAK" style={{height:'100%'}} bodyStyle={{padding:'4px 6px', display:'flex', flexDirection:'column'}}
          foot={{tone:'sub', id:5214, msg:'dollar drawdown from running equity peak', ms:0}}>
          <div style={{flex:1, minHeight:0}}><EquityChart data={dd} baseline={0} color="var(--qe-red)"/></div>
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

// ── List of Trades tab — entry/exit pair per trade, via the DataList primitive
// One DataList row per trade (entry value above, exit value below in each cell)
// so search · sort · filter operate on whole trades — sorting by P/L, drawdown,
// time, etc. keeps each entry/exit pair intact. The ALL/LONG/SHORT segmented
// control pre-filters the rows; DataList adds search + per-column sort + a
// Signal facet on top. (Was a hand-rolled two-<tr>-per-trade <table>.)
const TradesTab = ({report}) => {
  const [side, setSide] = React.useState('all');
  const trades = report.trades.filter(t => side === 'all' || t.side === side);
  const cols = [
    { key:'n', label:'#', sortVal:t=>t.n,
      render:t=><span className="qe-mono" style={{color:'var(--qe-muted)'}}>{t.n}</span> },
    { key:'order', label:'Order', sort:false, search:false,
      render:t=>(<div className="qe-mc-stack">
        <span className="qe-mono" style={{color:'var(--qe-muted)'}}>{2*t.n-1}</span>
        <span className="qe-mono" style={{color:'var(--qe-muted)', opacity:0.6}}>{2*t.n}</span>
      </div>) },
    { key:'side', label:'Type', filter:false, sortVal:t=>t.side, searchVal:t=>`${t.entryType} ${t.exitType}`,
      render:t=>(<div className="qe-mc-stack">
        <Badge tone={t.side==='L'?'ok':'err'}>{t.entryType.replace('Entry','')}</Badge>
        <span style={{fontSize:'0.5rem', color:'var(--qe-muted)'}}>{t.exitType.replace('Exit','Exit ')}</span>
      </div>) },
    { key:'entrySignal', label:'Signal', searchVal:t=>`${t.entrySignal} ${t.exitSignal}`,
      render:t=>(<div className="qe-mc-stack">
        <span className="qe-mono" style={{color:'var(--qe-cyan)', fontSize:'0.56rem'}}>{t.entrySignal}</span>
        <span className="qe-mono" style={{color:'var(--qe-sub)', fontSize:'0.56rem'}}>{t.exitSignal}</span>
      </div>) },
    { key:'entryDate', label:'Date', sortVal:t=>t.entryDate, searchVal:t=>`${t.entryDate} ${t.exitDate}`,
      render:t=>(<div className="qe-mc-stack">
        <span className="qe-mono" style={{color:'var(--qe-muted)', fontSize:'0.54rem'}}>{t.entryDate}</span>
        <span className="qe-mono" style={{color:'var(--qe-muted)', fontSize:'0.54rem', opacity:0.8}}>{t.exitDate}</span>
      </div>) },
    { key:'entryTime', label:'Time', sortVal:t=>t.entryTime, searchVal:t=>`${t.entryTime} ${t.exitTime}`,
      render:t=>(<div className="qe-mc-stack">
        <span className="qe-mono" style={{color:'var(--qe-muted)', fontSize:'0.54rem'}}>{t.entryTime}</span>
        <span className="qe-mono" style={{color:'var(--qe-muted)', fontSize:'0.54rem', opacity:0.8}}>{t.exitTime}</span>
      </div>) },
    { key:'entryPrice', label:'Price', align:'right', sortVal:t=>t.entryPrice,
      render:t=>(<div className="qe-mc-stack">
        <span className="qe-mono">{t.entryPrice}</span>
        <span className="qe-mono" style={{color:'var(--qe-muted)'}}>{t.exitPrice}</span>
      </div>) },
    { key:'contracts', label:'Cts', align:'right', render:t=><span className="qe-mono">{t.contracts}</span> },
    { key:'profit',    label:'Profit $', align:'right', sortVal:t=>t.profit,    render:t=><MCNum v={t.profit} fmt="usd" bold/> },
    { key:'profitPct', label:'Profit %', align:'right', sortVal:t=>t.profitPct, render:t=><MCNum v={t.profitPct} fmt="pct"/> },
    { key:'cum',       label:'Cum $',    align:'right', sortVal:t=>t.cum,       render:t=><MCNum v={t.cum} fmt="usd"/> },
    { key:'runup',     label:'Run-up $', align:'right', sortVal:t=>t.runup,     render:t=><MCNum v={t.runup} fmt="usd"/> },
    { key:'dd',        label:'Drawdn $', align:'right', sortVal:t=>t.dd,        render:t=><MCNum v={t.dd} fmt="usd"/> },
  ];
  return (
    <GridWorkspace key="tr">
      <GridItem x={0} y={0} w={24} h={24} minW={12} minH={12}>
        <Pane title="List of Trades" count={trades.length} style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'info', id:5202, msg:'entry/exit pair per trade · run-up & drawdown per MultiCharts', ms:0}}
          right={<span style={{display:'flex', gap:4}}>{[['all','ALL'],['L','LONG'],['S','SHORT']].map(([v,l])=>(
            <button key={v} className={`qe-btn qe-btn-sm ${side===v?'qe-btn-on':''}`} onClick={()=>setSide(v)}>{l}</button>))}</span>}>
          <div className="qe-mc-trades">
            <DataList selKey="n" columns={cols} rows={trades}
              emptyMsg={`no ${side==='L'?'long':side==='S'?'short':''} trades in run`}/>
          </div>
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

// ── Trade Analysis tab ─────────────────────────────────────────────────────
const AnalysisTab = ({report}) => {
  const ta = report.tradeAnalysis;
  return (
    <GridWorkspace key="an">
      <GridItem x={0} y={0} w={14} h={10} minW={8} minH={8}>
        <Pane title="Total Trade Analysis" tag="ALL / LONG / SHORT" style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'sub', id:5215, msg:'per-trade aggregates · all / long / short', ms:0}}>
          <DataList
            dense={false} selKey="label" tools={false}
            columns={[
              {key:'label', label:'Measure', cell:'dim'},
              {key:'all',   label:'All',   align:'center', render:r=><MCNum v={r.all} fmt="num" bold/>},
              {key:'long',  label:'Long',  align:'center', render:r=><MCNum v={r.long} fmt="num"/>},
              {key:'short', label:'Short', align:'center', render:r=><MCNum v={r.short} fmt="num"/>},
            ]}
            rows={ta.total}
          />
        </Pane>
      </GridItem>

      <GridItem x={14} y={0} w={10} h={5} minW={6} minH={5}>
        <Pane title="Outliers" tag="±1 STD DEV" style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'sub', id:5216, msg:'trades beyond ±1 standard deviation', ms:0}}>
          <DataList
            dense={false} selKey="label" tools={false}
            columns={[
              {key:'label',    label:'Measure',  cell:'dim'},
              {key:'total',    label:'Total',    align:'center', render:r=><MCNum v={r.total} fmt="num"/>},
              {key:'positive', label:'Positive', align:'center', render:r=><MCNum v={r.positive} fmt="num"/>},
              {key:'negative', label:'Negative', align:'center', render:r=><MCNum v={r.negative} fmt="num"/>},
            ]}
            rows={ta.outliers}
          />
        </Pane>
      </GridItem>

      <GridItem x={14} y={5} w={10} h={5} minW={6} minH={5}>
        <Pane title="Run-up / Drawdown" style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'sub', id:5217, msg:'intratrade run-up & drawdown extremes', ms:0}}>
          <DataList
            dense={false} selKey="label" tools={false}
            columns={[
              {key:'label',    label:'Measure',  cell:'dim'},
              {key:'runup',    label:'Run-up',   align:'center', render:r=><MCNum v={r.runup} fmt="num"/>},
              {key:'drawdown', label:'Drawdown', align:'right',  render:r=><MCNum v={r.drawdown} fmt="num"/>},
            ]}
            rows={ta.runupDD}
          />
        </Pane>
      </GridItem>

      <GridItem x={0} y={10} w={8} h={8} minW={6} minH={6}>
        <Pane title="Trade Series Analysis" style={{height:'100%'}}
          foot={{tone:'sub', id:5218, msg:'streaks & consecutive-trade behaviour', ms:0}}>
          <FieldList dense rows={ta.series.map(r => ({label:r.label, value:<MCNum v={r.value} fmt="num"/>}))}/>
        </Pane>
      </GridItem>

      <GridItem x={8} y={10} w={8} h={8} minW={6} minH={6}>
        <Pane title="Consecutive Winners" style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'sub', id:5219, msg:'win streaks · avg gain then next-trade loss', ms:0}}>
          <DataList
            dense={false} selKey="streak" tools={false}
            columns={[
              {key:'streak',      label:'Streak',        cell:'dim'},
              {key:'count',       label:'Series',        align:'center', render:r=><MCNum v={r.count} fmt="int"/>},
              {key:'avgGain',     label:'Avg Gain',      align:'center', render:r=><MCNum v={r.avgGain} fmt="usd"/>},
              {key:'avgLossNext', label:'Avg Loss Next', align:'right',  render:r=><MCNum v={r.avgLossNext} fmt="usd"/>},
            ]}
            rows={ta.seriesWinners}
          />
        </Pane>
      </GridItem>

      <GridItem x={16} y={10} w={8} h={8} minW={6} minH={6}>
        <Pane title="Consecutive Losers" style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'sub', id:5220, msg:'loss streaks · avg loss then next-trade gain', ms:0}}>
          <DataList
            dense={false} selKey="streak" tools={false}
            columns={[
              {key:'streak',      label:'Streak',        cell:'dim'},
              {key:'count',       label:'Series',        align:'center', render:r=><MCNum v={r.count} fmt="int"/>},
              {key:'avgLoss',     label:'Avg Loss',      align:'center', render:r=><MCNum v={r.avgLoss} fmt="usd"/>},
              {key:'avgGainNext', label:'Avg Gain Next', align:'right',  render:r=><MCNum v={r.avgGainNext} fmt="usd"/>},
            ]}
            rows={ta.seriesLosers}
          />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

// ── Periodical Analysis tab ────────────────────────────────────────────────
const PeriodicalTab = ({report}) => {
  const h = report.periodical.hourly;
  return (
    <GridWorkspace key="pe">
      <GridItem x={0} y={0} w={24} h={8} minW={10} minH={6}>
        <Pane title="Profit by Hour" tag="HOURLY" style={{height:'100%'}} bodyStyle={{padding:'4px 6px', display:'flex', flexDirection:'column'}}
          foot={{tone:'sub', id:5221, msg:'net profit bucketed by hour of day', ms:0}}>
          <div style={{flex:1, minHeight:0}}><BarChart data={h.map(x=>x.profit)} categories={h.map(x=>x.hour)} color="var(--qe-cyan)"/></div>
        </Pane>
      </GridItem>
      <GridItem x={0} y={8} w={24} h={12} minW={10} minH={8}>
        <Pane title="Hourly Period Analysis" count={h.length} style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'sub', id:5222, msg:'per-hour breakdown of the imported run', ms:0}}>
          <DataList
            dense={false} selKey="hour" tools={false}
            columns={[
              {key:'hour',          label:'Period',       cell:'dim'},
              {key:'profit',        label:'Profit $',     align:'center', render:r=><MCNum v={r.profit} fmt="usd"/>},
              {key:'profitPct',     label:'Profit %',     align:'center', render:r=><MCNum v={r.profitPct} fmt="pct"/>},
              {key:'avgProfit',     label:'Avg $',        align:'center', render:r=><MCNum v={r.avgProfit} fmt="usd"/>},
              {key:'grossProfit',   label:'Gross Profit', align:'center', render:r=><MCNum v={r.grossProfit} fmt="usd"/>},
              {key:'grossLoss',     label:'Gross Loss',   align:'center', render:r=><MCNum v={r.grossLoss} fmt="usd"/>},
              {key:'trades',        label:'# Trades',     align:'center', render:r=><MCNum v={r.trades} fmt="int"/>},
              {key:'pctProfitable', label:'% Profitable', align:'right',  render:r=><MCNum v={r.pctProfitable} fmt="pct"/>},
            ]}
            rows={h}
          />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

// ── Settings tab ───────────────────────────────────────────────────────────
const _KVTable = (rows) => (
  <FieldList dense rows={rows.map(r => ({label:r.k, value:String(r.v)}))}/>
);
const SettingsTab = ({report}) => (
  <GridWorkspace key="se">
    <GridItem x={0} y={0} w={12} h={12} minW={7} minH={8}>
      <Pane title="Strategy Inputs" count={report.settings.inputs.length} style={{height:'100%'}}
        foot={{tone:'sub', id:5223, msg:'strategy parameters from the Settings sheet', ms:0}}>
        {_KVTable(report.settings.inputs)}
      </Pane>
    </GridItem>
    <GridItem x={12} y={0} w={12} h={12} minW={7} minH={8}>
      <Pane title="Backtest Settings" count={report.settings.config.length} style={{height:'100%'}}
        foot={{tone:'sub', id:5224, msg:'run configuration · symbol, costs, capital', ms:0}}>
        {_KVTable(report.settings.config)}
      </Pane>
    </GridItem>
  </GridWorkspace>
);

Object.assign(window, { MCNum, MetricTable, StrategyAnalysisTab, GraphsTab, TradesTab, AnalysisTab, PeriodicalTab, SettingsTab });
