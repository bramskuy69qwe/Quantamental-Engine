/* v3.0 app bundle — precompiled from frontend/src/ by build.mjs.
   DO NOT EDIT: regenerate with `npm run build`. Concatenated modules share
   window globals in load order (classic React.createElement). */

/* ==== primitives.jsx ==== */
const mockOhlc = (n = 60, base = 82.2, vol = 2) => {
  let c = base, out = [];
  const now = Date.UTC(2026, 3, 25, 20, 0, 0) - (n - 1) * 36e5;
  for (let i = 0; i < n; i++) {
    const o = c;
    c = Math.max(base * 0.86, Math.min(base * 1.16, c + (Math.random() - 0.49) * vol));
    const h = Math.max(o, c) + Math.random() * vol * 0.4;
    const l = Math.min(o, c) - Math.random() * vol * 0.4;
    out.push([now + i * 36e5, +o.toFixed(3), +c.toFixed(3), +l.toFixed(3), +h.toFixed(3)]);
  }
  const f = base / out[out.length - 1][2];
  return out.map((r) => [r[0], +(r[1] * f).toFixed(3), +(r[2] * f).toFixed(3), +(r[3] * f).toFixed(3), +(r[4] * f).toFixed(3)]);
};
const mockEquity = (n = 80, base = 82.2, vol = 0.8) => {
  let v = base;
  const out = [];
  for (let i = 0; i < n; i++) {
    v += (Math.random() - 0.49) * vol;
    v = Math.max(base * 0.86, Math.min(base * 1.18, v));
    out.push(+v.toFixed(3));
  }
  return out;
};
const mockSpark = (n = 24, base = 0, range = 1) => {
  let v = base, out = [];
  for (let i = 0; i < n; i++) {
    v += (Math.random() - 0.5) * range;
    out.push(+v.toFixed(3));
  }
  return out;
};
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
const EmptyState = ({ tone = "neutral", glyph = "\u2205", msg, hint, cta = null }) => /* @__PURE__ */ React.createElement("div", { className: `qe-empty ${tone === "neutral" ? "" : tone}` }, /* @__PURE__ */ React.createElement("div", { className: "qe-empty-glyph" }, glyph), /* @__PURE__ */ React.createElement("div", { className: "qe-empty-msg" }, msg), hint && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "var(--qe-fs-xs)", color: "var(--qe-muted)", textAlign: "center" } }, hint), cta && /* @__PURE__ */ React.createElement("div", { className: "qe-empty-cta" }, cta));
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
const useLiveTicker = (base, { jitter = 1, intervalMs = 1100, decimals = 2, clamp = null } = {}) => {
  const [v, setV] = React.useState(base);
  React.useEffect(() => {
    const id = setInterval(() => {
      setV((prev) => {
        let next = prev + (Math.random() - 0.5) * jitter * 2;
        if (clamp) next = Math.max(clamp[0], Math.min(clamp[1], next));
        return +next.toFixed(decimals);
      });
    }, intervalMs + Math.random() * 400);
    return () => clearInterval(id);
  }, []);
  return v;
};
const LiveNumber = ({
  id,
  base,
  jitter = 1,
  intervalMs = 1100,
  decimals = 2,
  clamp = null,
  format,
  style = {},
  className = ""
}) => {
  const v = useLiveTicker(base, { jitter, intervalMs, decimals, clamp });
  const fmt = format || ((x) => decimals > 0 ? x.toFixed(decimals) : String(Math.round(x)));
  return /* @__PURE__ */ React.createElement(LiveValue, { id, value: v, format: fmt, style, className });
};
const LivePct = ({ id, base, jitter = 0.05, intervalMs = 1300, decimals = 2, style = {} }) => {
  const v = useLiveTicker(base, { jitter, intervalMs, decimals });
  const col = v > 0 ? "var(--qe-green)" : v < 0 ? "var(--qe-red)" : "var(--qe-sub)";
  const sign = v > 0 ? "+" : "";
  return /* @__PURE__ */ React.createElement(
    LiveValue,
    {
      id,
      value: v,
      format: (x) => sign + x.toFixed(decimals) + "%",
      style: { color: col, fontWeight: 700, ...style }
    }
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
let QE_EVENT_SEQ = 0;
const nextEventId = (base = 0) => {
  QE_EVENT_SEQ = Math.max(QE_EVENT_SEQ, base | 0) + 2 + Math.floor(Math.random() * 6);
  return QE_EVENT_SEQ;
};
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
  const startRef = React.useRef(0);
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
    startRef.current = typeof performance !== "undefined" ? performance.now() : Date.now();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      const elapsed = Math.max(1, Math.round(now - startRef.current));
      const f = footRef.current;
      setErrored(false);
      if (f) setRFoot({ tone: "ok", id: nextEventId(f.id), msg: "reloaded \xB7 resynced from source", ms: elapsed });
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
  ), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, padding: "5px 7px", overflow: "auto", ...bodyStyle } }, /* @__PURE__ */ React.createElement(PaneErrorBoundary, { key: nonce, title, onReload: doRefresh, onError: () => setErrored(true) }, children)), effFoot && /* @__PURE__ */ React.createElement(PaneFoot, { ...effFoot }), refreshing && /* @__PURE__ */ React.createElement(PaneReloadBody, { hasFoot: !!effFoot }), resizable && /* @__PURE__ */ React.createElement("span", { className: "qe-grip", title: "resize", style: { pointerEvents: "none" } }));
};
const DL_AUTO_MIN = 5;
const DL_AUTO_MIN_FACET = 3;
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
    if (distinct.length < 2) return;
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
    return /* @__PURE__ */ React.createElement(EmptyState, { tone: "neutral", glyph: "\u25C7", msg: emptyMsg });
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
    const feed = news || window.MOCK_REGIME && window.MOCK_REGIME.news || [];
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
const Switch = ({ checked = false, onChange, label = null, title = null, accent = "var(--qe-sub)" }) => /* @__PURE__ */ React.createElement("div", { onClick: onChange, title, style: { display: "flex", alignItems: "center", gap: 7, cursor: "pointer" } }, /* @__PURE__ */ React.createElement("span", { style: { width: 26, height: 14, background: checked ? accent : "var(--qe-faint)", position: "relative", flexShrink: 0, transition: "background .12s" } }, /* @__PURE__ */ React.createElement("span", { style: { position: "absolute", top: 2, left: checked ? 14 : 2, width: 10, height: 10, background: "var(--qe-bg)", transition: "left .12s" } })), label && /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.6rem", fontWeight: 600, color: checked ? "var(--qe-text)" : "var(--qe-muted)" } }, label));
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
  mockOhlc,
  mockEquity,
  mockSpark,
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
  useLiveTicker,
  LiveNumber,
  LivePct,
  LiveClock,
  asciiSpark,
  ASCII_SPARK,
  Pane,
  PaneHead,
  PaneFoot,
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
    backgroundColor: "#000",
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
        backgroundColor: "#000",
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

/* ==== nav-and-data.jsx ==== */
const MOCK = {
  ohlc: mockOhlc(80, 82.2, 1.8),
  equity: mockEquity(120, 82.2, 0.6),
  account: { name: "Account 1 (Binance)", env: "LIVE", balance: "82.20", ccy: "USDT" },
  exchange: {
    name: "Binance",
    market: "USD-M Futures",
    serverTime: "2026-04-25 20:08:36 UTC",
    latency: 93,
    makerFee: "0.020%",
    takerFee: "0.050%",
    ws: { connected: true, ping: 93, age: "1s" }
  },
  pnl: {
    daily: { abs: "-0.00", pct: "-0.00" },
    weekly: { abs: "-0.00", pct: "-0.00" },
    monthly: { abs: "-11.18", pct: "-11.97" },
    ytd: { abs: "-11.18", pct: "-11.97" },
    unrealized: "+5.23"
  },
  equityBlocks: [
    { label: "Available", value: "43.81" },
    { label: "Margin Used", value: "38.39" },
    { label: "Unrealized", value: "+5.23" },
    { label: "BOD Equity", value: "82.20" },
    { label: "SOW Equity", value: "82.20" },
    { label: "Max Eq (BOD)", value: "82.20" },
    { label: "Min Eq (BOD)", value: "82.20" },
    { label: "Total IP", value: "0.00" },
    { label: "Total GL", value: "0.00" }
  ],
  risk: {
    exposure: { v: 2.93, max: 5, ok: true, current: "2.93\xD7", maxLabel: "5.0\xD7" },
    drawdown: { v: 11.97, max: 10, ok: false, current: "11.97%", maxLabel: "10.0%" },
    weeklyDD: { v: 0, max: 5, ok: true, current: "0.00%", maxLabel: "5.0%" },
    positions: { open: 5, max: 20 },
    fundingExposure: null,
    sectorExposure: null,
    ddState: "ok",
    weeklyState: "ok"
  },
  params: [
    { label: "Risk/trade", value: "1.00%", tone: "cyan" },
    { label: "Max W-loss", value: "5.0%", tone: "text" },
    { label: "Max DD", value: "10.0%", tone: "text" },
    { label: "Max exposure", value: "5.0\xD7", tone: "text" },
    { label: "Max positions", value: "10", tone: "text" },
    { label: "Max corr.", value: "50%", tone: "text" }
  ],
  regime: { tone: "chop", label: "RISK-ON CHOPPY", score: 0.62, age: "48s ago" },
  april: {
    label: "April 2026",
    pnl: "-11.18",
    pnlPct: "-11.97",
    trades: 31,
    wins: 12,
    losses: 19,
    winrate: 38.7,
    avgRR: 1.2,
    avgP: 1.23,
    avgL: -1.02,
    maxDD: 12.24,
    vol: "$2,168",
    fee: "$2.54",
    longs: 19,
    shorts: 12,
    topPairs: ["STOUSDT", "JCTUSDT", "AIOTUSDT"]
  },
  // recent trades for tickers
  recent: [
    { sym: "STOUSDT", dir: "L", pnl: 0.82, pct: 1, t: "04-25 18:43" },
    { sym: "BTCUSDT", dir: "S", pnl: 1.93, pct: 0.47, t: "04-25 17:25" },
    { sym: "JCTUSDT", dir: "S", pnl: -1.04, pct: -1.04, t: "04-25 16:22" },
    { sym: "AIOTUSDT", dir: "L", pnl: 0.41, pct: 0.45, t: "04-25 14:08" },
    { sym: "STOUSDT", dir: "L", pnl: -1.12, pct: -1.32, t: "04-25 11:55" },
    { sym: "ETHUSDT", dir: "L", pnl: -0.55, pct: -0.36, t: "04-24 22:48" }
  ],
  // mock open positions for variants that show some
  positionsOpen: [
    { sym: "BTCUSDT", dir: "L", size: "0.012", entry: "93412.10", mark: "93580.40", pnl: 2.02, pct: 0.18, tp: "94100.00", sl: "93180.00", mfe: 2.41, mae: -0.18, fee: "-0.06", age: "1h 12m" },
    { sym: "ETHUSDT", dir: "S", size: "0.55", entry: "3214.50", mark: "3208.20", pnl: 3.47, pct: 0.19, tp: "3185.00", sl: "3232.00", mfe: 4.21, mae: -0.92, fee: "-0.08", age: "42m" },
    { sym: "SOLUSDT", dir: "L", size: "2.4", entry: "138.42", mark: "139.21", pnl: 1.9, pct: 0.57, tp: "141.10", sl: "137.20", mfe: 2.12, mae: -0.34, fee: "-0.04", age: "18m" },
    { sym: "AVAXUSDT", dir: "L", size: "8.2", entry: "42.18", mark: "42.04", pnl: -1.15, pct: -0.33, tp: "43.20", sl: "41.60", mfe: 0.84, mae: -1.42, fee: "-0.05", age: "2h 31m" },
    { sym: "LINKUSDT", dir: "S", size: "12.6", entry: "21.84", mark: "21.92", pnl: -1.01, pct: -0.37, tp: "21.20", sl: "22.10", mfe: 0.42, mae: -1.18, fee: "-0.06", age: "56m" }
  ],
  ordersOpen: [
    { sym: "DOGEUSDT", side: "SELL", type: "STP", qty: "120", price: "0.1841", tp: "0.1812", sl: "0.1862", age: "21m" },
    { sym: "WIFUSDT", side: "BUY", type: "LMT", qty: "24", price: "2.412", tp: "2.481", sl: "2.380", age: "14m" },
    { sym: "PEPEUSDT", side: "BUY", type: "LMT", qty: "4.2M", price: "0.00001214", tp: "0.0000128", sl: "0.0000118", age: "3m" },
    { sym: "ARBUSDT", side: "SELL", type: "STP", qty: "80", price: "0.842", tp: "0.818", sl: "0.851", age: "1h 04m" }
  ],
  signals: [
    { key: "BTC.D", v: "58.12", d: "+0.21", tone: "up" },
    { key: "USDT.D", v: "4.81", d: "-0.03", tone: "dn" },
    { key: "10Y", v: "4.21%", d: "+2bp", tone: "up" },
    { key: "DXY", v: "104.2", d: "-0.18", tone: "dn" },
    { key: "VIX", v: "13.8", d: "-0.42", tone: "dn" },
    { key: "BTC.OI", v: "$32.1B", d: "+1.8%", tone: "up" },
    { key: "FUND\xB7BTC", v: "+0.012%", d: "+0.001%", tone: "up" },
    { key: "RVOL\xB71D", v: "0.84", d: "-0.06", tone: "dn" },
    { key: "BTC.MCAP", v: "$1.87T", d: "+0.4%", tone: "up" },
    { key: "ETH.D", v: "17.4", d: "+0.08", tone: "up" },
    { key: "GOLD", v: "2641", d: "-4.2", tone: "dn" },
    { key: "WTI", v: "71.84", d: "+0.42", tone: "up" }
  ],
  logs: [
    { t: "20:08:34", tag: "WS", msg: "Market WS connected.", tone: "ok" },
    { t: "20:08:34", tag: "WS", msg: "Market WS connecting (2 streams, attempt 1)", tone: "info" },
    { t: "20:08:32", tag: "REG", msg: "Regime: neutral \xD71.0 (high)", tone: "sub" },
    { t: "20:08:24", tag: "WS", msg: "No market streams to subscribe \u2014 sleeping 10s.", tone: "sub" },
    { t: "20:08:14", tag: "WS", msg: "No market streams to subscribe \u2014 sleeping 10s.", tone: "sub" },
    { t: "20:08:02", tag: "ENG", msg: "Snapshot persisted (eq=82.20, n=1247).", tone: "sub" },
    { t: "20:07:48", tag: "REG", msg: "Regime transition: NEUT \u2192 CHOP (score 0.62).", tone: "info" },
    { t: "20:07:21", tag: "RISK", msg: "DD 30d 11.97% > 10.0% cap. ADVISORY \u2014 no auto-halt.", tone: "sub" },
    { t: "20:06:55", tag: "OM", msg: "Order 504678492 partial fill 0.42/0.55 @ 3214.50.", tone: "sub" },
    { t: "20:06:11", tag: "EXEC", msg: "calc c-4f29bb \u2192 fill linked (\u2206 entry +0.02%).", tone: "ok" }
  ]
};
const NAV_ITEMS = ["Dashboard", "Pre-Trade", "Linkage", "History", "Analytics", "Models", "Regime", "Primitives"];
const QE_CLOCK_OFFSET = 0;
const qeClockFmt = (t) => {
  const s = new Date(t.getTime() + QE_CLOCK_OFFSET).toISOString();
  return s.slice(0, 10) + " " + s.slice(11, 19) + " UTC";
};
const QE_LIVE = { lat: 93, pnlD: -0, pnlW: -0.02, pnlM: -11.18, eventsK: 12.4 };
(function() {
  const subs = /* @__PURE__ */ new Set();
  const step = (k, jitter, clamp, decimals = 2) => {
    let v = QE_LIVE[k] + (Math.random() - 0.5) * jitter * 2;
    if (clamp) {
      if (v < clamp[0]) v = clamp[0] + (clamp[0] - v);
      if (v > clamp[1]) v = clamp[1] - (v - clamp[1]);
      v = Math.max(clamp[0], Math.min(clamp[1], v));
    }
    QE_LIVE[k] = +v.toFixed(decimals);
  };
  setInterval(() => {
    step("lat", 6, [60, 180], 0);
    step("pnlD", 0.08, [-1.2, 1.2], 2);
    step("pnlW", 0.04, [-2.4, 2.4], 2);
    step("pnlM", 0.05, [-11.5, -10.9], 2);
    step("eventsK", 0.05, [12.4, 99], 1);
    subs.forEach((f) => f());
  }, 1300);
  window.useQeLive = (key) => {
    const [, force] = React.useReducer((x) => x + 1, 0);
    React.useEffect(() => {
      subs.add(force);
      return () => subs.delete(force);
    }, []);
    return QE_LIVE[key];
  };
})();
const QE_POS = {};
const _posWalk = (sym, base) => QE_POS[sym] || (QE_POS[sym] = { v: base, base, subs: /* @__PURE__ */ new Set(), lo: null, hi: null });
setInterval(() => {
  Object.values(QE_POS).forEach((w) => {
    var _a, _b;
    const lo = (_a = w.lo) != null ? _a : w.base * 0.997, hi = (_b = w.hi) != null ? _b : w.base * 1.003;
    let v = w.v + (Math.random() - 0.5) * w.base * 18e-4;
    if (v > hi) v = hi - (v - hi);
    if (v < lo) v = lo + (lo - v);
    w.v = Math.max(lo, Math.min(hi, v));
    w.subs.forEach((f) => f());
  });
}, 1100);
const _posDerive = (r, mark) => {
  const dir = r.dir === "L" ? 1 : -1, size = parseFloat(r.size);
  const pnl = r.pnl + (mark - parseFloat(r.mark)) * size * dir;
  return { mark, pnl, pct: pnl / (parseFloat(r.entry) * size) * 100 };
};
window.useQePosMark = (r) => {
  var _a, _b;
  const w = _posWalk(r.sym, parseFloat(r.mark));
  const tp = parseFloat((_a = r.tp) != null ? _a : r.tp_live), sl = parseFloat((_b = r.sl) != null ? _b : r.sl_live);
  if (isFinite(tp) && isFinite(sl)) {
    const hiCap = Math.max(tp, sl), loCap = Math.min(tp, sl), m = (hiCap - loCap) * 0.05;
    w.lo = Math.max(w.base * 0.997, loCap + m);
    w.hi = Math.min(w.base * 1.003, hiCap - m);
    if (!(w.lo < w.hi)) {
      w.lo = w.base * 0.999;
      w.hi = w.base * 1.001;
    }
  }
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    w.subs.add(force);
    return () => w.subs.delete(force);
  }, [w]);
  return _posDerive(r, w.v);
};
window.useQeUnrealSum = () => {
  const rows = MOCK.positionsOpen;
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    const ws = rows.map((r) => _posWalk(r.sym, parseFloat(r.mark)));
    ws.forEach((w) => w.subs.add(force));
    return () => ws.forEach((w) => w.subs.delete(force));
  }, []);
  return rows.reduce((s, r) => s + _posDerive(r, _posWalk(r.sym, parseFloat(r.mark)).v).pnl, 0);
};
const SharedPct = ({ id, k }) => {
  const v = window.useQeLive(k);
  const col = v > 0 ? "var(--qe-green)" : v < 0 ? "var(--qe-red)" : "var(--qe-sub)";
  return /* @__PURE__ */ React.createElement(LiveValue, { id, value: v, format: (x) => (x > 0 ? "+" : "") + x.toFixed(2) + "%", style: { color: col, fontWeight: 700 } });
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
  const lat = window.useQeLive("lat");
  const pnlM = window.useQeLive("pnlM");
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
  } }, /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)", letterSpacing: "0.1em" } }, "WORKSPACE"), /* @__PURE__ */ React.createElement("div", { className: "qe-period", style: { opacity: dim, pointerEvents: interactive ? "auto" : "none" } }, presets.map((p) => /* @__PURE__ */ React.createElement("button", { key: p, className: preset === p ? "on" : "", onClick: guard(() => onPreset(p)) }, p))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 4, opacity: dim, pointerEvents: interactive ? "auto" : "none" } }, /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: guard(onSave), title: "Save current layout" }, "\u2913 Save"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: guard(onLoad), title: "Load saved layout" }, "\u2912 Load"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", onClick: guard(onCreate), title: "New workspace from default", style: { width: 22, padding: 0, justifyContent: "center" } }, "+"), flash && /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.54rem", color: flash[0] === "\u2713" ? "var(--qe-green)" : "var(--qe-amber)" } }, flash)), !interactive && /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.5rem", color: "var(--qe-faint)", letterSpacing: "0.06em" } }, "\xB7 dashboard only"), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement(Strip, { dense: true, items: [
    { label: "EXCH", value: "Binance" },
    { label: "LAT", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.lat", value: lat, format: (x) => Math.round(x) + "ms", style: { color: lat < 120 ? "var(--qe-green)" : "var(--qe-amber)", fontWeight: 700 } }) },
    { label: "REGIME", value: /* @__PURE__ */ React.createElement(RegimeBadge, { tone: MOCK.regime.tone }) },
    { label: "P&L\xB7D", value: /* @__PURE__ */ React.createElement(SharedPct, { id: "ws.pnl.d", k: "pnlD" }) },
    { label: "P&L\xB7W", value: /* @__PURE__ */ React.createElement(SharedPct, { id: "ws.pnl.w", k: "pnlW" }) },
    { label: "P&L\xB7M", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.pnl.m", value: pnlM / 93.38 * 100, format: (x) => (x > 0 ? "+" : "") + x.toFixed(2) + "%", style: { color: pnlM < 0 ? "var(--qe-red)" : "var(--qe-green)", fontWeight: 700 } }) },
    { label: "OPEN", value: `${MOCK.positionsOpen.length}/20`, color: "var(--qe-cyan)" },
    { label: "EXP", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.exp", value: MOCK.risk.exposure.v, format: (x) => x.toFixed(2) + "\xD7" }) },
    { label: "DD", value: /* @__PURE__ */ React.createElement(LiveValue, { id: "ws.dd", value: 0, format: (x) => x.toFixed(2) + "%" }) }
  ] }), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", disabled: true, title: "Add pane \u2014 planned, not wired in this build", style: { opacity: 0.4, cursor: "default" } }, "\u229E Pane"), /* @__PURE__ */ React.createElement("button", { className: "qe-btn qe-btn-sm", disabled: true, title: "Pop out \u2014 planned, not wired in this build", style: { opacity: 0.4, cursor: "default" } }, "\u2922 Pop"));
};
const TopNavStd = ({ page = "Dashboard", onChange, variant = "line", dense = false }) => {
  const [locked, toggleLock] = useWorkspaceLock();
  const navLat = window.useQeLive("lat");
  const nav = onChange || ((p) => {
    if (window.qeNav) window.qeNav(p);
  });
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
  ), /* @__PURE__ */ React.createElement("select", { className: "qe-input qe-select", style: { height: 22, fontSize: "0.62rem", width: 175 }, defaultValue: "acc1" }, /* @__PURE__ */ React.createElement("option", { value: "acc1" }, "Account 1 (Binance)"), /* @__PURE__ */ React.createElement("option", { value: "acc2", disabled: true }, "Bybit Linear (Test) \u2014 inactive"))), /* @__PURE__ */ React.createElement(StatusDot, { tone: MOCK.exchange.ws.connected ? "ok" : "err", label: "WS", value: MOCK.exchange.ws.connected ? /* @__PURE__ */ React.createElement(LiveValue, { id: "nav.lat", value: navLat, format: (x) => Math.round(x) + "ms" }) : "down" }), /* @__PURE__ */ React.createElement("span", { style: {
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
  ), /* @__PURE__ */ React.createElement(NotifBell, null)))), /* @__PURE__ */ React.createElement(NotifBanner, null), /* @__PURE__ */ React.createElement(WorkspaceBar, { interactive: page === "Dashboard" }));
};
const MOCK_WATCHLIST = [
  { sym: "BTCUSDT", last: "93580.40", d: 0.18, vol: "1.2M" },
  { sym: "ETHUSDT", last: "3208.20", d: -0.19, vol: "842K" },
  { sym: "SOLUSDT", last: "139.21", d: 0.57, vol: "412K" },
  { sym: "AVAXUSDT", last: "42.04", d: -0.33, vol: "118K" },
  { sym: "LINKUSDT", last: "21.92", d: 0.18, vol: "88K" },
  { sym: "DOGEUSDT", last: "0.1842", d: 0.41, vol: "2.1M" },
  { sym: "WIFUSDT", last: "2.412", d: 1.84, vol: "620K" },
  { sym: "ARBUSDT", last: "0.842", d: -1.18, vol: "318K" },
  { sym: "PEPEUSDT", last: "0.0000121", d: 2.84, vol: "1.8B" },
  { sym: "XRPUSDT", last: "0.5184", d: -0.42, vol: "1.1M" }
];
const StatusFooter = () => {
  const lat = window.useQeLive("lat");
  const eventsK = window.useQeLive("eventsK");
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
  } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, (window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectShortName || "QRE") + " " + (window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectVersion || "v3")), /* @__PURE__ */ React.createElement("span", null, "\xB7"), /* @__PURE__ */ React.createElement("span", null, "tasks queue 0"), /* @__PURE__ */ React.createElement("span", null, "\xB7"), /* @__PURE__ */ React.createElement("span", null, "events ", /* @__PURE__ */ React.createElement(LiveValue, { id: "sb.events", value: eventsK, format: (x) => x.toFixed(1) + "k" })), /* @__PURE__ */ React.createElement("span", null, "\xB7"), /* @__PURE__ */ React.createElement("span", null, "uptime 13d 4h"), /* @__PURE__ */ React.createElement("div", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, "\u25CF bus"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, "\u25CF db"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-green)" } }, "\u25CF ws ", /* @__PURE__ */ React.createElement(LiveValue, { id: "sb.lat", value: lat, format: (x) => Math.round(x) + "ms", style: { color: "var(--qe-muted)", marginLeft: 2 } })), /* @__PURE__ */ React.createElement(LiveClock, { id: "sb.clock", format: qeClockFmt, style: { color: "var(--qe-muted)" } }));
};
Object.assign(window, {
  MOCK,
  NAV_ITEMS,
  TopNavStd,
  WorkspaceBar,
  StatusFooter,
  MOCK_WATCHLIST,
  QE_CLOCK_OFFSET,
  qeClockFmt,
  qeMockClockFmt: qeClockFmt
  // P0 compat alias — drop once all page modules use qeClockFmt
});

;

/* ==== notifications.jsx ==== */
const NotifCtx = React.createContext(null);
const N_CHANNELS = ["FILLS", "RISK", "REGIME", "SYSTEM", "LINK", "NEWS"];
const N_ACTIONS = {
  FILLS: ["View order", "order detail"],
  RISK: ["Review risk", "risk panel"],
  REGIME: ["Open Regime", "regime page"],
  SYSTEM: ["Details", "system log"],
  LINK: ["Link trades", "linkage queue"],
  NEWS: ["Read", "news feed"]
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
  regime: () => _rnd([
    { ch: "REGIME", pri: "risk", head: "Regime \u2192 RISK-OFF PANIC", detail: "was DEFENSIVE \xB7 size \xD70.7 \u2192 \xD70.25" },
    { ch: "REGIME", pri: "routine", head: "Regime \u2192 DEFENSIVE", detail: "was NEUTRAL \xB7 size \xD71.0 \u2192 \xD70.7 \xB7 RVol 2.1\u03C3" },
    { ch: "REGIME", pri: "routine", head: "Regime \u2192 RISK-ON TREND", detail: "was NEUTRAL \xB7 size \xD71.0 \u2192 \xD71.2" }
  ]),
  risk: () => _rnd([
    { ch: "RISK", pri: "risk", head: `Weekly loss ${78 + Math.floor(Math.random() * 12)}% of limit`, detail: `\u2212$${(3.1 + Math.random() * 0.6).toFixed(2)} of \u2212$4.11 \xB7 1 more stop trips the cap` },
    { ch: "RISK", pri: "risk", head: `Daily drawdown ${_px(3.5 + Math.random(), 1)}% \u2014 approaching 5.0% cap`, detail: "position sizing throttled to \xD70.5" }
  ]),
  halt: () => ({ ch: "RISK", pri: "halt", head: "TRADING HALTED \u2014 hard-stop breached", detail: "Realized DD 5.04% > 5.00% cap \xB7 all positions frozen" }),
  link: () => {
    const nl = (window.L_NEEDS_LINK || []).filter((o) => o.status === "NEEDS_MANUAL_REVIEW" || o.status === "UNLINKED").length || 5;
    const nc = (window.L_CLOSES || []).filter((c) => c.pending_reason).length || 3;
    return { ch: "LINK", pri: "risk", head: `Calc link window closes in 0${2 + Math.floor(Math.random() * 4)}:${10 + Math.floor(Math.random() * 49)}`, detail: `triage ${nl + nc} open \xB7 ${nl} orders below 6/6 \xB7 ${nc} closes to review` };
  },
  news: () => _rnd([
    { ch: "NEWS", pri: "risk", head: "HIGH-impact \xB7 US CPI in 10m", detail: "14:30 UTC \xB7 est 3.1% YoY \xB7 prev 3.4%" },
    { ch: "NEWS", pri: "routine", head: "FOMC minutes released", detail: "18:00 UTC \xB7 hawkish tilt flagged" }
  ]),
  ws: () => _rnd([
    { ch: "SYSTEM", pri: "routine", head: "Market WS reconnected", detail: "2 streams \xB7 108ms \xB7 gap 1.4s recovered" }
  ])
};
const N_STREAM = ["fill", "partial", "regime", "risk", "link", "news", "ws"];
const _nbase = Date.now();
const N_SEED = [
  { ch: "FILLS", pri: "routine", head: "FILLED \xB7 BUY 0.0420 BTC", detail: "@ 93,580.4 \xB7 slippage +0.4bp \xB7 order #A1903", age: 12, unread: true },
  { ch: "REGIME", pri: "risk", head: "Regime \u2192 RISK-OFF PANIC", detail: "was DEFENSIVE \xB7 size \xD70.7 \u2192 \xD70.25", age: 48, unread: true },
  { ch: "RISK", pri: "risk", head: "Drawdown 30d 11.97% \u2014 over 10.0% cap", detail: "\u2212$11.18 of \u2212$9.34 allowance \xB7 ADVISORY mode, no auto-halt", age: 95, unread: true },
  { ch: "SYSTEM", pri: "routine", head: "Market WS reconnected", detail: "2 streams \xB7 108ms \xB7 gap 1.4s recovered", age: 240, unread: false },
  { ch: "LINK", pri: "risk", head: "Calc link window closes in 04:12", detail: "triage 8 open \xB7 5 orders below 6/6 \xB7 3 closes to review", age: 360, unread: false },
  { ch: "FILLS", pri: "routine", head: "Order #A1888 partially filled 60%", detail: "SELL 0.018 / 0.030 ETH @ 3,208.0", age: 840, unread: false },
  { ch: "REGIME", pri: "routine", head: "Regime \u2192 DEFENSIVE", detail: "was NEUTRAL \xB7 size \xD71.0 \u2192 \xD70.7 \xB7 RVol 2.1\u03C3", age: 1860, unread: false }
].map((e, i) => ({ id: "seed" + i, ch: e.ch, pri: e.pri, head: e.head, detail: e.detail, unread: e.unread, ts: _nbase - e.age * 1e3 }));
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
      title: "TRADING HALTED",
      detail: /* @__PURE__ */ React.createElement(React.Fragment, null, "hard-stop 5.04% > 5.00% cap \xB7 positions frozen \xB7 ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--qe-sub)" } }, grass)),
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
const NotifSwitch = ({ label, on, onToggle, title }) => /* @__PURE__ */ React.createElement(Switch, { label, checked: on, onChange: onToggle, title });
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
  return /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", left: 10, bottom: 50, zIndex: 70, width: 198, background: "var(--qe-card)", border: "1px solid var(--qe-line-2)", boxShadow: "0 10px 30px rgba(0,0,0,0.6)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, padding: "5px 9px", borderBottom: "1px solid var(--qe-line)", background: "var(--qe-panel)" } }, /* @__PURE__ */ React.createElement("span", { style: { width: 6, height: 6, background: "var(--qe-cyan)" } }), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "var(--qe-ui)", fontSize: "0.54rem", fontWeight: 800, letterSpacing: "0.14em", color: "var(--qe-sub)" } }, "DEMO \xB7 FIRE EVENTS"), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { onClick: onHide, title: "Collapse demo panel", className: "qe-btn qe-btn-ghost qe-btn-sm", style: { height: 16, padding: "0 5px" } }, "\u2013")), /* @__PURE__ */ React.createElement("div", { style: { padding: 8, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5 } }, /* @__PURE__ */ React.createElement(Btn, { label: "Fill", k: "fill" }), /* @__PURE__ */ React.createElement(Btn, { label: "Partial", k: "partial" }), /* @__PURE__ */ React.createElement(Btn, { label: "Regime", k: "regime" }), /* @__PURE__ */ React.createElement(Btn, { label: "Risk", k: "risk" }), /* @__PURE__ */ React.createElement(Btn, { label: "Link", k: "link" }), /* @__PURE__ */ React.createElement(Btn, { label: "News", k: "news" }), /* @__PURE__ */ React.createElement(Btn, { label: "WS recon", k: "ws" }), /* @__PURE__ */ React.createElement(Btn, { label: "Burst \xD75", k: "burst" }), /* @__PURE__ */ React.createElement("button", { onClick: () => fire("halt"), className: "qe-btn qe-btn-sm qe-btn-danger", style: { gridColumn: "1 / -1", justifyContent: "center" } }, "\u26D4 HARD-STOP HALT")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, padding: "6px 9px", borderTop: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(NotifSwitch, { label: "Auto-stream", on: autostream, onToggle: onAuto }), /* @__PURE__ */ React.createElement("span", { className: "qe-grow" }), /* @__PURE__ */ React.createElement("button", { onClick: onReset, className: "qe-btn qe-btn-ghost qe-btn-sm" }, "RESET")));
};
function NotificationProvider({ children, demo = false }) {
  const [events, setEvents] = React.useState(N_SEED);
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
      ["fill", "regime", "risk", "ws", "partial"].forEach((k, i) => setTimeout(() => pushEvent(k), i * 420));
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
    setEvents(N_SEED.map((e) => ({ ...e })));
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
  }, className: "qe-btn qe-btn-sm qe-empty-cta" }, "Clear filters")) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(Group, { title: "Just now", rows: justNow }), /* @__PURE__ */ React.createElement(Group, { title: "Earlier today", rows: earlier }))), /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0, padding: "7px 11px", borderTop: "1px solid var(--qe-line)", background: "var(--qe-panel)", display: "flex", alignItems: "center", gap: 14 } }, /* @__PURE__ */ React.createElement(NotifSwitch, { label: "Sound", on: sound, onToggle: () => setSound((v) => !v), title: "Play a cue on incoming" }), /* @__PURE__ */ React.createElement(NotifSwitch, { label: "Desktop", on: desktop, onToggle: toggleDesktop, title: "Browser push notifications" }), /* @__PURE__ */ React.createElement(NotifSwitch, { label: "DND", on: dnd, onToggle: () => setDnd((v) => !v), title: "Do not disturb" }))), toasts.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", top: banner ? 92 : 62, right: open ? 370 : 8, zIndex: 60, display: "flex", flexDirection: "column", gap: 5, transition: "right .18s ease" } }, toasts.map((t) => /* @__PURE__ */ React.createElement(NotifToast, { key: t.id, ev: t, onClick: () => {
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
] })))), /* @__PURE__ */ React.createElement(Card, { pad: true }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "NewsTickerBar \xB7 footer marquee"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.5 } }, "Single-line async news feed. Holds ~1s then scrolls one full pass; pauses on hover. ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "React.memo"), " + inlined runs keep the animation from restarting under parent re-renders. Defaults to the Regime feed; pass ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "news"), " to override."), /* @__PURE__ */ React.createElement(
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
} }), /* @__PURE__ */ React.createElement(Chip, { label: "News", count: 1, muted: true, onMute: () => {
} }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Bell"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement(NotifBell, null), /* @__PURE__ */ React.createElement("span", { className: "qe-mono", style: { fontSize: "0.56rem", color: "var(--qe-muted)" } }, "+ red unread-count badge when count > 0"))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Banner \xB7 alert"), /* @__PURE__ */ React.createElement("div", { style: { width: "100%", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(Banner, { tone: "err", tag: "HALT", title: "TRADING HALTED", detail: "Daily hard-stop 5.04% > 5.00% cap \xB7 positions frozen", time: "14:31:06", releaseIn: "0d 19h 21m 16s" }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "Toast"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(Toast, { tone: "ok", tag: "FILLS", time: "14:31:06", title: "FILLED \xB7 BUY 0.0420 BTC", detail: "@ 93,580.4 \xB7 order #A1903" }), /* @__PURE__ */ React.createElement(Toast, { tone: "warn", tag: "RISK", time: "14:30:18", title: "Weekly loss 78% of limit", detail: "\u2212$1,840 of \u2212$2,360" }), /* @__PURE__ */ React.createElement(Toast, { tone: "err", tag: "RISK", time: "14:31:06", title: "TRADING HALTED \u2014 hard-stop breached", detail: "DD 5.04% > 5.00% cap" }))), /* @__PURE__ */ React.createElement("div", { className: "spec-row" }, /* @__PURE__ */ React.createElement("span", { className: "l" }, "NotifRow"), /* @__PURE__ */ React.createElement("div", { style: { width: "100%", border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(NotifRow, { ev: { id: "x1", ch: "REGIME", pri: "risk", head: "Regime \u2192 RISK-OFF PANIC", detail: "was DEFENSIVE \xB7 size \xD71.0 \u2192 \xD70.25", ts: Date.now() - 48e3, unread: true }, now: Date.now(), muted: false, onRead: () => {
}, onDismiss: () => {
} }), /* @__PURE__ */ React.createElement(NotifRow, { ev: { id: "x2", ch: "SYSTEM", pri: "routine", head: "Market WS reconnected", detail: "2 streams \xB7 93ms \xB7 gap 1.4s recovered", ts: Date.now() - 24e4, unread: false }, now: Date.now(), muted: false, onRead: () => {
}, onDismiss: () => {
} })))), /* @__PURE__ */ React.createElement(Card, { pad: true, style: { gridColumn: "1 / span 2", borderColor: "var(--qe-cyan)" } }, /* @__PURE__ */ React.createElement(SecLbl, { rule: true }, "Workspace \xB7 GridStack tiling in React + ECharts theme"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: "0.62rem", color: "var(--qe-sub)", marginBottom: 8, lineHeight: 1.55 } }, /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "GridWorkspace"), " owns the gs-* attributes imperatively, so React re-renders never reset the layout. ", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, "Drag"), " a pane by its title bar,", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, " resize"), " from any edge; the top-nav ", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--qe-text)" } }, "lock"), " (\u{1F513}) freezes every workspace. The Equity + Sparkline panes render through ", /* @__PURE__ */ React.createElement("code", { style: { color: "var(--qe-cyan)" } }, "QE_ECHARTS_THEME"), " (canvas, vendored ECharts)."), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", height: 248, border: "1px solid var(--qe-line)" } }, /* @__PURE__ */ React.createElement(GridWorkspace, { cols: 12, rows: 12, persistId: "primitives-demo" }, /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 0, w: 7, h: 7 }, /* @__PURE__ */ React.createElement(Pane, { title: "Equity", tag: "ECHARTS", foot: { tone: "ok", id: 2101, msg: "demo series \xB7 QE_ECHARTS_THEME", ms: 3 } }, /* @__PURE__ */ React.createElement(EquityChart, { data: DEMO_EQUITY, baseline: DEMO_EQUITY[0] }))), /* @__PURE__ */ React.createElement(GridItem, { x: 7, y: 0, w: 5, h: 7 }, /* @__PURE__ */ React.createElement(Pane, { title: "Positions", count: 3 }, /* @__PURE__ */ React.createElement(FieldList, { rows: [
  { label: "BTCUSDT", value: "+2.02", color: "green" },
  { label: "ETHUSDT", value: "+3.47", color: "green" },
  { label: "SOLUSDT", value: "-0.85", color: "red" }
] }))), /* @__PURE__ */ React.createElement(GridItem, { x: 0, y: 7, w: 12, h: 5 }, /* @__PURE__ */ React.createElement(Pane, { title: "Sparkline", hot: true, foot: { tone: "info", id: 2102, msg: "drag my title bar \xB7 resize my edges", ms: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "10px 8px" } }, /* @__PURE__ */ React.createElement(Sparkline, { data: DEMO_EQUITY, height: 44, color: "var(--qe-cyan)" }))))))))), /* @__PURE__ */ React.createElement(StatusFooter, null));
const _PagePlaceholder = (name, phase) => function PagePlaceholder() {
  return /* @__PURE__ */ React.createElement("div", { className: "qe-scope", style: { width: "100%", height: "100%", background: "var(--qe-bg)", display: "flex", flexDirection: "column", overflow: "hidden" } }, /* @__PURE__ */ React.createElement(TopNavStd, { page: name, variant: "line", dense: true }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", fontFamily: "var(--qe-mono)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: "1.1rem", fontWeight: 700, color: "var(--qe-text)", letterSpacing: "0.06em" } }, name), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, fontSize: "0.6rem", color: "var(--qe-muted)", letterSpacing: "0.14em" } }, "REACT PORT \xB7 ", phase))), /* @__PURE__ */ React.createElement(StatusFooter, null));
};
const QE_PAGES = {
  Dashboard: _PagePlaceholder("Dashboard", "P1"),
  "Pre-Trade": _PagePlaceholder("Pre-Trade", "P3"),
  Linkage: _PagePlaceholder("Linkage", "P4"),
  History: _PagePlaceholder("History", "P4"),
  Analytics: _PagePlaceholder("Analytics", "P5"),
  Models: _PagePlaceholder("Models", "P7"),
  Regime: _PagePlaceholder("Regime", "P6"),
  Config: _PagePlaceholder("Config", "P2"),
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
    return "Primitives";
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
