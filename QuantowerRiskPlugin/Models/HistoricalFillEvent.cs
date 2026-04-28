using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

/// <summary>
/// One historical Trade pulled by the plugin via Core.GetTrades on connect.
/// Sent to the engine for backfilling exchange_history without hitting Binance
/// REST. Idempotent on the engine side via the Quantower trade ID.
/// </summary>
public class HistoricalFillEvent
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "historical_fill";

    [JsonPropertyName("trade_id")]
    public string TradeId { get; set; } = "";

    [JsonPropertyName("account_id")]
    public string AccountId { get; set; } = "";

    [JsonPropertyName("symbol")]
    public string Symbol { get; set; } = "";

    [JsonPropertyName("side")]
    public string Side { get; set; } = "";   // "BUY" or "SELL"

    [JsonPropertyName("price")]
    public double Price { get; set; }

    [JsonPropertyName("quantity")]
    public double Quantity { get; set; }

    [JsonPropertyName("gross_pnl")]
    public double GrossPnL { get; set; }

    [JsonPropertyName("net_pnl")]
    public double NetPnL { get; set; }

    [JsonPropertyName("fee")]
    public double Fee { get; set; }

    /// <summary>Unix milliseconds.</summary>
    [JsonPropertyName("timestamp")]
    public long Timestamp { get; set; }

    [JsonPropertyName("order_id")]
    public string OrderId { get; set; } = "";

    [JsonPropertyName("position_id")]
    public string PositionId { get; set; } = "";

    /// <summary>"Open" / "Close" / "Reverse" — Quantower's PositionImpactType.</summary>
    [JsonPropertyName("position_impact_type")]
    public string PositionImpactType { get; set; } = "";
}
