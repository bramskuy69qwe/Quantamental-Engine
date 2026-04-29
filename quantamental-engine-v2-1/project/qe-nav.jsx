// QE Navigation
const LOG_MSGS = [
'[20:08:14] No market streams to subscribe — sleeping 10s.',
'[20:08:24] No market streams to subscribe — sleeping 10s.',
'[20:08:34] Market WS connecting (2 streams, attempt 1)',
'[20:08:34] Market WS connected.',
'[20:08:32] Regime: neutral ×1.0 (high)'];


const TopNav = ({ page, setPage }) => {
  const [showLog, setShowLog] = React.useState(false);
  const navItems = ['Dashboard', 'Calculator', 'History', 'Params', 'Analytics', 'Backtest', 'Regime'];

  return (
    <header style={{
      background: QEC.card,
      borderBottom: `1px solid ${QEC.border}`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 10px',

      position: 'sticky',
      top: 0,
      zIndex: 200,
      flexShrink: 0,
      gap: '8px', height: "50px"
    }}>
      {/* Logo + Nav */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, overflow: 'hidden', height: "50px" }}>
        <span style={{
          fontFamily: "'Space Grotesk',sans-serif",
          fontWeight: 800, color: QEC.blue,
          whiteSpace: 'nowrap', flexShrink: 0, fontSize: "15px", letterSpacing: "0px", padding: "0px 0px 1px"
        }}>
          QUANTAMENTAL ENGINE <span style={{ color: QEC.sub, fontWeight: 400, fontSize: "12px" }}>v2.1</span>
        </span>
        <nav style={{ display: 'flex', overflowX: 'auto', scrollbarWidth: 'none', WebkitOverflowScrolling: 'touch', flexShrink: 1 }}>
          {navItems.map((item) => {
            const key = item.toLowerCase();
            const active = page === key;
            return (
              <button key={item} onClick={() => setPage(key)} style={{
                border: 'none', cursor: 'pointer',
                background: active ? QEC.blue : 'transparent',
                color: active ? '#fff' : QEC.sub,
                fontWeight: active ? 700 : 500,
                whiteSpace: 'nowrap', transition: 'background 0.1s, color 0.1s',
                fontFamily: "'Space Grotesk',sans-serif",
                borderBottom: active ? '2px solid #fff' : 'none',
                flexShrink: 0, fontSize: "13px", borderColor: "currentcolor currentcolor rgb(255, 255, 255)", height: "50px", padding: "0px 9px"
              }}>{item}</button>);

          })}
        </nav>
      </div>

      {/* Right controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
        <select style={{
          background: QEC.panel, border: `1px solid ${QEC.border}`, color: QEC.text,
          borderRadius: '4px', padding: '2px 6px', fontSize: '0.68rem', height: '24px', cursor: 'pointer', fontFamily: "\"Space Grotesk\"", width: "150px"
        }}>
          <option>Account 1 (Binance)</option>
        </select>

        <select style={{
          background: QEC.panel, border: `1px solid ${QEC.border}`, color: QEC.text,
          borderRadius: '4px', padding: '2px 6px', fontSize: '0.68rem', height: '24px', cursor: 'pointer', fontFamily: "\"Space Grotesk\"", width: "100px"
        }}>
          <option>Standalone</option>
          <option>Quantower</option>
        </select>

        {/* WS status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.65rem', color: QEC.sub, whiteSpace: 'nowrap' }}>
          <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: QEC.green, display: 'inline-block', flexShrink: 0 }}></span>
          <span style={{ color: QEC.green, fontWeight: 700 }}>WS</span>
          <span style={{ fontFamily: 'JetBrains Mono,monospace' }}>93ms</span>
          <span>1s</span>
        </div>

        {/* Log toggle */}
        <div style={{ position: 'relative' }}>
          <button onClick={() => setShowLog((v) => !v)} style={{
            background: showLog ? QEC.panel : 'transparent',
            border: `1px solid ${showLog ? QEC.borderFoc : QEC.border}`,
            color: showLog ? QEC.text : QEC.sub,
            borderRadius: '4px', padding: '2px 7px', fontSize: '0.62rem',
            cursor: 'pointer', fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600
          }}>LOG</button>

          {showLog &&
          <div onClick={() => setShowLog(false)} style={{
            position: 'fixed', inset: 0, zIndex: 199
          }} />
          }
          {showLog &&
          <div style={{
            position: 'absolute', top: '28px', right: 0,
            background: QEC.card, border: `1px solid ${QEC.border}`,
            borderRadius: '5px', padding: '8px', width: '340px', zIndex: 300,
            fontFamily: 'JetBrains Mono,monospace', fontSize: '0.62rem', color: QEC.sub,
            maxHeight: '110px', overflowY: 'auto',
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)'
          }}>
              {LOG_MSGS.map((m, i) => <div key={i} style={{ marginBottom: '2px', lineHeight: 1.5 }}>{m}</div>)}
            </div>
          }
        </div>
      </div>
    </header>);

};

Object.assign(window, { TopNav });