using TradingPlatform.BusinessLayer;
using QuantowerRiskPlugin.Models;

namespace QuantowerRiskPlugin;

/// <summary>
/// Quantower strategy entry point — bridges fill/position events to the risk engine.
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

    private RiskEngineConnection? _conn;
    private Account? _activeAccount;

    // Throttle Account.Updated -> account_state events. Quantower fires Updated
    // on every quote tick that touches unrealized PnL; 5 Hz is plenty for the
    // engine's risk dashboard.
    private long _lastAccountStateMs;
    private const int AccountStateMinIntervalMs = 200;

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

        // Pick the first available account as the active one.
        _activeAccount = Core.Instance.Accounts.FirstOrDefault();

        // Wire engine-wide events
        Core.Instance.AccountAdded   += OnAccountAdded;
        Core.Instance.TradeAdded     += OnTradeAdded;
        Core.Instance.PositionAdded  += OnPositionChanged;
        Core.Instance.PositionRemoved += OnPositionChanged;

        _ = ConnectAndIntroduceAsync();
        Log("Risk Engine Plugin started.", StrategyLoggingLevel.Info);
    }

    /// <summary>
    /// Connect, then send the hello payload so the engine can auto-populate
    /// broker_account_id from Quantower's Account.Id.
    /// </summary>
    private async Task ConnectAndIntroduceAsync()
    {
        if (_conn is null) return;
        await _conn.ConnectAsync();
        await SendHelloAsync();
    }

    private async Task SendHelloAsync()
    {
        if (_conn is null || _activeAccount is null) return;
        try
        {
            var hello = RiskEngineEventMapper.MapHello(_activeAccount);
            await _conn.SendHelloAsync(hello);
            Log($"Hello sent: {hello.Broker}/{hello.BrokerAccountId} ({hello.AccountName})",
                StrategyLoggingLevel.Info);
        }
        catch (Exception ex)
        {
            Log($"SendHelloAsync error: {ex.Message}", StrategyLoggingLevel.Error);
        }
    }

    protected override void OnStop()
    {
        Core.Instance.AccountAdded    -= OnAccountAdded;
        Core.Instance.TradeAdded      -= OnTradeAdded;
        Core.Instance.PositionAdded   -= OnPositionChanged;
        Core.Instance.PositionRemoved -= OnPositionChanged;

        _conn?.Dispose();
        _conn = null;
        Log("Risk Engine Plugin stopped.", StrategyLoggingLevel.Info);
    }

    private void OnAccountAdded(Account account)
    {
        // If we didn't have an account at startup, latch onto the first one that arrives.
        if (_activeAccount is null)
            _activeAccount = account;
    }

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
            // Filter Core.Positions to those belonging to the active account.
            var account = _activeAccount ?? Core.Instance.Accounts.FirstOrDefault();
            if (account is null) return;

            var positions = Core.Instance.Positions
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
}
