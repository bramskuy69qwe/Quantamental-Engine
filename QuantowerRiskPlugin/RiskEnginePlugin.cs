using TradingPlatform.BusinessLayer;
using QuantowerRiskPlugin.Models;
using System.Text.Json;

namespace QuantowerRiskPlugin;

/// <summary>
/// Quantower strategy entry point — bridges fill/position/market-data events to the risk engine.
///
/// HOW TO INSTALL:
///   1. Build this project (Release configuration).
///   2. Copy QuantowerRiskPlugin.dll to:
///        %AppData%\Quantower\Settings\Strategies\
///   3. Restart Quantower.
///   4. Open the Strategies panel, find "Risk Engine Plugin", set Engine URL, click Run.
/// </summary>
public class RiskEnginePlugin : Strategy
{
    [InputParameter("Engine URL", 0)]
    public string EngineUrl { get; set; } = "ws://localhost:8000/ws/platform";

    [InputParameter("Backfill days", 1)]
    public int BackfillDays { get; set; } = 90;

    private RiskEngineConnection? _conn;
    private Account? _activeAccount;

    // Throttle Account.Updated -> account_state events (5 Hz)
    private long _lastAccountStateMs;
    private const int AccountStateMinIntervalMs = 200;

    // R4: active market-data subscriptions (engine-normalised symbol → Quantower Symbol)
    private readonly Dictionary<string, Symbol> _ohlcvSubs = new();
    private readonly Dictionary<string, Symbol> _depthSubs = new();
    private readonly Dictionary<string, Symbol> _markSubs  = new();

    public RiskEnginePlugin() : base()
    {
        this.Name = "Risk Engine Plugin";
    }

    protected override void OnRun()
    {
        Log($"Risk Engine Plugin starting — connecting to {EngineUrl}", StrategyLoggingLevel.Info);

        _conn = new RiskEngineConnection(EngineUrl);

        _conn.RiskStateReceived += state =>
        {
            if (state.TryGetProperty("dd_state", out var dd) && dd.GetString() == "limit")
                Log("RISK ALERT: Drawdown limit reached!", StrategyLoggingLevel.Error);
        };

        _conn.PositionsRequested += SendPositionSnapshot;
        _conn.OhlcvRequested     += OnOhlcvRequested;
        _conn.OhlcvUnsubscribed  += OnOhlcvUnsubscribed;
        _conn.DepthRequested     += OnDepthRequested;
        _conn.DepthUnsubscribed  += OnDepthUnsubscribed;

        _activeAccount = Core.Instance.Accounts.FirstOrDefault();
        if (_activeAccount != null)
            _activeAccount.Updated += OnAccountUpdated;

        Core.Instance.AccountAdded    += OnAccountAdded;
        Core.Instance.TradeAdded      += OnTradeAdded;
        Core.Instance.PositionAdded   += OnPositionChanged;
        Core.Instance.PositionRemoved += OnPositionChanged;

        _ = ConnectAndIntroduceAsync();
        Log("Risk Engine Plugin started.", StrategyLoggingLevel.Info);
    }

    private async Task ConnectAndIntroduceAsync()
    {
        if (_conn is null) return;
        await _conn.ConnectAsync();
        await SendHelloAsync();
        SendAccountStateNow(force: true);
        _ = BackfillHistoricalTradesAsync();
    }

    // ── Historical trade backfill ─────────────────────────────────────────────

    private async Task BackfillHistoricalTradesAsync()
    {
        if (_conn is null || _activeAccount is null) return;
        try
        {
            var req = new TradesHistoryRequestParameters
            {
                From = DateTime.UtcNow.AddDays(-Math.Max(1, BackfillDays)),
                To   = DateTime.UtcNow,
            };
            string connId = _activeAccount.ComplexId.ConnectionId ?? "";
            if (string.IsNullOrEmpty(connId))
            {
                Log("Backfill: no ConnectionId on active account — skipping", StrategyLoggingLevel.Error);
                return;
            }

            var trades = await Task.Run(() => Core.Instance.GetTrades(req, connId));
            if (trades == null) { Log("Backfill: GetTrades returned null", StrategyLoggingLevel.Error); return; }

            int sent = 0, skipped = 0;
            foreach (var trade in trades)
            {
                if (trade?.Account?.Id != _activeAccount.Id) { skipped++; continue; }
                var ev = RiskEngineEventMapper.MapHistoricalFill(trade);
                if (ev is null) { skipped++; continue; }
                await _conn.SendHistoricalFillAsync(ev);
                sent++;
            }
            Log($"Backfill: sent {sent} historical trade(s), skipped {skipped}", StrategyLoggingLevel.Info);
        }
        catch (Exception ex)
        {
            Log($"BackfillHistoricalTradesAsync error: {ex.Message}", StrategyLoggingLevel.Error);
        }
    }

    // ── Hello ─────────────────────────────────────────────────────────────────

    private async Task SendHelloAsync()
    {
        if (_conn is null || _activeAccount is null) return;
        try
        {
            var hello = RiskEngineEventMapper.MapHello(_activeAccount);
            await _conn.SendHelloAsync(hello);
            Log($"Hello sent: {hello.Broker}/{hello.BrokerAccountId} ({hello.AccountName})", StrategyLoggingLevel.Info);
        }
        catch (Exception ex)
        {
            Log($"SendHelloAsync error: {ex.Message}", StrategyLoggingLevel.Error);
        }
    }

    // ── Teardown ──────────────────────────────────────────────────────────────

    protected override void OnStop()
    {
        Core.Instance.AccountAdded    -= OnAccountAdded;
        Core.Instance.TradeAdded      -= OnTradeAdded;
        Core.Instance.PositionAdded   -= OnPositionChanged;
        Core.Instance.PositionRemoved -= OnPositionChanged;

        if (_activeAccount != null)
            _activeAccount.Updated -= OnAccountUpdated;

        UnsubscribeAll();

        _conn?.Dispose();
        _conn = null;
        Log("Risk Engine Plugin stopped.", StrategyLoggingLevel.Info);
    }

    private void UnsubscribeAll()
    {
        foreach (var (_, sym) in _ohlcvSubs)
            try { sym.NewMark -= OnSymbolMark; } catch { }
        foreach (var (_, sym) in _depthSubs)
            try { sym.NewLevel2 -= OnSymbolDepth; } catch { }
        _ohlcvSubs.Clear();
        _depthSubs.Clear();
        _markSubs.Clear();
    }

    // ── Account events ────────────────────────────────────────────────────────

    private void OnAccountAdded(Account account)
    {
        if (_activeAccount is null)
        {
            _activeAccount = account;
            _activeAccount.Updated += OnAccountUpdated;
            SendAccountStateNow(force: true);
        }
    }

    private void OnAccountUpdated(Account account)
    {
        if (_activeAccount is null || account.Id != _activeAccount.Id) return;
        SendAccountStateNow(force: false);
    }

    private void SendAccountStateNow(bool force)
    {
        if (_conn is null || _activeAccount is null) return;
        long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        if (!force && (now - _lastAccountStateMs) < AccountStateMinIntervalMs) return;
        _lastAccountStateMs = now;
        try
        {
            var state = RiskEngineEventMapper.MapAccountState(_activeAccount);
            _ = _conn.SendAccountStateAsync(state);
        }
        catch (Exception ex)
        {
            Log($"SendAccountStateNow error: {ex.Message}", StrategyLoggingLevel.Error);
        }
    }

    // ── Trade / position events ───────────────────────────────────────────────

    private void OnTradeAdded(Trade trade)
    {
        if (_conn is null) return;
        try
        {
            var fill = RiskEngineEventMapper.MapFill(trade);
            if (fill is null) return;
            _ = _conn.SendFillAsync(fill);
        }
        catch (Exception ex)
        {
            Log($"OnTradeAdded error: {ex.Message}", StrategyLoggingLevel.Error);
        }
    }

    private void OnPositionChanged(Position position)
    {
        try { SendPositionSnapshot(); }
        catch (Exception ex) { Log($"OnPositionChanged error: {ex.Message}", StrategyLoggingLevel.Error); }
    }

    private void SendPositionSnapshot()
    {
        if (_conn is null) return;
        try
        {
            var account = _activeAccount ?? Core.Instance.Accounts.FirstOrDefault();
            if (account is null) return;
            var positions = (Core.Instance.Positions ?? Enumerable.Empty<Position>())
                .Where(p => p.Account?.Id == account.Id)
                .ToArray();
            var snap = RiskEngineEventMapper.MapPositions(account, positions);
            _ = _conn.SendPositionSnapshotAsync(snap);
        }
        catch (Exception ex)
        {
            Log($"SendPositionSnapshot error: {ex.Message}", StrategyLoggingLevel.Error);
        }
    }

    // ── R4: OHLCV demand-driven subscriptions ─────────────────────────────────

    private void OnOhlcvRequested(JsonElement req)
    {
        if (_conn is null) return;
        string symbol   = req.TryGetProperty("symbol",   out var s)  ? (s.GetString()  ?? "") : "";
        string interval = req.TryGetProperty("interval", out var iv) ? (iv.GetString() ?? "1m") : "1m";
        if (string.IsNullOrEmpty(symbol)) return;

        var qtSym = FindSymbol(symbol);
        if (qtSym is null)
        {
            Log($"R4: symbol {symbol} not found in Quantower", StrategyLoggingLevel.Error);
            return;
        }

        // Subscribe mark price for this symbol (idempotent)
        if (!_markSubs.ContainsKey(symbol))
        {
            _markSubs[symbol] = qtSym;
            qtSym.NewMark += OnSymbolMark;
        }
        _ohlcvSubs[symbol] = qtSym;

        Log($"R4: subscribed {symbol} mark-price; sending {interval} history", StrategyLoggingLevel.Info);
        _ = SendHistoricalOhlcvAsync(qtSym, symbol, interval);
    }

    private void OnOhlcvUnsubscribed(JsonElement req)
    {
        string symbol = req.TryGetProperty("symbol", out var s) ? (s.GetString() ?? "") : "";
        if (string.IsNullOrEmpty(symbol)) return;

        if (_markSubs.TryGetValue(symbol, out var qtSym))
        {
            try { qtSym.NewMark -= OnSymbolMark; } catch { }
            _markSubs.Remove(symbol);
        }
        _ohlcvSubs.Remove(symbol);
        Log($"R4: unsubscribed {symbol} mark-price / OHLCV", StrategyLoggingLevel.Info);
    }

    // ── R4: Depth subscriptions ───────────────────────────────────────────────

    private void OnDepthRequested(JsonElement req)
    {
        if (_conn is null) return;
        string symbol = req.TryGetProperty("symbol", out var s) ? (s.GetString() ?? "") : "";
        if (string.IsNullOrEmpty(symbol) || _depthSubs.ContainsKey(symbol)) return;

        var qtSym = FindSymbol(symbol);
        if (qtSym is null) return;

        _depthSubs[symbol] = qtSym;
        qtSym.NewLevel2 += OnSymbolDepth;
        Log($"R4: subscribed {symbol} depth (Level2)", StrategyLoggingLevel.Info);
    }

    private void OnDepthUnsubscribed(JsonElement req)
    {
        string symbol = req.TryGetProperty("symbol", out var s) ? (s.GetString() ?? "") : "";
        if (string.IsNullOrEmpty(symbol)) return;
        if (_depthSubs.TryGetValue(symbol, out var qtSym))
        {
            try { qtSym.NewLevel2 -= OnSymbolDepth; } catch { }
            _depthSubs.Remove(symbol);
        }
    }

    // ── R4: Historical OHLCV sender ───────────────────────────────────────────

    private async Task SendHistoricalOhlcvAsync(Symbol qtSym, string symbolName, string interval)
    {
        if (_conn is null) return;
        try
        {
            var period = IntervalToPeriod(interval);
            var req = new HistoryRequestParameters
            {
                Symbol      = qtSym,
                FromTime    = DateTime.UtcNow.AddDays(-5),
                ToTime      = DateTime.UtcNow,
                Aggregation = new HistoryAggregationTime(period, HistoryType.Last),
                CancellationToken = CancellationToken.None,
            };

            var history = await Task.Run(() => qtSym.GetHistory(req));
            if (history is null) return;

            int count = 0;
            foreach (var raw in history)
            {
                if (raw is not HistoryItemBar bar) continue;
                var ev = new OhlcvBarEvent
                {
                    Symbol   = symbolName,
                    Interval = interval,
                    OpenTime = (long)(bar.TimeLeft.ToUniversalTime() - DateTime.UnixEpoch).TotalMilliseconds,
                    Open     = (double)bar.Open,
                    High     = (double)bar.High,
                    Low      = (double)bar.Low,
                    Close    = (double)bar.Close,
                    Volume   = (double)bar.Volume,
                    Closed   = true,
                };
                await _conn.SendOhlcvBarAsync(ev);
                count++;
            }
            Log($"R4: sent {count} historical bars for {symbolName} ({interval})", StrategyLoggingLevel.Info);
        }
        catch (Exception ex)
        {
            Log($"SendHistoricalOhlcvAsync ({symbolName}): {ex.Message}", StrategyLoggingLevel.Error);
        }
    }

    // ── R4: Market data event handlers ───────────────────────────────────────

    private void OnSymbolMark(Symbol symbol, Mark mark)
    {
        if (_conn is null) return;
        try
        {
            var ev = new MarkPriceEvent
            {
                Symbol    = NormalizeSymbol(symbol.Name),
                Price     = (double)mark.Price,
                Timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
            _ = _conn.SendMarkPriceAsync(ev);
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[R4] OnSymbolMark error: {ex.Message}");
        }
    }

    private void OnSymbolDepth(Symbol symbol, Level2Quote quote, DOMQuote dom)
    {
        if (_conn is null) return;
        try
        {
            var bids = dom.Bids.Take(20)
                           .Select(l => new double[] { (double)l.Price, (double)l.Size })
                           .ToArray();
            var asks = dom.Asks.Take(20)
                           .Select(l => new double[] { (double)l.Price, (double)l.Size })
                           .ToArray();
            var ev = new DepthSnapshotEvent
            {
                Symbol = NormalizeSymbol(symbol.Name),
                Bids   = bids,
                Asks   = asks,
            };
            _ = _conn.SendDepthSnapshotAsync(ev);
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[R4] OnSymbolDepth error: {ex.Message}");
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private static Symbol? FindSymbol(string engineName)
    {
        return Core.Instance.Symbols.FirstOrDefault(s =>
            NormalizeSymbol(s.Name).Equals(engineName, StringComparison.OrdinalIgnoreCase));
    }

    private static string NormalizeSymbol(string name)
        => name.Replace("/", "").Replace(" ", "").Replace("-", "").ToUpperInvariant();

    private static Period IntervalToPeriod(string interval) => interval switch
    {
        "1m"  => Period.MIN1,
        "3m"  => Period.MIN3,
        "5m"  => Period.MIN5,
        "15m" => Period.MIN15,
        "30m" => Period.MIN30,
        "1h"  => Period.HOUR1,
        "4h"  => Period.HOUR4,
        "1d"  => Period.DAY1,
        _     => Period.MIN1,
    };
}
