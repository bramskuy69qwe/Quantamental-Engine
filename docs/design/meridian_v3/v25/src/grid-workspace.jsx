/* QE v2.5 — GridWorkspace
   Reusable GridStack tiling shell extracted from the Dashboard so every page
   shares one implementation. Wrap a set of <GridItem> children in a
   <GridWorkspace> to get full tiling-window behaviour:
     · step / discrete resizing  — panes snap to a cols × rows cell lattice
     · grid + edge snapping       — edges lock to valid multiplier intervals
     · tiling window management   — float:false ⇒ panes never overlap
     · gapless proportional       — small uniform margin, neighbours flush

   React + GridStack safety: positions are applied IMPERATIVELY in the init
   effect (read from each item's data-* props, written to gs-* attributes just
   before GridStack.init). React therefore never manages the gs-x/gs-y/gs-w/gs-h
   attributes, so content re-renders (toggles, live tickers) and user drags do
   NOT reset the layout. Switch views by mounting a fresh keyed GridWorkspace. */

// A single tile. Position lives in data-* (React-managed, stable); the
// workspace promotes it to gs-* before init. Drag handle is the pane title bar.
const GridItem = ({x, y, w, h, minW, minH, noMove=false, children}) => (
  <div className="grid-stack-item"
       data-gx={x} data-gy={y} data-gw={w} data-gh={h}
       data-gminw={minW} data-gminh={minH} data-gnomove={noMove ? 1 : undefined}>
    <div className="grid-stack-item-content">{children}</div>
  </div>
);

// Shared, persisted lock state so the toggle on ANY workspace locks them all
// consistently (single "lock workspace" affordance across every page).
const WS_LOCK_KEY = 'qe.workspace.locked';
function useWorkspaceLock() {
  const read = () => { try { return localStorage.getItem(WS_LOCK_KEY) === '1'; } catch { return false; } };
  const [locked, setLocked] = React.useState(read);
  React.useEffect(() => {
    const sync = () => setLocked(read());
    window.addEventListener('qe-ws-lock', sync);
    window.addEventListener('storage', sync);
    return () => { window.removeEventListener('qe-ws-lock', sync); window.removeEventListener('storage', sync); };
  }, []);
  const toggle = React.useCallback(() => {
    const next = !read();
    try { localStorage.setItem(WS_LOCK_KEY, next ? '1' : '0'); } catch {}
    window.dispatchEvent(new Event('qe-ws-lock'));
  }, []);
  return [locked, toggle];
}

const GridWorkspace = ({cols=24, rows=24, margin=null, minCell=17, persistId=null, style={}, children}) => {
  const wrapRef = React.useRef(null);
  const elRef   = React.useRef(null);
  const gridRef = React.useRef(null);
  const [locked, toggleLock] = useWorkspaceLock();  // toggleLock unused here; lock lives in TopNav

  React.useEffect(() => {
    if (!window.GridStack || !elRef.current || gridRef.current) return;

    // GridStack's stock CSS only ships column rules up to 12. Generate the
    // width/left rules for an arbitrary column count once, globally.
    const cssId = `gs-${cols}-cols`;
    if (!document.getElementById(cssId)) {
      let css = `.gs-${cols}>.grid-stack-item{width:${100/cols}%}\n`;
      for (let n=1; n<=cols; n++) css += `.gs-${cols}>.grid-stack-item[gs-w="${n}"]{width:${n/cols*100}%}\n`;
      for (let n=0; n<cols;  n++) css += `.gs-${cols}>.grid-stack-item[gs-x="${n}"]{left:${n/cols*100}%}\n`;
      const st = document.createElement('style');
      st.id = cssId; st.textContent = css;
      document.head.appendChild(st);
    }

    // Promote data-* positions to gs-* attributes (imperative ⇒ React-safe).
    [...elRef.current.children].forEach(it => {
      const d = it.dataset;
      if (d.gx   != null) it.setAttribute('gs-x', d.gx);
      if (d.gy   != null) it.setAttribute('gs-y', d.gy);
      if (d.gw   != null) it.setAttribute('gs-w', d.gw);
      if (d.gh   != null) it.setAttribute('gs-h', d.gh);
      if (d.gminw) it.setAttribute('gs-min-w', d.gminw);
      if (d.gminh) it.setAttribute('gs-min-h', d.gminh);
      if (d.gnomove) it.setAttribute('gs-no-move', 'true');
    });

    const wrap = wrapRef.current;
    // Standard pane gutter (token --qe-pane-gap): GridStack insets each tile by
    // GAP/2, so neighbours sit 2×(GAP/2)=GAP apart; the wrap adds GAP/2 padding
    // so the workspace edges match that exact same gutter. Single source = token.
    const GAP = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--qe-pane-gap')) || 4;
    const m = margin != null ? margin : Math.round(GAP / 2);
    const vpad = 2 * m;          // wrap padding eats this much vertical space
    // Row-bands fill the available height (minus edge padding + row margins).
    const cell = () => Math.max(minCell, Math.floor(((wrap.clientHeight || 720) - vpad - m*(rows+1)) / rows));
    const grid = window.GridStack.init({
      column: cols,
      margin: m,                 // half the standard gutter (GAP/2) on every tile edge
      float: false,              // tiling — compact upward, never overlap
      cellHeight: cell(),
      handle: '.qe-pane-head',   // drag from the title bar only
      draggable: { cancel: 'button, input, select, a, textarea, .qe-period, .qe-grip' },
      resizable: { handles: 'n,e,s,w,se,sw,ne,nw' },
      animate: true,
      disableOneColumnMode: true,
    }, elRef.current);
    gridRef.current = grid;

    const ro = new ResizeObserver(() => grid.cellHeight(cell()));
    ro.observe(wrap);

    // Register this grid for save/load so the toolbar (WorkspaceBar) can
    // serialise / restore its layout by id. Capture the initial layout as the
    // "Default" baseline so Load works even before a manual Save.
    if (persistId) {
      window.__qeWorkspaces = window.__qeWorkspaces || {};
      window.__qeWorkspaces[persistId] = grid;
      window.__qeWorkspaceDefaults = window.__qeWorkspaceDefaults || {};
      window.__qeWorkspaceDefaults[persistId] = grid.save(false, false);
    }
    return () => {
      ro.disconnect();
      if (persistId && window.__qeWorkspaces) delete window.__qeWorkspaces[persistId];
      grid.destroy(false); gridRef.current = null;
    };
  }, []);

  // Apply lock state whenever it changes (and once after init). setStatic()
  // freezes drag + resize and strips the resize handles; data-locked drives the
  // cursor / handle CSS cues.
  React.useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    grid.setStatic(locked);
    if (elRef.current) elRef.current.setAttribute('data-locked', locked ? '1' : '0');
  }, [locked]);

  return (
    <div ref={wrapRef} style={{flex:1, minHeight:0, overflowY:'auto', overflowX:'hidden', padding:'calc(var(--qe-pane-gap) / 2)', ...style}}>
      <div className="grid-stack" ref={elRef} style={{width:'100%'}}>
        {children}
      </div>
    </div>
  );
};

Object.assign(window, { GridWorkspace, GridItem, useWorkspaceLock });

// ─────────────────────────────────────────────────────────────────────────
// Workspace save / load — operate on a registered GridWorkspace by persistId.
// Layout is stored in localStorage; Load applies saved positions to the live
// widgets by index (no gs-id needed) inside a batch so it tiles in one pass.
// ─────────────────────────────────────────────────────────────────────────
const WS_LAYOUT_KEY = id => `qe.ws.layout.${id}`;

function qeWorkspaceSave(id) {
  const grid = window.__qeWorkspaces && window.__qeWorkspaces[id];
  if (!grid) return false;
  try {
    localStorage.setItem(WS_LAYOUT_KEY(id), JSON.stringify(grid.save(false, false)));
    return true;
  } catch { return false; }
}

function qeWorkspaceApply(grid, layout) {
  if (!grid || !Array.isArray(layout)) return false;
  const els = grid.getGridItems();
  grid.batchUpdate();
  layout.forEach((n, i) => {
    if (els[i]) grid.update(els[i], { x: n.x, y: n.y, w: n.w, h: n.h });
  });
  grid.commit();
  grid.compact();
  return true;
}

function qeWorkspaceLoad(id) {
  const grid = window.__qeWorkspaces && window.__qeWorkspaces[id];
  if (!grid) return false;
  let raw = null;
  try { raw = localStorage.getItem(WS_LAYOUT_KEY(id)); } catch {}
  if (!raw) return false;
  return qeWorkspaceApply(grid, JSON.parse(raw));
}

function qeWorkspaceReset(id) {
  const grid = window.__qeWorkspaces && window.__qeWorkspaces[id];
  const def  = window.__qeWorkspaceDefaults && window.__qeWorkspaceDefaults[id];
  return qeWorkspaceApply(grid, def);
}

function qeWorkspaceHasSaved(id) {
  try { return !!localStorage.getItem(WS_LAYOUT_KEY(id)); } catch { return false; }
}

// Apply an explicit layout (array of {x,y,w,h} in tile DOM order) to a
// registered workspace — powers the named presets in the WorkspaceBar.
function qeWorkspaceSetLayout(id, layout) {
  const grid = window.__qeWorkspaces && window.__qeWorkspaces[id];
  if (!grid) return false;
  return qeWorkspaceApply(grid, layout);
}

Object.assign(window, { qeWorkspaceSave, qeWorkspaceLoad, qeWorkspaceReset, qeWorkspaceHasSaved, qeWorkspaceSetLayout });
