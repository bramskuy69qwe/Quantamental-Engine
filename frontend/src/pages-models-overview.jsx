/* v3.0 P7 — Models Overview sub-tab: aggregate KPIs + leaderboard + the
   searchable library, all from the /api/models/overview feed rows
   ({…model, runs_count, latest_run, spark}). `foot` = the feed fetch's
   qeFootState line (passed by ModelsPage — one pipe, one truth). */

const ModelOverview = ({ models, onOpen, onNew, foot }) => {
  const scored = (models || [])
    .map((m) => ({ m, k: mdlLatestKpis(m) }))
    .filter((x) => x.k);
  const totalNet = scored.reduce((a, x) => a + x.k.net, 0);
  const avgWin = scored.length ? scored.reduce((a, x) => a + x.k.winPct, 0) / scored.length : 0;
  const totalTrades = scored.reduce((a, x) => a + x.k.nTrades, 0);
  const ranked = [...scored].sort((a, b) => b.k.net - a.k.net);
  const best = ranked[0], worst = ranked[ranked.length - 1];
  const n = (models || []).length;

  return (
    <GridWorkspace key="models-overview">
      <GridItem x={0} y={0} w={12} h={5} minW={8} minH={4}>
        <Pane title="Library Summary" count={n} style={{ height: '100%' }} foot={foot}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(132px, 1fr))', gap: 7 }}>
            <KpiTile label="Total Net P/L" value={_mdlMoney(totalNet, 0)} sub="latest run / model" color={_mdlPl(totalNet)} />
            <KpiTile label="Avg Win %" value={avgWin.toFixed(1) + '%'} sub={`${scored.length} models`} />
            <KpiTile label="Models" value={n} sub={`${n - scored.length} without runs`} />
            <KpiTile label="Best Model" value={best ? _mdlMoney(best.k.net, 0) : '—'} sub={best ? best.m.name : '—'} color="var(--qe-green)" />
            <KpiTile label="Worst Model" value={worst ? _mdlMoney(worst.k.net, 0) : '—'} sub={worst ? worst.m.name : '—'} color={worst && worst.k.net < 0 ? 'var(--qe-red)' : 'var(--qe-text)'} />
          </div>
          <div className="qe-mono" style={{ marginTop: 6, fontSize: '0.52rem', color: 'var(--qe-muted)' }}>
            {scored.length} with imported performance · {totalTrades} backtested trades
          </div>
        </Pane>
      </GridItem>

      <GridItem x={12} y={0} w={12} h={5} minW={8} minH={4}>
        <Pane title="Leaderboard" count={ranked.length} style={{ height: '100%' }} bodyStyle={{ padding: 0 }} foot={foot}>
          {ranked.length ? (
            <DataList
              selKey="id"
              onClick={(row) => { const m = (models || []).find((x) => x.id === row.id); if (m) onOpen(m); }}
              columns={[
                { key: 'rank', label: '#', sort: false, filter: false, search: false, render: (r, i) => <span className="qe-mono" style={{ color: 'var(--qe-muted)' }}>{i + 1}</span> },
                { key: 'name', label: 'MODEL', filter: false, render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.6rem' }}>{r.name}</span> },
                { key: 'type', label: 'TYPE', filter: true,
                  filterVal: (r) => String(r.type || '—').toUpperCase(),
                  render: (r) => <TypeBadge type={r.type} /> },
                // MODEL is unique-per-row (one row per model) so it can never be
                // a useful facet; TYPE often has a single value. Bucket the net P/L
                // sign — this pane's actual question.
                { key: 'net', label: 'NET P/L', align: 'right',
                  filter: { label: 'RESULT' },
                  filterVal: (r) => (r.net > 0 ? 'PROFIT' : r.net < 0 ? 'LOSS' : 'FLAT'),
                  render: (r) => <span className="qe-mono" style={{ color: _mdlPl(r.net), fontWeight: 700 }}>{_mdlMoney(r.net, 0)}</span> },
                { key: 'pf', label: 'PF', align: 'right', render: (r) => <span className="qe-mono">{r.pf.toFixed(2)}</span> },
                { key: 'win', label: 'WIN%', align: 'right', render: (r) => <span className="qe-mono">{r.win}%</span> },
              ]}
              rows={ranked.map((x) => ({ id: x.m.id, name: x.m.name, type: x.m.type, net: x.k.net, pf: x.k.pf, win: x.k.winPct }))} />
          ) : (
            <div style={{ padding: 10, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <EmptyState tone="neutral" glyph="◇" msg="No ranked models yet"
                hint="Import a backtest report to put a model on the board." />
            </div>
          )}
        </Pane>
      </GridItem>

      <GridItem x={0} y={5} w={24} h={13} minW={12} minH={9}>
        <Pane title="Model Library" count={n} style={{ height: '100%' }}
          right={<button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onNew}>+ New Model</button>}
          foot={foot}
          bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
          <ModelLibrary models={models} onOpen={onOpen} onNew={onNew} embedded />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

Object.assign(window, { ModelOverview });
