using TradingPlatform.BusinessLayer;
using QuantowerRiskPlugin.Models;

namespace QuantowerRiskPlugin;

/// <summary>
/// Quantower plugin entry point.
///
/// HOW TO INSTALL:
///   1. Build this project (Release configuration).
///   2. Copy QuantowerRiskPlugin.dll to:
///        %AppData%\Quantower\Settings\Plugins\
///      (or the custom plugins folder set in Quantower → General Settings → Plugins Path)
///   3. Restart Quantower.
///   4. Go to Settings → Plugins → "Risk Engine Plugin" → configure Engine URL.
///
/// HOW IT WORKS:
///   - On Init(), subscribes to Quantower's order-fill and position-change events.
///   - Each event maps to a JSON payload and is sent to the risk engine over WebSocket.
///   - If WebSocket is unavailable (e.g., engine not running), falls back to REST.
///   - On Dispose(), cleanly disconnects.
/// </summary>
[PluginInfo(
    Name        = "Risk Engine Plugin",
    Version     = "1.0.0",
    Description = "Sends fills and positions to the Quantamental Risk Engine in real-time.",
    Author      = "Quantamental"
)]
public class RiskEnginePlugin : Plugin
{
    // ── Plugin settings (editable in Quantower Settings panel) ───────────────

    [InputParameter("Engine URL", 0,
        Description = "WebSocket URL of the risk engine (e.g. ws://localhost:8000/ws/platform)")]
    public string EngineUrl { get; set; } = "ws://localhost:8000/ws/platform";

    // ── Runtime fields ────────────────────────────────────────────────────────

    private RiskEngineConnection? _conn;
    private Account? _activeAccount;

    // ── Plugin lifecycle ──────────────────────────────────────────────────────

    public override void Init()
    {
        Log($"Risk Engine Plugin initializing — connecting to {EngineUrl}");

        _conn = new RiskEngineConnection(EngineUrl);

        // Wire risk-state push → log (extend this to chart overlays as needed)
        _conn.RiskStateReceived += state =>
        {
            if (state.TryGetProperty("dd_state", out var dd) && dd.GetString() == "limit")
                Log("RISK ALERT: Drawdown limit reached!", LoggingLevel.Error);
        };

        // Subscribe to account events
        Core.Instance.Accounts.AddedItem    += OnAccountAdded;
        Core.Instance.Accounts.RemovedItem  += OnAccountRemoved;

        // Subscribe to whichever account is currently active
        _activeAccount = Core.Instance.Accounts.FirstOrDefault();
        if (_activeAccount != null)
            SubscribeToAccount(_activeAccount);

        // Subscribe to new order fills (fired for all accounts)
        Core.Instance.TradeHistory.AddedItem += OnOrderFilled;

        _ = _conn.ConnectAsync();
        Log("Risk Engine Plugin started.");
    }

    public override void Dispose()
    {
        Core.Instance.Accounts.AddedItem   -= OnAccountAdded;
        Core.Instance.Accounts.RemovedItem -= OnAccountRemoved;
        Core.Instance.TradeHistory.AddedItem -= OnOrderFilled;

        if (_activeAccount != null)
            UnsubscribeFromAccount(_activeAccount);

        _conn?.Dispose();
        Log("Risk Engine Plugin stopped.");
        base.Dispose();
    }

    // ── Account wiring ────────────────────────────────────────────────────────

    private void SubscribeToAccount(Account account)
    {
        account.PositionList.AddedItem   += OnPositionChanged;
        account.PositionList.RemovedItem += OnPositionChanged;
        account.PositionList.UpdatedItem += OnPositionChanged;
    }

    private void UnsubscribeFromAccount(Account account)
    {
        account.PositionList.AddedItem   -= OnPositionChanged;
        account.PositionList.RemovedItem -= OnPositionChanged;
        account.PositionList.UpdatedItem -= OnPositionChanged;
    }

    private void OnAccountAdded(Account account)
    {
        SubscribeToAccount(account);
    }

    private void OnAccountRemoved(Account account)
    {
        UnsubscribeFromAccount(account);
    }

    // ── Event handlers ────────────────────────────────────────────────────────

    private void OnOrderFilled(HistoryItem item)
    {
        if (_conn is null) return;
        try
        {
            // HistoryItem wraps a filled Order — cast to access order fields
            if (item is not Order order) return;
            if (order.Status != OrderStatus.Filled && order.Status != OrderStatus.PartiallyFilled)
                return;

            var fill = RiskEngineEventMapper.MapFill(order);
            if (fill is null) return;   // MapFill returns null when account/symbol is missing
            _ = _conn.SendFillAsync(fill);
        }
        catch (Exception ex)
        {
            Log($"OnOrderFilled error: {ex.Message}", LoggingLevel.Error);
        }
    }

    private void OnPositionChanged(Position position)
    {
        if (_conn is null || _activeAccount is null) return;
        try
        {
            var positions = _activeAccount.PositionList.ToArray();
            var snap = RiskEngineEventMapper.MapPositions(_activeAccount, positions);
            _ = _conn.SendPositionSnapshotAsync(snap);
        }
        catch (Exception ex)
        {
            Log($"OnPositionChanged error: {ex.Message}", LoggingLevel.Error);
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private void Log(string message, LoggingLevel level = LoggingLevel.Trading)
        => Core.Instance.Loggers.Log(message, level);
}
