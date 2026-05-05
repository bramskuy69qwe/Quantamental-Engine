// ── Quantamental Engine – ECharts Theme & Utilities ──────────────────────────
(function() {
  'use strict';

  // ── Color palette (matches CSS vars in base.html) ──────────────────────────
  var C = {
    bg:     '#07080f',
    card:   '#0c1118',
    panel:  '#101826',
    border: '#18253a',
    text:   '#e8f2ff',
    sub:    '#96b4d0',
    muted:  '#526a88',
    blue:   '#3c8ff5',
    green:  '#00c855',
    red:    '#e83535',
    amber:  '#e89020',
    cyan:   '#00b4d8',
    purple: '#9b6ef5',
  };

  // ── Register ECharts theme ─────────────────────────────────────────────────
  echarts.registerTheme('quantamental', {
    backgroundColor: 'transparent',
    textStyle: { fontFamily: "'JetBrains Mono', monospace", color: C.sub, fontSize: 11 },
    title: { textStyle: { color: C.text, fontFamily: "'Space Grotesk', sans-serif", fontWeight: 600 } },
    legend: { textStyle: { color: C.sub, fontSize: 11 } },
    categoryAxis: {
      axisLine:  { lineStyle: { color: C.border } },
      splitLine: { lineStyle: { color: C.border } },
      axisLabel: { color: C.muted, fontSize: 10 },
      axisTick:  { lineStyle: { color: C.border } },
    },
    valueAxis: {
      axisLine:  { lineStyle: { color: C.border } },
      splitLine: { lineStyle: { color: C.border, type: 'dashed' } },
      axisLabel: { color: C.muted, fontSize: 10 },
      axisTick:  { lineStyle: { color: C.border } },
    },
    timeAxis: {
      axisLine:  { lineStyle: { color: C.border } },
      splitLine: { lineStyle: { color: C.border, type: 'dashed' } },
      axisLabel: { color: C.muted, fontSize: 10 },
      axisTick:  { lineStyle: { color: C.border } },
    },
    color: [C.blue, C.green, C.red, C.amber, C.cyan, C.purple],
    tooltip: {
      backgroundColor: C.card,
      borderColor: C.border,
      textStyle: { color: C.text, fontFamily: "'JetBrains Mono', monospace", fontSize: 11 },
    },
    toolbox: {
      iconStyle: { borderColor: C.muted },
      emphasis: { iconStyle: { borderColor: C.text } },
    },
    dataZoom: [{
      type: 'inside',
      textStyle: { color: C.sub },
    }, {
      type: 'slider',
      backgroundColor: C.panel,
      borderColor: C.border,
      fillerColor: 'rgba(60,143,245,0.12)',
      handleStyle: { color: C.blue, borderColor: C.blue },
      textStyle: { color: C.sub, fontSize: 10 },
      dataBackground: { lineStyle: { color: C.border }, areaStyle: { color: C.panel } },
    }],
  });

  // ── Internal: fully dispose an ECharts instance + clean up resize listener ─
  function fullDispose(inst) {
    if (!inst) return;
    if (inst.___qeResize) {
      window.removeEventListener('resize', inst.___qeResize);
      inst.___qeResize = null;
    }
    inst.dispose();
  }

  // ── Utility: init chart with theme + auto-resize + dispose safety ──────────
  function initChart(el, opts) {
    if (!el) { console.warn('QE.initChart: element is null'); return null; }
    // Dispose existing instance if any (with full cleanup)
    var existing = echarts.getInstanceByDom(el);
    if (existing) fullDispose(existing);
    // Mark for HTMX lifecycle hook
    el.setAttribute('data-echarts', '');
    // Init with theme
    var chart = echarts.init(el, 'quantamental', { renderer: 'canvas' });
    chart.setOption(opts);
    // Auto-resize
    var onResize = function() { chart.resize(); };
    window.addEventListener('resize', onResize);
    chart.___qeResize = onResize; // store ref for cleanup
    return chart;
  }

  // ── Utility: dispose chart and clean up resize listener ────────────────────
  function disposeChart(el) {
    if (!el) return;
    stopRefresh(el);
    var inst = echarts.getInstanceByDom(el);
    fullDispose(inst);
  }

  // ── Utility: convert OHLC data to ECharts candlestick format ───────────────
  // ECharts expects: [open, close, low, high]
  function ohlcToEcharts(o, h, l, c) {
    return [o, c, l, h];
  }

  // ── Utility: create gradient for area charts ───────────────────────────────
  function areaGradient(color, topOpacity, bottomOpacity) {
    topOpacity = topOpacity !== undefined ? topOpacity : 0.25;
    bottomOpacity = bottomOpacity !== undefined ? bottomOpacity : 0.02;
    return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: color + Math.round(topOpacity * 255).toString(16).padStart(2, '0') },
      { offset: 1, color: color + Math.round(bottomOpacity * 255).toString(16).padStart(2, '0') },
    ]);
  }

  // ── Data refresh lifecycle ──────────────────────────────────────────────────
  function _doRefresh(el, url, onData) {
    var chart = echarts.getInstanceByDom(el);
    if (!chart || chart.isDisposed()) return;
    fetch(url, { cache: 'no-store' })
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(data) {
        var c = echarts.getInstanceByDom(el);
        if (c && !c.isDisposed()) onData(c, data, el);
      })
      .catch(function(err) {
        console.warn('QE refresh error (' + url + '):', err);
      });
  }

  function startRefresh(el, url, onData, intervalMs) {
    if (!el) { console.warn('QE.startRefresh: element is null'); return; }
    stopRefresh(el);
    el.___qeRefreshTimer = setInterval(function() {
      if (!document.body.contains(el)) { stopRefresh(el); return; }
      var chart = echarts.getInstanceByDom(el);
      if (!chart || chart.isDisposed()) { stopRefresh(el); return; }
      _doRefresh(el, url, onData);
    }, intervalMs);
  }

  function stopRefresh(el) {
    if (!el) return;
    if (el.___qeRefreshTimer) {
      clearInterval(el.___qeRefreshTimer);
      el.___qeRefreshTimer = null;
    }
    if (el.___qeTickTimer) {
      clearInterval(el.___qeTickTimer);
      el.___qeTickTimer = null;
    }
  }

  // ── Expose globally ────────────────────────────────────────────────────────
  window.QE = {
    colors: C,
    initChart: initChart,
    disposeChart: disposeChart,
    ohlcToEcharts: ohlcToEcharts,
    areaGradient: areaGradient,
    startRefresh: startRefresh,
    stopRefresh: stopRefresh,
  };

})();
