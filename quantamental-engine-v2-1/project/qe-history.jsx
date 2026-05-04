// QE History Page
const HIST_ROWS = [
  {open:'2026-04-04 15:13:53',close:'2026-04-04 15:16:03',hold:'42s',sym:'JCTUSDT',dir:'LONG', entry:0.0032,exit:0.0032,notional:10.67,pnl:0.17, fees:0.01,mfe:0.30, mae:-0.10,mr:3.0},
  {open:'2026-04-04 14:00:10',close:'2026-04-04 14:00:28',hold:'17s',sym:'JCTUSDT',dir:'LONG', entry:0.0030,exit:0.0030,notional:9.85, pnl:-0.02,fees:0.01,mfe:0.02, mae:-0.03,mr:0.67},
  {open:'2026-04-04 13:58:47',close:'2026-04-04 13:59:51',hold:'21s',sym:'JCTUSDT',dir:'LONG', entry:0.0030,exit:0.0030,notional:16.36,pnl:-0.06,fees:0.02,mfe:0.04, mae:-0.09,mr:0.44},
  {open:'2026-04-05 13:10:53',close:'2026-04-05 13:20:22',hold:'01m 26s',sym:'JCTUSDT',dir:'LONG', entry:0.0031,exit:0.0031,notional:0.96, pnl:0.01, fees:0.01,mfe:0.03, mae:0.00, mr:null},
  {open:'2026-04-05 13:10:53',close:'2026-04-05 13:20:22',hold:'01m 26s',sym:'PUFFERUSDT',dir:'LONG',entry:0.0398,exit:0.0393,notional:1.30, pnl:0.02, fees:0.01,mfe:0.04, mae:-0.02,mr:null},
  {open:'2026-04-04 12:45:15',close:'2026-04-04 12:45:36',hold:'20s',sym:'BTCUSDT',dir:'LONG', entry:66868.9,exit:66877.8,notional:601.9,pnl:0.08, fees:0.60,mfe:0.08, mae:0.00, mr:null},
  {open:'2026-04-04 12:43:58',close:'2026-04-04 12:44:43',hold:'43s',sym:'AIOTUSDT',dir:'LONG', entry:0.0287,exit:0.0288,notional:76.55,pnl:0.11, fees:0.07,mfe:0.15, mae:-0.05,mr:3.0},
  {open:'2026-04-04 12:42:53',close:'2026-04-04 12:43:21',hold:'37s',sym:'AIOTUSDT',dir:'LONG', entry:0.0287,exit:0.0288,notional:49.34,pnl:0.10, fees:0.03,mfe:0.31, mae:-0.07,mr:4.43},
  {open:'2026-04-03 13:10:00',close:'2026-04-03 13:15:05',hold:'05s',sym:'STOUSDT', dir:'SHORT',entry:0.5083,exit:0.0072,notional:130.85,pnl:7.41,fees:0.07,mfe:7.60,mae:-3.58,mr:2.12},
  {open:'2026-04-02 16:36:57',close:'2026-04-02 16:37:46',hold:'48s',sym:'STOUSDT', dir:'SHORT',entry:0.5142,exit:0.5617,notional:36.19,pnl:2.20, fees:0.08,mfe:2.56, mae:-3.01,mr:0.85},
];

const PRE_ROWS = [
  {time:'2026-04-25T12:59:29',ticker:'BTCUSDT',side:'SHORT',avg:'77,521.9500',sl:'78,000.0000',tp:'77,400.0000',atr:1.000,size:0.0017,notional:133.30,rr:0.08,eligible:false},
  {time:'2026-04-25T12:14:43',ticker:'BTCUSDT',side:'SHORT',avg:'77,638.5500',sl:'78,000.0000',tp:'77,400.0000',atr:1.000,size:0.0016,notional:123.60,rr:0.37,eligible:false},
  {time:'2026-04-25T11:58:50',ticker:'BTCUSDT',side:'SHORT',avg:'77,621.0500',sl:'78,000.0000',tp:'77,400.0000',atr:1.000,size:0.0022,notional:168.58,rr:0.51,eligible:false},
];

const TH = ({children,style={}}) => (
  <th style={{color:QEC.sub,fontSize:'0.6rem',fontWeight:700,letterSpacing:'0.07em',textTransform:'uppercase',
    padding:'6px 8px',borderBottom:`1px solid ${QEC.border}`,textAlign:'left',whiteSpace:'nowrap',...style}}>
    {children}
  </th>
);
const TD = ({children,style={}}) => (
  <td style={{padding:'5px 8px',borderBottom:`1px solid ${QEC.border}`,fontFamily:'JetBrains Mono,monospace',
    fontSize:'0.72rem',color:QEC.text,whiteSpace:'nowrap',...style}}>
    {children}
  </td>
);

const PRESETS = ['Last 90 days','Last 30 days','Last 15 days','Last 7 days','Yesterday','Today'];

const HistoryPage = () => {
  const [preset, setPreset]   = React.useState('Last 30 days');
  const [search, setSearch]   = React.useState('');
  const [page, setPage]       = React.useState(1);

  const filtered = HIST_ROWS.filter(r => !search || r.sym.toLowerCase().includes(search.toLowerCase()));

  return (
    <div style={{display:'flex',flexDirection:'column',gap:'6px',padding:'8px'}}>

      {/* Toolbar */}
      <Card p="7px 10px">
        <div style={{display:'flex',alignItems:'center',gap:'6px',flexWrap:'wrap'}}>
          <Btn variant="primary" size="sm" style={{letterSpacing:'0.04em'}}>Export All to Excel</Btn>
          <Btn variant="secondary" size="sm">Refresh Now</Btn>
          <span style={{fontSize:'0.62rem',color:QEC.sub}}>Auto-refreshes every 30s</span>
          <div style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:'4px',fontSize:'0.65rem',color:QEC.sub,fontFamily:'monospace'}}>
            <span style={{color:QEC.text}}>2026-03-26</span>
            <span>→</span>
            <span style={{color:QEC.text}}>2026-04-25</span>
            <Btn variant="ghost" size="sm">Reset</Btn>
          </div>
        </div>
        <div style={{display:'flex',gap:'3px',marginTop:'6px',flexWrap:'wrap'}}>
          {PRESETS.map(p => (
            <button key={p} onClick={() => setPreset(p)} style={{
              padding:'3px 9px',borderRadius:'3px',cursor:'pointer',border:`1px solid ${QEC.border}`,
              background: preset===p ? '#1a3060' : QEC.panel,
              color: preset===p ? '#93c5fd' : QEC.sub,
              fontSize:'0.65rem',fontWeight:600,
            }}>{p}</button>
          ))}
        </div>
      </Card>

      {/* Position History */}
      <Card p="8px 10px">
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'8px',gap:'8px',flexWrap:'wrap'}}>
          <SecLabel style={{marginBottom:0}}>Position History ({HIST_ROWS.length} entries)</SecLabel>
          <input value={search} onChange={e=>setSearch(e.target.value)}
            placeholder="Search..."
            style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:QEC.text,
              borderRadius:'4px',padding:'3px 8px',fontSize:'0.72rem',height:'26px',width:'160px',outline:'none'}}/>
        </div>
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse'}}>
            <thead>
              <tr>
                {['Open','Close','Hold','Symbol','Dir','Entry','Exit','Notional','PnL','TP/SL','Fees','MFE','MAE','M·R','Notes'].map(h =>
                  <TH key={h}>{h}</TH>
                )}
              </tr>
            </thead>
            <tbody>
              {filtered.map((r,i) => (
                <tr key={i}
                  onMouseOver={e => e.currentTarget.querySelectorAll('td').forEach(td => td.style.background=QEC.hover)}
                  onMouseOut={e => e.currentTarget.querySelectorAll('td').forEach(td => td.style.background='transparent')}>
                  <TD style={{color:QEC.sub,fontSize:'0.65rem'}}>{r.open.slice(5)}</TD>
                  <TD style={{color:QEC.sub,fontSize:'0.65rem'}}>{r.close.slice(5)}</TD>
                  <TD style={{color:QEC.sub}}>{r.hold}</TD>
                  <TD style={{color:QEC.blue,fontWeight:700}}>{r.sym}</TD>
                  <TD style={{color:r.dir==='LONG'?QEC.green:QEC.red,fontWeight:700}}>{r.dir}</TD>
                  <TD>{r.entry.toFixed(r.entry>1?2:4)}</TD>
                  <TD>{r.exit.toFixed(r.exit>1?2:4)}</TD>
                  <TD>{r.notional.toFixed(2)}</TD>
                  <TD style={{color:r.pnl>=0?QEC.green:QEC.red,fontWeight:700}}>{r.pnl>=0?'+':''}{r.pnl.toFixed(2)}</TD>
                  <TD style={{color:QEC.sub}}>—</TD>
                  <TD style={{color:QEC.sub}}>{r.fees.toFixed(2)}</TD>
                  <TD style={{color:QEC.green}}>{r.mfe.toFixed(2)}</TD>
                  <TD style={{color:QEC.red}}>{r.mae.toFixed(2)}</TD>
                  <TD style={{color:QEC.text}}>{r.mr!=null?r.mr.toFixed(2):'—'}</TD>
                  <TD style={{color:QEC.blue,fontSize:'0.62rem',cursor:'pointer'}}>+ Add note</TD>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginTop:'8px',flexWrap:'wrap',gap:'6px'}}>
          <span style={{fontSize:'0.65rem',color:QEC.sub}}>Showing 1-{filtered.length} of {HIST_ROWS.length}</span>
          <div style={{display:'flex',gap:'3px'}}>
            {['«','1','2','3','»'].map(p => (
              <button key={p} onClick={()=>{if(!isNaN(p))setPage(+p)}} style={{
                padding:'2px 7px',border:`1px solid ${QEC.border}`,borderRadius:'3px',cursor:'pointer',
                background: page===+p ? QEC.blue : QEC.panel,
                color: page===+p ? '#fff' : QEC.sub,
                fontSize:'0.65rem',fontWeight:600,
              }}>{p}</button>
            ))}
            <select style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:QEC.text,borderRadius:'4px',padding:'2px 6px',fontSize:'0.65rem',height:'24px'}}>
              <option>20 / page</option><option>50 / page</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Pre-trade log */}
      <Card p="8px 10px">
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'8px',gap:'8px',flexWrap:'wrap'}}>
          <SecLabel style={{marginBottom:0}}>Pre-Trade Log ({PRE_ROWS.length} entries)</SecLabel>
          <div style={{display:'flex',gap:'4px'}}>
            <input placeholder="Search ticker..." style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:QEC.text,borderRadius:'4px',padding:'3px 8px',fontSize:'0.72rem',height:'26px',width:'140px',outline:'none'}}/>
            <select style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:QEC.text,borderRadius:'4px',padding:'2px 6px',fontSize:'0.68rem',height:'26px'}}>
              <option>All Sides</option><option>Long</option><option>Short</option>
            </select>
          </div>
        </div>
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse'}}>
            <thead>
              <tr>
                {['Time','Ticker','Side','Avg','SL','TP','ATR C','Size','Notional','R:R','Eligible','Notes'].map(h =>
                  <TH key={h}>{h}</TH>
                )}
              </tr>
            </thead>
            <tbody>
              {PRE_ROWS.map((r,i) => (
                <tr key={i}
                  onMouseOver={e => e.currentTarget.querySelectorAll('td').forEach(td => td.style.background=QEC.hover)}
                  onMouseOut={e => e.currentTarget.querySelectorAll('td').forEach(td => td.style.background='transparent')}>
                  <TD style={{color:QEC.sub,fontSize:'0.65rem'}}>{r.time.slice(11)}</TD>
                  <TD style={{color:QEC.blue,fontWeight:700}}>{r.ticker}</TD>
                  <TD style={{color:r.side==='LONG'?QEC.green:QEC.red,fontWeight:700}}>{r.side}</TD>
                  <TD>{r.avg}</TD>
                  <TD style={{color:QEC.red}}>{r.sl}</TD>
                  <TD style={{color:QEC.green}}>{r.tp}</TD>
                  <TD>{r.atr.toFixed(3)}</TD>
                  <TD>{r.size.toFixed(4)}</TD>
                  <TD>{r.notional.toFixed(2)}</TD>
                  <TD style={{color:QEC.amber}}>{r.rr.toFixed(2)}</TD>
                  <TD>
                    <span style={{display:'inline-block',width:'8px',height:'8px',borderRadius:'50%',background:r.eligible?QEC.green:QEC.red}}></span>
                  </TD>
                  <TD style={{color:QEC.blue,fontSize:'0.62rem',cursor:'pointer'}}>+ Add note</TD>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};

Object.assign(window, {HistoryPage});
