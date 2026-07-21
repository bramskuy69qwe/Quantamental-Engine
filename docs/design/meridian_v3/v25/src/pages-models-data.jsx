/* QE v3.0 — Models data. Each model carries runs; each run carries a full
   categorized report in the MultiCharts shape (strategy / trades / tradeAnalysis
   / periodical / settings). The @ES model uses the REAL parsed report
   (MC_ES_REPORT, loaded first); the others are synthetic but identically shaped.

   Run report shape:
     report = {
       strategy: { groups:[{name, rows:[{label, all, long, short, fmt}]}],
                   ratios:[{label, all, fmt}], time:[{label, val, fmt}] },
       trades:  [{n, side, entryType, entrySignal, entryDate, entryTime,
                  entryPrice, contracts, exitType, exitSignal, exitDate,
                  exitTime, exitPrice, profit, profitPct, cum, cumPct,
                  runup, runupPct, dd, ddPct}],
       tradeAnalysis: { total[], outliers[], runupDD[], series[],
                        seriesWinners[], seriesLosers[] },
       periodical: { hourly:[{hour, profit, profitPct, avgProfit,
                              grossProfit, grossLoss, trades, pctProfitable}] },
       settings:  { inputs:[{k,v}], config:[{k,v}] },
     } */

// Headline KPIs derived from a report (used by cards / leaderboard / overview).
function runKpis(report) {
  const g = {};
  report.strategy.groups.forEach(grp => grp.rows.forEach(r => { g[r.label] = r; }));
  const net = g['Net Profit'] ? g['Net Profit'].all : 0;
  const pf  = g['Profit Factor'] ? Math.abs(g['Profit Factor'].all) : 0;
  const win = g['% Profitable'] ? g['% Profitable'].all * 100 : 0;
  const ddP = g['Max Strategy Drawdown (%)'] ? g['Max Strategy Drawdown (%)'].all * 100 : 0;
  const n   = g['Total # of Trades'] ? g['Total # of Trades'].all : report.trades.length;
  const startEq = (report.settings.config.find(c => c.k === 'Initial Capital') || {}).v || 100000;
  return { net, pf, winPct: +win.toFixed(1), maxDDPct: +ddP.toFixed(2), nTrades: n, startEq: +startEq };
}

// ── Synthetic report generator ─────────────────────────────────────────────
function _synthReport(seed, cfg) {
  let rng = seed;
  const rand = () => { rng = (rng * 9301 + 49297) % 233280; return rng / 233280; };
  const { nTrades, winRate, avgWin, avgLoss, startEq, symbol, point, sigLong, sigShort, exitTP, exitSL } = cfg;

  // 1) trades
  const trades = [];
  let cum = 0, peak = 0, day = Date.UTC(2026, 0, 6, 14, 30, 0);
  for (let i = 0; i < nTrades; i++) {
    const win = rand() < winRate;
    const long = rand() < 0.5;
    const mult = 0.4 + rand() * 1.8;
    const pl = +((win ? avgWin * mult : avgLoss * mult)).toFixed(2);
    cum = +(cum + pl).toFixed(2); peak = Math.max(peak, cum);
    const dd = +(cum - peak).toFixed(2);
    const entryP = +(point * (1 + rand() * 0.4) + 80).toFixed(2);
    const dur = (2 + Math.floor(rand() * 40));
    const ed = new Date(day), xd = new Date(day + dur * 60000);
    const runup = +(Math.abs(pl) * (0.5 + rand())).toFixed(2);
    trades.push({
      n: i + 1, side: long ? 'L' : 'S',
      entryType: long ? 'EntryLong' : 'EntryShort', entrySignal: long ? sigLong : sigShort,
      entryDate: ed.toISOString().slice(0, 10), entryTime: ed.toISOString().slice(11, 19),
      entryPrice: entryP, contracts: 1,
      exitType: long ? 'ExitLong' : 'ExitShort', exitSignal: win ? exitTP : exitSL,
      exitDate: xd.toISOString().slice(0, 10), exitTime: xd.toISOString().slice(11, 19),
      exitPrice: +(entryP + (win ? 1 : -1) * (long ? 1 : -1) * (2 + rand() * 8)).toFixed(2),
      profit: pl, profitPct: +(pl / startEq).toFixed(6),
      cum, cumPct: +(cum / startEq).toFixed(6),
      runup, runupPct: +(runup / startEq).toFixed(6),
      dd, ddPct: +(dd / startEq).toFixed(6),
    });
    day += (1 + Math.floor(rand() * 4)) * 3600000;
  }

  // 2) per-subset aggregates
  const agg = (subset) => {
    const ts = subset;
    const wins = ts.filter(t => t.profit > 0), losses = ts.filter(t => t.profit < 0);
    const gp = +wins.reduce((a, t) => a + t.profit, 0).toFixed(2);
    const gl = +losses.reduce((a, t) => a + t.profit, 0).toFixed(2);
    const net = +(gp + gl).toFixed(2);
    let c = 0, pk = 0, mdd = 0;
    ts.forEach(t => { c += t.profit; pk = Math.max(pk, c); mdd = Math.min(mdd, c - pk); });
    return {
      net, gp, gl, n: ts.length,
      winPct: ts.length ? wins.length / ts.length : 0,
      pf: gl !== 0 ? +(gp / gl).toFixed(6) : 0,
      wins: wins.length, losses: losses.length,
      avgWin: wins.length ? +(gp / wins.length).toFixed(4) : 0,
      avgLoss: losses.length ? +(gl / losses.length).toFixed(4) : 0,
      largestWin: wins.length ? +Math.max(...wins.map(t => t.profit)).toFixed(2) : 0,
      largestLoss: losses.length ? +Math.min(...losses.map(t => t.profit)).toFixed(2) : 0,
      mdd: +mdd.toFixed(2),
    };
  };
  const A = agg(trades), L = agg(trades.filter(t => t.side === 'L')), S = agg(trades.filter(t => t.side === 'S'));
  const acct = Math.abs(A.mdd) + Math.abs(A.gl) * 0.05;
  const tri = (fa, fl, fs, fmt) => ({ all: fa, long: fl, short: fs, fmt });

  const strategy = {
    groups: [
      { name: 'Profit & Loss', rows: [
        { label: 'Net Profit', ...tri(A.net, L.net, S.net, 'usd') },
        { label: 'Gross Profit', ...tri(A.gp, L.gp, S.gp, 'usd') },
        { label: 'Gross Loss', ...tri(A.gl, L.gl, S.gl, 'usd') },
        { label: 'Adjusted Net Profit', ...tri(+(A.net * 1.18).toFixed(2), +(L.net * 1.18).toFixed(2), +(S.net * 1.18).toFixed(2), 'usd') },
        { label: 'Adjusted Gross Profit', ...tri(+(A.gp * 0.86).toFixed(2), +(L.gp * 0.86).toFixed(2), +(S.gp * 0.86).toFixed(2), 'usd') },
        { label: 'Adjusted Gross Loss', ...tri(+(A.gl * 1.12).toFixed(2), +(L.gl * 1.12).toFixed(2), +(S.gl * 1.12).toFixed(2), 'usd') },
        { label: 'Select Net Profit', ...tri(+(A.net * 0.92).toFixed(2), +(L.net * 0.92).toFixed(2), +(S.net * 0.92).toFixed(2), 'usd') },
        { label: 'Select Gross Profit', ...tri(+(A.gp * 0.7).toFixed(2), +(L.gp * 0.7).toFixed(2), +(S.gp * 0.7).toFixed(2), 'usd') },
        { label: 'Select Gross Loss', ...tri(+(A.gl * 0.68).toFixed(2), +(L.gl * 0.68).toFixed(2), +(S.gl * 0.68).toFixed(2), 'usd') },
        { label: 'Open Position P/L', ...tri(0, 0, 0, 'usd') },
      ]},
      { name: 'Capital & Volatility', rows: [
        { label: 'Account Size Required', ...tri(+acct.toFixed(2), +(acct * 0.4).toFixed(2), +(acct * 0.7).toFixed(2), 'usd') },
        { label: 'Max # Contracts Held', ...tri(1, 1, 1, 'int') },
        { label: 'Slippage Paid', ...tri(0, 0, 0, 'usd') },
        { label: 'Commission Paid', ...tri(0, 0, 0, 'usd') },
        { label: 'Monthly Return StdDev', ...tri(+(Math.abs(A.net) * 0.3).toFixed(2), null, null, 'num') },
      ]},
      { name: 'Returns', rows: [
        { label: 'Return on Account', ...tri(+(A.net / acct).toFixed(6), +(L.net / acct).toFixed(6), +(S.net / acct).toFixed(6), 'pct') },
        { label: 'Return on Initial Capital', ...tri(+(A.net / startEq).toFixed(6), +(L.net / startEq).toFixed(6), +(S.net / startEq).toFixed(6), 'pct') },
        { label: 'Profit Factor', ...tri(A.pf, L.pf, S.pf, 'pf') },
        { label: 'Adjusted Profit Factor', ...tri(+(A.pf * 0.78).toFixed(4), +(L.pf * 0.78).toFixed(4), +(S.pf * 0.78).toFixed(4), 'pf') },
        { label: 'Select Profit Factor', ...tri(+(A.pf * 0.85).toFixed(4), +(L.pf * 0.85).toFixed(4), +(S.pf * 0.85).toFixed(4), 'pf') },
        { label: 'Annual Rate of Return', ...tri(+(A.net / startEq * 6).toFixed(6), null, null, 'pct') },
        { label: 'Monthly Rate of Return', ...tri(+(A.net / startEq * 0.5).toFixed(6), null, null, 'pct') },
        { label: 'Buy & Hold Return', ...tri(+(avgWin * 4).toFixed(2), null, null, 'usd') },
        { label: 'Avg Monthly Return', ...tri(A.net, null, null, 'usd') },
        { label: 'Total # of Trades', ...tri(A.n, L.n, S.n, 'int') },
        { label: '% Profitable', ...tri(+A.winPct.toFixed(6), +L.winPct.toFixed(6), +S.winPct.toFixed(6), 'pct') },
      ]},
      { name: 'Drawdown', rows: [
        { label: 'Max Strategy Drawdown', ...tri(A.mdd, L.mdd, S.mdd, 'usd') },
        { label: 'Max Strategy Drawdown (%)', ...tri(+(A.mdd / startEq).toFixed(6), +(L.mdd / startEq).toFixed(6), +(S.mdd / startEq).toFixed(6), 'pct') },
        { label: 'Max Close To Close Drawdown', ...tri(+(A.mdd * 0.95).toFixed(2), +(L.mdd * 0.95).toFixed(2), +(S.mdd * 0.95).toFixed(2), 'usd') },
        { label: 'Max Close To Close Drawdown (%)', ...tri(+(A.mdd * 0.95 / startEq).toFixed(6), null, null, 'pct') },
        { label: 'Return on Max Strategy Drawdown', ...tri(+(A.net / Math.abs(A.mdd || 1)).toFixed(6), +(L.net / Math.abs(L.mdd || 1)).toFixed(6), +(S.net / Math.abs(S.mdd || 1)).toFixed(6), 'num') },
      ]},
    ],
    ratios: [
      { label: 'Sharpe Ratio', all: +(0.4 + rand()).toFixed(4), fmt: 'num' },
      { label: 'Annualized Sharpe Ratio', all: +(0.6 + rand() * 1.5).toFixed(4), fmt: 'num' },
      { label: 'Sortino Ratio', all: +(0.5 + rand() * 1.4).toFixed(4), fmt: 'num' },
      { label: 'Calmar Ratio', all: +(A.net / Math.abs(A.mdd || 1) * 0.04).toFixed(4), fmt: 'num' },
      { label: 'Sterling Ratio', all: +(rand() * 0.01).toFixed(6), fmt: 'num' },
      { label: 'RINA Index', all: +(A.net * 0.16).toFixed(4), fmt: 'num' },
      { label: 'Upside Potential Ratio', all: +(rand() * 2).toFixed(4), fmt: 'num' },
      { label: 'Fouse Ratio', all: +(A.net * 0.02).toFixed(4), fmt: 'num' },
    ],
    time: [
      { label: 'Trading Period', val: '14 Hrs, 9 Mins', fmt: 'str' },
      { label: 'Time in the Market', val: (1 + Math.floor(rand() * 4)) + ' Hrs, ' + Math.floor(rand() * 59) + ' Mins', fmt: 'str' },
      { label: 'Percent in the Market', val: +(0.1 + rand() * 0.3).toFixed(6), fmt: 'pct' },
      { label: 'Longest flat period', val: (10 + Math.floor(rand() * 50)) + ' Mins', fmt: 'str' },
    ],
  };

  // trade analysis
  let maxCW = 0, maxCL = 0, cw = 0, cl = 0;
  trades.forEach(t => { if (t.profit > 0) { cw++; cl = 0; } else if (t.profit < 0) { cl++; cw = 0; } maxCW = Math.max(maxCW, cw); maxCL = Math.max(maxCL, cl); });
  const triT = (a, l, s) => ({ all: a, long: l, short: s });
  const tradeAnalysis = {
    total: [
      { label: 'Total # of Trades', ...triT(A.n, L.n, S.n) },
      { label: 'Number Winning Trades', ...triT(A.wins, L.wins, S.wins) },
      { label: 'Number Losing Trades', ...triT(A.losses, L.losses, S.losses) },
      { label: '% Profitable', ...triT(+A.winPct.toFixed(4), +L.winPct.toFixed(4), +S.winPct.toFixed(4)) },
      { label: 'Avg Trade (win & loss)', ...triT(+(A.net / A.n).toFixed(4), +(L.net / (L.n || 1)).toFixed(4), +(S.net / (S.n || 1)).toFixed(4)) },
      { label: 'Average Winning Trade', ...triT(A.avgWin, L.avgWin, S.avgWin) },
      { label: 'Average Losing Trade', ...triT(A.avgLoss, L.avgLoss, S.avgLoss) },
      { label: 'Ratio Avg Win / Avg Loss', ...triT(+Math.abs(A.avgWin / (A.avgLoss || 1)).toFixed(4), +Math.abs(L.avgWin / (L.avgLoss || 1)).toFixed(4), +Math.abs(S.avgWin / (S.avgLoss || 1)).toFixed(4)) },
      { label: 'Largest Winning Trade', ...triT(A.largestWin, L.largestWin, S.largestWin) },
      { label: 'Largest Losing Trade', ...triT(A.largestLoss, L.largestLoss, S.largestLoss) },
      { label: 'Avg # Bars in All Trades', ...triT(2, 2, 2) },
    ],
    outliers: [
      { label: '1 Std. Deviation', total: +(Math.abs(A.avgWin) * 1.5).toFixed(4), positive: +(Math.abs(A.avgWin) * 1.2).toFixed(4), negative: +(Math.abs(A.avgLoss) * 1.3).toFixed(4) },
      { label: 'Number of Outliers', total: Math.floor(A.n * 0.12), positive: Math.floor(A.wins * 0.12), negative: Math.floor(A.losses * 0.12) },
      { label: 'Outlier Profit/Loss', total: +(A.net * 0.1).toFixed(2), positive: +(A.gp * 0.4).toFixed(2), negative: +(A.gl * 0.3).toFixed(2) },
    ],
    runupDD: [
      { label: 'Max Value', runup: +(A.avgWin * 3).toFixed(2), drawdown: +(A.avgLoss * 4).toFixed(2) },
      { label: 'Avg Value', runup: +(A.avgWin * 0.9).toFixed(2), drawdown: +(A.avgLoss * 0.9).toFixed(2) },
      { label: '1 Std. Deviation', runup: +(Math.abs(A.avgWin) * 0.8).toFixed(2), drawdown: +(Math.abs(A.avgLoss) * 0.8).toFixed(2) },
    ],
    series: [
      { label: 'Z-score', value: +(rand() * 2).toFixed(4) },
      { label: 'Confidence Limit', value: +(rand()).toFixed(4) },
      { label: 'Max Consec. Winners', value: maxCW },
      { label: 'Max Consec. Losers', value: maxCL },
      { label: 'Largest Consec. Winners $', value: +(A.avgWin * maxCW).toFixed(2) },
      { label: 'Largest Consec. Losers $', value: +(A.avgLoss * maxCL).toFixed(2) },
    ],
    seriesWinners: [
      { streak: 1, count: Math.floor(A.wins * 0.5), avgGain: A.avgWin, avgLossNext: A.avgLoss },
      { streak: 2, count: Math.floor(A.wins * 0.25), avgGain: +(A.avgWin * 0.95).toFixed(2), avgLossNext: +(A.avgLoss * 0.8).toFixed(2) },
      { streak: 3, count: Math.floor(A.wins * 0.1), avgGain: +(A.avgWin * 0.9).toFixed(2), avgLossNext: +(A.avgLoss * 1.1).toFixed(2) },
    ],
    seriesLosers: [
      { streak: 1, count: Math.floor(A.losses * 0.5), avgLoss: A.avgLoss, avgGainNext: A.avgWin },
      { streak: 2, count: Math.floor(A.losses * 0.25), avgLoss: +(A.avgLoss * 0.9).toFixed(2), avgGainNext: +(A.avgWin * 0.8).toFixed(2) },
      { streak: 3, count: Math.floor(A.losses * 0.12), avgLoss: +(A.avgLoss * 0.85).toFixed(2), avgGainNext: +(A.avgWin * 1.05).toFixed(2) },
    ],
  };

  // periodical hourly
  const byHour = {};
  trades.forEach(t => { const h = t.entryTime.slice(0, 2) + ':00'; (byHour[h] = byHour[h] || []).push(t); });
  const hourly = Object.keys(byHour).sort().map(h => {
    const ts = byHour[h], a = agg(ts);
    return { hour: h, profit: a.net, profitPct: +(a.net / startEq).toFixed(6), avgProfit: +(a.net / ts.length).toFixed(2), grossProfit: a.gp, grossLoss: a.gl, trades: ts.length, pctProfitable: +a.winPct.toFixed(6) };
  });

  const settings = {
    inputs: cfg.inputs,
    config: [
      { k: 'Symbol Name', v: symbol }, { k: 'Symbol Currency', v: 'USD' },
      { k: 'Initial Capital', v: startEq }, { k: 'Point Value', v: '$' + point },
      { k: 'Commission', v: 'No Commission' }, { k: 'Slippage', v: '0$ per Trade' },
      { k: 'Compression', v: cfg.compression || '1 Minute' }, { k: 'Backtesting Mode', v: 'Classic' },
      { k: 'Interest Rate', v: 0.02 }, { k: 'Degree of Risk Aversion', v: 'Conservative' },
    ],
  };

  return { strategy, trades, tradeAnalysis, periodical: { hourly }, settings };
}

// ── Models ──────────────────────────────────────────────────────────────────
const MOCK_MODELS = [
  {
    id: 'mdl_es_orb_1m', name: 'ES ORB 1-Min', type: 'Micro',
    desc: 'Opening-range breakout on @ES 1-minute. Long/short on OR break with TP/SL by reward-risk multiple. Real imported MultiCharts backtest.',
    updated: '2026-04-24', tags: ['orb', 'es', 'real'],
    risk: { riskPct: 1.0, sizing: 'Fixed fractional', matchWindow: 30, tp: 'RewardRisk × 1.5', sl: 'OR stop + 2 ticks', regimeMult: false, sizeOverride: null },
    source: { app: 'MultiCharts', symbol: '@ES', resolution: '1 Minute', pointValue: 50, currency: 'USD', initialCapital: 100000, commission: 'No Commission', slippage: '0$ per Trade' },
    strategy: { notes: 'TES SATU — opening-range breakout. OR window 30 min, no entry after 15:30, reward:risk 1.5, 1% equity risk. Real backtest imported from MultiCharts.', entry: 'Break of 30-min opening range ± entry buffer', exit: 'TP at 1.5× risk · OR-based stop · flatten on close', universe: '@ES (E-mini S&P 500)', regimeCfg: 'multiplier off' },
    runs: [{ id: 'run_es_real', source: 'MultiCharts', file: '@ES - 1 Minute.xlsx', window: '2026-04-24', imported: '2026-04-24 21:09', report: (typeof MC_ES_REPORT !== 'undefined' ? MC_ES_REPORT : null) }],
    usage: [{ posId: 'pos_es_4401', sym: '@ES', status: 'closed', pnl: -0.94, date: '04-24' }],
  },
  {
    id: 'mdl_btc_macro_trend', name: 'BTC Macro Trend', type: 'Macro',
    desc: 'Daily-bias trend follower on BTC perp. Long/short off MA crossover gated by regime.',
    updated: '2026-04-22', tags: ['trend', 'core', 'btc'],
    risk: { riskPct: 1.0, sizing: 'Fixed fractional', matchWindow: 90, tp: 'ATR × 2.5', sl: 'ATR × 1.2', regimeMult: true, sizeOverride: null },
    strategy: { notes: 'Primary core model. Only trades in TREND / DEF regimes; flat in PANIC.', entry: '20/50 EMA cross · RVOL > 1.2 · regime ∈ {TREND, DEF}', exit: 'ATR-trailing stop · TP at 2.5×ATR · time-stop 48h', universe: 'BTCUSDT perp', regimeCfg: 'multiplier on · PANIC → flat' },
    runs: [
      { id: 'run_btc_1', source: 'MultiCharts', file: 'BTC_macro_2024-2025.xlsx', window: '2024-01 → 2025-12', imported: '2026-04-12 09:18',
        report: _synthReport(101, { nTrades: 142, winRate: 0.58, avgWin: 380, avgLoss: -240, startEq: 25000, symbol: 'BTCUSDT', point: 42000, sigLong: 'EMA_X_L', sigShort: 'EMA_X_S', exitTP: 'TP_ATR', exitSL: 'SL_ATR', compression: 'Daily',
          inputs: [{ k: 'FastEMA', v: 20 }, { k: 'SlowEMA', v: 50 }, { k: 'ATRMult_TP', v: 2.5 }, { k: 'ATRMult_SL', v: 1.2 }, { k: 'RiskPctOfEquity', v: 1.0 }, { k: 'RVolMin', v: 1.2 }] }) },
      { id: 'run_btc_2', source: 'MultiCharts', file: 'BTC_macro_v2.xlsx', window: '2023-06 → 2025-06', imported: '2026-03-31 14:02',
        report: _synthReport(202, { nTrades: 88, winRate: 0.52, avgWin: 520, avgLoss: -410, startEq: 25000, symbol: 'BTCUSDT', point: 38000, sigLong: 'EMA_X_L', sigShort: 'EMA_X_S', exitTP: 'TP_ATR', exitSL: 'SL_ATR', compression: 'Daily',
          inputs: [{ k: 'FastEMA', v: 20 }, { k: 'SlowEMA', v: 50 }, { k: 'ATRMult_TP', v: 2.0 }, { k: 'ATRMult_SL', v: 1.0 }, { k: 'RiskPctOfEquity', v: 1.0 }] }) },
    ],
    usage: [
      { posId: 'pos_4f29a1', sym: 'BTCUSDT', status: 'closed', pnl: 1.93, date: '04-25' },
      { posId: 'pos_4f28b0', sym: 'BTCUSDT', status: 'open', pnl: 0.42, date: '04-26' },
    ],
  },
  {
    id: 'mdl_eth_micro_scalp', name: 'ETH Micro Scalp', type: 'Micro',
    desc: 'Intraday mean-reversion scalper on ETH. High trade count, tight stops, taker-fee sensitive.',
    updated: '2026-04-18', tags: ['scalp', 'eth', 'intraday'],
    risk: { riskPct: 0.5, sizing: 'Fixed fractional', matchWindow: 30, tp: 'Fixed 0.4%', sl: 'Fixed 0.3%', regimeMult: false, sizeOverride: null },
    strategy: { notes: 'Fade extensions into VWAP bands. Disabled during high-impact news windows.', entry: 'VWAP band fade · z-score > 2 · spread < 1bp', exit: 'VWAP touch · TP 0.4% · SL 0.3% · max-hold 25m', universe: 'ETHUSDT perp', regimeCfg: 'multiplier off' },
    runs: [
      { id: 'run_eth_1', source: 'MultiCharts', file: 'ETH_scalp_h1.xlsx', window: '2025-01 → 2025-12', imported: '2026-04-10 21:44',
        report: _synthReport(303, { nTrades: 216, winRate: 0.61, avgWin: 210, avgLoss: -150, startEq: 50000, symbol: 'ETHUSDT', point: 3200, sigLong: 'VWAP_L', sigShort: 'VWAP_S', exitTP: 'VWAP_TP', exitSL: 'VWAP_SL', compression: '1 Minute',
          inputs: [{ k: 'ZScoreMin', v: 2.0 }, { k: 'TP_Pct', v: 0.4 }, { k: 'SL_Pct', v: 0.3 }, { k: 'MaxHoldMin', v: 25 }, { k: 'RiskPctOfEquity', v: 0.5 }] }) },
    ],
    usage: [{ posId: 'pos_4f29bb', sym: 'ETHUSDT', status: 'closed', pnl: -0.55, date: '04-25' }],
  },
  {
    id: 'mdl_alt_swing_both', name: 'Alt Swing Rotation', type: 'Both',
    desc: 'Multi-day swing rotation across liquid alts. Combines macro regime gate with micro entry timing.',
    updated: '2026-03-29', tags: ['swing', 'alts'],
    risk: { riskPct: 1.5, sizing: 'Volatility-target', matchWindow: 120, tp: 'Structure', sl: 'Swing low', regimeMult: true, sizeOverride: 250 },
    strategy: { notes: 'Rotates into top-3 momentum alts when BTC regime is TREND.', entry: 'Momentum rank ≤ 3 · BTC regime TREND · pullback to 0.382', exit: 'Structure break · TP at prior swing high · 5d time-stop', universe: 'SOL, AVAX, LINK, ARB perps', regimeCfg: 'multiplier on · vol-target 20%' },
    runs: [
      { id: 'run_alt_1', source: 'MultiCharts', file: 'alt_swing_2y.xlsx', window: '2023-01 → 2025-01', imported: '2026-03-28 11:30',
        report: _synthReport(404, { nTrades: 64, winRate: 0.47, avgWin: 880, avgLoss: -640, startEq: 100000, symbol: 'SOLUSDT', point: 180, sigLong: 'MOM_L', sigShort: 'MOM_S', exitTP: 'STRUCT_TP', exitSL: 'SWING_SL', compression: '4 Hours',
          inputs: [{ k: 'MomRankMax', v: 3 }, { k: 'VolTarget', v: 20 }, { k: 'TimeStopDays', v: 5 }, { k: 'RiskPctOfEquity', v: 1.5 }] }) },
    ],
    usage: [],
  },
  {
    id: 'mdl_draft_regime_def', name: 'Regime Defensive (draft)', type: 'Macro',
    desc: 'Capital-preservation overlay that flattens exposure in PANIC and scales down in DEF. No imported performance yet.',
    updated: '2026-04-24', tags: ['defensive', 'draft'],
    risk: { riskPct: 0.75, sizing: 'Fixed fractional', matchWindow: 60, tp: 'n/a', sl: 'Hard 2%', regimeMult: true, sizeOverride: null },
    strategy: { notes: 'Work in progress. Intended as a portfolio overlay rather than a standalone alpha source.', entry: 'regime transition → DEF/PANIC', exit: 'regime recovery → NEUT/TREND', universe: 'portfolio-level', regimeCfg: 'multiplier on · PANIC → flat all' },
    runs: [],
    usage: [],
  },
];

// latest run helper
const _latestRun = (m) => m.runs && m.runs.length ? m.runs[0] : null;

// equity / drawdown series derived from a report's trades
function runEquity(report) {
  const startEq = +((report.settings.config.find(c => c.k === 'Initial Capital') || {}).v || 100000);
  return [startEq, ...report.trades.map(t => +(startEq + t.cum).toFixed(2))];
}
function runDrawdown(report) { return [0, ...report.trades.map(t => t.dd)]; }
// kpis straight from a run object
const runKpisOf = (run) => (run && run.report) ? runKpis(run.report) : null;

// Extract model metadata from a parsed report's Settings sheet (autofill).
function parseReportMeta(report) {
  const cfg = {}; (report.settings.config || []).forEach(c => { cfg[c.k] = c.v; });
  const inp = {}; (report.settings.inputs || []).forEach(c => { inp[c.k] = c.v; });
  const symbol = cfg['Symbol Name'] || '';
  const resolution = cfg['Compression'] || '';
  const pv = parseFloat(String(cfg['Point Value'] || '').replace(/[^0-9.]/g, '')) || 0;
  const rrm = inp['RewardRiskMult'];
  return {
    name: symbol ? (symbol.replace('@', '') + ' ' + resolution.replace(' Minute', 'm').replace(' Hours', 'h') + ' Model').replace(/\s+/g, ' ').trim() : '',
    symbol, resolution,
    pointValue: pv,
    currency: cfg['Symbol Currency'] || cfg['Strategy Currency'] || 'USD',
    initialCapital: parseFloat(cfg['Initial Capital']) || 100000,
    commission: cfg['Commission'] || 'No Commission',
    slippage: cfg['Slippage'] || '0$ per Trade',
    riskPct: parseFloat(inp['RiskPctOfEquity']) || 1.0,
    tp: rrm != null ? ('RewardRisk × ' + rrm) : 'ATR × 2.5',
    universe: symbol,
  };
}

const MOCK_IMPORT_PREVIEW = {
  file: 'BTC_macro_2026Q1.xlsx', source: 'MultiCharts', symbol: 'BTCUSDT',
  window: '2026-01-01 → 2026-03-31', nTrades: 58, net: 1840.5, pf: 1.74, winPct: 56.9, maxDDPct: -8.4, sharpe: 1.31,
  warnings: ['3 trades missing exit reason — defaulted to MANUAL'],
};

Object.assign(window, { MOCK_MODELS, MOCK_IMPORT_PREVIEW, runKpis, runKpisOf, runEquity, runDrawdown, parseReportMeta, _latestRun, _synthReport });
