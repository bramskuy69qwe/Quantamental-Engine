using TradingPlatform.BusinessLayer;
using QuantowerRiskPlugin.Models;

namespace QuantowerRiskPlugin;

/// <summary>
/// Maps Quantower domain objects to engine event payloads.
/// All symbol normalization happens here so the bridge stays clean.
/// </summary>
internal static class RiskEngineEventMapper
{
    /// <summary>
    /// Map a filled Quantower Order to a FillEvent for the engine.
    /// Returns null if the order is missing a required field (account, symbol).
    /// Callers must null-check the return value.
    /// </summary>
    public static FillEvent? MapFill(Order order)
    {
        // Reject fills with no account — the engine uses account_id for routing
        if (order.Account is null)
        {
            System.Diagnostics.Debug.WriteLine("[RiskEngine] MapFill: skipping fill — order.Account is null");
            return null;
        }

        string symbol = NormalizeSymbol(order.Symbol?.Name ?? "");
        if (string.IsNullOrEmpty(symbol))
        {
            System.Diagnostics.Debug.WriteLine("[RiskEngine] MapFill: skipping fill — symbol is null/empty");
            return null;
        }

        bool isBuy = order.Side == Side.Buy;
        double grossPnl = 0.0;
        try { grossPnl = (double)(order.GrossPnl ?? 0); }
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"[RiskEngine] GrossPnl conversion failed: {ex.Message}"); }

        double fee = 0.0;
        try { fee = Math.Abs((double)(order.TotalFee ?? 0)); }
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"[RiskEngine] TotalFee conversion failed: {ex.Message}"); }

        return new FillEvent
        {
            Symbol    = symbol,
            Side      = isBuy ? "BUY" : "SELL",
            Price     = order.AverageFilledPrice.HasValue
                            ? (double)order.AverageFilledPrice.Value
                            : (double)order.Price,
            Quantity  = Math.Abs((double)order.FilledQuantity),
            GrossPnL  = grossPnl,
            Fee       = fee,
            Timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            AccountId = order.Account.Id,
        };
    }

    /// <summary>
    /// Build a position snapshot from the account's current open positions.
    /// </summary>
    public static PositionSnapshot MapPositions(Account account, IEnumerable<Position> positions)
    {
        var snap = new PositionSnapshot { AccountId = account.Id };
        foreach (var p in positions)
        {
            // Signed quantity: positive for LONG, negative for SHORT
            double signedQty = p.Side == Side.Buy
                ? (double)p.Quantity
                : -(double)p.Quantity;

            double avgPrice = 0.0;
            try { avgPrice = (double)p.OpenPrice; } catch { }

            double unrealized = 0.0;
            try { unrealized = (double)(p.GrossPnl ?? 0); } catch { }

            snap.Positions.Add(new PositionItem
            {
                Symbol       = NormalizeSymbol(p.Symbol?.Name ?? ""),
                Quantity     = signedQty,
                AvgPrice     = avgPrice,
                UnrealizedPnL = unrealized,
            });
        }
        return snap;
    }

    /// <summary>
    /// Normalize Quantower symbol names to engine format.
    /// "BTC/USDT" → "BTCUSDT", "BTC USDT" → "BTCUSDT"
    /// </summary>
    public static string NormalizeSymbol(string qtSymbol)
        => qtSymbol.Replace("/", "").Replace(" ", "").Replace("-", "").ToUpperInvariant();
}
