/* QE v3.0 — Models tab: Overview sub-tab. One tiled workspace that merges the
   aggregate dashboard with the searchable model library (cards + summary on
   top), per the agreed IA. Depends on pages-models-data / -lib + charts/grid. */

const ModelOverview = ({models, onOpen, onNew}) => {
  const withRuns = models.map(m => ({m, run: _latestRun(m), k: _latestRun(m) ? runKpis(_latestRun(m).report) : null})).filter(x => x.k);
  const totalNet = withRuns.reduce((a, x) => a + x.k.net, 0);
  const avgWin = withRuns.length ? withRuns.reduce((a, x) => a + x.k.winPct, 0) / withRuns.length : 0;
  const totalTrades = withRuns.reduce((a, x) => a + x.k.nTrades, 0);
  const ranked = [...withRuns].sort((a, b) => b.k.net - a.k.net);
  const best = ranked[0], worst = ranked[ranked.length - 1];

  return (
    <GridWorkspace key="models-overview">
      {/* Aggregate KPIs — left half */}
      <GridItem x={0} y={0} w={12} h={5} minW={8} minH={4}>
        <Pane title="Library Summary" count={models.length} style={{height:'100%'}}
          foot={{tone:'sub', id:5100, msg:`${withRuns.length} models with imported performance · ${totalTrades} backtested trades`, ms:0}}>
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(132px, 1fr))', gap:7}}>
            <KpiTile label="Total Net P/L" value={_money(totalNet, 0)} sub="latest run / model" color={_plColor(totalNet)}/>
            <KpiTile label="Avg Win %" value={avgWin.toFixed(1) + '%'} sub={`${withRuns.length} models`}/>
            <KpiTile label="Models" value={models.length} sub={`${models.length - withRuns.length} without runs`}/>
            <KpiTile label="Best Model" value={best ? _money(best.k.net, 0) : '—'} sub={best ? best.m.name : '—'} color="var(--qe-green)"/>
            <KpiTile label="Worst Model" value={worst ? _money(worst.k.net, 0) : '—'} sub={worst ? worst.m.name : '—'} color={worst && worst.k.net < 0 ? 'var(--qe-red)' : 'var(--qe-text)'}/>
          </div>
        </Pane>
      </GridItem>

      {/* Leaderboard — right half */}
      <GridItem x={12} y={0} w={12} h={5} minW={8} minH={4}>
        <Pane title="Leaderboard" count={ranked.length} style={{height:'100%'}} bodyStyle={{padding:0}}
          foot={{tone:'sub', id:5110, msg:`ranked by net P/L · latest imported run · ${ranked.length} of ${models.length} scored`, ms:0}}>
          {ranked.length ? (
            <DataList
              selKey="id"
              onClick={(row) => onOpen(models.find(m => m.id === row.id))}
              columns={[
                {key:'rank', label:'#', render:(r,i)=><span className="qe-mono" style={{color:'var(--qe-muted)'}}>{i+1}</span>},
                {key:'name', label:'MODEL', render:r=><span style={{color:'var(--qe-cyan)', fontWeight:700, fontSize:'0.6rem'}}>{r.name}</span>},
                {key:'type', label:'TYPE', render:r=><TypeBadge type={r.type}/>},
                {key:'net',  label:'NET P/L', align:'right', render:r=><span className="qe-mono" style={{color:_plColor(r.net), fontWeight:700}}>{_money(r.net,0)}</span>},
                {key:'pf',   label:'PF', align:'right', render:r=><span className="qe-mono">{r.pf.toFixed(2)}</span>},
                {key:'win',  label:'WIN%', align:'right', render:r=><span className="qe-mono">{r.win}%</span>},
              ]}
              rows={ranked.map(x => ({id:x.m.id, name:x.m.name, type:x.m.type, net:x.k.net, pf:x.k.pf, win:x.k.winPct}))}/>
          ) : (
            <div style={{padding:10, height:'100%', display:'flex', alignItems:'center', justifyContent:'center'}}>
              <EmptyState tone="neutral" glyph="◇" msg="No ranked models yet"/>
            </div>
          )}
        </Pane>
      </GridItem>

      {/* Model library — searchable card grid */}
      <GridItem x={0} y={5} w={24} h={13} minW={12} minH={9}>
        <Pane title="Model Library" count={models.length} style={{height:'100%'}}
          right={<button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onNew}>+ New Model</button>}
          foot={{tone:'sub', id:5120, msg:`${models.length} models · ${withRuns.length} with imported performance · click a card to open`, ms:0}}
          bodyStyle={{padding:0, display:'flex', flexDirection:'column'}}>
          <ModelLibrary models={models} onOpen={onOpen} onNew={onNew} embedded/>
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

Object.assign(window, { ModelOverview });
