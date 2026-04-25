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

    [JsonPropertyName("symbol")]
    public string Symbol { get; set; } = "";

    [JsonPropertyName("side")]
    public string Side { get; set; } = "";   // "BUY" or "SELL"

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
