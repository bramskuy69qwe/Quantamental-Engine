/* v3.0 app bundle — precompiled from frontend/src/ by build.mjs.
   DO NOT EDIT: regenerate with `npm run build`. Concatenated modules share
   window globals in load order (classic React.createElement). */

/* ==== primitives.jsx ==== */
const Lbl = ({ children, bracket = false, style = {} }) => /* @__PURE__ */ React.createElement("div", { className: `qe-lbl ${bracket ? "qe-lbl-bracket" : ""}`, style }, children);
const SecLbl = ({ children, count = null, rule = false, right = null, style = {} }) => /* @__PURE__ */ React.createElement("div", { className: "qe-sec-lbl", style: { marginBottom: 6, ...style } }, /* @__PURE__ */ React.createElement("span", null, children), count != null && /* @__PURE__ */ React.createElement("span", { className: "qe-sec-count" }, "\xB7  ", count), rule && /* @__PURE__ */ React.createElement("span", { className: "qe-sec-rule" }), right && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "auto" } }, right));
const KV = ({ l, v, color, span, style = {} }) => /* @__PURE__ */ React.createElement("div", { style: { minWidth: 0, gridColumn: span ? "1 / -1" : "auto", ...style } }, /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--qe-muted)" } }, l), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.6rem", color: color || "var(--qe-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, v));
const Card = ({ children, tight = false, pad = false, hot = false, ticks = false, style = {}, className = "" }) => /* @__PURE__ */ React.createElement("div", { className: [
  "qe-card",
  tight && "qe-card-tight",
  pad && "qe-card-pad",
  hot && "qe-card-hot",
  ticks && "qe-card-ticks",
  className
].filter(Boolean).join(" "), style }, children);
const Stat = ({ label, value, sub, color, size }) => /* @__PURE__ */ React.createElement("div", { className: "qe-stat" }, /* @__PURE__ */ React.createElement(Lbl, null, label), /* @__PURE__ */ React.createElement("div", { className: "qe-stat-val", style: { color, fontSize: size } }, value), sub && /* @__PURE__ */ React.createElement("div", { className: "qe-stat-sub" }, sub));
const HeroNumber = ({ value, ccy = "USDT", size = "var(--qe-fs-3xl)" }) => {
  const s = String(value);
  const [int, dec] = s.includes(".") ? s.split(".") : [s, null];
  return /* @__PURE__ */ React.createElement("div", { className: "qe-hero-val", style: { fontSize: size } }, int, dec && /* @__PURE__ */ React.createElement("span", { className: "qe-hero-cents" }, ".", dec), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.36em", color: "var(--qe-sub)", fontWeight: 600, marginLeft: 8, verticalAlign: "middle" } }, ccy));
};
const Delta = ({ value, pct = null, size = "var(--qe-fs-md)", flat = false }) => {
  const v = parseFloat(value);
  const dir = v > 0 ? "up" : v < 0 ? "dn" : "flat";
  const col = dir === "up" ? "var(--qe-green)" : dir === "dn" ? "var(--qe-red)" : "var(--qe-sub)";
  const sign = v > 0 ? "+" : "";
  return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: col, fontSize: size, fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 4 } }, !flat && (dir === "up" ? /* @__PURE__ */ React.createElement("span", { className: "qe-tick qe-tick-up" }) : dir === "dn" ? /* @__PURE__ */ React.createElement("span", { className: "qe-tick qe-tick-dn" }) : null), sign, value, pct != null && /* @__PURE__ */ React.createElement("span", { style: { color: col, opacity: 0.7, fontWeight: 600 } }, "(", sign, pct, "%)"));
};
const StatusDot = ({ tone = "off", label, value = null, sq = false }) => /* @__PURE__ */ React.createElement("span", { className: `qe-dot ${sq ? "qe-dot-sq" : ""} qe-dot-${tone}` }, /* @__PURE__ */ React.createElement("span", { style: { color: "inherit" } }, label), value != null && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)", fontWeight: 600 } }, value));
const Badge = ({ children, tone = "mute", solid = false, style = {} }) => /* @__PURE__ */ React.createElement("span", { className: `qe-badge ${solid ? "qe-badge-solid" : ""} qe-badge-${tone}`, style }, children);
const REGIME = {
  trend: ["qe-rg-trend", "TREND"],
  chop: ["qe-rg-chop", "CHOP"],
  neut: ["qe-rg-neut", "NEUT"],
  def: ["qe-rg-def", "DEF"],
  panic: ["qe-rg-panic", "PANIC"]
};
const RegimeBadge = ({ tone = "neut", label = null }) => {
  const [cls, dl] = REGIME[tone] || REGIME.neut;
  return /* @__PURE__ */ React.createElement("span", { className: `qe-badge ${cls}` }, label || dl);
};
const PeriodSelector = ({ options, value, onChange, style = {} }) => /* @__PURE__ */ React.createElement("div", { className: "qe-period", style }, options.map((opt) => {
  const [val, lbl] = Array.isArray(opt) ? opt : [opt, opt];
  return /* @__PURE__ */ React.createElement("button", { key: val, className: value === val ? "on" : "", onClick: () => onChange(val) }, lbl);
}));
const Gauge = ({ label, value, max, current, maxLabel, ticks = [], hint = null }) => {
  const pct = Math.min(value / max * 100, 100);
  const tone = pct > 80 ? "err" : pct > 60 ? "warn" : "ok";
  return /* @__PURE__ */ React.createElement("div", { className: "qe-gauge" }, /* @__PURE__ */ React.createElement("div", { className: "qe-gauge-head" }, /* @__PURE__ */ React.createElement(Lbl, null, label), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "var(--qe-fs-md)", fontWeight: 700, color: "var(--qe-text)" } }, current)), /* @__PURE__ */ React.createElement("div", { className: "qe-gauge-track" }, /* @__PURE__ */ React.createElement("div", { className: `qe-gauge-fill ${tone}`, style: { width: pct + "%" } }), ticks.map((t, i) => /* @__PURE__ */ React.createElement("div", { key: i, className: "qe-gauge-tick", style: { left: t / max * 100 + "%" } }))), /* @__PURE__ */ React.createElement("div", { className: "qe-gauge-foot" }, /* @__PURE__ */ React.createElement("span", null, hint || `0`), /* @__PURE__ */ React.createElement("span", null, maxLabel)));
};
const EmptyState = ({ tone = "neutral", glyph = "\u2205", msg, hint, cta = null, fill = false }) => /* @__PURE__ */ React.createElement("div", { className: `qe-empty ${tone === "neutral" ? "" : tone}${fill ? " fill" : ""}` }, /* @__PURE__ */ React.createElement("div", { className: "qe-empty-glyph" }, glyph), /* @__PURE__ */ React.createElement("div", { className: "qe-empty-msg" }, msg), hint && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "var(--qe-fs-xs)", color: "var(--qe-muted)", textAlign: "center" } }, hint), cta && /* @__PURE__ */ React.createElement("div", { className: "qe-empty-cta" }, cta));
const HeatBar = ({ mfe, mae, pnl = null, w = 84, h = 12 }) => {
  if (mfe == null && mae == null) return /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014");
  const f = +mfe || 0, a = +mae || 0, p = pnl == null ? null : +pnl || 0;
  const span = Math.max(Math.abs(f), Math.abs(a), Math.abs(p == null ? 0 : p)) || 1;
  const half = (v) => v / span * 50;
  const maeW = Math.max(1.5, -half(Math.min(0, a)));
  const mfeW = Math.max(1.5, half(Math.max(0, f)));
  const exit = p == null ? null : 50 + half(p);
  const title = `MFE +${Math.abs(f).toFixed(2)} / MAE ${a.toFixed(2)}` + (p == null ? "" : ` \xB7 exit ${p >= 0 ? "+" : ""}${p.toFixed(2)}`);
  return /* @__PURE__ */ React.createElement("div", { title, style: {
    position: "relative",
    width: w,
    height: h,
    background: "var(--qe-panel)",
    border: "1px solid var(--qe-faint)",
    flexShrink: 0,
    display: "inline-block",
    verticalAlign: "middle"
  } }, /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "var(--qe-line-2)" } }), /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", top: 2, bottom: 2, right: "50%", width: maeW + "%", background: "var(--qe-red)", opacity: 0.42 } }), /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", top: 2, bottom: 2, left: "50%", width: mfeW + "%", background: "var(--qe-green)", opacity: 0.42 } }), exit != null && /* @__PURE__ */ React.createElement("div", { style: {
    position: "absolute",
    top: -1,
    bottom: -1,
    left: exit + "%",
    width: 2,
    marginLeft: -1,
    background: p >= 0 ? "var(--qe-green)" : "var(--qe-red)"
  } }));
};
const HeatBarLabelled = ({ mfe, mae, pnl = null, pct = null, h = 16 }) => /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: {
  display: "flex",
  justifyContent: "space-between",
  fontFamily: "var(--qe-mono)",
  fontSize: "0.5rem",
  letterSpacing: "0.06em",
  marginBottom: 3
} }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)" } }, "MAE ", mae == null ? "\u2014" : (+mae).toFixed(2)), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "ENTRY"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, "MFE ", mfe == null ? "\u2014" : "+" + Math.abs(+mfe).toFixed(2))), /* @__PURE__ */ React.createElement(HeatBar, { mfe, mae, pnl, w: "100%", h }), pnl != null && /* @__PURE__ */ React.createElement("div", { style: {
  textAlign: "center",
  fontFamily: "var(--qe-mono)",
  fontSize: "0.5rem",
  color: +pnl >= 0 ? "var(--qe-green)" : "var(--qe-red)",
  marginTop: 3
} }, "\u25B2 exit ", +pnl >= 0 ? "+" : "", (+pnl).toFixed(2), pct == null ? "" : ` (${+pct >= 0 ? "+" : ""}${(+pct).toFixed(2)}%)`));
Object.assign(window, { HeatBar, HeatBarLabelled });
const Tabs = ({ tabs, value, onChange, style = null }) => /* @__PURE__ */ React.createElement("div", { className: "qe-tabs", style: style || void 0 }, tabs.map(([id, lbl, count]) => /* @__PURE__ */ React.createElement("button", { key: id, className: value === id ? "on" : "", onClick: () => onChange(id) }, lbl, count != null && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", marginLeft: 5, fontFamily: "var(--qe-mono)" } }, count))));
const TabStrip = ({ tabs, value, onChange, right = null, style = {} }) => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "stretch", padding: "0 4px", background: "var(--qe-page)", borderBottom: "1px solid var(--qe-line)", flexShrink: 0, ...style } }, /* @__PURE__ */ React.createElement("div", { className: "qe-hscroll", style: { flex: 1, minWidth: 0, display: "flex" } }, /* @__PURE__ */ React.createElement(Tabs, { value, onChange, tabs, style: { minWidth: "max-content", flex: 1 } })), right);
Object.assign(window, { TabStrip });
const Strip = ({ items, dense = false, style = {} }) => /* @__PURE__ */ React.createElement("div", { className: "qe-strip", style }, items.map((it, i) => /* @__PURE__ */ React.createElement("div", { key: i, className: "qe-strip-cell", style: dense ? { padding: "3px 8px" } : {} }, /* @__PURE__ */ React.createElement("span", { className: "lbl" }, it.label), /* @__PURE__ */ React.createElement("span", { className: "val", style: { color: it.color } }, it.value))));
const FlashCell = ({ value, formatter = String, style = {}, className = "" }) => {
  const prev = React.useRef(value);
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!ref.current) return;
    if (value > prev.current) {
      ref.current.classList.remove("qe-flash-dn", "qe-flash-up");
      void ref.current.offsetWidth;
      ref.current.classList.add("qe-flash-up");
    } else if (value < prev.current) {
      ref.current.classList.remove("qe-flash-up", "qe-flash-dn");
      void ref.current.offsetWidth;
      ref.current.classList.add("qe-flash-dn");
    }
    prev.current = value;
  }, [value]);
  return /* @__PURE__ */ React.createElement("span", { ref, className: `qe-mono ${className}`, style }, formatter(value));
};
const LiveValue = ({ id, value, format = String, tone = "auto", stale = false, style = {}, className = "" }) => {
  const prev = React.useRef(value);
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!ref.current) return;
    if (tone === "up") {
      ref.current.classList.remove("qe-flash-dn");
      void ref.current.offsetWidth;
      ref.current.classList.add("qe-flash-up");
    } else if (tone === "dn") {
      ref.current.classList.remove("qe-flash-up");
      void ref.current.offsetWidth;
      ref.current.classList.add("qe-flash-dn");
    } else {
      const pv = parseFloat(prev.current);
      const cv = parseFloat(value);
      if (!isNaN(pv) && !isNaN(cv)) {
        if (cv > pv) {
          ref.current.classList.remove("qe-flash-dn", "qe-flash-up");
          void ref.current.offsetWidth;
          ref.current.classList.add("qe-flash-up");
        } else if (cv < pv) {
          ref.current.classList.remove("qe-flash-up", "qe-flash-dn");
          void ref.current.offsetWidth;
          ref.current.classList.add("qe-flash-dn");
        }
      }
    }
    prev.current = value;
  }, [value, tone]);
  return /* @__PURE__ */ React.createElement(
    "span",
    {
      ref,
      "data-live-id": id,
      className: `qe-mono qe-live-value ${stale ? "qe-live-stale" : ""} ${className}`,
      style
    },
    format(value)
  );
};
const LiveClock = ({ id = "clock", style = {}, format = null }) => {
  const [t, setT] = React.useState(() => /* @__PURE__ */ new Date());
  React.useEffect(() => {
    const i = setInterval(() => setT(/* @__PURE__ */ new Date()), 1e3);
    return () => clearInterval(i);
  }, []);
  const s = format ? format(t) : t.toISOString().slice(0, 10) + " " + t.toISOString().slice(11, 19) + " UTC";
  return /* @__PURE__ */ React.createElement(LiveValue, { id, value: s, format: (x) => x, style });
};
const ASCII_SPARK = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588";
const asciiSpark = (vals) => {
  if (!(vals == null ? void 0 : vals.length)) return "";
  const min = Math.min(...vals), max = Math.max(...vals);
  const rng = max - min || 1;
  return vals.map((v) => ASCII_SPARK[Math.floor((v - min) / rng * (ASCII_SPARK.length - 1))]).join("");
};
const RELOAD_MS = 620;
const FOOT_H = 17;
const ReloadIconSVG = () => /* @__PURE__ */ React.createElement("svg", { className: "qe-reload-svg", viewBox: "-0.1 1.2 24.2 24.2", fill: "none", "aria-hidden": "true", focusable: "false" }, /* @__PURE__ */ React.createElement("path", { d: "M19.86 9.8 A8.6 8.6 0 1 1 10.51 4.83", stroke: "currentColor", strokeWidth: "2.7", strokeLinecap: "round" }), /* @__PURE__ */ React.createElement("path", { d: "M11.2 1.4 L17.4 5.2 L11.2 9 Z", fill: "currentColor" }));
const useSpinFrame = (frames, active = true, ms = 110) => {
  const [i, setI] = React.useState(0);
  React.useEffect(() => {
    if (!active) {
      setI(0);
      return;
    }
    const reduce = typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setI(0);
      return;
    }
    let k = 0;
    const iv = setInterval(() => {
      k = (k + 1) % frames.length;
      setI(k);
    }, ms);
    return () => clearInterval(iv);
  }, [active, ms, frames]);
  return frames[i] || frames[0];
};
const SQUARE_POS = { TL: [1, 1], TR: [6, 1], BR: [6, 6], BL: [1, 6] };
const SQUARE_EDGES = [["TL", "TR"], ["TR", "BR"], ["BR", "BL"], ["BL", "TL"]];
const BrailleSquares = ({ active = true, style = {} }) => {
  const pair = useSpinFrame(SQUARE_EDGES, active);
  return /* @__PURE__ */ React.createElement("svg", { className: "qe-braille-sq", viewBox: "0 0 10 10", fill: "currentColor", "aria-hidden": "true", style }, pair.map((k) => {
    const [x, y] = SQUARE_POS[k];
    return /* @__PURE__ */ React.createElement("rect", { key: k, x, y, width: "3", height: "3" });
  }));
};
const ReloadGlyph = ({ spinning = false, size = null, style = {} }) => /* @__PURE__ */ React.createElement(
  "span",
  {
    className: "qe-refresh-ic",
    "aria-hidden": "true",
    style: size ? { fontSize: size, ...style } : style
  },
  spinning ? /* @__PURE__ */ React.createElement(BrailleSquares, null) : /* @__PURE__ */ React.createElement(ReloadIconSVG, null)
);
const Spinner = ({ size = "0.9rem", label = null, color = "var(--qe-cyan)", gap = 7, style = {} }) => /* @__PURE__ */ React.createElement(
  "span",
  {
    className: "qe-spinner",
    role: "status",
    "aria-label": label || "loading",
    style: { display: "inline-flex", alignItems: "center", gap, color, fontFamily: "var(--qe-mono)", ...style }
  },
  /* @__PURE__ */ React.createElement(BrailleSquares, { style: { fontSize: size } }),
  label && /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.58rem", letterSpacing: "0.18em", textTransform: "uppercase", lineHeight: 1 } }, label)
);
const RefreshButton = ({ onClick, spinning = false, tone = "default", title = "Reload pane", size = 16, style = {} }) => {
  const color = tone === "err" ? "var(--qe-red)" : tone === "warn" ? "var(--qe-amber)" : "var(--qe-muted)";
  return /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: `qe-refresh${spinning ? " on" : ""}${tone === "err" ? " err" : ""}`,
      title,
      "aria-label": title,
      onMouseDown: (e) => e.stopPropagation(),
      onClick: (e) => {
        e.stopPropagation();
        if (onClick) onClick(e);
      },
      style: { width: size, height: size, color, ...style }
    },
    /* @__PURE__ */ React.createElement(ReloadGlyph, { spinning })
  );
};
const PaneReloadBody = ({ hasFoot = false }) => /* @__PURE__ */ React.createElement("div", { className: "qe-pane-refresh", style: { bottom: hasFoot ? FOOT_H : 0 } }, /* @__PURE__ */ React.createElement(ReloadGlyph, { spinning: true, size: "1rem" }), /* @__PURE__ */ React.createElement("span", null, "RELOADING"));
class PaneErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, msg: null };
  }
  static getDerivedStateFromError(err) {
    return { hasError: true, msg: err && err.message ? err.message : String(err) };
  }
  componentDidCatch(err, info) {
    if (this.props.onError) this.props.onError(err, info);
  }
  render() {
    if (this.state.hasError) {
      return /* @__PURE__ */ React.createElement(
        EmptyState,
        {
          fill: true,
          tone: "err",
          glyph: "\u26A0",
          msg: `${this.props.title || "Pane"} failed to render`,
          hint: this.state.msg,
          cta: /* @__PURE__ */ React.createElement("button", { type: "button", className: "qe-btn qe-btn-sm qe-btn-danger", onClick: this.props.onReload }, /* @__PURE__ */ React.createElement("span", { className: "qe-refresh-ic", style: { marginRight: 5, fontSize: "0.92em" } }, /* @__PURE__ */ React.createElement(ReloadIconSVG, null)), " Reload")
        }
      );
    }
    return this.props.children;
  }
}
const PaneHead = ({ title, count = null, right = null, hot = false, tag = null, onRefresh = null, refreshing = false, refreshTone = "default" }) => {
  const dots = /* @__PURE__ */ React.createElement("span", { className: "qe-pane-dots", style: { color: "var(--qe-muted)", fontSize: "0.66rem", letterSpacing: "0.1em", cursor: "pointer" } }, "\xB7\xB7\xB7");
  return /* @__PURE__ */ React.createElement("div", { className: "qe-pane-head", style: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "2px 6px",
    background: hot ? "color-mix(in srgb, var(--qe-cyan) 4%, transparent)" : "var(--qe-panel)",
    borderBottom: "1px solid var(--qe-line)",
    height: 20,
    flexShrink: 0
  } }, /* @__PURE__ */ React.createElement("span", { style: {
    fontFamily: "var(--qe-mono)",
    fontSize: "0.56rem",
    fontWeight: 700,
    letterSpacing: "0.14em",
    textTransform: "uppercase",
    flexShrink: 0,
    color: hot ? "var(--qe-cyan)" : "var(--qe-text-dim)"
  } }, title), count != null && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.54rem", color: "var(--qe-muted)", flexShrink: 0 } }, "\xB7  ", count), tag && /* @__PURE__ */ React.createElement(Badge, { tone: "info" }, tag), onRefresh ? (
    // Tile pane: title-bar info sits beside the title; the right edge holds
    // ONLY the reload + ··· controls.
    /* @__PURE__ */ React.createElement(React.Fragment, null, right && /* @__PURE__ */ React.createElement("span", { className: "qe-pane-info", style: { display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 } }, right), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement(RefreshButton, { onClick: onRefresh, spinning: refreshing, tone: refreshTone }), dots)
  ) : (
    // Legacy / modal use (e.g. ModalShell close ✕): keep right-slot on the right.
    /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), right, dots)
  ));
};
const _ptJson = async (url) => {
  let r;
  try {
    r = await fetch(url, { headers: { Accept: "application/json" } });
  } catch (e) {
    const err = new Error(url + " unreachable");
    err.status = 0;
    throw err;
  }
  if (!r.ok) {
    const err = new Error(url + " " + r.status);
    err.status = r.status;
    throw err;
  }
  try {
    return await r.json();
  } catch (e) {
    const err = new Error(url + " corrupt response");
    err.corrupt = true;
    throw err;
  }
};
const qeFootCause = (err) => {
  if (!err) return "unknown error";
  if (err.corrupt) return "corrupt response";
  const s = err.status;
  if (s === 404) return "endpoint not found (404)";
  if (s === 401 || s === 403) return `unauthorized (${s})`;
  if (s >= 500) return `server error (${s})`;
  if (s == null || s === 0) return "no network \u2014 engine unreachable";
  return `request failed (${s})`;
};
const qeFootState = ({ loading, err, corrupt, status, hasData, empty, ms, retrying }) => {
  const e = err || corrupt != null || status != null ? {
    corrupt: (err && err.corrupt) != null ? err.corrupt : corrupt,
    status: (err && err.status) != null ? err.status : status
  } : null;
  if (loading && !hasData) {
    return { tone: "sub", busy: true, msg: e ? "reconnecting\u2026" : "loading\u2026" };
  }
  if (e) {
    if (hasData) {
      const suffix = retrying ? " \xB7 retrying" : "";
      if (e.corrupt) return { tone: "warn", msg: `response corrupt \xB7 showing last data${suffix}` };
      if (e.status == null || e.status === 0) return { tone: "warn", msg: `no network \xB7 showing last data${suffix}` };
      return { tone: "warn", msg: `${qeFootCause(e)} \xB7 showing last data${suffix}` };
    }
    return { tone: "err", msg: qeFootCause(e) };
  }
  if (ms != null && ms > 500) return { tone: "warn", msg: `delayed [${Math.round(ms)}ms]` };
  return { tone: "ok", msg: `connected${ms != null ? ` [${Math.round(ms)}ms]` : ""}` };
};
const PaneFoot = ({ tone = "info", id, msg, ms, busy = false }) => {
  const toneColors = {
    ok: { fg: "var(--qe-green)", bg: "rgba(0,255,127,0.06)", glyph: "\u2713" },
    info: { fg: "var(--qe-cyan)", bg: "rgba(0,231,255,0.05)", glyph: "i" },
    warn: { fg: "var(--qe-amber)", bg: "rgba(255,174,0,0.06)", glyph: "!" },
    err: { fg: "var(--qe-red)", bg: "rgba(255,45,74,0.06)", glyph: "\u2717" },
    sub: { fg: "var(--qe-sub)", bg: "transparent", glyph: "\xB7" }
  };
  const t = toneColors[tone] || toneColors.info;
  return /* @__PURE__ */ React.createElement("div", { style: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    flexShrink: 0,
    borderTop: "1px solid var(--qe-line)",
    background: t.bg,
    padding: "0 6px",
    height: 16,
    fontFamily: "var(--qe-mono)",
    fontSize: "0.54rem",
    lineHeight: 1
  } }, busy ? /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", justifyContent: "center", width: 11, height: 11, color: t.fg } }, /* @__PURE__ */ React.createElement(BrailleSquares, { style: { fontSize: "0.62rem" } })) : /* @__PURE__ */ React.createElement("span", { style: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 11,
    height: 11,
    border: `1px solid ${t.fg}`,
    color: t.fg,
    fontWeight: 700,
    fontSize: "0.52rem"
  } }, t.glyph), id != null && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "[", String(id).padStart(5, "0"), "]"), /* @__PURE__ */ React.createElement("span", { style: { color: t.fg, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 } }, msg), ms != null && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, ms, "ms"));
};
const Pane = ({ title, count, right, hot, tag, foot = null, resizable = true, onRefresh = null, children, bodyStyle = {}, style = {} }) => {
  const [nonce, setNonce] = React.useState(0);
  const [refreshing, setRefresh] = React.useState(false);
  const [errored, setErrored] = React.useState(false);
  const [reloadFoot, setRFoot] = React.useState(null);
  const timer = React.useRef(null);
  const footRef = React.useRef(foot);
  footRef.current = foot;
  React.useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const footKey = foot ? `${foot.tone}|${foot.id}|${foot.msg}|${foot.ms}` : "";
  const lastFootKey = React.useRef(footKey);
  React.useEffect(() => {
    if (footKey !== lastFootKey.current) {
      lastFootKey.current = footKey;
      setRFoot(null);
    }
  }, [footKey]);
  const doRefresh = React.useCallback(() => {
    setRefresh(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const f = footRef.current;
      setErrored(false);
      if (f) setRFoot({ tone: "ok", msg: onRefresh ? "reloaded \xB7 refetched" : "reloaded \xB7 body remounted" });
      setNonce((n) => n + 1);
      setRefresh(false);
      if (onRefresh) {
        try {
          onRefresh();
        } catch (e) {
        }
      }
    }, RELOAD_MS);
  }, [onRefresh]);
  let effFoot = null;
  if (foot) {
    if (refreshing) effFoot = { tone: "info", busy: true, id: (reloadFoot || foot).id, msg: "reloading\u2026", ms: null };
    else if (errored) effFoot = { tone: "err", id: foot.id, msg: `${title || "pane"} render failed \xB7 reload to recover`, ms: foot.ms };
    else effFoot = reloadFoot || foot;
  }
  return /* @__PURE__ */ React.createElement("div", { style: {
    display: "flex",
    flexDirection: "column",
    background: "var(--qe-card)",
    border: "1px solid var(--qe-line)",
    minWidth: 0,
    minHeight: 0,
    position: "relative",
    ...style
  } }, /* @__PURE__ */ React.createElement(
    PaneHead,
    {
      title,
      count,
      right,
      hot,
      tag,
      onRefresh: doRefresh,
      refreshing,
      refreshTone: errored ? "err" : "default"
    }
  ), /* @__PURE__ */ React.createElement("div", { className: "qe-pane-body", style: { flex: 1, minHeight: 0, padding: "5px 7px", overflow: "auto", position: "relative", ...bodyStyle } }, /* @__PURE__ */ React.createElement(PaneErrorBoundary, { key: nonce, title, onReload: doRefresh, onError: () => setErrored(true) }, children)), effFoot && /* @__PURE__ */ React.createElement(PaneFoot, { ...effFoot }), refreshing && /* @__PURE__ */ React.createElement(PaneReloadBody, { hasFoot: !!effFoot }), resizable && /* @__PURE__ */ React.createElement("span", { className: "qe-grip", title: "resize", style: { pointerEvents: "none" } }));
};
const ModelDialog = ({ title, onClose, width = 460, children, footer, foot = null, hot = true }) => /* @__PURE__ */ React.createElement(
  "div",
  {
    style: { position: "absolute", inset: 0, zIndex: 50, background: "rgba(0,0,0,0.66)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 },
    onClick: onClose
  },
  /* @__PURE__ */ React.createElement("div", { onClick: (e) => e.stopPropagation(), style: {
    width,
    maxWidth: "100%",
    maxHeight: "100%",
    display: "flex",
    flexDirection: "column",
    position: "relative",
    background: "var(--qe-card)",
    border: "1px solid var(--qe-line-2)",
    boxShadow: "0 24px 70px -16px var(--qe-bg)"
  } }, /* @__PURE__ */ React.createElement(
    PaneHead,
    {
      title,
      hot,
      right: /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: onClose,
          title: "Close",
          style: {
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 14,
            height: 14,
            border: "1px solid var(--qe-faint)",
            background: "transparent",
            color: "var(--qe-muted)",
            cursor: "pointer",
            fontSize: "0.7rem",
            lineHeight: 1,
            padding: 0
          },
          onMouseEnter: (e) => {
            e.currentTarget.style.color = "var(--qe-red)";
            e.currentTarget.style.borderColor = "var(--qe-red)";
          },
          onMouseLeave: (e) => {
            e.currentTarget.style.color = "var(--qe-muted)";
            e.currentTarget.style.borderColor = "var(--qe-faint)";
          }
        },
        "\u2715"
      )
    }
  ), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, overflow: "auto", padding: 10 } }, children), foot && /* @__PURE__ */ React.createElement(PaneFoot, { ...foot }), footer && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6, padding: "7px 9px", borderTop: "1px solid var(--qe-line)", background: "var(--qe-panel)", flexShrink: 0 } }, footer), /* @__PURE__ */ React.createElement("span", { className: "qe-grip", style: { pointerEvents: "none" } }))
);
const DL_AUTO_MIN = 1;
const DL_AUTO_MIN_FACET = 1;
const DL_FACET_AUTO_MAX = 6;
const DL_FACET_AUTO_ABS = 4;
const DL_FACET_CARD_RATIO = 0.6;
const DL_FACET_FORCE_MAX = 16;
const DL_VALUE_MAXLEN = 16;
const DL_TOOLS_H = 28;
const _dlText = (v) => v == null ? "" : typeof v === "string" ? v : String(v);
const _dlNum = (v) => {
  if (typeof v === "number") return v;
  if (typeof v !== "string") return NaN;
  let s = v.trim();
  if (!s) return NaN;
  s = s.replace(/[$\s]/g, "").replace(/,/g, "").replace(/%$/, "").replace(/[a-zA-Z]+$/, "");
  return /^[-+]?\d*\.?\d+$/.test(s) ? parseFloat(s) : NaN;
};
const _dlDeriveFacets = (columns, rows) => {
  const out = [];
  columns.forEach((col, ci) => {
    if (col.filter === false) return;
    const get = col.filterVal ? col.filterVal : col.key != null ? (r) => r[col.key] : null;
    if (!get) return;
    const forced = col.filter === true || col.filter && typeof col.filter === "object";
    const counts = /* @__PURE__ */ new Map();
    let defined = 0, numericN = 0, tooLong = false, hasObj = false;
    for (const row of rows) {
      const raw = get(row);
      if (raw == null || raw === "") continue;
      if (typeof raw === "object") {
        hasObj = true;
        break;
      }
      defined++;
      const s = String(raw);
      if (s.length > DL_VALUE_MAXLEN) tooLong = true;
      if (Number.isFinite(_dlNum(s))) numericN++;
      counts.set(s, (counts.get(s) || 0) + 1);
    }
    if (hasObj || defined === 0) return;
    if (tooLong && !forced) return;
    const distinct = [...counts.keys()];
    if (distinct.length < 2 && !forced) return;
    if (forced) {
      if (distinct.length > DL_FACET_FORCE_MAX) return;
    } else {
      if (numericN / defined >= 0.7) return;
      if (distinct.length > DL_FACET_AUTO_MAX) return;
      if (distinct.length > DL_FACET_AUTO_ABS && distinct.length > rows.length * DL_FACET_CARD_RATIO) return;
      if (defined / rows.length < 0.5) return;
    }
    const allNum = distinct.every((d) => Number.isFinite(_dlNum(d)));
    distinct.sort(allNum ? (a, b) => _dlNum(a) - _dlNum(b) : (a, b) => a.localeCompare(b));
    const opts = col.filter && typeof col.filter === "object" && Array.isArray(col.filter.options) ? col.filter.options.map(String) : distinct;
    out.push({
      key: col.key != null ? col.key : typeof col.label === "string" ? col.label : "facet" + ci,
      label: col.filter && col.filter.label || (typeof col.label === "string" ? col.label : String(col.key || "").toUpperCase()),
      options: opts,
      get
    });
  });
  return out;
};
const DataList = ({ columns, rows, dense = true, onClick, selKey = "id", selected = null, emptyMsg = "no rows", summary = null, tools }) => {
  const allRows = rows || [];
  const [q, setQ] = React.useState("");
  const [sort, setSort] = React.useState({ key: null, dir: null });
  const [facetSel, setFacet] = React.useState({});
  const toolsObj = tools && typeof tools === "object" ? tools : null;
  const facetsAll = React.useMemo(() => _dlDeriveFacets(columns, allRows), [columns, allRows]);
  const autoOn = allRows.length >= DL_AUTO_MIN || allRows.length >= DL_AUTO_MIN_FACET && facetsAll.length > 0;
  const toolsOn = tools === false ? false : tools === true || toolsObj ? true : autoOn;
  const showSearch = toolsOn && (!toolsObj || toolsObj.search !== false);
  const showSort = toolsOn && (!toolsObj || toolsObj.sort !== false);
  const showFilter = toolsOn && (!toolsObj || toolsObj.filter !== false);
  const facets = showFilter ? facetsAll : [];
  const presentKeys = React.useMemo(() => {
    const s = /* @__PURE__ */ new Set();
    columns.forEach((c) => {
      if (c.key != null && allRows.some((r) => r[c.key] != null)) s.add(c.key);
    });
    return s;
  }, [columns, allRows]);
  const colId = (col) => col.key != null ? col.key : typeof col.label === "string" ? col.label : null;
  const sortableOf = (col) => showSort && col.sort !== false && (col.sortVal || presentKeys.has(col.key));
  let view = allRows.map((row, _i) => ({ row, _i }));
  if (showFilter) {
    for (const f of facets) {
      const sel = facetSel[f.key];
      if (sel == null || sel === "") continue;
      view = view.filter(({ row }) => _dlText(f.get(row)) === sel);
    }
  }
  const needle = showSearch ? q.trim().toLowerCase() : "";
  if (needle) {
    const scols = columns.filter((c) => c.search !== false && (c.searchVal || presentKeys.has(c.key)));
    view = view.filter(({ row }) => scols.some((c) => _dlText(c.searchVal ? c.searchVal(row) : row[c.key]).toLowerCase().includes(needle)));
  }
  if (showSort && sort.key) {
    const col = columns.find((c) => colId(c) === sort.key);
    if (col) {
      const get = (w) => col.sortVal ? col.sortVal(w.row) : w.row[col.key];
      const raw = view.map(get);
      const numeric = raw.some((v) => Number.isFinite(_dlNum(v))) && raw.every((v) => v == null || v === "" || Number.isFinite(_dlNum(v)));
      const sgn = sort.dir === "desc" ? -1 : 1;
      view = [...view].sort((wa, wb) => {
        const a = get(wa), b = get(wb);
        const ae = a == null || a === "", be = b == null || b === "";
        if (ae && be) return 0;
        if (ae) return 1;
        if (be) return -1;
        if (numeric) return (_dlNum(a) - _dlNum(b)) * sgn;
        return _dlText(a).localeCompare(_dlText(b)) * sgn;
      });
    }
  }
  if (!allRows.length) {
    return /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: emptyMsg });
  }
  const fixed = columns.some((c) => c.width);
  const anyActive = !!needle || Object.values(facetSel).some((v) => v) || !!sort.key;
  const clearAll = () => {
    setQ("");
    setFacet({});
    setSort({ key: null, dir: null });
  };
  const cycleSort = (id) => setSort((s) => s.key === id ? s.dir === "asc" ? { key: id, dir: "desc" } : { key: null, dir: null } : { key: id, dir: "asc" });
  return /* @__PURE__ */ React.createElement(React.Fragment, null, toolsOn && /* @__PURE__ */ React.createElement("div", { className: "qe-dl-tools" }, showSearch && /* @__PURE__ */ React.createElement("div", { className: "qe-dl-search" }, /* @__PURE__ */ React.createElement("span", { className: "qe-dl-search-ic", "aria-hidden": "true" }, "\u2315"), /* @__PURE__ */ React.createElement(
    "input",
    {
      value: q,
      onChange: (e) => setQ(e.target.value),
      placeholder: "search\u2026",
      spellCheck: false,
      onKeyDown: (e) => {
        if (e.key === "Escape") {
          setQ("");
          e.currentTarget.blur();
        }
      }
    }
  ), q && /* @__PURE__ */ React.createElement("button", { type: "button", title: "clear search", onClick: () => setQ("") }, "\u2715")), showFilter && facets.map((f) => {
    var _a;
    return /* @__PURE__ */ React.createElement("label", { key: f.key, className: "qe-dl-facet" }, /* @__PURE__ */ React.createElement("span", null, f.label), /* @__PURE__ */ React.createElement(
      "select",
      {
        className: "qe-input qe-select",
        value: (_a = facetSel[f.key]) != null ? _a : "",
        onChange: (e) => setFacet((s) => ({ ...s, [f.key]: e.target.value }))
      },
      /* @__PURE__ */ React.createElement("option", { value: "" }, "ALL"),
      f.options.map((o) => /* @__PURE__ */ React.createElement("option", { key: o, value: o }, o))
    ));
  }), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("span", { className: "qe-dl-count" }, view.length === allRows.length ? allRows.length : `${view.length} / ${allRows.length}`), anyActive && /* @__PURE__ */ React.createElement("button", { type: "button", className: "qe-dl-clear", onClick: clearAll }, "CLEAR")), view.length ? /* @__PURE__ */ React.createElement("table", { className: `qe-table ${dense ? "tight" : ""}`, style: fixed ? { tableLayout: "fixed" } : void 0 }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, columns.map((col, ci) => {
    var _a;
    const isEdge = ci === 0 || ci === columns.length - 1;
    const eff = isEdge ? col.align : "center";
    const canSort = sortableOf(col);
    const id = colId(col);
    const active = canSort && id != null && sort.key === id;
    const thStyle = {
      ...col.width ? { width: col.width } : null,
      ...toolsOn ? { top: DL_TOOLS_H } : null
    };
    return /* @__PURE__ */ React.createElement(
      "th",
      {
        key: (_a = col.key) != null ? _a : ci,
        className: [eff === "right" ? "r" : eff === "center" ? "c" : "", canSort ? "qe-sort" : "", active ? "on" : ""].filter(Boolean).join(" "),
        style: Object.keys(thStyle).length ? thStyle : void 0,
        onClick: canSort ? () => cycleSort(id) : void 0
      },
      col.label,
      canSort && /* @__PURE__ */ React.createElement("span", { className: `qe-sort-caret${active ? "" : " idle"}`, "aria-hidden": "true" }, active ? sort.dir === "desc" ? "\u25BC" : "\u25B2" : "\u2195")
    );
  }))), /* @__PURE__ */ React.createElement("tbody", null, view.map(({ row, _i }) => {
    var _a;
    const isSel = selected != null && row[selKey] === selected;
    return /* @__PURE__ */ React.createElement(
      "tr",
      {
        key: (_a = row[selKey]) != null ? _a : _i,
        className: isSel ? "sel" : "",
        onClick: onClick ? () => onClick(row, _i) : void 0,
        style: onClick ? { cursor: "pointer" } : void 0
      },
      columns.map((col, ci) => {
        var _a2;
        const isEdge = ci === 0 || ci === columns.length - 1;
        const eff = isEdge ? col.align : "center";
        const cls = [
          eff === "right" ? "r" : eff === "center" ? "c" : "",
          col.cell || ""
        ].filter(Boolean).join(" ");
        return /* @__PURE__ */ React.createElement("td", { key: (_a2 = col.key) != null ? _a2 : ci, className: cls, style: col.width ? { width: col.width } : void 0 }, col.render ? col.render(row, _i) : row[col.key]);
      })
    );
  }))) : /* @__PURE__ */ React.createElement("div", { className: "qe-dl-empty" }, "no matches", anyActive && /* @__PURE__ */ React.createElement(React.Fragment, null, " \xB7 ", /* @__PURE__ */ React.createElement("button", { type: "button", onClick: clearAll }, "clear"))), summary && /* @__PURE__ */ React.createElement("div", { style: {
    padding: "3px 8px",
    borderTop: "1px solid var(--qe-line)",
    background: "var(--qe-panel)",
    flexShrink: 0,
    display: "flex",
    justifyContent: "space-between",
    fontSize: "var(--qe-fs-xs)",
    fontFamily: "var(--qe-mono)",
    color: "var(--qe-sub)"
  } }, typeof summary === "string" ? /* @__PURE__ */ React.createElement("span", null, summary) : summary));
};
const FL_TONES = { cyan: "cyan", green: "green", red: "red", amber: "amber", sub: "sub" };
const FieldList = ({ rows, cols = 1, dense = false, style = {} }) => /* @__PURE__ */ React.createElement("div", { className: `qe-fl${cols === 2 ? " qe-fl-2" : ""}${dense ? " qe-fl-dense" : ""}`, style }, rows.map((r, i) => {
  var _a;
  const tone = FL_TONES[r.color];
  const raw = !tone && r.color ? r.color : void 0;
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      key: (_a = r.label) != null ? _a : i,
      className: `qe-fl-row${r.meta != null ? " qe-fl-meta3" : ""}${r.emphasis ? " qe-fl-emph" : ""}`,
      title: r.hint || void 0
    },
    /* @__PURE__ */ React.createElement("div", { className: "qe-fl-l" }, /* @__PURE__ */ React.createElement("span", { style: { overflow: "hidden", textOverflow: "ellipsis" } }, r.label), r.hint && /* @__PURE__ */ React.createElement("span", { className: "qe-fl-hint" }, r.hint)),
    /* @__PURE__ */ React.createElement("div", { className: `qe-fl-v${tone ? " " + tone : ""}`, style: raw ? { color: raw } : void 0 }, r.value),
    r.meta != null && /* @__PURE__ */ React.createElement("div", { className: "qe-fl-m" }, r.meta),
    r.bar && /* @__PURE__ */ React.createElement("div", { className: "qe-fl-bar" }, /* @__PURE__ */ React.createElement("span", { style: { width: `${Math.max(0, Math.min(100, r.bar.pct))}%`, background: r.bar.color || void 0 } }))
  );
}));
const StepperInput = ({ defaultValue, step = 1, decimals = 2, min = null, color }) => {
  const [v, setV] = React.useState(parseFloat(defaultValue));
  const [text, setText] = React.useState(() => parseFloat(defaultValue).toFixed(decimals));
  const clamp = (n) => {
    let x = +(+n).toFixed(decimals);
    if (min != null && x < min) x = min;
    return x;
  };
  const commit = (n) => {
    const x = clamp(n);
    setV(x);
    setText(x.toFixed(decimals));
  };
  const bump = (d) => commit(v + d * step);
  const btn = {
    width: 16,
    flex: 1,
    minHeight: 0,
    padding: 0,
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "transparent",
    border: "none",
    cursor: "pointer"
  };
  const triUp = {
    width: 0,
    height: 0,
    borderLeft: "3px solid transparent",
    borderRight: "3px solid transparent",
    borderBottom: "4px solid var(--qe-muted)"
  };
  const triDown = {
    width: 0,
    height: 0,
    borderLeft: "3px solid transparent",
    borderRight: "3px solid transparent",
    borderTop: "4px solid var(--qe-muted)"
  };
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "stretch", height: 22, background: "var(--qe-panel)", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(
    "input",
    {
      value: text,
      onChange: (e) => {
        setText(e.target.value);
        const n = parseFloat(e.target.value);
        if (!Number.isNaN(n)) setV(clamp(n));
      },
      onBlur: () => {
        const n = parseFloat(text);
        commit(Number.isNaN(n) ? v : n);
      },
      onKeyDown: (e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        else if (e.key === "ArrowUp") {
          e.preventDefault();
          bump(1);
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          bump(-1);
        }
      },
      style: {
        flex: 1,
        minWidth: 0,
        width: "100%",
        height: "100%",
        boxSizing: "border-box",
        background: "transparent",
        border: "none",
        outline: "none",
        padding: "0 7px",
        fontFamily: "var(--qe-mono)",
        fontSize: "0.7rem",
        fontWeight: 600,
        color: color || "var(--qe-text)"
      }
    }
  ), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", height: "100%", borderLeft: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement("button", { title: "Increase", onClick: () => bump(1), style: { ...btn, borderBottom: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement("span", { style: triUp })), /* @__PURE__ */ React.createElement("button", { title: "Decrease", onClick: () => bump(-1), style: btn }, /* @__PURE__ */ React.createElement("span", { style: triDown }))));
};
const LockButton = ({ locked, onToggle, compact = false, style = {} }) => /* @__PURE__ */ React.createElement(
  "button",
  {
    type: "button",
    onClick: onToggle,
    className: `qe-btn qe-btn-sm qe-lockbtn${locked ? " qe-btn-on" : ""}`,
    title: locked ? "Workspace locked \u2014 click to edit layout" : "Lock workspace layout",
    "aria-pressed": locked,
    style: { gap: 4, ...style }
  },
  /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.72rem", lineHeight: 1 } }, locked ? "\u{1F512}" : "\u{1F513}"),
  !compact && /* @__PURE__ */ React.createElement("span", { style: { letterSpacing: "0.04em" } }, locked ? "LOCKED" : "LOCK")
);
const NewsTickerBar = React.memo(function NewsTickerBar2({
  news,
  label = "NEWS",
  meta = "REGIME FEED \xB7 finnhub + bwe",
  pollMs = 4e3
}) {
  const sortFeed = () => {
    const feed = news || [];
    return [...feed].sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at));
  };
  const [items, setItems] = React.useState(sortFeed);
  const fetchLatest = React.useCallback(async () => {
    await new Promise((r) => setTimeout(r, 40));
    return sortFeed();
  }, [news]);
  React.useEffect(() => {
    let alive = true;
    const key = (arr) => arr.map((n) => n.id + ":" + n.published_at).join("|");
    (async function poll() {
      while (alive) {
        await new Promise((r) => setTimeout(r, pollMs));
        const next = await fetchLatest();
        setItems((prev) => key(prev) === key(next) ? prev : next);
      }
    })();
    return () => {
      alive = false;
    };
  }, [fetchLatest, pollMs]);
  const nowMs = (items.length ? Date.parse(items[0].published_at) : Date.now()) + 18 * 6e4;
  const impactColor = { high: "var(--qe-red)", medium: "var(--qe-amber)", low: "var(--qe-muted)" };
  const rel = (iso) => {
    const m = Math.max(0, Math.round((nowMs - Date.parse(iso)) / 6e4));
    if (m < 60) return m + "m";
    const h = Math.round(m / 60);
    return h < 24 ? h + "h" : Math.round(h / 24) + "d";
  };
  const runItems = (prefix) => items.map((n, i) => /* @__PURE__ */ React.createElement("span", { key: prefix + n.id + "-" + i, className: "qe-newsticker-item" }, /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-dot", style: { background: impactColor[n.impact] || "var(--qe-muted)" } }), /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-src" }, n.source.toUpperCase()), /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-head" }, n.headline), n.tickers && /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-tk" }, n.tickers), /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-time" }, rel(n.published_at), " ago"), /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-sep" }, "\u25C6")));
  return /* @__PURE__ */ React.createElement("div", { className: "qe-newsticker" }, /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-label" }, /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-live" }), label), /* @__PURE__ */ React.createElement("div", { className: "qe-newsticker-track" }, /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-run" }, runItems("a")), /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-run", "aria-hidden": "true" }, runItems("b"))), meta && /* @__PURE__ */ React.createElement("span", { className: "qe-newsticker-meta" }, meta));
});
const Switch = ({ checked = false, onChange, label = null, title = null, accent = "var(--qe-sub)", disabled = false }) => /* @__PURE__ */ React.createElement(
  "div",
  {
    onClick: disabled ? void 0 : onChange,
    title,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 7,
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.45 : 1
    }
  },
  /* @__PURE__ */ React.createElement("span", { style: { width: 26, height: 14, background: checked && !disabled ? accent : "var(--qe-faint)", position: "relative", flexShrink: 0, transition: "background .12s" } }, /* @__PURE__ */ React.createElement("span", { style: { position: "absolute", top: 2, left: checked && !disabled ? 14 : 2, width: 10, height: 10, background: "var(--qe-bg)", transition: "left .12s" } })),
  label && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.6rem", fontWeight: 600, color: checked && !disabled ? "var(--qe-text)" : "var(--qe-muted)" } }, label)
);
const Chip = ({ label, count = null, active = false, muted = false, onClick, onMute = null }) => /* @__PURE__ */ React.createElement("div", { onClick, style: {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "1px 4px 1px 7px",
  cursor: "pointer",
  border: `1px solid ${active ? "var(--qe-line-2)" : "var(--qe-faint)"}`,
  background: active ? "var(--qe-panel)" : "transparent"
} }, /* @__PURE__ */ React.createElement("span", { style: {
  fontFamily: "var(--qe-ui)",
  fontWeight: 600,
  fontSize: "0.56rem",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: active ? "var(--qe-text)" : "var(--qe-sub)",
  textDecoration: muted ? "line-through" : "none",
  opacity: muted ? 0.55 : 1
} }, label), count != null && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", fontWeight: 600, color: "var(--qe-muted)" } }, count), onMute && /* @__PURE__ */ React.createElement(
  "span",
  {
    title: muted ? "Unmute" : "Mute",
    onClick: (e) => {
      e.stopPropagation();
      onMute();
    },
    style: { width: 14, height: 14, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "0.62rem", lineHeight: 1, color: muted ? "var(--qe-amber)" : "var(--qe-muted)" }
  },
  muted ? "\u2298" : "\u266A"
));
const _BANNER = {
  err: ["var(--qe-red)", "var(--qe-bg-red)"],
  warn: ["var(--qe-amber)", "var(--qe-bg-amber)"],
  info: ["var(--qe-cyan)", "var(--qe-bg-cyan)"],
  ok: ["var(--qe-green)", "var(--qe-bg-green)"]
};
const Banner = ({ tone = "err", tag = null, title, detail = null, time = null, releaseIn = null, releaseLabel = "RELEASES IN", actionLabel = "ACKNOWLEDGE", onAction = null }) => {
  const [c, bg] = _BANNER[tone] || _BANNER.err;
  return /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0, position: "relative", display: "flex", alignItems: "center", gap: 12, height: 30, padding: "0 12px", background: bg, borderBottom: `1px solid ${c}` } }, /* @__PURE__ */ React.createElement("span", { style: { position: "absolute", left: 0, top: 0, bottom: 0, width: 3, background: c } }), tag && /* @__PURE__ */ React.createElement("span", { className: "qe-badge qe-badge-solid", style: { background: c } }, tag), time && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.62rem", fontWeight: 600, color: "var(--qe-sub)", whiteSpace: "nowrap", letterSpacing: "0.02em" } }, time), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontWeight: 700, color: c, fontSize: "0.72rem", letterSpacing: "0.02em", whiteSpace: "nowrap" } }, title), detail && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", color: "var(--qe-text-dim)", fontSize: "0.64rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 } }, detail), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), releaseIn != null && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.14em", color: "var(--qe-muted)", whiteSpace: "nowrap" } }, releaseLabel), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.72rem", fontWeight: 700, color: c, whiteSpace: "nowrap", border: `1px solid ${c}`, padding: "1px 7px", background: "rgba(0,0,0,0.28)" } }, releaseIn)), onAction && /* @__PURE__ */ React.createElement("button", { className: `qe-btn qe-btn-sm ${tone === "err" ? "qe-btn-danger" : ""}`, onClick: onAction }, actionLabel));
};
const _TOASTC = { err: "var(--qe-red)", warn: "var(--qe-amber)", info: "var(--qe-cyan)", ok: "var(--qe-green)", mute: "var(--qe-line-2)" };
const Toast = ({ tone = "mute", tag = null, time = null, title, detail = null, onClose = null, onClick = null }) => {
  const c = _TOASTC[tone] || _TOASTC.mute;
  return /* @__PURE__ */ React.createElement("div", { className: "qe-toast", onClick, style: { position: "relative", width: 300, background: "var(--qe-card)", borderTop: "1px solid var(--qe-line)", borderRight: "1px solid var(--qe-line)", boxShadow: "0 8px 24px rgba(0,0,0,0.55)", overflow: "hidden", cursor: onClick ? "pointer" : "default" } }, /* @__PURE__ */ React.createElement("div", { style: { position: "relative", zIndex: 1, display: "flex", flexDirection: "column", gap: 2, padding: "6px 9px 7px 11px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7 } }, tag && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.14em", color: "var(--qe-muted)" } }, tag), time && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", letterSpacing: "0.02em", color: "var(--qe-muted)" } }, "\xB7 ", time), tone !== "mute" && tone !== "info" && tone !== "ok" && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.1em", color: c } }, tone === "err" ? "HALT" : "RISK"), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), onClose && /* @__PURE__ */ React.createElement("span", { onClick: (e) => {
    e.stopPropagation();
    onClose();
  }, style: { color: "var(--qe-muted)", fontSize: "0.85rem", lineHeight: 1, cursor: "pointer" } }, "\xD7")), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-ui)", fontWeight: 600, fontSize: "0.7rem", color: "var(--qe-text)", lineHeight: 1.2 } }, title), detail && /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.54rem", color: "var(--qe-sub)", lineHeight: 1.28 } }, detail)), /* @__PURE__ */ React.createElement("span", { style: { position: "absolute", left: 0, right: 0, bottom: 0, height: 1, background: "var(--qe-line)", zIndex: 1 } }), /* @__PURE__ */ React.createElement("span", { style: { position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: c, zIndex: 2 } }), /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", left: 0, right: 0, bottom: 0, height: 2, zIndex: 2 } }, /* @__PURE__ */ React.createElement("div", { className: "qe-toast-bar", style: { height: "100%", background: c, opacity: 0.9 } })));
};
const PageHeader = ({ title, subtitle = null, left = null, children = null }) => /* @__PURE__ */ React.createElement("div", { className: "qe-page-header", style: {
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "0 10px",
  height: 34,
  boxSizing: "border-box",
  borderBottom: "1px solid var(--qe-line)",
  background: "var(--qe-page)",
  flexShrink: 0
} }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.78rem", fontWeight: 700, color: "var(--qe-text)", whiteSpace: "nowrap", letterSpacing: "0.04em", textTransform: "uppercase" } }, title), subtitle && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.56rem", color: "var(--qe-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 } }, subtitle), left, children && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), children));
Object.assign(window, {
  Lbl,
  SecLbl,
  KV,
  Card,
  Stat,
  HeroNumber,
  Delta,
  StatusDot,
  Badge,
  RegimeBadge,
  PeriodSelector,
  Gauge,
  EmptyState,
  Tabs,
  Strip,
  FlashCell,
  LiveValue,
  LiveClock,
  asciiSpark,
  ASCII_SPARK,
  Pane,
  PaneHead,
  PaneFoot,
  ModelDialog,
  qeFootState,
  qeFootCause,
  _ptJson,
  RefreshButton,
  ReloadGlyph,
  ReloadIconSVG,
  BrailleSquares,
  Spinner,
  useSpinFrame,
  RELOAD_MS,
  PaneErrorBoundary,
  DataList,
  FieldList,
  StepperInput,
  LockButton,
  NewsTickerBar,
  Switch,
  Chip,
  Banner,
  Toast,
  PageHeader
});

;

/* ==== charts.jsx ==== */
const _qeResolveColor = (c) => {
  if (typeof c !== "string") return c;
  const m = c.match(/^var\(\s*(--[\w-]+)\s*\)(.*)$/);
  if (!m) return c;
  const v = getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim();
  return v + (m[2] || "");
};
const _qeReadVar = (name, fallback) => {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
};
const QE_ECHARTS_THEME = new Proxy({}, {
  get(_, key) {
    const map = {
      bg: ["--qe-bg", "#000000"],
      text: ["--qe-text", "#ffffff"],
      sub: ["--qe-sub", "#b6c8df"],
      muted: ["--qe-muted", "#8298b4"],
      line: ["--qe-line", "#36486a"],
      faint: ["--qe-faint", "#2c3a52"],
      green: ["--qe-green", "#00ff7f"],
      red: ["--qe-red", "#ff2d4a"],
      cyan: ["--qe-cyan", "#00e7ff"],
      amber: ["--qe-amber", "#ffae00"],
      blue: ["--qe-blue", "#2a8fff"]
    };
    const pair = map[key];
    if (!pair) return void 0;
    return _qeReadVar(pair[0], pair[1]);
  }
});
const _baseChart = (opts = {}) => ({
  backgroundColor: "transparent",
  animation: false,
  textStyle: { fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: QE_ECHARTS_THEME.text, fontWeight: 500 },
  grid: { left: 38, right: 8, top: 6, bottom: 18, ...opts.grid },
  tooltip: {
    trigger: "axis",
    backgroundColor: QE_ECHARTS_THEME.bg,
    borderColor: QE_ECHARTS_THEME.cyan,
    borderWidth: 1,
    padding: [4, 8],
    textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: "JetBrains Mono, monospace", fontWeight: 500 },
    axisPointer: { lineStyle: { color: QE_ECHARTS_THEME.cyan, type: "solid", opacity: 0.4 }, crossStyle: { color: QE_ECHARTS_THEME.cyan } }
  }
});
const _axis = (extra = {}) => ({
  axisLine: { lineStyle: { color: QE_ECHARTS_THEME.line } },
  axisTick: { lineStyle: { color: QE_ECHARTS_THEME.line } },
  axisLabel: { color: QE_ECHARTS_THEME.sub, fontSize: 10, fontFamily: "JetBrains Mono, monospace", fontWeight: 500 },
  splitLine: { lineStyle: { color: QE_ECHARTS_THEME.line, opacity: 0.5, type: [2, 3] } },
  ...extra
});
function useECharts(ref, opts, deps = []) {
  React.useEffect(() => {
    if (!ref.current || !window.echarts) return;
    const chart = window.echarts.init(ref.current, null, { renderer: "canvas" });
    chart.setOption(opts);
    const raf = requestAnimationFrame(() => {
      try {
        chart.resize();
      } catch (e) {
      }
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    let ro = null;
    if (window.ResizeObserver) {
      ro = new ResizeObserver(() => chart.resize());
      ro.observe(ref.current);
    }
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      if (ro) ro.disconnect();
      chart.dispose();
    };
  }, deps);
}
const CandlestickChart = ({ data, height = "100%", volume = false, logScale = false }) => {
  const ref = React.useRef(null);
  const opts = React.useMemo(() => {
    const cats = data.map((d) => new Date(d[0]));
    const oclh = data.map((d) => [d[1], d[2], d[3], d[4]]);
    return {
      ..._baseChart({ grid: { left: 44, right: 8, top: 6, bottom: 18 } }),
      xAxis: {
        type: "category",
        boundaryGap: true,
        data: cats.map((d) => `${("0" + (d.getUTCMonth() + 1)).slice(-2)}-${("0" + d.getUTCDate()).slice(-2)} ${("0" + d.getUTCHours()).slice(-2)}:00`),
        ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.sub, fontSize: 10, fontFamily: "JetBrains Mono, monospace", fontWeight: 500, interval: Math.max(1, Math.floor(data.length / 6)) } })
      },
      yAxis: {
        type: logScale ? "log" : "value",
        scale: true,
        position: "left",
        ..._axis({ axisLabel: {
          color: QE_ECHARTS_THEME.sub,
          fontSize: 10,
          fontFamily: "JetBrains Mono, monospace",
          fontWeight: 500,
          formatter: (v) => v.toFixed(2)
        } })
      },
      series: [{
        type: "candlestick",
        data: oclh,
        itemStyle: {
          color: QE_ECHARTS_THEME.green,
          // up body fill
          color0: "transparent",
          // down body fill (hollow)
          borderColor: QE_ECHARTS_THEME.green,
          borderColor0: QE_ECHARTS_THEME.red,
          borderWidth: 1
        },
        emphasis: { itemStyle: { borderWidth: 1.5 } },
        barWidth: "60%"
      }]
    };
  }, [data, logScale]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, className: "qe-chart", style: { height } });
};
const EquityChart = ({ data, height = "100%", color = QE_ECHARTS_THEME.green, baseline = null }) => {
  const ref = React.useRef(null);
  color = _qeResolveColor(color);
  const opts = React.useMemo(() => ({
    ..._baseChart({ grid: { left: 40, right: 8, top: 6, bottom: 18 } }),
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: data.map((_, i) => i),
      ..._axis({ axisLabel: { show: false }, axisTick: { show: false } })
    },
    yAxis: {
      type: "value",
      scale: true,
      ..._axis({ axisLabel: {
        color: QE_ECHARTS_THEME.sub,
        fontSize: 10,
        fontFamily: "JetBrains Mono, monospace",
        fontWeight: 500,
        formatter: (v) => v.toFixed(2)
      } })
    },
    series: [{
      type: "line",
      data,
      smooth: 0.15,
      symbol: "none",
      lineStyle: { color, width: 1.4 },
      areaStyle: { color: {
        type: "linear",
        x: 0,
        y: 0,
        x2: 0,
        y2: 1,
        colorStops: [
          { offset: 0, color: color + "40" },
          { offset: 1, color: color + "00" }
        ]
      } },
      markLine: baseline != null ? {
        symbol: "none",
        silent: true,
        data: [{
          yAxis: baseline,
          lineStyle: { color: QE_ECHARTS_THEME.muted, type: "dashed", width: 1 },
          label: { show: false }
        }]
      } : void 0
    }]
  }), [data, color, baseline]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, className: "qe-chart", style: { height } });
};
const Sparkline = ({ data, color = QE_ECHARTS_THEME.green, height = 24, area = true, width = "100%" }) => {
  const ref = React.useRef(null);
  color = _qeResolveColor(color);
  const opts = React.useMemo(() => ({
    backgroundColor: "transparent",
    animation: false,
    grid: { left: 0, right: 0, top: 1, bottom: 1 },
    xAxis: { type: "category", show: false, boundaryGap: false, data: data.map((_, i) => i) },
    yAxis: { type: "value", show: false, scale: true },
    series: [{
      type: "line",
      data,
      smooth: 0.2,
      symbol: "none",
      lineStyle: { color, width: 1.1 },
      areaStyle: area ? { color: color + "25" } : void 0
    }],
    tooltip: { show: false }
  }), [data, color, area]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, style: { width, height } });
};
const BarChart = ({ data, color = QE_ECHARTS_THEME.cyan, height = "100%", categories = null }) => {
  const ref = React.useRef(null);
  color = _qeResolveColor(color);
  const opts = React.useMemo(() => ({
    ..._baseChart({ grid: { left: 36, right: 8, top: 6, bottom: 18 } }),
    xAxis: {
      type: "category",
      data: categories || data.map((_, i) => i),
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.sub, fontSize: 10, fontFamily: "JetBrains Mono, monospace", fontWeight: 500 } })
    },
    yAxis: { type: "value", ..._axis() },
    series: [{
      type: "bar",
      data,
      itemStyle: { color: (p) => p.value >= 0 ? QE_ECHARTS_THEME.green : QE_ECHARTS_THEME.red },
      barWidth: "60%"
    }]
  }), [data, color, categories]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, className: "qe-chart", style: { height } });
};
const RegimeRibbon = ({ segments, height = 22, width = "100%" }) => {
  const total = segments.reduce((a, s) => a + s.t, 0);
  const colors = {
    trend: "var(--qe-green)",
    chop: "var(--qe-cyan)",
    neut: "var(--qe-sub)",
    def: "var(--qe-amber)",
    panic: "var(--qe-red)"
  };
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", width, height, border: "1px solid var(--qe-line)" } }, segments.map((s, i) => /* @__PURE__ */ React.createElement(
    "div",
    {
      key: i,
      title: s.label,
      style: {
        flex: s.t / total,
        background: colors[s.tone] || "var(--qe-sub)",
        opacity: 0.85,
        borderRight: i < segments.length - 1 ? "1px solid var(--qe-bg)" : "none"
      }
    }
  )));
};
const HeatStrip = ({ data, height = 18 }) => {
  const max = Math.max(...data.map((d) => Math.abs(d.pnl)));
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", height, gap: 1 } }, data.map((d, i) => {
    const mag = Math.abs(d.pnl) / max;
    const col = d.pnl >= 0 ? `rgba(0,255,127,${0.15 + mag * 0.85})` : `rgba(255,45,74,${0.15 + mag * 0.85})`;
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        key: i,
        title: `${d.date}: ${d.pnl >= 0 ? "+" : ""}${d.pnl}`,
        style: { flex: 1, background: col }
      }
    );
  }));
};
const ScatterChart = ({ points, height = "100%", xName = "X", yName = "Y" }) => {
  const ref = React.useRef(null);
  const opts = React.useMemo(() => {
    const profitable = points.filter((p) => p.profit);
    const losses = points.filter((p) => !p.profit);
    return {
      ..._baseChart({ grid: { left: 48, right: 14, top: 18, bottom: 38 } }),
      tooltip: {
        trigger: "item",
        backgroundColor: QE_ECHARTS_THEME.bg,
        borderColor: QE_ECHARTS_THEME.cyan,
        borderWidth: 1,
        textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: "JetBrains Mono, monospace" },
        formatter: (p) => {
          const d = p.data;
          return `<div style="padding:4px 8px;">
            <b>${d[2] || ""}</b><br/>
            ${xName}: ${d[0].toFixed(2)}<br/>
            ${yName}: ${d[1].toFixed(2)}
          </div>`;
        }
      },
      xAxis: {
        type: "value",
        scale: true,
        name: xName,
        nameLocation: "center",
        nameGap: 24,
        nameTextStyle: { color: QE_ECHARTS_THEME.sub, fontSize: 10 },
        ..._axis()
      },
      yAxis: {
        type: "value",
        scale: true,
        name: yName,
        nameLocation: "middle",
        nameGap: 36,
        nameRotate: 90,
        nameTextStyle: { color: QE_ECHARTS_THEME.sub, fontSize: 10 },
        ..._axis()
      },
      series: [
        {
          name: "Profitable",
          type: "scatter",
          data: profitable.map((d) => [d.x, d.y, d.label]),
          itemStyle: { color: QE_ECHARTS_THEME.green, opacity: 0.8 },
          symbolSize: 7
        },
        {
          name: "Loss",
          type: "scatter",
          data: losses.map((d) => [d.x, d.y, d.label]),
          itemStyle: { color: QE_ECHARTS_THEME.red, opacity: 0.8 },
          symbolSize: 7
        }
      ]
    };
  }, [points, xName, yName]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, className: "qe-chart", style: { height } });
};
Object.assign(window, {
  QE_ECHARTS_THEME,
  CandlestickChart,
  EquityChart,
  Sparkline,
  BarChart,
  RegimeRibbon,
  HeatStrip,
  ScatterChart
});

;

/* ==== grid-workspace.jsx ==== */
const GridItem = ({ x, y, w, h, minW, minH, noMove = false, children }) => /* @__PURE__ */ React.createElement(
  "div",
  {
    className: "grid-stack-item",
    "data-gx": x,
    "data-gy": y,
    "data-gw": w,
    "data-gh": h,
    "data-gminw": minW,
    "data-gminh": minH,
    "data-gnomove": noMove ? 1 : void 0
  },
  /* @__PURE__ */ React.createElement("div", { className: "grid-stack-item-content" }, children)
);
const WS_LOCK_KEY = "qe.workspace.locked";
function useWorkspaceLock() {
  const read = () => {
    try {
      return localStorage.getItem(WS_LOCK_KEY) === "1";
    } catch {
      return false;
    }
  };
  const [locked, setLocked] = React.useState(read);
  React.useEffect(() => {
    const sync = () => setLocked(read());
    window.addEventListener("qe-ws-lock", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("qe-ws-lock", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const toggle = React.useCallback(() => {
    const next = !read();
    try {
      localStorage.setItem(WS_LOCK_KEY, next ? "1" : "0");
    } catch {
    }
    window.dispatchEvent(new Event("qe-ws-lock"));
  }, []);
  return [locked, toggle];
}
const GridWorkspace = ({ cols = 24, rows = 24, margin = null, minCell = 17, persistId = null, style = {}, children }) => {
  const wrapRef = React.useRef(null);
  const elRef = React.useRef(null);
  const gridRef = React.useRef(null);
  const [locked, toggleLock] = useWorkspaceLock();
  React.useEffect(() => {
    if (!window.GridStack || !elRef.current || gridRef.current) return;
    const cssId = `gs-${cols}-cols`;
    if (!document.getElementById(cssId)) {
      let css = `.gs-${cols}>.grid-stack-item{width:${100 / cols}%}
`;
      for (let n = 1; n <= cols; n++) css += `.gs-${cols}>.grid-stack-item[gs-w="${n}"]{width:${n / cols * 100}%}
`;
      for (let n = 0; n < cols; n++) css += `.gs-${cols}>.grid-stack-item[gs-x="${n}"]{left:${n / cols * 100}%}
`;
      const st = document.createElement("style");
      st.id = cssId;
      st.textContent = css;
      document.head.appendChild(st);
    }
    [...elRef.current.children].forEach((it) => {
      const d = it.dataset;
      if (d.gx != null) it.setAttribute("gs-x", d.gx);
      if (d.gy != null) it.setAttribute("gs-y", d.gy);
      if (d.gw != null) it.setAttribute("gs-w", d.gw);
      if (d.gh != null) it.setAttribute("gs-h", d.gh);
      if (d.gminw) it.setAttribute("gs-min-w", d.gminw);
      if (d.gminh) it.setAttribute("gs-min-h", d.gminh);
      if (d.gnomove) it.setAttribute("gs-no-move", "true");
    });
    const wrap = wrapRef.current;
    const GAP = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--qe-pane-gap")) || 4;
    const m = margin != null ? margin : Math.round(GAP / 2);
    const vpad = 2 * m;
    const cell = () => Math.max(minCell, Math.floor(((wrap.clientHeight || 720) - vpad - m * (rows + 1)) / rows));
    const grid = window.GridStack.init({
      column: cols,
      margin: m,
      // half the standard gutter (GAP/2) on every tile edge
      float: false,
      // tiling — compact upward, never overlap
      cellHeight: cell(),
      handle: ".qe-pane-head",
      // drag from the title bar only
      draggable: { cancel: "button, input, select, a, textarea, .qe-period, .qe-grip" },
      resizable: { handles: "n,e,s,w,se,sw,ne,nw" },
      animate: true,
      disableOneColumnMode: true
    }, elRef.current);
    gridRef.current = grid;
    const ro = new ResizeObserver(() => grid.cellHeight(cell()));
    ro.observe(wrap);
    if (persistId) {
      window.__qeWorkspaces = window.__qeWorkspaces || {};
      window.__qeWorkspaces[persistId] = grid;
      window.__qeWorkspaceDefaults = window.__qeWorkspaceDefaults || {};
      window.__qeWorkspaceDefaults[persistId] = grid.save(false, false);
    }
    return () => {
      ro.disconnect();
      if (persistId && window.__qeWorkspaces) delete window.__qeWorkspaces[persistId];
      grid.destroy(false);
      gridRef.current = null;
    };
  }, []);
  React.useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    grid.setStatic(locked);
    if (elRef.current) elRef.current.setAttribute("data-locked", locked ? "1" : "0");
  }, [locked]);
  return /* @__PURE__ */ React.createElement("div", { ref: wrapRef, style: { flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", padding: "calc(var(--qe-pane-gap) / 2)", ...style } }, /* @__PURE__ */ React.createElement("div", { className: "grid-stack", ref: elRef, style: { width: "100%" } }, children));
};
Object.assign(window, { GridWorkspace, GridItem, useWorkspaceLock });
const WS_LAYOUT_KEY = (id) => `qe.ws.layout.${id}`;
function qeWorkspaceSave(id) {
  const grid = window.__qeWorkspaces && window.__qeWorkspaces[id];
  if (!grid) return false;
  try {
    localStorage.setItem(WS_LAYOUT_KEY(id), JSON.stringify(grid.save(false, false)));
    return true;
  } catch {
    return false;
  }
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
  try {
    raw = localStorage.getItem(WS_LAYOUT_KEY(id));
  } catch {
  }
  if (!raw) return false;
  return qeWorkspaceApply(grid, JSON.parse(raw));
}
function qeWorkspaceReset(id) {
  const grid = window.__qeWorkspaces && window.__qeWorkspaces[id];
  const def = window.__qeWorkspaceDefaults && window.__qeWorkspaceDefaults[id];
  return qeWorkspaceApply(grid, def);
}
function qeWorkspaceHasSaved(id) {
  try {
    return !!localStorage.getItem(WS_LAYOUT_KEY(id));
  } catch {
    return false;
  }
}
function qeWorkspaceSetLayout(id, layout) {
  const grid = window.__qeWorkspaces && window.__qeWorkspaces[id];
  if (!grid) return false;
  return qeWorkspaceApply(grid, layout);
}
Object.assign(window, { qeWorkspaceSave, qeWorkspaceLoad, qeWorkspaceReset, qeWorkspaceHasSaved, qeWorkspaceSetLayout });

;

/* ==== chrome-live.js ==== */
const QE_CHROME = function() {
  const st = {
    state: null,
    snap: null,
    sys: null,
    accounts: null,
    stateErr: false,
    snapErr: false,
    sysErr: false,
    sse: "idle"
  };
  const subs = /* @__PURE__ */ new Set();
  const emit = () => subs.forEach((f) => {
    try {
      f();
    } catch (e) {
    }
  });
  const j = async (url) => {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(url + " " + r.status);
    return r.json();
  };
  const poll = (url, key, errKey, ms) => {
    const run = async () => {
      try {
        st[key] = await j(url);
        st[errKey] = false;
      } catch (e) {
        st[errKey] = true;
      }
      emit();
    };
    run();
    setInterval(run, ms);
  };
  poll("/api/state", "state", "stateErr", 1e4);
  poll("/api/dashboard/snapshot", "snap", "snapErr", 3e4);
  poll("/api/system", "sys", "sysErr", 6e4);
  const loadAccounts = async () => {
    try {
      st.accounts = await j("/accounts");
    } catch (e) {
      st.accounts = null;
    }
    emit();
    if (st.accounts == null) setTimeout(loadAccounts, 6e4);
  };
  loadAccounts();
  setInterval(() => {
    const s = window.QE_SSE && window.QE_SSE.status() || "idle";
    if (s !== st.sse) {
      st.sse = s;
      emit();
    }
  }, 2e3);
  return {
    get: () => st,
    sub: (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    reloadAccounts: loadAccounts
  };
}();
const useQeChrome = () => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => QE_CHROME.sub(force), []);
  return QE_CHROME.get();
};
Object.assign(window, { QE_CHROME, useQeChrome });

;

/* ==== nav-and-data.jsx ==== */
const NAV_REGIME_TONE = {
  risk_on_trending: "trend",
  risk_on_choppy: "chop",
  neutral: "neut",
  risk_off_defensive: "def",
  risk_off_panic: "panic"
};
const NAV_SSE_TONE = { open: "ok", connecting: "warn", error: "err", idle: "off", disabled: "off" };
const NAV_FEED_STALE_S = 30;
const _navFeed = (ch) => {
  if (ch && ch.stateErr) return {
    tone: "off",
    value: "\u2014",
    title: "Exchange feed: reading unavailable \u2014 /api/state is not responding"
  };
  const w = ch && ch.state && ch.state.exchange_ws || null;
  if (!w) return {
    tone: "off",
    value: "\u2014",
    title: "Exchange market-data feed: no reading yet (/api/state)"
  };
  if (!w.connected) return {
    tone: "err",
    value: "down",
    title: "Exchange market-data websocket is DOWN \u2014 prices on screen are frozen"
  };
  if (w.stale_s != null && w.stale_s > NAV_FEED_STALE_S) return {
    tone: "warn",
    value: Math.round(w.stale_s) + "s",
    title: `Exchange feed connected but no message for ${Math.round(w.stale_s)}s \u2014 prices may be stale`
  };
  if (w.using_fallback) return {
    tone: "warn",
    value: "REST",
    title: "Exchange market-data on REST FALLBACK \u2014 the websocket is not delivering; prices update on the poll interval"
  };
  return {
    tone: "ok",
    value: w.latency_ms == null ? "\u2014" : Math.round(w.latency_ms) + "ms",
    title: "Exchange market-data websocket live" + (w.latency_ms == null ? " \xB7 latency not measured yet" : ` \xB7 ${Math.round(w.latency_ms)}ms per-frame latency`)
  };
};
const _navCap = (s) => s ? s.charAt(0).toUpperCase() + s.slice(1) : "\u2014";
const _navPct = (v) => v == null ? "\u2014" : (v > 0 ? "+" : "") + v.toFixed(2) + "%";
const _navPctCol = (v) => v == null ? "var(--qe-muted)" : v > 0 ? "var(--qe-green)" : v < 0 ? "var(--qe-red)" : "var(--qe-sub)";
const _navUptime = (s) => {
  if (s == null) return "\u2014";
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
};
const NAV_ITEMS = ["Dashboard", "Pre-Trade", "Linkage", "History", "Analytics", "Models", "Regime", "Primitives"];
const QE_CLOCK_OFFSET = 0;
const qeClockFmt = (t) => {
  const s = new Date(t.getTime() + QE_CLOCK_OFFSET).toISOString();
  return s.slice(0, 10) + " " + s.slice(11, 19) + " UTC";
};
const QE_DASH_PRESETS = {
  Risk: [
    { x: 0, y: 16, w: 8, h: 8 },
    { x: 8, y: 9, w: 8, h: 7 },
    { x: 0, y: 0, w: 8, h: 16 },
    { x: 8, y: 0, w: 16, h: 9 },
    { x: 16, y: 9, w: 8, h: 7 },
    { x: 8, y: 16, w: 8, h: 8 },
    { x: 16, y: 16, w: 4, h: 8 },
    { x: 20, y: 16, w: 4, h: 8 }
  ],
  Execution: [
    { x: 0, y: 10, w: 6, h: 7 },
    { x: 16, y: 0, w: 8, h: 10 },
    { x: 6, y: 10, w: 5, h: 7 },
    { x: 0, y: 0, w: 16, h: 10 },
    { x: 11, y: 10, w: 5, h: 7 },
    { x: 0, y: 17, w: 16, h: 7 },
    { x: 16, y: 17, w: 8, h: 7 },
    { x: 16, y: 10, w: 8, h: 7 }
  ],
  Macro: [
    { x: 0, y: 16, w: 6, h: 8 },
    { x: 8, y: 0, w: 16, h: 8 },
    { x: 6, y: 16, w: 6, h: 8 },
    { x: 12, y: 16, w: 8, h: 8 },
    { x: 0, y: 0, w: 8, h: 16 },
    { x: 16, y: 8, w: 8, h: 8 },
    { x: 20, y: 16, w: 4, h: 8 },
    { x: 8, y: 8, w: 8, h: 8 }
  ]
};
const WorkspaceBar = ({ interactive = false, persistId = "dashboard" }) => {
  const ch = useQeChrome();
  const [preset, setPreset] = React.useState("Default");
  const [flash, setFlash] = React.useState(null);
  const flashTimer = React.useRef(null);
  const say = (msg) => {
    setFlash(msg);
    clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), 1800);
  };
  React.useEffect(() => () => clearTimeout(flashTimer.current), []);
  const presets = ["Default", "Risk", "Execution", "Macro"];
  const onSave = () => say(window.qeWorkspaceSave(persistId) ? "\u2713 Saved" : "Save failed");
  const onLoad = () => say(window.qeWorkspaceHasSaved(persistId) ? window.qeWorkspaceLoad(persistId) ? "\u2713 Loaded" : "Load failed" : "No saved layout");
  const onCreate = () => {
    window.qeWorkspaceReset(persistId);
    say("New workspace");
  };
  const onPreset = (p) => {
    setPreset(p);
    if (p === "Default") {
      window.qeWorkspaceReset(persistId);
      say("Default layout");
    } else if (QE_DASH_PRESETS[p] && window.qeWorkspaceSetLayout(persistId, QE_DASH_PRESETS[p])) say(p + " layout");
    else say("Preset unavailable");
  };
  const dim = interactive ? 1 : 0.4;
  const guard = (fn) => interactive ? fn : void 0;
  return /* @__PURE__ */ React.createElement("div", { className: "qe-hscroll", style: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "2px 6px",
    borderBottom: "1px solid var(--qe-line)",
    background: "var(--qe-page)",
    height: 22,
    flexShrink: 0
  } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", letterSpacing: "0.1em" } }, "WORKSPACE"), /* @__PURE__ */ React.createElement("div", { className: "qe-period", style: { opacity: dim, pointerEvents: interactive ? "auto" : "none" } }, presets.map((p) => /* @__PURE__ */ React.createElement("button", { key: p, className: preset === p ? "on" : "", onClick: guard(() => onPreset(p)) }, p))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 4, opacity: dim, pointerEvents: interactive ? "auto" : "none" } }, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: guard(onSave), title: "Save current layout" }, "\u2913 Save"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: guard(onLoad), title: "Load saved layout" }, "\u2912 Load"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: guard(onCreate), title: "New workspace from default", style: { width: 22, padding: 0, justifyContent: "center" } }, "+"), flash && /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.54rem", color: flash[0] === "\u2713" ? "var(--qe-green)" : "var(--qe-amber)" } }, flash)), !interactive && /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.5rem", color: "var(--qe-faint)", letterSpacing: "0.06em" } }, "\xB7 dashboard only"), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement(Strip, { dense: true, items: (() => {
    const st = ch.state, eq = ch.snap && ch.snap.equity, rk = ch.snap && ch.snap.risk;
    const jr = ch.snap && ch.snap.journal, rg = ch.snap && ch.snap.regime;
    const active = (ch.accounts || []).find((a) => a.is_active);
    const dPct = eq ? eq.daily_pnl_pct : null;
    const wPct = eq ? eq.weekly_pnl_pct : null;
    const mPct = jr ? jr.monthly_pnl_pct : null;
    const feed = _navFeed(ch);
    return [
      { label: "EXCH", value: active ? _navCap(active.exchange) : "\u2014" },
      { label: "LAT", value: /* @__PURE__ */ React.createElement("span", { title: feed.title, style: {
        color: feed.tone === "err" ? "var(--qe-red)" : feed.tone === "warn" ? "var(--qe-amber)" : feed.tone === "off" ? "var(--qe-muted)" : "var(--qe-sub)"
      } }, feed.value) },
      { label: "REGIME", value: rg && rg.label && NAV_REGIME_TONE[rg.label] ? /* @__PURE__ */ React.createElement(RegimeBadge, { tone: NAV_REGIME_TONE[rg.label] }) : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") },
      { label: "P&L\xB7D", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.pnl.d", value: dPct == null ? "\u2014" : dPct, format: () => _navPct(dPct), style: { color: _navPctCol(dPct), fontWeight: 700 } }) },
      { label: "P&L\xB7W", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.pnl.w", value: wPct == null ? "\u2014" : wPct, format: () => _navPct(wPct), style: { color: _navPctCol(wPct), fontWeight: 700 } }) },
      { label: "P&L\xB7M", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.pnl.m", value: mPct == null ? "\u2014" : mPct, format: () => _navPct(mPct), style: { color: _navPctCol(mPct), fontWeight: 700 } }) },
      { label: "OPEN", value: st ? `${st.position_count}${rk && rk.positions_max != null ? "/" + rk.positions_max : ""}` : "\u2014", color: "var(--qe-cyan)" },
      { label: "EXP", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.exp", value: st ? st.total_exposure : "\u2014", format: (x) => st ? (+x).toFixed(2) + "\xD7" : "\u2014" }) },
      { label: "DD", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.dd", value: st ? st.drawdown * 100 : "\u2014", format: (x) => st ? (+x).toFixed(2) + "%" : "\u2014", style: st && st.dd_state !== "ok" ? { color: st.dd_state === "limit" ? "var(--qe-red)" : "var(--qe-amber)", fontWeight: 700 } : void 0 }) }
    ];
  })() }), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", disabled: true, title: "Add pane \u2014 planned, not wired in this build", style: { opacity: 0.4, cursor: "default" } }, "\u229E Pane"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", disabled: true, title: "Pop out \u2014 planned, not wired in this build", style: { opacity: 0.4, cursor: "default" } }, "\u2922 Pop"));
};
const ClockDriftBanner = () => {
  const ch = useQeChrome();
  const state = ch && ch.state || {};
  const sev = state.clock_severity;
  if (!sev || sev === "ok") return null;
  const drift = -Math.round(state.clock_offset_ms || 0);
  const driftStr = (drift >= 0 ? "+" : "") + drift + "ms";
  const failed = sev === "failed";
  return /* @__PURE__ */ React.createElement(
    Banner,
    {
      tone: sev === "warn" ? "warn" : "err",
      tag: "CLOCK",
      title: failed ? "CLOCK SYNC FAILED \u2014 exchange server time unreachable" : "OS CLOCK DRIFT \u2014 exchange requests may be rejected",
      detail: failed ? "Could not reach exchange server time; if account/funding reads keep failing, sync the OS clock." : `local clock ${driftStr} vs exchange \xB7 Binance rejects signed reads >1000ms ahead (-1021) \xB7 sync the OS clock`
    }
  );
};
const TopNavStd = ({ page = "Dashboard", onChange, variant = "line", dense = false }) => {
  const [locked, toggleLock] = useWorkspaceLock();
  const ch = useQeChrome();
  const [switching, setSwitching] = React.useState(false);
  const [switchErr, setSwitchErr] = React.useState(false);
  const nav = onChange || ((p) => {
    if (window.qeNav) window.qeNav(p);
  });
  const accounts = ch.accounts || [];
  const active = accounts.find((a) => a.is_active);
  const onAccount = async (id) => {
    if (!id || switching || active && String(active.id) === String(id)) return;
    setSwitching(true);
    setSwitchErr(false);
    try {
      const r = await fetch("/accounts/" + id + "/activate", { method: "POST" });
      if (r.ok) {
        window.location.reload();
        return;
      }
    } catch (e) {
    }
    setSwitching(false);
    setSwitchErr(true);
    setTimeout(() => setSwitchErr(false), 4e3);
  };
  const sseTone = NAV_SSE_TONE[ch.sse] || "off";
  const feed = _navFeed(ch);
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "qe-hscroll", style: {
    display: "flex",
    alignItems: "center",
    gap: 0,
    background: "var(--qe-bg)",
    borderBottom: "1px solid var(--qe-line)",
    fontFamily: "var(--qe-ui)",
    height: dense ? 32 : 38,
    flexShrink: 0
  } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "0 14px", display: "flex", alignItems: "baseline", gap: 8, borderRight: "1px solid var(--qe-line)", alignSelf: "stretch", alignItems: "center" } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.7rem", fontWeight: 700, color: "var(--qe-cyan)", letterSpacing: "0.08em" } }, window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectShortName || "QRE"), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.56rem", color: "var(--qe-sub)", letterSpacing: "0.06em" } }, window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectVersion || "v3")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignSelf: "stretch" } }, NAV_ITEMS.map((it) => {
    const on = page === it;
    if (variant === "line") return /* @__PURE__ */ React.createElement(React.Fragment, { key: it }, it === "Primitives" && /* @__PURE__ */ React.createElement("div", { style: { width: 1, alignSelf: "center", height: 16, background: "var(--qe-line)", margin: "0 6px" } }), /* @__PURE__ */ React.createElement("button", { onClick: () => nav(it), style: {
      background: "transparent",
      border: "none",
      cursor: "pointer",
      padding: "0 12px",
      height: "100%",
      display: "inline-flex",
      alignItems: "center",
      gap: 5,
      fontFamily: "var(--qe-ui)",
      fontSize: "0.72rem",
      fontWeight: on ? 700 : 500,
      color: on ? it === "Primitives" ? "var(--qe-amber)" : "var(--qe-cyan)" : "var(--qe-sub)",
      borderBottom: on ? `2px solid ${it === "Primitives" ? "var(--qe-amber)" : "var(--qe-cyan)"}` : "2px solid transparent",
      marginBottom: "-1px",
      letterSpacing: "0.04em"
    } }, it, it === "Primitives" && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.08em", color: on ? "var(--qe-bg)" : "var(--qe-amber)", background: on ? "var(--qe-amber)" : "transparent", border: "1px solid var(--qe-amber)", padding: "0 3px", lineHeight: 1.4 } }, "DEV")));
    if (variant === "solid") return /* @__PURE__ */ React.createElement("button", { key: it, onClick: () => nav(it), style: {
      background: on ? "var(--qe-cyan)" : "transparent",
      color: on ? "var(--qe-bg)" : "var(--qe-sub)",
      border: "none",
      cursor: "pointer",
      padding: "0 14px",
      height: "100%",
      fontFamily: "var(--qe-ui)",
      fontSize: "0.72rem",
      fontWeight: on ? 700 : 500,
      letterSpacing: "0.04em"
    } }, it);
    return /* @__PURE__ */ React.createElement("button", { key: it, onClick: () => nav(it), style: {
      background: "transparent",
      border: "none",
      cursor: "pointer",
      padding: "0 10px",
      height: "100%",
      fontFamily: "var(--qe-mono)",
      fontSize: "0.7rem",
      fontWeight: on ? 700 : 500,
      color: on ? "var(--qe-cyan)" : "var(--qe-sub)"
    } }, on ? /* @__PURE__ */ React.createElement(React.Fragment, null, "[", /* @__PURE__ */ React.createElement("span", { style: { padding: "0 2px" } }, it), "]") : it);
  })), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, padding: "0 12px", alignSelf: "stretch" } }, /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", gap: 5, alignSelf: "center" } }, /* @__PURE__ */ React.createElement(
    LockButton,
    {
      locked,
      onToggle: toggleLock,
      compact: true,
      style: { height: 22, width: 22, padding: 0, justifyContent: "center" }
    }
  ), accounts.length ? /* @__PURE__ */ React.createElement(
    "select",
    {
      className: "qe-input qe-select",
      style: { height: 22, fontSize: "0.62rem", width: 175 },
      value: active ? String(active.id) : "",
      disabled: switching,
      onChange: (e) => onAccount(e.target.value),
      title: "Switch active account (reloads)"
    },
    accounts.map((a) => /* @__PURE__ */ React.createElement("option", { key: a.id, value: String(a.id) }, a.name, " (", _navCap(a.exchange), ")", a.is_active ? "" : " \u2014 inactive"))
  ) : /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", style: { height: 22, fontSize: "0.62rem", width: 175 }, disabled: true, value: "" }, /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 no accounts \u2014")), switchErr && /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.54rem", color: "var(--qe-red)" } }, "switch failed")), /* @__PURE__ */ React.createElement(StatusDot, { tone: sseTone, label: "SSE", value: ch.sse === "open" ? "live" : ch.sse }), /* @__PURE__ */ React.createElement("span", { title: feed.title, style: { display: "inline-flex" } }, /* @__PURE__ */ React.createElement(StatusDot, { tone: feed.tone, label: "FEED", value: feed.value })), /* @__PURE__ */ React.createElement("span", { style: {
    fontFamily: "var(--qe-mono)",
    fontSize: "0.56rem",
    color: "var(--qe-muted)",
    letterSpacing: "0.04em"
  } }, /* @__PURE__ */ React.createElement(LiveClock, { id: "nav.clock", format: qeClockFmt })), /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", gap: 6 } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: () => nav("Config"),
      title: "Configuration",
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 22,
        height: 22,
        padding: 0,
        background: page === "Config" ? "var(--qe-bg-cyan)" : "transparent",
        cursor: "pointer",
        border: `1px solid ${page === "Config" ? "var(--qe-cyan)" : "var(--qe-line)"}`,
        color: page === "Config" ? "var(--qe-cyan)" : "var(--qe-sub)",
        fontSize: "0.85rem",
        lineHeight: 1,
        transition: "all 0.12s"
      },
      onMouseOver: (e) => {
        e.currentTarget.style.color = "var(--qe-cyan)";
        e.currentTarget.style.borderColor = "var(--qe-line-2)";
      },
      onMouseOut: (e) => {
        e.currentTarget.style.color = page === "Config" ? "var(--qe-cyan)" : "var(--qe-sub)";
        e.currentTarget.style.borderColor = page === "Config" ? "var(--qe-cyan)" : "var(--qe-line)";
      }
    },
    "\u2699"
  ), /* @__PURE__ */ React.createElement(NotifBell, null)))), /* @__PURE__ */ React.createElement(ClockDriftBanner, null), /* @__PURE__ */ React.createElement(NotifBanner, null), /* @__PURE__ */ React.createElement(WorkspaceBar, { interactive: page === "Dashboard" }));
};
const StatusFooter = () => {
  const ch = useQeChrome();
  const engineTone = ch.stateErr ? "var(--qe-red)" : ch.state ? "var(--qe-green)" : "var(--qe-muted)";
  const sseTone = ch.sse === "open" ? "var(--qe-green)" : ch.sse === "connecting" ? "var(--qe-amber)" : ch.sse === "error" ? "var(--qe-red)" : "var(--qe-muted)";
  const feed = _navFeed(ch);
  return /* @__PURE__ */ React.createElement("div", { style: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    background: "var(--qe-bg)",
    borderTop: "1px solid var(--qe-line)",
    padding: "1px 8px",
    height: 18,
    flexShrink: 0,
    fontFamily: "var(--qe-mono)",
    fontSize: "0.54rem",
    color: "var(--qe-muted)"
  } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, (window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectShortName || "QRE") + " " + (window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectVersion || "v3")), /* @__PURE__ */ React.createElement("span", null, "\xB7"), /* @__PURE__ */ React.createElement("span", null, "uptime ", /* @__PURE__ */ React.createElement(LiveValue, { id: "sb.uptime", value: ch.sys ? ch.sys.uptime_s : "\u2014", format: () => _navUptime(ch.sys ? ch.sys.uptime_s : null) })), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("span", { style: { color: engineTone } }, "\u25CF engine"), /* @__PURE__ */ React.createElement("span", { style: { color: sseTone } }, "\u25CF sse"), /* @__PURE__ */ React.createElement("span", { title: feed.title, style: {
    color: feed.tone === "ok" ? "var(--qe-green)" : feed.tone === "warn" ? "var(--qe-amber)" : feed.tone === "err" ? "var(--qe-red)" : "var(--qe-muted)"
  } }, "\u25CF feed"), /* @__PURE__ */ React.createElement(LiveClock, { id: "sb.clock", format: qeClockFmt, style: { color: "var(--qe-muted)" } }));
};
Object.assign(window, {
  NAV_ITEMS,
  TopNavStd,
  WorkspaceBar,
  StatusFooter,
  QE_CLOCK_OFFSET,
  qeClockFmt
});

;

/* ==== notifications.jsx ==== */
const NotifCtx = React.createContext(null);
const N_CHANNELS = ["FILLS", "RISK", "LINK", "SYSTEM"];
const N_ACTIONS = {
  FILLS: ["View order", "order detail"],
  RISK: ["Review risk", "risk panel"],
  SYSTEM: ["Details", "system log"],
  LINK: ["Link trades", "linkage queue"]
};
const nSev = (pri) => pri === "halt" ? "var(--qe-red)" : pri === "risk" ? "var(--qe-amber)" : "var(--qe-line-2)";
const _rnd = (a) => a[Math.floor(Math.random() * a.length)];
const _px = (n, d = 1) => n.toFixed(d);
const N_SCENARIOS = {
  fill: () => {
    const side = _rnd(["BUY", "SELL"]);
    const s = _rnd([["BTC", 93580, 0.04], ["ETH", 3208, 0.18], ["SOL", 139, 12]]);
    const p = s[1] * (1 + (Math.random() - 0.5) * 4e-3);
    return {
      ch: "FILLS",
      pri: "routine",
      head: `FILLED \xB7 ${side} ${_px(s[2] * (0.5 + Math.random()), 3)} ${s[0]}`,
      detail: `@ ${_px(p, 1)} \xB7 slippage +${_px(Math.random() * 0.9, 1)}bp \xB7 order #A${1900 + Math.floor(Math.random() * 99)}`
    };
  },
  partial: () => {
    const s = _rnd([["ETH", 3208], ["SOL", 139], ["BTC", 93580]]);
    return {
      ch: "FILLS",
      pri: "routine",
      head: `Order #A${1880 + Math.floor(Math.random() * 40)} partially filled ${40 + Math.floor(Math.random() * 5) * 10}%`,
      detail: `SELL ${_px(Math.random(), 3)} / ${_px(1 + Math.random(), 3)} ${s[0]} @ ${_px(s[1], 1)}`
    };
  },
  risk: () => _rnd([
    { ch: "RISK", pri: "risk", head: `Weekly loss ${78 + Math.floor(Math.random() * 12)}% of limit`, detail: `\u2212$${(3.1 + Math.random() * 0.6).toFixed(2)} of \u2212$4.11 \xB7 1 more stop trips the cap` },
    { ch: "RISK", pri: "risk", head: `Daily drawdown ${_px(3.5 + Math.random(), 1)}% \u2014 approaching 5.0% cap`, detail: "position sizing throttled to \xD70.5" }
  ]),
  halt: () => ({ ch: "RISK", pri: "halt", head: "CALCULATOR BLOCKED \u2014 hard-stop breached", detail: "Realized DD 5.04% > 5.00% cap \xB7 new entries gated \xB7 open positions unaffected" }),
  link: () => {
    const nl = (window.L_NEEDS_LINK || []).filter((o) => o.status === "NEEDS_MANUAL_REVIEW" || o.status === "UNLINKED").length || 5;
    const nc = (window.L_CLOSES || []).filter((c) => c.pending_reason).length || 3;
    return { ch: "LINK", pri: "risk", head: `Calc link window closes in 0${2 + Math.floor(Math.random() * 4)}:${10 + Math.floor(Math.random() * 49)}`, detail: `triage ${nl + nc} open \xB7 ${nl} orders below 6/6 \xB7 ${nc} closes to review` };
  },
  ws: () => _rnd([
    { ch: "SYSTEM", pri: "routine", head: "Market WS reconnected", detail: "2 streams \xB7 108ms \xB7 gap 1.4s recovered" }
  ])
};
const N_STREAM = ["fill", "partial", "risk", "link", "ws"];
function nRel(ts, now) {
  const s = Math.max(0, Math.round((now - ts) / 1e3));
  if (s < 5) return "now";
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m";
  return Math.floor(s / 3600) + "h";
}
function nAbs(ts) {
  const d = new Date(ts + (window.QE_CLOCK_OFFSET || 0));
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}
let _nac = null;
function nBeep(pri) {
  try {
    _nac = _nac || new (window.AudioContext || window.webkitAudioContext)();
    if (_nac.state === "suspended") _nac.resume();
    const seq = pri === "halt" ? [[330, 0], [220, 0.13]] : pri === "risk" ? [[520, 0]] : [[760, 0]];
    seq.forEach(([f, t]) => {
      const o = _nac.createOscillator(), g = _nac.createGain();
      o.type = pri === "routine" ? "sine" : "triangle";
      o.frequency.value = f;
      const t0 = _nac.currentTime + t;
      g.gain.setValueAtTime(1e-4, t0);
      g.gain.exponentialRampToValueAtTime(pri === "routine" ? 0.06 : 0.12, t0 + 0.01);
      g.gain.exponentialRampToValueAtTime(1e-4, t0 + 0.18);
      o.connect(g);
      g.connect(_nac.destination);
      o.start(t0);
      o.stop(t0 + 0.2);
    });
  } catch (e) {
  }
}
const NotifBell = () => {
  const ctx = React.useContext(NotifCtx);
  const count = ctx ? ctx.unread : 0;
  const active = ctx ? ctx.open : false;
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      onClick: ctx ? ctx.toggleOpen : void 0,
      title: "Notifications",
      style: {
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 22,
        height: 22,
        cursor: ctx ? "pointer" : "default",
        border: `1px solid ${active ? "var(--qe-cyan)" : "var(--qe-line)"}`,
        background: active ? "var(--qe-bg-cyan)" : "transparent",
        color: active ? "var(--qe-cyan)" : "var(--qe-sub)"
      }
    },
    /* @__PURE__ */ React.createElement("svg", { width: "13", height: "13", viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: "1.3" }, /* @__PURE__ */ React.createElement("path", { d: "M8 1.6c-2.2 0-3.7 1.7-3.7 3.9 0 3.4-1 4.4-1.4 4.8h10.2c-.4-.4-1.4-1.4-1.4-4.8 0-2.2-1.5-3.9-3.7-3.9Z" }), /* @__PURE__ */ React.createElement("path", { d: "M6.5 12.6a1.5 1.5 0 0 0 3 0" })),
    count > 0 && /* @__PURE__ */ React.createElement("span", { style: {
      position: "absolute",
      top: -6,
      right: -6,
      minWidth: 14,
      height: 14,
      padding: "0 3px",
      background: "var(--qe-red)",
      color: "var(--qe-text)",
      fontFamily: "var(--qe-mono)",
      fontSize: "0.5rem",
      fontWeight: 800,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      lineHeight: 1,
      border: "1px solid var(--qe-bg)"
    } }, count)
  );
};
const HALT_KEY = "qe.haltUntil";
const HALT_AT_KEY = "qe.haltAt";
function readHaltUntil() {
  return 0;
}
function readHaltAt() {
  return 0;
}
const fmtHaltAt = (ts) => {
  try {
    return new Date(ts + (window.QE_CLOCK_OFFSET || 0)).toISOString().slice(11, 19);
  } catch (e) {
    return "";
  }
};
function nextHaltRelease() {
  const d = /* @__PURE__ */ new Date();
  d.setUTCHours(24, 0, 0, 0);
  return d.getTime();
}
function fmtHaltLeft(ms) {
  if (ms < 0) ms = 0;
  const dd = Math.floor(ms / 864e5), hh = Math.floor(ms % 864e5 / 36e5), mm = Math.floor(ms % 36e5 / 6e4), ss = Math.floor(ms % 6e4 / 1e3);
  return `${dd}d ${String(hh).padStart(2, "0")}h ${String(mm).padStart(2, "0")}m ${String(ss).padStart(2, "0")}s`;
}
const HALT_GRASS = [
  "step away \u2014 go touch some grass.",
  "markets will survive without you. go outside.",
  "breathe, hydrate, go touch some grass.",
  "the highest-EV trade right now is a walk."
];
const NotifBanner = () => {
  const ctx = React.useContext(NotifCtx);
  if (!ctx || !ctx.haltUntil) return null;
  const rem = ctx.haltUntil - Date.now();
  if (rem <= 0) return null;
  const grass = HALT_GRASS[Math.floor(ctx.haltUntil / 6e4) % HALT_GRASS.length];
  return /* @__PURE__ */ React.createElement(
    Banner,
    {
      tone: "err",
      tag: "HALT",
      time: ctx.haltAt > 0 ? fmtHaltAt(ctx.haltAt) : null,
      title: "CALCULATOR BLOCKED",
      detail: /* @__PURE__ */ React.createElement(React.Fragment, null, "hard-stop breached \xB7 new entries gated \xB7 open positions unaffected \xB7 ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, grass)),
      releaseIn: fmtHaltLeft(rem)
    }
  );
};
const NotifRow = ({ ev, now, muted, onRead, onDismiss, onAction }) => {
  const sev = nSev(ev.pri);
  const colored = ev.pri !== "routine";
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      className: "qe-notif-row",
      onClick: () => ev.unread && onRead(ev.id),
      style: {
        position: "relative",
        display: "flex",
        gap: 9,
        padding: "5px 11px 6px 12px",
        cursor: ev.unread ? "pointer" : "default",
        borderBottom: "1px solid var(--qe-faint)",
        background: ev.unread ? "color-mix(in srgb, var(--qe-text) 2%, transparent)" : "transparent",
        opacity: muted ? 0.5 : 1
      }
    },
    ev.unread && /* @__PURE__ */ React.createElement("span", { style: { position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: sev } }),
    /* @__PURE__ */ React.createElement("div", { style: { minWidth: 0, flex: 1, display: "flex", flexDirection: "column", gap: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.14em", color: "var(--qe-muted)" } }, ev.ch), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", letterSpacing: "0.02em", color: "var(--qe-muted)" } }, "\xB7 ", nAbs(ev.ts)), colored && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.1em", color: sev } }, ev.pri === "halt" ? "HALT" : "RISK"), muted && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", letterSpacing: "0.08em", color: "var(--qe-muted)" } }, "MUTED"), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("div", { className: "qe-notif-actions", style: { display: "flex", gap: 4, alignItems: "center" } }, onAction && /* @__PURE__ */ React.createElement("button", { title: "Open", onClick: (e) => {
      e.stopPropagation();
      onAction(ev);
    }, className: "qe-notif-cta" }, (N_ACTIONS[ev.ch] || ["View"])[0]), ev.unread && /* @__PURE__ */ React.createElement("button", { title: "Mark read", onClick: (e) => {
      e.stopPropagation();
      onRead(ev.id);
    }, className: "qe-notif-ib" }, "\u2713"), /* @__PURE__ */ React.createElement("button", { title: "Dismiss", onClick: (e) => {
      e.stopPropagation();
      onDismiss(ev.id);
    }, className: "qe-notif-ib" }, "\xD7")), /* @__PURE__ */ React.createElement("span", { className: "qe-notif-time", style: { fontFamily: "var(--qe-mono)", fontSize: "0.54rem", color: "var(--qe-muted)" } }, nRel(ev.ts, now)), ev.unread && /* @__PURE__ */ React.createElement("span", { style: { width: 5, height: 5, borderRadius: "50%", background: sev, flexShrink: 0 } })), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.72rem", lineHeight: 1.2, fontWeight: ev.unread ? 600 : 500, color: ev.unread ? "var(--qe-text)" : "var(--qe-sub)" } }, ev.head), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.54rem", color: "var(--qe-muted)", lineHeight: 1.28 } }, ev.detail))
  );
};
const NotifChip = ({ label, count, active, muted, onFilter, onMute }) => /* @__PURE__ */ React.createElement(Chip, { label, count, active, muted, onClick: onFilter, onMute });
const NotifSeg = ({ options, active, onPick }) => /* @__PURE__ */ React.createElement("div", { style: { display: "inline-flex", border: "1px solid var(--qe-line)" } }, options.map((o, i) => /* @__PURE__ */ React.createElement("button", { key: o, onClick: () => onPick(o), style: {
  border: "none",
  borderRight: i < options.length - 1 ? "1px solid var(--qe-line)" : "none",
  cursor: "pointer",
  padding: "2px 9px",
  fontFamily: "var(--qe-mono)",
  fontSize: "0.56rem",
  fontWeight: 600,
  letterSpacing: "0.04em",
  background: o === active ? "var(--qe-active)" : "transparent",
  color: o === active ? "var(--qe-text)" : "var(--qe-muted)"
} }, o)));
const NotifSwitch = ({ label, on, onToggle, title, disabled = false }) => /* @__PURE__ */ React.createElement(Switch, { label, checked: on, onChange: onToggle, title, disabled });
const NotifToast = ({ ev, onClick, onClose }) => /* @__PURE__ */ React.createElement(
  Toast,
  {
    tone: ev.pri === "halt" ? "err" : ev.pri === "risk" ? "warn" : "mute",
    tag: ev.ch,
    time: nAbs(ev.ts),
    title: ev.head,
    detail: ev.detail,
    onClose,
    onClick
  }
);
const NotifDemo = ({ fire, autostream, onAuto, onReset, onHide }) => {
  const Btn = ({ label, k, danger }) => /* @__PURE__ */ React.createElement("button", { onClick: () => fire(k), className: "qe-btn qe-btn-sm" + (danger ? " qe-btn-danger" : ""), style: { justifyContent: "center" } }, label);
  return /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", left: 10, bottom: 50, zIndex: 70, width: 198, background: "var(--qe-card)", border: "1px solid var(--qe-line-2)", boxShadow: "0 10px 30px rgba(0,0,0,0.6)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, padding: "5px 9px", borderBottom: "1px solid var(--qe-line)", background: "var(--qe-panel)" } }, /* @__PURE__ */ React.createElement("span", { style: { width: 6, height: 6, background: "var(--qe-cyan)" } }), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.54rem", fontWeight: 800, letterSpacing: "0.14em", color: "var(--qe-sub)" } }, "DEMO \xB7 FIRE EVENTS"), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { onClick: onHide, title: "Collapse demo panel", className: "qe-btn qe-btn-ghost qe-btn-sm", style: { height: 16, padding: "0 5px" } }, "\u2013")), /* @__PURE__ */ React.createElement("div", { style: { padding: 8, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5 } }, /* @__PURE__ */ React.createElement(Btn, { label: "Fill", k: "fill" }), /* @__PURE__ */ React.createElement(Btn, { label: "Partial", k: "partial" }), /* @__PURE__ */ React.createElement(Btn, { label: "Risk", k: "risk" }), /* @__PURE__ */ React.createElement(Btn, { label: "Link", k: "link" }), /* @__PURE__ */ React.createElement(Btn, { label: "WS recon", k: "ws" }), /* @__PURE__ */ React.createElement(Btn, { label: "Burst \xD75", k: "burst" }), /* @__PURE__ */ React.createElement("button", { onClick: () => fire("halt"), className: "qe-btn qe-btn-sm qe-btn-danger", style: { gridColumn: "1 / -1", justifyContent: "center" } }, "\u26D4 HARD-STOP HALT")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, padding: "6px 9px", borderTop: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(NotifSwitch, { label: "Auto-stream", on: autostream, onToggle: onAuto }), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { onClick: onReset, className: "qe-btn qe-btn-ghost qe-btn-sm" }, "RESET")));
};
function NotificationProvider({ children, demo = false }) {
  const [events, setEvents] = React.useState([]);
  const [open, setOpen] = React.useState(false);
  const [filter, setFilter] = React.useState("All");
  const [priority, setPriority] = React.useState("All");
  const [muted, setMuted] = React.useState({});
  const [sound, setSound] = React.useState(true);
  const [demoOpen, setDemoOpen] = React.useState(false);
  const [desktop, setDesktop] = React.useState(false);
  const [dnd, setDnd] = React.useState(false);
  const [haltUntil, setHaltUntil] = React.useState(readHaltUntil);
  const [haltAt, setHaltAt] = React.useState(readHaltAt);
  const [toasts, setToasts] = React.useState([]);
  const [autostream, setAutostream] = React.useState(false);
  const [now, setNow] = React.useState(Date.now());
  const idRef = React.useRef(1);
  React.useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1e3);
    return () => clearInterval(t);
  }, []);
  const banner = haltUntil > now;
  React.useEffect(() => {
    if (haltUntil && Date.now() >= haltUntil) {
      setHaltUntil(0);
      try {
        localStorage.removeItem(HALT_KEY);
      } catch (e) {
      }
      setHaltAt(0);
      try {
        localStorage.removeItem(HALT_AT_KEY);
      } catch (e) {
      }
      setEvents((list) => [{ id: "e" + idRef.current++, ch: "SYSTEM", pri: "routine", head: "Trading halt released", detail: "Daily hard-stop window elapsed \xB7 trading re-enabled", ts: Date.now(), unread: true }, ...list]);
    }
  }, [now, haltUntil]);
  const flags = React.useRef({});
  flags.current = { muted, sound, desktop, dnd, open };
  const removeToast = (id) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const sinceRef = React.useRef(-1);
  React.useEffect(() => {
    let alive = true;
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const r = await fetch(
          "/notifications/poll?since=" + sinceRef.current,
          { headers: { Accept: "application/json" } }
        );
        if (!r.ok) return;
        const d = await r.json();
        if (!alive || !d || typeof d.latest_id !== "number") return;
        const priming = sinceRef.current < 0;
        sinceRef.current = d.latest_id;
        if (priming) return;
        (d.notifications || []).forEach((n) => {
          const ev = {
            id: "n" + n.id,
            ch: N_CHANNELS.indexOf(n.ch) >= 0 ? n.ch : "SYSTEM",
            pri: n.pri || "routine",
            head: n.head || n.message || "",
            detail: n.detail || "",
            ts: n.ts || n.ts_ms || Date.now(),
            unread: true
          };
          setEvents((list) => [ev, ...list].slice(0, 200));
          const f = flags.current;
          if (!(f.dnd || f.muted[ev.ch])) {
            if (f.sound) nBeep(ev.pri);
            setToasts((ts) => [ev, ...ts].slice(0, 4));
            setTimeout(() => removeToast(ev.id), 5200);
          }
        });
      } catch (e) {
      } finally {
        inFlight = false;
      }
    };
    poll();
    const t = setInterval(poll, 5e3);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  const pushEvent = React.useCallback((key) => {
    const tpl = N_SCENARIOS[key]();
    if (!tpl) return;
    const ev = { ...tpl, id: "e" + idRef.current++, ts: Date.now(), unread: true };
    setEvents((list) => [ev, ...list]);
    if (ev.pri === "halt") {
      const until = nextHaltRelease();
      setHaltUntil(until);
      try {
        localStorage.setItem(HALT_KEY, String(until));
      } catch (e) {
      }
      const at = Date.now();
      setHaltAt(at);
      try {
        localStorage.setItem(HALT_AT_KEY, String(at));
      } catch (e) {
      }
    }
    const f = flags.current;
    const suppressed = f.dnd || f.muted[ev.ch];
    if (!suppressed) {
      if (f.sound) nBeep(ev.pri);
      setToasts((ts) => [ev, ...ts].slice(0, 4));
      setTimeout(() => removeToast(ev.id), 5200);
      if (f.desktop && "Notification" in window && Notification.permission === "granted") {
        try {
          new Notification(ev.ch + " \xB7 " + ev.head, { body: ev.detail });
        } catch (e) {
        }
      }
    }
  }, []);
  const fire = (key) => {
    if (key === "burst") {
      ["fill", "link", "risk", "ws", "partial"].forEach((k, i) => setTimeout(() => pushEvent(k), i * 420));
      return;
    }
    pushEvent(key);
  };
  React.useEffect(() => {
    if (!autostream) return;
    const t = setInterval(() => pushEvent(N_STREAM[Math.floor(Math.random() * N_STREAM.length)]), 4500);
    return () => clearInterval(t);
  }, [autostream, pushEvent]);
  const markRead = (id) => setEvents((l) => l.map((e) => e.id === id ? { ...e, unread: false } : e));
  const dismiss = (id) => setEvents((l) => l.filter((e) => e.id !== id));
  const actionToast = (label, target) => {
    const ev = { id: "act" + idRef.current++, ch: "", pri: "routine", head: "\u2192 " + label, detail: target, ts: Date.now() };
    setToasts((ts) => [ev, ...ts].slice(0, 4));
    setTimeout(() => removeToast(ev.id), 3200);
  };
  const handleAction = (ev) => {
    const [label, target] = N_ACTIONS[ev.ch] || ["View", "detail"];
    markRead(ev.id);
    setOpen(false);
    actionToast(label, target);
  };
  const markAll = () => setEvents((l) => l.map((e) => ({ ...e, unread: false })));
  const clearAll = () => setEvents([]);
  const toggleMute = (ch) => setMuted((m) => ({ ...m, [ch]: !m[ch] }));
  const toggleDesktop = () => setDesktop((v) => !v);
  const reset = () => {
    setEvents([]);
    setHaltUntil(0);
    try {
      localStorage.removeItem(HALT_KEY);
    } catch (e) {
    }
    setHaltAt(0);
    try {
      localStorage.removeItem(HALT_AT_KEY);
    } catch (e) {
    }
    setToasts([]);
    setFilter("All");
    setPriority("All");
    setMuted({});
  };
  const unread = events.filter((e) => e.unread && !muted[e.ch]).length;
  const counts = N_CHANNELS.reduce((a, ch) => (a[ch] = events.filter((e) => e.ch === ch).length, a), {});
  const priPass = (e) => priority === "All" ? true : priority === "Risk+" ? e.pri === "risk" || e.pri === "halt" : e.pri === "halt";
  const visible = events.filter((e) => (filter === "All" || e.ch === filter) && priPass(e));
  const justNow = visible.filter((e) => now - e.ts < 12e4);
  const earlier = visible.filter((e) => now - e.ts >= 12e4);
  const ctx = { unread, open, banner, haltUntil, haltAt, toggleOpen: () => setOpen((o) => !o) };
  const navH = banner ? 84 : 54;
  const Group = ({ title, rows }) => rows.length === 0 ? null : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { padding: "4px 11px 3px", fontFamily: "var(--qe-ui)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.16em", color: "var(--qe-muted)", textTransform: "uppercase" } }, title), rows.map((ev) => /* @__PURE__ */ React.createElement(NotifRow, { key: ev.id, ev, now, muted: !!muted[ev.ch], onRead: markRead, onDismiss: dismiss, onAction: handleAction })));
  return /* @__PURE__ */ React.createElement(NotifCtx.Provider, { value: ctx }, /* @__PURE__ */ React.createElement("div", { style: { position: "relative", height: "100%", width: "100%", overflow: "hidden" } }, children, open && /* @__PURE__ */ React.createElement("div", { onClick: () => setOpen(false), style: { position: "absolute", top: navH, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.4)", zIndex: 55 } }), open && /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", top: navH, right: 0, bottom: 0, width: 362, zIndex: 58, background: "var(--qe-card)", borderLeft: "1px solid var(--qe-line-2)", borderTop: "1px solid var(--qe-line-2)", boxShadow: "-14px 0 40px rgba(0,0,0,0.6)", display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0, padding: "8px 11px", borderBottom: "1px solid var(--qe-line)", display: "flex", flexDirection: "column", gap: 7 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontWeight: 700, fontSize: "0.72rem", letterSpacing: "0.12em", color: "var(--qe-text)" } }, "NOTIFICATIONS"), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.56rem", color: unread ? "var(--qe-sub)" : "var(--qe-muted)" } }, unread, " unread"), dnd && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.1em", color: "var(--qe-amber)", border: "1px solid var(--qe-amber)", padding: "0 4px" } }, "DND"), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { onClick: markAll, className: "qe-btn qe-btn-ghost qe-btn-sm", style: { opacity: unread ? 1 : 0.4 } }, "MARK ALL READ"), /* @__PURE__ */ React.createElement("button", { onClick: clearAll, className: "qe-btn qe-btn-ghost qe-btn-sm", style: { opacity: events.length ? 1 : 0.4 } }, "CLEAR"), /* @__PURE__ */ React.createElement("span", { onClick: () => setOpen(false), title: "Close", style: { color: "var(--qe-muted)", fontSize: "0.95rem", cursor: "pointer", paddingLeft: 2 } }, "\xD7")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 4 } }, /* @__PURE__ */ React.createElement(NotifChip, { label: "All", count: events.length, active: filter === "All", onFilter: () => setFilter("All") }), N_CHANNELS.map((ch) => /* @__PURE__ */ React.createElement(NotifChip, { key: ch, label: ch, count: counts[ch], active: filter === ch, muted: !!muted[ch], onFilter: () => setFilter(ch), onMute: () => toggleMute(ch) }))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.52rem", fontWeight: 700, letterSpacing: "0.12em", color: "var(--qe-muted)", textTransform: "uppercase" } }, "PRIORITY"), /* @__PURE__ */ React.createElement(NotifSeg, { options: ["All", "Risk+", "Halt"], active: priority, onPick: setPriority }))), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, overflowY: "auto" } }, visible.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "qe-empty", style: { margin: 12 } }, /* @__PURE__ */ React.createElement("div", { className: "qe-empty-glyph" }, "\u2014 \u2014 \u2014"), /* @__PURE__ */ React.createElement("div", { className: "qe-empty-msg" }, events.length ? "Nothing matches this filter" : "No notifications"), events.length > 0 && /* @__PURE__ */ React.createElement("button", { onClick: () => {
    setFilter("All");
    setPriority("All");
  }, className: "qe-btn qe-btn-sm qe-empty-cta" }, "Clear filters")) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(Group, { title: "Just now", rows: justNow }), /* @__PURE__ */ React.createElement(Group, { title: "Earlier today", rows: earlier }))), /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0, padding: "7px 11px", borderTop: "1px solid var(--qe-line)", background: "var(--qe-panel)", display: "flex", alignItems: "center", gap: 14 } }, /* @__PURE__ */ React.createElement(NotifSwitch, { label: "Sound", on: sound, onToggle: () => setSound((v) => !v), title: "Play a cue on incoming" }), /* @__PURE__ */ React.createElement(
    NotifSwitch,
    {
      label: "Desktop",
      on: false,
      disabled: true,
      title: "Desktop notifications are deferred (plan \xA77) \u2014 not yet implemented"
    }
  ), /* @__PURE__ */ React.createElement(NotifSwitch, { label: "DND", on: dnd, onToggle: () => setDnd((v) => !v), title: "Do not disturb" }))), toasts.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", top: banner ? 92 : 62, right: open ? 370 : 8, zIndex: 60, display: "flex", flexDirection: "column", gap: 5, transition: "right .18s ease" } }, toasts.map((t) => /* @__PURE__ */ React.createElement(NotifToast, { key: t.id, ev: t, onClick: () => {
    setOpen(true);
    markRead(t.id);
    removeToast(t.id);
  }, onClose: () => removeToast(t.id) }))), demo && (demoOpen ? /* @__PURE__ */ React.createElement(NotifDemo, { fire, autostream, onAuto: () => setAutostream((v) => !v), onReset: reset, onHide: () => setDemoOpen(false) }) : /* @__PURE__ */ React.createElement("button", { onClick: () => setDemoOpen(true), title: "Open the notification demo panel", className: "qe-btn qe-btn-sm", style: { position: "absolute", left: 10, bottom: 50, zIndex: 70, opacity: 0.8 } }, "\u25C6 DEMO"))));
}
Object.assign(window, { NotifCtx, NotifBell, NotifBanner, NotifRow, NotificationProvider });

;

/* ==== sse-adapter.js ==== */
const QE_SSE = function() {
  const CHANNELS = ["position_update", "equity_update", "dd_state", "order_update", "fill"];
  const chanSubs = /* @__PURE__ */ new Map();
  const values = /* @__PURE__ */ new Map();
  const valSubs = /* @__PURE__ */ new Map();
  let source = null;
  let status = "idle";
  const accountId = () => window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.activeAccountId;
  function fanout(map, key, arg) {
    const subs = map.get(key);
    if (subs) subs.forEach((fn) => {
      try {
        fn(arg);
      } catch (e) {
      }
    });
  }
  function connect() {
    if (source) return status;
    const id = accountId();
    if (id == null || typeof EventSource === "undefined") {
      status = "disabled";
      return status;
    }
    status = "connecting";
    try {
      source = new EventSource("/stream/account/" + id);
    } catch (e) {
      status = "error";
      return status;
    }
    source.onopen = () => {
      status = "open";
    };
    source.onerror = () => {
      status = "error";
    };
    CHANNELS.forEach((ch) => {
      source.addEventListener(ch, (ev) => {
        let data;
        try {
          data = JSON.parse(ev.data);
        } catch (e) {
          return;
        }
        fanout(chanSubs, ch, data);
      });
    });
    return status;
  }
  function disconnect() {
    if (source) {
      try {
        source.close();
      } catch (e) {
      }
      source = null;
    }
    status = "idle";
  }
  return {
    connect,
    disconnect,
    status: () => status,
    channels: CHANNELS.slice(),
    /* Subscribe to a raw channel's decoded payloads. Returns an unsubscribe fn. */
    onChannel(channel, fn) {
      if (!chanSubs.has(channel)) chanSubs.set(channel, /* @__PURE__ */ new Set());
      chanSubs.get(channel).add(fn);
      return () => {
        const s = chanSubs.get(channel);
        if (s) s.delete(fn);
      };
    },
    /* data-live-id registry — P1 maps channel payloads → live-id values here so
       leaf LiveValue spans re-render without touching their surrounding pane. */
    setValue(liveId, v) {
      values.set(liveId, v);
      fanout(valSubs, liveId, v);
    },
    getValue(liveId) {
      return values.get(liveId);
    },
    onValue(liveId, fn) {
      if (!valSubs.has(liveId)) valSubs.set(liveId, /* @__PURE__ */ new Set());
      valSubs.get(liveId).add(fn);
      return () => {
        const s = valSubs.get(liveId);
        if (s) s.delete(fn);
      };
    }
  };
}();
const useSSEChannel = (channel) => {
  const [payload, setPayload] = React.useState(null);
  React.useEffect(() => QE_SSE.onChannel(channel, setPayload), [channel]);
  return payload;
};
const useLiveId = (liveId, initial) => {
  const [v, setV] = React.useState(() => QE_SSE.getValue(liveId) !== void 0 ? QE_SSE.getValue(liveId) : initial);
  React.useEffect(() => QE_SSE.onValue(liveId, setV), [liveId]);
  return v;
};
QE_SSE.connect();
Object.assign(window, { QE_SSE, useSSEChannel, useLiveId });

;

/* ==== dash-tiled.jsx ==== */
const QE_DASH = /* @__PURE__ */ function() {
  const state = {
    equity: {},
    risk: {},
    journal: {},
    regime: null,
    positions: [],
    // snapshot rows; SSE position_update refreshes upnl/pct
    st: {},
    // /api/state (halted, blocked, dd_state, weekly_pnl_state, …)
    macro: [],
    // /api/regime/signals/latest
    log: [],
    // engine-log lines, newest-first for the prepend feed
    logCursor: 0,
    loaded: false,
    // per-source data-pipe state for qeFootState (DESIGN.md §5 4-tier foots)
    net: { snapshot: {}, st: {}, macro: {}, log: {} }
  };
  const subs = /* @__PURE__ */ new Set();
  const notify = () => subs.forEach((f) => {
    try {
      f();
    } catch (e) {
    }
  });
  async function _json(url, key) {
    const t0 = performance.now();
    try {
      const d = await _ptJson(url);
      if (key) state.net[key] = { err: null, ms: performance.now() - t0 };
      return d;
    } catch (err) {
      if (key) {
        state.net[key] = { ...state.net[key], err };
        notify();
      }
      throw err;
    }
  }
  const _sideKey = (s) => (s || "").toLowerCase().startsWith("l") ? "L" : "S";
  const _rowKey = (sym, side) => sym + "|" + _sideKey(side);
  async function loadSnapshot() {
    try {
      const s = await _json("/api/dashboard/snapshot", "snapshot");
      state.equity = s.equity || {};
      state.risk = s.risk || {};
      state.journal = s.journal || {};
      state.regime = s.regime || null;
      if (Array.isArray(s.positions)) {
        state.positions = s.positions.map((r) => ({ ...r, _k: _rowKey(r.sym, r.side) }));
      }
      state.loaded = true;
      notify();
    } catch (e) {
    }
  }
  async function loadState() {
    try {
      state.st = await _json("/api/state", "st");
      notify();
    } catch (e) {
    }
  }
  async function loadMacro() {
    try {
      const m = await _json("/api/regime/signals/latest", "macro");
      state.macro = m.signals || [];
      notify();
    } catch (e) {
    }
  }
  async function loadLog() {
    try {
      const d = await _json("/api/engine/log?since=" + state.logCursor + "&limit=60", "log");
      const lines = d.lines || [];
      if (lines.length) {
        state.log = [...lines.slice().reverse(), ...state.log].slice(0, 60);
        state.logCursor = d.latest_id || state.logCursor;
        notify();
      } else if (d.latest_id != null) {
        state.logCursor = d.latest_id;
        notify();
      }
    } catch (e) {
    }
  }
  function _wireSSE() {
    if (typeof window.QE_SSE === "undefined") return;
    window.QE_SSE.onChannel("equity_update", (p) => {
      state.equity = {
        ...state.equity,
        total_equity: p.total_equity != null ? p.total_equity : state.equity.total_equity,
        available_margin: p.available_margin != null ? p.available_margin : state.equity.available_margin,
        unrealized_pnl: p.unrealized_pnl != null ? p.unrealized_pnl : state.equity.unrealized_pnl
      };
      notify();
    });
    window.QE_SSE.onChannel("position_update", (p) => {
      const list = Array.isArray(p.positions) ? p.positions : [];
      const prev = {};
      state.positions.forEach((r) => {
        prev[r._k || _rowKey(r.sym, r.side)] = r;
      });
      state.positions = list.map((x) => {
        const k = _rowKey(x.symbol, x.side);
        const r = prev[k] || {};
        const upnl = x.upnl != null ? x.upnl : r.upnl;
        const notional = r.notional || 0;
        const pct = notional ? +(upnl / Math.abs(notional) * 100).toFixed(2) : r.pct || 0;
        return {
          ...r,
          _k: k,
          sym: x.symbol,
          side: x.side != null ? x.side : r.side,
          size: x.size != null ? x.size : r.size,
          upnl,
          pct
        };
      });
      notify();
    });
    window.QE_SSE.onChannel("dd_state", (p) => {
      state.st = {
        ...state.st,
        dd_state: p.to != null ? p.to : state.st.dd_state,
        drawdown: p.drawdown != null ? p.drawdown : state.st.drawdown
      };
      notify();
    });
  }
  let started = false, wired = false;
  const _timers = [];
  function start() {
    if (!wired) {
      _wireSSE();
      wired = true;
    }
    if (started) return;
    started = true;
    loadSnapshot();
    loadState();
    loadMacro();
    loadLog();
    _timers.push(setInterval(loadState, 5e3));
    _timers.push(setInterval(loadLog, 4e3));
    _timers.push(setInterval(loadMacro, 6e4));
    _timers.push(setInterval(loadSnapshot, 15e3));
  }
  function stop() {
    _timers.forEach(clearInterval);
    _timers.length = 0;
    started = false;
  }
  return { start, stop, get: () => state, subscribe(fn) {
    subs.add(fn);
    return () => subs.delete(fn);
  } };
}();
const _dashFoot = (d, key, hasData) => {
  const n = d.net && d.net[key] || {};
  return qeFootState({ loading: n.ms == null && !n.err, err: n.err, hasData: !!hasData, ms: n.ms, retrying: true });
};
const useDash = () => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => QE_DASH.subscribe(force), []);
  return QE_DASH.get();
};
const _n = (v, d = 2) => v == null || isNaN(v) ? "\u2014" : (+v).toFixed(d);
const _sn = (v, d = 2) => v == null || isNaN(v) ? "\u2014" : (v >= 0 ? "+" : "") + (+v).toFixed(d);
const _loc = (v, d = 2) => v == null || isNaN(v) ? "\u2014" : (+v).toLocaleString(void 0, { minimumFractionDigits: d, maximumFractionDigits: d });
const EquityHero = () => {
  const d = useDash();
  const v = d.equity.total_equity;
  const [int, dec] = (v != null && !isNaN(v) ? (+v).toFixed(2) : "0.00").split(".");
  return /* @__PURE__ */ React.createElement("div", { className: "qe-hero-val", style: { fontSize: "1.9rem" } }, /* @__PURE__ */ React.createElement(LiveValue, { id: "acct.eq.int", value: +int, format: (x) => x.toLocaleString() }), /* @__PURE__ */ React.createElement("span", { className: "qe-hero-cents" }, ".", /* @__PURE__ */ React.createElement(LiveValue, { id: "acct.eq.cents", value: dec, format: (x) => x })), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.36em", color: "var(--qe-sub)", fontWeight: 600, marginLeft: 8, verticalAlign: "middle" } }, "USDT"));
};
const DeltaPct = ({ id, value, suffix = "%" }) => {
  const v = value;
  const dir = v == null ? "flat" : v > 1e-3 ? "up" : v < -1e-3 ? "dn" : "flat";
  const col = dir === "up" ? "var(--qe-green)" : dir === "dn" ? "var(--qe-red)" : "var(--qe-sub)";
  return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: col, fontSize: "var(--qe-fs-md)", fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 4 } }, dir === "up" ? /* @__PURE__ */ React.createElement("span", { className: "qe-tick qe-tick-up" }) : dir === "dn" ? /* @__PURE__ */ React.createElement("span", { className: "qe-tick qe-tick-dn" }) : null, /* @__PURE__ */ React.createElement(LiveValue, { id, value: v == null ? 0 : v, format: (x) => _sn(x) + suffix, style: { color: col, fontWeight: 700 } }));
};
const _findPos = (positions, k) => positions.find((p) => p._k === k) || {};
const PosMark = ({ r }) => {
  const d = useDash();
  const p = _findPos(d.positions, r._k);
  return /* @__PURE__ */ React.createElement(LiveValue, { id: `pos.${r._k}.mark`, value: p.mark != null ? p.mark : "\u2014", format: (x) => p.mark == null ? "\u2014" : _loc(x, 2), style: { color: "var(--qe-text)", fontWeight: 700 } });
};
const PosPnl = ({ r }) => {
  const d = useDash();
  const p = _findPos(d.positions, r._k);
  const pnl = p.upnl != null ? p.upnl : 0;
  return /* @__PURE__ */ React.createElement(LiveValue, { id: `pos.${r._k}.pnl`, value: pnl, format: (x) => _sn(x), style: { color: pnl >= 0 ? "var(--qe-green)" : "var(--qe-red)", fontWeight: 700 } });
};
const PosPct = ({ r }) => {
  const d = useDash();
  const p = _findPos(d.positions, r._k);
  const pct = p.pct != null ? p.pct : 0;
  return /* @__PURE__ */ React.createElement(LiveValue, { id: `pos.${r._k}.pct`, value: pct, format: (x) => _sn(x) + "%", style: { color: pct >= 0 ? "var(--qe-green)" : "var(--qe-red)", fontWeight: 600 } });
};
const PosAge = ({ r }) => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    const t2 = setInterval(force, 6e4);
    return () => clearInterval(t2);
  }, []);
  const raw = r.entry_ms;
  const t = typeof raw === "number" ? raw : raw ? Date.parse(raw) : NaN;
  if (!t || isNaN(t)) return /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014");
  const s = Math.max(0, Math.floor((Date.now() - t) / 1e3));
  const dd = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  const txt = dd ? `${dd}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
  return /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, txt);
};
const PosMfeMae = ({ r }) => {
  const mfe = r.mfe, mae = r.mae;
  return /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.6rem" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, mfe == null ? "\u2014" : "+" + (+mfe).toFixed(2)), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, " / "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)" } }, mae == null ? "\u2014" : (+mae).toFixed(2)));
};
const PosUnrealSum = () => {
  const d = useDash();
  const s = d.positions.reduce((a, p) => a + (p.upnl || 0), 0);
  return /* @__PURE__ */ React.createElement("span", { style: { color: s >= 0 ? "var(--qe-green)" : "var(--qe-red)" } }, "\u03A3 unrealized ", _sn(s), " USDT");
};
const EquityStatsPane = () => {
  const d = useDash();
  const eq = d.equity;
  const blocks = [
    ["Available", eq.available_margin],
    ["Margin Used", eq.margin_used],
    ["Unrealized", eq.unrealized_pnl],
    ["BOD Equity", eq.bod_equity],
    ["SOW Equity", eq.sow_equity],
    ["Max Eq (BOD)", eq.max_equity],
    ["Min Eq (BOD)", eq.min_equity]
  ];
  return /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Equity",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "LIVE"),
      foot: _dashFoot(d, "snapshot", eq.total_equity != null)
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Total"), /* @__PURE__ */ React.createElement(EquityHero, null)), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Daily"), /* @__PURE__ */ React.createElement(DeltaPct, { id: "eq.daily", value: eq.daily_pnl_pct })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Weekly"), /* @__PURE__ */ React.createElement(DeltaPct, { id: "eq.weekly", value: eq.weekly_pnl_pct })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Unrealized"), /* @__PURE__ */ React.createElement(LiveValue, { id: "eq.unreal", value: eq.unrealized_pnl == null ? 0 : eq.unrealized_pnl, format: (x) => _sn(x), style: { color: (eq.unrealized_pnl || 0) >= 0 ? "var(--qe-green)" : "var(--qe-red)", fontWeight: 700, fontSize: "var(--qe-fs-md)" } })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Available"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontWeight: 700 } }, _n(eq.available_margin)))), /* @__PURE__ */ React.createElement("div", { className: "qe-divider-h" }), /* @__PURE__ */ React.createElement(FieldList, { cols: 2, dense: true, rows: blocks.map(([label, v]) => ({ label, value: _n(v) })) }))
  );
};
const EquityOhlcChart = React.memo(function EquityOhlcChart2({ tf, onNet, onBar }) {
  const [data, setData] = React.useState([]);
  React.useEffect(() => {
    let alive = true;
    const load = async () => {
      const t0 = performance.now();
      try {
        const j = await _ptJson("/api/dashboard/equity_ohlc?tf=" + tf);
        const rows = (j.candles || []).map((c) => [c.x, c.o, c.c, c.l, c.h]);
        if (alive) {
          setData(rows);
          if (onNet) onNet({ err: null, ms: performance.now() - t0 });
          if (onBar) {
            const n = j.candles || [];
            const last = n[n.length - 1] || null;
            const prev = n.length > 1 ? n[n.length - 2] : last;
            onBar(last ? { o: last.o, h: last.h, l: last.l, prevC: prev ? prev.c : null } : null);
          }
        }
      } catch (err) {
        if (alive && onNet) onNet((n) => ({ ...n, err }));
      }
    };
    load();
    const id = setInterval(load, 5e3);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [tf]);
  return data.length ? /* @__PURE__ */ React.createElement(CandlestickChart, { data }) : /* @__PURE__ */ React.createElement(EmptyState, { tone: "neutral", glyph: "\u3030", msg: "Loading equity\u2026" });
});
const EquityCurvePane = () => {
  const [tf, setTf] = React.useState("1h");
  const [net, setNet] = React.useState({});
  const [bar, setBar] = React.useState(null);
  const d = useDash();
  const c = d.equity.total_equity;
  const chg = c != null && bar && bar.prevC != null ? c - bar.prevC : null;
  return /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Equity Curve",
      hot: true,
      tag: "OHLC",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["1h", "1H"], ["4h", "4H"], ["1d", "1D"], ["1w", "1W"]], value: tf, onChange: setTf }),
      foot: qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: net.ms != null, ms: net.ms, retrying: true }),
      bodyStyle: { padding: 6 }
    },
    /* @__PURE__ */ React.createElement("div", { style: { height: "100%", display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.62rem", display: "flex", gap: 14, flexWrap: "wrap", padding: "2px 4px", alignItems: "baseline" } }, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "O"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)" } }, bar ? "$" + _n(bar.o) : "\u2014")), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "H"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, bar ? "$" + _n(bar.h) : "\u2014")), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "L"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)" } }, bar ? "$" + _n(bar.l) : "\u2014")), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "C"), " ", /* @__PURE__ */ React.createElement(LiveValue, { id: "ohlc.c", value: c == null ? 0 : c, format: (x) => "$" + _n(x), style: { color: "var(--qe-text)", fontWeight: 700 } })), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "Chg"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: chg == null ? "var(--qe-muted)" : chg >= 0 ? "var(--qe-green)" : "var(--qe-red)" } }, chg == null ? "\u2014" : _sn(chg))), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "Bar Range"), " ", /* @__PURE__ */ React.createElement("span", null, bar ? "$" + _n(bar.h - bar.l) : "\u2014")), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { color: net.err ? "var(--qe-red)" : "var(--qe-muted)" } }, net.err ? "stalled" : "poll 5s"))), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0 } }, /* @__PURE__ */ React.createElement(EquityOhlcChart, { tf, onNet: setNet, onBar: setBar })))
  );
};
const _stateTone = (s) => s === "limit" ? "err" : s === "warning" ? "warn" : "ok";
const _stateLabel = (s) => s === "limit" ? "LIMIT" : s === "warning" ? "WARN" : "OK";
const RiskMonitorPane = () => {
  const d = useDash();
  const rk = d.risk, st = d.st;
  const ddState = st.dd_state || rk.dd_state || "ok";
  const enforced = st.dd_enforcement_mode === "enforced";
  return /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Risk Monitor",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement(Badge, { tone: enforced ? "err" : "info" }, enforced ? "ENFORCED" : "ADVISORY"),
      foot: _dashFoot(d, "st", d.st && d.st.dd_state != null)
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 14 } }, /* @__PURE__ */ React.createElement(Gauge, { label: "Net Exposure", value: rk.exposure_pct != null ? rk.exposure_pct / 100 : 0, max: (rk.max_exposure_pct || 500) / 100, current: rk.exposure_pct != null ? _n(rk.exposure_pct / 100, 2) + "\xD7" : "\u2014", maxLabel: `${_n(rk.max_exposure_pct / 100, 1)}\xD7 cap` }), /* @__PURE__ */ React.createElement(Gauge, { label: "Drawdown 30d", value: Math.min(rk.drawdown_pct || 0, rk.max_dd_pct || 10), max: rk.max_dd_pct || 10, current: _n(rk.drawdown_pct) + "%", maxLabel: `${_n(rk.max_dd_pct)}% limit`, ticks: [0.5, 0.8].map((f) => f * (rk.max_dd_pct || 10)) }), /* @__PURE__ */ React.createElement(Gauge, { label: "Weekly Loss", value: Math.max(0, -(d.equity.weekly_pnl_pct || 0)), max: ((d.journal.params || {}).max_weekly_loss_pct || 0.05) * 100, current: d.equity.weekly_pnl_pct != null ? _sn(d.equity.weekly_pnl_pct) + "%" : "\u2014", maxLabel: `${_n(((d.journal.params || {}).max_weekly_loss_pct || 0.05) * 100, 1)}% cap` }), /* @__PURE__ */ React.createElement(Gauge, { label: "Positions", value: rk.positions_open || 0, max: rk.positions_max || 20, current: `${rk.positions_open || 0}/${rk.positions_max || 20}`, maxLabel: "capacity" }), /* @__PURE__ */ React.createElement("div", { className: "qe-divider-h" }), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "DD STATE"), /* @__PURE__ */ React.createElement(Badge, { tone: _stateTone(ddState) }, enforced && ddState === "limit" ? "HALTED" : _stateLabel(ddState))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "WEEKLY"), /* @__PURE__ */ React.createElement(Badge, { tone: _stateTone(st.weekly_pnl_state || rk.weekly_pnl_state) }, _stateLabel(st.weekly_pnl_state || rk.weekly_pnl_state)))), (rk.funding_lines || []).length > 0 && /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)" } }, (rk.funding_lines || []).join(" \xB7 ")), (rk.sector_lines || []).length > 0 && /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, "SECTOR "), (rk.sector_lines || []).join(" \xB7 ")))
  );
};
const OpenPositionsPane = () => {
  const d = useDash();
  const rows = d.positions;
  const longs = rows.filter((r) => (r.side || "").toLowerCase().startsWith("l")).length;
  return /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Open Positions",
      count: rows.length,
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", title: "Size a new position in Pre-Trade", onClick: () => window.qeNav && window.qeNav("Pre-Trade") }, "+ Calc"),
      foot: _dashFoot(d, "snapshot", d.loaded),
      bodyStyle: { padding: 0, display: "flex", flexDirection: "column" }
    },
    /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "_k",
        columns: [
          { key: "sym", label: "SYM", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.sym) },
          {
            key: "side",
            label: "SIDE",
            filter: { label: "SIDE" },
            filterVal: (r) => (r.side || "").toLowerCase().startsWith("l") ? "LONG" : "SHORT",
            render: (r) => {
              const l = (r.side || "").toLowerCase().startsWith("l");
              return /* @__PURE__ */ React.createElement(Badge, { tone: l ? "ok" : "err" }, l ? "LONG" : "SHORT");
            }
          },
          { key: "size", label: "SIZE", align: "right", render: (r) => _loc(r.size, 3) },
          { key: "entry", label: "ENTRY", align: "right", cell: "dim", render: (r) => _loc(r.entry, 2) },
          { key: "mark", label: "MARK", align: "right", render: (r) => /* @__PURE__ */ React.createElement(PosMark, { r }) },
          // PosPnl renders the LIVE upnl; the row's own `pnl` key is not what the
          // cell shows, so sorting used a different number. Bucketing upnl also
          // gives this tile its only stable facet (sym/side go homogeneous on a
          // one-position book, every other column is continuous).
          {
            key: "pnl",
            label: "PnL",
            align: "right",
            sortVal: (r) => r.upnl != null ? r.upnl : null,
            filter: { label: "PnL" },
            filterVal: (r) => (r.upnl || 0) >= 0 ? "UP" : "DOWN",
            render: (r) => /* @__PURE__ */ React.createElement(PosPnl, { r })
          },
          { key: "pct", label: "%", align: "right", render: (r) => /* @__PURE__ */ React.createElement(PosPct, { r }) },
          {
            key: "tpsl",
            label: "TP / SL",
            align: "right",
            sort: false,
            filter: { label: "TP/SL" },
            filterVal: (r) => (r.tp != null ? "TP" : "") + (r.tp != null && r.sl != null ? "+" : "") + (r.sl != null ? "SL" : "") || "NONE",
            render: (r) => /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.6rem" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, r.tp == null ? "\u2014" : _loc(r.tp, 2)), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, " / "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)" } }, r.sl == null ? "\u2014" : _loc(r.sl, 2)))
          },
          { key: "mm", label: "MFE/MAE", align: "right", render: (r) => /* @__PURE__ */ React.createElement(PosMfeMae, { r }) },
          // AGE had opted out of sort because 'age' is not a row field; PosAge
          // parses entry_ms (a MISNAMED ISO string) at render. Sort on the parsed
          // epoch so the header agrees with the cell — ascending = oldest first.
          {
            key: "age",
            label: "AGE",
            align: "right",
            sortVal: (r) => {
              const t = Date.parse(r.entry_ms);
              return isNaN(t) ? null : t;
            },
            render: (r) => /* @__PURE__ */ React.createElement(PosAge, { r })
          }
        ],
        rows,
        emptyMsg: "No open positions",
        summary: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", null, rows.length, " / ", d.risk.positions_max || 20, " positions \xB7 ", longs, " long \xB7 ", rows.length - longs, " short"), /* @__PURE__ */ React.createElement(PosUnrealSum, null))
      }
    )
  );
};
const MacroSignalsPane = () => {
  const d = useDash();
  const sigs = d.macro;
  return /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Macro Signals",
      count: sigs.length,
      style: { height: "100%" },
      foot: _dashFoot(d, "macro", sigs.length > 0)
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, sigs.length === 0 && /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "warn", glyph: "\u2205", msg: "No signal data", hint: "Run regime backfill to populate." }), sigs.map((s) => /* @__PURE__ */ React.createElement("div", { key: s.key, style: { display: "grid", gridTemplateColumns: "84px 1fr 64px 56px", alignItems: "center", gap: 6, padding: "3px 0", borderBottom: "1px dotted var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.6rem", color: "var(--qe-sub)", letterSpacing: "0.04em" } }, s.key), /* @__PURE__ */ React.createElement("div", { style: { height: 18, minWidth: 0 } }, (s.series || []).length > 1 ? /* @__PURE__ */ React.createElement(Sparkline, { data: s.series, height: 18, area: false, color: s.tone === "dn" ? "var(--qe-red)" : s.tone === "up" ? "var(--qe-green)" : "var(--qe-sub)" }) : null), /* @__PURE__ */ React.createElement(LiveValue, { id: `sig.${s.key}`, value: s.v == null ? 0 : s.v, format: (x) => s.v == null ? "\u2014" : (+x).toFixed(2), style: { fontSize: "0.68rem", fontWeight: 700, textAlign: "right", display: "block" } }), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", textAlign: "right", color: s.tone === "up" ? "var(--qe-green)" : s.tone === "dn" ? "var(--qe-red)" : "var(--qe-muted)" } }, s.d == null ? "" : _sn(s.d)))))
  );
};
const MonthlyPane = () => {
  const d = useDash();
  const j = d.journal;
  const daily = j.daily_pnl || [];
  return /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Monthly Analytics Preview",
      tag: j.month_label || void 0,
      style: { height: "100%" },
      foot: _dashFoot(d, "snapshot", d.loaded),
      bodyStyle: { padding: "4px 6px", display: "flex", flexDirection: "column" }
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "minmax(190px, 0.9fr) 1.1fr", gap: 10, height: "100%", minHeight: 0 } }, /* @__PURE__ */ React.createElement(FieldList, { rows: [
      { label: "Period PnL", value: /* @__PURE__ */ React.createElement(React.Fragment, null, _sn(j.monthly_pnl), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.6rem" } }, "(", _sn(j.monthly_pnl_pct), "%)")), color: (j.monthly_pnl || 0) < 0 ? "red" : "green" },
      { label: "QTD", value: /* @__PURE__ */ React.createElement(React.Fragment, null, _sn(j.quarterly_pnl), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.6rem" } }, "(", _sn(j.quarterly_pnl_pct), "%)")) },
      { label: "YTD", value: /* @__PURE__ */ React.createElement(React.Fragment, null, _sn(j.yearly_pnl), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.6rem" } }, "(", _sn(j.yearly_pnl_pct), "%)")) },
      { label: "Trades", value: /* @__PURE__ */ React.createElement(React.Fragment, null, j.trade_count || 0, " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)", fontSize: "0.62rem" } }, "\xB7", j.win_count || 0, "W"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)", fontSize: "0.62rem" } }, "\xB7", j.loss_count || 0, "L")) },
      { label: "Winrate / R", value: `${_n(j.win_rate)}% / ${_n(j.avg_rr)}R` },
      { label: "Max DD", value: `-${_n(j.max_dd_month)}%`, color: "red" }
    ] }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", minHeight: 0 } }, /* @__PURE__ */ React.createElement(Lbl, null, "Daily PnL \xB7 ", j.month_label || "month"), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, marginTop: 2 } }, daily.length ? /* @__PURE__ */ React.createElement(BarChart, { data: daily.map((r) => r.pnl), categories: daily.map((r) => String(r.d || "").slice(8)) }) : /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.6rem", color: "var(--qe-muted)", padding: 8 } }, "no daily snapshots this month"))))
  );
};
const ActiveParamsPane = () => {
  const d = useDash();
  const p = d.journal.params || {};
  const rows = [
    { label: "Risk / trade", value: _n((p.individual_risk_per_trade || 0) * 100) + "%", color: "cyan" },
    { label: "Max W-loss", value: _n((p.max_weekly_loss_pct || 0) * 100) + "%" },
    { label: "Max DD", value: _n((p.max_drawdown_pct || 0) * 100) + "%" },
    { label: "Max exposure", value: _n(p.max_exposure_multiple, 1) + "\xD7" },
    { label: "Max positions", value: String(p.max_open_positions != null ? p.max_open_positions : "\u2014") },
    { label: "Max corr.", value: _n((p.max_correlated_exposure || 0) * 100) + "%" }
  ];
  return /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Active Parameters",
      tag: "VIEW",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", title: "Edit risk parameters in Configuration", onClick: () => window.qeNav && window.qeNav("Config") }, "Edit"),
      foot: _dashFoot(d, "snapshot", d.loaded)
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, /* @__PURE__ */ React.createElement(FieldList, { rows }))
  );
};
const EngineLogBody = () => {
  const d = useDash();
  const rows = d.log;
  return /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.62rem", lineHeight: 1.5 } }, rows.length === 0 && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--qe-muted)" } }, "\u2014 no recent engine events \u2014"), rows.map((l, i) => /* @__PURE__ */ React.createElement("div", { key: `${l.id}-${i}`, style: { display: "grid", gridTemplateColumns: "56px 44px 1fr", gap: 6, opacity: i === 0 ? 1 : Math.max(0.45, 1 - i * 0.06) } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, l.t), /* @__PURE__ */ React.createElement("span", { style: { color: l.tone === "ok" ? "var(--qe-green)" : l.tone === "info" ? "var(--qe-cyan)" : l.tone === "err" ? "var(--qe-red)" : l.tone === "warn" ? "var(--qe-amber)" : "var(--qe-sub)" } }, "[", l.tag, "]"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text-dim)" } }, l.msg))));
};
const EngineLogPane = () => {
  const d = useDash();
  return /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Engine Log",
      tag: "LIVE",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement(StatusDot, { tone: "ok", label: "LOG" }),
      foot: _dashFoot(d, "log", d.log.length > 0),
      bodyStyle: { padding: "4px 6px", fontFamily: "var(--qe-mono)" }
    },
    /* @__PURE__ */ React.createElement(EngineLogBody, null)
  );
};
const TiledGrid = React.memo(function TiledGrid2() {
  return /* @__PURE__ */ React.createElement(GridWorkspace, { persistId: "dashboard" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 8, h: 8, minW: 6, minH: 6 }, /* @__PURE__ */ React.createElement(EquityStatsPane, null)), /* @__PURE__ */ React.createElement(GridItem, { x: 8, y: 0, w: 16, h: 8, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(EquityCurvePane, null)), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 8, w: 6, h: 8, minW: 4, minH: 6 }, /* @__PURE__ */ React.createElement(RiskMonitorPane, null)), /* @__PURE__ */ React.createElement(GridItem, { x: 6, y: 8, w: 12, h: 8, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(OpenPositionsPane, null)), /* @__PURE__ */ React.createElement(GridItem, { x: 18, y: 8, w: 6, h: 8, minW: 4, minH: 6 }, /* @__PURE__ */ React.createElement(MacroSignalsPane, null)), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 16, w: 12, h: 8, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(MonthlyPane, null)), /* @__PURE__ */ React.createElement(GridItem, { x: 12, y: 16, w: 6, h: 8, minW: 4, minH: 6 }, /* @__PURE__ */ React.createElement(ActiveParamsPane, null)), /* @__PURE__ */ React.createElement(GridItem, { x: 18, y: 16, w: 6, h: 8, minW: 4, minH: 6 }, /* @__PURE__ */ React.createElement(EngineLogPane, null)));
});
const DashHeaderDots = () => {
  const d = useDash();
  const st = d.st, rg = d.regime;
  const sse = typeof window.QE_SSE !== "undefined" ? window.QE_SSE.status() : "idle";
  const wsTone = sse === "open" ? "ok" : sse === "error" ? "err" : "warn";
  const gateHalted = !!st.halted;
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(StatusDot, { tone: wsTone, label: "STREAM", value: sse === "open" ? "live" : sse }), /* @__PURE__ */ React.createElement(StatusDot, { tone: "info", label: "REGIME", value: rg && rg.label ? `${rg.label.replace(/_/g, " ")} \xD7${_n(rg.multiplier, 1)}` : "\u2014" }), /* @__PURE__ */ React.createElement(StatusDot, { tone: gateHalted ? "err" : "ok", label: "GATE", value: gateHalted ? "HALTED" : "READY" }));
};
const DashHaltBanner = () => {
  const d = useDash();
  const st = d.st;
  if (st.halted) {
    return /* @__PURE__ */ React.createElement(
      Banner,
      {
        tone: "err",
        tag: "HALT",
        title: "TRADING HALTED \u2014 new entries blocked",
        detail: st.halt_reason || "DD limit breached \xB7 enforced mode"
      }
    );
  }
  if (st.blocked) {
    return /* @__PURE__ */ React.createElement(
      Banner,
      {
        tone: "warn",
        tag: "LIMIT",
        title: "At risk limit \u2014 advisory",
        detail: "A drawdown/weekly-loss limit is at cap; advisory mode does not auto-halt."
      }
    );
  }
  return null;
};
const WatchlistTape = () => {
  const d = useDash();
  const rows = d.positions;
  return /* @__PURE__ */ React.createElement("div", { style: {
    display: "flex",
    alignItems: "center",
    gap: 0,
    background: "var(--qe-bg)",
    borderBottom: "1px solid var(--qe-line)",
    padding: "0 4px",
    height: 22,
    flexShrink: 0,
    fontFamily: "var(--qe-mono)",
    fontSize: "0.62rem",
    overflow: "hidden",
    whiteSpace: "nowrap"
  } }, rows.length === 0 && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", padding: "0 9px" } }, "no open positions"), rows.map((r, i) => /* @__PURE__ */ React.createElement("span", { key: r._k || r.sym, style: { display: "inline-flex", alignItems: "baseline", gap: 5, padding: "0 9px", borderRight: i < rows.length - 1 ? "1px solid var(--qe-faint)" : "none" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, (r.sym || "").replace("USDT", "")), /* @__PURE__ */ React.createElement(LiveValue, { id: `tape.${r._k || r.sym}`, value: r.mark != null ? r.mark : "\u2014", format: (x) => r.mark == null ? "\u2014" : _loc(x, 2), style: { color: "var(--qe-text)", fontWeight: 600 } }), /* @__PURE__ */ React.createElement(LiveValue, { id: `tape.${r._k || r.sym}.pct`, value: r.pct != null ? r.pct : 0, format: (x) => _sn(x) + "%", style: { fontSize: "0.56rem", fontWeight: 600, color: (r.pct || 0) >= 0 ? "var(--qe-green)" : "var(--qe-red)" } }))));
};
const DashTiled = () => {
  React.useEffect(() => {
    QE_DASH.start();
    return () => QE_DASH.stop();
  }, []);
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "01 Dashboard", style: {
    width: "100%",
    height: "100%",
    background: "var(--qe-bg)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden"
  } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "Dashboard", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "Dashboard", subtitle: "live positions \xB7 equity \xB7 risk \xB7 open orders" }, /* @__PURE__ */ React.createElement(DashHeaderDots, null)), /* @__PURE__ */ React.createElement(DashHaltBanner, null), /* @__PURE__ */ React.createElement(WatchlistTape, null), /* @__PURE__ */ React.createElement(TiledGrid, null), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
Object.assign(window, { DashTiled, QE_DASH });

;

/* ==== pages-config.jsx ==== */
const _cfgJson = async (url) => {
  let r;
  try {
    r = await fetch(url, { headers: { Accept: "application/json" } });
  } catch (e) {
    const err = new Error(url + " unreachable");
    err.status = 0;
    throw err;
  }
  if (!r.ok) {
    const err = new Error(url + " " + r.status);
    err.status = r.status;
    throw err;
  }
  try {
    return await r.json();
  } catch (e) {
    const err = new Error(url + " corrupt response");
    err.corrupt = true;
    throw err;
  }
};
const _cfgStrip = (html) => {
  try {
    return (new DOMParser().parseFromString(html || "", "text/html").body.textContent || "").trim();
  } catch (e) {
    return (html || "").trim();
  }
};
const _cfgFriendly = (raw) => {
  const t = (raw || "").trim();
  if (t.startsWith("{") || t.startsWith("[")) {
    try {
      const j = JSON.parse(t);
      const det = j && j.detail;
      if (Array.isArray(det)) {
        return det.map(
          (d) => (d.loc && d.loc.length ? d.loc[d.loc.length - 1] + ": " : "") + (d.msg || d.type || "invalid")
        ).join(" \xB7 ");
      }
      if (typeof det === "string") return det;
      if (j && j.error) return j.error;
    } catch (e) {
    }
  }
  return t;
};
const _cfgPostForm = async (url, fields, method = "POST") => {
  const body = new URLSearchParams();
  Object.entries(fields || {}).forEach(([k, v]) => {
    if (v != null) body.append(k, v);
  });
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString()
  });
  return { ok: r.ok, text: _cfgFriendly(_cfgStrip(await r.text())) };
};
const _cfgPostJson = async (url, payload) => {
  const r = await fetch(url, {
    method: "POST",
    headers: payload != null ? { "Content-Type": "application/json" } : {},
    body: payload != null ? JSON.stringify(payload) : void 0
  });
  let data = null;
  try {
    data = await r.json();
  } catch (e) {
  }
  return { ok: r.ok, data };
};
const _cfgPct = (v) => v == null || isNaN(v) ? "\u2014" : (+v * 100).toFixed(1).replace(/\.0$/, "") + "%";
const _cfgUptime = (s) => {
  if (s == null || isNaN(s)) return "\u2014";
  s = Math.floor(+s);
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return (d ? d + "d " : "") + h + "h " + String(m).padStart(2, "0") + "m";
};
const CfgMsgLine = ({ msg }) => msg ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: {
  fontSize: "0.62rem",
  marginTop: 6,
  color: msg.tone === "ok" ? "var(--qe-green)" : msg.tone === "err" ? "var(--qe-red)" : "var(--qe-sub)"
} }, msg.text) : null;
const CFG_RATIO_PAIRS = [
  ["max_dd_warning_pct", "max_dd_limit_pct"],
  ["weekly_loss_warning_pct", "weekly_loss_limit_pct"]
];
const cfgRatioPairs = (form, stored) => {
  const out = {};
  for (const [warnKey, limitKey] of CFG_RATIO_PAIRS) {
    const w = (form[warnKey] || "").trim();
    const l = (form[limitKey] || "").trim();
    if (!w && !l) continue;
    const fallback = (k) => stored && stored[k] != null ? String(stored[k]) : null;
    out[warnKey] = w || fallback(warnKey);
    out[limitKey] = l || fallback(limitKey);
  }
  return out;
};
const cfgRatioError = (form) => {
  for (const [warnKey, limitKey] of CFG_RATIO_PAIRS) {
    const w = parseFloat(form[warnKey]), l = parseFloat(form[limitKey]);
    if (!isNaN(w) && !isNaN(l) && w >= l) {
      return `${warnKey} (${w}) must be BELOW ${limitKey} (${l})`;
    }
    for (const [k, v] of [[warnKey, w], [limitKey, l]]) {
      if (!isNaN(v) && (v < 0.5 || v > 1)) return `${k} (${v}) is outside 0.50\u20131.00`;
    }
  }
  return null;
};
const CfgAccountForm = ({ account, detail, onReload }) => {
  const p = detail.params || {};
  const s = detail.settings || {};
  const [form, setForm] = React.useState(() => ({
    exchange: account.exchange || "",
    market_type: account.market_type || "future",
    environment: account.environment || "live",
    api_key: "",
    api_secret: "",
    broker_account_id: account.broker_account_id || "",
    individual_risk_per_trade: p.individual_risk_per_trade != null ? String(p.individual_risk_per_trade) : "",
    max_w_loss_percent: p.max_w_loss_percent != null ? String(p.max_w_loss_percent) : "",
    max_dd_percent: p.max_dd_percent != null ? String(p.max_dd_percent) : "",
    max_exposure: p.max_exposure != null ? String(p.max_exposure) : "",
    max_position_count: p.max_position_count != null ? String(p.max_position_count) : "",
    max_correlated_exposure: p.max_correlated_exposure != null ? String(p.max_correlated_exposure) : "",
    /* config-1 (2026-07-25 Meridian audit): the four warn/hard-stop RATIOS. They
       live in account_params (NOT the account_settings block rendered read-only
       below), are bounded in core/state.PARAM_BOUNDS, pair-validated warn<limit
       by validate_params, live-consumed by core/data_cache for pf.dd_state and
       pf.weekly_pnl_state — and POST /accounts/{id}/update already accepted them
       as Form fields. The form simply never sent them, so they were editable
       nowhere in v3 (the legacy Jinja account form still exposes all four). */
    weekly_loss_warning_pct: p.weekly_loss_warning_pct != null ? String(p.weekly_loss_warning_pct) : "",
    weekly_loss_limit_pct: p.weekly_loss_limit_pct != null ? String(p.weekly_loss_limit_pct) : "",
    max_dd_warning_pct: p.max_dd_warning_pct != null ? String(p.max_dd_warning_pct) : "",
    max_dd_limit_pct: p.max_dd_limit_pct != null ? String(p.max_dd_limit_pct) : ""
  }));
  const [busy, setBusy] = React.useState(null);
  const [msg, setMsg] = React.useState(null);
  const set = (k) => (e) => {
    const v = e.target.value;
    setForm((f) => ({ ...f, [k]: v }));
  };
  const doSave = async () => {
    const ratioErr = cfgRatioError(form);
    if (ratioErr) {
      setMsg({ text: ratioErr, tone: "err" });
      return;
    }
    setBusy("save");
    setMsg(null);
    try {
      const r = await _cfgPostForm(`/accounts/${account.id}/update`, {
        exchange: form.exchange.trim() || null,
        market_type: form.market_type,
        environment: form.environment,
        broker_account_id: form.broker_account_id,
        // blank = keep current (endpoint ignores falsy credentials); trimmed so
        // an accidental whitespace-only paste can't overwrite a stored key
        api_key: form.api_key.trim() || null,
        api_secret: form.api_secret.trim() || null,
        individual_risk_per_trade: form.individual_risk_per_trade.trim() || null,
        max_w_loss_percent: form.max_w_loss_percent.trim() || null,
        max_dd_percent: form.max_dd_percent.trim() || null,
        max_exposure: form.max_exposure.trim() || null,
        max_position_count: form.max_position_count.trim() || null,
        max_correlated_exposure: form.max_correlated_exposure.trim() || null,
        // config-1: warn/hard-stop ratios, sent PAIRWISE — see _cfgPair.
        ...cfgRatioPairs(form, p)
      });
      const ok = r.ok && /saved/i.test(r.text);
      setMsg({ text: r.text || (r.ok ? "Saved." : "save failed"), tone: ok ? "ok" : "err" });
      if (ok) {
        setForm((f) => ({ ...f, api_key: "", api_secret: "" }));
        onReload(true);
      }
    } catch (e) {
      setMsg({ text: "save failed \u2014 engine unreachable?", tone: "err" });
    }
    setBusy(null);
  };
  const doTest = async () => {
    setBusy("test");
    setMsg(null);
    try {
      const r = await _cfgPostJson(`/accounts/${account.id}/test`);
      const d = r.data || {};
      setMsg(d.ok ? { text: `connection OK \xB7 ${d.latency_ms} ms` + (d.fees_updated ? ` \xB7 fees ${d.maker_fee}/${d.taker_fee}` : ""), tone: "ok" } : { text: d.error || "connection test failed", tone: "err" });
    } catch (e) {
      setMsg({ text: "test failed \u2014 engine unreachable?", tone: "err" });
    }
    setBusy(null);
  };
  const doActivate = async () => {
    if (!window.confirm("Activate this account? This will restart the exchange connection (WS teardown + reinit).")) return;
    setBusy("activate");
    setMsg(null);
    try {
      const r = await _cfgPostJson(`/accounts/${account.id}/activate`);
      const d = r.data || {};
      if (d.status === "ok") {
        setMsg({ text: d.message === "already active" ? "already active" : `activated \xB7 ${d.name || account.name}`, tone: "ok" });
        onReload(true);
      } else {
        setMsg({ text: d.error || "activate failed", tone: "err" });
      }
    } catch (e) {
      setMsg({ text: "activate failed \u2014 engine unreachable?", tone: "err" });
    }
    setBusy(null);
  };
  const envTone = account.environment === "live" ? "err" : account.environment === "testnet" ? "info" : "blue";
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: 10 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.9rem", fontWeight: 700 } }, account.name), account.is_active ? /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "Active") : null, /* @__PURE__ */ React.createElement(Badge, { tone: envTone }, (account.environment || "live").toUpperCase()), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: doTest, disabled: !!busy }, busy === "test" ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.7rem", label: "testing" }) : "Test Connection")), /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Credentials"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Exchange"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.exchange, onChange: set("exchange"), placeholder: "binance" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Market Type"), /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", value: form.market_type, onChange: set("market_type") }, /* @__PURE__ */ React.createElement("option", { value: "future" }, "USD-M Futures"), /* @__PURE__ */ React.createElement("option", { value: "spot" }, "Spot"))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Environment"), /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", value: form.environment, onChange: set("environment") }, /* @__PURE__ */ React.createElement("option", { value: "live" }, "Live"), /* @__PURE__ */ React.createElement("option", { value: "paper" }, "Paper"), /* @__PURE__ */ React.createElement("option", { value: "testnet" }, "Testnet"))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "API Key"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", type: "password", value: form.api_key, onChange: set("api_key"), placeholder: "Leave blank to keep current" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "API Secret"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", type: "password", value: form.api_secret, onChange: set("api_secret"), placeholder: "Leave blank to keep current" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Broker Account ID"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.broker_account_id, onChange: set("broker_account_id") }))), /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Risk Parameters \xB7 sizing (account_params)"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Risk / Trade (fraction)"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.individual_risk_per_trade, onChange: set("individual_risk_per_trade"), placeholder: "0.01" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Max Weekly Loss (fraction)"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.max_w_loss_percent, onChange: set("max_w_loss_percent"), placeholder: "0.05" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Max Drawdown (fraction)"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.max_dd_percent, onChange: set("max_dd_percent"), placeholder: "0.10" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Max Exposure \xD7"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.max_exposure, onChange: set("max_exposure"), placeholder: "5.0" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Max Positions"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.max_position_count, onChange: set("max_position_count"), placeholder: "10" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Max Corr. Exposure (fraction)"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.max_correlated_exposure, onChange: set("max_correlated_exposure"), placeholder: "0.50" }))), /* @__PURE__ */ React.createElement(SecLbl, { rule: true, right: /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.54rem" } }, "fraction of the budget above \xB7 warn < limit") }, "Warn & Hard-stop ratios (account_params)"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8, marginBottom: 4 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "DD Warn \xD7 Max DD"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.max_dd_warning_pct, onChange: set("max_dd_warning_pct"), placeholder: "0.80" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "DD Hard-stop \xD7 Max DD"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.max_dd_limit_pct, onChange: set("max_dd_limit_pct"), placeholder: "0.95" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Weekly Warn \xD7 Max W. Loss"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.weekly_loss_warning_pct, onChange: set("weekly_loss_warning_pct"), placeholder: "0.80" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Weekly Hard-stop \xD7 Max W. Loss"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.weekly_loss_limit_pct, onChange: set("weekly_loss_limit_pct"), placeholder: "0.95" }))), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", margin: "0 0 10px", lineHeight: 1.5 } }, "Range 0.50\u20130.99 (hard-stop to 1.00); warn must stay below its hard-stop or the save is rejected. Leave a field blank to keep its stored value \u2014 edit either half of a pair and both are sent.", /* @__PURE__ */ React.createElement("br", null), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, "WEEKLY"), " drives the live weekly state machine.", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, " DD"), " is a FALLBACK only \u2014 the rolling-DD path uses the absolute thresholds below, and these two are read solely if that path errors."), /* @__PURE__ */ React.createElement(SecLbl, { rule: true, right: /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.54rem" } }, "READ-ONLY \xB7 set via Presets tab") }, "Enforcement & Recovery \xB7 DD posture (account_settings)"), /* @__PURE__ */ React.createElement(FieldList, { cols: 2, rows: [
    { label: "Strategy preset", value: (s.strategy_preset || "custom").toUpperCase(), color: "cyan" },
    { label: "DD window", value: s.dd_rolling_window_days != null ? s.dd_rolling_window_days + "d" : "\u2014" },
    { label: "DD warn", value: _cfgPct(s.dd_warning_threshold), color: "amber" },
    { label: "DD limit", value: _cfgPct(s.dd_limit_threshold), color: "red" },
    { label: "DD recovery", value: _cfgPct(s.dd_recovery_threshold), color: "green" },
    { label: "DD enforcement", value: (s.dd_enforcement_mode || "\u2014").toUpperCase() },
    { label: "Weekly warn", value: _cfgPct(s.weekly_pnl_warning_threshold), color: "amber" },
    { label: "Weekly limit", value: _cfgPct(s.weekly_pnl_limit_threshold), color: "red" },
    { label: "Weekly enforcement", value: (s.weekly_pnl_enforcement_mode || "\u2014").toUpperCase() }
  ] }), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", margin: "6px 0 10px", lineHeight: 1.5 } }, "The rolling-DD gate reads THIS store \u2014 ABSOLUTE thresholds, written by preset Apply (Presets tab). Disjoint from the ratios above, which live in account_params. Note a preset rewrites these thresholds and the six sizing knobs, but NOT the four ratios \u2014 those stay as you set them. The advisory\u2192enforced flip ships with its name-confirm safety gate in a later phase."), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, marginTop: 8, alignItems: "center" } }, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-primary", onClick: doSave, disabled: !!busy }, busy === "save" ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.7rem", label: "saving" }) : "Save"), /* @__PURE__ */ React.createElement(
    "button",
    {
      className: "qe-btn",
      onClick: doActivate,
      disabled: !!busy || !!account.is_active,
      title: account.is_active ? "Already the active account" : "Switch the engine to this account"
    },
    busy === "activate" ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.7rem", label: "switching" }) : "Activate"
  ), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement(
    "button",
    {
      className: "qe-btn qe-btn-danger",
      disabled: true,
      title: "Not wired in P2 \u2014 delete via the current /config page"
    },
    "Delete Account"
  )), /* @__PURE__ */ React.createElement(CfgMsgLine, { msg }));
};
const CfgAccountsTab = () => {
  const [accounts, setAccounts] = React.useState(null);
  const [acct, setAcct] = React.useState(null);
  const [detail, setDetail] = React.useState(null);
  const acctRef = React.useRef(null);
  const [netA, setNetA] = React.useState({});
  const [netD, setNetD] = React.useState({});
  const loadAccounts = React.useCallback(async (keepSelection) => {
    const t0 = performance.now();
    try {
      const rows = await _cfgJson("/accounts");
      setNetA({ err: null, ms: performance.now() - t0 });
      setAccounts(rows);
      setAcct((cur) => {
        if (keepSelection && cur != null && rows.some((a) => a.id === cur)) return cur;
        const act = rows.find((a) => a.is_active) || rows[0];
        return act ? act.id : null;
      });
    } catch (err) {
      setAccounts([]);
      setNetA((n) => ({ ...n, err }));
    }
  }, []);
  React.useEffect(() => {
    loadAccounts(false);
  }, [loadAccounts]);
  React.useEffect(() => {
    acctRef.current = acct;
    if (acct == null) return;
    setDetail(null);
    let alive = true;
    const t0 = performance.now();
    _cfgJson("/api/config/account/" + acct).then((d) => {
      if (alive) {
        setDetail(d);
        setNetD({ err: null, ms: performance.now() - t0 });
      }
    }).catch((err) => {
      if (alive) {
        setDetail({ params: {}, settings: {}, _placeholder: true });
        setNetD((n) => ({ ...n, err }));
      }
    });
    return () => {
      alive = false;
    };
  }, [acct]);
  const reload = (accountsToo) => {
    if (accountsToo) loadAccounts(true);
    const target = acct;
    if (target != null) {
      _cfgJson("/api/config/account/" + target).then((d) => {
        if (acctRef.current === target && d.account_id === target) setDetail(d);
      }).catch(() => {
      });
    }
  };
  const sel = (accounts || []).find((a) => a.id === acct);
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 6, h: 20, minW: 4, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Accounts",
      count: accounts ? accounts.length : null,
      style: { height: "100%" },
      onRefresh: () => loadAccounts(true),
      foot: qeFootState({ loading: netA.ms == null && !netA.err, err: netA.err, hasData: accounts != null && accounts.length > 0, ms: netA.ms })
    },
    accounts == null ? /* @__PURE__ */ React.createElement(Spinner, { label: "loading" }) : !accounts.length ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "warn", glyph: "\u2205", msg: "No accounts", hint: "Engine unreachable, or no accounts configured." }) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4 } }, accounts.map((a) => /* @__PURE__ */ React.createElement(Card, { key: a.id, tight: true, style: {
      cursor: "pointer",
      borderColor: acct === a.id ? "var(--qe-cyan)" : "var(--qe-line)",
      background: acct === a.id ? "var(--qe-active)" : "var(--qe-card)"
    }, onClick: () => setAcct(a.id) }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, alignItems: "center" } }, /* @__PURE__ */ React.createElement(StatusDot, { tone: a.is_active ? "ok" : "off", label: "" }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.72rem", fontWeight: 700, color: "var(--qe-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, a.name), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.58rem", color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, a.exchange, " \xB7 ", a.market_type)), /* @__PURE__ */ React.createElement(Badge, { tone: a.environment === "live" ? "err" : a.environment === "testnet" ? "info" : "blue" }, (a.environment || "live").toUpperCase())))), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "qe-btn qe-btn-primary qe-btn-sm",
        disabled: true,
        title: "Not wired in P2 \u2014 add accounts via the current /config page",
        style: { marginTop: 4, justifyContent: "center" }
      },
      "+ Add Account"
    ))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 6, y: 0, w: 18, h: 20, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Account Settings",
      style: { height: "100%" },
      bodyStyle: { overflow: "auto" },
      onRefresh: () => reload(true),
      foot: !sel ? { tone: "sub", msg: "no account selected" } : qeFootState({ loading: detail == null && !netD.err, err: netD.err, hasData: detail != null && !detail._placeholder, ms: netD.ms })
    },
    !sel ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: "No account selected" }) : detail == null ? /* @__PURE__ */ React.createElement(Spinner, { label: "loading" }) : /* @__PURE__ */ React.createElement(CfgAccountForm, { key: sel.id, account: sel, detail, onReload: reload })
  )));
};
const CfgConnectionsTab = () => {
  const [conns, setConns] = React.useState(null);
  const [drafts, setDrafts] = React.useState({});
  const [editing, setEditing] = React.useState(null);
  const [busyP, setBusyP] = React.useState(null);
  const [msg, setMsg] = React.useState(null);
  const [add, setAdd] = React.useState({ provider: "", label: "", key: "" });
  const [net, setNet] = React.useState({});
  const load = React.useCallback(async () => {
    const t0 = performance.now();
    try {
      setConns((await _cfgJson("/api/connections")).connections || []);
      setNet({ err: null, ms: performance.now() - t0 });
    } catch (err) {
      setConns([]);
      setNet((n) => ({ ...n, err }));
    }
  }, []);
  React.useEffect(() => {
    load();
  }, [load]);
  const upsert = async (provider, label, key) => {
    if (!key || !key.trim()) {
      setMsg({ text: `${label}: enter an API key first`, tone: "err" });
      return false;
    }
    setBusyP(provider);
    setMsg(null);
    let saved = false;
    try {
      const r = await _cfgPostForm("/connections", { provider, label, api_key: key.trim() });
      if (r.ok) {
        saved = true;
        setMsg({ text: `${label}: key saved`, tone: "ok" });
        setDrafts((d) => ({ ...d, [provider]: "" }));
        setEditing(null);
        await load();
      } else {
        setMsg({ text: `${label}: save failed \u2014 ${r.text || "error"}`, tone: "err" });
      }
    } catch (e) {
      setMsg({ text: `${label}: save failed \u2014 engine unreachable?`, tone: "err" });
    }
    setBusyP(null);
    return saved;
  };
  const test = async (provider, label) => {
    setBusyP(provider);
    setMsg(null);
    try {
      const r = await fetch(`/connections/${encodeURIComponent(provider)}/test`, { method: "POST" });
      const text = _cfgStrip(await r.text());
      setMsg({ text: `${label}: ${text}`, tone: text.startsWith("\u2713") ? "ok" : "err" });
    } catch (e) {
      setMsg({ text: `${label}: test failed \u2014 engine unreachable?`, tone: "err" });
    }
    setBusyP(null);
  };
  const remove = async (provider, label) => {
    if (!window.confirm(`Remove ${label} connection?`)) return;
    setBusyP(provider);
    setMsg(null);
    try {
      const r = await fetch(`/connections/${encodeURIComponent(provider)}`, { method: "DELETE" });
      setMsg(r.ok ? { text: `${label}: removed`, tone: "ok" } : { text: `${label}: remove failed`, tone: "err" });
      await load();
    } catch (e) {
      setMsg({ text: `${label}: remove failed \u2014 engine unreachable?`, tone: "err" });
    }
    setBusyP(null);
  };
  const keyInput = (c) => /* @__PURE__ */ React.createElement(
    "input",
    {
      className: "qe-input",
      type: "password",
      placeholder: "API Key",
      value: drafts[c.provider] || "",
      onChange: (e) => {
        const v = e.target.value;
        setDrafts((d) => ({ ...d, [c.provider]: v }));
      },
      onClick: (e) => e.stopPropagation(),
      style: { width: 200, height: 22, fontSize: "0.62rem" }
    }
  );
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 20, minW: 10, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Data & Exchange Connections",
      count: conns ? conns.length : null,
      style: { height: "100%" },
      bodyStyle: { padding: 0 },
      onRefresh: load,
      foot: qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: conns != null && conns.length > 0, ms: net.ms })
    },
    conns == null ? /* @__PURE__ */ React.createElement("div", { style: { padding: 10 } }, /* @__PURE__ */ React.createElement(Spinner, { label: "loading" })) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
      DataList,
      {
        dense: false,
        selKey: "provider",
        emptyMsg: "no connections",
        columns: [
          { key: "label", label: "PROVIDER", render: (c) => /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700 } }, c.label) },
          { key: "provider", label: "ID", render: (c) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, c.provider) },
          /* 'status' is RENDER-ONLY — the row carries has_key, not a
             status field — so facet derivation and presentKeys both
             skipped it: no FILTER dropdown and an inert STATUS header.
             Project has_key onto the same two strings the cell shows. */
          {
            key: "status",
            label: "STATUS",
            filter: true,
            filterVal: (c) => c.has_key ? "CONNECTED" : "NOT SET",
            sortVal: (c) => c.has_key ? "CONNECTED" : "NOT SET",
            render: (c) => c.has_key ? /* @__PURE__ */ React.createElement(StatusDot, { tone: "ok", label: "CONNECTED" }) : /* @__PURE__ */ React.createElement(StatusDot, { tone: "off", label: "NOT SET" })
          },
          { key: "key", label: "KEY", render: (c) => c.has_key && editing !== c.provider ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, c.api_key_hint || "\u2022\u2022\u2022\u2022\u2022\u2022") : keyInput(c) },
          { key: "act", label: "", align: "right", render: (c) => {
            const busy = busyP === c.provider;
            if (!c.has_key || editing === c.provider) {
              return /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", gap: 4 } }, /* @__PURE__ */ React.createElement(
                "button",
                {
                  className: "qe-btn qe-btn-sm qe-btn-primary",
                  disabled: busy,
                  onClick: (e) => {
                    e.stopPropagation();
                    upsert(c.provider, c.label, drafts[c.provider]);
                  }
                },
                busy ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.62rem" }) : "Save"
              ), c.has_key ? /* @__PURE__ */ React.createElement(
                "button",
                {
                  className: "qe-btn qe-btn-sm qe-btn-ghost",
                  disabled: busy,
                  onClick: (e) => {
                    e.stopPropagation();
                    setEditing(null);
                  }
                },
                "Cancel"
              ) : null);
            }
            return /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", gap: 4 } }, /* @__PURE__ */ React.createElement(
              "button",
              {
                className: "qe-btn qe-btn-sm",
                disabled: busy,
                onClick: (e) => {
                  e.stopPropagation();
                  test(c.provider, c.label);
                }
              },
              busy ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.62rem" }) : "Test"
            ), /* @__PURE__ */ React.createElement(
              "button",
              {
                className: "qe-btn qe-btn-sm qe-btn-ghost",
                disabled: busy,
                onClick: (e) => {
                  e.stopPropagation();
                  setEditing(c.provider);
                }
              },
              "Edit"
            ), /* @__PURE__ */ React.createElement(
              "button",
              {
                className: "qe-btn qe-btn-sm qe-btn-danger",
                disabled: busy,
                onClick: (e) => {
                  e.stopPropagation();
                  remove(c.provider, c.label);
                }
              },
              "Remove"
            ));
          } }
        ],
        rows: conns
      }
    ), /* @__PURE__ */ React.createElement("div", { style: { padding: "8px 10px", borderTop: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(Lbl, null, "+ Add custom provider"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, alignItems: "center", marginTop: 4 } }, /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "qe-input",
        placeholder: "provider id (e.g. alphavantage)",
        value: add.provider,
        onChange: (e) => {
          const v = e.target.value;
          setAdd((a) => ({ ...a, provider: v }));
        },
        style: { maxWidth: 180 }
      }
    ), /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "qe-input",
        placeholder: "label",
        value: add.label,
        onChange: (e) => {
          const v = e.target.value;
          setAdd((a) => ({ ...a, label: v }));
        },
        style: { maxWidth: 180 }
      }
    ), /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "qe-input",
        type: "password",
        placeholder: "API key",
        value: add.key,
        onChange: (e) => {
          const v = e.target.value;
          setAdd((a) => ({ ...a, key: v }));
        },
        style: { maxWidth: 220 }
      }
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "qe-btn qe-btn-sm qe-btn-primary",
        disabled: !add.provider.trim() || !add.label.trim() || !add.key.trim() || !!busyP,
        onClick: () => upsert(add.provider.trim(), add.label.trim(), add.key).then((ok) => {
          if (ok) setAdd({ provider: "", label: "", key: "" });
        })
      },
      "Add"
    )), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", marginTop: 6 } }, "Keys are encrypted at rest with AES-256 (Fernet)."), /* @__PURE__ */ React.createElement(CfgMsgLine, { msg })))
  )));
};
const CfgPresetsTab = () => {
  const [cat, setCat] = React.useState(null);
  const [active, setActive] = React.useState(null);
  const [current, setCurrent] = React.useState("");
  const [busy, setBusy] = React.useState(null);
  const [msg, setMsg] = React.useState(null);
  const [net, setNet] = React.useState({});
  const load = React.useCallback(async () => {
    const t0 = performance.now();
    try {
      const [pc, accounts] = await Promise.all([_cfgJson("/api/config/presets"), _cfgJson("/accounts")]);
      setNet({ err: null, ms: performance.now() - t0 });
      setCat(pc.presets || []);
      const act = (accounts || []).find((a) => a.is_active) || null;
      setActive(act);
      if (act) {
        try {
          const d = await _cfgJson("/api/config/account/" + act.id);
          setCurrent((d.settings || {}).strategy_preset || "");
        } catch (e) {
          setCurrent("");
        }
      }
    } catch (err) {
      setCat([]);
      setNet((n) => ({ ...n, err }));
    }
  }, []);
  React.useEffect(() => {
    load();
  }, [load]);
  const apply = async (name) => {
    const target = active ? active.name : "the active account";
    if (!window.confirm(
      `Apply preset ${name.toUpperCase()} to ${target}?

FULL apply \u2014 writes BOTH risk stores:
\xB7 DD posture (window / warn / limit / recovery + analytics period)
\xB7 sizing envelope (risk/trade, weekly loss, max DD, exposure, positions, corr. cap)

Enforcement mode is NOT changed.`
    )) return;
    setBusy(name);
    setMsg(null);
    try {
      const r = await _cfgPostJson("/api/config/apply-preset", { preset: name });
      if (r.ok && r.data && r.data.status === "ok") {
        setMsg({ text: `preset ${name.toUpperCase()} applied to ${target}`, tone: "ok" });
        await load();
      } else {
        setMsg({ text: r.data && r.data.error || "apply failed", tone: "err" });
      }
    } catch (e) {
      setMsg({ text: "apply failed \u2014 engine unreachable?", tone: "err" });
    }
    setBusy(null);
  };
  const fRow = (l, v, color) => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, l), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: color || "var(--qe-text)" } }, v));
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 16, minW: 10, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Risk Presets",
      style: { height: "100%" },
      bodyStyle: { overflow: "auto" },
      onRefresh: load,
      foot: qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: (cat || []).length > 0, ms: net.ms })
    },
    /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.6rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.5 } }, "Apply is FULL: writes the DD posture (account_settings \u2014 the store the DD gate reads) AND the sizing envelope (account_params). Applies to the active account", active ? /* @__PURE__ */ React.createElement("span", null, " \u2014 ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, active.name)) : null, ". Enforcement mode never changes here."),
    cat == null ? /* @__PURE__ */ React.createElement(Spinner, { label: "loading" }) : !cat.length ? /* @__PURE__ */ React.createElement(EmptyState, { tone: "warn", glyph: "\u2205", msg: "No presets", hint: "Engine unreachable?" }) : /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 } }, cat.map((p) => {
      const dd = p.dd || {}, sz = p.sizing || {};
      const isCur = current === p.name;
      return /* @__PURE__ */ React.createElement(Card, { key: p.name, ticks: true }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.78rem", fontWeight: 700, color: "var(--qe-cyan)", letterSpacing: "0.08em" } }, p.name.replace("_", " ").toUpperCase()), isCur ? /* @__PURE__ */ React.createElement(Badge, { tone: "info" }, "CURRENT") : null), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4, fontSize: "0.66rem", fontFamily: "var(--qe-mono)" } }, fRow("DD window", dd.dd_rolling_window_days != null ? dd.dd_rolling_window_days + "d" : "\u2014"), fRow("warn", _cfgPct(dd.dd_warning_threshold), "var(--qe-amber)"), fRow("limit", _cfgPct(dd.dd_limit_threshold), "var(--qe-red)"), fRow("recovery", _cfgPct(dd.dd_recovery_threshold), "var(--qe-green)"), fRow("period", dd.analytics_default_period || "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { borderTop: "1px solid var(--qe-line)", margin: "3px 0" } }), fRow("risk/trade", _cfgPct(sz.individual_risk_per_trade), "var(--qe-cyan)"), fRow("wk loss cap", _cfgPct(sz.max_w_loss_percent)), fRow("max DD cap", _cfgPct(sz.max_dd_percent)), fRow("exposure", sz.max_exposure != null ? sz.max_exposure + "\xD7" : "\u2014"), fRow("positions", sz.max_position_count != null ? String(sz.max_position_count) : "\u2014"), fRow("corr. cap", _cfgPct(sz.max_correlated_exposure))), /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "qe-btn qe-btn-sm",
          disabled: !!busy,
          style: { width: "100%", marginTop: 8, justifyContent: "center" },
          onClick: () => apply(p.name)
        },
        busy === p.name ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.62rem", label: "applying" }) : "Apply Preset"
      ));
    })),
    /* @__PURE__ */ React.createElement(CfgMsgLine, { msg })
  )));
};
const CfgSystemTab = () => {
  const [sys, setSys] = React.useState(null);
  const [net, setNet] = React.useState({});
  const load = React.useCallback(async () => {
    const t0 = performance.now();
    try {
      setSys(await _cfgJson("/api/system"));
      setNet({ err: null, ms: performance.now() - t0 });
    } catch (err) {
      setSys({});
      setNet((n) => ({ ...n, err }));
    }
  }, []);
  React.useEffect(() => {
    load();
  }, [load]);
  const c = sys && sys.cadences || {};
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 12, minW: 10, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "System",
      style: { height: "100%" },
      bodyStyle: { overflow: "auto" },
      onRefresh: load,
      foot: qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: !!(sys && sys.version), ms: net.ms })
    },
    sys == null ? /* @__PURE__ */ React.createElement(Spinner, { label: "loading" }) : !sys.version ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "warn", glyph: "\u2205", msg: "Engine unreachable", hint: "/api/system did not answer." }) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(SecLbl, { rule: true, right: /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.54rem" } }, "READ-ONLY \xB7 G-O8") }, "Engine"), /* @__PURE__ */ React.createElement(FieldList, { cols: 2, rows: [
      { label: "Engine", value: sys.short_name || sys.name || "\u2014" },
      { label: "Version", value: sys.version || "\u2014", color: "cyan" },
      { label: "Pub/Sub backend", value: sys.bus_backend || "\u2014" },
      { label: "Uptime", value: _cfgUptime(sys.uptime_s), color: "green" },
      { label: "Started", value: sys.started_at || "\u2014" }
    ] }), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.58rem", color: "var(--qe-sub)", margin: "4px 0 10px" } }, sys.description || ""), /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Poll cadences"), /* @__PURE__ */ React.createElement(FieldList, { cols: 2, rows: [
      { label: "Dashboard poll", value: c.dashboard_poll_s != null ? c.dashboard_poll_s + "s" : "\u2014" },
      { label: "Calculator poll", value: c.calculator_poll_s != null ? c.calculator_poll_s + "s" : "\u2014" },
      { label: "History poll", value: c.history_poll_s != null ? c.history_poll_s + "s" : "\u2014" },
      { label: "WS status poll", value: c.ws_status_poll_s != null ? c.ws_status_poll_s + "s" : "\u2014" },
      { label: "WS ping", value: c.ws_ping_s != null ? c.ws_ping_s + "s" : "\u2014" }
    ] }))
  )));
};
const ConfigPage = () => {
  const [tab, setTab] = React.useState("accounts");
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "08 Config", style: {
    width: "100%",
    height: "100%",
    background: "var(--qe-bg)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden"
  } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "Config", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "Configuration", subtitle: "accounts \xB7 connections \xB7 risk parameters \xB7 presets" }), /* @__PURE__ */ React.createElement(TabStrip, { value: tab, onChange: setTab, tabs: [
    ["accounts", "Accounts"],
    ["connections", "Connections"],
    ["presets", "Presets"],
    ["system", "System"]
  ] }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "auto" } }, tab === "accounts" && /* @__PURE__ */ React.createElement(CfgAccountsTab, null), tab === "connections" && /* @__PURE__ */ React.createElement(CfgConnectionsTab, null), tab === "presets" && /* @__PURE__ */ React.createElement(CfgPresetsTab, null), tab === "system" && /* @__PURE__ */ React.createElement(CfgSystemTab, null)), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
Object.assign(window, { ConfigPage });

;

/* ==== pages-pretrade.jsx ==== */
const _ptCalcFoot = (busy, calcErr, calc) => {
  if (busy) return { tone: "sub", busy: true, msg: "calculating\u2026" };
  if (calcErr) {
    return calc ? { tone: "warn", msg: "calc failed \xB7 showing last result" } : { tone: "err", msg: String(calcErr).slice(0, 80) };
  }
  return calc ? { tone: "ok", msg: "calc ok" } : { tone: "sub", msg: "no calc yet" };
};
const _ptStrip = (html) => {
  let t;
  try {
    t = (new DOMParser().parseFromString(html || "", "text/html").body.textContent || "").trim();
  } catch (e) {
    t = (html || "").trim();
  }
  if (t.startsWith("{") || t.startsWith("[")) {
    try {
      const j = JSON.parse(t);
      const det = j && j.detail;
      if (Array.isArray(det)) {
        return det.map(
          (d) => (d.loc && d.loc.length ? d.loc[d.loc.length - 1] + ": " : "") + (d.msg || d.type || "invalid")
        ).join(" \xB7 ");
      }
      if (typeof det === "string") return det;
      if (j && j.error) return j.error;
    } catch (e) {
    }
  }
  return t;
};
const _ptFmtP = (v) => {
  if (v == null || isNaN(v)) return "\u2014";
  const a = Math.abs(+v);
  const d = a >= 1e3 ? 2 : a >= 1 ? 4 : 6;
  return (+v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
};
const _ptFmtSz = (v) => v == null || isNaN(v) ? "\u2014" : (+v).toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
const _ptFmtN = (v, d = 2) => v == null || isNaN(v) ? "\u2014" : (+v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const _ptSign = (v, d = 2) => v == null || isNaN(v) ? "\u2014" : (v >= 0 ? "+" : "") + _ptFmtN(v, d);
const _ptAge = (ts) => {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1e3));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  return Math.floor(s / 3600) + "h " + Math.floor(s % 3600 / 60) + "m ago";
};
const PtAge = ({ ts }) => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    const t = setInterval(force, 3e4);
    return () => clearInterval(t);
  }, []);
  return /* @__PURE__ */ React.createElement(React.Fragment, null, _ptAge(ts));
};
const _ptRemain = (sec) => {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return h >= 1 ? `~${h}h ${m}m` : `${m}m ${s}s`;
};
const PT_STATE_KEY = "qe.v3.calc_state";
const PT_RESULT_KEY = "qe.v3.calc_result";
const PT_HIST_KEY = "qe.v3.calc_history";
const PT_COMMODITY_RE = /^(XAU|XAG|XPT|XPD|WTI|BRN)/i;
const PT_FORM_DEFAULTS = {
  orderType: "market",
  ticker: "",
  limitPrice: "",
  tpslMode: "price",
  sideSel: "long",
  tpPrice: "",
  slPrice: "",
  tpPct: "",
  slPct: "",
  tpAmountPct: "100",
  slAmountPct: "100",
  modelId: "",
  modelName: "",
  modelDesc: "",
  linkOverride: "",
  sizeOverride: "",
  applyMult: true,
  ladder: []
  // [{price:'', pct:''}] — serialized on submit
};
const _ptReadJSON = (store, key) => {
  try {
    const s = store.getItem(key);
    return s ? JSON.parse(s) : null;
  } catch (e) {
    return null;
  }
};
const _ptWriteJSON = (store, key, v) => {
  try {
    store.setItem(key, JSON.stringify(v));
  } catch (e) {
  }
};
const PtCountdownChip = ({ lw }) => {
  const s = lw && lw.status;
  const ticking = s === "LINKABLE" || s === "EXPIRING_SOON";
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    if (!ticking) return;
    const t = setInterval(force, 1e3);
    return () => clearInterval(t);
  }, [ticking, lw]);
  if (!lw) {
    return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, padding: "2px 8px", border: "1px solid var(--qe-line)", fontSize: "0.62rem", fontFamily: "var(--qe-mono)", color: "var(--qe-muted)" } }, "no active calc");
  }
  const box = (color, children) => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, padding: "2px 8px", border: `1px solid ${color}`, borderLeft: `3px solid ${color}`, fontSize: "0.62rem", fontFamily: "var(--qe-mono)" } }, children);
  if (s === "PENDING") return box("var(--qe-line-2)", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontWeight: 700 } }, "\u231B Confirming calc\u2026"));
  if (s === "ERROR") return box("var(--qe-red)", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)", fontWeight: 700 } }, "\u2717 Submission failed to record"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014 please retry")));
  if (s === "LINKED") return box("var(--qe-green)", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)", fontWeight: 700 } }, "\u2713 LINKED"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014 matched to an order")));
  if (s === "LINKED_CONFIRMED") return box("var(--qe-green)", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)", fontWeight: 700 } }, "\u2713 LINKED (CONFIRMED)"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014 operator confirmation bypasses window check")));
  if (s === "EXPIRED") return box("var(--qe-red)", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)", fontWeight: 700 } }, "\u2717 PLAN EXPIRED"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014 recalculate to link new fills")));
  const elapsed = lw._at ? (Date.now() - lw._at) / 1e3 : 0;
  const rem = (lw.remaining_s || 0) - elapsed;
  const warn = s === "EXPIRING_SOON";
  const col = warn ? "var(--qe-amber)" : "var(--qe-green)";
  return box(col, /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: col, fontWeight: 700 } }, warn ? "\u26A0 EXPIRING SOON" : "\u2713 LINKABLE"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)" } }, _ptRemain(rem), " left"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "(window ", Math.round((lw.effective_window_s || 0) / 60), " min)")));
};
const PtCopyCell = ({ label, value, display, color, copied, onCopy }) => {
  const done = copied === label;
  return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, label), /* @__PURE__ */ React.createElement("div", { onClick: () => onCopy(label, value), title: `Copy ${label}`, style: {
    display: "flex",
    alignItems: "stretch",
    height: 22,
    cursor: "pointer",
    background: "var(--qe-panel)",
    border: `1px solid ${done ? "var(--qe-green)" : "var(--qe-line)"}`
  } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0, padding: "0 7px", display: "flex", alignItems: "center", fontFamily: "var(--qe-mono)", fontSize: "0.7rem", fontWeight: 600, color, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, display != null ? display : value), /* @__PURE__ */ React.createElement("button", { title: `Copy ${label}`, onClick: (e) => {
    e.stopPropagation();
    onCopy(label, value);
  }, style: {
    width: 22,
    flex: "0 0 22px",
    padding: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "transparent",
    border: "none",
    borderLeft: `1px solid ${done ? "var(--qe-green)" : "var(--qe-line)"}`,
    color: done ? "var(--qe-green)" : "var(--qe-muted)",
    cursor: "pointer",
    fontSize: "0.72rem",
    lineHeight: 1
  } }, /* @__PURE__ */ React.createElement("span", { style: { display: "block", transform: "translateY(1px)" } }, done ? "\u2713" : "\u29C9"))));
};
const PreTradePage = () => {
  const [st, setSt] = React.useState(null);
  const [regime, setRegime] = React.useState(null);
  const [models, setModels] = React.useState(null);
  const [ctxInfo, setCtxInfo] = React.useState(null);
  const [riskPct, setRiskPct] = React.useState(null);
  const [form, setForm] = React.useState(() => {
    const saved = _ptReadJSON(localStorage, PT_STATE_KEY);
    return saved ? { ...PT_FORM_DEFAULTS, ...saved, ladder: Array.isArray(saved.ladder) ? saved.ladder : [] } : { ...PT_FORM_DEFAULTS };
  });
  const set = (k) => (e) => {
    const v = e && e.target ? e.target.type === "checkbox" ? e.target.checked : e.target.value : e;
    setForm((f) => ({ ...f, [k]: v }));
  };
  const [livePrice, setLivePrice] = React.useState(null);
  const [ob, setOb] = React.useState(null);
  const [calc, setCalc] = React.useState(() => _ptReadJSON(sessionStorage, PT_RESULT_KEY));
  const [calcErr, setCalcErr] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [lwCalcId, setLwCalcId] = React.useState(() => {
    const c2 = _ptReadJSON(sessionStorage, PT_RESULT_KEY);
    return c2 && c2.calc_id && c2.eligible ? c2.calc_id : null;
  });
  const [lw, setLw] = React.useState(null);
  const [autoRate, setAutoRate] = React.useState(() => {
    const saved = _ptReadJSON(localStorage, PT_STATE_KEY);
    return saved && saved.orderType && saved.orderType !== "market" ? 30 : 1;
  });
  const [sizeUnit, setSizeUnit] = React.useState("notional");
  const [copied, setCopied] = React.useState(null);
  const [recent, setRecent] = React.useState(() => _ptReadJSON(localStorage, PT_HIST_KEY) || []);
  const [winSaved, setWinSaved] = React.useState(null);
  const tickerRef = React.useRef(form.ticker.trim().toUpperCase());
  const inFlight = React.useRef(false);
  const pendingManual = React.useRef(false);
  const t0Ref = React.useRef(0);
  const formRef = React.useRef(form);
  formRef.current = form;
  const liveRef = React.useRef(null);
  liveRef.current = livePrice;
  const stRef = React.useRef(null);
  stRef.current = st;
  const regimeRef = React.useRef(null);
  regimeRef.current = regime;
  const calcTickerRef = React.useRef(calc ? calc.ticker : null);
  const [netRegime, setNetRegime] = React.useState({});
  React.useEffect(() => {
    let alive = true;
    const load = (url, fn, netFn) => {
      const t0 = performance.now();
      return _ptJson(url).then((d) => {
        if (alive) {
          fn(d);
          if (netFn) netFn({ err: null, ms: performance.now() - t0 });
        }
      }).catch((err) => {
        if (alive && netFn) netFn((n) => ({ ...n, err }));
      });
    };
    load("/api/state", setSt);
    load("/api/regime/current", setRegime, setNetRegime);
    load("/api/models", (d) => setModels(Array.isArray(d) ? d : d.models || []));
    load("/api/calculator/context", setCtxInfo);
    const aid = window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.activeAccountId;
    if (aid != null) load("/api/config/account/" + aid, (d) => setRiskPct((d.params || {}).individual_risk_per_trade));
    const t1 = setInterval(() => load("/api/state", setSt), 5e3);
    const t2 = setInterval(() => load("/api/regime/current", setRegime, setNetRegime), 6e4);
    return () => {
      alive = false;
      clearInterval(t1);
      clearInterval(t2);
    };
  }, []);
  const applyPrefill = React.useCallback((id) => {
    if (!id) return;
    _ptJson("/calculator/prefill/" + encodeURIComponent(id)).then((p) => {
      const rp = p && p.risk_preset || {};
      setForm((f) => ({
        ...f,
        applyMult: rp.apply_regime_multiplier != null ? !!rp.apply_regime_multiplier : f.applyMult,
        sizeOverride: rp.size_override_default != null ? String(rp.size_override_default) : f.sizeOverride,
        modelName: f.modelName || p.name || ""
      }));
    }).catch(() => {
    });
  }, []);
  React.useEffect(() => {
    let qid = null;
    try {
      qid = new URLSearchParams(window.location.search).get("model_id");
    } catch (e) {
    }
    if (!qid || !/^\d+$/.test(qid)) return;
    setForm((f) => ({ ...f, modelId: qid }));
    applyPrefill(qid);
  }, [applyPrefill]);
  const tickerNorm = form.ticker.trim().toUpperCase();
  const [netPx, setNetPx] = React.useState({});
  React.useEffect(() => {
    tickerRef.current = tickerNorm;
    setLivePrice(null);
    setNetPx({});
    if (!tickerNorm) return;
    let alive = true, timer = null;
    let hadPrice = false;
    const poll = async () => {
      const t0 = performance.now();
      try {
        const d = await _ptJson("/api/price/" + encodeURIComponent(tickerNorm));
        if (alive && tickerRef.current === tickerNorm) {
          const ms = performance.now() - t0;
          if (d.price) {
            hadPrice = true;
            setLivePrice(d.price);
          }
          setNetPx(!d.price && hadPrice ? { err: { corrupt: true }, ms } : { err: null, ms });
        }
      } catch (err) {
        if (alive && tickerRef.current === tickerNorm) setNetPx((n) => ({ ...n, err }));
      }
      if (alive) timer = setTimeout(poll, 1e3);
    };
    const debounce = setTimeout(poll, 500);
    return () => {
      alive = false;
      clearTimeout(debounce);
      clearTimeout(timer);
    };
  }, [tickerNorm]);
  const [netOb, setNetOb] = React.useState({});
  React.useEffect(() => {
    setOb(null);
    setNetOb({});
    if (!tickerNorm) return;
    let alive = true, timer = null;
    const poll = async () => {
      const t0 = performance.now();
      try {
        const d = await _ptJson("/api/calculator/orderbook/" + encodeURIComponent(tickerNorm));
        if (alive && tickerRef.current === tickerNorm) {
          setOb(d);
          setNetOb({ err: null, ms: performance.now() - t0 });
        }
      } catch (err) {
        if (alive && tickerRef.current === tickerNorm) setNetOb((n) => ({ ...n, err }));
      }
      if (alive) timer = setTimeout(poll, 2e3);
    };
    const debounce = setTimeout(poll, 600);
    return () => {
      alive = false;
      clearTimeout(debounce);
      clearTimeout(timer);
    };
  }, [tickerNorm]);
  React.useEffect(() => {
    setLw(null);
    t0Ref.current = 0;
    if (!lwCalcId) return;
    let stop = false, timer = null;
    const poll = async () => {
      try {
        const q = t0Ref.current ? "&t0=" + t0Ref.current : "";
        const d = await _ptJson("/calculator/link-window-status/" + encodeURIComponent(lwCalcId) + "?format=json" + q);
        if (stop) return;
        setLw({ ...d, _at: Date.now() });
        if (d.t0) t0Ref.current = d.t0;
        if (d.status === "PENDING") timer = setTimeout(poll, 1e3);
        else if (d.status === "LINKABLE" || d.status === "EXPIRING_SOON") timer = setTimeout(poll, 5e3);
      } catch (e) {
        if (!stop) timer = setTimeout(poll, 5e3);
      }
    };
    poll();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [lwCalcId]);
  const doCalculate = React.useCallback(async (auto) => {
    const f = formRef.current;
    const t = f.ticker.trim().toUpperCase();
    if (inFlight.current) {
      if (!auto) pendingManual.current = true;
      return;
    }
    if (stRef.current && stRef.current.halted) {
      if (!auto) setCalcErr("Calculator blocked \u2014 DD hard stop (enforced). See the banner.");
      return;
    }
    if (!t) {
      if (!auto) setCalcErr("Ticker is required.");
      return;
    }
    if (auto && t !== calcTickerRef.current) return;
    const entry = f.orderType === "market" ? liveRef.current : parseFloat(f.limitPrice);
    if (!entry || !isFinite(entry) || entry <= 0) {
      if (!auto) setCalcErr(f.orderType === "market" ? "No live price yet \u2014 wait a beat or switch to LIMIT." : "Entry price is required.");
      return;
    }
    let tp = null, sl = null;
    if (f.tpslMode === "price") {
      tp = f.tpPrice.trim() ? parseFloat(f.tpPrice) : null;
      sl = f.slPrice.trim() ? parseFloat(f.slPrice) : null;
    } else {
      const tpp = parseFloat(f.tpPct), slp = parseFloat(f.slPct);
      if (f.slPct.trim() && (!isFinite(slp) || slp <= 0)) {
        if (!auto) setCalcErr("SL % must be a positive number.");
        return;
      }
      const dir = f.sideSel === "short" ? -1 : 1;
      if (isFinite(tpp) && tpp > 0) tp = entry * (1 + dir * tpp / 100);
      if (isFinite(slp) && slp > 0) sl = entry * (1 - dir * slp / 100);
    }
    const ladder = f.ladder.map((r) => ({ price: parseFloat(r.price), size_pct: parseFloat(r.pct) })).filter((r) => isFinite(r.price) && r.price > 0 && isFinite(r.size_pct) && r.size_pct > 0);
    if ((tp == null || !isFinite(tp) || tp <= 0) && ladder.length) tp = ladder[0].price;
    if (sl == null || !isFinite(sl) || sl <= 0) {
      if (!auto) setCalcErr("SL is required.");
      return;
    }
    inFlight.current = true;
    if (!auto) {
      setBusy(true);
      setCalcErr(null);
    }
    try {
      const body = new URLSearchParams({
        ticker: t,
        average: String(entry),
        sl_price: String(sl),
        tp_price: tp != null && isFinite(tp) ? String(tp) : "0",
        tp_amount_pct: f.tpAmountPct.trim() || "100",
        sl_amount_pct: f.slAmountPct.trim() || "100",
        model_name: f.modelName,
        model_desc: f.modelDesc,
        order_type: f.orderType,
        auto_refresh: auto ? "1" : "0",
        apply_regime_multiplier: f.applyMult ? "1" : "0",
        link_window_seconds_override: f.linkOverride,
        size_override: f.sizeOverride.trim(),
        tp_levels: ladder.length ? JSON.stringify(ladder) : "",
        model_id: f.modelId
      });
      const r = await fetch("/calculator/calculate?format=json", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString()
      });
      const text = await r.text();
      let data = null;
      try {
        data = JSON.parse(text);
      } catch (e) {
      }
      if (tickerRef.current !== t) return;
      if (!data || !r.ok) {
        if (!auto) setCalcErr(_ptStrip(text) || "calc failed (" + r.status + ")");
        return;
      }
      setCalc(data);
      calcTickerRef.current = t;
      if (!auto) {
        setCalcErr(null);
        if (data.calc_id && data.eligible) setLwCalcId(data.calc_id);
        else setLwCalcId(null);
        _ptWriteJSON(sessionStorage, PT_RESULT_KEY, data);
        const { ladder: lad, ...rest } = f;
        _ptWriteJSON(localStorage, PT_STATE_KEY, { ...rest, ladder: lad });
        const entryRec = {
          ticker: t,
          side: data.side ? String(data.side).toUpperCase() : sl > entry ? "SHORT" : "LONG",
          orderType: f.orderType,
          entry,
          tp,
          sl,
          mult: data.regime_multiplier != null ? data.regime_multiplier : 1,
          regime: data.regime_label || regimeRef.current && regimeRef.current.label || "",
          ts: Date.now()
        };
        setRecent((prev) => {
          const next = [entryRec, ...prev].slice(0, 2);
          _ptWriteJSON(localStorage, PT_HIST_KEY, next);
          return next;
        });
      }
    } catch (e) {
      if (!auto) setCalcErr("calc failed \u2014 engine unreachable?");
    } finally {
      inFlight.current = false;
      if (!auto) setBusy(false);
      if (pendingManual.current) {
        pendingManual.current = false;
        setTimeout(() => doCalculate(false), 0);
      }
    }
  }, []);
  const hasCalc = !!calc;
  React.useEffect(() => {
    if (!autoRate || !hasCalc) return;
    const t = setInterval(() => {
      if (!inFlight.current && calcTickerRef.current) doCalculate(true);
    }, autoRate * 1e3);
    return () => clearInterval(t);
  }, [autoRate, hasCalc, doCalculate]);
  const setOrderType = (k) => {
    setForm((f) => ({ ...f, orderType: k }));
    setAutoRate((r) => r === 0 ? 0 : k === "market" ? 1 : 30);
  };
  const doClear = async () => {
    setForm({ ...PT_FORM_DEFAULTS });
    setCalc(null);
    setCalcErr(null);
    setLwCalcId(null);
    setLw(null);
    setLivePrice(null);
    setOb(null);
    setSizeUnit("notional");
    setAutoRate(1);
    calcTickerRef.current = null;
    try {
      localStorage.removeItem(PT_STATE_KEY);
      sessionStorage.removeItem(PT_RESULT_KEY);
    } catch (e) {
    }
    try {
      await fetch("/calculator/clear", { method: "POST" });
    } catch (e) {
    }
  };
  const saveWindow = async (v) => {
    setWinSaved(null);
    try {
      const r = await fetch("/calculator/window", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ window_seconds: v }).toString()
      });
      const txt = _ptStrip(await r.text());
      const ok = /✓|saved/i.test(txt);
      setWinSaved({ text: txt || (r.ok ? "saved \u2713" : "save failed"), ok });
      if (ok) setCtxInfo((c2) => c2 ? { ...c2, window_seconds: +v } : c2);
    } catch (e) {
      setWinSaved({ text: "save failed \u2014 engine unreachable?", ok: false });
    }
  };
  const recall = (r) => {
    setForm((f) => ({
      ...f,
      ticker: r.ticker,
      orderType: r.orderType || "market",
      limitPrice: r.orderType !== "market" && r.entry != null ? String(r.entry) : f.limitPrice,
      tpslMode: "price",
      tpPrice: r.tp != null ? String(r.tp) : "",
      slPrice: r.sl != null ? String(r.sl) : ""
    }));
    setAutoRate((cur) => cur === 0 ? 0 : (r.orderType || "market") === "market" ? 1 : 30);
  };
  const copyCell = (label, value) => {
    const clean = String(value).replace(/,/g, "");
    try {
      navigator.clipboard && navigator.clipboard.writeText(clean).catch(() => {
      });
    } catch (e) {
    }
    setCopied(label);
    setTimeout(() => setCopied((c2) => c2 === label ? null : c2), 1200);
  };
  const halted = !!(st && st.halted);
  const blocked = !!(st && st.blocked);
  const gateDot = halted ? ["err", "HALTED"] : blocked ? ["warn", "LIMIT"] : ["ok", "READY"];
  const isCommodity = PT_COMMODITY_RE.test(tickerNorm);
  const effSizeUnit = sizeUnit === "lot" && !isCommodity ? "contracts" : sizeUnit;
  const c = calc || {};
  const regLabel = (calc && calc.regime_label || regime && regime.label || "\u2014").replace(/_/g, " ");
  const regMult = calc && calc.regime_multiplier != null ? calc.regime_multiplier : regime && regime.multiplier != null ? regime.multiplier : 1;
  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      doCalculate(false);
    }
  };
  const enterTo = (fn) => (e) => {
    if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      fn();
    }
  };
  const focusId = (id) => () => {
    const el = document.getElementById(id);
    if (el) el.focus();
  };
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "02 Pre-Trade", style: {
    width: "100%",
    height: "100%",
    background: "var(--qe-bg)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden"
  }, onKeyDown: onKey }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "Pre-Trade", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "Pre-Trade", subtitle: "position sizing \xB7 TP/SL \xB7 risk gate \xB7 exec link" }, /* @__PURE__ */ React.createElement(StatusDot, { tone: gateDot[0], label: "GATE", value: gateDot[1] }), /* @__PURE__ */ React.createElement(StatusDot, { tone: "info", label: "REGIME", value: regLabel !== "\u2014" ? `${String(regLabel).toUpperCase().slice(0, 14)} \xD7${_ptFmtN(regMult, 1)}` : "\u2014" }), /* @__PURE__ */ React.createElement(StatusDot, { tone: "info", label: "LINK", value: ctxInfo ? Math.round(ctxInfo.window_seconds / 60) + "m window" : "\u2014" }), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.56rem", color: "var(--qe-muted)" } }, "risk/trade ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, riskPct != null ? _ptFmtN(riskPct * 100, 2) + "%" : "\u2014"))), halted && /* @__PURE__ */ React.createElement(
    Banner,
    {
      tone: "err",
      tag: "HALT",
      title: "CALCULATOR BLOCKED \u2014 DD hard stop (enforced)",
      detail: (st.halt_reason || "drawdown limit breached") + " \xB7 new sizing calcs are gated \xB7 open positions are NOT affected \xB7 override via Dashboard"
    }
  ), !halted && blocked && /* @__PURE__ */ React.createElement(
    Banner,
    {
      tone: "warn",
      tag: "RISK",
      title: "RISK LIMIT REACHED (advisory)",
      detail: `dd_state=${st.dd_state} \xB7 weekly=${st.weekly_pnl_state} \xB7 advisory mode \u2014 trading continues, calcs stay enabled`
    }
  ), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, padding: "2px 8px", background: "var(--qe-page)", borderBottom: "1px solid var(--qe-line)", opacity: halted ? 0.45 : 1 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.56rem", color: "var(--qe-muted)", letterSpacing: "0.1em" } }, "\u21BB AUTO-REFRESH"), /* @__PURE__ */ React.createElement(PeriodSelector, { options: [[1, "1s"], [5, "5s"], [10, "10s"], [30, "30s"], [0, "\u23F8"]], value: autoRate, onChange: setAutoRate }), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.56rem", color: "var(--qe-muted)", letterSpacing: "0.1em", marginLeft: 10 } }, "MATCH WINDOW"), /* @__PURE__ */ React.createElement(
    "select",
    {
      className: "qe-input qe-select",
      style: { width: "auto", height: 22, fontSize: "0.6rem" },
      value: ctxInfo ? String(ctxInfo.window_seconds) : "300",
      onChange: (e) => saveWindow(e.target.value)
    },
    ctxInfo && ![60, 300, 900].includes(ctxInfo.window_seconds) ? /* @__PURE__ */ React.createElement("option", { value: String(ctxInfo.window_seconds) }, ctxInfo.window_seconds, " s") : null,
    /* @__PURE__ */ React.createElement("option", { value: "60" }, "1 min"),
    /* @__PURE__ */ React.createElement("option", { value: "300" }, "5 min"),
    /* @__PURE__ */ React.createElement("option", { value: "900" }, "15 min")
  ), winSaved ? /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: winSaved.ok ? "var(--qe-green)" : "var(--qe-red)" } }, winSaved.text) : null, /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement(PtCountdownChip, { lw })), /* @__PURE__ */ React.createElement("div", { style: { position: "relative", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement(GridWorkspace, { style: halted ? { filter: "blur(3px) grayscale(0.4)", pointerEvents: "none", userSelect: "none" } : {} }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 10, h: 12, minW: 6, minH: 8 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Order Inputs",
      style: { height: "100%" },
      bodyStyle: { overflow: "auto" },
      right: /* @__PURE__ */ React.createElement(Badge, { tone: form.orderType === "limit" ? "ok" : "warn" }, form.orderType === "limit" ? "MAKER FEE" : "TAKER FEE"),
      foot: !tickerNorm ? { tone: "sub", msg: "local \xB7 enter a ticker to poll price" } : qeFootState({
        loading: netPx.ms == null && !netPx.err,
        err: netPx.err,
        hasData: livePrice != null,
        ms: netPx.ms,
        retrying: true
      })
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Order Type"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4, marginTop: 3 } }, [["market", "MARKET"], ["limit", "LIMIT"], ["stop", "STOP"]].map(([k, l]) => /* @__PURE__ */ React.createElement("button", { key: k, onClick: () => setOrderType(k), className: `qe-btn ${form.orderType === k ? "qe-btn-primary" : ""}`, style: { height: 26, justifyContent: "center" } }, l)))), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Ticker"), /* @__PURE__ */ React.createElement(
      "input",
      {
        id: "pt-ticker",
        className: "qe-input",
        value: form.ticker,
        onChange: set("ticker"),
        placeholder: "BTCUSDT",
        onKeyDown: enterTo(focusId(form.orderType === "market" ? "pt-tp" : "pt-entry"))
      }
    )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Entry Price", form.orderType === "market" && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)", marginLeft: 4 } }, "(live)")), form.orderType === "market" ? /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "qe-input",
        readOnly: true,
        value: livePrice != null ? _ptFmtP(livePrice) : "\u2014",
        style: { color: "var(--qe-green)", borderColor: "var(--qe-bg-green)" }
      }
    ) : /* @__PURE__ */ React.createElement(
      "input",
      {
        id: "pt-entry",
        className: "qe-input",
        value: form.limitPrice,
        onChange: set("limitPrice"),
        placeholder: livePrice != null ? _ptFmtP(livePrice) : "",
        onKeyDown: enterTo(focusId("pt-tp"))
      }
    ))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 4 } }, /* @__PURE__ */ React.createElement(Lbl, null, "TP / SL"), /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["price", "BY PRICE"], ["pct", "BY %"]], value: form.tpslMode, onChange: (v) => setForm((f) => ({ ...f, tpslMode: v })) }), form.tpslMode === "pct" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.56rem" } }, "side"), /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["long", "LONG"], ["short", "SHORT"]], value: form.sideSel, onChange: (v) => setForm((f) => ({ ...f, sideSel: v })) }))), form.tpslMode === "price" ? /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "TP Price"), /* @__PURE__ */ React.createElement("input", { id: "pt-tp", className: "qe-input", value: form.tpPrice, onChange: set("tpPrice"), onKeyDown: enterTo(focusId("pt-sl")), style: { color: "var(--qe-green)" } })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "SL Price"), /* @__PURE__ */ React.createElement("input", { id: "pt-sl", className: "qe-input", value: form.slPrice, onChange: set("slPrice"), onKeyDown: enterTo(() => doCalculate(false)), style: { color: "var(--qe-red)" } }))) : /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "TP %"), /* @__PURE__ */ React.createElement("input", { id: "pt-tp", className: "qe-input", value: form.tpPct, onChange: set("tpPct"), onKeyDown: enterTo(focusId("pt-sl")), style: { color: "var(--qe-green)" } })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "SL %"), /* @__PURE__ */ React.createElement("input", { id: "pt-sl", className: "qe-input", value: form.slPct, onChange: set("slPct"), onKeyDown: enterTo(() => doCalculate(false)), style: { color: "var(--qe-red)" } }))), (() => {
      const entry = form.orderType === "market" ? livePrice : parseFloat(form.limitPrice);
      if (!entry || !isFinite(entry)) return null;
      if (form.tpslMode === "price") {
        const tpv = parseFloat(form.tpPrice), slv = parseFloat(form.slPrice);
        if (!isFinite(tpv) && !isFinite(slv)) return null;
        const pc = (v) => {
          const p = Math.abs(v - entry) / entry * 100;
          return p > 100 ? ">100%" : _ptFmtN(p, 2) + "%";
        };
        return /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.6rem", color: "var(--qe-sub)", marginTop: 3, padding: "2px 4px", background: "var(--qe-panel)" } }, isFinite(tpv) ? /* @__PURE__ */ React.createElement(React.Fragment, null, "TP ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, pc(tpv))) : null, isFinite(tpv) && isFinite(slv) ? "  \xB7  " : "", isFinite(slv) ? /* @__PURE__ */ React.createElement(React.Fragment, null, "SL ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)" } }, pc(slv))) : null);
      }
      const tpp = parseFloat(form.tpPct), slp = parseFloat(form.slPct);
      if (!isFinite(tpp) && !isFinite(slp)) return null;
      const dir = form.sideSel === "short" ? -1 : 1;
      return /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.6rem", color: "var(--qe-sub)", marginTop: 3, padding: "2px 4px", background: "var(--qe-panel)" } }, isFinite(tpp) ? /* @__PURE__ */ React.createElement(React.Fragment, null, "TP ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, _ptFmtP(entry * (1 + dir * tpp / 100)))) : null, isFinite(tpp) && isFinite(slp) ? "  \xB7  " : "", isFinite(slp) ? /* @__PURE__ */ React.createElement(React.Fragment, null, "SL ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)" } }, _ptFmtP(entry * (1 - dir * slp / 100)))) : null);
    })()), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "TP Amount %"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.tpAmountPct, onChange: set("tpAmountPct") })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "SL Amount %"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.slAmountPct, onChange: set("slAmountPct") }))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6 } }, /* @__PURE__ */ React.createElement(Lbl, null, "TP Ladder ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "(optional \xB7 TP1 feeds the single TP when blank)")), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), form.ladder.length < 10 && /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: () => setForm((f) => ({ ...f, ladder: [...f.ladder, { price: "", pct: "" }] })) }, "+ level")), form.ladder.map((row, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "grid", gridTemplateColumns: "1fr 1fr 24px", gap: 4, marginTop: 3 } }, /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "qe-input",
        placeholder: `TP${i + 1} price`,
        value: row.price,
        onChange: (e) => {
          const v = e.target.value;
          setForm((f) => ({ ...f, ladder: f.ladder.map((r, j) => j === i ? { ...r, price: v } : r) }));
        }
      }
    ), /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "qe-input",
        placeholder: "size %",
        value: row.pct,
        onChange: (e) => {
          const v = e.target.value;
          setForm((f) => ({ ...f, ladder: f.ladder.map((r, j) => j === i ? { ...r, pct: v } : r) }));
        }
      }
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "qe-btn qe-btn-sm qe-btn-ghost",
        title: "remove level",
        onClick: () => setForm((f) => ({ ...f, ladder: f.ladder.filter((_, j) => j !== i) }))
      },
      "\u2715"
    ))), (() => {
      const sum = form.ladder.reduce((a, r) => a + (parseFloat(r.pct) || 0), 0);
      if (!form.ladder.length) return null;
      return /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.56rem", marginTop: 2, color: sum > 100 ? "var(--qe-red)" : "var(--qe-muted)" } }, "\u03A3 ", _ptFmtN(sum, 1), "% ", sum > 100 ? "\u2014 exceeds 100%" : "of position");
    })()), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Model (library)"), /* @__PURE__ */ React.createElement(
      "select",
      {
        className: "qe-input qe-select",
        value: form.modelId,
        onChange: (e) => {
          const v = e.target.value;
          setForm((f) => ({ ...f, modelId: v }));
          applyPrefill(v);
        }
      },
      /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 no model \u2014"),
      form.modelId && (!models || !models.some((m) => String(m.id) === String(form.modelId))) ? /* @__PURE__ */ React.createElement("option", { value: form.modelId }, "model #", form.modelId) : null,
      (models || []).map((m) => /* @__PURE__ */ React.createElement("option", { key: m.id, value: String(m.id) }, m.name))
    )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Model Name (free text)"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.modelName, onChange: set("modelName"), placeholder: "e.g. MA-Cross-V2" }))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Model Description"), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.modelDesc, onChange: set("modelDesc"), placeholder: "optional notes" })), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Link Window Override ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "(blank \u2192 account default)")), /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", value: form.linkOverride, onChange: set("linkOverride") }, /* @__PURE__ */ React.createElement("option", { value: "" }, "(use account default)"), /* @__PURE__ */ React.createElement("option", { value: "1800" }, "30 min"), /* @__PURE__ */ React.createElement("option", { value: "3600" }, "1 h"), /* @__PURE__ */ React.createElement("option", { value: "14400" }, "4 h"), /* @__PURE__ */ React.createElement("option", { value: "21600" }, "6 h"), /* @__PURE__ */ React.createElement("option", { value: "43200" }, "12 h"), /* @__PURE__ */ React.createElement("option", { value: "86400" }, "24 h"))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Size Override ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "(contracts \xB7 blank \u2192 engine)")), /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: form.sizeOverride, onChange: set("sizeOverride"), placeholder: "engine-recommended" }))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, padding: "3px 6px", background: "var(--qe-panel)", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement("label", { style: { display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: "0.62rem", color: "var(--qe-text)", fontFamily: "var(--qe-mono)" } }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: form.applyMult, onChange: set("applyMult"), style: { accentColor: "var(--qe-cyan)" } }), "Apply regime multiplier"), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.6rem", color: "var(--qe-sub)" } }, regLabel), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.62rem", color: "var(--qe-cyan)", fontWeight: 700 } }, "\xD7", _ptFmtN(regMult, 1), " size")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6 } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "qe-btn qe-btn-primary qe-btn-lg",
        style: { flex: 1, justifyContent: "center" },
        onClick: () => doCalculate(false),
        disabled: busy
      },
      busy ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.8rem", label: "calculating" }) : "Calculate"
    ), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-lg", onClick: doClear, disabled: busy }, "Clear")), calcErr ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.62rem", color: "var(--qe-red)" } }, calcErr) : null, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", textAlign: "center", fontFamily: "var(--qe-mono)" } }, "enter advances fields \xB7 enter on SL submits \xB7 ctrl+enter anywhere"))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 12, w: 10, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Setup Summary",
      tag: "CLICK TO COPY",
      style: { height: "100%" },
      foot: _ptCalcFoot(busy, calcErr, calc),
      right: /* @__PURE__ */ React.createElement(
        PeriodSelector,
        {
          options: isCommodity ? [["notional", "NOTIONAL"], ["contracts", "CONTRACTS"], ["lot", "LOT"]] : [["notional", "NOTIONAL"], ["contracts", "CONTRACTS"]],
          value: effSizeUnit,
          onChange: setSizeUnit
        }
      )
    },
    !calc ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: "No calc yet", hint: "Run Calculate to populate the paste-ready setup." }) : (() => {
      const sideUp = (c.side || "").toUpperCase();
      const szVal = effSizeUnit === "notional" ? c.notional : c.size;
      const szDisp = effSizeUnit === "notional" ? _ptFmtN(c.notional) : _ptFmtSz(c.size);
      const copyAll = () => {
        const block = [
          `Symbol: ${c.ticker}`,
          `Direction: ${sideUp}`,
          `Size (${effSizeUnit}): ${szVal}`,
          `Entry: ${c.average}`,
          `TP: ${c.tp_price || "\u2014"}`,
          `SL: ${c.sl_price}`
        ].join("\n");
        copyCell("ALL", block);
      };
      return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, /* @__PURE__ */ React.createElement(PtCopyCell, { label: "Symbol", value: c.ticker || "", color: "var(--qe-cyan)", copied, onCopy: copyCell }), /* @__PURE__ */ React.createElement(PtCopyCell, { label: "Direction", value: sideUp, color: sideUp === "SHORT" ? "var(--qe-red)" : "var(--qe-green)", copied, onCopy: copyCell }), /* @__PURE__ */ React.createElement(PtCopyCell, { label: `Size (${effSizeUnit.toUpperCase()})`, value: szVal != null ? szVal : "", display: szDisp, color: "var(--qe-cyan)", copied, onCopy: copyCell })), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, /* @__PURE__ */ React.createElement(PtCopyCell, { label: "Entry", value: c.average != null ? c.average : "", display: _ptFmtP(c.average), color: "var(--qe-text)", copied, onCopy: copyCell }), /* @__PURE__ */ React.createElement(PtCopyCell, { label: "TP Price", value: c.tp_price || "", display: c.tp_price ? _ptFmtP(c.tp_price) : "\u2014", color: "var(--qe-green)", copied, onCopy: copyCell }), /* @__PURE__ */ React.createElement(PtCopyCell, { label: "SL Price", value: c.sl_price != null ? c.sl_price : "", display: _ptFmtP(c.sl_price), color: "var(--qe-red)", copied, onCopy: copyCell }))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end", marginTop: 6 } }, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: copyAll }, copied === "ALL" ? "\u2713 copied" : "\u29C9 copy all")));
    })()
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 10, y: 0, w: 7, h: 5, minW: 5, minH: 4 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Recent Setups",
      count: recent.length,
      style: { height: "100%" },
      foot: { tone: "ok", msg: "local" }
    },
    !recent.length ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: "No recent setups" }) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 3 } }, recent.map((r, i) => /* @__PURE__ */ React.createElement("div", { key: i, onClick: () => recall(r), title: "Click to recall into the form", style: {
      padding: "4px 7px",
      border: "1px solid var(--qe-line)",
      background: "var(--qe-panel)",
      cursor: "pointer"
    } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 2 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.68rem", fontWeight: 700, color: "var(--qe-cyan)" } }, r.ticker), /* @__PURE__ */ React.createElement(Badge, { tone: r.side === "LONG" ? "ok" : "err" }, r.side), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", textTransform: "uppercase" } }, r.orderType), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.54rem", color: "var(--qe-muted)" } }, /* @__PURE__ */ React.createElement(PtAge, { ts: r.ts }))), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.6rem", color: "var(--qe-sub)" } }, "Entry ", _ptFmtP(r.entry), " \xB7 TP ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, r.tp != null ? _ptFmtP(r.tp) : "\u2014"), " \xB7 SL ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)" } }, _ptFmtP(r.sl))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.54rem", marginTop: 1, fontFamily: "var(--qe-mono)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)" } }, (r.regime || "").replace(/_/g, " ").toUpperCase()), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, " \xD7", _ptFmtN(r.mult, 1), " size")))))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 17, y: 0, w: 7, h: 5, minW: 5, minH: 4 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Regime \xB7 ATR Volatility",
      hot: true,
      style: { height: "100%" },
      foot: qeFootState({ loading: netRegime.ms == null && !netRegime.err, err: netRegime.err, hasData: regime != null, ms: netRegime.ms, retrying: true })
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Current Regime"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.74rem", fontWeight: 700, color: "var(--qe-cyan)" } }, String(regLabel).toUpperCase()), calc && calc.regime_stale || !calc && regime && regime.label == null ? /* @__PURE__ */ React.createElement(Badge, { tone: "warn" }, "STALE") : null, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.78rem", fontWeight: 700, color: "var(--qe-cyan)" } }, "\xD7", _ptFmtN(regMult, 1), " size")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", marginTop: 2 } }, riskPct != null ? `${_ptFmtN(riskPct * 100, 2)}% \u2192 ${_ptFmtN(riskPct * 100 * regMult, 2)}% risk` : "", calc && calc.regime_mode ? ` \xB7 mode ${calc.regime_mode}` : regime && regime.mode ? ` \xB7 mode ${regime.mode}` : "")), /* @__PURE__ */ React.createElement("div", { style: { borderTop: "1px solid var(--qe-line)" } }), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Volatility (atr_c)"), calc && calc.atr_c != null ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "1rem", fontWeight: 700 } }, _ptFmtN(calc.atr_c, 2)), /* @__PURE__ */ React.createElement(Badge, { tone: calc.atr_category === "normal" ? "ok" : calc.atr_category === "not_volatile" ? "info" : "warn" }, String(calc.atr_category || "").toUpperCase())), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", marginTop: 2 } }, "ATR(", "100", ",4h) ", _ptFmtP(calc.atr100), " \xB7 ATR(14,4h) ", _ptFmtP(calc.atr14))) : /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.6rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", marginTop: 4 } }, "run Calculate for the ticker's ATR read")))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 10, y: 5, w: 14, h: 7, minW: 8, minH: 7 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Position Result",
      style: { height: "100%" },
      right: calc ? /* @__PURE__ */ React.createElement(Badge, { tone: c.eligible ? "ok" : "err" }, c.eligible ? "\u2713 ELIGIBLE" : "\u26D4 INELIGIBLE") : null,
      bodyStyle: { padding: 0 },
      foot: _ptCalcFoot(busy, calcErr, calc)
    },
    !calc ? /* @__PURE__ */ React.createElement("div", { style: { padding: 10 } }, /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: "No calc yet", hint: "Size a setup to see the position result." })) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", height: "100%" } }, !c.eligible && c.ineligible_reason ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.62rem", color: "var(--qe-red)", padding: "4px 8px", borderBottom: "1px solid var(--qe-line)" } }, "\u26D4 ", c.ineligible_reason) : null, c.equity_stale || c.mark_price_stale ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.58rem", color: "var(--qe-amber)", padding: "3px 8px", borderBottom: "1px solid var(--qe-line)" } }, c.equity_stale ? "\u26A0 equity snapshot stale" : "", c.equity_stale && c.mark_price_stale ? " \xB7 " : "", c.mark_price_stale ? `\u26A0 mark price stale${c.mark_price_age != null ? ` (${Math.round(c.mark_price_age)}s)` : ""}` : "") : null, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 1px 1.05fr 1px 1fr", gap: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "7px 12px 7px 8px", display: "flex", flexDirection: "column", overflow: "auto" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Position"), /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement(Lbl, null, "Size (Contracts) ", form.applyMult && c.regime_multiplier != null && c.regime_multiplier !== 1 ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\xD7", _ptFmtN(c.regime_multiplier, 1), " regime") : null, " ", c.size_overridden ? /* @__PURE__ */ React.createElement(Badge, { tone: "warn" }, "OVERRIDE") : null), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "1.5rem", fontWeight: 700, color: "var(--qe-cyan)", lineHeight: 1.05 } }, _ptFmtSz(c.size)), c.size_raw != null && c.size_raw !== c.size ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "without regime: ", _ptFmtSz(c.size_raw)) : null, !c.eligible && c.would_be_size ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "would-be: ", _ptFmtSz(c.would_be_size)) : null), /* @__PURE__ */ React.createElement(FieldList, { rows: [
      { label: "Notional", value: _ptFmtN(c.notional) + " USDT" },
      { label: "Exposure \xD7", value: _ptFmtN(c.est_exposure, 2) + "\xD7" },
      { label: "TP \u2192 Profit", value: _ptSign(c.tp_usdt), color: "green" },
      { label: "SL \u2192 Loss", value: _ptSign(c.sl_usdt != null ? -Math.abs(c.sl_usdt) : null), color: "red" }
    ] })), /* @__PURE__ */ React.createElement("div", { style: { background: "var(--qe-line)" } }), /* @__PURE__ */ React.createElement("div", { style: { padding: "7px 12px", display: "flex", flexDirection: "column", overflow: "auto" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Pricing"), /* @__PURE__ */ React.createElement(FieldList, { dense: true, rows: [
      { label: "Ticker", value: c.ticker, color: "cyan" },
      { label: "Side", value: (c.side || "").toUpperCase(), color: (c.side || "") === "short" ? "red" : "green" },
      { label: "Order Type", value: (c.order_type || "").toUpperCase() },
      { label: "Avg Entry", value: _ptFmtP(c.average) },
      { label: "Risk USDT", value: _ptFmtN(c.risk_usdt) },
      { label: "Base Size", value: _ptFmtN(c.base_size), hint: "USDT" },
      { label: "Est. Fill", value: _ptFmtP(c.est_fill_price) },
      { label: "1% Depth / Mid", value: _ptFmtN(c.one_percent_depth) + " USDT" },
      { label: "Best Bid / Ask", value: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, _ptFmtP(c.best_bid)), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, " / "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-red)" } }, _ptFmtP(c.best_ask))) }
    ] })), /* @__PURE__ */ React.createElement("div", { style: { background: "var(--qe-line)" } }), /* @__PURE__ */ React.createElement("div", { style: { padding: "7px 8px 7px 12px", display: "flex", flexDirection: "column", overflow: "auto" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "After Costs"), /* @__PURE__ */ React.createElement(FieldList, { dense: true, rows: [
      { label: "Est. Slippage", value: c.est_slippage != null ? _ptFmtN(c.est_slippage * 100, 4) + "%" : "\u2014", color: "amber" },
      { label: "Slip USDT", value: _ptFmtN(c.est_slippage_usdt) },
      { label: "Net Profit", value: _ptSign(c.est_profit), color: "green" },
      { label: "Net Loss", value: c.est_loss != null ? _ptSign(-Math.abs(c.est_loss)) : "\u2014", color: "red" },
      { label: "Est. R : R", value: _ptFmtN(c.est_r, 2), color: (c.est_r || 0) >= 1 ? "green" : "red" },
      { label: "Portfolio Exp.", value: _ptFmtN(c.est_exposure, 2) + "\xD7" },
      { label: `RT Fee (${form.orderType === "limit" ? "Maker" : "Taker"})`, value: c.fee_rate != null ? _ptFmtN(c.fee_rate * 2 * 100, 3) + "%" : "\u2014", color: "sub" }
    ] }))))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 10, y: 12, w: 7, h: 6, minW: 5, minH: 4 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Correlated Sector Exposure",
      style: { height: "100%" },
      foot: _ptCalcFoot(busy, calcErr, calc)
    },
    !calc || !c.correlated_exposure ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: "No calc yet" }) : /* @__PURE__ */ React.createElement(React.Fragment, null, c.exceeds_corr_limit ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.6rem", color: "var(--qe-red)", marginBottom: 4 } }, "\u26D4 correlated-exposure cap exceeded") : null, /* @__PURE__ */ React.createElement(FieldList, { rows: [
      ...Object.entries(c.correlated_exposure).map(([sector, v]) => ({
        label: sector,
        value: _ptSign(v),
        color: v > 0 ? "green" : v < 0 ? "red" : void 0
      })),
      { label: `New (${c.ticker})`, value: _ptSign(c.new_sector_exposure) + " USDT", emphasis: true }
    ] }))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 17, y: 12, w: 7, h: 6, minW: 5, minH: 4 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Live Orderbook",
      tag: "2s",
      style: { height: "100%" },
      right: ob && (ob.bids || []).length ? /* @__PURE__ */ React.createElement(StatusDot, { tone: "ok", label: "LIVE" }) : /* @__PURE__ */ React.createElement(StatusDot, { tone: "off", label: "\u2014" }),
      foot: !tickerNorm ? { tone: "sub", msg: "enter a ticker" } : qeFootState({ loading: netOb.ms == null && !netOb.err, err: netOb.err, hasData: ob != null, ms: netOb.ms, retrying: true })
    },
    !ob || !(ob.bids || []).length && !(ob.asks || []).length ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u3007", msg: tickerNorm ? "No depth yet" : "Enter a ticker" }) : (() => {
      const maxQ = Math.max(...[...ob.bids || [], ...ob.asks || []].map(([, q]) => parseFloat(q) || 0), 1e-9);
      const rowFor = (color) => ([p, s], i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", justifyContent: "space-between", fontFamily: "var(--qe-mono)", fontSize: "0.62rem", padding: "1px 0", position: "relative" } }, /* @__PURE__ */ React.createElement("span", { style: { position: "absolute", right: 0, top: 0, bottom: 0, width: `${Math.min(100, (parseFloat(s) || 0) / maxQ * 100) * 0.5}%`, background: `color-mix(in srgb, ${color} 8%, transparent)` } }), /* @__PURE__ */ React.createElement("span", { style: { color, position: "relative" } }, _ptFmtP(parseFloat(p))), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", position: "relative" } }, s));
      return /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", fontWeight: 700, color: "var(--qe-green)", letterSpacing: "0.1em", marginBottom: 3 } }, "BIDS"), (ob.bids || []).map(rowFor("var(--qe-green)"))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", fontWeight: 700, color: "var(--qe-red)", letterSpacing: "0.1em", marginBottom: 3 } }, "ASKS"), (ob.asks || []).map(rowFor("var(--qe-red)"))));
    })()
  ))), halted && /* @__PURE__ */ React.createElement("div", { style: {
    position: "absolute",
    inset: 0,
    zIndex: 40,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "rgba(0,0,0,0.35)"
  } }, /* @__PURE__ */ React.createElement("div", { style: { background: "var(--qe-card)", border: "1px solid var(--qe-red)", borderLeft: "4px solid var(--qe-red)", padding: "14px 18px", maxWidth: 460 } }, /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.8rem", fontWeight: 700, color: "var(--qe-red)", letterSpacing: "0.06em" } }, "CALCULATOR BLOCKED"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.64rem", color: "var(--qe-text)", marginTop: 6, lineHeight: 1.6 } }, st.halt_reason || "DD limit breached \xB7 enforcement mode ENFORCED"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.58rem", color: "var(--qe-sub)", marginTop: 6, lineHeight: 1.6 } }, "New sizing calcs are gated by the DD hard stop. Open positions are NOT affected. Recovery clears the gate automatically; a manual override lives on the Dashboard.")))), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
Object.assign(window, { PreTradePage });

;

/* ==== link-primitives.jsx ==== */
const lpPx = (v) => {
  if (v == null || isNaN(v)) return "\u2014";
  const a = Math.abs(+v);
  const d = a >= 1e3 ? 2 : a >= 1 ? 4 : 6;
  return (+v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
};
const lpUsd = (v, d = 2) => v == null || isNaN(v) ? "\u2014" : (v >= 0 ? "+" : "\u2212") + Math.abs(v).toFixed(d);
const lpPct = (v, d = 2) => v == null || isNaN(v) ? "\u2014" : (v >= 0 ? "+" : "\u2212") + Math.abs(v).toFixed(d) + "%";
const lpSgn = (v) => v > 0 ? "var(--qe-green)" : v < 0 ? "var(--qe-red)" : "var(--qe-sub)";
const lpClock = (s) => {
  if (s == null) return "\u2014";
  if (s <= 0) return "expired";
  const m = Math.floor(s / 60), ss = Math.floor(s % 60);
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(ss).padStart(2, "0")}`;
};
const useLpCountdown = (expiryMs) => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    const i = setInterval(force, 1e3);
    return () => clearInterval(i);
  }, []);
  return expiryMs != null ? Math.round((expiryMs - Date.now()) / 1e3) : null;
};
const CalcCountdown = ({ expiry, window: win = 300 }) => {
  const s = useLpCountdown(expiry);
  if (s == null) return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)", fontSize: "0.6rem" } }, "\u2014");
  const tone = s <= 0 ? "var(--qe-red)" : s <= 60 ? "var(--qe-amber)" : "var(--qe-green)";
  const pct = Math.max(0, Math.min(100, s / (win || 300) * 100));
  const r = 4, sw = 3, c = 2 * Math.PI * r, off = c * (1 - pct / 100);
  return /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", justifyContent: "flex-end", gap: 5, verticalAlign: "middle" }, title: `window ${win}s` }, /* @__PURE__ */ React.createElement("svg", { width: "11", height: "11", viewBox: "0 0 11 11", style: { transform: "rotate(-90deg)", flexShrink: 0, display: "block" } }, /* @__PURE__ */ React.createElement("circle", { cx: "5.5", cy: "5.5", r, fill: "none", stroke: "var(--qe-faint)", strokeWidth: sw }), /* @__PURE__ */ React.createElement(
    "circle",
    {
      cx: "5.5",
      cy: "5.5",
      r,
      fill: "none",
      stroke: tone,
      strokeWidth: sw,
      strokeDasharray: c,
      strokeDashoffset: off,
      style: { transition: "stroke-dashoffset 1s linear" }
    }
  )), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: tone, fontWeight: 700, fontSize: "0.6rem", lineHeight: "11px" } }, lpClock(s)));
};
const LP_LINK_META = {
  LINKED: { v1: "LINKED", v3: "LINKED", tone: "ok", col: "var(--qe-green)" },
  NEEDS_MANUAL_REVIEW: { v1: "NEEDS REVIEW", v3: "REVIEW", tone: "warn", col: "var(--qe-amber)" },
  UNLINKED: { v1: "UNLINKED", v3: "UNLINKED", tone: "err", col: "var(--qe-red)" },
  UNPLANNED: { v1: "UNPLANNED", v3: "UNPLAN", tone: "blue", col: "var(--qe-blue)" }
};
const LinkBadge = ({ status, variant = 1 }) => {
  const m = LP_LINK_META[status];
  if (!m) return null;
  if (variant === 3) {
    return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", fontWeight: 700, color: m.col, letterSpacing: "0.08em" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "["), m.v3, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "]"));
  }
  return /* @__PURE__ */ React.createElement(Badge, { tone: m.tone }, m.v1);
};
const LP_DEV_META = {
  green: { label: "ON-PLAN", col: "var(--qe-green)" },
  yellow: { label: "AMENDED", col: "var(--qe-amber)" },
  red: { label: "OFF-PLAN", col: "var(--qe-red)" }
};
const DevBadge = ({ pos }) => {
  const m = LP_DEV_META[pos.deviation_badge];
  if (!m) return /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014");
  const drift = Math.abs(pos.tp_drift_pct || 0) >= 0.1 ? `tp ${lpPct(pos.tp_drift_pct)}` : Math.abs(pos.sl_drift_pct || 0) >= 0.1 ? `sl ${lpPct(pos.sl_drift_pct)}` : null;
  const desc = pos.deviation_badge === "red" && !pos.calc_id ? "no calc" : drift;
  const title = `size \u0394 ${lpPct(pos.size_delta_pct)} \xB7 ${pos.amendment_count || 0} amendment${(pos.amendment_count || 0) === 1 ? "" : "s"}${pos.tpsl_amended ? " \xB7 TP/SL amended" : ""}`;
  return /* @__PURE__ */ React.createElement("span", { title, style: { display: "inline-flex", alignItems: "center", gap: 5, whiteSpace: "nowrap" } }, /* @__PURE__ */ React.createElement("span", { className: "qe-badge", style: { color: m.col, borderColor: m.col, background: "transparent", padding: "1px 5px", fontSize: "0.52rem" } }, m.label), desc && /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.55rem", color: m.col, fontWeight: 600 } }, desc), (pos.amendment_count || 0) > 0 && /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.52rem", color: "var(--qe-muted)" } }, "\u270E", pos.amendment_count));
};
const LP_EXIT_REASONS = {
  TP_PLANNED: { label: "TP \xB7 plan", tone: "ok" },
  TP_AMENDED: { label: "TP \xB7 amended", tone: "warn" },
  SL_PLANNED: { label: "SL \xB7 plan", tone: "err" },
  SL_AMENDED: { label: "SL \xB7 amended", tone: "warn" },
  TP_LADDER_COMPLETE: { label: "TP ladder", tone: "ok" },
  MIXED: { label: "Mixed", tone: "warn" },
  MANUAL_INTERVENTION: { label: "Intervention", tone: "mag" },
  MANUAL_DISCIPLINE_BREAK: { label: "Discipline", tone: "err" },
  MANUAL_NEW_OPPORTUNITY: { label: "New opp", tone: "blue" },
  MANUAL_OTHER: { label: "Manual", tone: "mute" },
  LIQUIDATION: { label: "Liquidation", tone: "err" },
  ADL: { label: "ADL", tone: "err" },
  EXPIRED: { label: "Expired", tone: "mute" }
};
const LP_MANUAL_REASONS = [
  { key: "MANUAL_INTERVENTION", label: "Intervention", hint: "Judgement call \u2014 exited against the plan deliberately" },
  { key: "MANUAL_DISCIPLINE_BREAK", label: "Discipline break", hint: "Fear / impatience \u2014 broke the plan, logging it honestly" },
  { key: "MANUAL_NEW_OPPORTUNITY", label: "New opportunity", hint: "Freed capital for a better setup" },
  { key: "MANUAL_OTHER", label: "Other", hint: "Free-text rationale below" }
];
const ExitBadge = ({ reason, note, pending }) => {
  if (!reason || pending) return /* @__PURE__ */ React.createElement(Badge, { tone: "warn" }, "SET REASON");
  const m = LP_EXIT_REASONS[reason] || { label: reason, tone: "mute" };
  return /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", gap: 3 } }, /* @__PURE__ */ React.createElement(Badge, { tone: m.tone }, m.label), note && /* @__PURE__ */ React.createElement("span", { title: note, style: { color: "var(--qe-muted)", fontSize: "0.6rem" } }, "\u270E"));
};
const lpCritRows = (order, cand) => [
  { k: "Ticker", calc: cand.ticker, order: order.symbol, ok: true },
  { k: "Direction", calc: (cand.side || "").toUpperCase(), order: (order.side || "").toUpperCase(), ok: true },
  { k: "In-window", calc: cand.age_hours != null ? `${(+cand.age_hours).toFixed(1)}h ago` : "\u2014", order: "loose 168h", ok: true },
  {
    k: "Entry",
    calc: lpPx(cand.effective_entry),
    order: lpPx(order.price),
    ok: !!cand.entry_match,
    diff: cand.entry_drift_pct != null ? lpPct(cand.entry_drift_pct * 100) : ""
  },
  {
    k: "Take-profit",
    calc: lpPx(cand.tp_price),
    order: lpPx(order.tp_trigger_price),
    ok: !!cand.tp_match,
    diff: cand.tp_drift_pct != null ? lpPct(cand.tp_drift_pct * 100) : ""
  },
  {
    k: "Stop-loss",
    calc: lpPx(cand.sl_price),
    order: lpPx(order.sl_trigger_price),
    ok: !!cand.sl_match,
    diff: cand.sl_drift_pct != null ? lpPct(cand.sl_drift_pct * 100) : ""
  }
];
const lpScore = (cand) => 3 + (cand.entry_match ? 1 : 0) + (cand.tp_match ? 1 : 0) + (cand.sl_match ? 1 : 0);
const MatchDiff = ({ order, candidate }) => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 1 } }, lpCritRows(order, candidate).map((c) => /* @__PURE__ */ React.createElement("div", { key: c.k, style: {
  display: "grid",
  gridTemplateColumns: "76px 1fr 1fr 52px 18px",
  alignItems: "center",
  gap: 6,
  padding: "2px 6px",
  background: c.ok ? "transparent" : "var(--qe-bg-red)",
  borderLeft: `2px solid ${c.ok ? "var(--qe-green)" : "var(--qe-red)"}`,
  fontFamily: "var(--qe-mono)",
  fontSize: "0.58rem"
} }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, c.k), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)" } }, c.calc), /* @__PURE__ */ React.createElement("span", { style: { color: c.ok ? "var(--qe-text)" : "var(--qe-red)" } }, c.order), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.52rem" } }, c.diff || ""), /* @__PURE__ */ React.createElement("span", { style: { color: c.ok ? "var(--qe-green)" : "var(--qe-red)", fontWeight: 700, textAlign: "right", fontSize: "0.78rem", lineHeight: 1 } }, c.ok ? "\u25CF" : "\u25CB"))));
const FundingWho = ({ pays }) => pays === "you" ? /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-red)", fontSize: "0.58rem", fontWeight: 700 } }, "PAY") : /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-green)", fontSize: "0.58rem", fontWeight: 700 } }, "EARN");
Object.assign(window, {
  lpPx,
  lpUsd,
  lpPct,
  lpSgn,
  lpClock,
  useLpCountdown,
  CalcCountdown,
  LinkBadge,
  DevBadge,
  ExitBadge,
  MatchDiff,
  FundingWho,
  LP_EXIT_REASONS,
  LP_MANUAL_REASONS,
  LP_LINK_META,
  LP_DEV_META,
  lpCritRows,
  lpScore
});

;

/* ==== pages-linkage.jsx ==== */
const _lkForm = async (url, fields, method = "POST") => {
  const body = new URLSearchParams();
  Object.entries(fields || {}).forEach(([k, v]) => {
    if (v != null) body.append(k, v);
  });
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString()
  });
  const raw = await r.text();
  return {
    ok: r.ok && !/alert-(error|warning)/.test(raw),
    text: _ptStrip(raw)
  };
};
const _lkCreated = (iso) => {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return isNaN(d) ? "\u2014" : d.toLocaleTimeString([], { hour12: false });
};
const _lkAgeH = (h) => {
  if (h == null || isNaN(h)) return "";
  if (h < 1) return `${Math.round(h * 60)}m`;
  const hh = Math.floor(h);
  return `${hh}h ${Math.round((h - hh) * 60)}m`;
};
const _lkDur = (ms) => {
  if (ms == null || isNaN(ms) || ms < 0) return "\u2014";
  const s = Math.floor(ms / 1e3);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(s / 3600);
  return `${h}h ${Math.floor(s % 3600 / 60)}m`;
};
const _lkHM = (ms) => {
  if (!ms) return "\u2014";
  const d = new Date(ms);
  return isNaN(d) ? "\u2014" : d.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" });
};
const _lkHMS = (ms) => {
  if (!ms) return "\u2014";
  const d = new Date(ms);
  return isNaN(d) ? "\u2014" : d.toLocaleTimeString([], { hour12: false });
};
const LkLinkResolver = ({ item, onDone }) => {
  const cands = item.candidates || [];
  const [selCand, setSelCand] = React.useState(cands[0] && cands[0].calc_id);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);
  const cand = cands.find((c) => c.calc_id === selCand) || cands[0];
  const act = async (kind) => {
    const label = kind === "link" ? `Link order #${item.id} to ${cand.calc_id}?` : `Mark order #${item.id} UNPLANNED?`;
    if (!window.confirm(label)) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = kind === "link" ? await _lkForm(`/orders/${item.id}/manual_link`, { calc_id: cand.calc_id }) : await _lkForm(`/orders/${item.id}/mark_unplanned`, {});
      setMsg({ text: r.text || (r.ok ? "done" : "failed"), ok: r.ok });
      if (r.ok) onDone(r.text || (kind === "link" ? `#${item.id} linked to ${cand.calc_id}` : `#${item.id} marked UNPLANNED`));
    } catch (e) {
      setMsg({ text: "action failed \u2014 engine unreachable?", ok: false });
    }
    setBusy(false);
  };
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", minHeight: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7, marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-cyan)", fontWeight: 700, fontSize: "0.72rem" } }, item.symbol), /* @__PURE__ */ React.createElement(Badge, { tone: (item.side || "").toUpperCase() === "BUY" || (item.side || "").toUpperCase() === "LONG" ? "ok" : "err" }, (item.side || "").toUpperCase()), /* @__PURE__ */ React.createElement(LinkBadge, { status: item.link_status }), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.52rem", color: "var(--qe-muted)" } }, _lkHM(item.created_at_ms), " \xB7 ", /* @__PURE__ */ React.createElement(PtAge, { ts: item.created_at_ms }))), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "5px 10px", padding: "6px 8px", border: "1px solid var(--qe-line)", marginBottom: 8 } }, /* @__PURE__ */ React.createElement(KV, { l: "Order", v: "#" + (item.exchange_order_id || item.id) }), /* @__PURE__ */ React.createElement(KV, { l: "Type", v: (item.order_type || "").toUpperCase() }), /* @__PURE__ */ React.createElement(KV, { l: "Price", v: lpPx(item.price), color: "var(--qe-cyan)" }), /* @__PURE__ */ React.createElement(KV, { l: "Size", v: item.quantity != null ? (+item.quantity).toLocaleString(void 0, { maximumFractionDigits: 4 }) : "\u2014" }), /* @__PURE__ */ React.createElement(KV, { l: "Notional", v: item.price != null && item.quantity != null ? `${(item.price * item.quantity).toLocaleString(void 0, { maximumFractionDigits: 2 })} U` : "\u2014" }), /* @__PURE__ */ React.createElement(KV, { l: "Operator", v: item.operator_id || "\u2014" }), /* @__PURE__ */ React.createElement(KV, { l: "Client order id", v: item.client_order_id || "\u2014", span: true })), !cands.length ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(EmptyState, { tone: "warn", glyph: "\u2205", msg: "No candidate calcs in window", hint: "Mark unplanned or wait for a fresh calc." }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end", paddingTop: 8 } }, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", disabled: busy, onClick: () => act("unplanned") }, "UNPLANNED"))) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "qe-lbl", style: { margin: "2px 0 5px" } }, "Candidate calcs \xB7 ", cands.length), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 6 } }, cands.map((c, ci) => {
    const on = c.calc_id === selCand;
    const best = ci === 0;
    return /* @__PURE__ */ React.createElement("button", { key: c.calc_id, onClick: () => setSelCand(c.calc_id), style: {
      display: "flex",
      alignItems: "center",
      gap: 5,
      padding: "3px 8px",
      cursor: "pointer",
      background: on ? "var(--qe-active)" : "var(--qe-panel)",
      border: `1px solid ${on ? "var(--qe-cyan)" : "var(--qe-line)"}`
    } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.58rem", color: "var(--qe-cyan)", fontWeight: 700 } }, String(c.calc_id).slice(-6)), /* @__PURE__ */ React.createElement(Badge, { tone: best ? "warn" : "mute" }, lpScore(c), " / 6"), best ? /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.5rem", color: "var(--qe-amber)", letterSpacing: "0.08em", fontWeight: 700 } }, "BEST") : null, c.status === "released" ? /* @__PURE__ */ React.createElement(Badge, { tone: "mag" }, "REPLACEMENT") : null);
  })), cand ? /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap", padding: "0 2px 6px", fontFamily: "var(--qe-mono)", fontSize: "0.52rem", color: "var(--qe-muted)" } }, cand.model ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontWeight: 700 } }, cand.model) : null, /* @__PURE__ */ React.createElement("span", null, "created ", _lkCreated(cand.timestamp), cand.age_hours != null ? ` (${_lkAgeH(cand.age_hours)})` : ""), cand.r != null ? /* @__PURE__ */ React.createElement("span", null, "R ", (+cand.r).toFixed(2)) : null, (cand.tags || []).map((t) => /* @__PURE__ */ React.createElement("span", { key: t, style: { color: "var(--qe-purple)" } }, "#", t))) : null, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "76px 1fr 1fr 52px 18px", gap: 6, padding: "0 6px 2px", fontFamily: "var(--qe-mono)", fontSize: "0.5rem", color: "var(--qe-muted)", letterSpacing: "0.06em" } }, /* @__PURE__ */ React.createElement("span", null, "CRITERION"), /* @__PURE__ */ React.createElement("span", null, "CALC ", String(cand.calc_id).slice(-6)), /* @__PURE__ */ React.createElement("span", null, "ORDER #", item.id), /* @__PURE__ */ React.createElement("span", null, "DIFF"), /* @__PURE__ */ React.createElement("span", { style: { textAlign: "right" } }, "OK")), /* @__PURE__ */ React.createElement(MatchDiff, { order: item, candidate: cand }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, paddingTop: 8 } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.52rem", color: "var(--qe-muted)" } }, lpScore(cand), " / 6 \u2014 ", lpScore(cand) === 6 ? "eligible" : "below 6/6 threshold"), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", disabled: busy, onClick: () => act("unplanned") }, "UNPLANNED"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-success", disabled: busy, title: `Link ${cand.calc_id}`, onClick: () => act("link") }, busy ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.62rem" }) : "Link"))), msg ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.58rem", marginTop: 6, color: msg.ok ? "var(--qe-green)" : "var(--qe-red)" } }, msg.text) : null);
};
const LkReasonResolver = ({ item, onDone }) => {
  const [pick, setPick] = React.useState(null);
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);
  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await _lkForm(`/history/close_reason/${item.id}`, { exit_reason: pick, close_note: note }, "PUT");
      setMsg({ text: r.ok ? "reason saved" : r.text || "save failed", ok: r.ok });
      if (r.ok) onDone(`${item.symbol} close \u2192 ${(LP_EXIT_REASONS[pick] || {}).label || pick}`);
    } catch (e) {
      setMsg({ text: "save failed \u2014 engine unreachable?", ok: false });
    }
    setBusy(false);
  };
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", minHeight: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7, marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-cyan)", fontWeight: 700, fontSize: "0.72rem" } }, item.symbol), /* @__PURE__ */ React.createElement(Badge, { tone: item.direction === "LONG" ? "ok" : "err" }, item.direction), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontWeight: 700, color: lpSgn(item.net_pnl) } }, lpUsd(item.net_pnl), item.entry_price && item.quantity ? ` (${lpPct(item.net_pnl / (item.entry_price * item.quantity) * 100)})` : ""), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.52rem", color: "var(--qe-muted)" } }, "closed ", _lkHM(item.exit_time_ms))), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "5px 10px", padding: "6px 8px", border: "1px solid var(--qe-line)", marginBottom: 8 } }, /* @__PURE__ */ React.createElement(KV, { l: "Entry", v: lpPx(item.entry_price) }), /* @__PURE__ */ React.createElement(KV, { l: "Exit", v: lpPx(item.exit_price) }), /* @__PURE__ */ React.createElement(KV, { l: "Hold", v: _lkDur(item.hold_time_ms) }), /* @__PURE__ */ React.createElement(KV, { l: "Funding", v: lpUsd(item.funding_fees, 3), color: lpSgn(item.funding_fees) }), /* @__PURE__ */ React.createElement(KV, { l: "Closed at", v: _lkHM(item.exit_time_ms) }), /* @__PURE__ */ React.createElement(KV, { l: "Detected", v: (LP_EXIT_REASONS[item.exit_reason] || {}).label || item.exit_reason || "\u2014" })), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.54rem", color: "var(--qe-muted)", marginBottom: 7 } }, "No calc matched this close \u2014 categorize it (optional, never blocks)."), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5, marginBottom: 8 } }, LP_MANUAL_REASONS.map((r) => /* @__PURE__ */ React.createElement("button", { key: r.key, onClick: () => setPick(r.key), style: {
    textAlign: "left",
    padding: "6px 8px",
    cursor: "pointer",
    background: pick === r.key ? "var(--qe-active)" : "var(--qe-panel)",
    border: `1px solid ${pick === r.key ? "var(--qe-cyan)" : "var(--qe-line)"}`
  } }, /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.6rem", fontWeight: 700, color: pick === r.key ? "var(--qe-cyan)" : "var(--qe-text)" } }, r.label), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", marginTop: 2, lineHeight: 1.3 } }, r.hint)))), /* @__PURE__ */ React.createElement("input", { className: "qe-input", placeholder: "optional note\u2026", value: note, onChange: (e) => setNote(e.target.value) }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end", gap: 6, marginTop: 8 } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      className: "qe-btn qe-btn-sm qe-btn-ghost",
      disabled: busy,
      onClick: () => onDone(`${item.symbol} \u2014 left for later`)
    },
    "Later"
  ), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", disabled: !pick || busy, style: { opacity: pick ? 1 : 0.45 }, onClick: save }, busy ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.62rem" }) : "Save")), msg ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.58rem", marginTop: 6, color: msg.ok ? "var(--qe-green)" : "var(--qe-red)" } }, msg.text) : null);
};
const LinkagePage = () => {
  const [needs, setNeeds] = React.useState(null);
  const [positions, setPositions] = React.useState(null);
  const [calcs, setCalcs] = React.useState(null);
  const [funding, setFunding] = React.useState(null);
  const [closes, setCloses] = React.useState(null);
  const [sel, setSel] = React.useState(null);
  const [toast, setToast] = React.useState(null);
  const [cancelCalc, setCancelCalc] = React.useState(null);
  const [cancelReason, setCancelReason] = React.useState("");
  const [cancelBusy, setCancelBusy] = React.useState(false);
  const [nets, setNets] = React.useState({});
  const load = React.useCallback((which) => {
    const get = (url, fn, pick, key) => {
      const t0 = performance.now();
      return _ptJson(url).then((d) => {
        fn(pick ? d[pick] : d);
        setNets((m) => ({ ...m, [key]: { err: null, ms: performance.now() - t0 } }));
      }).catch((err) => {
        setNets((m) => ({ ...m, [key]: { ...m[key], err } }));
      });
    };
    if (!which || which === "fast") {
      get("/orders/needs_review", setNeeds, "orders", "needs");
      get("/api/linkage/positions", setPositions, "positions", "positions");
      get("/api/linkage/calcs", setCalcs, "calcs", "calcs");
    }
    if (!which || which === "slow") {
      get("/api/linkage/funding", setFunding, null, "funding");
      get("/api/linkage/closes", setCloses, "closes", "closes");
    }
  }, []);
  const lkFoot = (key, hasData) => {
    const n = nets[key] || {};
    return qeFootState({ loading: n.ms == null && !n.err, err: n.err, hasData, ms: n.ms, retrying: true });
  };
  React.useEffect(() => {
    load();
    const t1 = setInterval(() => load("fast"), 5e3);
    const t2 = setInterval(() => load("slow"), 3e4);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
    };
  }, [load]);
  React.useEffect(() => {
    if (typeof window.QE_SSE === "undefined") return;
    const sideKey = (s) => (s || "").toLowerCase().startsWith("l") ? "L" : "S";
    return window.QE_SSE.onChannel("position_update", (p) => {
      const list = Array.isArray(p.positions) ? p.positions : [];
      setPositions((prev) => {
        if (!prev) return prev;
        const by = {};
        list.forEach((x) => {
          by[x.symbol + "|" + sideKey(x.side)] = x;
        });
        return prev.map((r) => {
          const u = by[r.symbol + "|" + sideKey(r.direction)];
          return u && u.upnl != null ? { ...r, upnl: u.upnl } : r;
        });
      });
    });
  }, []);
  const flash = (m) => {
    setToast(m);
    setTimeout(() => setToast(null), 2600);
  };
  const inbox = [
    ...(needs || []).map((o) => ({ ...o, kind: "link", key: "L" + o.id })),
    ...(closes || []).filter((c) => c.pending_reason).map((c) => ({ ...c, kind: "close", key: "C" + c.id }))
  ];
  const active = inbox.find((i) => i.key === sel) || inbox[0];
  const resolveDone = (m) => {
    flash(m);
    setSel(null);
    load();
  };
  const posCols = [
    {
      key: "symbol",
      label: "Sym",
      filter: true,
      filterVal: (r) => (r.symbol || "").replace("USDT", ""),
      sortVal: (r) => (r.symbol || "").replace("USDT", ""),
      render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, (r.symbol || "").replace("USDT", ""))
    },
    {
      key: "direction",
      label: "Side",
      filter: { label: "SIDE" },
      filterVal: (r) => (r.direction || "").toUpperCase() || "\u2014",
      render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.direction === "LONG" ? "ok" : "err" }, (r.direction || " ")[0])
    },
    { key: "size", label: "Size", align: "right" },
    { key: "entry", label: "Entry", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, lpPx(r.entry)) },
    { key: "mark", label: "Mark", align: "right", render: (r) => lpPx(r.mark) },
    { key: "upnl", label: "uPnL", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(r.upnl), fontWeight: 700 } }, lpUsd(r.upnl)) },
    // TP/SL keeps sort:false — two independent prices, no single defensible key.
    // It DOES gain a protection facet: "which positions are unprotected" is a
    // real triage question and the raw fields answer it categorically.
    {
      key: "tpsl",
      label: "TP / SL",
      align: "right",
      sort: false,
      filter: { label: "TP/SL" },
      filterVal: (r) => (r.tp_live ? "TP" : "") + (r.tp_live && r.sl_live ? "+" : "") + (r.sl_live ? "SL" : "") || "NONE",
      render: (r) => /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.56rem" } }, /* @__PURE__ */ React.createElement("span", { className: "qe-up" }, r.tp_live ? lpPx(r.tp_live) : "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, " / "), /* @__PURE__ */ React.createElement("span", { className: "qe-dn" }, r.sl_live ? lpPx(r.sl_live) : "\u2014"))
    },
    { key: "link_status", label: "Link", filter: { label: "LINK" }, render: (r) => /* @__PURE__ */ React.createElement(LinkBadge, { status: r.link_status }) },
    // `dev` is not a row field — the badge reads deviation_badge. That made the
    // column invisible to BOTH sort and facet derivation (defined===0), which is
    // why it had opted out of sort entirely. sortVal/filterVal are the primitive's
    // escape hatch for exactly this. Ascending = worst-first: this is a triage
    // pane, so "off-plan at the top" is the useful direction.
    {
      key: "dev",
      label: "Plan deviation",
      sortVal: (r) => ({ red: 0, yellow: 1, green: 2 })[r.deviation_badge] != null ? { red: 0, yellow: 1, green: 2 }[r.deviation_badge] : 3,
      filter: { label: "PLAN" },
      filterVal: (r) => ((LP_DEV_META || {})[r.deviation_badge] || {}).label || "\u2014",
      render: (r) => /* @__PURE__ */ React.createElement(DevBadge, { pos: r })
    }
  ];
  const calcCols = [
    {
      key: "ticker",
      label: "Sym",
      filter: true,
      filterVal: (r) => (r.ticker || "").replace("USDT", ""),
      sortVal: (r) => (r.ticker || "").replace("USDT", ""),
      render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, (r.ticker || "").replace("USDT", ""))
    },
    {
      key: "side",
      label: "Side",
      filter: { label: "SIDE" },
      filterVal: (r) => (r.side || "").toUpperCase() || "\u2014",
      render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: (r.side || "").toLowerCase() === "long" ? "ok" : "err" }, (r.side || " ")[0].toUpperCase())
    },
    { key: "average", label: "Entry", align: "right", render: (r) => lpPx(r.average) },
    { key: "tp_price", label: "TP", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { className: "qe-up" }, lpPx(r.tp_price)) },
    { key: "sl_price", label: "SL", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { className: "qe-dn" }, lpPx(r.sl_price)) },
    // Same shape as posCols.dev: 'cd' is not a row field, so the column was
    // invisible to sort and facets. It renders a countdown off the REAL numeric
    // expiry_ms, and "which calc expires first" is the ordering this pane exists
    // for. The STATE facet hangs here because no column declares `status`, so the
    // facet engine could never see it.
    {
      key: "cd",
      label: "Link window",
      align: "right",
      sortVal: (r) => r.expiry_ms,
      filter: { label: "STATE" },
      filterVal: (r) => (r.status || "").toUpperCase() || "\u2014",
      render: (r) => /* @__PURE__ */ React.createElement(CalcCountdown, { expiry: r.expiry_ms, window: r.window_seconds })
    },
    // 'act' stays sort:false + filter:false — it is a button, not data.
    { key: "act", label: "", align: "right", sort: false, filter: false, search: false, render: (r) => (
      // operator-bug #6: open the ModelDialog confirm instead of window.confirm.
      /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "qe-btn qe-btn-sm qe-btn-ghost",
          title: "Cancel this calc",
          onClick: (e) => {
            e.stopPropagation();
            setCancelReason("");
            setCancelCalc(r);
          }
        },
        "\u2715"
      )
    ) }
  ];
  const fundCols = [
    {
      key: "symbol",
      label: "Sym",
      filter: true,
      filterVal: (r) => (r.symbol || "").replace("USDT", ""),
      sortVal: (r) => (r.symbol || "").replace("USDT", ""),
      render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, (r.symbol || "").replace("USDT", ""))
    },
    {
      key: "direction",
      label: "Side",
      filter: { label: "SIDE" },
      filterVal: (r) => (r.direction || "").toUpperCase() || "\u2014",
      render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.direction === "LONG" ? "ok" : "err" }, (r.direction || " ")[0])
    },
    { key: "rate", label: "Rate", align: "right", render: (r) => r.rate == null ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : /* @__PURE__ */ React.createElement("span", { style: { color: r.rate >= 0 ? "var(--qe-amber)" : "var(--qe-green)" } }, (r.rate * 100).toFixed(4), "%") },
    // Flow is this pane's categorical axis. filterVal/searchVal must mirror the
    // CELL, not the raw field: routes_cockpit assigns `pays` unconditionally, so
    // a rate==null row still carries pays='venue' and would facet as EARN while
    // rendering '—'. Returning '' for those rows drops them from the facet
    // (raw==='' is skipped) instead of filing them under a flow they don't have.
    {
      key: "pays",
      label: "Flow",
      filter: { label: "FLOW" },
      filterVal: (r) => r.rate == null ? "" : r.pays === "you" ? "PAY" : "EARN",
      searchVal: (r) => r.rate == null ? "" : r.pays === "you" ? "PAY" : "EARN",
      render: (r) => r.rate == null ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : /* @__PURE__ */ React.createElement(FundingWho, { pays: r.pays })
    },
    { key: "est_next", label: "Est", align: "right", render: (r) => r.rate == null ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(r.est_next), fontSize: "0.56rem" } }, lpUsd(r.est_next, 4)) },
    { key: "cum", label: "Cum", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(r.cum) } }, lpUsd(r.cum, 3)) }
  ];
  const closeCols = [
    {
      key: "symbol",
      label: "Sym",
      filter: true,
      filterVal: (r) => (r.symbol || "").replace("USDT", ""),
      sortVal: (r) => (r.symbol || "").replace("USDT", ""),
      render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, (r.symbol || "").replace("USDT", ""))
    },
    {
      key: "direction",
      label: "Side",
      filter: { label: "SIDE" },
      filterVal: (r) => (r.direction || "").toUpperCase() || "\u2014",
      render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.direction === "LONG" ? "ok" : "err" }, (r.direction || " ")[0])
    },
    { key: "entry_price", label: "Entry", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, lpPx(r.entry_price)) },
    { key: "exit_price", label: "Exit", align: "right", render: (r) => lpPx(r.exit_price) },
    // Bucket the continuous PnL into the sign trichotomy — the raw float is
    // never offered as options (that would be one option per row).
    {
      key: "net_pnl",
      label: "PnL",
      align: "right",
      filter: { label: "RESULT" },
      filterVal: (r) => (r.net_pnl || 0) > 0 ? "WIN" : (r.net_pnl || 0) < 0 ? "LOSS" : "FLAT",
      render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(r.net_pnl), fontWeight: 700 } }, lpUsd(r.net_pnl))
    },
    // Facet/sort/search all follow the RENDERED badge (pending → "SET REASON",
    // otherwise the LP_EXIT_REASONS label), so the column can no longer sort or
    // filter on a value the operator never sees. NB the facet stays invisible
    // while every close shares one reason — that bail is data-gated and resolves
    // itself as soon as reasons are categorised through this page's resolver.
    {
      key: "exit_reason",
      label: "Exit reason",
      filter: { label: "REASON" },
      filterVal: (r) => r.pending_reason ? "SET REASON" : ((LP_EXIT_REASONS || {})[r.exit_reason] || {}).label || r.exit_reason || "\u2014",
      sortVal: (r) => r.pending_reason ? "SET REASON" : ((LP_EXIT_REASONS || {})[r.exit_reason] || {}).label || r.exit_reason || "",
      searchVal: (r) => r.pending_reason ? "SET REASON pending" : `${((LP_EXIT_REASONS || {})[r.exit_reason] || {}).label || ""} ${r.exit_reason || ""} ${r.close_note || ""}`,
      render: (r) => /* @__PURE__ */ React.createElement(ExitBadge, { reason: r.exit_reason, note: r.close_note, pending: r.pending_reason })
    },
    { key: "funding_fees", label: "Fund", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(r.funding_fees), fontSize: "0.56rem" } }, lpUsd(r.funding_fees, 3)) }
  ];
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "03 Linkage", style: { width: "100%", height: "100%", background: "var(--qe-bg)", display: "flex", flexDirection: "column", position: "relative" } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "Linkage", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "Linkage", subtitle: "calc-linkage workspace \xB7 manual link \xB7 close reasons \xB7 positions \xB7 funding" }, /* @__PURE__ */ React.createElement(StatusDot, { tone: inbox.length ? "warn" : "ok", label: "QUEUE", value: `${inbox.length} open` })), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement(GridWorkspace, { persistId: "linkage" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 9, h: 24, minW: 6, minH: 10 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "MANUAL LINK \u2014 NEEDS REVIEW",
      right: /* @__PURE__ */ React.createElement(Badge, { tone: inbox.length ? "warn" : "ok" }, inbox.length),
      bodyStyle: { padding: 0, display: "flex", flexDirection: "column" },
      foot: lkFoot("needs", needs != null)
    },
    needs == null ? /* @__PURE__ */ React.createElement("div", { style: { padding: 10 } }, /* @__PURE__ */ React.createElement(Spinner, { label: "loading" })) : !inbox.length ? /* @__PURE__ */ React.createElement("div", { style: { flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 10 } }, /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "info", glyph: "\u2713", msg: "Inbox clear", hint: "Every order is linked and every close is categorized." })) : /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "162px 1fr" } }, /* @__PURE__ */ React.createElement("div", { style: { overflow: "auto", borderRight: "1px solid var(--qe-line)" } }, inbox.map((item) => {
      const on = active && item.key === active.key;
      const accent = item.kind === "link" ? "var(--qe-amber)" : "var(--qe-magenta)";
      const sideRaw = (item.kind === "link" ? item.side : item.direction) || "";
      const isLong = sideRaw.toUpperCase() === "BUY" || sideRaw.toUpperCase() === "LONG";
      const ts = item.kind === "link" ? item.created_at_ms : item.exit_time_ms;
      const notional = item.price && item.quantity ? (item.price * item.quantity).toFixed(2) : null;
      return /* @__PURE__ */ React.createElement("div", { key: item.key, onClick: () => setSel(item.key), style: {
        display: "flex",
        flexDirection: "column",
        gap: 3,
        padding: "7px 8px",
        cursor: "pointer",
        borderBottom: "1px solid var(--qe-faint)",
        borderLeft: `3px solid ${on ? "var(--qe-cyan)" : "transparent"}`,
        background: on ? "var(--qe-active)" : "transparent"
      } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 5 } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.5rem", color: accent, fontWeight: 700, letterSpacing: "0.08em" } }, item.kind === "link" ? "LINK" : "REASON"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", color: "var(--qe-cyan)", fontWeight: 700 } }, (item.symbol || "").replace("USDT", "")), sideRaw ? /* @__PURE__ */ React.createElement(Badge, { tone: isLong ? "ok" : "err" }, isLong ? "L" : "S") : null, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.5rem", color: "var(--qe-muted)", marginLeft: "auto" } }, _lkHMS(ts))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 5 } }, item.kind === "link" ? /* @__PURE__ */ React.createElement(LinkBadge, { status: item.link_status, variant: 3 }) : /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.52rem", color: "var(--qe-magenta)" } }, "set reason"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.5rem", marginLeft: "auto", color: item.kind === "link" ? "var(--qe-muted)" : lpSgn(item.net_pnl) } }, item.kind === "link" ? /* @__PURE__ */ React.createElement(React.Fragment, null, "#", item.id, " \xB7 ", /* @__PURE__ */ React.createElement(PtAge, { ts: item.created_at_ms })) : lpUsd(item.net_pnl))), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.5rem", color: "var(--qe-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, item.kind === "link" ? `${(item.order_type || "").toUpperCase()} @ ${lpPx(item.price)}${notional ? ` \xB7 ${notional}U` : ""}` : `${_lkDur(item.hold_time_ms)} \xB7 ${lpPx(item.entry_price)}\u2192${lpPx(item.exit_price)}`));
    })), /* @__PURE__ */ React.createElement("div", { style: { overflow: "auto", padding: 8 } }, active && (active.kind === "link" ? /* @__PURE__ */ React.createElement(LkLinkResolver, { key: active.key, item: active, onDone: resolveDone }) : /* @__PURE__ */ React.createElement(LkReasonResolver, { key: active.key, item: active, onDone: resolveDone }))))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 9, y: 0, w: 15, h: 9, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Open Positions",
      count: positions ? positions.length : null,
      onRefresh: () => load("fast"),
      bodyStyle: { padding: 0 },
      foot: lkFoot("positions", positions != null)
    },
    positions == null ? /* @__PURE__ */ React.createElement("div", { style: { padding: 10 } }, /* @__PURE__ */ React.createElement(Spinner, { label: "loading" })) : /* @__PURE__ */ React.createElement(DataList, { columns: posCols, rows: positions, selKey: "position_id", emptyMsg: "no open positions" })
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 9, y: 9, w: 8, h: 8, minW: 4, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Active Calcs",
      count: calcs ? calcs.length : null,
      bodyStyle: { padding: 0 },
      foot: lkFoot("calcs", calcs != null)
    },
    calcs == null ? /* @__PURE__ */ React.createElement("div", { style: { padding: 10 } }, /* @__PURE__ */ React.createElement(Spinner, { label: "loading" })) : /* @__PURE__ */ React.createElement(DataList, { columns: calcCols, rows: calcs, selKey: "calc_id", emptyMsg: "no active calcs" })
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 17, y: 9, w: 7, h: 8, minW: 4, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Funding",
      tag: "LIVE",
      bodyStyle: { padding: 0 },
      onRefresh: () => load("slow"),
      foot: lkFoot("funding", funding != null)
    },
    funding == null ? /* @__PURE__ */ React.createElement("div", { style: { padding: 10 } }, /* @__PURE__ */ React.createElement(Spinner, { label: "loading" })) : /* @__PURE__ */ React.createElement(
      DataList,
      {
        columns: fundCols,
        rows: funding.rows || [],
        selKey: "position_id",
        emptyMsg: "no open positions",
        summary: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", null, "net next ", funding.countdown_s != null ? lpClock(funding.countdown_s) : "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(funding.net_next) } }, lpUsd(funding.net_next, 3)))
      }
    )
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 9, y: 17, w: 15, h: 7, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Recent Closes",
      count: closes ? closes.length : null,
      bodyStyle: { padding: 0 },
      foot: lkFoot("closes", closes != null)
    },
    closes == null ? /* @__PURE__ */ React.createElement("div", { style: { padding: 10 } }, /* @__PURE__ */ React.createElement(Spinner, { label: "loading" })) : /* @__PURE__ */ React.createElement(DataList, { columns: closeCols, rows: closes, selKey: "id", emptyMsg: "no recent closes" })
  )))), cancelCalc && /* @__PURE__ */ React.createElement(
    ModelDialog,
    {
      title: `Cancel calc \xB7 ${String(cancelCalc.calc_id).slice(-8)}`,
      width: 420,
      onClose: () => {
        if (!cancelBusy) {
          setCancelCalc(null);
          setCancelReason("");
        }
      },
      footer: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "qe-btn qe-btn-sm qe-btn-ghost",
          disabled: cancelBusy,
          onClick: () => {
            setCancelCalc(null);
            setCancelReason("");
          }
        },
        "Keep calc"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "qe-btn qe-btn-sm qe-btn-danger",
          disabled: cancelBusy,
          onClick: async () => {
            setCancelBusy(true);
            try {
              const res = await _lkForm(
                `/calculator/cancel/${cancelCalc.calc_id}`,
                cancelReason.trim() ? { reason: cancelReason.trim() } : {}
              );
              flash(res.text || "cancel sent");
              setCancelCalc(null);
              setCancelReason("");
              load("fast");
            } catch (err) {
              flash("cancel failed \u2014 engine unreachable?");
            }
            setCancelBusy(false);
          }
        },
        cancelBusy ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.62rem" }) : "Cancel calc"
      ))
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7 } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-cyan)", fontWeight: 700, fontSize: "0.72rem" } }, cancelCalc.ticker), /* @__PURE__ */ React.createElement(Badge, { tone: (cancelCalc.side || "").toLowerCase() === "long" ? "ok" : "err" }, (cancelCalc.side || "").toUpperCase())), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "5px 10px", padding: "6px 8px", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(KV, { l: "Entry", v: lpPx(cancelCalc.average) }), /* @__PURE__ */ React.createElement(KV, { l: "TP", v: lpPx(cancelCalc.tp_price), color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(KV, { l: "SL", v: lpPx(cancelCalc.sl_price), color: "var(--qe-red)" })), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", lineHeight: 1.4 } }, "Cancelling releases this calc's link window. A fill after this lands UNPLANNED unless a fresh calc is run for the ticker."), /* @__PURE__ */ React.createElement("label", { style: { display: "flex", flexDirection: "column", gap: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.52rem", fontWeight: 700, letterSpacing: "0.09em", textTransform: "uppercase", color: "var(--qe-sub)" } }, "Reason (optional)"), /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "qe-input",
        value: cancelReason,
        placeholder: "why\u2026",
        onChange: (e) => setCancelReason(e.target.value),
        onKeyDown: (e) => {
          if (e.key === "Escape" && !cancelBusy) {
            setCancelCalc(null);
            setCancelReason("");
          }
        },
        style: { height: 22, boxSizing: "border-box" }
      }
    )))
  ), toast && /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", bottom: 14, left: "50%", transform: "translateX(-50%)", zIndex: 80, display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", background: "var(--qe-bg)", border: "1px solid var(--qe-green)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, "\u2713"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", color: "var(--qe-text)" } }, toast)), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
Object.assign(window, { LinkagePage });

;

/* ==== pages-history.jsx ==== */
const _hFmtTs = (ms) => {
  if (!ms) return "\u2014";
  const d = /* @__PURE__ */ new Date(+ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const _hDur = (ms) => {
  if (ms == null) return "\u2014";
  const s = Math.max(0, Math.floor(ms / 1e3));
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return (d ? d + "d " : "") + (d || h ? h + "h " : "") + m + "m";
};
const _hIso = (dt, end) => {
  const p = (n) => String(n).padStart(2, "0");
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}T${end ? "23:59:59" : "00:00:00"}`;
};
const _hRange = (preset) => {
  if (preset === "all") return { date_from: "", date_to: "" };
  const now = /* @__PURE__ */ new Date();
  const from = new Date(now);
  if (preset === "ytd") {
    from.setMonth(0, 1);
  } else from.setDate(now.getDate() - ({ "7d": 7, "15d": 15, "30d": 30, "90d": 90 }[preset] || 30));
  return { date_from: _hIso(from, false), date_to: _hIso(now, true) };
};
const _hEvtSummary = (r) => {
  const p = r._payload || {};
  const f = (v, d = 4) => v == null || isNaN(v) ? "\u2014" : (+v).toFixed(d);
  if (r.event_type === "position_amended" && p.old != null) return `${p.field || ""}: ${f(p.old)} \u2192 ${f(p.new)}`;
  if ((r.event_type === "tp_modified" || r.event_type === "sl_modified") && p.from_price != null) return `${f(p.from_price)} \u2192 ${f(p.to_price)}`;
  if (r.event_type === "order_filled" && p.price != null) return `Price: ${f(p.price)} \xB7 Qty: ${f(p.quantity != null ? p.quantity : p.fill_qty)}`;
  if (r.event_type === "position_closed" && p.pnl != null) return `PnL: ${f(p.pnl, 2)}`;
  if (r.event_type === "order_placed" && p.side) return `${p.side} ${p.order_type || ""}`;
  const raw = r.payload_json || "";
  return raw.length > 60 ? raw.slice(0, 60) + "\u2026" : raw;
};
const H_TABS = [
  ["positions", "Closed Positions", "/fragments/history/closed_positions"],
  ["orders", "Orders", "/fragments/history/order_history"],
  ["fills", "Fills", "/fragments/history/fills"],
  ["events", "Trade Events", "/fragments/history/trade_events"],
  ["pretrade", "Pre-Trade Log", "/fragments/history/pre_trade"]
];
const HReasonModal = ({ row, onClose, onSaved }) => {
  const [pick, setPick] = React.useState(null);
  const [note, setNote] = React.useState(row.close_note || "");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await _lkForm(`/history/close_reason/${row.id}`, { exit_reason: pick, close_note: note }, "PUT");
      if (r.ok) {
        onSaved();
        onClose();
      } else setErr(r.text || "save failed");
    } catch (e) {
      setErr("save failed \u2014 engine unreachable?");
    }
    setBusy(false);
  };
  return /* @__PURE__ */ React.createElement("div", { style: { position: "fixed", inset: 0, zIndex: 90, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center" }, onClick: onClose }, /* @__PURE__ */ React.createElement("div", { style: { background: "var(--qe-card)", border: "1px solid var(--qe-line)", padding: 14, width: 380 }, onClick: (e) => e.stopPropagation() }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true, right: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: onClose }, "\u2715") }, row.symbol, " \xB7 close reason"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5, margin: "8px 0" } }, LP_MANUAL_REASONS.map((r) => /* @__PURE__ */ React.createElement("button", { key: r.key, onClick: () => setPick(r.key), style: {
    textAlign: "left",
    padding: "6px 8px",
    cursor: "pointer",
    background: pick === r.key ? "var(--qe-active)" : "var(--qe-panel)",
    border: `1px solid ${pick === r.key ? "var(--qe-cyan)" : "var(--qe-line)"}`
  } }, /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.6rem", fontWeight: 700, color: pick === r.key ? "var(--qe-cyan)" : "var(--qe-text)" } }, r.label), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", marginTop: 2 } }, r.hint)))), /* @__PURE__ */ React.createElement("input", { className: "qe-input", placeholder: "optional note\u2026", value: note, onChange: (e) => setNote(e.target.value) }), err ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.58rem", color: "var(--qe-red)", marginTop: 6 } }, err) : null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end", marginTop: 8 } }, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", disabled: !pick || busy, onClick: save }, busy ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.62rem" }) : "Save"))));
};
const HistoryPage = () => {
  const [tab, setTab] = React.useState("positions");
  const [period, setPeriod] = React.useState("30d");
  const [q, setQ] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [perPage, setPerPage] = React.useState(50);
  const [counts, setCounts] = React.useState({});
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [sel, setSel] = React.useState(null);
  const [drill, setDrill] = React.useState(null);
  const [modal, setModal] = React.useState(null);
  const seqRef = React.useRef(0);
  const [net, setNet] = React.useState({});
  const [netDrill, setNetDrill] = React.useState({});
  const load = React.useCallback(async () => {
    const ep = H_TABS.find(([k]) => k === tab)[2];
    const { date_from, date_to } = _hRange(period);
    const params = new URLSearchParams({
      format: "json",
      page: String(page),
      per_page: String(perPage),
      search: q.trim(),
      date_from,
      date_to
    });
    const seq = ++seqRef.current;
    setLoading(true);
    const t0 = performance.now();
    try {
      const d = await _ptJson(ep + "?" + params.toString());
      if (seq === seqRef.current) {
        setData(d);
        setNet({ err: null, ms: performance.now() - t0 });
      }
    } catch (err) {
      if (seq === seqRef.current) {
        setData((prev) => prev || { rows: [], total: 0 });
        setNet((n) => ({ ...n, err }));
      }
    }
    if (seq === seqRef.current) setLoading(false);
  }, [tab, period, q, page, perPage]);
  React.useEffect(() => {
    load();
  }, [load]);
  React.useEffect(() => {
    const t = setInterval(load, 3e4);
    return () => clearInterval(t);
  }, [load]);
  React.useEffect(() => {
    setPage(1);
    setSel(null);
    setDrill(null);
  }, [tab, period, q]);
  const loadCounts = React.useCallback(async () => {
    const { date_from, date_to } = _hRange(period);
    const out = {};
    await Promise.all(H_TABS.map(async ([k, , ep]) => {
      try {
        const d = await _ptJson(ep + "?" + new URLSearchParams({
          format: "json",
          page: "1",
          per_page: "1",
          date_from,
          date_to
        }).toString());
        out[k] = d && d.total != null ? d.total : null;
      } catch (e) {
        out[k] = null;
      }
    }));
    setCounts(out);
  }, [period]);
  React.useEffect(() => {
    loadCounts();
  }, [loadCounts]);
  const drillSeq = React.useRef(0);
  const openDrill = async (row) => {
    if (sel && sel.id === row.id) {
      setSel(null);
      setDrill(null);
      return;
    }
    const seq = ++drillSeq.current;
    setSel(row);
    setDrill(null);
    setNetDrill({});
    const t0 = performance.now();
    let legErr = null;
    const [fills, ctx] = await Promise.all([
      _ptJson(`/fragments/history/position_fills?position_id=${row.id}&format=json`).catch((e) => {
        legErr = legErr || e;
        return { fills: [] };
      }),
      _ptJson(`/context/position/${encodeURIComponent(row.terminal_position_id || row.id)}`).catch((e) => {
        legErr = legErr || e;
        return null;
      })
    ]);
    if (seq === drillSeq.current) {
      setDrill({ fills: fills && fills.fills || [], ctx });
      setNetDrill(legErr ? { err: legErr } : { err: null, ms: performance.now() - t0 });
    }
  };
  const rows = data && data.rows || [];
  const total = data && data.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const exportCsv = () => {
    if (!rows.length) return;
    const cols = Object.keys(rows[0]).filter((k) => !k.startsWith("_"));
    const esc = (v) => {
      const s = String(v == null ? "" : v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `qe-history-${tab}-${period}-p${page}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const exitCell = (r) => {
    const er = r.exit_reason || "";
    if (er.startsWith("MANUAL") || er === "manual" || er === "limit_close") {
      return /* @__PURE__ */ React.createElement("span", { style: { cursor: "pointer" }, onClick: (e) => {
        e.stopPropagation();
        setModal(r);
      }, title: "Set / edit the close reason" }, /* @__PURE__ */ React.createElement(ExitBadge, { reason: er.startsWith("MANUAL") ? er : "MANUAL_OTHER", note: r.close_note }));
    }
    return /* @__PURE__ */ React.createElement(ExitBadge, { reason: er || null, note: r.close_note, pending: !er });
  };
  const COLS = {
    positions: [
      { key: "exit_time_ms", label: "CLOSED", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, _hFmtTs(r.exit_time_ms)) },
      { key: "symbol", label: "SYM", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.symbol) },
      { key: "direction", label: "SIDE", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.direction === "LONG" ? "ok" : "err" }, r.direction) },
      { key: "model_name", label: "MODEL", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, r.model_name || "\u2014") },
      {
        key: "plan",
        label: "PLAN",
        // ascending = worst-first (off-plan at the top) — this is a triage column.
        sortVal: (r) => r.calc_id ? { red: 0, yellow: 1, green: 2 }[r.deviation_badge] != null ? { red: 0, yellow: 1, green: 2 }[r.deviation_badge] : 3 : 4,
        filter: { label: "PLAN" },
        filterVal: (r) => r.calc_id ? ((LP_DEV_META || {})[r.deviation_badge] || {}).label || "\u2014" : "UNPLANNED",
        render: (r) => r.calc_id ? /* @__PURE__ */ React.createElement(DevBadge, { pos: { ...r, amendment_count: r.cumulative_amendment_count } }) : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014")
      },
      { key: "quantity", label: "QTY", align: "right", render: (r) => _ptFmtSz(r.quantity) },
      { key: "entry_price", label: "ENTRY", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, lpPx(r.entry_price)) },
      { key: "exit_price", label: "EXIT", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, lpPx(r.exit_price)) },
      { key: "net_pnl", label: "NET", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(r.net_pnl), fontWeight: 700 } }, lpUsd(r.net_pnl)) },
      {
        key: "pct",
        label: "%",
        align: "right",
        sortVal: (r) => {
          const den = (r.entry_price || 0) * (r.quantity || 0);
          return den ? r.net_pnl / den * 100 : null;
        },
        render: (r) => {
          const den = (r.entry_price || 0) * (r.quantity || 0);
          const pct = den ? r.net_pnl / den * 100 : null;
          return pct == null ? "\u2014" : /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(pct) } }, lpPct(pct));
        }
      },
      {
        key: "mr",
        label: "M\xB7R",
        align: "right",
        // mirrors the render exactly: unknown -> null (sorts last), measured
        // zero-MAE with positive MFE -> Infinity (the rendered '∞').
        sortVal: (r) => {
          if (r.mae == null || r.mfe == null) return null;
          const mae = Math.abs(+r.mae);
          if (!mae) return +r.mfe > 0 ? Infinity : null;
          return (+r.mfe || 0) / mae;
        },
        render: (r) => {
          if (r.mae == null || r.mfe == null) return /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014");
          const mae = Math.abs(+r.mae);
          if (!mae) return +r.mfe > 0 ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, "\u221E") : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014");
          const mr = (+r.mfe || 0) / mae;
          return /* @__PURE__ */ React.createElement("span", { style: { color: mr >= 2 ? "var(--qe-green)" : mr >= 1 ? "var(--qe-text)" : "var(--qe-red)" } }, mr.toFixed(2));
        }
      },
      // label restored to the design's 'MAE ◂ HEAT ▸ MFE'. `pnl` feeds the exit
      // tick — the third channel — so the cell shows where the close landed
      // within the swing. The design has this column sort:false; we keep the
      // sort (operator DataList directive) on the adverse extent, the bar's
      // dominant visual weight.
      {
        key: "heat",
        label: "MAE \u25C2 HEAT \u25B8 MFE",
        align: "right",
        sortVal: (r) => r.mae == null ? null : Math.abs(+r.mae),
        render: (r) => /* @__PURE__ */ React.createElement(HeatBar, { mfe: r.mfe, mae: r.mae, pnl: r.net_pnl })
      },
      { key: "total_fees", label: "FEE", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, _ptFmtN(r.total_fees, 4)) },
      { key: "hold_time_ms", label: "DUR", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, _hDur(r.hold_time_ms)) },
      { key: "exit_reason", label: "REASON", render: exitCell }
    ],
    orders: [
      { key: "updated_at_ms", label: "TIME", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, _hFmtTs(r.updated_at_ms)) },
      { key: "exchange_order_id", label: "ORDER ID", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, String(r.exchange_order_id || "").slice(0, 12)) },
      { key: "symbol", label: "SYM", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.symbol) },
      { key: "side", label: "SIDE", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: (r.side || "").toUpperCase() === "BUY" ? "ok" : "err" }, (r.side || "").toUpperCase()) },
      { key: "order_type", label: "TYPE", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: "mute" }, (r.order_type || "").toUpperCase()) },
      { key: "quantity", label: "QTY", align: "right" },
      /* history-1 (2026-07-25 Meridian audit): a stop/TP order carries its level
         in stop_price, NOT price — price is 0 on every one of them (109 of 258
         live rows). lpPx(0) formats as '0.000000', which read as a real level, so
         PRICE now blanks on 0 and the TRIGGER column carries the actual level.
         DEVIATION from the design, which had two columns (TP + SL) sourced from
         tp_trigger_price / sl_trigger_price. Those are the PLAN levels attached
         to an ENTRY order — a different fact from "the level this order triggers
         at" — and they are populated on only 17 of 258 rows, so two columns
         would be ~93% empty while still never showing the stop level. One
         TRIGGER column on stop_price matches the shipped Jinja twin of this same
         table (fragments/history/order_history_table.html sorts a "Trigger"
         column on stop_price) and covers the rows that actually needed it.
         A tp/sl fallback was tried and REVERTED in review: it printed an entry
         order's take-profit plan as though it were that order's trigger, dropped
         the SL half silently, and made the column sort disagree with itself
         (DataList sorts row[col.key], i.e. raw stop_price = 0 for those rows). */
      {
        key: "price",
        label: "PRICE",
        align: "right",
        render: (r) => r.price == null || +r.price === 0 ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : lpPx(r.price)
      },
      {
        key: "stop_price",
        label: "TRIGGER",
        align: "right",
        render: (r) => r.stop_price == null || +r.stop_price === 0 ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-amber)" } }, lpPx(r.stop_price))
      },
      {
        key: "avg_fill_price",
        label: "AVG FILL",
        align: "right",
        render: (r) => r.avg_fill_price == null || +r.avg_fill_price === 0 ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : lpPx(r.avg_fill_price)
      },
      { key: "status", label: "STATUS", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.status === "filled" ? "ok" : r.status === "new" ? "info" : "mute" }, (r.status || "").toUpperCase()) },
      { key: "link_status", label: "LINK", render: (r) => /* @__PURE__ */ React.createElement(LinkBadge, { status: r.link_status, variant: 3 }) }
    ],
    fills: [
      { key: "timestamp_ms", label: "TIME", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, _hFmtTs(r.timestamp_ms)) },
      { key: "symbol", label: "SYM", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.symbol) },
      { key: "is_close", label: "ACTION", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.is_close ? "mute" : "info" }, r.is_close ? "CLOSE" : "OPEN") },
      { key: "direction", label: "SIDE", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.direction === "LONG" ? "ok" : "err" }, r.direction) },
      { key: "price", label: "PRICE", align: "right", render: (r) => lpPx(r.price) },
      { key: "quantity", label: "QTY", align: "right" },
      { key: "fee", label: "FEE", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, _ptFmtN(r.fee, 4), " ", r.fee_asset || "") },
      { key: "role", label: "ROLE", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: "mute" }, (r.role || "").toUpperCase()) },
      { key: "realized_pnl", label: "PnL", align: "right", render: (r) => r.realized_pnl == null || r.realized_pnl === 0 ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : /* @__PURE__ */ React.createElement("span", { style: { color: lpSgn(r.realized_pnl) } }, lpUsd(r.realized_pnl)) }
    ],
    events: [
      /* trade_events rows carry an ISO-string timestamp, not epoch-ms [P4 audit #1] */
      { key: "timestamp", label: "TIME", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, String(r.timestamp || "").slice(0, 16).replace("T", " ") || "\u2014") },
      { key: "_symbol", label: "SYM", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r._symbol || "\u2014") },
      { key: "event_type", label: "TYPE", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: "info" }, r.event_type) },
      { key: "calc_id", label: "CALC", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, r.calc_id ? String(r.calc_id).slice(-8) : "\u2014") },
      { key: "source", label: "SRC", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, r.source || "") },
      /* the event's SUBSTANCE — restored L3-F3 (the door parses _payload
         per row; the tab consumed only _symbol) */
      {
        key: "summary",
        label: "SUMMARY",
        sortVal: (r) => _hEvtSummary(r) || "",
        searchVal: (r) => _hEvtSummary(r) || "",
        render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontSize: "0.6rem", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block", verticalAlign: "bottom" } }, _hEvtSummary(r) || "\u2014")
      }
    ],
    pretrade: [
      { key: "timestamp", label: "TIME", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, String(r.timestamp || "").slice(0, 16).replace("T", " ")) },
      { key: "calc_id", label: "CALC ID", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontFamily: "var(--qe-mono)" } }, String(r.calc_id || "").slice(-8)) },
      { key: "ticker", label: "SYM", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.ticker) },
      { key: "side", label: "SIDE", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: (r.side || "").toLowerCase() === "long" ? "ok" : "err" }, (r.side || "").toUpperCase()) },
      { key: "average", label: "ENTRY", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, lpPx(r.average)) },
      { key: "tp_price", label: "TP", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { className: "qe-up" }, lpPx(r.tp_price)) },
      { key: "sl_price", label: "SL", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { className: "qe-dn" }, lpPx(r.sl_price)) },
      { key: "size", label: "SIZE", align: "right", render: (r) => _ptFmtSz(r.size) },
      { key: "model_display", label: "MODEL", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, r.model_display || "\u2014") },
      { key: "status", label: "LINK", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: ["matched", "linked"].includes(r.status) ? "ok" : r.status === "active" ? "info" : "mute" }, (r.status || "").toUpperCase()) }
    ]
  };
  const summary = (() => {
    if (tab !== "positions" || !rows.length) return null;
    const net2 = rows.reduce((s, r) => s + (r.net_pnl || 0), 0);
    const wins = rows.filter((r) => (r.net_pnl || 0) >= 0).length;
    const fees = rows.reduce((s, r) => s + (r.total_fees || 0), 0);
    return [
      { label: "ROWS", value: String(rows.length) },
      { label: "WINS", value: String(wins), color: "var(--qe-green)" },
      { label: "LOSSES", value: String(rows.length - wins), color: "var(--qe-red)" },
      { label: "WINRATE", value: rows.length ? Math.round(wins / rows.length * 100) + "%" : "\u2014" },
      { label: "FEES", value: _ptFmtN(fees), color: "var(--qe-sub)" },
      { label: "NET", value: lpUsd(net2), color: lpSgn(net2) }
    ];
  })();
  const dp = sel;
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "04 History", style: { width: "100%", height: "100%", background: "var(--qe-bg)", display: "flex", flexDirection: "column", overflow: "hidden" } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "History", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "History", subtitle: "closed positions \xB7 orders \xB7 fills \xB7 events \xB7 pre-trade log" }, /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["7d", "7D"], ["15d", "15D"], ["30d", "30D"], ["90d", "90D"], ["ytd", "YTD"], ["all", "ALL"]], value: period, onChange: setPeriod }), /* @__PURE__ */ React.createElement(
    "input",
    {
      className: "qe-input",
      placeholder: "filter symbol\u2026",
      value: q,
      onChange: (e) => setQ(e.target.value),
      onKeyDown: (e) => {
        if (e.key === "Escape") setQ("");
      },
      style: { width: 180, height: 22, boxSizing: "border-box" }
    }
  ), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: exportCsv, title: "Download the loaded rows as CSV" }, "Export CSV")), summary ? /* @__PURE__ */ React.createElement(Strip, { dense: true, style: { margin: 6, marginBottom: 0 }, items: summary }) : null, /* @__PURE__ */ React.createElement(TabStrip, { value: tab, onChange: setTab, tabs: H_TABS.map(([k, l]) => [
    k,
    l,
    k === tab ? data ? total : counts[k] != null ? counts[k] : null : counts[k] != null ? counts[k] : null
  ]) }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 16, h: 24, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: H_TABS.find(([k]) => k === tab)[1],
      count: total || null,
      onRefresh: load,
      style: { height: "100%" },
      bodyStyle: { padding: 0, display: "flex", flexDirection: "column" },
      foot: qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: rows.length > 0, ms: net.ms, retrying: true })
    },
    /* @__PURE__ */ React.createElement("div", { style: { flex: 1, overflow: "auto" } }, loading && !data ? /* @__PURE__ */ React.createElement("div", { style: { padding: 10 } }, /* @__PURE__ */ React.createElement(Spinner, { label: "loading" })) : (
      // design #1: this table is SERVER-PAGED (rows = one page). All
      // THREE tools are on (operator directive 2026-07-25) and all
      // three act on the LOADED page — an in-view refinement.
      // SEARCH was previously suppressed here to avoid implying it
      // spanned the dataset; it is now enabled and COMPLEMENTS the
      // symbol input above the tabs rather than duplicating it: that
      // one is server-side and narrows the result set across every
      // page, this one refines the page in view. Keep both — dropping
      // the server box would silently miss rows on other pages.
      // Global server-wired facets/sort remains a named follow-up.
      /* @__PURE__ */ React.createElement(
        DataList,
        {
          dense: true,
          tools: { search: true, sort: true, filter: true },
          columns: COLS[tab],
          rows,
          selKey: "id",
          selected: tab === "positions" && sel ? sel.id : null,
          onClick: tab === "positions" ? (r) => openDrill(r) : void 0,
          emptyMsg: "no rows in this window"
        }
      )
    )),
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, padding: "4px 8px", borderTop: "1px solid var(--qe-line)", fontFamily: "var(--qe-mono)", fontSize: "0.58rem" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, total, " rows \xB7 page ", page, "/", totalPages), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement(
      "select",
      {
        className: "qe-input qe-select",
        style: { width: "auto", height: 20, fontSize: "0.56rem" },
        value: String(perPage),
        onChange: (e) => {
          setPerPage(+e.target.value);
          setPage(1);
        }
      },
      /* @__PURE__ */ React.createElement("option", { value: "25" }, "25"),
      /* @__PURE__ */ React.createElement("option", { value: "50" }, "50"),
      /* @__PURE__ */ React.createElement("option", { value: "75" }, "75"),
      /* @__PURE__ */ React.createElement("option", { value: "100" }, "100")
    ), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", disabled: page <= 1, onClick: () => setPage((p) => p - 1) }, "\u2039"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", disabled: page >= totalPages, onClick: () => setPage((p) => p + 1) }, "\u203A"))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 16, y: 0, w: 8, h: 24, minW: 6, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Position Detail",
      style: { height: "100%" },
      bodyStyle: { overflow: "auto" },
      foot: !sel ? { tone: "sub", msg: "select a position" } : qeFootState({ loading: drill == null && !netDrill.err, err: netDrill.err, hasData: drill != null, ms: netDrill.ms })
    },
    !dp ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25CE", msg: "Select a closed position", hint: "Click a row to inspect its fills, exec link and amendments." }) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true, right: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: () => {
      setSel(null);
      setDrill(null);
    } }, "\u2715") }, dp.symbol, " \xB7 CLOSED \xB7 ", dp.direction), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 10px" } }, /* @__PURE__ */ React.createElement(KV, { l: "Net", v: lpUsd(dp.net_pnl), color: lpSgn(dp.net_pnl) }), /* @__PURE__ */ React.createElement(KV, { l: "Duration", v: _hDur(dp.hold_time_ms) }), /* @__PURE__ */ React.createElement(KV, { l: "Entry", v: lpPx(dp.entry_price) }), /* @__PURE__ */ React.createElement(KV, { l: "Exit", v: lpPx(dp.exit_price) }), /* @__PURE__ */ React.createElement(KV, { l: "TP plan", v: lpPx(dp.tp_price), color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(KV, { l: "SL plan", v: lpPx(dp.sl_price), color: "var(--qe-red)" }), /* @__PURE__ */ React.createElement(KV, { l: "MFE / MAE", v: `${_ptFmtN(dp.mfe)} / ${_ptFmtN(dp.mae)}` }), /* @__PURE__ */ React.createElement(KV, { l: "Funding", v: lpUsd(dp.funding_fees, 3), color: lpSgn(dp.funding_fees) }), /* @__PURE__ */ React.createElement(KV, { l: "Model", v: dp.model_name || "\u2014" }), /* @__PURE__ */ React.createElement(KV, { l: "Calc", v: dp.calc_id ? String(dp.calc_id).slice(-8) : "\u2014", color: "var(--qe-cyan)" })), /* @__PURE__ */ React.createElement("div", { style: { borderTop: "1px solid var(--qe-line)" } }), /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Fills"), drill == null ? /* @__PURE__ */ React.createElement(Spinner, { label: "loading" }) : !drill.fills.length ? /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.58rem", color: "var(--qe-muted)" } }, "No fills recorded for this position.") : (
      // drilldown fills. tools were off here ("a handful of rows
      // inside a modal"); lifted 2026-07-25 per the operator
      // directive — a scaled-in position has many legs, and that
      // is exactly where finding one fill pays off.
      /* @__PURE__ */ React.createElement(DataList, { dense: true, selKey: "id", columns: [
        { key: "timestamp_ms", label: "TIME", render: (f) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, _hFmtTs(f.timestamp_ms)) },
        { key: "is_close", label: "ACT", render: (f) => /* @__PURE__ */ React.createElement(Badge, { tone: f.is_close ? "mute" : "info" }, f.is_close ? "C" : "O") },
        { key: "price", label: "PRICE", align: "right", render: (f) => lpPx(f.price) },
        { key: "quantity", label: "QTY", align: "right" },
        {
          key: "exec",
          label: "EXEC LINK",
          sortVal: (f) => String(f.exec_link_status || ""),
          filter: { label: "EXEC" },
          filterVal: (f) => String(f.exec_link_status || "\u2014").toUpperCase(),
          render: (f) => f.is_close || !f.calc_id ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : f.exec_link_status === "linked" ? /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "\u25CF LINKED") : f.exec_link_status === "partial" ? /* @__PURE__ */ React.createElement(Badge, { tone: "warn" }, "\u26A0 ", f.exec_match_count, "/1") : /* @__PURE__ */ React.createElement(Badge, { tone: "err" }, "\u2717 UNLINKED")
        }
      ], rows: drill.fills })
    ), drill && drill.ctx && Array.isArray(drill.ctx.amendments) && drill.ctx.amendments.length ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Amendments \xB7 ", drill.ctx.amendments.length), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 2 } }, drill.ctx.amendments.slice(0, 12).map((a, i) => /* @__PURE__ */ React.createElement("div", { key: i, className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-sub)" } }, _hFmtTs(a.ts_ms), " \xB7 ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-amber)" } }, a.field), " ", a.old_value, " \u2192 ", a.new_value, a.deviation_pct != null ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, " (", lpPct(a.deviation_pct), ")") : null)))) : null)
  )))), modal ? /* @__PURE__ */ React.createElement(HReasonModal, { row: modal, onClose: () => setModal(null), onSaved: load }) : null, /* @__PURE__ */ React.createElement(StatusFooter, null));
};
Object.assign(window, { HistoryPage });

;

/* ==== pages-analytics.jsx ==== */
const ANA_TABS = [
  ["overview", "Overview"],
  ["equity", "Equity Curve"],
  ["dist", "Distributions"],
  ["calendar", "Calendar PnL"],
  ["pairs", "Traded Pairs"],
  ["excursions", "MFE / MAE"],
  ["rmultiples", "R-Multiples"],
  ["risk", "Risk Metrics"],
  ["execution", "Execution Quality"],
  ["funding", "Funding"],
  ["beta", "Beta Exposure"]
];
const ANA_PERIOD_TABS = /* @__PURE__ */ new Set(["overview", "dist", "pairs", "excursions", "rmultiples", "risk"]);
const ANA_NO_NAV = /* @__PURE__ */ new Set(["rolling_30d", "rolling_90d", "all_time"]);
const _anaPnl = (v) => v > 0 ? "var(--qe-green)" : v < 0 ? "var(--qe-red)" : "var(--qe-sub)";
const _anaQS = (period, offset) => `period=${encodeURIComponent(period)}&offset=${offset}`;
const _anaRatio = (v) => v == null ? "\u2014" : v >= 999 ? "\u221E" : (+v).toFixed(2);
const _anaMs = (ms) => {
  if (ms == null) return "\u2014";
  if (ms < 1e3) return `${Math.round(ms)}ms`;
  if (ms < 6e4) return `${(ms / 1e3).toFixed(1)}s`;
  if (ms < 36e5) return `${(ms / 6e4).toFixed(1)}m`;
  return `${(ms / 36e5).toFixed(1)}h`;
};
const useAnaJson = (url, intervalMs = 0) => {
  const [data, setData] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [ms, setMs] = React.useState(null);
  const seqRef = React.useRef(0);
  const load = React.useCallback(async () => {
    if (!url) return;
    const seq = ++seqRef.current;
    const t0 = performance.now();
    try {
      const d = await _ptJson(url);
      if (seq === seqRef.current) {
        setData(d);
        setErr(null);
        setMs(performance.now() - t0);
      }
    } catch (e) {
      if (seq === seqRef.current) {
        setErr(e);
      }
    }
    if (seq === seqRef.current) setLoading(false);
  }, [url]);
  React.useEffect(() => {
    if (!url) {
      seqRef.current++;
      setData(null);
      setErr(null);
      setMs(null);
      setLoading(true);
      return;
    }
    setLoading(true);
    load();
  }, [load, url]);
  React.useEffect(() => {
    if (!intervalMs || !url) return void 0;
    const t = setInterval(load, intervalMs);
    return () => clearInterval(t);
  }, [load, intervalMs, url]);
  const foot = qeFootState({ loading, err, hasData: data != null, ms, retrying: intervalMs > 0 });
  return { data, err, loading, reload: load, ms, foot };
};
const useAnaLabel = (data, onLabel) => {
  React.useEffect(() => {
    if (data && data.period_label && onLabel) onLabel(data.period_label);
  }, [data, onLabel]);
};
const AnaEmpty = ({ err, msg }) => /* @__PURE__ */ React.createElement("div", { style: { padding: 4, height: "100%" } }, /* @__PURE__ */ React.createElement(
  EmptyState,
  {
    tone: err ? "warn" : "neutral",
    glyph: err ? "\u26A0" : "\u25C7",
    msg: err ? "analytics fetch failed" : msg,
    hint: err ? qeFootCause(err) : void 0
  }
));
const AnaKv = ({ label, value, color }) => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 2, minWidth: 0 } }, /* @__PURE__ */ React.createElement(Lbl, null, label), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.82rem", fontWeight: 700, color: color || "var(--qe-text)" } }, value));
const AnaVRow = ({ label, value, color }) => /* @__PURE__ */ React.createElement("div", { className: "qe-fl-row" }, /* @__PURE__ */ React.createElement("div", { className: "qe-fl-l" }, /* @__PURE__ */ React.createElement("span", { style: { overflow: "hidden", textOverflow: "ellipsis" } }, label)), /* @__PURE__ */ React.createElement("div", { className: "qe-fl-v", style: color ? { color } : void 0 }, value));
const AnaPeriodNav = ({ period, offset = 0, onPeriod, onNav, disabled, label }) => {
  const presets = [
    ["monthly", "Month"],
    ["weekly", "Week"],
    ["quarterly", "Quarter"],
    ["yearly", "Year"],
    ["rolling_30d", "30D"],
    ["rolling_90d", "90D"],
    ["all_time", "All"]
  ];
  const noNav = ANA_NO_NAV.has(period);
  const noFwd = noNav || offset >= 0;
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      title: disabled ? "Period filter doesn't apply to this sub-tab \u2014 it has its own controls." : "",
      style: { display: "flex", alignItems: "center", gap: 6, opacity: disabled ? 0.4 : 1, pointerEvents: disabled ? "none" : "auto" }
    },
    /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", disabled: noNav, style: noNav ? { opacity: 0.45 } : void 0, onClick: () => onNav(-1) }, "\u2039"),
    /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.74rem", fontWeight: 700, minWidth: 120, textAlign: "center", color: "var(--qe-text)" } }, label || "\u2026"),
    /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "qe-btn qe-btn-sm qe-btn-ghost",
        disabled: noFwd,
        style: noFwd ? { opacity: 0.45 } : void 0,
        title: offset >= 0 && !noNav ? "already at the current period" : void 0,
        onClick: () => onNav(1)
      },
      "\u203A"
    ),
    /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", margin: "0 2px" } }, "\u2502"),
    /* @__PURE__ */ React.createElement(PeriodSelector, { options: presets, value: period, onChange: onPeriod })
  );
};
const AnaHistChart = ({ bins, color = "var(--qe-cyan)", height = "100%", unit = "", divergent = false, noun = "trade", tip = null }) => {
  const ref = React.useRef(null);
  const c = _qeResolveColor(color);
  const green = QE_ECHARTS_THEME.green, red = QE_ECHARTS_THEME.red;
  const opts = React.useMemo(() => ({
    ..._baseChart({ grid: { left: 30, right: 10, top: 18, bottom: 20 } }),
    tooltip: {
      trigger: "axis",
      backgroundColor: QE_ECHARTS_THEME.bg,
      borderColor: QE_ECHARTS_THEME.cyan,
      borderWidth: 1,
      padding: [4, 8],
      textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: "JetBrains Mono, monospace" },
      axisPointer: { type: "shadow", shadowStyle: { color: (divergent ? green : c) + "22" } },
      formatter: (p) => {
        var _a;
        const v = (_a = p[0].data.value) != null ? _a : p[0].data;
        if (tip) return tip(p[0].axisValue, v);
        return `${p[0].axisValue || "\u2014"}${unit} \xB7 ${v} ${noun}${v === 1 ? "" : "s"}`;
      }
    },
    xAxis: {
      type: "category",
      data: bins.map((b) => b.label),
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 9, fontFamily: "JetBrains Mono, monospace" }, splitLine: { show: false } })
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      ..._axis({
        axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 9, fontFamily: "JetBrains Mono, monospace" },
        splitLine: { lineStyle: { color: QE_ECHARTS_THEME.faint, opacity: 0.4, type: [2, 3] } }
      })
    },
    series: [{
      type: "bar",
      barWidth: "62%",
      data: bins.map((b) => ({ value: b.count, itemStyle: { color: divergent ? b.pos ? green : red : c, opacity: 0.82 } })),
      emphasis: { itemStyle: { opacity: 1 } },
      label: {
        show: true,
        position: "top",
        fontSize: 9,
        fontFamily: "JetBrains Mono, monospace",
        color: divergent ? QE_ECHARTS_THEME.sub : c,
        formatter: (x) => x.value > 0 ? x.value : ""
      }
    }]
  }), [bins, c, unit, divergent, noun]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, className: "qe-chart", style: { height } });
};
const AnaDivergingBars = ({ rows, height = "100%", fmt = (v) => v.toFixed(2) }) => {
  const ref = React.useRef(null);
  const green = QE_ECHARTS_THEME.green, red = QE_ECHARTS_THEME.red;
  const opts = React.useMemo(() => ({
    ..._baseChart({ grid: { left: 34, right: 10, top: 16, bottom: 30 } }),
    tooltip: {
      trigger: "axis",
      backgroundColor: QE_ECHARTS_THEME.bg,
      borderColor: QE_ECHARTS_THEME.cyan,
      borderWidth: 1,
      padding: [4, 8],
      textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: "JetBrains Mono, monospace" },
      axisPointer: { type: "shadow", shadowStyle: { color: QE_ECHARTS_THEME.text + "10" } },
      formatter: (p) => {
        const r = rows[p[0].dataIndex];
        return `${r.label} \xB7 ${(r.v >= 0 ? "+" : "") + fmt(r.v)} \xB7 ${r.n} trade${r.n === 1 ? "" : "s"}`;
      }
    },
    xAxis: {
      type: "category",
      data: rows.map((r) => r.label),
      ..._axis({ axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 9, fontFamily: "JetBrains Mono, monospace" }, splitLine: { show: false } })
    },
    yAxis: {
      type: "value",
      ..._axis({
        axisLabel: { color: QE_ECHARTS_THEME.muted, fontSize: 9, fontFamily: "JetBrains Mono, monospace", formatter: (v) => v.toFixed(1) },
        splitLine: { lineStyle: { color: QE_ECHARTS_THEME.faint, opacity: 0.4, type: [2, 3] } }
      })
    },
    series: [{
      type: "bar",
      barWidth: "56%",
      data: rows.map((r) => ({ value: r.n > 0 ? r.v : 0, itemStyle: { color: r.v >= 0 ? green : red, opacity: 0.82 } })),
      markLine: { symbol: "none", silent: true, data: [{ yAxis: 0, lineStyle: { color: QE_ECHARTS_THEME.line, width: 1 }, label: { show: false } }] },
      emphasis: { itemStyle: { opacity: 1 } },
      label: {
        show: true,
        fontSize: 9,
        fontFamily: "JetBrains Mono, monospace",
        color: QE_ECHARTS_THEME.sub,
        position: "top",
        formatter: (x) => {
          const r = rows[x.dataIndex];
          return r.n > 0 && Math.abs(r.v) > 5e-3 ? (r.v >= 0 ? "+" : "") + fmt(r.v) : "";
        }
      }
    }]
  }), [rows, fmt]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, className: "qe-chart", style: { height } });
};
const ANA_FT_COLOR = {
  entry: "var(--qe-blue)",
  tp: "var(--qe-green)",
  sl: "var(--qe-red)",
  manual: "var(--qe-muted)",
  reduce_only: "var(--qe-sub)"
};
const AnaExecScatter = ({ points, height = "100%" }) => {
  const ref = React.useRef(null);
  const opts = React.useMemo(() => {
    const maxX = Math.max(...points.map((p) => p.est), 1) * 1.18;
    const maxY = Math.max(...points.map((p) => p.act), 1) * 1.18;
    const minY = Math.min(0, ...points.map((p) => p.act)) * 1.18;
    const data = points.map((p) => ({
      value: [p.est, p.act],
      name: p.id,
      itemStyle: {
        color: _qeResolveColor(ANA_FT_COLOR[p.ft] || "var(--qe-sub)"),
        opacity: 0.82,
        borderColor: p.act > 0 ? QE_ECHARTS_THEME.red : "transparent",
        borderWidth: p.act > 0 ? 1.6 : 0
      },
      _ft: p.ft
    }));
    return {
      ..._baseChart({ grid: { left: 46, right: 16, top: 14, bottom: 40 } }),
      tooltip: {
        trigger: "item",
        backgroundColor: QE_ECHARTS_THEME.bg,
        borderColor: QE_ECHARTS_THEME.cyan,
        borderWidth: 1,
        padding: [4, 8],
        textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: "JetBrains Mono, monospace" },
        formatter: (o) => {
          const d = o.data;
          return `<b>${d.name}</b> \xB7 ${d._ft}<br/>impact est ${d.value[0].toFixed(2)}bp<br/>residual&nbsp;&nbsp;${(d.value[1] >= 0 ? "+" : "") + d.value[1].toFixed(2)}bp vs plan`;
        }
      },
      xAxis: {
        type: "value",
        min: 0,
        max: maxX,
        name: "Predicted impact (bp)",
        nameLocation: "center",
        nameGap: 24,
        nameTextStyle: { color: QE_ECHARTS_THEME.sub, fontSize: 10 },
        ..._axis()
      },
      yAxis: {
        type: "value",
        min: minY,
        max: maxY,
        name: "Residual vs plan (bp)",
        nameLocation: "middle",
        nameGap: 32,
        nameRotate: 90,
        nameTextStyle: { color: QE_ECHARTS_THEME.sub, fontSize: 10 },
        ..._axis()
      },
      series: [
        {
          type: "line",
          silent: true,
          symbol: "none",
          data: [[0, 0], [maxX, 0]],
          lineStyle: { color: QE_ECHARTS_THEME.muted, type: "dashed", width: 1 },
          tooltip: { show: false },
          z: 1
        },
        { type: "scatter", data, symbolSize: 11, z: 2, emphasis: { scale: 1.3, itemStyle: { opacity: 1 } } }
      ]
    };
  }, [points]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, className: "qe-chart", style: { height } });
};
const AnaTabOverview = ({ period, offset, onLabel }) => {
  const { data, err, foot } = useAnaJson(`/fragments/analytics/overview?format=json&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading overview\u2026" });
  const s = data.stats || {}, b = data.boundaries || {}, c = data.cumulative || {}, ra = data.ratios || {};
  const lbl = data.period_label || "";
  const days = data.trading_days || 0;
  const pnl = s.total_pnl || 0;
  const initial = b.initial_equity || 0;
  const pnlPct = initial > 0 ? pnl / initial * 100 : null;
  const total = s.total_trades || 0;
  const wins = s.winning_trades || 0;
  const winrate = total > 0 ? wins / total * 100 : 0;
  const rr = s.avg_profit && s.avg_loss ? Math.abs(s.avg_profit / s.avg_loss) : null;
  const eqSeries = (data.daily_equity || []).map((r) => r.total_equity).filter((v) => v != null);
  const noR = (data.r_count || 0) === 0;
  const ratioRows = [
    ["Sharpe", ra.sharpe, "annualized"],
    ["Sharpe (MFE)", ra.sharpe_mfe, "mfe / notional"],
    ["Sortino", ra.sortino, "downside \u03C3 \xB7 \u221E = no downside days"],
    ["Sortino (MAE)", ra.sortino_mae, "mae / notional"],
    ["Profit Factor", noR ? null : ra.profit_factor, "\u03A3 gross w / |\u03A3 gross l| \xB7 \u221E = no losers"],
    ["Expectancy", noR ? null : ra.expectancy, "mean R-multiple", "R"]
  ].map(([l, v, d, suf]) => {
    const empty = v == null;
    const inf = !empty && v >= 999;
    const color = empty ? "sub" : inf || v >= 2 ? "green" : v >= 1 ? "amber" : "red";
    return { label: l, hint: d, value: empty ? "\u2014" : inf ? "\u221E" : (+v).toFixed(2) + (suf || ""), color };
  });
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 8, h: 6, minW: 5, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Volume & Activity",
      tag: lbl,
      style: { height: "100%" },
      foot
    },
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Trading Volume", value: `$${(s.trading_volume || 0).toLocaleString(void 0, { maximumFractionDigits: 0 })}` }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Fees Paid", value: `$${(s.total_fees || 0).toFixed(2)}` }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "No. of Longs", value: s.num_longs || 0, color: "var(--qe-green)" }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "No. of Shorts", value: s.num_shorts || 0, color: "var(--qe-red)" }),
    /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8 } }, /* @__PURE__ */ React.createElement(Lbl, null, "Top Pairs"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.68rem", color: "var(--qe-sub)", marginTop: 2 } }, (data.top_pairs || []).length ? data.top_pairs.join(" \xB7 ") : "\u2014"))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 8, y: 0, w: 16, h: 7, minW: 8, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Equity & PnL",
      tag: lbl,
      style: { height: "100%" },
      bodyStyle: { padding: 0 },
      foot
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "minmax(200px,0.9fr) 1px 1.3fr", gap: 0, height: "100%" } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "7px 12px 7px 8px" } }, /* @__PURE__ */ React.createElement(FieldList, { rows: [
      { label: "Initial Equity", value: `$${initial.toFixed(2)}` },
      { label: "Final Equity", value: `$${(b.final_equity || 0).toFixed(2)}` },
      { label: "Period PnL", value: `$${pnl.toFixed(2)}`, color: _anaPnl(pnl) },
      { label: "Period PnL %", value: pnlPct == null ? "\u2014" : `${pnlPct.toFixed(2)}%`, color: _anaPnl(pnlPct || 0) },
      { label: "Daily Avg PnL", value: days ? `$${(pnl / days).toFixed(2)}` : "\u2014", color: _anaPnl(pnl) },
      { label: "Trading Days", value: days }
    ] })), /* @__PURE__ */ React.createElement("div", { style: { background: "var(--qe-line)" } }), /* @__PURE__ */ React.createElement("div", { style: { padding: "7px 8px 7px 12px", display: "flex", flexDirection: "column", minHeight: 0 } }, /* @__PURE__ */ React.createElement(Lbl, null, "Equity Curve \xB7 ", lbl), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, marginTop: 2 } }, eqSeries.length >= 2 ? /* @__PURE__ */ React.createElement(EquityChart, { data: eqSeries, color: _anaPnl(pnl), baseline: initial || null, height: "100%" }) : /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.62rem", color: "var(--qe-muted)", padding: 8 } }, "not enough snapshots in window"))))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 6, w: 8, h: 10, minW: 5, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Trade Statistics",
      style: { height: "100%" },
      foot
    },
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Total Trades", value: total }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Winning", value: wins, color: "var(--qe-green)" }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Losing", value: s.losing_trades || 0, color: "var(--qe-red)" }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Win Rate", value: `${winrate.toFixed(1)}%`, color: winrate >= 50 ? "var(--qe-green)" : "var(--qe-red)" }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Avg W / L", value: rr == null ? "\u2014" : `${rr.toFixed(2)}\xD7` }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Avg Profit", value: `$${(s.avg_profit || 0).toFixed(2)}`, color: "var(--qe-green)" }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Avg Loss", value: `$${(s.avg_loss || 0).toFixed(2)}`, color: "var(--qe-red)" }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Biggest Win", value: `$${(s.biggest_profit || 0).toFixed(2)}`, color: "var(--qe-green)" }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Biggest Loss", value: `$${(s.biggest_loss || 0).toFixed(2)}`, color: "var(--qe-red)" }),
    /* @__PURE__ */ React.createElement(AnaVRow, { label: "Max Drawdown", value: `${((b.max_drawdown || 0) * 100).toFixed(2)}%`, color: "var(--qe-red)" })
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 8, y: 7, w: 16, h: 5, minW: 8, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Performance Ratios", style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement(FieldList, { cols: 2, rows: ratioRows }))), /* @__PURE__ */ React.createElement(GridItem, { x: 8, y: 12, w: 16, h: 4, minW: 8, minH: 4 }, /* @__PURE__ */ React.createElement(Pane, { title: "Cash & Cumulative", style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement(FieldList, { cols: 2, rows: [
    { label: "Deposits (window)", value: `$${(s.deposits || 0).toFixed(2)}` },
    { label: "Withdrawals (window)", value: `$${(s.withdrawals || 0).toFixed(2)}` },
    { label: "Cumulative PnL (all-time)", value: `$${(c.total_pnl || 0).toFixed(2)}`, color: _anaPnl(c.total_pnl || 0) },
    { label: "Cumulative PnL %", value: c.total_pnl_percent == null ? "\u2014" : `${(+c.total_pnl_percent).toFixed(2)}%`, color: _anaPnl(c.total_pnl_percent || 0) }
  ] }))));
};
const AnaTabEquity = () => {
  const [tf, setTf] = React.useState("1M");
  const [logScale, setLogScale] = React.useState(false);
  const [ddMode, setDdMode] = React.useState(false);
  const { data, err, foot } = useAnaJson(`/api/analytics/equity_ohlc?tf=${encodeURIComponent(tf)}`);
  const candles = data && data.candles || [];
  const ddSeries = React.useMemo(() => {
    let peak = -Infinity;
    return candles.map((d) => {
      if (d.c != null) peak = Math.max(peak, d.c);
      return peak > 0 && d.c != null ? +((d.c - peak) / peak * 100).toFixed(2) : 0;
    });
  }, [candles]);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading equity curve\u2026" });
  if (!candles.length) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "no equity snapshots yet" });
  const last = candles[candles.length - 1];
  const prev = candles.length > 1 ? candles[candles.length - 2] : last;
  const chg = last.c != null && prev.c != null ? last.c - prev.c : 0;
  const chgPct = prev.c ? chg / prev.c * 100 : 0;
  const ohlcRow = [
    ["O", last.o, "var(--qe-text)"],
    ["H", last.h, "var(--qe-green)"],
    ["L", last.l, "var(--qe-red)"],
    ["C", last.c, "var(--qe-text)"]
  ];
  return /* @__PURE__ */ React.createElement("div", { style: { padding: 4, height: "100%" } }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Equity Curve",
      hot: true,
      tag: ddMode ? "DRAWDOWN %" : "OHLC",
      right: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["1W", "1W"], ["2W", "2W"], ["1M", "1M"], ["3M", "3M"], ["6M", "6M"], ["1Y", "1Y"], ["all", "All"]], value: tf, onChange: setTf }), /* @__PURE__ */ React.createElement(
        "button",
        {
          className: `qe-btn qe-btn-sm ${logScale && !ddMode ? "qe-btn-on" : "qe-btn-ghost"}`,
          disabled: ddMode,
          style: ddMode ? { opacity: 0.4 } : void 0,
          onClick: () => setLogScale((v) => !v)
        },
        "log scale"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          className: `qe-btn qe-btn-sm ${ddMode ? "qe-btn-on" : "qe-btn-ghost"}`,
          onClick: () => setDdMode((v) => !v)
        },
        "drawdown %"
      )),
      style: { height: "100%" },
      bodyStyle: { padding: 6 },
      foot
    },
    /* @__PURE__ */ React.createElement("div", { style: { height: "100%", display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.62rem", display: "flex", gap: 14, flexWrap: "wrap", padding: "2px 4px", alignItems: "baseline" } }, ohlcRow.map(([k, v, col]) => /* @__PURE__ */ React.createElement("span", { key: k }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, k), " ", /* @__PURE__ */ React.createElement("span", { style: { color: col } }, v == null ? "\u2014" : `$${(+v).toFixed(2)}`))), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "Chg"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: _anaPnl(chg) } }, `${chg >= 0 ? "+" : ""}$${chg.toFixed(2)} (${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%)`)), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "Bar Range"), " ", /* @__PURE__ */ React.createElement("span", null, last.h != null && last.l != null ? `$${(last.h - last.l).toFixed(2)}` : "\u2014")), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "Cash Flow"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-blue)" } }, last.cf ? `${last.cf >= 0 ? "+" : "-"}$${Math.abs(+last.cf).toFixed(2)}` : "+$0.00"))), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0 } }, ddMode ? /* @__PURE__ */ React.createElement(EquityChart, { data: ddSeries, color: "var(--qe-red)", baseline: 0 }) : /* @__PURE__ */ React.createElement(CandlestickChart, { data: candles.map((d) => [d.x, d.o, d.c, d.l, d.h]), logScale })))
  ));
};
const AnaTabDistributions = ({ period, offset, onLabel }) => {
  const { data, err, foot } = useAnaJson(`/api/analytics/distributions?${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading distributions\u2026" });
  const trades = data.trades || [];
  if (!trades.length) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "no closed trades in window" });
  const lbl = data.period_label || "";
  const pnls = trades.map((t) => t.pnl).filter((v) => v != null);
  const lo = Math.min(...pnls, 0), hi = Math.max(...pnls, 0);
  const rawStep = (hi - lo) / 12 || 1;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= rawStep) || 10 * mag;
  const b0 = Math.floor(lo / step) * step;
  const nBins = Math.max(1, Math.ceil((hi - b0) / step) || 1);
  const pnlBins = Array.from({ length: nBins }, (_, i) => {
    const a = b0 + i * step;
    return {
      label: `${a >= 0 ? "+" : ""}${+a.toFixed(2)}`,
      count: pnls.filter((v) => v >= a && v < a + step).length,
      pos: a >= 0
    };
  });
  const holds = trades.map((t) => t.hold_min).filter((v) => v != null);
  const HOLD_EDGES = [[0, 10], [10, 30], [30, 60], [60, 120], [120, 240], [240, 480], [480, Infinity]];
  const holdBins = HOLD_EDGES.map(([a, b]) => ({
    label: b === Infinity ? `${a}+` : `${a}-${b}`,
    count: holds.filter((v) => v >= a && v < b).length
  }));
  const hourBins = Array.from({ length: 24 }, (_, h) => ({
    label: h % 3 === 0 ? `${h}h` : "",
    count: trades.filter((t) => t.hour === h).length
  }));
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const dowRows = DOW.map((label, i) => {
    const ts = trades.filter((t) => t.dow === i && t.pnl != null);
    return { label, v: ts.length ? ts.reduce((s, t) => s + t.pnl, 0) / ts.length : 0, n: ts.length };
  });
  const wrHourBins = Array.from({ length: 24 }, (_, h) => {
    const tr = trades.filter((t) => t.hour === h && t.pnl != null);
    const w = tr.filter((t) => t.pnl > 0).length;
    return {
      label: h % 3 === 0 ? `${h}h` : "",
      count: tr.length ? Math.round(w / tr.length * 100) : 0,
      pos: tr.length > 0 && w / tr.length >= 0.5
    };
  });
  const rBins = (data.r_histogram || []).map((b) => ({ label: b.label, count: b.count, pos: b.pos }));
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 12, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "PnL Distribution",
      style: { height: "100%" },
      tag: lbl || `$${step} bins`,
      foot
    },
    /* @__PURE__ */ React.createElement(AnaHistChart, { bins: pnlBins, divergent: true, noun: "trade" })
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 12, y: 0, w: 12, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "R-Multiple Distribution",
      style: { height: "100%" },
      tag: "1R bins",
      right: /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "n=", (data.r_values || []).length, " \xB7 positional R from plan SL"),
      foot
    },
    rBins.length ? /* @__PURE__ */ React.createElement(AnaHistChart, { bins: rBins, divergent: true, noun: "trade" }) : /* @__PURE__ */ React.createElement(EmptyState, { fill: true, msg: "no R-multiples in window" })
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 6, w: 12, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Hold Time Distribution", style: { height: "100%" }, tag: "min", foot }, holds.length ? /* @__PURE__ */ React.createElement(AnaHistChart, { bins: holdBins, color: "var(--qe-blue)", noun: "trade" }) : /* @__PURE__ */ React.createElement(EmptyState, { fill: true, msg: "no hold-time data (open_time unknown)" }))), /* @__PURE__ */ React.createElement(GridItem, { x: 12, y: 6, w: 12, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Trades by Hour of Day", style: { height: "100%" }, tag: "account tz", foot }, /* @__PURE__ */ React.createElement(AnaHistChart, { bins: hourBins, color: "var(--qe-cyan)", noun: "trade" }))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 12, w: 12, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Avg PnL by Day of Week", style: { height: "100%" }, tag: "$", foot }, /* @__PURE__ */ React.createElement(AnaDivergingBars, { rows: dowRows }))), /* @__PURE__ */ React.createElement(GridItem, { x: 12, y: 12, w: 12, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Win Rate by Hour of Day", style: { height: "100%" }, tag: "%", foot }, /* @__PURE__ */ React.createElement(
    AnaHistChart,
    {
      bins: wrHourBins,
      divergent: true,
      unit: "%",
      tip: (l, v) => `${l || "hour"} \xB7 ${v}% win rate`
    }
  ))));
};
const AnaTabCalendar = () => {
  const [ym, setYm] = React.useState("");
  const { data, err, foot } = useAnaJson(`/fragments/analytics/calendar?format=json&month=${encodeURIComponent(ym)}`);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading calendar\u2026" });
  const weeks = data.calendar_grid || [];
  const maxAbs = data.max_abs_pnl || 1;
  const atCurrent = data.month >= data.current_month;
  return /* @__PURE__ */ React.createElement("div", { style: { padding: 4, height: "100%" } }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Calendar PnL",
      right: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: () => setYm(data.prev_month) }, "\u2039 Prev"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.74rem", fontWeight: 700, padding: "0 6px" } }, data.month_label), /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "qe-btn qe-btn-sm qe-btn-ghost",
          disabled: atCurrent,
          style: atCurrent ? { opacity: 0.4 } : void 0,
          title: atCurrent ? "Already at the current month" : "",
          onClick: () => setYm(data.next_month)
        },
        "Next \u203A"
      )),
      style: { height: "100%" },
      foot
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6, height: "100%" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 2 } }, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => /* @__PURE__ */ React.createElement("div", { key: d, style: { textAlign: "center", fontSize: "0.54rem", color: "var(--qe-muted)", textTransform: "uppercase", padding: "2px 0", letterSpacing: "0.1em" } }, d))), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 2, flex: 1, minHeight: 0, alignContent: "start" } }, weeks.flat().map((cell, i) => {
      if (!cell || !cell.day) return /* @__PURE__ */ React.createElement("div", { key: i });
      if (cell.pnl == null) {
        return /* @__PURE__ */ React.createElement("div", { key: i, title: `${cell.date}: no trades`, style: {
          background: "var(--qe-panel)",
          border: "1px solid color-mix(in srgb, var(--qe-text) 4%, transparent)",
          // operator-bug #7: day cells sized 2:3 (height:width) via
          // aspect-ratio 3/2 — was flat (minHeight 46 only). minHeight
          // kept as a floor for narrow panes.
          padding: "4px 6px",
          aspectRatio: "3 / 2",
          minHeight: 46,
          opacity: 0.45
        } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.6rem", fontFamily: "var(--qe-mono)", color: "var(--qe-muted)" } }, cell.day));
      }
      const intensity = Math.min(Math.abs(cell.pnl) / maxAbs, 1);
      const bg = cell.pnl > 0 ? `rgba(0,255,127,${0.12 + intensity * 0.6})` : cell.pnl < 0 ? `rgba(255,45,74,${0.12 + intensity * 0.6})` : "var(--qe-panel)";
      const tc = cell.pnl >= 0 ? "var(--qe-green)" : "var(--qe-red)";
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          key: i,
          title: `${cell.date}: $${cell.pnl.toFixed(2)} \xB7 ${cell.trades || 0}T \xB7 ${((cell.win_rate || 0) * 100).toFixed(0)}% WR`,
          style: { background: bg, border: "1px solid color-mix(in srgb, var(--qe-text) 4%, transparent)", padding: "4px 6px", display: "flex", flexDirection: "column", aspectRatio: "3 / 2", minHeight: 46 }
        },
        /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.6rem", fontFamily: "var(--qe-mono)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: tc, fontWeight: 600 } }, cell.day), cell.trades > 0 && /* @__PURE__ */ React.createElement("span", { style: { color: tc, opacity: 0.7 } }, ((cell.win_rate || 0) * 100).toFixed(0), "%")),
        /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.7rem", fontWeight: 700, color: tc, marginTop: 3 } }, cell.pnl >= 0 ? "+" : "-", "$", Math.abs(cell.pnl).toFixed(2)),
        /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }),
        cell.trades > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.52rem", color: tc, opacity: 0.75, fontFamily: "var(--qe-mono)" } }, cell.trades, "T")
      );
    })), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, padding: "6px 4px", borderTop: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(AnaKv, { label: "Trading Days", value: data.trading_days || 0 }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Avg Daily PnL", value: `$${(data.avg_daily || 0).toFixed(2)}`, color: _anaPnl(data.avg_daily || 0) }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Best Day", value: `$${(data.best_day || 0).toFixed(2)}`, color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Worst Day", value: `$${(data.worst_day || 0).toFixed(2)}`, color: "var(--qe-red)" })))
  ));
};
const AnaTabPairs = ({ period, offset, onLabel }) => {
  const { data, err, foot } = useAnaJson(`/fragments/analytics/pairs?format=json&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading pairs\u2026" });
  const rows = data.rows || [];
  if (!rows.length) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "no trades in window" });
  const totals = {
    trades: rows.reduce((s, r) => s + (r.total || 0), 0),
    pnl: rows.reduce((s, r) => s + (r.pnl_total || 0), 0),
    fees: rows.reduce((s, r) => s + (r.fees_total || 0), 0),
    vol: rows.reduce((s, r) => s + (r.volume || 0), 0)
  };
  const pnlCell = (v, bold) => /* @__PURE__ */ React.createElement("span", { style: { color: v >= 0 ? "var(--qe-green)" : "var(--qe-red)", fontWeight: bold ? 700 : void 0 } }, v === 0 ? "\u2014" : (v >= 0 ? "+" : "") + v.toFixed(2));
  return /* @__PURE__ */ React.createElement("div", { style: { padding: 4, height: "100%" } }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Traded Pairs",
      count: `${rows.length} symbols`,
      tag: data.period_label,
      style: { height: "100%" },
      bodyStyle: { padding: 0 },
      foot
    },
    /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "symbol",
        dense: false,
        columns: [
          { key: "symbol", label: "SYMBOL", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.symbol) },
          { key: "total", label: "TRADES", align: "right" },
          { key: "longs", label: "LONGS", align: "right", cell: "up" },
          { key: "shorts", label: "SHORTS", align: "right", cell: "dn" },
          { key: "pnl_long", label: "PnL (L)", align: "right", render: (r) => pnlCell(r.pnl_long || 0) },
          { key: "pnl_short", label: "PnL (S)", align: "right", render: (r) => pnlCell(r.pnl_short || 0) },
          {
            key: "pnl_total",
            label: "PnL TOTAL",
            align: "right",
            // DataList sweep: this pane's only faceting axis. SYMBOL is
            // unique-per-row (the query GROUP BYs it) and every other column is
            // continuous numeric, so nothing here can auto-facet. Bucketing the
            // sign gives at most 3 options and answers the pane's question.
            filter: { label: "RESULT" },
            filterVal: (r) => (r.pnl_total || 0) > 0 ? "WIN" : (r.pnl_total || 0) < 0 ? "LOSS" : "FLAT",
            render: (r) => pnlCell(r.pnl_total || 0, true)
          },
          { key: "win_rate", label: "WIN RATE", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: (r.win_rate || 0) >= 0.5 ? "var(--qe-green)" : "var(--qe-red)" } }, ((r.win_rate || 0) * 100).toFixed(1), "%") },
          { key: "avg_win", label: "AVG WIN", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, r.avg_win ? r.avg_win.toFixed(2) : "\u2014") },
          { key: "avg_loss", label: "AVG LOSS", align: "right", cell: "dn", render: (r) => r.avg_loss ? r.avg_loss.toFixed(2) : "\u2014" },
          { key: "fees_total", label: "FEES", align: "right", cell: "dim", render: (r) => (r.fees_total || 0).toFixed(2) },
          { key: "volume", label: "VOLUME", align: "right", cell: "dim", render: (r) => (r.volume || 0).toLocaleString(void 0, { maximumFractionDigits: 0 }) }
        ],
        rows,
        summary: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "TOTAL"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)", fontWeight: 700 } }, totals.trades, " trades")), /* @__PURE__ */ React.createElement("span", { style: { color: totals.pnl >= 0 ? "var(--qe-green)" : "var(--qe-red)", fontWeight: 700 } }, "\u03A3 PnL ", totals.pnl >= 0 ? "+" : "", totals.pnl.toFixed(2), " \xB7 fees ", totals.fees.toFixed(2), " \xB7 vol ", totals.vol.toLocaleString(void 0, { maximumFractionDigits: 0 })))
      }
    )
  ));
};
const AnaTabExcursions = ({ period, offset, onLabel }) => {
  const [dir, setDir] = React.useState("all");
  const { data, err, foot } = useAnaJson(`/fragments/analytics/excursions?format=json&dir=${encodeURIComponent(dir)}&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading excursions\u2026" });
  const trades = data.trades || [];
  const points = (data.scatter_data || []).map((p) => ({ x: p.x, y: p.y, profit: (p.z || 0) >= 0, label: p.sym }));
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 16, h: 16, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "MFE / MAE Scatter",
      tag: data.period_label,
      right: /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["all", "All"], ["LONG", "Long"], ["SHORT", "Short"]], value: dir, onChange: setDir }),
      style: { height: "100%" },
      bodyStyle: { padding: 6 },
      foot
    },
    points.length ? /* @__PURE__ */ React.createElement(ScatterChart, { points, xName: "MFE ($)", yName: "MAE ($)" }) : /* @__PURE__ */ React.createElement(EmptyState, { fill: true, msg: "no reconciled excursions in window" })
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 16, y: 0, w: 8, h: 5, minW: 5, minH: 4 }, /* @__PURE__ */ React.createElement(Pane, { title: "Excursion Summary", style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 14px" } }, /* @__PURE__ */ React.createElement(AnaKv, { label: "Avg MFE", value: `$${(data.avg_mfe || 0).toFixed(2)}`, color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Avg |MAE|", value: `$${(data.avg_mae_abs || 0).toFixed(2)}`, color: "var(--qe-red)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Avg ME-Ratio", value: (data.avg_mer || 0).toFixed(2) }), /* @__PURE__ */ React.createElement(AnaKv, { label: "MFE > 2\xD7 MAE", value: `${data.pct_favorable || 0}%`, color: "var(--qe-green)" })))), /* @__PURE__ */ React.createElement(GridItem, { x: 16, y: 5, w: 8, h: 11, minW: 5, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Per-Trade Excursions",
      count: points.length > trades.length ? `${trades.length} of ${points.length}` : trades.length,
      style: { height: "100%" },
      bodyStyle: { padding: 0 },
      foot
    },
    /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "trade_key",
        columns: [
          { key: "symbol", label: "SYMBOL", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.symbol) },
          { key: "direction", label: "DIR", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.direction === "LONG" ? "ok" : "err" }, r.direction) },
          { key: "mfe", label: "MFE", align: "right", cell: "up", render: (r) => (r.mfe || 0).toFixed(2) },
          { key: "mae", label: "MAE", align: "right", cell: "dn", render: (r) => (r.mae || 0).toFixed(2) },
          // 'mer' is computed in render — no row carries the key, so the
          // header sorted on undefined for every row (a dead control).
          {
            key: "mer",
            label: "ME-R",
            align: "right",
            sortVal: (r) => r.mae ? Math.abs((r.mfe || 0) / r.mae) : null,
            render: (r) => r.mae ? Math.abs((r.mfe || 0) / r.mae).toFixed(2) : "\u2014"
          },
          {
            key: "income",
            label: "PnL",
            align: "right",
            filter: { label: "RESULT" },
            filterVal: (r) => (r.income || 0) >= 0 ? "WIN" : "LOSS",
            render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: (r.income || 0) >= 0 ? "var(--qe-green)" : "var(--qe-red)", fontWeight: 700 } }, (r.income || 0) >= 0 ? "+" : "", (r.income || 0).toFixed(2))
          },
          { key: "hold_ms", label: "HOLD", align: "right", cell: "dim", render: (r) => _hDur(r.hold_ms) }
        ],
        rows: trades,
        emptyMsg: "no excursions in window"
      }
    )
  )));
};
const AnaTabRMultiples = ({ period, offset, onLabel }) => {
  const { data, err, foot } = useAnaJson(`/fragments/analytics/r_multiples?format=json&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading r-multiples\u2026" });
  const st = data.r_stats || {};
  const bins = (data.histogram || []).map((b) => ({ label: b.label, count: b.count, pos: b.pos }));
  if (!st.count) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "no R-multiples in window (needs plan-linked closes)" });
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 16, h: 12, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "R-Multiple Distribution",
      tag: data.period_label,
      style: { height: "100%" },
      foot
    },
    /* @__PURE__ */ React.createElement(AnaHistChart, { bins, divergent: true, noun: "trade" })
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 16, y: 0, w: 8, h: 12, minW: 5, minH: 6 }, /* @__PURE__ */ React.createElement(Pane, { title: "R-Multiple Stats", style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, /* @__PURE__ */ React.createElement(AnaKv, { label: "Total Trades", value: st.count }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Win Rate", value: `${((st.win_rate || 0) * 100).toFixed(1)}%`, color: (st.win_rate || 0) >= 0.5 ? "var(--qe-green)" : "var(--qe-red)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Expectancy", value: `${(st.expectancy || 0).toFixed(3)}R`, color: _anaPnl(st.expectancy || 0) }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Profit Factor", value: _anaRatio(st.profit_factor), color: (st.profit_factor || 0) >= 1.5 ? "var(--qe-green)" : (st.profit_factor || 0) >= 1 ? "var(--qe-amber)" : "var(--qe-red)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Avg Win R", value: `${(st.avg_win_r || 0).toFixed(2)}R`, color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Avg Loss R", value: `${(st.avg_loss_r || 0).toFixed(2)}R`, color: "var(--qe-red)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Best R", value: `${(st.best || 0).toFixed(2)}R`, color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Worst R", value: `${(st.worst || 0).toFixed(2)}R`, color: "var(--qe-red)" }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Median R", value: `${(st.median || 0).toFixed(2)}R` }), /* @__PURE__ */ React.createElement(AnaKv, { label: "Mean R", value: `${(st.mean || 0).toFixed(3)}R` })))));
};
const AnaVarCard = ({ label, val, equity, desc }) => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4, padding: 10, background: "var(--qe-panel)", border: "1px solid var(--qe-line)" }, title: desc }, /* @__PURE__ */ React.createElement(Lbl, null, label), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "1rem", fontWeight: 700, color: "var(--qe-red)" } }, Math.abs(val * 100).toFixed(2), "%"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "$", Math.abs(val * (equity || 0)).toFixed(0)));
const AnaTabRisk = ({ period, offset, onLabel }) => {
  const { data, err, foot } = useAnaJson(`/fragments/analytics/var?format=json&${_anaQS(period, offset)}`);
  useAnaLabel(data, onLabel);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading risk metrics\u2026" });
  if (!data.has_data) {
    return /* @__PURE__ */ React.createElement("div", { style: { padding: 4, height: "100%" } }, /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        tone: "info",
        glyph: "\u03C3",
        msg: `VaR needs \u226520 daily returns in the window \u2014 have ${(data.returns || []).length}`,
        hint: "widen the period (90D / All) or come back after more trading days"
      }
    ));
  }
  const varThreshPct = (data.var95 || 0) * 100;
  const histBins = (data.hist_data || []).map((b) => ({
    label: `${b.x.toFixed(1)}%`,
    count: b.y,
    pos: b.x > varThreshPct
  }));
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 5, minW: 10, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Value at Risk \xB7 Risk Metrics",
      tag: data.period_label,
      style: { height: "100%" },
      foot
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8 } }, /* @__PURE__ */ React.createElement(AnaVarCard, { label: "Historical VaR (95%)", val: data.var95 || 0, equity: data.cur_equity, desc: "Worst daily loss exceeded 5% of the time" }), /* @__PURE__ */ React.createElement(AnaVarCard, { label: "Historical VaR (99%)", val: data.var99 || 0, equity: data.cur_equity, desc: "Worst daily loss exceeded 1% of the time" }), /* @__PURE__ */ React.createElement(AnaVarCard, { label: "CVaR / ES (95%)", val: data.cvar95 || 0, equity: data.cur_equity, desc: "Expected Shortfall \u2014 average loss on worst 5% of days" }), /* @__PURE__ */ React.createElement(AnaVarCard, { label: "Parametric VaR (95%)", val: data.pvar95 || 0, equity: data.cur_equity, desc: "Gaussian VaR (\u03BC \u2212 1.645\u03C3)" }))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 5, w: 24, h: 12, minW: 10, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Daily Return Distribution",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "red = below the 95% VaR threshold \xB7 n=", (data.returns || []).length, " days"),
      foot
    },
    /* @__PURE__ */ React.createElement(AnaHistChart, { bins: histBins, divergent: true, unit: "%", noun: "day" })
  )));
};
const ANA_LINK_META = {
  auto: { label: "Auto-linked", color: "var(--qe-green)", bg: "rgba(0,255,127,0.06)" },
  confirmed: { label: "Confirmed", color: "var(--qe-cyan)", bg: "rgba(0,231,255,0.05)" },
  partial: { label: "Partial", color: "var(--qe-amber)", bg: "rgba(255,174,0,0.06)" },
  unlinked: { label: "Unlinked", color: "var(--qe-red)", bg: "rgba(255,45,74,0.06)" },
  na: { label: "n/a (close/manual)", color: "var(--qe-muted)", bg: "transparent" }
};
const _anaLinkKey = (r) => {
  if (r.link_status === "linked") return r.link_confirmed ? "confirmed" : "auto";
  if (r.link_status === "partial") return "partial";
  if (r.link_status === "unlinked") return "unlinked";
  return "na";
};
const AnaTabExecution = () => {
  const [ftFilter, setFtFilter] = React.useState("all");
  const { data, err, foot } = useAnaJson("/api/analytics/execution?limit=500");
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading execution quality\u2026" });
  const rows = data.rows || [];
  const sum = data.summary || {};
  if (!rows.length) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "no fills recorded yet" });
  const entryN = sum.by_fill_type && sum.by_fill_type.entry || 0;
  const linkedEntries = rows.filter((r) => r.fill_type === "entry" && r.link_status === "linked").length;
  const linkCov = entryN > 0 ? linkedEntries / entryN * 100 : null;
  const calcPct = sum.total ? sum.calc_backed / sum.total * 100 : 0;
  const bias = sum.bias_bp;
  const linkBreak = ["auto", "confirmed", "partial", "unlinked", "na"].map((k) => ({
    key: k,
    ...ANA_LINK_META[k],
    n: rows.filter((r) => _anaLinkKey(r) === k).length
  }));
  const ftStats = ["entry", "tp", "sl", "manual", "reduce_only"].map((ft) => {
    const es = rows.filter((r) => r.fill_type === ft && r.slippage_cost != null);
    return { ft, n: es.length, avgBp: es.length ? es.reduce((s, r) => s + Math.abs(r.slippage_cost), 0) / es.length * 1e4 : 0 };
  });
  const maxFtBp = Math.max(...ftStats.map((f) => f.avgBp), 0.1);
  const scatterPts = rows.filter((r) => r.est_slippage != null && r.slippage_cost != null).map((r) => ({ est: r.est_slippage * 1e4, act: r.slippage_cost * 1e4, ft: r.fill_type || "entry", id: r.exchange_fill_id || String(r.fill_id) }));
  const ttfs = rows.map((r) => r.time_to_fill_ms).filter((v) => v != null);
  const TTF_EDGES = [[0, 1e3, "<1s"], [1e3, 1e4, "1-10s"], [1e4, 6e4, "10-60s"], [6e4, 6e5, "1-10m"], [6e5, 36e5, "10-60m"], [36e5, Infinity, "1h+"]];
  const ttfBins = TTF_EDGES.map(([a, b, label]) => ({ label, count: ttfs.filter((v) => v >= a && v < b).length }));
  const entryCosts = rows.filter((r) => r.fill_type === "entry" && r.slippage_cost != null).map((r) => r.slippage_cost * 1e4);
  const SLIP_STEP = 5;
  const slipMax = Math.min(100, Math.max(SLIP_STEP, Math.ceil(Math.max(...entryCosts, 0) / SLIP_STEP) * SLIP_STEP));
  const slipBins = [{ label: "<0", count: entryCosts.filter((v) => v < 0).length }].concat(Array.from({ length: slipMax / SLIP_STEP }, (_, i) => {
    const a = i * SLIP_STEP;
    return { label: `${a}-${a + SLIP_STEP}`, count: entryCosts.filter((v) => v >= a && v < a + SLIP_STEP).length };
  })).concat(entryCosts.some((v) => v >= slipMax) ? [{ label: `${slipMax}+`, count: entryCosts.filter((v) => v >= slipMax).length }] : []);
  const otKeys = Object.keys(sum.by_order_type || {}).sort((a, b) => (sum.by_order_type[b] || 0) - (sum.by_order_type[a] || 0));
  const otColor = (ot) => {
    const u = ot.toUpperCase();
    return u === "LIMIT" ? "var(--qe-green)" : u === "MARKET" ? "var(--qe-blue)" : u.includes("STOP") ? "var(--qe-red)" : "var(--qe-sub)";
  };
  const tableRows = ftFilter === "all" ? rows : rows.filter((r) => r.fill_type === ftFilter);
  const kpis = [
    {
      l: "Exec Link Coverage",
      v: linkCov == null ? "\u2014" : `${linkCov.toFixed(1)}%`,
      sub: `${linkedEntries}/${entryN} entry fills auto+confirmed`,
      tone: linkCov == null ? "var(--qe-sub)" : linkCov > 80 ? "var(--qe-green)" : "var(--qe-amber)"
    },
    { l: "Calc-Backed Fills", v: `${calcPct.toFixed(0)}%`, sub: `${sum.calc_backed}/${sum.total} carry calc_id`, tone: "var(--qe-blue)" },
    {
      l: "Entry Residual (vs plan)",
      v: sum.avg_cost_bp == null ? "\u2014" : `${sum.avg_cost_bp >= 0 ? "+" : ""}${sum.avg_cost_bp.toFixed(2)}bp`,
      sub: sum.avg_est_bp == null ? "no calc-backed entries" : `predicted impact ${sum.avg_est_bp.toFixed(2)}bp \xB7 n=${sum.entry_n}`,
      tone: "var(--qe-text)"
    },
    {
      l: "Slip Bias",
      v: bias == null ? "\u2014" : `${bias >= 0 ? "+" : ""}${bias.toFixed(2)}bp`,
      sub: bias == null ? "needs calc-backed entries" : bias > 0 ? "fills run worse than plan" : "fills run better than plan",
      tone: bias == null ? "var(--qe-sub)" : Math.abs(bias) < 0.5 ? "var(--qe-green)" : "var(--qe-amber)"
    },
    { l: "Time to Fill (p95)", v: _anaMs(sum.ttf_p95_ms), sub: `avg ${_anaMs(sum.ttf_avg_ms)} \xB7 max ${_anaMs(sum.ttf_max_ms)} \xB7 n=${sum.ttf_n}`, tone: "var(--qe-cyan)" }
  ];
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, kpis.map(({ l, v, sub, tone }, i) => /* @__PURE__ */ React.createElement(GridItem, { key: l, x: i < 4 ? i * 4 : 16, y: 0, w: i === 4 ? 8 : 4, h: 3, minW: 3, minH: 3 }, /* @__PURE__ */ React.createElement(Pane, { title: l, style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4 } }, /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "1.1rem", fontWeight: 700, color: tone, lineHeight: 1.1 } }, v), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.58rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", lineHeight: 1.4 } }, sub))))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 3, w: 12, h: 6, minW: 6, minH: 6 }, /* @__PURE__ */ React.createElement(Pane, { title: "Exec Link Status", style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", height: 12, marginBottom: 8, gap: 1, background: "var(--qe-panel)" } }, linkBreak.filter((b) => b.n > 0).map((b) => /* @__PURE__ */ React.createElement("div", { key: b.key, title: `${b.label}: ${b.n}`, style: { flex: b.n, background: b.color, opacity: 0.85 } }))), linkBreak.map((b) => /* @__PURE__ */ React.createElement("div", { key: b.key, style: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "3px 6px",
    background: b.bg,
    marginBottom: 2,
    borderLeft: `2px solid ${b.color}`
  } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", fontWeight: 700, color: b.color } }, b.label), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, alignItems: "baseline" } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.66rem", color: b.color, fontWeight: 700 } }, b.n), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.58rem", color: "var(--qe-muted)" } }, rows.length ? (b.n / rows.length * 100).toFixed(0) : 0, "%")))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", color: "var(--qe-muted)", lineHeight: 1.5, marginTop: 6, borderTop: "1px solid var(--qe-faint)", paddingTop: 4 } }, "Link status needs ", /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-cyan)" } }, "calc_id"), " on the fill (entry fills only \u2014 close/manual fills report n/a)."))), /* @__PURE__ */ React.createElement(GridItem, { x: 12, y: 3, w: 12, h: 6, minW: 6, minH: 6 }, /* @__PURE__ */ React.createElement(Pane, { title: "Avg |Slippage| by Fill Type", tag: "bp", style: { height: "100%" }, foot }, ftStats.map(({ ft, n, avgBp }) => /* @__PURE__ */ React.createElement("div", { key: ft, style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", fontWeight: 700, color: ANA_FT_COLOR[ft], width: 76, flexShrink: 0 } }, ft), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, height: 10, background: "var(--qe-panel)", border: "1px solid var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: n > 0 ? `${(avgBp / maxFtBp * 100).toFixed(1)}%` : "0%", height: "100%", background: ANA_FT_COLOR[ft], opacity: 0.8 } })), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", fontWeight: 700, color: ANA_FT_COLOR[ft], width: 52, textAlign: "right", flexShrink: 0 } }, n > 0 ? avgBp.toFixed(1) + "bp" : "\u2014"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", width: 26, textAlign: "right", flexShrink: 0 } }, "\xD7", n))), /* @__PURE__ */ React.createElement("div", { className: "qe-divider-h", style: { margin: "6px 0" } }), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", color: "var(--qe-muted)", lineHeight: 1.5 } }, "sl slippage is measured against the stop trigger; entry against the plan's effective entry."))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 9, w: 24, h: 8, minW: 10, minH: 7 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Entry Slippage: Predicted Impact vs Residual",
      tag: "calc-backed entries",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)" } }, "y=0 = fill exactly at the plan's predicted price \xB7 red ring = worse than plan"),
      bodyStyle: { padding: "8px 10px" },
      foot
    },
    scatterPts.length ? /* @__PURE__ */ React.createElement(AnaExecScatter, { points: scatterPts }) : /* @__PURE__ */ React.createElement(EmptyState, { fill: true, msg: "no calc-backed entries with both estimate and residual yet" })
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 17, w: 12, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Time-to-Fill Distribution", tag: "order\u2192fill", style: { height: "100%" }, bodyStyle: { display: "flex", flexDirection: "column" }, foot }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0 } }, ttfs.length ? /* @__PURE__ */ React.createElement(AnaHistChart, { bins: ttfBins, color: "var(--qe-cyan)", noun: "fill" }) : /* @__PURE__ */ React.createElement(EmptyState, { msg: "no order-linked fills yet" })), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 14, marginTop: 6, fontSize: "0.58rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, /* @__PURE__ */ React.createElement("span", null, "avg ", _anaMs(sum.ttf_avg_ms)), /* @__PURE__ */ React.createElement("span", null, "p95 ", _anaMs(sum.ttf_p95_ms)), /* @__PURE__ */ React.createElement("span", null, "max ", _anaMs(sum.ttf_max_ms)), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "auto" } }, "engine-observed (order persisted \u2192 fill) \xB7 resting limits skew high")))), /* @__PURE__ */ React.createElement(GridItem, { x: 12, y: 17, w: 12, h: 6, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Entry Residual Distribution", tag: "bp vs plan", style: { height: "100%" }, bodyStyle: { display: "flex", flexDirection: "column" }, foot }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0 } }, entryCosts.length ? /* @__PURE__ */ React.createElement(AnaHistChart, { bins: slipBins, color: "var(--qe-blue)", noun: "fill" }) : /* @__PURE__ */ React.createElement(EmptyState, { msg: "no calc-backed entry fills yet" })), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.58rem", color: "var(--qe-muted)", marginTop: 6, fontFamily: "var(--qe-mono)" } }, "<0 = filled better than plan \xB7 ", "n=", entryCosts.length))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 23, w: 12, h: 5, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Order Type Mix", style: { height: "100%" }, foot }, otKeys.length ? otKeys.map((ot) => {
    const n = sum.by_order_type[ot] || 0;
    const c = otColor(ot);
    return /* @__PURE__ */ React.createElement("div", { key: ot, style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", color: c, width: 110, flexShrink: 0 } }, ot.toUpperCase()), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, height: 8, background: "var(--qe-panel)", border: "1px solid var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: `${(n / (sum.total || 1) * 100).toFixed(1)}%`, height: "100%", background: c, opacity: 0.8 } })), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", color: "var(--qe-text)", width: 24, textAlign: "right", flexShrink: 0 } }, n), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", width: 34, textAlign: "right", flexShrink: 0 } }, (n / (sum.total || 1) * 100).toFixed(0), "%"));
  }) : /* @__PURE__ */ React.createElement(EmptyState, { msg: "no order metadata" }), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", color: "var(--qe-muted)", marginTop: 4 } }, '"unknown" = fill without a tracked parent order.'))), /* @__PURE__ */ React.createElement(GridItem, { x: 12, y: 23, w: 12, h: 5, minW: 6, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Maker / Taker Split", style: { height: "100%" }, foot }, [["maker", sum.maker || 0, "var(--qe-green)"], ["taker", sum.taker || 0, "var(--qe-amber)"]].map(([role, n, c]) => /* @__PURE__ */ React.createElement("div", { key: role, style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", color: c, width: 60, flexShrink: 0 } }, role.toUpperCase()), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, height: 8, background: "var(--qe-panel)", border: "1px solid var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: `${(n / (sum.total || 1) * 100).toFixed(1)}%`, height: "100%", background: c, opacity: 0.8 } })), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", color: "var(--qe-text)", width: 24, textAlign: "right", flexShrink: 0 } }, n), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", width: 34, textAlign: "right", flexShrink: 0 } }, (n / (sum.total || 1) * 100).toFixed(0), "%"))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", color: "var(--qe-muted)", marginTop: 4 } }, "role stamped per fill by the exchange stream; maker rebates lower fee drag."))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 28, w: 24, h: 14, minW: 10, minH: 8 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Per-Fill Log",
      count: tableRows.length,
      tag: `newest ${data.limit}`,
      style: { height: "100%" },
      foot,
      right: /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 3 } }, ["all", "entry", "tp", "sl", "manual"].map((f) => /* @__PURE__ */ React.createElement(
        "button",
        {
          key: f,
          onClick: () => setFtFilter(f),
          className: `qe-btn qe-btn-sm ${ftFilter === f ? "qe-btn-primary" : ""}`,
          style: { color: ftFilter === f ? "var(--qe-bg)" : ANA_FT_COLOR[f] || "var(--qe-sub)", textTransform: "uppercase", letterSpacing: "0.04em" }
        },
        f
      ))),
      bodyStyle: { padding: 0, display: "flex", flexDirection: "column" }
    },
    /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "fill_id",
        columns: [
          { key: "time_ms", label: "TIME", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, _hFmtTs(r.time_ms)) },
          { key: "symbol", label: "SYM", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.symbol) },
          { key: "fill_type", label: "FILL", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: ANA_FT_COLOR[r.fill_type] || "var(--qe-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", fontSize: "0.58rem" } }, r.fill_type || "\u2014") },
          { key: "order_type", label: "TYPE", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, (r.order_type || "\u2014").toUpperCase()) },
          { key: "est_slippage", label: "EST IMPACT", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, r.est_slippage != null ? (r.est_slippage * 1e4).toFixed(1) + "bp" : "\u2014") },
          { key: "slippage_cost", label: "RESIDUAL", align: "right", render: (r) => {
            if (r.slippage_cost == null) return /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014");
            const bp = r.slippage_cost * 1e4;
            return /* @__PURE__ */ React.createElement("span", { style: { color: bp > 5 ? "var(--qe-amber)" : bp < 0 ? "var(--qe-green)" : "var(--qe-text)", fontWeight: 700 } }, (bp >= 0 ? "+" : "") + bp.toFixed(1), "bp");
          } },
          { key: "time_to_fill_ms", label: "TTF", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)" } }, _anaMs(r.time_to_fill_ms)) },
          { key: "role", label: "ROLE", render: (r) => r.role ? /* @__PURE__ */ React.createElement(Badge, { tone: r.role === "maker" ? "ok" : "warn" }, r.role.toUpperCase()) : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") },
          // LINK renders a DERIVED 5-bucket label via _anaLinkKey, but sorted
          // and faceted on the raw link_status — which is a different value
          // set, and on live data is NULL on nearly every fill, so the header
          // did nothing. Point all three at the rendered label.
          {
            key: "link_status",
            label: "LINK",
            filter: { label: "LINK" },
            filterVal: (r) => ANA_LINK_META[_anaLinkKey(r)].label,
            sortVal: (r) => ANA_LINK_META[_anaLinkKey(r)].label,
            render: (r) => {
              const m = ANA_LINK_META[_anaLinkKey(r)];
              return /* @__PURE__ */ React.createElement("span", { style: { color: m.color, fontWeight: 700, fontSize: "0.58rem" } }, m.label);
            }
          },
          { key: "calc_id", label: "CALC ID", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: r.calc_id ? "var(--qe-sub)" : "var(--qe-muted)" } }, r.calc_id ? String(r.calc_id).slice(-8) : "\u2014") }
        ],
        rows: tableRows,
        emptyMsg: "No fills match this filter",
        summary: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", null, tableRows.length, " fills \xB7 ", sum.maker || 0, " maker \xB7 ", sum.taker || 0, " taker"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)" } }, "ttf avg ", _anaMs(sum.ttf_avg_ms), " \xB7 p95 ", _anaMs(sum.ttf_p95_ms)))
      }
    )
  )));
};
const AnaTabFunding = () => {
  const { data, err, foot } = useAnaJson("/fragments/analytics/funding?format=json", 3e4);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading funding\u2026" });
  const raw = data.rows || [];
  if (!raw.length) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "no open positions \u2014 funding exposure is live-position-based" });
  const rows = raw.map((r) => ({ ...r, _k: `${r.ticker}\xB7${r.direction}` }));
  const sgn = (r, v) => r.adverse ? -v : v;
  const tot8h = rows.reduce((s, r) => s + sgn(r, r.per_8h || 0), 0);
  const totDay = rows.reduce((s, r) => s + sgn(r, r.per_day || 0), 0);
  const money = (v, d = 4) => /* @__PURE__ */ React.createElement("span", { style: { color: v >= 0 ? "var(--qe-green)" : "var(--qe-red)" } }, v >= 0 ? "+" : "-", "$", Math.abs(v).toFixed(d));
  return /* @__PURE__ */ React.createElement("div", { style: { padding: 4, height: "100%" } }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Funding Rate Exposure \xB7 Live",
      right: err ? /* @__PURE__ */ React.createElement(StatusDot, { tone: "warn", label: "STALE \u2014 retrying" }) : /* @__PURE__ */ React.createElement(StatusDot, { tone: "info", label: "30s refresh" }),
      style: { height: "100%" },
      bodyStyle: { padding: 0 },
      foot
    },
    /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "_k",
        dense: false,
        columns: [
          { key: "ticker", label: "SYMBOL", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.ticker) },
          { key: "direction", label: "DIR", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.direction === "LONG" ? "ok" : "err" }, r.direction) },
          { key: "notional", label: "NOTIONAL", align: "right", cell: "dim", render: (r) => `$${(r.notional || 0).toLocaleString(void 0, { maximumFractionDigits: 0 })}` },
          { key: "funding_rate", label: "FUNDING RATE", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: r.adverse ? "var(--qe-red)" : "var(--qe-green)" } }, ((r.funding_rate || 0) * 100).toFixed(4), "%") },
          {
            key: "per_8h",
            label: "PER 8h",
            align: "right",
            sortVal: (r) => sgn(r, r.per_8h || 0),
            render: (r) => money(sgn(r, r.per_8h || 0))
          },
          {
            key: "per_day",
            label: "PER DAY",
            align: "right",
            sortVal: (r) => sgn(r, r.per_day || 0),
            render: (r) => money(sgn(r, r.per_day || 0), 3)
          },
          {
            key: "per_week",
            label: "PER WEEK",
            align: "right",
            cell: "dim",
            sortVal: (r) => sgn(r, r.per_week || 0),
            render: (r) => money(sgn(r, r.per_week || 0), 2)
          },
          { key: "next_funding", label: "NEXT FUNDING", cell: "dim" },
          // 'impact' is not a row field — the endpoint emits `adverse`. The
          // column therefore never sorted and never faceted, which is why this
          // pane showed no dropdown at all.
          {
            key: "impact",
            label: "IMPACT",
            filter: true,
            filterVal: (r) => r.adverse ? "PAY" : "EARN",
            sortVal: (r) => r.adverse ? "PAY" : "EARN",
            render: (r) => r.adverse ? /* @__PURE__ */ React.createElement(Badge, { tone: "err" }, "PAY") : /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "EARN")
          }
        ],
        rows,
        summary: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u03A3 NET EXPOSURE"), /* @__PURE__ */ React.createElement("span", { style: { color: tot8h >= 0 ? "var(--qe-green)" : "var(--qe-red)", fontWeight: 700 } }, "per 8h ", tot8h >= 0 ? "+" : "-", "$", Math.abs(tot8h).toFixed(4), " \xB7 per day ", totDay >= 0 ? "+" : "-", "$", Math.abs(totDay).toFixed(3)))
      }
    ),
    /* @__PURE__ */ React.createElement("div", { style: { padding: "4px 8px", borderTop: "1px solid var(--qe-line)", fontSize: "0.56rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "Binance settles funding every 8h (00:00 \xB7 08:00 \xB7 16:00 UTC). LONG pays when rate > 0; SHORT pays when rate < 0.")
  ));
};
const AnaTabBeta = () => {
  const { data, err, foot } = useAnaJson("/fragments/analytics/beta?format=json", 6e4);
  if (!data) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "loading beta\u2026" });
  const raw = data.rows || [];
  if (!raw.length) return /* @__PURE__ */ React.createElement(AnaEmpty, { err, msg: "no open positions \u2014 beta exposure is live-position-based" });
  const rows = raw.map((r) => ({ ...r, _k: `${r.ticker}\xB7${r.direction}` }));
  const sectors = Object.entries(data.sector_totals || {});
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 14, h: 13, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Beta-Weighted Exposure vs BTC",
      count: rows.length,
      right: /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "\u03B2 from 30d OHLCV \xB7 sector preset fallback \xB7 unsigned notional"),
      style: { height: "100%" },
      bodyStyle: { padding: 0 },
      foot
    },
    /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "_k",
        dense: false,
        columns: [
          { key: "ticker", label: "SYMBOL", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.ticker) },
          { key: "direction", label: "DIR", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.direction === "LONG" ? "ok" : "err" }, r.direction) },
          { key: "sector", label: "SECTOR", cell: "dim" },
          { key: "notional", label: "NOTIONAL", align: "right", render: (r) => `$${(r.notional || 0).toLocaleString(void 0, { maximumFractionDigits: 0 })}` },
          { key: "beta", label: "\u03B2 vs BTC", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: r.beta > 1.5 ? "var(--qe-amber)" : r.beta <= 1 ? "var(--qe-green)" : "var(--qe-text)" } }, (r.beta || 0).toFixed(2)) },
          { key: "beta_adj_exp", label: "\u03B2-ADJ. EXP.", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700 } }, "$", (r.beta_adj_exp || 0).toLocaleString(void 0, { maximumFractionDigits: 0 })) }
        ],
        rows,
        summary: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "PORTFOLIO TOTAL"), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)", fontWeight: 700 } }, "$", (data.total_notional || 0).toLocaleString(void 0, { maximumFractionDigits: 0 }))), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700 } }, "\u03B2 = ", /* @__PURE__ */ React.createElement("span", { style: { color: Math.abs(data.port_beta || 0) > 1.5 ? "var(--qe-amber)" : "var(--qe-text)" } }, (data.port_beta || 0).toFixed(2)), " \xB7 \u03B2-adj. $", (data.total_beta_exp || 0).toLocaleString(void 0, { maximumFractionDigits: 0 })))
      }
    )
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 14, y: 0, w: 10, h: 7, minW: 6, minH: 4 }, /* @__PURE__ */ React.createElement(Pane, { title: "Sector \u03B2-Adjusted Breakdown", style: { height: "100%" }, foot }, sectors.length ? /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, sectors.map(([sec, exp]) => {
    const pct = data.total_beta_exp ? Math.abs(exp / data.total_beta_exp * 100) : 0;
    return /* @__PURE__ */ React.createElement("div", { key: sec, style: { padding: 6, background: "var(--qe-panel)", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(Lbl, null, sec), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.86rem", fontWeight: 700, color: "var(--qe-text)" } }, "$", (+exp).toLocaleString(void 0, { maximumFractionDigits: 0 })), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, pct.toFixed(1), "%"));
  })) : /* @__PURE__ */ React.createElement(EmptyState, { fill: true, msg: "no sector data" }))), /* @__PURE__ */ React.createElement(GridItem, { x: 14, y: 7, w: 10, h: 6, minW: 6, minH: 4 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Sector Preset Betas \xB7 Fallback",
      style: { height: "100%" },
      foot: { tone: "sub", msg: "ok \xB7 local \u2014 compiled presets" }
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4, fontSize: "0.62rem", fontFamily: "var(--qe-mono)" } }, [["big_two_crypto", "1.0"], ["top_twenty_alts", "1.5"], ["commodities", "0.4"], ["other_alts", "2.0"]].map(([s, v]) => /* @__PURE__ */ React.createElement("div", { key: s, style: { display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px dotted var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, s), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)", fontWeight: 700 } }, v)))),
    /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", color: "var(--qe-muted)", marginTop: 6 } }, "used when <10 aligned daily returns exist for the empirical 30d \u03B2.")
  )));
};
const AnalyticsPage = () => {
  const [tab, setTab] = React.useState("overview");
  const [period, setPeriod] = React.useState("monthly");
  const [offset, setOffset] = React.useState(0);
  const [srvLabel, setSrvLabel] = React.useState("");
  const periodEnabled = ANA_PERIOD_TABS.has(tab);
  const onLabel = React.useCallback((l) => setSrvLabel(l), []);
  const setP = (p) => {
    setPeriod(p);
    setOffset(0);
    setSrvLabel("");
  };
  const nav = (d) => {
    setOffset((o) => o + d);
    setSrvLabel("");
  };
  const common = { period, offset, onLabel };
  const tabContent = {
    overview: /* @__PURE__ */ React.createElement(AnaTabOverview, { ...common }),
    equity: /* @__PURE__ */ React.createElement(AnaTabEquity, null),
    dist: /* @__PURE__ */ React.createElement(AnaTabDistributions, { ...common }),
    calendar: /* @__PURE__ */ React.createElement(AnaTabCalendar, null),
    pairs: /* @__PURE__ */ React.createElement(AnaTabPairs, { ...common }),
    excursions: /* @__PURE__ */ React.createElement(AnaTabExcursions, { ...common }),
    rmultiples: /* @__PURE__ */ React.createElement(AnaTabRMultiples, { ...common }),
    risk: /* @__PURE__ */ React.createElement(AnaTabRisk, { ...common }),
    execution: /* @__PURE__ */ React.createElement(AnaTabExecution, null),
    funding: /* @__PURE__ */ React.createElement(AnaTabFunding, null),
    beta: /* @__PURE__ */ React.createElement(AnaTabBeta, null)
  };
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "05 Analytics", style: {
    width: "100%",
    height: "100%",
    background: "var(--qe-bg)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden"
  } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "Analytics", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "Analytics", subtitle: "portfolio performance \xB7 equity curve \xB7 distributions \xB7 execution \xB7 funding \xB7 beta" }, /* @__PURE__ */ React.createElement(AnaPeriodNav, { period, offset, onPeriod: setP, onNav: nav, disabled: !periodEnabled, label: srvLabel })), /* @__PURE__ */ React.createElement(TabStrip, { value: tab, onChange: setTab, tabs: ANA_TABS.map(([id, l]) => [id, l]) }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column" } }, tabContent[tab]), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
Object.assign(window, { AnalyticsPage });

;

/* ==== pages-regime.jsx ==== */
const REGIME_KEYS = ["risk_on_trending", "risk_on_choppy", "neutral", "risk_off_defensive", "risk_off_panic"];
const REGIME_INFO = {
  risk_on_trending: { label: "Risk-On Trending", short: "TREND", tone: "trend", color: "var(--qe-green)", bg: "color-mix(in srgb, var(--qe-green) 10%, transparent)" },
  risk_on_choppy: { label: "Risk-On Choppy", short: "CHOP", tone: "chop", color: "var(--qe-cyan)", bg: "color-mix(in srgb, var(--qe-cyan) 10%, transparent)" },
  neutral: { label: "Neutral", short: "NEUT", tone: "neut", color: "var(--qe-sub)", bg: "color-mix(in srgb, var(--qe-sub) 6%, transparent)" },
  risk_off_defensive: { label: "Risk-Off Defensive", short: "DEF", tone: "def", color: "var(--qe-amber)", bg: "color-mix(in srgb, var(--qe-amber) 10%, transparent)" },
  risk_off_panic: { label: "Risk-Off Panic", short: "PANIC", tone: "panic", color: "var(--qe-red)", bg: "color-mix(in srgb, var(--qe-red) 10%, transparent)" }
};
const REGIME_THEME_KEY = {
  risk_on_trending: "green",
  risk_on_choppy: "cyan",
  neutral: "muted",
  risk_off_defensive: "amber",
  risk_off_panic: "red"
};
const REGIME_HEX = Object.fromEntries(
  REGIME_KEYS.map((k) => [k, QE_ECHARTS_THEME[REGIME_THEME_KEY[k]]])
);
const _rgMult = (mults, key) => mults && mults[key] != null ? `${mults[key]}\xD7` : "\u2014";
const _rgFromDate = (days) => {
  if (!days) return "";
  const d = new Date(Date.now() - days * 864e5);
  return d.toISOString().slice(0, 10);
};
const _rgRel = (iso, nowMs) => {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "\u2014";
  const diff = Math.max(0, Math.floor((nowMs - t) / 1e3));
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};
const _rgThr = (v, c, l) => v == null ? null : { v, c, l };
const RG_SIGNALS = [
  {
    key: "vix_close",
    label: "VIX",
    unit: "",
    color: "var(--qe-red)",
    decimals: 1,
    thr: (t) => [_rgThr(t.vix_panic, "var(--qe-red)", "Panic"), _rgThr(t.vix_defensive, "var(--qe-amber)", "Def"), _rgThr(t.vix_risk_on, "var(--qe-green)", "Risk-On")]
  },
  { key: "us10y_yield", label: "US 10Y Yield", unit: "%", color: "var(--qe-blue)", decimals: 2, thr: () => [] },
  {
    key: "hy_spread",
    label: "HY Spread",
    unit: "%",
    color: "var(--qe-amber)",
    decimals: 2,
    thr: (t) => [_rgThr(t.hy_spread_panic, "var(--qe-red)", "Panic"), _rgThr(t.hy_spread_defensive, "var(--qe-amber)", "Def"), _rgThr(t.hy_spread_risk_on, "var(--qe-green)", "Risk-On")]
  },
  {
    key: "btc_rvol_ratio",
    label: "BTC RVol (30d/7d)",
    unit: "",
    color: "var(--qe-purple)",
    decimals: 2,
    thr: (t) => [_rgThr(t.rvol_ratio_choppy, "var(--qe-amber)", "Chop"), _rgThr(t.rvol_ratio_trending, "var(--qe-green)", "Trend")]
  },
  {
    key: "agg_oi_change",
    label: "Aggregate OI Change",
    unit: "%",
    color: "var(--qe-green)",
    decimals: 2,
    thr: () => [{ v: 0, c: "var(--qe-muted)", l: "Zero" }]
  },
  {
    key: "avg_funding",
    label: "Avg Funding Rate",
    unit: "",
    color: "var(--qe-cyan)",
    decimals: 5,
    thr: (t) => [{ v: 0, c: "var(--qe-muted)", l: "Zero" }, _rgThr(t.funding_panic, "var(--qe-red)", "Panic")]
  }
];
const _rgSigThr = (sig, thresholds) => thresholds ? sig.thr(thresholds).filter(Boolean) : [];
const RG_THRESHOLD_LABELS = {
  vix_panic: "VIX Panic",
  vix_defensive: "VIX Defensive",
  vix_risk_on: "VIX Risk-On",
  vix_choppy: "VIX Choppy",
  hy_spread_panic: "HY Spread Panic",
  hy_spread_defensive: "HY Spread Defensive",
  hy_spread_neutral: "HY Spread Neutral",
  hy_spread_risk_on: "HY Spread Risk-On",
  rvol_ratio_choppy: "RVol Choppy",
  rvol_ratio_trending: "RVol Trending",
  funding_panic: "Funding Panic",
  btc_dom_change_bull: "BTC Dom Bull",
  btc_dom_change_bear: "BTC Dom Bear"
};
const _rgPost = async (url, body) => {
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: body != null ? { "Content-Type": "application/json" } : {},
      body: body != null ? JSON.stringify(body) : void 0
    });
    let data = null;
    try {
      data = await r.json();
    } catch (e) {
    }
    return { ok: r.ok, status: r.status, data };
  } catch (e) {
    return { ok: false, status: 0, data: null };
  }
};
const _regimeSegs = (data) => {
  const segs = [];
  let cur = { label: data[0].label, start: 0, days: 1 };
  for (let i = 1; i < data.length; i++) {
    if (data[i].label === cur.label) cur.days++;
    else {
      segs.push(cur);
      cur = { label: data[i].label, start: i, days: 1 };
    }
  }
  segs.push(cur);
  return segs;
};
const _fmtDay = (data, i) => data[i] && data[i].date ? data[i].date : `#${i}`;
const TimelineSvg = ({ data, style = "swim" }) => {
  const ref = React.useRef(null);
  const empty = !data || !data.length;
  const n = empty ? 0 : data.length;
  const { opts, height } = React.useMemo(() => {
    if (empty) return { opts: null, height: 120 };
    const muted = QE_ECHARTS_THEME.muted, sub = QE_ECHARTS_THEME.sub, line = QE_ECHARTS_THEME.line;
    const segs = _regimeSegs(data);
    const tip = {
      trigger: "item",
      backgroundColor: QE_ECHARTS_THEME.bg,
      borderColor: QE_ECHARTS_THEME.cyan,
      borderWidth: 1,
      padding: [4, 8],
      textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: "JetBrains Mono, monospace" },
      formatter: (p) => p.data && p.data._meta ? p.data._meta : ""
    };
    const infoOf = (l) => REGIME_INFO[l] || { label: l, short: String(l).slice(0, 5).toUpperCase(), color: "var(--qe-sub)" };
    const hexOf = (l) => REGIME_HEX[l] || QE_ECHARTS_THEME.sub;
    if (style === "swim") {
      const lanes = REGIME_KEYS;
      const bgItems = lanes.map((r, li) => ({ value: [0, n, li], itemStyle: { color: REGIME_HEX[r], opacity: 0.07 } }));
      const segItems = segs.filter((s) => lanes.indexOf(s.label) >= 0).map((s) => ({
        value: [s.start, s.start + s.days, lanes.indexOf(s.label)],
        itemStyle: { color: hexOf(s.label), opacity: 0.92 },
        _meta: `${infoOf(s.label).label} \xB7 ${s.days}d \xB7 ${_fmtDay(data, s.start)} \u2192 ${_fmtDay(data, Math.min(s.start + s.days - 1, n - 1))}`
      }));
      const swimRect = (frac) => (params, api) => {
        const x0 = api.coord([api.value(0), api.value(2)]);
        const x1 = api.coord([api.value(1), api.value(2)]);
        const bandH = api.size([0, 1])[1];
        const h = Math.max(bandH * frac, 2);
        return { type: "rect", shape: { x: x0[0], y: x0[1] - h / 2, width: Math.max(x1[0] - x0[0], 1), height: h }, style: api.style() };
      };
      return {
        height: lanes.length * 18 + 12,
        opts: {
          backgroundColor: "transparent",
          animation: false,
          grid: { left: 54, right: 10, top: 6, bottom: 6 },
          tooltip: tip,
          xAxis: { type: "value", min: 0, max: n, show: false },
          yAxis: {
            type: "category",
            inverse: true,
            data: lanes.map((r) => REGIME_INFO[r].short),
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { show: false },
            axisLabel: { color: (val, idx) => REGIME_HEX[lanes[idx]], fontSize: 9, fontWeight: 700, fontFamily: "JetBrains Mono, monospace" }
          },
          series: [
            { type: "custom", silent: true, z: 1, renderItem: swimRect(0.86), encode: { x: [0, 1], y: 2 }, data: bgItems },
            { type: "custom", z: 2, renderItem: swimRect(0.86), encode: { x: [0, 1], y: 2 }, data: segItems }
          ]
        }
      };
    }
    if (style === "bars") {
      const items = data.map((d, i) => ({
        value: [i, i + 1, 0],
        itemStyle: { color: hexOf(d.label), opacity: 0.92 },
        _meta: `${infoOf(d.label).label} \xB7 ${d.date || "#" + i}`
      }));
      return {
        height: 56,
        opts: {
          backgroundColor: "transparent",
          animation: false,
          grid: { left: 10, right: 10, top: 8, bottom: 8 },
          tooltip: tip,
          xAxis: { type: "value", min: 0, max: n, show: false },
          yAxis: { type: "category", data: [""], show: false },
          series: [{
            type: "custom",
            renderItem: (params, api) => {
              const x0 = api.coord([api.value(0), 0]);
              const x1 = api.coord([api.value(1), 0]);
              const bandH = api.size([0, 1])[1];
              return { type: "rect", shape: { x: x0[0], y: x0[1] - bandH * 0.42, width: Math.max(x1[0] - x0[0], 0.6), height: bandH * 0.84 }, style: api.style() };
            },
            encode: { x: [0, 1], y: 2 },
            data: items
          }]
        }
      };
    }
    if (style === "blocks") {
      const items = segs.map((s) => ({
        value: [s.start, s.start + s.days, 0],
        itemStyle: { color: hexOf(s.label), opacity: 0.9 },
        _label: s.days > 6 ? `${infoOf(s.label).short} ${s.days}d` : infoOf(s.label).short,
        _meta: `${infoOf(s.label).label} \xB7 ${s.days}d \xB7 ${_fmtDay(data, s.start)} \u2192 ${_fmtDay(data, Math.min(s.start + s.days - 1, n - 1))}`
      }));
      return {
        height: 52,
        opts: {
          backgroundColor: "transparent",
          animation: false,
          grid: { left: 10, right: 10, top: 8, bottom: 8 },
          tooltip: tip,
          xAxis: { type: "value", min: 0, max: n, show: false },
          yAxis: { type: "category", data: [""], show: false },
          series: [{
            type: "custom",
            renderItem: (params, api) => {
              const x0 = api.coord([api.value(0), 0]);
              const x1 = api.coord([api.value(1), 0]);
              const bandH = api.size([0, 1])[1];
              const w = Math.max(x1[0] - x0[0], 1);
              const rect = { type: "rect", shape: { x: x0[0] + 0.5, y: x0[1] - bandH * 0.45, width: Math.max(w - 1, 0.6), height: bandH * 0.9 }, style: api.style() };
              const lbl = params.data && params.data._label;
              if (w > 42 && lbl) {
                return { type: "group", children: [rect, {
                  type: "text",
                  style: {
                    text: lbl,
                    x: x0[0] + w / 2,
                    y: x0[1],
                    fill: QE_ECHARTS_THEME.bg,
                    opacity: 0.6,
                    font: "700 9px JetBrains Mono, monospace",
                    textAlign: "center",
                    textVerticalAlign: "middle"
                  }
                }] };
              }
              return rect;
            },
            encode: { x: [0, 1], y: 2 },
            data: items
          }]
        }
      };
    }
    if (style === "heat") {
      const cells = data.map((d) => [d.date, REGIME_KEYS.indexOf(d.label)]);
      return {
        height: 132,
        opts: {
          backgroundColor: "transparent",
          animation: false,
          tooltip: { ...tip, formatter: (p) => {
            const k = REGIME_KEYS[p.data[1]];
            return `${p.data[0]}
${(REGIME_INFO[k] || {}).label || "\u2014"}`;
          } },
          visualMap: {
            show: false,
            type: "piecewise",
            dimension: 1,
            seriesIndex: 0,
            pieces: REGIME_KEYS.map((r, i) => ({ value: i, color: REGIME_HEX[r] }))
          },
          calendar: {
            top: 24,
            left: 34,
            right: 10,
            bottom: 6,
            cellSize: ["auto", 15],
            range: [data[0].date, data[n - 1].date],
            orient: "horizontal",
            itemStyle: { color: QE_ECHARTS_THEME.bg, borderColor: QE_ECHARTS_THEME.bg, borderWidth: 1.5 },
            dayLabel: { color: muted, fontSize: 8, fontFamily: "JetBrains Mono, monospace", firstDay: 1 },
            monthLabel: { color: sub, fontSize: 9, fontFamily: "JetBrains Mono, monospace" },
            yearLabel: { show: false },
            splitLine: { lineStyle: { color: line, width: 1 } }
          },
          series: [{
            type: "heatmap",
            coordinateSystem: "calendar",
            data: cells,
            itemStyle: { borderColor: QE_ECHARTS_THEME.bg, borderWidth: 1.5 }
          }]
        }
      };
    }
    const WIN = 14, step = Math.max(1, Math.floor(n / 200));
    const buckets = [], labels = [];
    for (let bi = WIN; bi <= n; bi += step) {
      const slice = data.slice(bi - WIN, bi);
      const c = {};
      REGIME_KEYS.forEach((r) => {
        c[r] = 0;
      });
      slice.forEach((d) => {
        if (c[d.label] != null) c[d.label]++;
      });
      buckets.push(c);
      labels.push(_fmtDay(data, bi - 1));
    }
    const series = REGIME_KEYS.map((r) => ({
      name: REGIME_INFO[r].short,
      type: "line",
      stack: "comp",
      smooth: 0.2,
      symbol: "none",
      lineStyle: { width: 0 },
      areaStyle: { color: REGIME_HEX[r], opacity: 0.85 },
      emphasis: { focus: "series" },
      data: buckets.map((b) => +(b[r] / WIN * 100).toFixed(1))
    }));
    return {
      height: 130,
      opts: {
        backgroundColor: "transparent",
        animation: false,
        grid: { left: 38, right: 10, top: 10, bottom: 20 },
        tooltip: {
          trigger: "axis",
          backgroundColor: QE_ECHARTS_THEME.bg,
          borderColor: QE_ECHARTS_THEME.cyan,
          borderWidth: 1,
          padding: [6, 9],
          textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: "JetBrains Mono, monospace" },
          axisPointer: { type: "line", lineStyle: { color: QE_ECHARTS_THEME.cyan, opacity: 0.4 } },
          formatter: (ps) => {
            const head = ps[0] ? ps[0].axisValue : "";
            const rows = ps.filter((p) => p.value > 0).reverse().map((p) => `${p.marker} ${p.seriesName} ${p.value.toFixed(0)}%`).join("<br/>");
            return `${head}<br/>${rows}`;
          }
        },
        xAxis: {
          type: "category",
          boundaryGap: false,
          data: labels,
          ..._axis({ axisLabel: {
            color: muted,
            fontSize: 9,
            fontFamily: "JetBrains Mono, monospace",
            interval: Math.ceil(labels.length / 6)
          }, splitLine: { show: false } })
        },
        yAxis: {
          type: "value",
          min: 0,
          max: 100,
          ..._axis({
            axisLabel: { color: muted, fontSize: 9, fontFamily: "JetBrains Mono, monospace", formatter: (v) => v + "%" },
            splitLine: { lineStyle: { color: QE_ECHARTS_THEME.faint, opacity: 0.4, type: [2, 3] } }
          })
        },
        series
      }
    };
  }, [data, style, empty, n]);
  useECharts(ref, opts, [opts]);
  if (empty) {
    return /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        tone: "info",
        glyph: "\u3007",
        msg: "No regime data yet",
        cta: /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.6rem", color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "use Backfill tab to fetch macro signals")
      }
    );
  }
  const showTimeAxis = style === "swim" || style === "bars" || style === "blocks";
  const padL = style === "swim" ? 54 : 10;
  const ticks = (() => {
    if (!showTimeAxis) return [];
    const fmt = (s) => typeof s === "string" && s.length >= 10 ? s.slice(5) : s;
    const idxs = [0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(t * (n - 1)));
    return [...new Set(idxs)].map((i) => fmt(_fmtDay(data, i)));
  })();
  return /* @__PURE__ */ React.createElement("div", { style: { width: "100%" } }, /* @__PURE__ */ React.createElement("div", { ref, style: { width: "100%", height } }), showTimeAxis && ticks.length > 1 && /* @__PURE__ */ React.createElement("div", { style: {
    display: "flex",
    justifyContent: "space-between",
    paddingLeft: padL,
    paddingRight: 10,
    marginTop: 2,
    fontFamily: "var(--qe-mono)",
    fontSize: "0.52rem",
    color: "var(--qe-muted)",
    letterSpacing: "0.02em"
  } }, ticks.map((t, i) => /* @__PURE__ */ React.createElement("span", { key: i }, t))));
};
const RegimeLegend = () => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 14, flexWrap: "wrap", fontFamily: "var(--qe-mono)" } }, REGIME_KEYS.map((r) => /* @__PURE__ */ React.createElement("span", { key: r, style: { display: "inline-flex", alignItems: "center", gap: 4, fontSize: "0.58rem" } }, /* @__PURE__ */ React.createElement("span", { style: { width: 8, height: 8, background: REGIME_HEX[r], display: "inline-block" } }), /* @__PURE__ */ React.createElement("span", { style: { color: REGIME_HEX[r] } }, REGIME_INFO[r].label))));
const SignalChart = ({ data, color, thresholds = [], decimals = 2, unit = "", height = 84 }) => {
  const ref = React.useRef(null);
  const c = _qeResolveColor(color);
  const opts = React.useMemo(() => {
    const lo = Math.min(...data), hi = Math.max(...data);
    const pad = (hi - lo) * 0.6 || 1;
    const inBand = thresholds.filter((t) => t.v >= lo - pad && t.v <= hi + pad);
    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 42, right: 8, top: 8, bottom: 6 },
      tooltip: {
        trigger: "axis",
        backgroundColor: QE_ECHARTS_THEME.bg,
        borderColor: QE_ECHARTS_THEME.cyan,
        borderWidth: 1,
        padding: [3, 7],
        textStyle: { color: QE_ECHARTS_THEME.text, fontSize: 11, fontFamily: "JetBrains Mono, monospace" },
        axisPointer: { type: "line", lineStyle: { color: c, opacity: 0.5 } },
        formatter: (ps) => {
          const v = ps[0].value;
          return `${(+v).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${unit ? " " + unit : ""}`;
        }
      },
      xAxis: { type: "category", show: false, boundaryGap: false, data: data.map((_, i) => i) },
      yAxis: {
        type: "value",
        scale: true,
        ..._axis({
          axisLabel: {
            color: QE_ECHARTS_THEME.muted,
            fontSize: 8,
            fontFamily: "JetBrains Mono, monospace",
            formatter: (v) => (+v).toLocaleString("en-US", { maximumFractionDigits: decimals })
          },
          splitLine: { lineStyle: { color: QE_ECHARTS_THEME.faint, opacity: 0.35, type: [2, 3] } }
        })
      },
      series: [{
        type: "line",
        data,
        smooth: 0.18,
        symbol: "none",
        lineStyle: { color: c, width: 1.4 },
        areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [
          { offset: 0, color: c + "40" },
          { offset: 1, color: c + "00" }
        ] } },
        markLine: inBand.length ? {
          symbol: "none",
          silent: true,
          data: inBand.map((t) => ({
            yAxis: t.v,
            lineStyle: { color: _qeResolveColor(t.c), type: "dashed", width: 1, opacity: 0.8 },
            label: {
              show: true,
              position: "insideStartTop",
              formatter: t.l,
              color: _qeResolveColor(t.c),
              fontSize: 8,
              fontFamily: "JetBrains Mono, monospace"
            }
          }))
        } : void 0
      }]
    };
  }, [data, c, thresholds, decimals, unit]);
  useECharts(ref, opts, [opts]);
  return /* @__PURE__ */ React.createElement("div", { ref, style: { width: "100%", height } });
};
const SignalCard = ({ sig, globalSel, coverageRows, thresholds, onOverride, onGoBackfill }) => {
  const [range, setRange] = React.useState(globalSel.v);
  React.useEffect(() => {
    setRange(globalSel.v);
  }, [globalSel]);
  const from = _rgFromDate(range);
  const { data, err } = useAnaJson(
    `/api/regime/signals?signal_name=${encodeURIComponent(sig.key)}${from ? `&from_date=${from}` : ""}`
  );
  const covLoading = coverageRows == null;
  const covered = (coverageRows || []).some((c) => c.signal_name === sig.key && (c.count || 0) > 0);
  const series = React.useMemo(
    () => Array.isArray(data) ? data.map((d) => d.value).filter((v) => v != null) : null,
    [data]
  );
  const last = series && series.length ? series[series.length - 1] : null;
  const thr = React.useMemo(() => _rgSigThr(sig, thresholds), [sig, thresholds]);
  const pick = (v) => {
    setRange(v);
    onOverride();
  };
  return /* @__PURE__ */ React.createElement("div", { style: { background: "var(--qe-card)", border: "1px solid var(--qe-line)", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { width: 6, height: 6, background: sig.color, display: "inline-block" } }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.7rem", fontWeight: 600, color: "var(--qe-text)" } }, sig.label), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.74rem", color: "var(--qe-text)", fontWeight: 700, marginLeft: 4 } }, last != null ? last.toLocaleString("en-US", { minimumFractionDigits: sig.decimals, maximumFractionDigits: sig.decimals }) + (sig.unit ? " " + sig.unit : "") : ""), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "auto" } }, /* @__PURE__ */ React.createElement(PeriodSelector, { options: [[30, "30d"], [90, "90d"], [365, "1y"], [1825, "5y"], [0, "All"]], value: range, onChange: pick }))), series == null ? err ? /* @__PURE__ */ React.createElement(EmptyState, { tone: "warn", glyph: "\u26A0", msg: "signal fetch failed", hint: "engine unreachable?" }) : /* @__PURE__ */ React.createElement("div", { style: { height: 84, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--qe-muted)", fontSize: "0.6rem", fontFamily: "var(--qe-mono)" } }, "loading\u2026") : series.length === 0 ? covLoading ? /* @__PURE__ */ React.createElement("div", { style: { height: 84, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--qe-muted)", fontSize: "0.6rem", fontFamily: "var(--qe-mono)" } }, "loading\u2026") : covered ? /* @__PURE__ */ React.createElement(EmptyState, { tone: "info", glyph: "\u25C7", msg: "No data for range", hint: "widen the range" }) : /* @__PURE__ */ React.createElement(
    EmptyState,
    {
      tone: "warn",
      glyph: "\u2205",
      msg: "Not yet backfilled",
      cta: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: onGoBackfill }, "Use Backfill tab \u2192")
    }
  ) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(SignalChart, { data: series, color: sig.color, thresholds: thr, decimals: sig.decimals, unit: sig.unit, height: 84 }), thr.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 6, fontSize: "0.54rem", fontFamily: "var(--qe-mono)" } }, thr.map((t) => /* @__PURE__ */ React.createElement("span", { key: t.l, style: { display: "inline-flex", alignItems: "center", gap: 3, color: t.c } }, /* @__PURE__ */ React.createElement("span", { style: { width: 8, height: 0, borderTop: `1px dashed ${t.c}`, display: "inline-block" } }), t.l, " ", t.v, sig.unit && " " + sig.unit)))));
};
const RegimeTabOverview = ({ current, curFoot, mults, multsFoot, onGoBackfill }) => {
  const [tlStyle, setTlStyle] = React.useState("swim");
  const [tlRange, setTlRange] = React.useState(365);
  const [globalSel, setGlobalSel] = React.useState({ v: 365, n: 0 });
  const [globalActive, setGlobalActive] = React.useState(true);
  const [selChange, setSelChange] = React.useState(null);
  const tlFrom = _rgFromDate(tlRange);
  const { data: tlData, err: tlErr, foot: tlFoot } = useAnaJson(
    `/api/regime/timeline${tlFrom ? `?from_date=${tlFrom}` : ""}`
  );
  const { data: coverage, foot: covFoot } = useAnaJson("/api/regime/coverage");
  const { data: thresholds } = useAnaJson("/api/regime/thresholds");
  const timeline = Array.isArray(tlData) ? tlData : [];
  const counts = {};
  REGIME_KEYS.forEach((r) => {
    counts[r] = 0;
  });
  timeline.forEach((d) => {
    if (counts[d.label] != null) counts[d.label]++;
  });
  const total = timeline.length;
  const changes = React.useMemo(() => {
    const out = [];
    for (let i = 1; i < timeline.length; i++) {
      if (timeline[i].label !== timeline[i - 1].label) {
        out.push({ ...timeline[i], _prev: timeline[i - 1].label });
      }
    }
    return out.reverse().slice(0, 25);
  }, [timeline]);
  const curInfo = current && current.label ? REGIME_INFO[current.label] || REGIME_INFO.neutral : null;
  const sigOf = (row, k) => row.signals && row.signals[k] != null ? row.signals[k] : null;
  const fmtSig = (v, d = 2, suf = "") => v == null ? "\u2014" : (+v).toFixed(d) + suf;
  const t = thresholds || {};
  const vixColor = (v) => v == null ? "var(--qe-muted)" : t.vix_defensive != null && v >= t.vix_defensive ? "var(--qe-red)" : t.vix_risk_on != null && v >= t.vix_risk_on ? "var(--qe-amber)" : "var(--qe-text)";
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 6, h: 7, minW: 4, minH: 4 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Current Regime",
      hot: true,
      style: { height: "100%" },
      foot: curFoot
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: "8px 0" } }, curInfo ? /* @__PURE__ */ React.createElement(RegimeBadge, { tone: curInfo.tone, label: curInfo.label.toUpperCase() }) : /* @__PURE__ */ React.createElement(RegimeBadge, { tone: "neut", label: "NO DATA" }), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "1.8rem", fontWeight: 700, color: curInfo ? curInfo.color : "var(--qe-muted)", lineHeight: 1 } }, current && current.multiplier != null && current.source !== "none" ? `${current.multiplier}\xD7` : "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.56rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "sizing multiplier"), current && current.source === "live" && /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, current.mode, " \xB7 ", current.confidence, " confidence \xB7 ", current.stability_bars, "d stable"), current && current.source === "db" && /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "from stored labels \xB7 ", current.date || "\u2014"))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 6, y: 0, w: 12, h: 7, minW: 6, minH: 4 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Regime Distribution",
      tag: tlRange === 0 ? "ALL" : `${tlRange}d`,
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, total, " days observed"),
      foot: tlFoot
    },
    total === 0 ? /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        fill: true,
        tone: tlErr ? "warn" : "info",
        glyph: "\u3007",
        msg: tlErr ? "timeline fetch failed" : "no regime labels in window",
        hint: tlErr ? "engine unreachable?" : "run a backfill to classify history"
      }
    ) : /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 6 } }, REGIME_KEYS.map((r) => {
      const c = counts[r] || 0;
      const pct = total > 0 ? c / total * 100 : 0;
      const info = REGIME_INFO[r];
      return /* @__PURE__ */ React.createElement("div", { key: r, style: { padding: "6px 4px", background: info.bg, border: "1px solid color-mix(in srgb, " + info.color + " 27%, transparent)", textAlign: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.56rem", fontWeight: 700, color: info.color, letterSpacing: "0.08em" } }, info.short), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "1rem", fontWeight: 700, color: info.color } }, pct.toFixed(1), "%"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.52rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, c, "d"));
    }))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 18, y: 0, w: 6, h: 7, minW: 4, minH: 4 }, /* @__PURE__ */ React.createElement(Pane, { title: "Sizing Multipliers", style: { height: "100%" }, foot: multsFoot }, /* @__PURE__ */ React.createElement(FieldList, { rows: REGIME_KEYS.map((r) => {
    const info = REGIME_INFO[r];
    return {
      label: info.label.replace("Risk-On ", "").replace("Risk-Off ", ""),
      value: _rgMult(mults, r),
      color: info.color
    };
  }) }), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", marginTop: 6 } }, "applied to base size at calc time"))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 7, w: 24, h: 8, minW: 10, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Regime Timeline",
      tag: tlStyle.toUpperCase(),
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", letterSpacing: "0.08em", fontFamily: "var(--qe-mono)" } }, "STYLE"), /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["swim", "Swim"], ["bars", "Bars"], ["blocks", "Blocks"], ["heat", "Heat"], ["stack", "Stack"]], value: tlStyle, onChange: setTlStyle }), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2502"), /* @__PURE__ */ React.createElement(PeriodSelector, { options: [[30, "30d"], [90, "90d"], [365, "1y"], [0, "All"]], value: tlRange, onChange: setTlRange })),
      foot: tlFoot
    },
    timeline.length === 0 && tlErr ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "warn", glyph: "\u26A0", msg: "timeline fetch failed", hint: "engine unreachable?" }) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, /* @__PURE__ */ React.createElement(TimelineSvg, { data: timeline, style: tlStyle }), /* @__PURE__ */ React.createElement(RegimeLegend, null))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 15, w: 24, h: 10, minW: 10, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Macro Signals",
      count: RG_SIGNALS.length,
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
        "span",
        {
          style: { fontSize: "0.54rem", color: "var(--qe-muted)", letterSpacing: "0.08em", fontFamily: "var(--qe-mono)" },
          title: "cards inherit the All range until individually overridden; a per-card range clears the global highlight"
        },
        "ALL"
      ), /* @__PURE__ */ React.createElement(
        PeriodSelector,
        {
          options: [[30, "30d"], [90, "90d"], [365, "1y"], [1825, "5y"], [0, "All"]],
          value: globalActive ? globalSel.v : null,
          onChange: (v) => {
            setGlobalSel((s) => ({ v, n: s.n + 1 }));
            setGlobalActive(true);
          }
        }
      )),
      foot: covFoot
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 } }, RG_SIGNALS.map((sig) => /* @__PURE__ */ React.createElement(
      SignalCard,
      {
        key: sig.key,
        sig,
        globalSel,
        coverageRows: Array.isArray(coverage) ? coverage : null,
        thresholds,
        onOverride: () => setGlobalActive(false),
        onGoBackfill
      }
    )))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 25, w: 24, h: 10, minW: 10, minH: 5 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Recent Regime Changes",
      count: changes.length,
      style: { height: "100%" },
      bodyStyle: { padding: 0 },
      foot: tlFoot
    },
    /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "date",
        onClick: (r) => setSelChange((s) => s === r.date ? null : r.date),
        selected: selChange,
        columns: [
          { key: "date", label: "DATE", cell: "dim" },
          {
            key: "label",
            label: "REGIME",
            filter: true,
            filterVal: (r) => (REGIME_INFO[r.label] || REGIME_INFO.neutral).label,
            render: (r) => {
              const info = REGIME_INFO[r.label] || REGIME_INFO.neutral;
              return /* @__PURE__ */ React.createElement("span", { style: { color: info.color, fontWeight: 700 } }, info.label);
            }
          },
          { key: "mode", label: "MODE", cell: "dim", filter: true },
          // vix/hy/rvol/funding are NOT row fields — sigOf() reads the row's
          // signal map at render time, so every one of these headers sorted on
          // undefined. sortVal exposes the real number.
          {
            key: "vix",
            label: "VIX",
            align: "right",
            sortVal: (r) => sigOf(r, "vix_close"),
            render: (r) => {
              const v = sigOf(r, "vix_close");
              return /* @__PURE__ */ React.createElement("span", { style: { color: vixColor(v) } }, fmtSig(v, 1));
            }
          },
          {
            key: "hy",
            label: "HY SPREAD",
            align: "right",
            sortVal: (r) => sigOf(r, "hy_spread"),
            render: (r) => fmtSig(sigOf(r, "hy_spread"), 2, "%")
          },
          {
            key: "rvol",
            label: "RVOL",
            align: "right",
            sortVal: (r) => sigOf(r, "btc_rvol_ratio"),
            render: (r) => fmtSig(sigOf(r, "btc_rvol_ratio"), 2)
          },
          {
            key: "funding",
            label: "FUNDING",
            align: "right",
            sortVal: (r) => sigOf(r, "avg_funding"),
            render: (r) => {
              const v = sigOf(r, "avg_funding");
              return v == null ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : /* @__PURE__ */ React.createElement("span", { style: { color: v >= 0 ? "var(--qe-green)" : "var(--qe-red)" } }, (v * 100).toFixed(3), "%");
            }
          }
        ],
        rows: changes,
        emptyMsg: "no regime transitions in window"
      }
    ),
    selChange && (() => {
      const i = changes.findIndex((r) => r.date === selChange);
      const row = changes[i];
      if (!row) return null;
      const to = REGIME_INFO[row.label] || REGIME_INFO.neutral;
      const from = row._prev ? REGIME_INFO[row._prev] || REGIME_INFO.neutral : null;
      return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 14, padding: "5px 10px", borderTop: "1px solid var(--qe-line)", background: "var(--qe-panel)", fontFamily: "var(--qe-mono)", fontSize: "0.62rem", flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", letterSpacing: "0.1em", fontSize: "0.5rem", fontWeight: 700 } }, "SIGNAL CONTEXT"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, row.date), /* @__PURE__ */ React.createElement("span", null, from && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: from.color, fontWeight: 700 } }, from.short), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, " \u2192 ")), /* @__PURE__ */ React.createElement("span", { style: { color: to.color, fontWeight: 700 } }, to.short)), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "size ", from ? /* @__PURE__ */ React.createElement("span", { style: { color: from.color } }, _rgMult(mults, row._prev)) : "\u2014", " \u2192 ", /* @__PURE__ */ React.createElement("span", { style: { color: to.color, fontWeight: 700 } }, _rgMult(mults, row.label))), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "VIX ", /* @__PURE__ */ React.createElement("span", { style: { color: vixColor(sigOf(row, "vix_close")) } }, fmtSig(sigOf(row, "vix_close"), 1))), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "HY ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)" } }, fmtSig(sigOf(row, "hy_spread"), 2, "%"))), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "RVOL ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)" } }, fmtSig(sigOf(row, "btc_rvol_ratio"), 2))), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "FUND ", (() => {
        const v = sigOf(row, "avg_funding");
        return v == null ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : /* @__PURE__ */ React.createElement("span", { style: { color: v >= 0 ? "var(--qe-green)" : "var(--qe-red)" } }, (v * 100).toFixed(3), "%");
      })()), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: () => setSelChange(null) }, "\u2715"));
    })()
  )));
};
const RG_SIGNAL_SOURCE = {
  vix_close: "yfinance",
  us10y_yield: "FRED",
  hy_spread: "FRED",
  btc_rvol_ratio: "derived",
  agg_oi_change: "Binance",
  avg_funding: "Binance"
};
const RegimeTabBackfill = ({ job, onStart }) => {
  const [mode, setMode] = React.useState("macro_only");
  const [since, setSince] = React.useState("2020-01-01");
  const [until, setUntil] = React.useState(() => (/* @__PURE__ */ new Date()).toISOString().slice(0, 10));
  const { data: coverage, err: covErr, reload: reloadCoverage, foot: covFoot } = useAnaJson("/api/regime/coverage");
  const jobStatus = job && job.status;
  React.useEffect(() => {
    if (jobStatus === "completed") reloadCoverage();
  }, [jobStatus, reloadCoverage]);
  const running = job && (job.status === "running" || job.status === "starting");
  const results = job && job.results;
  const srvRows = Array.isArray(coverage) ? coverage : [];
  const covRows = srvRows.concat(
    RG_SIGNALS.filter((s) => !srvRows.some((r) => r.signal_name === s.key)).map((s) => ({
      signal_name: s.key,
      source: RG_SIGNAL_SOURCE[s.key] || "\u2014",
      min_date: null,
      max_date: null,
      count: 0
    }))
  );
  const labelOf = (key) => {
    const s = RG_SIGNALS.find((x) => x.key === key);
    return s ? s.label : key;
  };
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 8, h: 14, minW: 5, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Backfill Macro Data",
      style: { height: "100%" },
      foot: !job ? { tone: "ok", msg: "local" } : job.status === "starting" || job.status === "running" ? { tone: "sub", busy: true, msg: `backfill ${Math.round(job.pct || 0)}%` } : job.status === "failed" ? { tone: "err", msg: job.detail || "backfill failed" } : { tone: "ok", msg: "backfill completed" }
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, /* @__PURE__ */ React.createElement("p", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", lineHeight: 1.5, margin: 0 } }, "Macro Only fetches VIX (yfinance) + yields/spreads (FRED) + derives BTC RVol \u2014 works for deep history. Full additionally classifies with any existing Binance OI/funding rows; those crypto series are refreshed by the engine scheduler, not this fetch."), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "Mode"), /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", value: mode, onChange: (e) => setMode(e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "macro_only" }, "Macro Only \xB7 VIX \xB7 FRED \xB7 RVol"), /* @__PURE__ */ React.createElement("option", { value: "full" }, "Full \xB7 + existing OI / funding rows"))), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "From"), /* @__PURE__ */ React.createElement("input", { type: "date", className: "qe-input", value: since, onChange: (e) => setSince(e.target.value) })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "To"), /* @__PURE__ */ React.createElement("input", { type: "date", className: "qe-input", value: until, onChange: (e) => setUntil(e.target.value) }))), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "qe-btn qe-btn-primary qe-btn-lg",
        style: { width: "100%", justifyContent: "center" },
        disabled: running,
        onClick: () => onStart({ mode, since, until })
      },
      running ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.7rem" }) : "\u25B6 Start Backfill"
    ), job && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4, marginTop: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.6rem", fontFamily: "var(--qe-mono)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: job.status === "failed" ? "var(--qe-red)" : "var(--qe-sub)" } }, job.status === "failed" ? "Backfill failed \u2014 data unchanged" : job.detail || job.status), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, Math.round(job.pct || 0), "%")), job.status === "failed" && job.detail && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, job.detail), /* @__PURE__ */ React.createElement("div", { style: { height: 4, background: "var(--qe-panel)", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: `${Math.max(0, Math.min(100, job.pct || 0))}%`, height: "100%", background: job.status === "failed" ? "var(--qe-red)" : "var(--qe-cyan)" } })), job.status === "completed" && results && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.58rem", color: "var(--qe-green)", fontFamily: "var(--qe-mono)", lineHeight: 1.6 } }, "done \u2014 ", Object.entries(results).map(([k, v]) => `${k}: ${v}`).join(" \xB7 "))))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 8, y: 0, w: 16, h: 20, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Signal Coverage",
      count: covRows.length,
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: reloadCoverage }, "\u21BB"),
      bodyStyle: { padding: 0 },
      foot: covFoot
    },
    covErr && srvRows.length === 0 ? /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "warn", glyph: "\u26A0", msg: "coverage fetch failed", hint: "engine unreachable?" }) : /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "signal_name",
        columns: [
          { key: "signal_name", label: "SIGNAL", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: (r.count || 0) > 0 ? "var(--qe-text)" : "var(--qe-sub)", fontWeight: 600 } }, labelOf(r.signal_name)) },
          {
            key: "source",
            label: "SOURCE",
            cell: "dim",
            filter: true,
            filterVal: (r) => String(r.source || "\u2014").toUpperCase()
          },
          { key: "min_date", label: "FROM", cell: "dim", render: (r) => r.min_date || /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") },
          { key: "max_date", label: "TO", cell: "dim", render: (r) => r.max_date || /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") },
          { key: "count", label: "ROWS", align: "right", render: (r) => (r.count || 0) > 0 ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)", fontWeight: 700 } }, (+r.count).toLocaleString()) : /* @__PURE__ */ React.createElement(Badge, { tone: "warn" }, "NOT BACKFILLED") }
        ],
        rows: covRows
      }
    )
  )));
};
const NEWS_SRC_STYLE = {
  finnhub: { color: "var(--qe-blue)", background: "var(--qe-bg-blue)" },
  bwe: { color: "var(--qe-amber)", background: "var(--qe-bg-amber)" }
};
const IMPACT_STYLE = {
  high: { color: "var(--qe-red)", background: "var(--qe-bg-red)" },
  medium: { color: "var(--qe-amber)", background: "var(--qe-bg-amber)" }
};
const RG_DEFAULT_PILL = { color: "var(--qe-sub)", background: "var(--qe-panel)" };
const srcPill = (source) => NEWS_SRC_STYLE[source] || RG_DEFAULT_PILL;
const impactPill = (impact) => IMPACT_STYLE[impact] || RG_DEFAULT_PILL;
const NewsItem = ({ n, hero = false, expanded, onClick, nowMs }) => {
  const srcStyle = srcPill(n.source);
  const catStyle = RG_DEFAULT_PILL;
  const catLbl = n.category || "news";
  const relTime = _rgRel(n.published_at, nowMs);
  const tickers = (n.tickers || "").split(",").map((t) => t.trim()).filter(Boolean);
  const openLink = n.url ? /* @__PURE__ */ React.createElement(
    "a",
    {
      href: n.url,
      target: "_blank",
      rel: "noopener noreferrer",
      onClick: (e) => e.stopPropagation(),
      style: { fontSize: "0.56rem", color: "var(--qe-cyan)", fontFamily: "var(--qe-mono)", textDecoration: "none" }
    },
    "open \u2197"
  ) : null;
  if (hero) {
    return /* @__PURE__ */ React.createElement("div", { onClick, style: {
      background: "var(--qe-card)",
      border: `1px solid ${expanded ? "var(--qe-cyan)" : "var(--qe-line)"}`,
      padding: "12px 14px",
      cursor: "pointer"
    } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { ...srcStyle, padding: "1px 6px", fontSize: "0.56rem", fontWeight: 700, letterSpacing: "0.06em", fontFamily: "var(--qe-mono)" } }, (n.source || "?").toUpperCase()), /* @__PURE__ */ React.createElement(Badge, { tone: "info" }, "TOP STORY"), /* @__PURE__ */ React.createElement("span", { style: { ...catStyle, padding: "1px 6px", fontSize: "0.54rem", fontWeight: 700, fontFamily: "var(--qe-mono)" } }, catLbl.toUpperCase()), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "auto", fontSize: "0.58rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, relTime)), /* @__PURE__ */ React.createElement("h2", { style: { fontSize: "0.94rem", fontWeight: 800, color: "var(--qe-text)", lineHeight: 1.35, marginBottom: 6, fontFamily: "var(--qe-ui)", letterSpacing: "-0.01em" } }, n.headline), n.summary ? /* @__PURE__ */ React.createElement("p", { style: { fontSize: "0.7rem", color: "var(--qe-sub)", lineHeight: 1.6, margin: 0 } }, n.summary) : null, expanded && tickers.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 } }, tickers.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, style: { padding: "1px 6px", fontFamily: "var(--qe-mono)", fontSize: "0.56rem", background: "var(--qe-panel)", border: "1px solid var(--qe-line)", color: "var(--qe-sub)" } }, t))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, marginTop: 6, alignItems: "baseline" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, expanded ? "\u25B2 Collapse" : "\u25BC Expand"), expanded && openLink));
  }
  return /* @__PURE__ */ React.createElement("div", { onClick, style: {
    background: "var(--qe-card)",
    border: `1px solid ${expanded ? "var(--qe-cyan)" : "var(--qe-line)"}`,
    padding: expanded ? "10px 12px" : "6px 10px",
    cursor: "pointer"
  } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "flex-start", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { ...srcStyle, padding: "1px 5px", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.06em", fontFamily: "var(--qe-mono)", flexShrink: 0 } }, (n.source || "?").toUpperCase()), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: expanded ? "0.74rem" : "0.68rem", fontWeight: expanded ? 700 : 600, color: "var(--qe-text)", lineHeight: 1.4 } }, n.headline), expanded && n.summary ? /* @__PURE__ */ React.createElement("p", { style: { fontSize: "0.66rem", color: "var(--qe-sub)", lineHeight: 1.6, margin: "6px 0 0 0" } }, n.summary) : null, expanded && (tickers.length > 0 || openLink) && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6, alignItems: "baseline" } }, tickers.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, style: { padding: "1px 5px", fontFamily: "var(--qe-mono)", fontSize: "0.54rem", background: "var(--qe-panel)", border: "1px solid var(--qe-line)", color: "var(--qe-sub)" } }, t)), openLink)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3, flexShrink: 0 } }, /* @__PURE__ */ React.createElement("span", { style: { ...catStyle, padding: "1px 5px", fontSize: "0.5rem", fontWeight: 700, fontFamily: "var(--qe-mono)" } }, catLbl.toUpperCase()), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", whiteSpace: "nowrap" } }, relTime))));
};
const RegimeTabNews = () => {
  const [expanded, setExpanded] = React.useState(null);
  const [newsView, setNewsView] = React.useState("magazine");
  const [calFilter, setCalFilter] = React.useState("");
  const [refreshMsg, setRefreshMsg] = React.useState(null);
  const [, setTick] = React.useState(0);
  const [calUrl] = React.useState(() => {
    const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
    return `/api/calendar?from_date=${iso(Date.now() - 30 * 864e5)}&to_date=${iso(Date.now() + 30 * 864e5)}`;
  });
  const { data: feedData, err: feedErr, reload: reloadFeed, foot: feedFoot } = useAnaJson("/api/news/feed?limit=80", 15e3);
  const { data: calData, reload: reloadCal, foot: calFoot } = useAnaJson(calUrl, 6e4);
  React.useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 6e4);
    return () => clearInterval(t);
  }, []);
  const nowMs = Date.now();
  const news = Array.isArray(feedData) ? feedData : [];
  const calAll = Array.isArray(calData) ? calData : [];
  const cal = calFilter ? calAll.filter((e) => calFilter.split(",").includes(e.impact)) : calAll;
  const refresh = async () => {
    setRefreshMsg("refreshing\u2026");
    const r = await _rgPost("/api/news/refresh");
    if (r.ok && r.data) {
      setRefreshMsg(`+${r.data.news_added || 0} news \xB7 +${r.data.calendar_added || 0} events`);
      reloadFeed();
      reloadCal();
    } else {
      setRefreshMsg(r.status ? `refresh failed (HTTP ${r.status})` : "refresh failed \u2014 engine unreachable?");
    }
  };
  React.useEffect(() => {
    if (!refreshMsg || refreshMsg === "refreshing\u2026") return void 0;
    const t = setTimeout(() => setRefreshMsg(null), 6e3);
    return () => clearTimeout(t);
  }, [refreshMsg]);
  const nowRef = React.useRef(null);
  const calReady = cal.length > 0;
  React.useEffect(() => {
    if (nowRef.current) {
      try {
        nowRef.current.scrollIntoView({ block: "center" });
      } catch (e) {
      }
    }
  }, [calReady, calFilter]);
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 16, h: 24, minW: 8, minH: 8 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Market News",
      count: news.length,
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement(React.Fragment, null, refreshMsg && /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, refreshMsg), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: refresh }, "\u21BB"), /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["magazine", "Magazine"], ["detail", "Detail"]], value: newsView, onChange: setNewsView }), feedErr ? /* @__PURE__ */ React.createElement(StatusDot, { tone: "warn", label: "STALE \u2014 retrying" }) : /* @__PURE__ */ React.createElement(StatusDot, { tone: "info", label: "15s refresh" })),
      bodyStyle: { padding: newsView === "magazine" ? 6 : 0 },
      foot: feedFoot
    },
    news.length === 0 ? /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        fill: true,
        tone: feedErr ? "warn" : "info",
        glyph: "\u{1F4F0}",
        msg: feedErr ? "news fetch failed" : "no news items stored yet",
        hint: feedErr ? "engine unreachable?" : "press \u21BB to fetch from finnhub (needs an API key in Connections)"
      }
    ) : newsView === "magazine" ? /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4 } }, /* @__PURE__ */ React.createElement(
      NewsItem,
      {
        n: news[0],
        hero: true,
        nowMs,
        expanded: expanded === news[0].id,
        onClick: () => setExpanded(expanded === news[0].id ? null : news[0].id)
      }
    ), news.slice(1).map((n) => /* @__PURE__ */ React.createElement(
      NewsItem,
      {
        key: n.id,
        n,
        nowMs,
        expanded: expanded === n.id,
        onClick: () => setExpanded(expanded === n.id ? null : n.id)
      }
    ))) : /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "id",
        dense: true,
        onClick: (n) => {
          setNewsView("magazine");
          setExpanded(n.id);
        },
        columns: [
          { key: "published_at", label: "TIME", cell: "dim", render: (n) => _rgRel(n.published_at, nowMs) },
          {
            key: "source",
            label: "SRC",
            filter: true,
            filterVal: (n) => (n.source || "?").toUpperCase(),
            render: (n) => /* @__PURE__ */ React.createElement("span", { style: { ...srcPill(n.source), padding: "1px 5px", fontSize: "0.5rem", fontWeight: 700, fontFamily: "var(--qe-mono)", letterSpacing: "0.06em" } }, (n.source || "?").toUpperCase())
          },
          // The engine's news rows carry CATEGORY (not impact — see the
          // Magazine cards, which already render it). Surfacing it as a
          // column gives this pane a second, genuinely categorical facet.
          {
            key: "category",
            label: "CAT",
            cell: "dim",
            filter: true,
            filterVal: (n) => (n.category || "news").toUpperCase(),
            render: (n) => /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.52rem", color: "var(--qe-sub)", fontFamily: "var(--qe-mono)", letterSpacing: "0.05em" } }, (n.category || "news").toUpperCase())
          },
          { key: "headline", label: "HEADLINE", render: (n) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)", fontWeight: 600 } }, n.headline) },
          { key: "tickers", label: "TICKERS", cell: "dim", render: (n) => /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.56rem" } }, n.tickers || "\u2014") }
        ],
        rows: news
      }
    )
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 16, y: 0, w: 8, h: 24, minW: 6, minH: 8 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Economic Calendar",
      count: cal.length,
      style: { height: "100%" },
      tag: "NOW MARKER",
      right: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["", "All"], ["high", "High"], ["high,medium", "High+Med"]], value: calFilter, onChange: setCalFilter }), /* @__PURE__ */ React.createElement(LiveClock, { id: "regime-news-clock", style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } })),
      bodyStyle: { padding: 6 },
      foot: calFoot
    },
    cal.length === 0 ? /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        fill: true,
        tone: "info",
        glyph: "\u25EB",
        msg: "no calendar events stored",
        hint: "press \u21BB on Market News to fetch (finnhub)"
      }
    ) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4 } }, (() => {
      const out = [];
      let nowInserted = false;
      const marker = /* @__PURE__ */ React.createElement("div", { key: "now-marker", ref: nowRef, style: { display: "flex", alignItems: "center", gap: 6, padding: "4px 0" } }, /* @__PURE__ */ React.createElement("hr", { style: { flex: 1, border: "none", borderTop: "1px solid var(--qe-cyan)", opacity: 0.5 } }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", fontWeight: 700, color: "var(--qe-cyan)", letterSpacing: "0.12em", fontFamily: "var(--qe-mono)" } }, "\u25CF NOW"), /* @__PURE__ */ React.createElement("hr", { style: { flex: 1, border: "none", borderTop: "1px solid var(--qe-cyan)", opacity: 0.5 } }));
      cal.forEach((e, i) => {
        const evMs = Date.parse(e.event_time);
        if (!nowInserted && Number.isFinite(evMs) && evMs >= nowMs) {
          nowInserted = true;
          out.push(marker);
        }
        const isPast = Number.isFinite(evMs) && evMs < nowMs;
        const minsAway = Number.isFinite(evMs) ? Math.round((evMs - nowMs) / 6e4) : 0;
        const isNear = !isPast && Math.abs(minsAway) <= 240;
        const timeLbl = !Number.isFinite(evMs) ? "\u2014" : isPast ? minsAway < -60 ? `${Math.round(-minsAway / 60)}h ago` : `${-minsAway}m ago` : minsAway < 60 ? `in ${minsAway}m` : `in ${Math.round(minsAway / 60)}h`;
        const est = e.estimate, act = e.actual;
        const surprise = act != null && est != null && Math.abs(+est) > 0 ? Math.abs(act - est) / Math.abs(est) : 0;
        const actColor = act == null ? "var(--qe-sub)" : surprise > 0.1 ? act > est ? "var(--qe-green)" : "var(--qe-red)" : "var(--qe-text)";
        const fmtNum = (v) => v == null ? "\u2014" : Math.abs(+v) > 0 && Math.abs(+v) < 0.01 ? (+v).toExponential(1) : (+v).toFixed(2);
        const impactStyle = impactPill(e.impact);
        out.push(
          /* @__PURE__ */ React.createElement("div", { key: e.id != null ? e.id : i, style: {
            padding: "5px 7px",
            /* rgba amber near-wash — the tint carve-out (DESIGN.md §2) */
            background: isNear ? "rgba(255,174,0,0.06)" : "var(--qe-panel)",
            border: `1px solid ${isNear ? "color-mix(in srgb, var(--qe-amber) 50%, transparent)" : "var(--qe-line)"}`,
            opacity: isPast ? 0.55 : 1
          } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 3 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.58rem", color: isNear ? "var(--qe-amber)" : "var(--qe-muted)", fontWeight: 700 } }, timeLbl), /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", gap: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, e.country || "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { ...impactStyle, padding: "1px 4px", fontSize: "0.5rem", fontWeight: 700, fontFamily: "var(--qe-mono)" } }, e.impact === "medium" ? "MED" : (e.impact || "?").toUpperCase()))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.66rem", fontWeight: 600, color: isPast ? "var(--qe-sub)" : "var(--qe-text)", lineHeight: 1.3, marginBottom: 3 } }, e.event_name, e.unit ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)", fontSize: "0.56rem" } }, " (", e.unit, ")") : null), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, fontFamily: "var(--qe-mono)", fontSize: "0.58rem" } }, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "est "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, fmtNum(est))), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "act "), /* @__PURE__ */ React.createElement("span", { style: { color: actColor, fontWeight: 700 } }, fmtNum(act))), e.previous != null && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "prev "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, fmtNum(e.previous)))))
        );
      });
      if (!nowInserted) out.push(marker);
      return out;
    })())
  )));
};
const RegimeTabConfig = ({ mults }) => {
  const { data: thresholds, err: thrErr, foot: thrFoot } = useAnaJson("/api/regime/thresholds");
  const [reclass, setReclass] = React.useState(null);
  const reclassify = async () => {
    if (!window.confirm("Reclassify ALL dates? This recomputes every historical regime label from stored signals.")) return;
    setReclass({ busy: true });
    const r = await _rgPost("/api/regime/reclassify", {});
    if (r.ok && r.data) setReclass({ msg: `reclassified ${r.data.labels_classified} labels` });
    else setReclass({ err: r.status ? `failed (HTTP ${r.status})` : "failed \u2014 engine unreachable?" });
  };
  const t = thresholds || {};
  const V = ({ k }) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text)", fontWeight: 700 } }, t[k] != null ? t[k] : "\u2014");
  const rules = [
    {
      label: "Panic",
      key: "risk_off_panic",
      body: /* @__PURE__ */ React.createElement(React.Fragment, null, "VIX > ", /* @__PURE__ */ React.createElement(V, { k: "vix_panic" }), " AND (HY Spread > ", /* @__PURE__ */ React.createElement(V, { k: "hy_spread_defensive" }), " OR full-mode Funding < ", /* @__PURE__ */ React.createElement(V, { k: "funding_panic" }), ")")
    },
    {
      label: "Defensive",
      key: "risk_off_defensive",
      body: /* @__PURE__ */ React.createElement(React.Fragment, null, "VIX > ", /* @__PURE__ */ React.createElement(V, { k: "vix_defensive" }), " OR HY Spread > ", /* @__PURE__ */ React.createElement(V, { k: "hy_spread_defensive" }), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "(also VIX > ", /* @__PURE__ */ React.createElement(V, { k: "vix_panic" }), " when the panic second leg fails)"))
    },
    {
      label: "Trending",
      key: "risk_on_trending",
      body: /* @__PURE__ */ React.createElement(React.Fragment, null, "HY < ", /* @__PURE__ */ React.createElement(V, { k: "hy_spread_risk_on" }), " AND VIX < ", /* @__PURE__ */ React.createElement(V, { k: "vix_risk_on" }), " AND ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "[macro:"), " RVol < ", /* @__PURE__ */ React.createElement(V, { k: "rvol_ratio_trending" }), " ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\xB7 full: OI rising AND funding > 0]"))
    },
    {
      label: "Choppy",
      key: "risk_on_choppy",
      body: /* @__PURE__ */ React.createElement(React.Fragment, null, "HY < ", /* @__PURE__ */ React.createElement(V, { k: "hy_spread_risk_on" }), " AND VIX < ", /* @__PURE__ */ React.createElement(V, { k: "vix_choppy" }), " AND RVol > ", /* @__PURE__ */ React.createElement(V, { k: "rvol_ratio_choppy" }))
    },
    {
      label: "Neutral",
      key: "neutral",
      body: /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "default fallback; HY Spread \u2265 ", /* @__PURE__ */ React.createElement(V, { k: "hy_spread_neutral" }), " floors any risk-on day to neutral")
    }
  ];
  return /* @__PURE__ */ React.createElement(GridWorkspace, null, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 8, h: 18, minW: 5, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Classifier Thresholds",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", disabled: reclass && reclass.busy, onClick: reclassify }, reclass && reclass.busy ? /* @__PURE__ */ React.createElement(Spinner, { size: "0.62rem" }) : "\u21BB Reclassify all dates"),
      foot: thrFoot
    },
    /* @__PURE__ */ React.createElement("p", { style: { fontSize: "0.6rem", color: "var(--qe-sub)", margin: "0 0 6px 0", lineHeight: 1.5 } }, "Threshold values used by the rule-based classifier (config constants \u2014 read-only; reclassify recomputes historical labels from stored signals)."),
    reclass && reclass.msg && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.6rem", color: "var(--qe-green)", fontFamily: "var(--qe-mono)", marginBottom: 4 } }, reclass.msg),
    reclass && reclass.err && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.6rem", color: "var(--qe-red)", fontFamily: "var(--qe-mono)", marginBottom: 4 } }, reclass.err),
    thresholds == null ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.6rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, thrErr ? "thresholds fetch failed" : "loading\u2026") : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 1 } }, Object.entries(thresholds).map(([k, v]) => /* @__PURE__ */ React.createElement("div", { key: k, style: { display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "3px 6px", borderBottom: "1px dotted var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.62rem", color: "var(--qe-sub)" } }, RG_THRESHOLD_LABELS[k] || k), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.74rem", fontWeight: 700, color: "var(--qe-text)" } }, v)))),
    /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10 } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Sizing Multipliers"), /* @__PURE__ */ React.createElement(FieldList, { rows: REGIME_KEYS.map((r) => ({
      label: REGIME_INFO[r].short,
      value: _rgMult(mults, r),
      color: REGIME_INFO[r].color
    })), dense: true }))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 8, y: 0, w: 16, h: 18, minW: 8, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Decision Tree Rules",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "evaluated top\u2192bottom \xB7 first match wins"),
      foot: thrFoot
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, rules.map((rule) => {
      const info = REGIME_INFO[rule.key];
      return /* @__PURE__ */ React.createElement("div", { key: rule.key, style: {
        background: info.bg,
        border: "1px solid color-mix(in srgb, " + info.color + " 33%, transparent)",
        borderLeft: `3px solid ${info.color}`,
        padding: "7px 10px"
      } }, /* @__PURE__ */ React.createElement("span", { style: { color: info.color, fontWeight: 700, fontSize: "0.72rem", fontFamily: "var(--qe-mono)" } }, rule.label, ":"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontSize: "0.66rem", marginLeft: 6, fontFamily: "var(--qe-mono)" } }, rule.body));
    }))
  )));
};
const REGIME_TABS = [
  ["overview", "Overview"],
  ["backfill", "Backfill"],
  ["news", "News"],
  ["config", "Config"]
];
const RegimePage = () => {
  const [tab, setTab] = React.useState("overview");
  const { data: current, foot: curFoot } = useAnaJson("/api/regime/current", 6e4);
  const { data: mults, foot: multsFoot } = useAnaJson("/api/regime/multipliers");
  const [bfJob, setBfJob] = React.useState(null);
  const bfBusyRef = React.useRef(false);
  const startBackfill = React.useCallback(async ({ mode, since, until }) => {
    if (bfBusyRef.current) return;
    bfBusyRef.current = true;
    setBfJob({ id: null, status: "starting", pct: 0, detail: "" });
    const r = await _rgPost("/api/regime/backfill", { mode, since_date: since, until_date: until });
    if (!r.ok || !r.data || r.data.job_id == null) {
      bfBusyRef.current = false;
      setBfJob({
        id: null,
        status: "failed",
        pct: 0,
        detail: r.data && (r.data.error || r.data.detail) || (r.status ? `HTTP ${r.status}` : "engine unreachable")
      });
      return;
    }
    setBfJob({ id: r.data.job_id, status: "running", pct: 0, detail: "", fails: 0 });
  }, []);
  const bfId = bfJob && bfJob.id;
  const bfStatus = bfJob && bfJob.status;
  React.useEffect(() => {
    if (bfStatus !== "running" || bfId == null) {
      bfBusyRef.current = bfStatus === "starting";
      return void 0;
    }
    const t = setInterval(async () => {
      try {
        const s = await _ptJson(`/api/regime/backfill-status/${bfId}`);
        setBfJob((j) => j && j.id === bfId ? { ...j, ...s, id: bfId, fails: 0 } : j);
      } catch (e) {
        setBfJob((j) => {
          if (!j || j.id !== bfId) return j;
          const fails = (j.fails || 0) + 1;
          if (fails >= 4) return { ...j, status: "failed", fails, detail: "job lost \u2014 engine restarted?" };
          return { ...j, fails };
        });
      }
    }, 1500);
    return () => clearInterval(t);
  }, [bfId, bfStatus]);
  React.useEffect(() => {
    if (bfStatus === "completed" || bfStatus === "failed") bfBusyRef.current = false;
  }, [bfStatus]);
  const goBackfill = React.useCallback(() => setTab("backfill"), []);
  const content = {
    overview: /* @__PURE__ */ React.createElement(RegimeTabOverview, { current, curFoot, mults, multsFoot, onGoBackfill: goBackfill }),
    backfill: /* @__PURE__ */ React.createElement(RegimeTabBackfill, { job: bfJob, onStart: startBackfill }),
    news: /* @__PURE__ */ React.createElement(RegimeTabNews, null),
    config: /* @__PURE__ */ React.createElement(RegimeTabConfig, { mults })
  };
  const tabSubtitles = {
    overview: "current regime \xB7 distribution \xB7 timeline \xB7 macro signals \xB7 changes",
    backfill: "fetch historical macro signals \xB7 signal coverage",
    news: "finnhub + bwe streams \xB7 economic calendar",
    config: "classifier thresholds \xB7 decision tree rules"
  };
  const curInfo = current && current.label ? REGIME_INFO[current.label] || REGIME_INFO.neutral : null;
  const asOf = current ? current.source === "live" && current.computed_at ? String(current.computed_at).slice(0, 16).replace("T", " ") + " UTC" : current.source === "db" ? `${current.date || "\u2014"} (stored)` : null : null;
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "07 Regime", style: {
    width: "100%",
    height: "100%",
    background: "var(--qe-bg)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden"
  } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "Regime", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "Regime", subtitle: tabSubtitles[tab] }, curInfo ? /* @__PURE__ */ React.createElement(RegimeBadge, { tone: curInfo.tone, label: curInfo.label.toUpperCase() }) : /* @__PURE__ */ React.createElement(RegimeBadge, { tone: "neut", label: "NO DATA" }), current && current.multiplier != null && current.source !== "none" && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.6rem", color: "var(--qe-cyan)", fontWeight: 700 } }, current.multiplier, "\xD7 size"), asOf && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.54rem", color: "var(--qe-muted)" } }, "as of ", asOf)), /* @__PURE__ */ React.createElement(TabStrip, { value: tab, onChange: setTab, tabs: REGIME_TABS }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column" } }, content[tab]), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
Object.assign(window, { RegimePage });

;

/* ==== pages-models-data.jsx ==== */
const _mdlSend = async (url, method, body) => {
  let r;
  try {
    r = await fetch(url, {
      method,
      headers: body != null ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: body != null ? JSON.stringify(body) : void 0
    });
  } catch (e) {
    const err = new Error(url + " unreachable");
    err.status = 0;
    throw err;
  }
  let data = null;
  try {
    data = await r.json();
  } catch (e) {
    const err = new Error(url + " corrupt response");
    err.corrupt = true;
    throw err;
  }
  if (!r.ok || data && data.error) {
    const err = new Error(data && data.error || url + " " + r.status);
    err.status = r.status;
    throw err;
  }
  return data;
};
const _mdlUpload = async (url, formData) => {
  let r;
  try {
    r = await fetch(url, { method: "POST", body: formData, headers: { Accept: "application/json" } });
  } catch (e) {
    const err = new Error(url + " unreachable");
    err.status = 0;
    throw err;
  }
  let data = null;
  try {
    data = await r.json();
  } catch (e) {
    const err = new Error(url + " corrupt response");
    err.corrupt = true;
    throw err;
  }
  if (!r.ok || data && data.error) {
    const err = new Error(data && data.error || url + " " + r.status);
    err.status = r.status;
    throw err;
  }
  return data;
};
const _mdlMoney = (v, dp = 2) => (v >= 0 ? "+" : "\u2212") + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const _mdlPl = (v) => v > 0 ? "var(--qe-green)" : v < 0 ? "var(--qe-red)" : "var(--qe-sub)";
const _mdlDate = (iso) => iso ? String(iso).slice(0, 10) : "\u2014";
const _mdlDt = (iso) => iso ? String(iso).slice(0, 16).replace("T", " ") : "\u2014";
const _mdlMs = (ms) => ms ? new Date(ms).toISOString().slice(0, 16).replace("T", " ") : "\u2014";
const MDL_TYPES = [["macro", "Macro"], ["micro", "Micro"], ["both", "Both"]];
const mdlTypeLabel = (t) => ({ macro: "Macro", micro: "Micro", both: "Both" })[t] || t || "\u2014";
const mdlCellVal = (c) => {
  if (c == null) return null;
  if (typeof c !== "object") return c;
  if (c.t === "n") return typeof c.v === "number" ? c.v : null;
  return c.v != null ? c.v : null;
};
const mdlCellNum = (c) => {
  const v = mdlCellVal(c);
  return typeof v === "number" ? v : null;
};
const mdlCellIsPct = (c) => !!(c && typeof c === "object" && c.t === "n" && typeof c.f === "string" && c.f.indexOf("%") >= 0);
const mdlCellIsDt = (c) => !!(c && typeof c === "object" && c.t === "dt");
const mdlCellText = (c) => {
  if (mdlCellIsDt(c)) return _mdlDt(c.v);
  const v = mdlCellVal(c);
  return v == null ? "" : String(v);
};
const mdlSheet = (report, name) => {
  if (!report || !report.sheets) return null;
  const s = report.sheets.find((x) => x.name === name);
  return s && s.rows && s.rows.length ? s : null;
};
const mdlSections = (rows) => {
  const secs = [];
  let cur = null;
  const isEmptyRow = (r) => !r || !r.length || r.every((c) => {
    const v = mdlCellVal(c);
    return v == null || v === "";
  });
  for (const r of rows || []) {
    if (isEmptyRow(r)) {
      cur = null;
      continue;
    }
    const vals = r.map(mdlCellVal);
    const filled = [];
    vals.forEach((v, i) => {
      if (v != null && v !== "") filled.push(i);
    });
    if (filled.length === 1 && typeof vals[filled[0]] === "string" && r.length <= filled[0] + 1) {
      cur = { title: String(vals[filled[0]]), header: null, rows: [] };
      secs.push(cur);
      continue;
    }
    const headerish = (vals[0] == null || vals[0] === "") && filled.length >= 2 && filled.every((i) => typeof vals[i] === "string");
    if (headerish) {
      if (!cur) {
        cur = { title: null, header: null, rows: [] };
        secs.push(cur);
      }
      cur.header = vals.map((v) => v == null ? "" : String(v));
      continue;
    }
    if (!cur) {
      cur = { title: null, header: null, rows: [] };
      secs.push(cur);
    }
    cur.rows.push(r);
  }
  return secs.filter((s) => s.rows.length || s.title);
};
const mdlSectionWidth = (sec) => Math.max(1, ...sec.rows.map((r) => r.length));
const mdlFindRow = (rows, label) => {
  for (const r of rows || []) {
    if (r && typeof mdlCellVal(r[0]) === "string" && String(mdlCellVal(r[0])).trim() === label) return r;
  }
  return null;
};
const MDL_FMT = {
  "Profit Factor": "pf",
  "Adjusted Profit Factor": "pf",
  "Select Profit Factor": "pf",
  "Total # of Trades": "int",
  "Max # Contracts Held": "int",
  "Number Winning Trades": "int",
  "Number Losing Trades": "int",
  "Number of Outliers": "int",
  "Max Consec. Winners": "int",
  "Max Consec. Losers": "int",
  "% Profitable": "pct",
  "Return on Account": "pct",
  "Return on Initial Capital": "pct",
  "Annual Rate of Return": "pct",
  "Monthly Rate of Return": "pct",
  "Percent in the Market": "pct",
  "Return on Max Strategy Drawdown": "num",
  "Monthly Return StdDev": "num",
  "Sharpe Ratio": "num",
  "Annualized Sharpe Ratio": "num",
  "Sortino Ratio": "num",
  "Calmar Ratio": "num",
  "Sterling Ratio": "num",
  "RINA Index": "num",
  "Upside Potential Ratio": "num",
  "Fouse Ratio": "num",
  "Z-score": "num",
  "Confidence Limit": "num"
};
const mdlFmtFor = (label, cell) => {
  if (mdlCellIsPct(cell)) return "pct";
  const l = String(label || "").trim();
  if (MDL_FMT[l]) return MDL_FMT[l];
  if (/\(%\)$/.test(l)) return "pct";
  if (/^(#|Number|Avg #|Max #)/.test(l) || /# of/.test(l)) return "int";
  if (/Ratio|Index|Z-score|StdDev|Std\. Deviation|Deviation/i.test(l)) return "num";
  return "usd";
};
const mdlPairTrades = (sheet) => {
  if (!sheet) return null;
  const rows = sheet.rows;
  let headIdx = -1, head = null;
  for (let i = 0; i < rows.length; i++) {
    const cells = (rows[i] || []).map((c) => String(mdlCellVal(c) == null ? "" : mdlCellVal(c)).trim());
    if (cells.indexOf("Trade #") >= 0 && cells.indexOf("Type") >= 0) {
      headIdx = i;
      head = cells;
      break;
    }
  }
  if (headIdx < 0) return null;
  const col = {};
  head.forEach((name, i) => {
    if (name) col[name] = i;
  });
  const get = (r, name) => col[name] != null && col[name] < r.length ? r[col[name]] : null;
  const dtSplit = (c) => {
    if (mdlCellIsDt(c)) {
      const iso = String(c.v);
      return [iso.slice(0, 10), iso.slice(11, 19)];
    }
    const v = mdlCellVal(c);
    return [v == null ? "" : String(v), ""];
  };
  const trades = [];
  let pending = null;
  for (let i = headIdx + 1; i < rows.length; i++) {
    const r = rows[i] || [];
    const typ = String(mdlCellVal(get(r, "Type")) || "").trim();
    if (typ.indexOf("Entry") === 0) {
      const [d, t] = dtSplit(get(r, "Date") != null ? get(r, "Date") : get(r, "Time"));
      pending = {
        n: mdlCellNum(get(r, "Trade #")) || trades.length + 1,
        side: typ.indexOf("Long") >= 0 ? "L" : "S",
        entryType: typ,
        entrySignal: mdlCellText(get(r, "Signal")),
        entryOrder: mdlCellNum(get(r, "Order #")),
        entryDate: d,
        entryTime: t,
        entryPrice: mdlCellNum(get(r, "Price")),
        contracts: mdlCellNum(get(r, "Contracts")),
        profit: mdlCellNum(get(r, "Profit ($)")),
        profitPct: mdlCellNum(get(r, "Profit (%)")),
        cum: mdlCellNum(get(r, "Cum. Profit ($)")),
        cumPct: mdlCellNum(get(r, "Cum. Profit (%)")),
        runup: mdlCellNum(get(r, "Run-up ($)")),
        runupPct: mdlCellNum(get(r, "Run-up (%)")),
        dd: mdlCellNum(get(r, "Drawdown ($)")),
        ddPct: mdlCellNum(get(r, "Drawdown (%)"))
      };
    } else if (typ.indexOf("Exit") === 0) {
      if (!pending) continue;
      const [d, t] = dtSplit(get(r, "Date") != null ? get(r, "Date") : get(r, "Time"));
      trades.push({
        ...pending,
        exitType: typ,
        exitSignal: mdlCellText(get(r, "Signal")),
        exitOrder: mdlCellNum(get(r, "Order #")),
        exitDate: d,
        exitTime: t,
        exitPrice: mdlCellNum(get(r, "Price"))
      });
      pending = null;
    }
  }
  return trades;
};
const mdlHourly = (trades) => {
  if (!trades || !trades.length) return [];
  const by = {};
  trades.forEach((t) => {
    if (!t.entryTime) return;
    const h = t.entryTime.slice(0, 2) + ":00";
    (by[h] = by[h] || []).push(t);
  });
  return Object.keys(by).sort().map((h) => {
    const ts = by[h];
    const wins = ts.filter((t) => (t.profit || 0) > 0);
    const net = ts.reduce((a, t) => a + (t.profit || 0), 0);
    return { hour: h, profit: +net.toFixed(2), trades: ts.length, winPct: ts.length ? +(wins.length / ts.length * 100).toFixed(1) : 0 };
  });
};
const mdlRunKpis = (summary) => {
  const s = summary || {};
  return {
    net: s.net_profit != null ? s.net_profit : 0,
    pf: s.profit_factor != null ? Math.abs(s.profit_factor) : 0,
    winPct: +((s.win_rate || 0) * 100).toFixed(1),
    maxDDPct: +((s.max_drawdown_pct || 0) * 100).toFixed(2),
    maxDD: s.max_drawdown != null ? s.max_drawdown : 0,
    sharpe: s.sharpe != null ? s.sharpe : 0,
    nTrades: s.total_trades != null ? s.total_trades : 0
  };
};
const mdlLatestKpis = (m) => m && m.latest_run ? mdlRunKpis(m.latest_run.summary) : null;
Object.assign(window, {
  _mdlSend,
  _mdlUpload,
  _mdlMoney,
  _mdlPl,
  _mdlDate,
  _mdlDt,
  _mdlMs,
  MDL_TYPES,
  mdlTypeLabel,
  mdlCellVal,
  mdlCellNum,
  mdlCellIsPct,
  mdlCellIsDt,
  mdlCellText,
  mdlSheet,
  mdlSections,
  mdlSectionWidth,
  mdlFindRow,
  mdlFmtFor,
  mdlPairTrades,
  mdlHourly,
  mdlRunKpis,
  mdlLatestKpis
});

;

/* ==== pages-models-lib.jsx ==== */
const _MDLTYPE_TONE = { macro: "info", micro: "blue", both: "mag" };
const TypeBadge = ({ type }) => /* @__PURE__ */ React.createElement(Badge, { tone: _MDLTYPE_TONE[type] || "mute" }, mdlTypeLabel(type));
const KpiTile = ({ label, value, sub, color }) => /* @__PURE__ */ React.createElement(Card, { tight: true, style: { display: "flex", flexDirection: "column", gap: 2, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--qe-muted)" } }, label), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.92rem", fontWeight: 700, color: color || "var(--qe-text)", lineHeight: 1.1, fontVariantNumeric: "tabular-nums" } }, value), sub && /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.5rem", color: "var(--qe-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, sub));
const KvMini = ({ l, v, c }) => /* @__PURE__ */ React.createElement("div", { style: { minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.08em", color: "var(--qe-muted)" } }, l), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.62rem", fontWeight: 700, color: c || "var(--qe-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, v));
const ModelCard = ({ m, onOpen }) => {
  const k = mdlLatestKpis(m);
  const spark = m.spark || [];
  return /* @__PURE__ */ React.createElement("div", { onClick: () => onOpen(m), style: { cursor: "pointer", display: "flex" } }, /* @__PURE__ */ React.createElement(Card, { ticks: true, className: "qe-model-card", style: { display: "flex", flexDirection: "column", gap: 6, cursor: "pointer", padding: "8px 10px", flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "flex-start", gap: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { minWidth: 0, flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontWeight: 700, fontSize: "0.78rem", color: "var(--qe-text)", letterSpacing: "0.01em" } }, m.name), /* @__PURE__ */ React.createElement(TypeBadge, { type: m.type })), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.58rem", color: "var(--qe-sub)", lineHeight: 1.4, marginTop: 3, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" } }, m.description))), k ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { height: 26 } }, spark.length > 1 ? /* @__PURE__ */ React.createElement(Sparkline, { data: spark, height: 26, color: k.net >= 0 ? "var(--qe-green)" : "var(--qe-red)" }) : /* @__PURE__ */ React.createElement("div", { style: { height: 26 } })), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 5 } }, /* @__PURE__ */ React.createElement(KvMini, { l: "NET P/L", v: _mdlMoney(k.net, 0), c: _mdlPl(k.net) }), /* @__PURE__ */ React.createElement(KvMini, { l: "WIN %", v: k.winPct + "%" }), /* @__PURE__ */ React.createElement(KvMini, { l: "PF", v: k.pf.toFixed(2), c: k.pf >= 1.3 ? "var(--qe-green)" : k.pf < 1 ? "var(--qe-red)" : "var(--qe-text)" }), /* @__PURE__ */ React.createElement(KvMini, { l: "MAX DD", v: k.maxDDPct + "%", c: "var(--qe-red)" }), /* @__PURE__ */ React.createElement(KvMini, { l: "TRADES", v: k.nTrades }))) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7, padding: "10px 4px", border: "1px dashed var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-amber)", fontSize: "0.7rem" } }, "\u25C7"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.58rem", color: "var(--qe-muted)" } }, "No backtests imported yet")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "auto", paddingTop: 4, borderTop: "1px solid var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, "updated ", _mdlDate(m.updated_at || m.created_at)), /* @__PURE__ */ React.createElement("span", { style: { display: "flex", gap: 4 } }, (m.tags || []).slice(0, 2).map((t) => /* @__PURE__ */ React.createElement("span", { key: t, style: { fontSize: "0.5rem", color: "var(--qe-muted)", letterSpacing: "0.06em", textTransform: "uppercase", border: "1px solid var(--qe-faint)", padding: "0 3px" } }, t))))));
};
const ModelLibrary = ({ models, onOpen, onNew, embedded = false }) => {
  const [q, setQ] = React.useState("");
  const [type, setType] = React.useState("all");
  const [sort, setSort] = React.useState("updated");
  const filtered = (models || []).filter((m) => type === "all" || m.type === type).filter((m) => {
    if (!q) return true;
    const needle = q.toLowerCase();
    return (m.name || "").toLowerCase().includes(needle) || (m.tags || []).some((t) => t.toLowerCase().includes(needle));
  }).sort((a, b) => {
    if (sort === "updated") return String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || ""));
    if (sort === "name") return String(a.name).localeCompare(String(b.name));
    const ka = mdlLatestKpis(a), kb = mdlLatestKpis(b);
    if (sort === "net") return ((kb && kb.net) != null && kb ? kb.net : -1e9) - ((ka && ka.net) != null && ka ? ka.net : -1e9);
    if (sort === "pf") return (kb ? kb.pf : -1) - (ka ? ka.pf : -1);
    return 0;
  });
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", height: "100%", minHeight: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderBottom: "1px solid var(--qe-line)", flexShrink: 0, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("div", { style: { position: "relative", width: 200 } }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", placeholder: "Search models\u2026", value: q, onChange: (e) => setQ(e.target.value), style: { paddingLeft: 20 } }), /* @__PURE__ */ React.createElement("span", { style: { position: "absolute", left: 6, top: "50%", transform: "translateY(-50%)", color: "var(--qe-muted)", fontSize: "0.6rem", pointerEvents: "none" } }, "\u2315")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 4 } }, [["all", "All"], ...MDL_TYPES].map(([v, l]) => /* @__PURE__ */ React.createElement("button", { key: v, className: `qe-btn qe-btn-sm ${type === v ? "qe-btn-on" : ""}`, onClick: () => setType(v) }, l))), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.52rem", color: "var(--qe-muted)", textTransform: "uppercase", letterSpacing: "0.08em" } }, "Sort"), /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", value: sort, onChange: (e) => setSort(e.target.value), style: { width: 120 } }, /* @__PURE__ */ React.createElement("option", { value: "updated" }, "Last updated"), /* @__PURE__ */ React.createElement("option", { value: "net" }, "Net P/L"), /* @__PURE__ */ React.createElement("option", { value: "pf" }, "Profit factor"), /* @__PURE__ */ React.createElement("option", { value: "name" }, "Name")), !embedded && /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", onClick: onNew }, "+ New Model")), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, overflow: "auto", padding: 10 } }, filtered.length ? /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))", gap: 10, alignItems: "stretch" } }, filtered.map((m) => /* @__PURE__ */ React.createElement(ModelCard, { key: m.id, m, onOpen }))) : /* @__PURE__ */ React.createElement("div", { style: { height: "100%", display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(
    EmptyState,
    {
      tone: (models || []).length ? "neutral" : "info",
      glyph: "\u25C7",
      msg: (models || []).length ? "No models match your filters" : "No models yet",
      hint: (models || []).length ? "Clear the search or type filter." : "Create a reusable trading model, then import a backtest report to track its performance.",
      cta: !(models || []).length && /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", onClick: onNew }, "+ New Model")
    }
  ))));
};
Object.assign(window, { TypeBadge, KpiTile, KvMini, ModelCard, ModelLibrary });

;

/* ==== pages-models-report.jsx ==== */
const MCNum = ({ v, fmt = "usd", bold }) => {
  if (v == null || v === "") return /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "n/a");
  if (fmt === "str") return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-text)" } }, v);
  const num = typeof v === "number" ? v : parseFloat(v);
  if (isNaN(num)) return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-text)" } }, v);
  if (fmt === "pf") {
    const a = Math.abs(num), lt1 = a < 1;
    return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: lt1 ? "var(--qe-red)" : "var(--qe-green)", fontWeight: bold ? 700 : 500, fontVariantNumeric: "tabular-nums" } }, lt1 ? "(" + a.toFixed(2) + ")" : a.toFixed(2));
  }
  const neg = num < 0, zero = num === 0;
  let body;
  if (fmt === "pct") body = (Math.abs(num) * 100).toFixed(2) + "%";
  else if (fmt === "int") body = Math.round(Math.abs(num)).toLocaleString();
  else if (fmt === "num") body = Math.abs(num).toFixed(2);
  else body = "$" + Math.abs(num).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const text = neg ? "(" + body + ")" : body;
  const color = fmt === "int" || zero ? "var(--qe-text)" : neg ? "var(--qe-red)" : "var(--qe-green)";
  return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color, fontWeight: bold ? 700 : 500, fontVariantNumeric: "tabular-nums" } }, text);
};
const MdlCellR = ({ cell, label, bold }) => {
  if (cell == null) return null;
  const n = mdlCellNum(cell);
  if (n == null) {
    const t = mdlCellText(cell);
    if (!t && typeof cell === "object") return /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "n/a");
    return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-text)" } }, t);
  }
  return /* @__PURE__ */ React.createElement(MCNum, { v: n, fmt: mdlFmtFor(label, cell), bold });
};
const MdlSheetSections = ({ sheet, emptyMsg = "sheet empty in this export" }) => {
  if (!sheet) {
    return /* @__PURE__ */ React.createElement("div", { style: { padding: 8, height: "100%", display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: emptyMsg }));
  }
  const secs = mdlSections(sheet.rows);
  if (!secs.length) {
    return /* @__PURE__ */ React.createElement("div", { style: { padding: 8, height: "100%", display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: emptyMsg }));
  }
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column" } }, secs.map((sec, si) => {
    const width = mdlSectionWidth(sec);
    const cols = [{
      key: "label",
      label: sec.header && sec.header[0] || "Metric",
      width: "40%",
      render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", whiteSpace: "normal" } }, r.label)
    }];
    for (let i = 1; i < width; i++) {
      cols.push({
        key: "c" + i,
        label: sec.header && sec.header[i] || "\xB7",
        align: i === width - 1 ? "right" : "center",
        render: (r) => /* @__PURE__ */ React.createElement(MdlCellR, { cell: r.cells[i], label: r.label, bold: i === 1 })
      });
    }
    const rows = sec.rows.map((r, ri) => ({
      id: si + ":" + ri,
      label: mdlCellText(r[0]),
      cells: r
    }));
    return /* @__PURE__ */ React.createElement("div", { key: si }, sec.title && /* @__PURE__ */ React.createElement(SecLbl, { rule: true, style: { margin: "8px 7px 2px" } }, sec.title), rows.length > 0 && /* @__PURE__ */ React.createElement(DataList, { columns: cols, rows, dense: false, selKey: "id" }));
  }));
};
const StrategyAnalysisTab = ({ rep, foot }) => {
  const k = mdlRunKpis(rep.run && rep.run.summary);
  const sheet = mdlSheet(rep.report, "Strategy Analysis");
  const acct = sheet ? mdlCellNum((mdlFindRow(sheet.rows, "Account Size Required") || [])[1]) : null;
  return /* @__PURE__ */ React.createElement(GridWorkspace, { key: "sa" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 6, minW: 12, minH: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Key Metrics", style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 7 } }, /* @__PURE__ */ React.createElement(KpiTile, { label: "Net Profit", value: _mdlMoney(k.net, 0), color: _mdlPl(k.net) }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Profit Factor", value: k.pf.toFixed(2), color: k.pf >= 1 ? "var(--qe-green)" : "var(--qe-red)" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "% Profitable", value: k.winPct + "%" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Max Drawdown", value: k.maxDDPct + "%", color: "var(--qe-red)" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Total Trades", value: k.nTrades }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Account Size", value: acct != null ? _mdlMoney(acct, 0) : "\u2014" })))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 6, w: 24, h: 18, minW: 10, minH: 10 }, /* @__PURE__ */ React.createElement(Pane, { title: "Strategy Performance", tag: "AS IN FILE", style: { height: "100%" }, bodyStyle: { padding: 0 }, foot }, /* @__PURE__ */ React.createElement(MdlSheetSections, { sheet, emptyMsg: "no verbatim capture for this run \u2014 re-import to populate" }))));
};
const GraphsTab = ({ rep, foot }) => {
  const eqRows = rep.equity || [];
  const k = mdlRunKpis(rep.run && rep.run.summary);
  const settings = ((rep.run || {}).summary || {}).settings || {};
  const initial = parseFloat(String(settings["Initial Capital"] != null ? settings["Initial Capital"] : "").replace(/[$,\s]/g, "")) || (eqRows.length ? eqRows[0].equity : 0);
  const eq = eqRows.length ? [initial, ...eqRows.map((r) => r.equity)] : [];
  const dd = eqRows.length ? [0, ...eqRows.map((r) => -Math.abs(r.drawdown))] : [];
  const empty = (msg) => /* @__PURE__ */ React.createElement("div", { style: { padding: 8, height: "100%", display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg }));
  return /* @__PURE__ */ React.createElement(GridWorkspace, { key: "gr" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 14, minW: 10, minH: 7 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Equity Curve",
      tag: "CLOSED TRADES",
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.54rem", color: "var(--qe-muted)" } }, "net ", _mdlMoney(k.net, 0)),
      foot,
      bodyStyle: { padding: "4px 6px", display: "flex", flexDirection: "column" }
    },
    eq.length > 1 ? /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0 } }, /* @__PURE__ */ React.createElement(EquityChart, { data: eq, baseline: initial, color: k.net >= 0 ? "var(--qe-green)" : "var(--qe-red)" })) : empty("no equity points on this run")
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 14, w: 24, h: 10, minW: 10, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Drawdown",
      tag: "$ FROM PEAK",
      style: { height: "100%" },
      bodyStyle: { padding: "4px 6px", display: "flex", flexDirection: "column" },
      foot
    },
    dd.length > 1 ? /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0 } }, /* @__PURE__ */ React.createElement(EquityChart, { data: dd, baseline: 0, color: "var(--qe-red)" })) : empty("no equity points on this run")
  )));
};
const TradesTab = ({ rep, foot }) => {
  const [side, setSide] = React.useState("all");
  const sheet = mdlSheet(rep.report, "List of Trades");
  const paired = React.useMemo(() => mdlPairTrades(sheet), [sheet]);
  if (!paired || !paired.length) {
    const rows = (rep.trades || []).map((t, i) => ({ ...t, _i: i + 1 }));
    return /* @__PURE__ */ React.createElement(GridWorkspace, { key: "tr-fb" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 24, minW: 12, minH: 12 }, /* @__PURE__ */ React.createElement(Pane, { title: "List of Trades", count: rows.length, tag: "NORMALIZED", style: { height: "100%" }, bodyStyle: { padding: 0 }, foot }, rows.length ? /* @__PURE__ */ React.createElement(DataList, { selKey: "_i", rows, columns: [
      { key: "_i", label: "#", filter: false, render: (t) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)" } }, t._i) },
      {
        key: "side",
        label: "Side",
        filter: { label: "SIDE" },
        filterVal: (t) => (t.side || "\u2014").toUpperCase(),
        render: (t) => /* @__PURE__ */ React.createElement(Badge, { tone: t.side === "long" ? "ok" : "err" }, (t.side || "").toUpperCase())
      },
      { key: "entry_dt", label: "Entry", render: (t) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem" } }, _mdlDt(t.entry_dt)) },
      { key: "exit_dt", label: "Exit", render: (t) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem" } }, _mdlDt(t.exit_dt)) },
      { key: "entry_price", label: "Entry Px", align: "right", render: (t) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, t.entry_price) },
      { key: "exit_price", label: "Exit Px", align: "right", render: (t) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, t.exit_price) },
      { key: "contracts", label: "Cts", align: "right", render: (t) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, t.contracts || "\u2014") },
      {
        key: "pnl_usdt",
        label: "P/L $",
        align: "right",
        filter: { label: "RESULT" },
        filterVal: (t) => (t.pnl_usdt || 0) > 0 ? "WIN" : (t.pnl_usdt || 0) < 0 ? "LOSS" : "FLAT",
        render: (t) => /* @__PURE__ */ React.createElement(MCNum, { v: t.pnl_usdt, fmt: "usd", bold: true })
      },
      {
        key: "exit_reason",
        label: "Exit Reason",
        filter: true,
        filterVal: (t) => String(t.exit_reason || "\u2014")
      }
    ], emptyMsg: "no trades on this run" }) : /* @__PURE__ */ React.createElement(MdlSheetSections, { sheet, emptyMsg: "no trades on this run" }))));
  }
  const trades = paired.filter((t) => side === "all" || t.side === side);
  const cols = [
    { key: "n", label: "#", sortVal: (t) => t.n, render: (t) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)" } }, t.n) },
    {
      key: "order",
      label: "Order",
      sort: false,
      search: false,
      render: (t) => /* @__PURE__ */ React.createElement("div", { className: "qe-mc-stack" }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)" } }, t.entryOrder != null ? t.entryOrder : "\u2014"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)", opacity: 0.6 } }, t.exitOrder != null ? t.exitOrder : "\u2014"))
    },
    {
      key: "side",
      label: "Type",
      filter: false,
      sortVal: (t) => t.side,
      searchVal: (t) => `${t.entryType} ${t.exitType}`,
      render: (t) => /* @__PURE__ */ React.createElement("div", { className: "qe-mc-stack" }, /* @__PURE__ */ React.createElement(Badge, { tone: t.side === "L" ? "ok" : "err" }, (t.entryType || "").replace("Entry", "")), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.5rem", color: "var(--qe-muted)" } }, (t.exitType || "").replace("Exit", "Exit ")))
    },
    {
      key: "entrySignal",
      label: "Signal",
      searchVal: (t) => `${t.entrySignal} ${t.exitSignal}`,
      render: (t) => /* @__PURE__ */ React.createElement("div", { className: "qe-mc-stack" }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-cyan)", fontSize: "0.56rem" } }, t.entrySignal), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-sub)", fontSize: "0.56rem" } }, t.exitSignal))
    },
    {
      key: "entryDate",
      label: "Date",
      sortVal: (t) => t.entryDate,
      searchVal: (t) => `${t.entryDate} ${t.exitDate}`,
      render: (t) => /* @__PURE__ */ React.createElement("div", { className: "qe-mc-stack" }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)", fontSize: "0.54rem" } }, t.entryDate), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)", fontSize: "0.54rem", opacity: 0.8 } }, t.exitDate))
    },
    {
      key: "entryTime",
      label: "Time",
      sortVal: (t) => t.entryTime,
      searchVal: (t) => `${t.entryTime} ${t.exitTime}`,
      render: (t) => /* @__PURE__ */ React.createElement("div", { className: "qe-mc-stack" }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)", fontSize: "0.54rem" } }, t.entryTime), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)", fontSize: "0.54rem", opacity: 0.8 } }, t.exitTime))
    },
    {
      key: "entryPrice",
      label: "Price",
      align: "right",
      sortVal: (t) => t.entryPrice,
      render: (t) => /* @__PURE__ */ React.createElement("div", { className: "qe-mc-stack" }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, t.entryPrice != null ? t.entryPrice : "\u2014"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)" } }, t.exitPrice != null ? t.exitPrice : "\u2014"))
    },
    { key: "contracts", label: "Cts", align: "right", render: (t) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, t.contracts != null ? t.contracts : "\u2014") },
    {
      key: "profit",
      label: "Profit $",
      align: "right",
      sortVal: (t) => t.profit,
      filter: { label: "RESULT" },
      filterVal: (t) => (t.profit || 0) > 0 ? "WIN" : (t.profit || 0) < 0 ? "LOSS" : "FLAT",
      render: (t) => /* @__PURE__ */ React.createElement(MCNum, { v: t.profit, fmt: "usd", bold: true })
    },
    { key: "profitPct", label: "Profit %", align: "right", sortVal: (t) => t.profitPct, render: (t) => /* @__PURE__ */ React.createElement(MCNum, { v: t.profitPct, fmt: "pct" }) },
    { key: "cum", label: "Cum $", align: "right", sortVal: (t) => t.cum, render: (t) => /* @__PURE__ */ React.createElement(MCNum, { v: t.cum, fmt: "usd" }) },
    { key: "runup", label: "Run-up $", align: "right", sortVal: (t) => t.runup, render: (t) => /* @__PURE__ */ React.createElement(MCNum, { v: t.runup, fmt: "usd" }) },
    { key: "dd", label: "Drawdn $", align: "right", sortVal: (t) => t.dd, render: (t) => /* @__PURE__ */ React.createElement(MCNum, { v: t.dd, fmt: "usd" }) }
  ];
  return /* @__PURE__ */ React.createElement(GridWorkspace, { key: "tr" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 24, minW: 12, minH: 12 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "List of Trades",
      count: trades.length,
      style: { height: "100%" },
      bodyStyle: { padding: 0 },
      foot,
      right: /* @__PURE__ */ React.createElement("span", { style: { display: "flex", gap: 4 } }, [["all", "ALL"], ["L", "LONG"], ["S", "SHORT"]].map(([v, l]) => /* @__PURE__ */ React.createElement("button", { key: v, className: `qe-btn qe-btn-sm ${side === v ? "qe-btn-on" : ""}`, onClick: () => setSide(v) }, l)))
    },
    /* @__PURE__ */ React.createElement("div", { className: "qe-mc-trades" }, /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "n",
        columns: cols,
        rows: trades,
        emptyMsg: `no ${side === "L" ? "long " : side === "S" ? "short " : ""}trades in run`
      }
    ))
  )));
};
const AnalysisTab = ({ rep, foot }) => /* @__PURE__ */ React.createElement(GridWorkspace, { key: "an" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 24, minW: 12, minH: 10 }, /* @__PURE__ */ React.createElement(Pane, { title: "Trade Analysis", tag: "AS IN FILE", style: { height: "100%" }, bodyStyle: { padding: 0 }, foot }, /* @__PURE__ */ React.createElement(
  MdlSheetSections,
  {
    sheet: mdlSheet(rep.report, "Trade Analysis"),
    emptyMsg: "'Trade Analysis' sheet empty in this export"
  }
))));
const PeriodicalTab = ({ rep, foot }) => {
  const paired = React.useMemo(() => mdlPairTrades(mdlSheet(rep.report, "List of Trades")), [rep.report]);
  const hourly = mdlHourly(paired);
  return /* @__PURE__ */ React.createElement(GridWorkspace, { key: "pe" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 24, h: 8, minW: 10, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Profit by Hour",
      tag: "FROM TRADE LIST",
      style: { height: "100%" },
      bodyStyle: { padding: "4px 6px", display: "flex", flexDirection: "column" },
      foot
    },
    hourly.length ? /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0 } }, /* @__PURE__ */ React.createElement(BarChart, { data: hourly.map((x) => x.profit), categories: hourly.map((x) => x.hour), color: "var(--qe-cyan)" })) : /* @__PURE__ */ React.createElement("div", { style: { padding: 8, height: "100%", display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(EmptyState, { fill: true, tone: "neutral", glyph: "\u25C7", msg: "no timed trades to bucket" }))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 8, w: 24, h: 16, minW: 10, minH: 8 }, /* @__PURE__ */ React.createElement(Pane, { title: "Periodical Analysis", tag: "AS IN FILE", style: { height: "100%" }, bodyStyle: { padding: 0 }, foot }, /* @__PURE__ */ React.createElement(
    MdlSheetSections,
    {
      sheet: mdlSheet(rep.report, "Periodical Analysis"),
      emptyMsg: "'Periodical Analysis' sheet empty in this export"
    }
  ))));
};
const SettingsTab = ({ rep, foot }) => {
  const run = rep.run || {};
  const summary = run.summary || {};
  return /* @__PURE__ */ React.createElement(GridWorkspace, { key: "se" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 16, h: 24, minW: 8, minH: 10 }, /* @__PURE__ */ React.createElement(Pane, { title: "Settings", tag: "AS IN FILE", style: { height: "100%" }, bodyStyle: { padding: 0 }, foot }, /* @__PURE__ */ React.createElement(
    MdlSheetSections,
    {
      sheet: mdlSheet(rep.report, "Settings"),
      emptyMsg: "'Settings' sheet empty in this export"
    }
  ))), /* @__PURE__ */ React.createElement(GridItem, { x: 16, y: 0, w: 8, h: 10, minW: 6, minH: 6 }, /* @__PURE__ */ React.createElement(Pane, { title: "Import Provenance", style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement(FieldList, { dense: true, rows: [
    { label: "Source file", value: summary.source_file || "\u2014", color: "cyan" },
    { label: "Source app", value: run.source_app || "\u2014" },
    { label: "Imported", value: _mdlDt(run.created_at) },
    { label: "Window", value: (run.date_from || "\u2014") + " \u2192 " + (run.date_to || "\u2014") },
    { label: "Status", value: (run.status || "\u2014").toUpperCase() }
  ] }))));
};
Object.assign(window, {
  MCNum,
  MdlCellR,
  MdlSheetSections,
  StrategyAnalysisTab,
  GraphsTab,
  TradesTab,
  AnalysisTab,
  PeriodicalTab,
  SettingsTab
});

;

/* ==== pages-models-overview.jsx ==== */
const ModelOverview = ({ models, onOpen, onNew, foot }) => {
  const scored = (models || []).map((m) => ({ m, k: mdlLatestKpis(m) })).filter((x) => x.k);
  const totalNet = scored.reduce((a, x) => a + x.k.net, 0);
  const avgWin = scored.length ? scored.reduce((a, x) => a + x.k.winPct, 0) / scored.length : 0;
  const totalTrades = scored.reduce((a, x) => a + x.k.nTrades, 0);
  const ranked = [...scored].sort((a, b) => b.k.net - a.k.net);
  const best = ranked[0], worst = ranked[ranked.length - 1];
  const n = (models || []).length;
  return /* @__PURE__ */ React.createElement(GridWorkspace, { key: "models-overview" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 12, h: 5, minW: 8, minH: 4 }, /* @__PURE__ */ React.createElement(Pane, { title: "Library Summary", count: n, style: { height: "100%" }, foot }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(132px, 1fr))", gap: 7 } }, /* @__PURE__ */ React.createElement(KpiTile, { label: "Total Net P/L", value: _mdlMoney(totalNet, 0), sub: "latest run / model", color: _mdlPl(totalNet) }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Avg Win %", value: avgWin.toFixed(1) + "%", sub: `${scored.length} models` }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Models", value: n, sub: `${n - scored.length} without runs` }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Best Model", value: best ? _mdlMoney(best.k.net, 0) : "\u2014", sub: best ? best.m.name : "\u2014", color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Worst Model", value: worst ? _mdlMoney(worst.k.net, 0) : "\u2014", sub: worst ? worst.m.name : "\u2014", color: worst && worst.k.net < 0 ? "var(--qe-red)" : "var(--qe-text)" })), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { marginTop: 6, fontSize: "0.52rem", color: "var(--qe-muted)" } }, scored.length, " with imported performance \xB7 ", totalTrades, " backtested trades"))), /* @__PURE__ */ React.createElement(GridItem, { x: 12, y: 0, w: 12, h: 5, minW: 8, minH: 4 }, /* @__PURE__ */ React.createElement(Pane, { title: "Leaderboard", count: ranked.length, style: { height: "100%" }, bodyStyle: { padding: 0 }, foot }, ranked.length ? /* @__PURE__ */ React.createElement(
    DataList,
    {
      selKey: "id",
      onClick: (row) => {
        const m = (models || []).find((x) => x.id === row.id);
        if (m) onOpen(m);
      },
      columns: [
        { key: "rank", label: "#", sort: false, filter: false, search: false, render: (r, i) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)" } }, i + 1) },
        { key: "name", label: "MODEL", filter: false, render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700, fontSize: "0.6rem" } }, r.name) },
        {
          key: "type",
          label: "TYPE",
          filter: true,
          filterVal: (r) => String(r.type || "\u2014").toUpperCase(),
          render: (r) => /* @__PURE__ */ React.createElement(TypeBadge, { type: r.type })
        },
        // MODEL is unique-per-row (one row per model) so it can never be
        // a useful facet; TYPE often has a single value. Bucket the net P/L
        // sign — this pane's actual question.
        {
          key: "net",
          label: "NET P/L",
          align: "right",
          filter: { label: "RESULT" },
          filterVal: (r) => r.net > 0 ? "PROFIT" : r.net < 0 ? "LOSS" : "FLAT",
          render: (r) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: _mdlPl(r.net), fontWeight: 700 } }, _mdlMoney(r.net, 0))
        },
        { key: "pf", label: "PF", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, r.pf.toFixed(2)) },
        { key: "win", label: "WIN%", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, r.win, "%") }
      ],
      rows: ranked.map((x) => ({ id: x.m.id, name: x.m.name, type: x.m.type, net: x.k.net, pf: x.k.pf, win: x.k.winPct }))
    }
  ) : /* @__PURE__ */ React.createElement("div", { style: { padding: 10, height: "100%", display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(
    EmptyState,
    {
      fill: true,
      tone: "neutral",
      glyph: "\u25C7",
      msg: "No ranked models yet",
      hint: "Import a backtest report to put a model on the board."
    }
  )))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 5, w: 24, h: 13, minW: 12, minH: 9 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Model Library",
      count: n,
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", onClick: onNew }, "+ New Model"),
      foot,
      bodyStyle: { padding: 0, display: "flex", flexDirection: "column" }
    },
    /* @__PURE__ */ React.createElement(ModelLibrary, { models, onOpen, onNew, embedded: true })
  )));
};
Object.assign(window, { ModelOverview });

;

/* ==== pages-models-detail.jsx ==== */
const _MdlFieldRow = ({ l, v, color }) => /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "104px 1fr", gap: 8, padding: "3px 0", borderBottom: "1px solid var(--qe-faint)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.54rem", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--qe-muted)" } }, l), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.62rem", color: color || "var(--qe-text)", textWrap: "pretty" } }, v));
const _mdlOr = (v, suffix = "") => v != null && v !== "" ? String(v) + suffix : "\u2014";
const ModelOverviewTab = ({ m, runs, runsFoot, usage, usageFoot, ovFoot, onOpenRun, onImport, onLoadCalc }) => {
  const r = m.risk_preset || {};
  const s = m.strategy || {};
  const src = m.source || {};
  const hasSrc = Object.keys(src).length > 0;
  const closed = usage && usage.closed || [];
  const plans = usage && usage.plans || [];
  return /* @__PURE__ */ React.createElement(GridWorkspace, { key: "ov-" + m.id }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 8, h: 11, minW: 5, minH: 8 }, /* @__PURE__ */ React.createElement(Pane, { title: "Risk, Sizing & Source", style: { height: "100%" }, foot: ovFoot }, /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Risk / trade", v: r.risk_pct != null ? (+r.risk_pct).toFixed(2) + "%" : "\u2014", color: "var(--qe-cyan)" }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Sizing rule", v: _mdlOr(r.sizing_rule) }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Match window", v: r.window_seconds != null ? r.window_seconds + "s" : "\u2014" }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "TP method", v: _mdlOr(r.tp_methodology) }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "SL method", v: _mdlOr(r.sl_methodology) }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Regime mult.", v: r.apply_regime_multiplier ? "ON" : "OFF", color: r.apply_regime_multiplier ? "var(--qe-green)" : "var(--qe-muted)" }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Size override", v: r.size_override_default != null ? "$" + r.size_override_default : "\u2014" }), hasSrc && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { margin: "7px 0 3px", fontFamily: "var(--qe-ui)", fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--qe-cyan)" } }, "Source \xB7 ", src.app || "\u2014"), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Symbol", v: _mdlOr(src.symbol), color: "var(--qe-cyan)" }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Resolution", v: _mdlOr(src.resolution) }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Point value", v: src.point_value != null ? "$" + src.point_value + (src.currency ? " / " + src.currency : "") : "\u2014" }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Init capital", v: src.initial_capital != null ? "$" + Number(src.initial_capital).toLocaleString() : "\u2014" }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Commission", v: _mdlOr(src.commission) }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Slippage", v: _mdlOr(src.slippage) })), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-on", style: { marginTop: 8, width: "100%", justifyContent: "center" }, onClick: onLoadCalc }, "\u21AA Load into Pre-Trade"))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 11, w: 8, h: 6, minW: 5, minH: 6 }, /* @__PURE__ */ React.createElement(Pane, { title: "Strategy Definition", style: { height: "100%" }, foot: ovFoot }, s.notes && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.6rem", color: "var(--qe-sub)", lineHeight: 1.5, marginBottom: 7, textWrap: "pretty" } }, s.notes), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Entry logic", v: _mdlOr(s.entry_logic) }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Exit logic", v: _mdlOr(s.exit_logic) }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Universe", v: _mdlOr(s.target_universe), color: "var(--qe-cyan)" }), /* @__PURE__ */ React.createElement(_MdlFieldRow, { l: "Regime cfg", v: _mdlOr(s.regime_config) }))), /* @__PURE__ */ React.createElement(GridItem, { x: 8, y: 0, w: 16, h: 8, minW: 9, minH: 7 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Backtest Runs",
      count: (runs || []).length,
      style: { height: "100%" },
      right: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", onClick: onImport }, "\u2913 Import Report"),
      foot: runsFoot,
      bodyStyle: { padding: 0 }
    },
    (runs || []).length ? /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "id",
        onClick: (row) => {
          if (row.status === "completed") onOpenRun(row);
        },
        columns: [
          {
            key: "source_app",
            label: "SOURCE",
            filter: true,
            filterVal: (r2) => String(r2.source_app || "\u2014").toUpperCase(),
            render: (r2) => /* @__PURE__ */ React.createElement(Badge, { tone: "info" }, r2.source_app || "\u2014")
          },
          // FILE/WINDOW render values that live off the row (summary.source_file,
          // a date RANGE), which is why they had opted out entirely. The
          // accessors reach exactly what the cell shows.
          {
            key: "file",
            label: "FILE",
            sortVal: (r2) => r2.summary && r2.summary.source_file || r2.name || "",
            searchVal: (r2) => r2.summary && r2.summary.source_file || r2.name || "",
            render: (r2) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-sub)" } }, r2.summary && r2.summary.source_file || r2.name || "\u2014")
          },
          { key: "window", label: "WINDOW", sortVal: (r2) => r2.date_from || "", render: (r2) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.54rem" } }, _mdlDate(r2.date_from), " \u2192 ", _mdlDate(r2.date_to)) },
          { key: "net", label: "NET P/L", align: "right", sortVal: (r2) => mdlRunKpis(r2.summary).net, render: (r2) => {
            const k = mdlRunKpis(r2.summary);
            return /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: _mdlPl(k.net), fontWeight: 700 } }, _mdlMoney(k.net, 0));
          } },
          { key: "pf", label: "PF", align: "right", sortVal: (r2) => mdlRunKpis(r2.summary).pf, render: (r2) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, mdlRunKpis(r2.summary).pf.toFixed(2)) },
          { key: "win", label: "WIN%", align: "right", sortVal: (r2) => mdlRunKpis(r2.summary).winPct, render: (r2) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, mdlRunKpis(r2.summary).winPct, "%") },
          { key: "dd", label: "MAX DD", align: "right", sortVal: (r2) => mdlRunKpis(r2.summary).maxDDPct, render: (r2) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-red)" } }, mdlRunKpis(r2.summary).maxDDPct, "%") },
          { key: "n", label: "TRADES", align: "right", sortVal: (r2) => mdlRunKpis(r2.summary).nTrades, render: (r2) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono" }, mdlRunKpis(r2.summary).nTrades) },
          {
            key: "status",
            label: "STATUS",
            filter: true,
            filterVal: (r2) => (r2.status || "\u2014").toUpperCase(),
            render: (r2) => /* @__PURE__ */ React.createElement(Badge, { tone: r2.status === "completed" ? "ok" : r2.status === "failed" ? "err" : "warn" }, (r2.status || "\u2014").toUpperCase())
          },
          { key: "created_at", label: "IMPORTED", align: "right", render: (r2) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.54rem", color: "var(--qe-muted)" } }, _mdlDt(r2.created_at)) }
        ],
        rows: runs
      }
    ) : /* @__PURE__ */ React.createElement("div", { style: { padding: 10, height: "100%", display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        fill: true,
        tone: "warn",
        glyph: "\u2913",
        msg: "No backtests imported yet",
        hint: "Performance only ever comes from imported reports (MultiCharts .xlsx / .xml).",
        cta: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", onClick: onImport }, "\u2913 Import a report")
      }
    ))
  )), /* @__PURE__ */ React.createElement(GridItem, { x: 8, y: 8, w: 16, h: 9, minW: 9, minH: 6 }, /* @__PURE__ */ React.createElement(
    Pane,
    {
      title: "Usage / Attribution",
      count: closed.length + plans.length,
      style: { height: "100%" },
      foot: usageFoot,
      bodyStyle: { padding: 0 }
    },
    closed.length || plans.length ? /* @__PURE__ */ React.createElement("div", null, closed.length > 0 && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(SecLbl, { rule: true, style: { margin: "6px 7px 2px" } }, "Closed positions"), /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "id",
        columns: [
          { key: "terminal_position_id", label: "POSITION", render: (u) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-cyan)", fontSize: "0.56rem" } }, u.terminal_position_id || "#" + u.id) },
          { key: "symbol", label: "SYMBOL" },
          { key: "direction", label: "SIDE", render: (u) => /* @__PURE__ */ React.createElement(Badge, { tone: u.direction === "long" ? "ok" : u.direction === "short" ? "err" : "mute" }, (u.direction || "\u2014").toUpperCase()) },
          { key: "net_pnl", label: "NET PnL", align: "right", sortVal: (u) => u.net_pnl, render: (u) => u.net_pnl == null ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-muted)" } }, "\u2014") : /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: _mdlPl(u.net_pnl), fontWeight: 700 } }, (u.net_pnl >= 0 ? "+" : "") + (+u.net_pnl).toFixed(2)) },
          { key: "exit_time_ms", label: "CLOSED", align: "right", render: (u) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)", fontSize: "0.54rem" } }, _mdlMs(u.exit_time_ms)) }
        ],
        rows: closed
      }
    )), plans.length > 0 && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(SecLbl, { rule: true, style: { margin: "6px 7px 2px" } }, "Pre-trade plans"), /* @__PURE__ */ React.createElement(
      DataList,
      {
        selKey: "id",
        columns: [
          { key: "calc_id", label: "CALC", render: (u) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-cyan)", fontSize: "0.56rem" } }, u.calc_id || "#" + u.id) },
          { key: "ticker", label: "TICKER" },
          { key: "side", label: "SIDE", render: (u) => /* @__PURE__ */ React.createElement(Badge, { tone: /long|buy/i.test(u.side || "") ? "ok" : /short|sell/i.test(u.side || "") ? "err" : "mute" }, (u.side || "\u2014").toUpperCase()) },
          // forced: COMPLETED_VIA_POSITION exceeds DL_VALUE_MAXLEN(16),
          // so auto-derivation refuses this column outright.
          {
            key: "status",
            label: "STATUS",
            filter: true,
            filterVal: (u) => (u.status || "\u2014").toUpperCase(),
            render: (u) => /* @__PURE__ */ React.createElement(Badge, { tone: "mute" }, (u.status || "\u2014").toUpperCase())
          },
          { key: "timestamp", label: "PLANNED", align: "right", render: (u) => /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { color: "var(--qe-muted)", fontSize: "0.54rem" } }, _mdlDt(u.timestamp)) }
        ],
        rows: plans
      }
    ))) : /* @__PURE__ */ React.createElement("div", { style: { padding: 10, height: "100%", display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        fill: true,
        tone: "neutral",
        glyph: "\u2205",
        msg: "Not used by any positions yet",
        hint: "Closed positions and pre-trade plans tagged with this model appear here (open positions appear once closed)."
      }
    ))
  )));
};
const MODEL_SECTIONS = [
  ["overview", "Overview"],
  ["strategy", "Strategy Analysis"],
  ["graphs", "Graphs"],
  ["trades", "List of Trades"],
  ["analysis", "Trade Analysis"],
  ["periodical", "Periodical"],
  ["settings", "Settings"]
];
const ModelView = ({ m, ovFoot, onImport, onLoadCalc }) => {
  const [section, setSection] = React.useState("overview");
  const [runId, setRunId] = React.useState(null);
  const { data: runsData, foot: runsFoot, reload: reloadRuns } = useAnaJson(`/api/models/${m.id}/runs`);
  const { data: usage, foot: usageFoot, reload: reloadUsage } = useAnaJson(`/api/models/${m.id}/usage`);
  const allRuns = runsData && runsData.runs || [];
  const runs = allRuns.filter((r) => r.status === "completed");
  React.useEffect(() => {
    setSection("overview");
    setRunId(null);
  }, [m.id]);
  const run = runs.find((r) => r.id === runId) || runs[0] || null;
  const effRunId = run ? run.id : null;
  const { data: rep, err: repErr, reload: reloadRep, foot: repFoot } = useAnaJson(
    effRunId != null ? `/api/models/${m.id}/runs/${effRunId}/report` : null
  );
  const report = effRunId != null && rep && rep.run ? rep : null;
  const needsRun = section !== "overview" && !report;
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", flex: 1, minHeight: 0 } }, /* @__PURE__ */ React.createElement(
    TabStrip,
    {
      value: section,
      onChange: setSection,
      tabs: MODEL_SECTIONS,
      right: run && section !== "overview" ? /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, paddingLeft: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", textTransform: "uppercase", letterSpacing: "0.08em" } }, "Run"), runs.length > 1 ? /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", value: effRunId, onChange: (e) => setRunId(+e.target.value), style: { width: 190, height: 18, alignSelf: "center" } }, runs.map((r) => /* @__PURE__ */ React.createElement("option", { key: r.id, value: r.id }, "#", r.id, " \xB7 ", r.summary && r.summary.source_file || r.name || r.source_app))) : /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-cyan)", alignSelf: "center" } }, "#", run.id, " \xB7 ", run.summary && run.summary.source_file || run.name || run.source_app)) : null
    }
  ), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" } }, section === "overview" && /* @__PURE__ */ React.createElement(
    ModelOverviewTab,
    {
      m,
      runs: allRuns,
      runsFoot,
      usage,
      usageFoot,
      ovFoot,
      onImport: () => onImport(() => {
        reloadRuns();
        reloadUsage();
      }),
      onLoadCalc,
      onOpenRun: (r) => {
        setRunId(r.id);
        setSection("strategy");
      }
    }
  ), needsRun && /* @__PURE__ */ React.createElement("div", { style: { height: "100%", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 } }, run && repErr ? (
    // MED-2 fold: a failed report fetch is a TERMINAL state on
    // this one-shot pipe — name the cause (tier 3), offer retry.
    /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        tone: "err",
        glyph: "\u2717",
        msg: "run report unavailable",
        hint: qeFootCause(repErr),
        cta: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: reloadRep }, "Retry")
      }
    )
  ) : run ? /* @__PURE__ */ React.createElement(Spinner, { label: "loading run report" }) : /* @__PURE__ */ React.createElement(
    EmptyState,
    {
      tone: "warn",
      glyph: "\u2913",
      msg: "No imported run to report on",
      hint: "This model has no completed backtest import yet. Import a MultiCharts report (.xlsx / .xml) to populate Strategy Analysis, trades, and the rest.",
      cta: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", onClick: () => onImport(() => {
        reloadRuns();
        reloadUsage();
      }) }, "\u2913 Import a report")
    }
  )), !needsRun && section === "strategy" && /* @__PURE__ */ React.createElement(StrategyAnalysisTab, { rep: report, foot: repFoot }), !needsRun && section === "graphs" && /* @__PURE__ */ React.createElement(GraphsTab, { rep: report, foot: repFoot }), !needsRun && section === "trades" && /* @__PURE__ */ React.createElement(TradesTab, { rep: report, foot: repFoot }), !needsRun && section === "analysis" && /* @__PURE__ */ React.createElement(AnalysisTab, { rep: report, foot: repFoot }), !needsRun && section === "periodical" && /* @__PURE__ */ React.createElement(PeriodicalTab, { rep: report, foot: repFoot }), !needsRun && section === "settings" && /* @__PURE__ */ React.createElement(SettingsTab, { rep: report, foot: repFoot })));
};
Object.assign(window, { ModelView, ModelOverviewTab });

;

/* ==== pages-models.jsx ==== */
const _MdlField = ({ label, children, hint, error }) => /* @__PURE__ */ React.createElement("label", { style: { display: "flex", flexDirection: "column", gap: 4, minWidth: 0 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.52rem", fontWeight: 700, letterSpacing: "0.09em", textTransform: "uppercase", color: error ? "var(--qe-red)" : "var(--qe-sub)" } }, label), children, error ? /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.5rem", color: "var(--qe-red)" } }, error) : hint && /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.5rem", color: "var(--qe-muted)" } }, hint));
const _MdlSec = ({ title, sub, children }) => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.54rem", fontWeight: 700, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--qe-sub)", whiteSpace: "nowrap" } }, title), sub && /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", whiteSpace: "nowrap" } }, sub), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, height: 1, background: "var(--qe-line)" } })), children);
const _MdlFileBtn = ({ label, onFile, className = "qe-btn qe-btn-sm qe-btn-on", accept = ".xlsx,.xml" }) => {
  const ref = React.useRef(null);
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
    "input",
    {
      ref,
      type: "file",
      accept,
      style: { display: "none" },
      onChange: (e) => {
        const f = e.target.files && e.target.files[0];
        if (f) onFile(f);
        e.target.value = "";
      }
    }
  ), /* @__PURE__ */ React.createElement("button", { className, onClick: () => ref.current && ref.current.click() }, label));
};
const MDL_SOURCE_APPS = ["MultiCharts", "TradeStation", "NinjaTrader", "Generic CSV"];
const ModelFormModal = ({ model, onClose, onSave }) => {
  const editing = !!model;
  const blank = {
    name: "",
    type: "macro",
    desc: "",
    tags: "",
    app: "MultiCharts",
    symbol: "",
    resolution: "",
    pointValue: "",
    currency: "USD",
    initialCapital: "",
    commission: "",
    slippage: "",
    riskPct: "1.0",
    matchWindow: "90",
    tp: "",
    sl: "",
    regimeMult: false,
    entry: "",
    exit: "",
    notes: "",
    universe: ""
  };
  const fromModel = (m) => {
    const r = m.risk_preset || {}, s = m.strategy || {}, src = m.source || {};
    return {
      name: m.name || "",
      type: m.type || "both",
      desc: m.description || "",
      tags: (m.tags || []).join(", "),
      app: src.app || "MultiCharts",
      symbol: src.symbol || "",
      resolution: src.resolution || "",
      pointValue: src.point_value != null ? String(src.point_value) : "",
      currency: src.currency || "USD",
      initialCapital: src.initial_capital != null ? String(src.initial_capital) : "",
      commission: src.commission || "",
      slippage: src.slippage || "",
      riskPct: r.risk_pct != null ? String(r.risk_pct) : "",
      matchWindow: r.window_seconds != null ? String(r.window_seconds) : "",
      tp: r.tp_methodology || "",
      sl: r.sl_methodology || "",
      regimeMult: !!r.apply_regime_multiplier,
      entry: s.entry_logic || "",
      exit: s.exit_logic || "",
      notes: s.notes || "",
      universe: s.target_universe || ""
    };
  };
  const [mode, setMode] = React.useState("blank");
  const [f, setF] = React.useState(() => editing ? fromModel(model) : blank);
  const [parsed, setParsed] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [subErr, setSubErr] = React.useState(null);
  const [touched, setTouched] = React.useState(false);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const doParse = async (file) => {
    setBusy(true);
    setSubErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("app_id", "multicharts");
      const pv = await _mdlUpload("/api/models/import?dry_run=1", fd);
      setParsed({ file, preview: pv });
      const sug = pv.source_suggestion || {};
      const inputs = pv.settings || {};
      const rp = parseFloat(inputs.RiskPctOfEquity);
      setF((p) => ({
        ...p,
        name: p.name || [sug.symbol, sug.resolution].filter(Boolean).join(" ").trim(),
        symbol: sug.symbol || p.symbol,
        resolution: sug.resolution || p.resolution,
        pointValue: sug.point_value != null ? String(sug.point_value) : p.pointValue,
        currency: sug.currency || p.currency,
        initialCapital: sug.initial_capital != null ? String(sug.initial_capital) : p.initialCapital,
        commission: sug.commission || p.commission,
        slippage: sug.slippage || p.slippage,
        riskPct: Number.isFinite(rp) ? String(rp) : p.riskPct,
        universe: p.universe || sug.symbol || ""
      }));
    } catch (e) {
      setSubErr(e);
    }
    setBusy(false);
  };
  const errors = {
    name: !f.name.trim() ? "Name is required" : null,
    riskPct: f.riskPct.trim() && !(parseFloat(f.riskPct) > 0 && parseFloat(f.riskPct) <= 100) ? "Risk must be in (0, 100]" : null
  };
  const valid = !errors.name && !errors.riskPct;
  const buildBody = () => {
    const risk = { ...model && model.risk_preset || {}, apply_regime_multiplier: f.regimeMult };
    if (f.riskPct.trim()) risk.risk_pct = parseFloat(f.riskPct);
    else delete risk.risk_pct;
    if (f.matchWindow.trim()) risk.window_seconds = parseInt(f.matchWindow, 10);
    else delete risk.window_seconds;
    if (f.tp.trim()) risk.tp_methodology = f.tp.trim();
    else delete risk.tp_methodology;
    if (f.sl.trim()) risk.sl_methodology = f.sl.trim();
    else delete risk.sl_methodology;
    const strategy = {
      ...model && model.strategy || {},
      entry_logic: f.entry.trim(),
      exit_logic: f.exit.trim(),
      target_universe: f.universe.trim(),
      notes: f.notes.trim()
    };
    const source = {};
    if (f.app.trim()) source.app = f.app.trim();
    if (f.symbol.trim()) source.symbol = f.symbol.trim();
    if (f.resolution.trim()) source.resolution = f.resolution.trim();
    if (f.pointValue.trim() && Number.isFinite(parseFloat(f.pointValue))) source.point_value = parseFloat(f.pointValue);
    if (f.currency.trim()) source.currency = f.currency.trim();
    if (f.initialCapital.trim() && Number.isFinite(parseFloat(f.initialCapital))) source.initial_capital = parseFloat(f.initialCapital);
    if (f.commission.trim()) source.commission = f.commission.trim();
    if (f.slippage.trim()) source.slippage = f.slippage.trim();
    return {
      name: f.name.trim(),
      type: f.type,
      description: f.desc.trim(),
      risk_preset: risk,
      strategy,
      source: Object.keys(source).length > 1 || source.symbol ? source : editing ? model.source || {} : {},
      tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean)
    };
  };
  const submit = async () => {
    setTouched(true);
    if (!valid || busy) return;
    setBusy(true);
    setSubErr(null);
    const body = buildBody();
    try {
      if (editing) {
        await _mdlSend("/api/models/" + model.id, "PUT", body);
        onSave({ kind: "updated", modelId: model.id });
      } else if (parsed) {
        const fd = new FormData();
        fd.append("file", parsed.file);
        fd.append("app_id", "multicharts");
        fd.append("payload", JSON.stringify(body));
        const res = await _mdlUpload("/api/models/import", fd);
        onSave({ kind: "created+imported", modelId: res.model_id, runId: res.run_id });
      } else {
        const res = await _mdlSend("/api/models", "POST", body);
        onSave({ kind: "created", modelId: res.model_id });
      }
    } catch (e) {
      setSubErr(e);
      setBusy(false);
    }
  };
  const seg = (val, label) => /* @__PURE__ */ React.createElement(
    "button",
    {
      key: val,
      onClick: () => {
        setMode(val);
        if (val === "blank") setParsed(null);
      },
      style: {
        flex: 1,
        padding: "7px 0",
        fontFamily: "var(--qe-ui)",
        fontSize: "0.58rem",
        fontWeight: 700,
        letterSpacing: "0.04em",
        cursor: "pointer",
        border: "1px solid " + (mode === val ? "var(--qe-cyan)" : "var(--qe-line)"),
        background: mode === val ? "var(--qe-bg-cyan)" : "transparent",
        color: mode === val ? "var(--qe-cyan)" : "var(--qe-sub)"
      }
    },
    label
  );
  const foot = busy ? { tone: "sub", busy: true, msg: parsed && !editing ? "uploading\u2026" : "saving\u2026" } : subErr ? { tone: "err", msg: qeFootCause(subErr) + " \u2014 " + String(subErr.message || "").slice(0, 60) } : parsed ? { tone: "ok", msg: `parsed ${parsed.file.name} \xB7 fields auto-filled` } : { tone: "sub", msg: "ok \xB7 local \u2014 nothing submitted yet" };
  const pvk = parsed ? mdlRunKpis(parsed.preview.summary) : null;
  return /* @__PURE__ */ React.createElement(
    ModelDialog,
    {
      title: editing ? `Edit Model \xB7 ${model.name}` : "New Model",
      width: 640,
      onClose,
      foot,
      footer: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: onClose }, "Cancel"), /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "qe-btn qe-btn-sm qe-btn-primary",
          disabled: !valid || busy,
          onClick: submit,
          style: !valid || busy ? { opacity: 0.5, cursor: "not-allowed" } : {}
        },
        editing ? "Save changes" : parsed ? "Create model + import run" : "Create model"
      ))
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 20, padding: "4px 6px" } }, !editing && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6 } }, seg("blank", "+ Blank model"), seg("import", "\u2913 From backtest report")), !editing && mode === "import" && /* @__PURE__ */ React.createElement(_MdlSec, { title: "Import Backtest Report", sub: "MultiCharts .xlsx / .xml" }, !parsed ? /* @__PURE__ */ React.createElement("div", { style: { border: "1px dashed var(--qe-line-2)", padding: "22px 16px", textAlign: "center", background: "var(--qe-panel)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "1.3rem", color: "var(--qe-muted)", lineHeight: 1 } }, "\u2913"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginTop: 8 } }, "Pick a report to auto-fill the model"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.52rem", color: "var(--qe-muted)", marginTop: 4 } }, "parses the Settings sheet \u2014 symbol, point value, resolution, risk inputs"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, justifyContent: "center", marginTop: 14 } }, busy ? /* @__PURE__ */ React.createElement(Spinner, { label: "parsing" }) : /* @__PURE__ */ React.createElement(_MdlFileBtn, { label: "Choose file\u2026", onFile: doParse }))) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "PARSED"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.6rem", color: "var(--qe-text)" } }, parsed.file.name), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: () => setParsed(null) }, "Clear")), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6 } }, /* @__PURE__ */ React.createElement(KpiTile, { label: "Net P/L", value: _mdlMoney(pvk.net, 0), color: _mdlPl(pvk.net) }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Profit Factor", value: pvk.pf.toFixed(2), color: pvk.pf >= 1 ? "var(--qe-green)" : "var(--qe-red)" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Win %", value: pvk.winPct + "%" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Trades", value: pvk.nTrades })), (parsed.preview.warnings || []).map((w, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", gap: 6, alignItems: "center", fontSize: "0.54rem", color: "var(--qe-amber)" } }, /* @__PURE__ */ React.createElement("span", null, "!"), /* @__PURE__ */ React.createElement("span", null, w))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.52rem", color: "var(--qe-muted)" } }, "Fields below were auto-filled from the report \u2014 edit anything before creating. Nothing is saved until you confirm."))), /* @__PURE__ */ React.createElement(_MdlSec, { title: "Identity" }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "2fr 1fr", gap: "14px 12px" } }, /* @__PURE__ */ React.createElement(_MdlField, { label: "Name", error: touched && errors.name }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.name, onChange: (e) => set("name", e.target.value), placeholder: "e.g. BTC Macro Trend" })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Type" }, /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", value: f.type, onChange: (e) => set("type", e.target.value) }, MDL_TYPES.map(([v, l]) => /* @__PURE__ */ React.createElement("option", { key: v, value: v }, l)))), /* @__PURE__ */ React.createElement(_MdlField, { label: "Description", hint: "One or two lines \u2014 shown on the library card." }, /* @__PURE__ */ React.createElement("textarea", { className: "qe-input", rows: 2, value: f.desc, onChange: (e) => set("desc", e.target.value), style: { resize: "vertical", lineHeight: 1.4 } })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Tags", hint: "comma-separated" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.tags, onChange: (e) => set("tags", e.target.value), placeholder: "trend, core" })))), /* @__PURE__ */ React.createElement(_MdlSec, { title: "Source Binding", sub: "where the model was backtested (\xA73 \u2014 the model owns it)" }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "14px 12px" } }, /* @__PURE__ */ React.createElement(_MdlField, { label: "Source app" }, /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", value: f.app, onChange: (e) => set("app", e.target.value) }, MDL_SOURCE_APPS.concat(MDL_SOURCE_APPS.indexOf(f.app) < 0 && f.app ? [f.app] : []).map((a) => /* @__PURE__ */ React.createElement("option", { key: a }, a)))), /* @__PURE__ */ React.createElement(_MdlField, { label: "Symbol" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.symbol, onChange: (e) => set("symbol", e.target.value), placeholder: "@ES" })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Resolution" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.resolution, onChange: (e) => set("resolution", e.target.value), placeholder: "1 Minute" })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Point value" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", type: "number", step: "1", value: f.pointValue, onChange: (e) => set("pointValue", e.target.value), placeholder: "50" })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Currency" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.currency, onChange: (e) => set("currency", e.target.value), placeholder: "USD" })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Initial capital" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", type: "number", step: "1000", value: f.initialCapital, onChange: (e) => set("initialCapital", e.target.value) })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Commission" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.commission, onChange: (e) => set("commission", e.target.value) })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Slippage" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.slippage, onChange: (e) => set("slippage", e.target.value) })))), /* @__PURE__ */ React.createElement(_MdlSec, { title: "Risk & Sizing Preset" }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px 12px" } }, /* @__PURE__ */ React.createElement(_MdlField, { label: "Risk / trade (%)", error: touched && errors.riskPct }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", type: "number", step: "0.05", value: f.riskPct, onChange: (e) => set("riskPct", e.target.value) })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Match window (s)" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", type: "number", step: "5", value: f.matchWindow, onChange: (e) => set("matchWindow", e.target.value) })), /* @__PURE__ */ React.createElement(_MdlField, { label: "TP methodology" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.tp, onChange: (e) => set("tp", e.target.value), placeholder: "ATR \xD7 2.5" })), /* @__PURE__ */ React.createElement(_MdlField, { label: "SL methodology" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.sl, onChange: (e) => set("sl", e.target.value), placeholder: "ATR \xD7 1.2" }))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, marginTop: 2 } }, /* @__PURE__ */ React.createElement(Switch, { checked: f.regimeMult, onChange: () => set("regimeMult", !f.regimeMult), accent: "var(--qe-cyan)" }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.6rem", color: "var(--qe-sub)" } }, "Apply regime multiplier"))), /* @__PURE__ */ React.createElement(_MdlSec, { title: "Strategy" }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 14 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px 12px" } }, /* @__PURE__ */ React.createElement(_MdlField, { label: "Entry logic" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.entry, onChange: (e) => set("entry", e.target.value) })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Exit logic" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.exit, onChange: (e) => set("exit", e.target.value) }))), /* @__PURE__ */ React.createElement(_MdlField, { label: "Target universe" }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", value: f.universe, onChange: (e) => set("universe", e.target.value), placeholder: "e.g. BTCUSDT perp" })), /* @__PURE__ */ React.createElement(_MdlField, { label: "Notes", hint: "Freeform strategy definition." }, /* @__PURE__ */ React.createElement("textarea", { className: "qe-input", rows: 3, value: f.notes, onChange: (e) => set("notes", e.target.value), style: { resize: "vertical", lineHeight: 1.5 } })))))
  );
};
const ImportModal = ({ model, onClose, onDone }) => {
  const [step, setStep] = React.useState("source");
  const [file, setFile] = React.useState(null);
  const [preview, setPreview] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const doPreview = async (f) => {
    setBusy(true);
    setErr(null);
    setFile(f);
    try {
      const fd = new FormData();
      fd.append("file", f);
      fd.append("app_id", "multicharts");
      const pv = await _mdlUpload(`/models/${model.id}/backtest-upload?format=json&dry_run=1`, fd);
      setPreview(pv);
      setStep("preview");
    } catch (e) {
      setErr(e);
      setStep("error");
    }
    setBusy(false);
  };
  const doConfirm = async () => {
    if (!file || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("app_id", "multicharts");
      const res = await _mdlUpload(`/models/${model.id}/backtest-upload?format=json`, fd);
      onDone(res);
    } catch (e) {
      setErr(e);
      setStep("error");
      setBusy(false);
    }
  };
  const foot = busy ? { tone: "sub", busy: true, msg: step === "preview" ? "importing\u2026" : "parsing\u2026" } : err ? { tone: "err", msg: qeFootCause(err) + " \u2014 " + String(err.message || "").slice(0, 60) } : preview ? { tone: "ok", msg: `parsed ${preview.file} \xB7 nothing saved yet` } : { tone: "sub", msg: "ok \xB7 local \u2014 nothing uploaded yet" };
  const pvk = preview ? mdlRunKpis(preview.summary) : null;
  return /* @__PURE__ */ React.createElement(
    ModelDialog,
    {
      title: `Import Report \u2192 ${model.name}`,
      width: 480,
      onClose,
      foot,
      footer: step === "preview" ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: () => setStep("upload") }, "Back"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", disabled: busy, onClick: doConfirm }, "Confirm import")) : step === "error" ? /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: () => {
        setErr(null);
        setStep("upload");
      } }, "Try another file") : step === "upload" ? /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: () => setStep("source") }, "Back") : null
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, marginBottom: 14 } }, ["source", "upload", "preview"].map((s, i) => {
      const active = step === s;
      const done = ["source", "upload", "preview"].indexOf(step) > i || step === "error" && i < 2;
      return /* @__PURE__ */ React.createElement("div", { key: s, style: { flex: 1, display: "flex", alignItems: "center", gap: 5 } }, /* @__PURE__ */ React.createElement("span", { style: {
        width: 16,
        height: 16,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
        border: `1px solid ${active ? "var(--qe-cyan)" : done ? "var(--qe-green)" : "var(--qe-faint)"}`,
        color: active ? "var(--qe-cyan)" : done ? "var(--qe-green)" : "var(--qe-muted)",
        fontSize: "0.5rem",
        fontFamily: "var(--qe-mono)",
        fontWeight: 700
      } }, done ? "\u2713" : i + 1), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.5rem", textTransform: "uppercase", letterSpacing: "0.08em", color: active ? "var(--qe-cyan)" : "var(--qe-muted)" } }, s));
    })),
    step === "source" && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10 } }, /* @__PURE__ */ React.createElement(_MdlField, { label: "Source application", hint: "More backtesting apps will be supported over time." }, /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", defaultValue: "MultiCharts" }, /* @__PURE__ */ React.createElement("option", null, "MultiCharts"))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end" } }, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", onClick: () => setStep("upload") }, "Next \u2192"))),
    step === "upload" && /* @__PURE__ */ React.createElement("div", { style: { border: "1px dashed var(--qe-line-2)", padding: "26px 16px", textAlign: "center", background: "var(--qe-panel)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "1.4rem", color: "var(--qe-muted)", lineHeight: 1 } }, "\u2913"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginTop: 8 } }, "Pick a MultiCharts report"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", marginTop: 3 } }, ".xlsx or .xml \u2014 performance summary + trade list"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, justifyContent: "center", marginTop: 12 } }, busy ? /* @__PURE__ */ React.createElement(Spinner, { label: "parsing" }) : /* @__PURE__ */ React.createElement(_MdlFileBtn, { label: "Choose file\u2026", onFile: doPreview }))),
    step === "preview" && preview && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7 } }, /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "PARSED"), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.6rem", color: "var(--qe-text)" } }, preview.file)), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 7 } }, /* @__PURE__ */ React.createElement(KpiTile, { label: "Net Profit", value: _mdlMoney(pvk.net, 0), color: _mdlPl(pvk.net) }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Profit Factor", value: pvk.pf.toFixed(2), color: pvk.pf >= 1.3 ? "var(--qe-green)" : "var(--qe-text)" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Win %", value: pvk.winPct + "%" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Max DD", value: pvk.maxDDPct + "%", color: "var(--qe-red)" }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Sharpe", value: pvk.sharpe.toFixed(2) }), /* @__PURE__ */ React.createElement(KpiTile, { label: "Trades", value: pvk.nTrades })), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.54rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)" } }, preview.session_name, " \xB7 ", preview.trades_count, " trades \xB7 ", (preview.sheets || []).length, " sheets captured"), (preview.warnings || []).map((w, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", gap: 6, alignItems: "center", fontSize: "0.54rem", color: "var(--qe-amber)" } }, /* @__PURE__ */ React.createElement("span", null, "!"), /* @__PURE__ */ React.createElement("span", null, w)))),
    step === "error" && /* @__PURE__ */ React.createElement(
      EmptyState,
      {
        tone: "err",
        glyph: "\u2717",
        msg: "Import failed",
        hint: err ? String(err.message || qeFootCause(err)) : "Unrecognized file format."
      }
    )
  );
};
const ModelTabStrip = ({ models, active, onSelect, onNew }) => /* @__PURE__ */ React.createElement(
  TabStrip,
  {
    value: active,
    onChange: onSelect,
    tabs: [["overview", "Overview"], ...(models || []).map((m) => [m.id, m.name])],
    right: /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "qe-btn qe-btn-sm qe-btn-ghost",
        onClick: onNew,
        title: "New model",
        style: { alignSelf: "center", marginLeft: 6, fontSize: "0.9rem", lineHeight: 1, padding: "0 8px" }
      },
      "+"
    )
  }
);
const ModelsPage = () => {
  const { data, err, foot: ovFoot, reload } = useAnaJson("/api/models/overview");
  const models = data && data.models || [];
  const [active, setActive] = React.useState("overview");
  const [modal, setModal] = React.useState(null);
  const importDoneRef = React.useRef(null);
  const [toast, setToast] = React.useState(null);
  const [confirmDel, setConfirmDel] = React.useState(false);
  React.useEffect(() => {
    setConfirmDel(false);
  }, [active]);
  React.useEffect(() => {
    if (!confirmDel) return void 0;
    const t = setTimeout(() => setConfirmDel(false), 4e3);
    return () => clearTimeout(t);
  }, [confirmDel]);
  const model = active !== "overview" ? models.find((m) => m.id === active) || null : null;
  React.useEffect(() => {
    if (active !== "overview" && data && !models.some((m) => m.id === active)) setActive("overview");
  }, [data, active]);
  const toastTimer = React.useRef(null);
  const flash = (msg, tone = "ok") => {
    setToast({ msg, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2600);
  };
  React.useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);
  const loadCalc = (id) => {
    try {
      history.replaceState(null, "", "?model_id=" + id + window.location.hash);
    } catch (e) {
    }
    flash("Risk preset \u2192 Pre-Trade");
    setTimeout(() => window.qeNav && window.qeNav("Pre-Trade"), 400);
  };
  const onFormSave = async (res) => {
    setModal(null);
    await reload();
    if (res.kind === "updated") flash("Model updated");
    else if (res.kind === "created+imported") {
      flash("Model created + run imported");
      setActive(res.modelId);
    } else {
      flash("Model created");
      setActive(res.modelId);
    }
  };
  const deleteModel = async () => {
    if (!model) return;
    setConfirmDel(false);
    try {
      await _mdlSend("/api/models/" + model.id, "DELETE");
      setActive("overview");
      reload();
      flash("Model deleted");
    } catch (e) {
      flash("Delete failed: " + qeFootCause(e), "err");
    }
  };
  const onImportDone = (res) => {
    setModal(null);
    reload();
    if (importDoneRef.current) {
      try {
        importDoneRef.current();
      } catch (e) {
      }
      importDoneRef.current = null;
    }
    flash(`Backtest report imported (run #${res.run_id})`);
  };
  const subtitle = model ? `${model.name} \xB7 ${mdlTypeLabel(model.type)} model` : "reusable, exchange-agnostic trading models \xB7 performance via import";
  const headerActions = model ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: () => setModal("edit") }, "Edit"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-on", onClick: () => loadCalc(model.id) }, "\u21AA Load into Pre-Trade"), confirmDel ? /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", gap: 4, alignItems: "center" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "0.56rem", color: "var(--qe-red)", fontFamily: "var(--qe-mono)", fontWeight: 700, letterSpacing: "0.04em" } }, "DELETE \u201C", model.name, "\u201D + its runs?"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-danger", onClick: deleteModel }, "Confirm"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-ghost", onClick: () => setConfirmDel(false) }, "Cancel")) : /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-danger", onClick: () => setConfirmDel(true) }, "Delete")) : /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary", onClick: () => setModal("new") }, "+ New Model");
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "06 Models", style: { width: "100%", height: "100%", background: "var(--qe-bg)", display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "Models", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "Models", subtitle }, headerActions), /* @__PURE__ */ React.createElement(
    ModelTabStrip,
    {
      models,
      active,
      onSelect: setActive,
      onNew: () => setModal("new")
    }
  ), active === "overview" && (err && !data ? /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement(
    EmptyState,
    {
      tone: "err",
      glyph: "\u2717",
      msg: "models feed unavailable",
      hint: qeFootCause(err),
      cta: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: reload }, "Retry")
    }
  )) : /* @__PURE__ */ React.createElement(ModelOverview, { models, foot: ovFoot, onOpen: (m) => setActive(m.id), onNew: () => setModal("new") })), model && // key: a model switch remounts the whole view — no cross-model
  // stale frame / phantom report fetch (P7 audit LOW-2).
  /* @__PURE__ */ React.createElement(
    ModelView,
    {
      key: model.id,
      m: model,
      ovFoot,
      onImport: (refresh) => {
        importDoneRef.current = refresh || null;
        setModal("import");
      },
      onLoadCalc: () => loadCalc(model.id)
    }
  ), modal === "new" && /* @__PURE__ */ React.createElement(ModelFormModal, { onClose: () => setModal(null), onSave: onFormSave }), modal === "edit" && model && /* @__PURE__ */ React.createElement(ModelFormModal, { model, onClose: () => setModal(null), onSave: onFormSave }), modal === "import" && model && /* @__PURE__ */ React.createElement(ImportModal, { model, onClose: () => {
    importDoneRef.current = null;
    setModal(null);
  }, onDone: onImportDone }), toast && /* @__PURE__ */ React.createElement("div", { style: {
    position: "absolute",
    bottom: 16,
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: 60,
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "7px 14px",
    background: "var(--qe-card)",
    border: `1px solid ${toast.tone === "err" ? "var(--qe-red)" : "var(--qe-green)"}`,
    boxShadow: "0 8px 30px var(--qe-bg)"
  } }, /* @__PURE__ */ React.createElement("span", { style: { width: 7, height: 7, borderRadius: "50%", background: toast.tone === "err" ? "var(--qe-red)" : "var(--qe-green)" } }), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.6rem", color: "var(--qe-text)" } }, toast.msg)), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
Object.assign(window, { ModelsPage, ModelTabStrip, ModelFormModal, ImportModal });

;

/* ==== app-shell.jsx ==== */
const LiveValueDemo = ({ id, base, jitter = 2, fmt, style }) => {
  const [v, setV] = React.useState(base);
  React.useEffect(() => {
    const t = setInterval(() => {
      setV((prev) => +(prev + (Math.random() - 0.5) * jitter).toFixed(4));
    }, 900 + Math.random() * 700);
    return () => clearInterval(t);
  }, []);
  return /* @__PURE__ */ React.createElement(LiveValue, { id, value: v, format: fmt, style });
};
const DEMO_EQUITY = [82.2, 82.44, 82.1, 82.86, 83.4, 83.02, 83.95, 84.6, 84.18, 85.22, 85.9, 85.55, 86.4, 87.1, 86.72, 87.85, 88.4, 88.05, 89.1, 89.95];
const PrimitivesPage = () => /* @__PURE__ */ React.createElement("div", { className: "qe-scope", "data-screen-label": "00 Primitives", style: {
  width: "100%",
  height: "100%",
  background: "var(--qe-bg)",
  display: "flex",
  flexDirection: "column",
  overflow: "hidden"
} }, /* @__PURE__ */ React.createElement(TopNavStd, { page: "Primitives", variant: "line", dense: true }), /* @__PURE__ */ React.createElement(PageHeader, { title: "Primitives", subtitle: "standardized component vocabulary \xB7 every page is composed from these" }, /* @__PURE__ */ React.createElement(Badge, { tone: "warn" }, "DEV \xB7 NOT IN PRODUCTION NAV")), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, overflow: "auto", padding: 14 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 14 } }, /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Color tokens \xB7 neon on black"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8 } }, [
  ["--qe-green", "GREEN", "long \xB7 win \xB7 ok"],
  ["--qe-red", "RED", "short \xB7 loss \xB7 halt"],
  ["--qe-amber", "AMBER", "warn \xB7 defensive"],
  ["--qe-cyan", "CYAN", "primary accent \xB7 live"],
  ["--qe-blue", "BLUE", "secondary action"],
  ["--qe-magenta", "MAGENTA", "reserved \xB7 neutral hot"],
  ["--qe-text", "TEXT", "primary"],
  ["--qe-sub", "SUB", "secondary"]
].map(([v, n, d]) => /* @__PURE__ */ React.createElement("div", { key: v, style: { border: "1px solid var(--qe-line)", padding: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { height: 22, background: `var(${v})`, marginBottom: 4 } }), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.58rem", fontWeight: 700 } }, n), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "var(--qe-mono)", fontSize: "0.54rem", color: "var(--qe-muted)" } }, d))))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Type"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, /* @__PURE__ */ React.createElement("div", { className: "qe-hero-val" }, "82.20", /* @__PURE__ */ React.createElement("span", { className: "qe-hero-cents" }, ".001")), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "1.4rem", fontWeight: 700 } }, "BTCUSDT 93,412.10"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.86rem" } }, "0.012  \xB7  1,120.94 USDT  \xB7  -1.18%"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.66rem", color: "var(--qe-sub)" } }, "Tabular numbers, sharp corners, no anti-aliased curves."), /* @__PURE__ */ React.createElement("div", { className: "qe-lbl" }, "section label \xB7 uppercase \xB7 letter-spaced"))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Badges \xB7 status"), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Badges"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 4, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "OK"), /* @__PURE__ */ React.createElement(Badge, { tone: "warn" }, "WARN"), /* @__PURE__ */ React.createElement(Badge, { tone: "err" }, "LIMIT"), /* @__PURE__ */ React.createElement(Badge, { tone: "info" }, "LIVE"), /* @__PURE__ */ React.createElement(Badge, { tone: "blue" }, "PAPER"), /* @__PURE__ */ React.createElement(Badge, { tone: "mag" }, "SHADOW"), /* @__PURE__ */ React.createElement(Badge, { tone: "mute" }, "\u2014"))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Regimes"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 4, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(RegimeBadge, { tone: "trend" }), /* @__PURE__ */ React.createElement(RegimeBadge, { tone: "chop" }), /* @__PURE__ */ React.createElement(RegimeBadge, { tone: "neut" }), /* @__PURE__ */ React.createElement(RegimeBadge, { tone: "def" }), /* @__PURE__ */ React.createElement(RegimeBadge, { tone: "panic" }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Status dots"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 14, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(StatusDot, { tone: "ok", label: "WS", value: "93ms" }), /* @__PURE__ */ React.createElement(StatusDot, { tone: "warn", label: "DD", value: "WARN" }), /* @__PURE__ */ React.createElement(StatusDot, { tone: "err", label: "HALT", value: "LIMIT" }), /* @__PURE__ */ React.createElement(StatusDot, { tone: "info", label: "LIVE" }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Deltas"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 14, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(Delta, { value: "+1.93", pct: "+2.18" }), /* @__PURE__ */ React.createElement(Delta, { value: "-1.04", pct: "-1.18" }), /* @__PURE__ */ React.createElement(Delta, { value: "0.00", pct: "0.00" })))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Controls"), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Buttons"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-primary" }, "Primary"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn" }, "Secondary"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-success" }, "Success"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-danger" }, "Danger"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-ghost" }, "Ghost"))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Period selector"), /* @__PURE__ */ React.createElement(PeriodSelector, { options: [["7d", "7D"], ["30d", "30D"], ["90d", "90D"], ["ytd", "YTD"], ["all", "ALL"]], value: "30d", onChange: () => {
} })), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Inputs"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6 } }, /* @__PURE__ */ React.createElement("input", { className: "qe-input", placeholder: "symbol", style: { maxWidth: 140 } }), /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", style: { maxWidth: 120 } }, /* @__PURE__ */ React.createElement("option", null, "LIMIT"), /* @__PURE__ */ React.createElement("option", null, "MARKET")))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Stepper input"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { width: 110 } }, /* @__PURE__ */ React.createElement(StepperInput, { defaultValue: "94100.00", step: 0.1, decimals: 2, min: 0, color: "var(--qe-green)" })), /* @__PURE__ */ React.createElement("div", { style: { width: 80 } }, /* @__PURE__ */ React.createElement(StepperInput, { defaultValue: "2.5", step: 0.1, decimals: 1, min: 0 })))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Workspace lock"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(LockButton, { locked: false, onToggle: () => {
} }), /* @__PURE__ */ React.createElement(LockButton, { locked: true, onToggle: () => {
} }), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", maxWidth: 260, lineHeight: 1.5 } }, "single control in the top nav (left of the account picker) \xB7 freezes drag + resize on ", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, "every"), " workspace via ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "grid.setStatic()"), " \xB7 universal & persisted across tabs")))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Gauges (single primitive \xB7 color shifts at 60/80%)"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 14 } }, /* @__PURE__ */ React.createElement(Gauge, { label: "Exposure", value: 1.2, max: 5, current: "24%", maxLabel: "5.0\xD7 cap" }), /* @__PURE__ */ React.createElement(Gauge, { label: "Drawdown", value: 6.2, max: 10, current: "6.2%", maxLabel: "10.0% limit", ticks: [5, 8] }), /* @__PURE__ */ React.createElement(Gauge, { label: "Halt approach", value: 9.1, max: 10, current: "9.1%", maxLabel: "hard stop" }))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Empty states (single primitive \xB7 3 tones \xB7 replaces 7 ad-hoc)"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 } }, /* @__PURE__ */ React.createElement(EmptyState, { tone: "neutral", glyph: "\u25C7", msg: "No open positions" }), /* @__PURE__ */ React.createElement(EmptyState, { tone: "info", glyph: "\u3007", msg: "No data in window", cta: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm qe-btn-primary" }, "Open Calc \u2192") }), /* @__PURE__ */ React.createElement(EmptyState, { tone: "warn", glyph: "\u2205", msg: "Not backfilled", hint: "Run backfill to populate this signal.", cta: /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm" }, "Backfill \u2192") }))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Card variants"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 } }, /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement(Lbl, null, "default"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.7rem", color: "var(--qe-sub)" } }, "padding 6/8 \xB7 1px border")), /* @__PURE__ */ React.createElement(Card, { tight: true }, /* @__PURE__ */ React.createElement(Lbl, null, "tight"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.7rem", color: "var(--qe-sub)" } }, "padding 4/6")), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(Lbl, null, "pad"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.7rem", color: "var(--qe-sub)" } }, "padding 10/12 \xB7 for hero content")), /* @__PURE__ */ React.createElement(Card, { ticks: true }, /* @__PURE__ */ React.createElement(Lbl, null, "ticks"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.7rem", color: "var(--qe-sub)" } }, "corner-tick decoration")), /* @__PURE__ */ React.createElement(Card, { hot: true, style: { gridColumn: "1/-1" } }, /* @__PURE__ */ React.createElement(Lbl, null, "hot"), /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.7rem", color: "var(--qe-sub)" } }, "cyan border \xB7 used to signal primary focus")))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "PaneFoot \xB7 last-response line"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.5 } }, "16px footer mirroring the latest ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "engine_events"), " row driving the pane. Wire each ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "#pane-foot-X"), ' to SSE for the live "tail -f" feel.'), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 2, border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(PaneFoot, { tone: "ok", id: 1841, msg: "snapshot persisted \xB7 eq=82.20 \xB7 n=1247", ms: 8 }), /* @__PURE__ */ React.createElement(PaneFoot, { tone: "info", id: 1842, msg: "WS kline \xB7 last tick C=82.30 \xB7 stream age 1.2s", ms: 0 }), /* @__PURE__ */ React.createElement(PaneFoot, { tone: "warn", id: 1846, msg: "period pnl negative \xB7 -11.18 \xB7 winrate 38.7%", ms: 6 }), /* @__PURE__ */ React.createElement(PaneFoot, { tone: "err", id: 1849, msg: "exchange ws disconnected \xB7 attempt 3/5", ms: null }), /* @__PURE__ */ React.createElement(PaneFoot, { tone: "sub", id: 1847, msg: "preset SWING \xB7 dd window 30d \xB7 mode advisory", ms: 1 }))), /* @__PURE__ */ React.createElement(Card, { pad: true, style: { gridColumn: "1 / span 2" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Pane \xB7 canonical tile container"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.5 } }, "Every tile in the engine is a ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, `<Pane>`), ". Layout = head (20px, title + count + tag + right slot, then the auto ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "\u21BB"), " reload + ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "\xB7\xB7\xB7"), ") + body (scrolling) + foot (16px, optional) + resize grip. Click ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "\u21BB"), " to reload a single pane; if its body throws it self-heals to a recoverable error state.", /* @__PURE__ */ React.createElement("br", null), "Spacing: the pane gutter is the token ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "--qe-pane-gap"), " (4px) \u2014 ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "GridWorkspace"), " applies half as tile margin (neighbours sit one gap apart) and half as edge padding (workspace edges match). Pages never add their own padding around a workspace."), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, height: 160 } }, /* @__PURE__ */ React.createElement(
  Pane,
  {
    title: "Open Positions",
    count: 5,
    right: /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "LIVE"),
    foot: { tone: "info", id: 1844, msg: "reconciler synced \xB7 5 positions \xB7 4 working orders", ms: 42 }
  },
  /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.66rem", color: "var(--qe-sub)" } }, "pane body \u2014 fills, scrolls independently")
), /* @__PURE__ */ React.createElement(
  Pane,
  {
    title: "Regime \xB7 ATR",
    hot: true,
    tag: "VIEW",
    foot: { tone: "ok", id: 2010, msg: "regime fresh \xB7 atr_c=1.84", ms: 42 }
  },
  /* @__PURE__ */ React.createElement("div", { className: "qe-mono", style: { fontSize: "0.66rem", color: "var(--qe-sub)" } }, "hot variant = cyan border for primary focus pane")
))), /* @__PURE__ */ React.createElement(Card, { pad: true, style: { gridColumn: "1 / span 2", borderColor: "var(--qe-cyan)" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Reload + loading \xB7 the braille spinner standard (engine-wide)"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 10, lineHeight: 1.55 } }, "Loading is ", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, "always"), " the square 2\xD72 braille spinner \u2014 ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "<Spinner>"), " / ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "BrailleSquares"), ", the one busy indicator (boot splash, pane reloads, anywhere). The reload button rests as the circular arrow and swaps to the spinner while reloading; the veil darkens the body but the ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "PaneFoot"), " stays lit. No alternatives."), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 } }, /* @__PURE__ */ React.createElement(
  Pane,
  {
    title: "Open Positions",
    count: 5,
    right: /* @__PURE__ */ React.createElement(Badge, { tone: "ok" }, "LIVE"),
    resizable: false,
    style: { height: 108 },
    foot: { tone: "info", id: 1844, msg: "reconciler synced \xB7 click \u21BB to reload", ms: 42 }
  },
  /* @__PURE__ */ React.createElement(FieldList, { rows: [
    { label: "BTCUSDT", value: "+2.02", color: "green" },
    { label: "ETHUSDT", value: "+3.47", color: "green" },
    { label: "SOLUSDT", value: "-0.85", color: "red" }
  ] })
), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", justifyContent: "center", gap: 12, padding: "0 4px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", letterSpacing: "0.1em" } }, "<Spinner size label color> \xB7 the one loading indicator"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 22, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(Spinner, { size: "0.8rem" }), /* @__PURE__ */ React.createElement(Spinner, { label: "loading" }), /* @__PURE__ */ React.createElement(Spinner, { size: "1.1rem", label: "fetching", color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(Spinner, { size: "1.4rem", label: "computing", color: "var(--qe-amber)" })), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", lineHeight: 1.5 } }, "click the pane's ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-text-dim)" } }, "\u21BB"), " to see the reload state \u2014 same spinner, engine-wide")))), /* @__PURE__ */ React.createElement(Card, { pad: true, style: { gridColumn: "1 / span 2", borderColor: "var(--qe-cyan)" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "LiveValue \xB7 the refresh standard"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.6 } }, /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-cyan)" } }, "Rule:"), " async streams must target the ", /* @__PURE__ */ React.createElement("em", { style: { color: "var(--qe-text)" } }, "value"), ", never the surrounding card / row / pane. Swapping a whole body causes layout reflow + visible flicker. Each streamed number/string is wrapped in a", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)", margin: "0 4px" } }, `<LiveValue id="\u2026">`), "with a stable ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "data-live-id"), ". SSE/htmx OOB swaps target just that span."), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "example values"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "140px 1fr", rowGap: 6, columnGap: 10, marginTop: 6, fontSize: "0.64rem" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "pos.BTC.mark"), /* @__PURE__ */ React.createElement(LiveValueDemo, { id: "demo.btc.mark", base: 93580.4, fmt: (v) => v.toFixed(2), style: { fontSize: "0.78rem", fontWeight: 700, color: "var(--qe-text)" } }), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "pos.BTC.pnl"), /* @__PURE__ */ React.createElement(LiveValueDemo, { id: "demo.btc.pnl", base: 2.02, jitter: 0.4, fmt: (v) => (v >= 0 ? "+" : "") + v.toFixed(2), style: { fontSize: "0.78rem", fontWeight: 700, color: "var(--qe-green)" } }), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "regime.score"), /* @__PURE__ */ React.createElement(LiveValueDemo, { id: "demo.regime.score", base: 0.62, jitter: 0.02, fmt: (v) => v.toFixed(2), style: { fontSize: "0.78rem", fontWeight: 700, color: "var(--qe-cyan)" } }), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "ws.latency.ms"), /* @__PURE__ */ React.createElement(LiveValueDemo, { id: "demo.ws.latency", base: 93, jitter: 8, fmt: (v) => Math.round(v) + "ms", style: { fontSize: "0.78rem", fontWeight: 700, color: "var(--qe-green)" } }), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "fund.next"), /* @__PURE__ */ React.createElement(LiveValue, { id: "demo.fund.next", value: "04-25 16:00", style: { fontSize: "0.78rem", fontWeight: 700, color: "var(--qe-amber)" } }), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)", fontFamily: "var(--qe-mono)" } }, "stale signal"), /* @__PURE__ */ React.createElement(LiveValue, { id: "demo.btc.dom", value: "58.12", stale: true, style: { fontSize: "0.78rem", fontWeight: 700 } }))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(Lbl, null, "server-side wire (htmx OOB)"), /* @__PURE__ */ React.createElement("pre", { style: {
  fontFamily: "var(--qe-mono)",
  fontSize: "0.58rem",
  color: "var(--qe-text-dim)",
  background: "var(--qe-bg)",
  border: "1px solid var(--qe-line)",
  padding: 8,
  margin: "6px 0 0",
  lineHeight: 1.5,
  overflow: "auto"
} }, `{# server emits, every tick: #}
<span data-live-id="pos.BTC.mark"
      hx-swap-oob="innerHTML:[data-live-id='pos.BTC.mark']">
  93,580.40
</span>

{# or via SSE: #}
event: live.pos.BTC.mark
data: 93580.40`), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.6rem", color: "var(--qe-sub)", marginTop: 6, lineHeight: 1.5 } }, "Card body, pane chrome, table row \u2014 none of them re-render. Only the inner span morphs. Flash green/red is local + free.")))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "DataList \xB7 canonical row table"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.5 } }, "Replaces ad-hoc ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, `<table>`), ". Column schema + render fns + optional summary footer. Built-in ", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, "search \xB7 click-to-sort headers \xB7 auto filters"), " \u2014 on automatically for record lists (\u22655 rows, or \u22653 with a categorical column). Force with ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "tools"), "; opt a column out with ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "filter:false"), " / ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "sort:false"), "."), /* @__PURE__ */ React.createElement("div", { style: { margin: "0 -12px -10px" } }, /* @__PURE__ */ React.createElement(
  DataList,
  {
    selKey: "sym",
    tools: true,
    columns: [
      { key: "sym", label: "SYM", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-cyan)", fontWeight: 700 } }, r.sym) },
      { key: "dir", label: "SIDE", render: (r) => /* @__PURE__ */ React.createElement(Badge, { tone: r.dir === "L" ? "ok" : "err" }, r.dir === "L" ? "LONG" : "SHORT") },
      { key: "pnl", label: "PnL", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: r.pnl >= 0 ? "var(--qe-green)" : "var(--qe-red)", fontWeight: 700 } }, r.pnl >= 0 ? "+" : "", r.pnl) },
      { key: "pct", label: "%", align: "right", render: (r) => /* @__PURE__ */ React.createElement("span", { style: { color: r.pct >= 0 ? "var(--qe-green)" : "var(--qe-red)" } }, r.pct >= 0 ? "+" : "", r.pct, "%") }
    ],
    rows: [
      { sym: "BTCUSDT", dir: "L", pnl: 2.02, pct: 0.18 },
      { sym: "ETHUSDT", dir: "S", pnl: 3.47, pct: 0.19 },
      { sym: "SOLUSDT", dir: "L", pnl: -0.85, pct: -0.42 },
      { sym: "MKRUSDT", dir: "S", pnl: 1.1, pct: 0.07 },
      { sym: "BNBUSDT", dir: "L", pnl: 0.54, pct: 0.21 },
      { sym: "ADAUSDT", dir: "S", pnl: -1.2, pct: -0.63 }
    ],
    summary: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", null, "6 / 20"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, "\u03A3 +5.08"))
  }
))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "FieldList \xB7 canonical key\u2192value rows"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.5 } }, "The vertical sibling of ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "DataList"), ": one record's fields stacked as label \u2192 value. Single-line rows lock to the 20px pane-head height. Replaces ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "VRow"), " + the Active Parameters / Correlated Exposure / Performance Ratios variants."), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", marginBottom: 4 } }, "value tones \xB7 meta col \xB7 bar \xB7 emphasis"), /* @__PURE__ */ React.createElement(FieldList, { rows: [
  { label: "Risk/trade", value: "1.00%", color: "cyan" },
  { label: "Max DD", value: "10.0%" },
  { label: "Crypto \xB7 Majors", value: "+1,120.94", color: "green", meta: "50% cap", bar: { pct: 42, color: "var(--qe-green)" } },
  { label: "BTC Market Cap", value: "1,870 $B", color: "amber" },
  { label: "New (BTC)", value: "+1,120.94 USDT", emphasis: true }
] })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.5rem", color: "var(--qe-muted)", fontFamily: "var(--qe-mono)", marginBottom: 4 } }, "hint sublabels \xB7 cols=2"), /* @__PURE__ */ React.createElement(FieldList, { cols: 2, rows: [
  { label: "Sharpe", hint: "annualized", value: "2.18", color: "green" },
  { label: "Sortino", hint: "downside \u03C3", value: "2.48", color: "green" },
  { label: "Profit F.", hint: "\u03A3w / |\u03A3l|", value: "0.74", color: "red" },
  { label: "Expect.", hint: "mean R", value: "-0.36R", color: "red" }
] })))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "NewsTickerBar \xB7 footer marquee"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.5 } }, "Single-line async news feed. Holds ~1s then scrolls one full pass; pauses on hover. ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "React.memo"), " + inlined runs keep the animation from restarting under parent re-renders. No default feed \u2014 pass ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "news"), " rows (empty renders quiet)."), /* @__PURE__ */ React.createElement(
  NewsTickerBar,
  {
    label: "NEWS",
    meta: "DEMO FEED",
    news: [
      { id: "s1", source: "finnhub", impact: "high", headline: "CPI prints cooler than expected; rate-cut odds firm up", tickers: "SPY,TLT", published_at: "2026-04-25T18:42:00Z" },
      { id: "s2", source: "bwe", impact: "medium", headline: "BTC reclaims $94k as ETF inflows resume", tickers: "BTC,IBIT", published_at: "2026-04-25T18:05:00Z" },
      { id: "s3", source: "finnhub", impact: "low", headline: "Dollar steadies ahead of Friday payrolls", tickers: "DXY", published_at: "2026-04-25T17:20:00Z" }
    ]
  }
)), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Strip \xB7 info ticker"), /* @__PURE__ */ React.createElement(Strip, { items: [
  { label: "EXCH", value: "Binance" },
  { label: "LAT", value: "93ms", color: "var(--qe-green)" },
  { label: "REGIME", value: /* @__PURE__ */ React.createElement(RegimeBadge, { tone: "chop" }) },
  { label: "P&L\xB7D", value: /* @__PURE__ */ React.createElement(Delta, { value: "-0.00", pct: "-0.00", flat: true }) }
] }), /* @__PURE__ */ React.createElement(SecLbl, { rule: true, style: { marginTop: 14 } }, "Tabs"), /* @__PURE__ */ React.createElement(Tabs, { value: "overview", onChange: () => {
}, tabs: [
  ["overview", "Overview", null],
  ["equity", "Equity Curve", null],
  ["pairs", "Pairs", 8],
  ["mfemae", "MFE / MAE", null]
] })), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Number primitives"), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "HeroNumber"), /* @__PURE__ */ React.createElement(HeroNumber, { value: "82.20", ccy: "USDT", size: "1.8rem" })), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Stat"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 14 } }, /* @__PURE__ */ React.createElement(Stat, { label: "Available", value: "82.20", sub: "USDT" }), /* @__PURE__ */ React.createElement(Stat, { label: "DD 30d", value: "0.00%", sub: "limit 10%", color: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(Stat, { label: "Win Rate", value: "38.7%", sub: "12W \xB7 19L" }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "FlashCell"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement(FlashCell, { value: 93580.4, formatter: (v) => v.toFixed(2), style: { fontSize: "0.84rem", fontWeight: 700, color: "var(--qe-text)" } }), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)" } }, "flashes green/red on change \xB7 wire to SSE")))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Regime ribbon \xB7 Heat strip"), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "RegimeRibbon"), /* @__PURE__ */ React.createElement("div", { style: { width: "100%" } }, /* @__PURE__ */ React.createElement(RegimeRibbon, { height: 20, segments: [
  { tone: "neut", t: 3 },
  { tone: "chop", t: 5 },
  { tone: "trend", t: 2 },
  { tone: "chop", t: 6 },
  { tone: "def", t: 1 },
  { tone: "chop", t: 7 },
  { tone: "panic", t: 1 },
  { tone: "def", t: 2 }
] }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "HeatStrip"), /* @__PURE__ */ React.createElement("div", { style: { width: "100%" } }, /* @__PURE__ */ React.createElement(HeatStrip, { height: 20, data: Array.from({ length: 30 }, (_, i) => ({ date: `04-${String(i + 1).padStart(2, "0")}`, pnl: +((Math.sin(i * 1.7) + Math.cos(i * 0.5)) * 0.9).toFixed(2) })) }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Gauge tone"), /* @__PURE__ */ React.createElement("div", { style: { width: "100%", display: "flex", flexDirection: "column", gap: 10 } }, /* @__PURE__ */ React.createElement(Gauge, { label: "OK", value: 1.2, max: 5, current: "24%", maxLabel: "cap" }), /* @__PURE__ */ React.createElement(Gauge, { label: "WARN", value: 6.5, max: 10, current: "65%", maxLabel: "limit" }), /* @__PURE__ */ React.createElement(Gauge, { label: "ERR", value: 9.1, max: 10, current: "91%", maxLabel: "hard stop" })))), /* @__PURE__ */ React.createElement(Card, { pad: true, style: { gridColumn: "1 / span 2", borderColor: "var(--qe-cyan)" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Notifications \xB7 new primitives (Switch \xB7 Chip \xB7 Banner \xB7 Toast \xB7 Bell \xB7 Row)"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.5 } }, "Added with the notification system. ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "Switch"), " = boolean toggle \xB7", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, " Chip"), " = muteable filter pill \xB7", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, " Banner"), " = pinned alert bar (under nav) \xB7", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, " Toast"), " = transient corner popup, severity rail + auto-dismiss countdown \xB7", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, " NotifBell"), " = nav icon + unread badge \xB7", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, " NotifRow"), " = notification-center list item. The priority filter reuses", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, " PeriodSelector"), "; buttons/empty-state reuse existing primitives."), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Switch"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 18 } }, /* @__PURE__ */ React.createElement(Switch, { label: "Sound", checked: true }), /* @__PURE__ */ React.createElement(Switch, { label: "Desktop", checked: true, accent: "var(--qe-green)" }), /* @__PURE__ */ React.createElement(Switch, { label: "DND", checked: false }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Chip \xB7 filter"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(Chip, { label: "All", count: 8, active: true }), /* @__PURE__ */ React.createElement(Chip, { label: "Fills", count: 3, onMute: () => {
} }), /* @__PURE__ */ React.createElement(Chip, { label: "Risk", count: 2, onMute: () => {
} }), /* @__PURE__ */ React.createElement(Chip, { label: "Link", count: 1, muted: true, onMute: () => {
} }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Bell"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement(NotifBell, null), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)" } }, "+ red unread-count badge when count > 0"))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Banner \xB7 alert"), /* @__PURE__ */ React.createElement("div", { style: { width: "100%", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(Banner, { tone: "err", tag: "HALT", title: "CALCULATOR BLOCKED", detail: "Daily hard-stop 5.04% > 5.00% cap \xB7 new entries gated", time: "14:31:06", releaseIn: "0d 19h 21m 16s" }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Toast"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(Toast, { tone: "ok", tag: "FILLS", time: "14:31:06", title: "EXAMPLE \xB7 fill toast", detail: "demo content \xB7 not a live event" }), /* @__PURE__ */ React.createElement(Toast, { tone: "warn", tag: "RISK", time: "14:30:18", title: "Weekly loss 78% of limit", detail: "\u2212$1,840 of \u2212$2,360" }), /* @__PURE__ */ React.createElement(Toast, { tone: "err", tag: "RISK", time: "14:31:06", title: "CALCULATOR BLOCKED \u2014 hard-stop breached", detail: "DD 5.04% > 5.00% cap" }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "NotifRow"), /* @__PURE__ */ React.createElement("div", { style: { width: "100%", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(NotifRow, { ev: { id: "x1", ch: "RISK", pri: "risk", head: "EXAMPLE \xB7 risk notification row", detail: "demo content \xB7 not a live event", ts: Date.now() - 48e3, unread: true }, now: Date.now(), muted: false, onRead: () => {
}, onDismiss: () => {
} }), /* @__PURE__ */ React.createElement(NotifRow, { ev: { id: "x2", ch: "SYSTEM", pri: "routine", head: "EXAMPLE \xB7 routine system row", detail: "demo content \xB7 not a live event", ts: Date.now() - 24e4, unread: false }, now: Date.now(), muted: false, onRead: () => {
}, onDismiss: () => {
} })))), /* @__PURE__ */ React.createElement(Card, { pad: true, style: { gridColumn: "1 / span 2", borderColor: "var(--qe-cyan)" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Workspace \xB7 GridStack tiling in React + ECharts theme"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.55 } }, /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "GridWorkspace"), " owns the gs-* attributes imperatively, so React re-renders never reset the layout. ", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, "Drag"), " a pane by its title bar,", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, " resize"), " from any edge; the top-nav ", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, "lock"), " (\u{1F513}) freezes every workspace. The Equity + Sparkline panes render through ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "QE_ECHARTS_THEME"), " (canvas, vendored ECharts)."), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", height: 248, border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(GridWorkspace, { cols: 12, rows: 12, persistId: "primitives-demo" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 7, h: 7 }, /* @__PURE__ */ React.createElement(Pane, { title: "Equity", tag: "ECHARTS", foot: { tone: "ok", id: 2101, msg: "demo series \xB7 QE_ECHARTS_THEME", ms: 3 } }, /* @__PURE__ */ React.createElement(EquityChart, { data: DEMO_EQUITY, baseline: DEMO_EQUITY[0] }))), /* @__PURE__ */ React.createElement(GridItem, { x: 7, y: 0, w: 5, h: 7 }, /* @__PURE__ */ React.createElement(Pane, { title: "Positions", count: 3, foot: { tone: "sub", id: 2103, msg: "demo rows \xB7 static", ms: 0 } }, /* @__PURE__ */ React.createElement(FieldList, { rows: [
  { label: "BTCUSDT", value: "+2.02", color: "green" },
  { label: "ETHUSDT", value: "+3.47", color: "green" },
  { label: "SOLUSDT", value: "-0.85", color: "red" }
] }))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 7, w: 12, h: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Sparkline", hot: true, foot: { tone: "info", id: 2102, msg: "drag my title bar \xB7 resize my edges", ms: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "10px 8px" } }, /* @__PURE__ */ React.createElement(Sparkline, { data: DEMO_EQUITY, height: 44, color: "var(--qe-cyan)" }))))))))), /* @__PURE__ */ React.createElement(StatusFooter, null));
const _PagePlaceholder = (name, phase) => function PagePlaceholder() {
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", style: { width: "100%", height: "100%", background: "var(--qe-bg)", display: "flex", flexDirection: "column", overflow: "hidden" } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: name, variant: "line", dense: true }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", fontFamily: "var(--qe-mono)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "1.1rem", fontWeight: 700, color: "var(--qe-text)", letterSpacing: "0.06em" } }, name), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, fontSize: "0.6rem", color: "var(--qe-muted)", letterSpacing: "0.14em" } }, "REACT PORT \xB7 ", phase))), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
const QE_PAGES = {
  Dashboard: DashTiled,
  // P1 — real page (dash-tiled.jsx)
  "Pre-Trade": PreTradePage,
  // P3 — real page (pages-pretrade.jsx)
  Linkage: LinkagePage,
  // P4 — real page (pages-linkage.jsx)
  History: HistoryPage,
  // P4 — real page (pages-history.jsx)
  Analytics: AnalyticsPage,
  // P5 — real page (pages-analytics.jsx)
  Models: ModelsPage,
  // P7 — real page (pages-models.jsx)
  Regime: RegimePage,
  // P6 — real page (pages-regime.jsx)
  Config: ConfigPage,
  // P2 — real page (pages-config.jsx)
  Primitives: PrimitivesPage
};
const readHashPage = () => {
  const h = decodeURIComponent((window.location.hash || "").replace(/^#/, ""));
  return QE_PAGES[h] ? h : null;
};
const App = () => {
  const [page, setPage] = React.useState(() => {
    const fromHash = readHashPage();
    if (fromHash) return fromHash;
    try {
      const s = localStorage.getItem("qe.page");
      if (QE_PAGES[s]) return s;
    } catch (e) {
    }
    return "Dashboard";
  });
  window.qeNav = (p) => {
    if (QE_PAGES[p]) setPage(p);
  };
  React.useEffect(() => {
    const onHash = () => {
      const p = readHashPage();
      if (p) setPage(p);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  React.useEffect(() => {
    try {
      localStorage.setItem("qe.page", page);
    } catch (e) {
    }
    if (readHashPage() !== page) {
      try {
        history.replaceState(null, "", "#" + page);
      } catch (e) {
      }
    }
    const _brand = window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectName || "Quantamental Engine";
    document.title = _brand + " \u2014 " + page;
  }, [page]);
  const PageComp = QE_PAGES[page] || PrimitivesPage;
  return /* @__PURE__ */ React.createElement(NotificationProvider, null, /* @__PURE__ */ React.createElement(PageComp, null));
};
const _qeRoot = ReactDOM.createRoot(document.getElementById("root"));
_qeRoot.render(/* @__PURE__ */ React.createElement(App, null));
Object.assign(window, { App, PrimitivesPage, LiveValueDemo, QE_PAGES });

;
