/**
 * ONE copy of the in-page control-enumeration logic, shared by the crawler
 * (Phase 1 inventory) and the sweep (Phase 2 actioning). The sweep finds elements
 * by recomputing the same (pane|kind|name|title) key the crawler minted the
 * manifest ids from — selector-recipe drift is impossible by construction.
 *
 * The body populates `out: Map<key, { rec, el }>`.
 */
export const ENUM_BODY = `
  const txt = (el) => (el.textContent || '').replace(/\\s+/g, ' ').trim();
  const norm = (s) => {
    s = (s || '').slice(0, 60).trim();
    if (/[a-zA-Z]/.test(s)) s = s.replace(/\\d[\\d.,%:/]*/g, ' ').replace(/\\s+/g, ' ').trim();
    return s.toLowerCase().slice(0, 40);
  };
  const headTitle = (h) => {
    const clone = h.cloneNode(true);
    clone.querySelectorAll('.qe-badge, button, select, input, .qe-period, .qe-grip, .qe-pane-dots, .qe-pane-refresh, .qe-dot')
      .forEach((n) => n.remove());
    return (clone.textContent || '').replace(/[·⋯…]+/g, ' ').replace(/\\s+/g, ' ').trim();
  };
  const paneOf = (el) => {
    const body = el.closest('.qe-pane-body');
    if (body) {
      const h = body.parentElement && body.parentElement.querySelector('.qe-pane-head');
      if (h) return [norm(headTitle(h)) || '(pane)', headTitle(h).slice(0, 40)];
    }
    const head = el.closest('.qe-pane-head');
    if (head) return [norm(headTitle(head)) || '(pane)', headTitle(head).slice(0, 40)];
    if (el.closest('.qe-page-header')) return ['(page-header)', '(page-header)'];
    if (el.closest('.qe-dl-tools')) return ['(dl-tools)', '(dl-tools)'];
    return ['(chrome-or-page)', '(chrome-or-page)'];
  };
  const nearLabel = (el) => {
    let n = el;
    for (let up = 0; up < 3 && n && n !== document.body; up++) {
      let sib = n.previousElementSibling;
      let hops = 0;
      while (sib && hops < 2) {
        const t = txt(sib);
        if (t && t.length <= 24 && /[a-zA-Z]/.test(t) && !sib.querySelector('input,select,button')) return t;
        sib = sib.previousElementSibling;
        hops++;
      }
      n = n.parentElement;
    }
    return '';
  };
  const out = new Map();
  const push = (el, kind, rawName) => {
    if (el.closest('#qe-e2e-overlay')) return;
    const [pane, paneRaw] = paneOf(el);
    const name = norm(rawName) || '(unnamed)';
    const title = el.getAttribute && (el.getAttribute('title') || undefined);
    const key = pane + '|' + kind + '|' + name + '|' + (title || '');
    const prev = out.get(key);
    if (prev) { prev.rec.instances += 1; return; }
    let selector;
    if (el.id) selector = { strategy: 'id', value: '#' + el.id };
    else if (title) selector = { strategy: 'title', value: title };
    else if (name && name !== '(unnamed)') selector = { strategy: 'text', value: name, scope: paneRaw };
    else selector = { strategy: 'struct', value: kind, scope: paneRaw };
    out.set(key, {
      el,
      rec: {
        pane, paneRaw, kind, name,
        title, elemId: el.id || undefined,
        disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true' || undefined,
        instances: 1, selector,
        sampleText: txt(el).slice(0, 40) || undefined,
      },
    });
  };
  document.querySelectorAll('button').forEach((el) => {
    const kind = el.closest('.qe-tabs') ? 'tab' : el.closest('.qe-period') ? 'period' : 'button';
    push(el, kind, el.getAttribute('title') || txt(el));
  });
  document.querySelectorAll('select').forEach((el) => {
    let lbl = '';
    const wrap = el.closest('label');
    if (wrap) {
      const clone = wrap.cloneNode(true);
      clone.querySelectorAll('select').forEach((n) => n.remove());
      lbl = (clone.textContent || '').trim();
    }
    push(el, 'select', el.getAttribute('title') || lbl || nearLabel(el) || 'select');
  });
  document.querySelectorAll('input, textarea').forEach((el) =>
    push(el, 'input', el.id || el.getAttribute('placeholder') || el.getAttribute('title') || nearLabel(el) || el.type || 'input'));
  // Sort names are CARET-AGNOSTIC: the header's caret glyph is sort STATE
  // (↕ idle / ▲ asc / ▼ desc) — clicking the header mutates its own textContent,
  // so a key carrying the caret can never survive its own action (the 126-error
  // class of run 2-20260728-0501) and would drift the manifest if crawled sorted.
  document.querySelectorAll('th.qe-sort').forEach((el) => push(el, 'sort', txt(el).replace(/[↕▲▼]/g, '')));
  document.querySelectorAll('a[href]').forEach((el) => push(el, 'link', txt(el) || el.getAttribute('href') || 'link'));
`;

/** Full enumeration → list of records (the crawler's snapshot). */
export const SNAPSHOT_SRC = `(() => {\n${ENUM_BODY}\n  return [...out.values()].map((v) => v.rec);\n})()`;

/** Find the live element for a manifest key (pane|kind|name|title). */
export const finderSrc = (key: string): string =>
  `(() => {\n${ENUM_BODY}\n  const hit = out.get(${JSON.stringify(key)});\n  return hit ? hit.el : null;\n})()`;
