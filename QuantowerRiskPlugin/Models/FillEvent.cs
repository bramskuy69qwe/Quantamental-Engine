using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

/// <summary>
/// JSON payload sent to the engine when a trade is filled.
/// Maps to the engine's "fill" event type in platform_bridge.py.
/// </summary>
public class FillEvent
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "fill";

    /// <summary>Exchange-assigned trade ID (Binance tradeId).</summary>
    [JsonPropertyName("exchangeFillId")]
    public string ExchangeFillId { get; set; } = "";

    /// <summary>Terminal-assigned trade ID (Quantower Trade.UniqueId).</summary>
    [JsonPropertyName("terminalFillId")]
    public string TerminalFillId { get; set; } = "";

    /// <summary>Parent order exchange ID (Binance orderId).</summary>
    [JsonPropertyName("exchangeOrderId")]
    public string ExchangeOrderId { get; set; } = "";

    [JsonPropertyName("symbol")]
    public string Symbol { get; set; } = "";

    [JsonPropertyName("side")]
    public string Side { get; set; } = "";   // "BUY" or "SELL"

    /// <summary>Position direction: "LONG" or "SHORT" (not the trade side).</summary>
    [JsonPropertyName("direction")]
    public string Direction { get; set; } = "";

    /// <summary>Quantower position ID this fill belongs to.</summary>
    [JsonPropertyName("positionId")]
    public string PositionId { get; set; } = "";

    /// <summary>Whether this fill opens or closes a position.</summary>
    [JsonPropertyName("isClose")]
    public bool IsClose { get; set; }

    [JsonPropertyName("price")]
    public double Price { get; set; }

    [JsonPropertyName("quantity")]
    public double Quantity { get; set; }

    [JsonPropertyName("grossPnL")]
    public double GrossPnL { get; set; }

    [JsonPropertyName("fee")]
    public double Fee { get; set; }

    [JsonPropertyName("timestamp")]
    public long Timestamp { get; set; }      // Unix milliseconds

    [JsonPropertyName("accountId")]
    public string AccountId { get; set; } = "";
}
