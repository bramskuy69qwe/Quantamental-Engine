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
    /// Map a Quantower Trade (a fill report) to a FillEvent for the engine.
    /// Returns null if the trade is missing a required field (account, symbol).
    /// </summary>
    public static FillEvent? MapFill(Trade trade)
    {
        if (trade.Account is null)
        {
            System.Diagnostics.Debug.WriteLine("[RiskEngine] MapFill: skipping — trade.Account is null");
            return null;
        }

        string symbol = NormalizeSymbol(trade.Symbol?.Name ?? "");
        if (string.IsNullOrEmpty(symbol))
        {
            System.Diagnostics.Debug.WriteLine("[RiskEngine] MapFill: skipping — symbol is null/empty");
            return null;
        }

        bool isBuy = trade.Side == Side.Buy;

        long timestampMs;
        try { timestampMs = ((DateTimeOffset)trade.DateTime).ToUnixTimeMilliseconds(); }
        catch { timestampMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); }

        return new FillEvent
        {
            Symbol    = symbol,
            Side      = isBuy ? "BUY" : "SELL",
            Price     = trade.Price,
            Quantity  = Math.Abs(trade.Quantity),
            GrossPnL  = (double)trade.GrossPnl.Value,
            Fee       = Math.Abs((double)trade.Fee.Value),
            Timestamp = timestampMs,
            AccountId = trade.Account.Id,
        };
    }

    /// <summary>
    /// Build a position snapshot from the given positions belonging to the account.
    /// </summary>
    public static PositionSnapshot MapPositions(Account account, IEnumerable<Position> positions)
    {
        var snap = new PositionSnapshot { AccountId = account.Id };
        foreach (var p in positions)
        {
            // Signed quantity: positive for LONG, negative for SHORT
            double signedQty = p.Side == Side.Buy
                ? p.Quantity
                : -p.Quantity;

            snap.Positions.Add(new PositionItem
            {
                Symbol        = NormalizeSymbol(p.Symbol?.Name ?? ""),
                Quantity      = signedQty,
                AvgPrice      = p.OpenPrice,
                UnrealizedPnL = (double)p.GrossPnL.Value,
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
