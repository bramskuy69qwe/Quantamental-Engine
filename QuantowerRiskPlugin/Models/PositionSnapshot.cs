using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

/// <summary>
/// JSON payload sent to the engine with the current open positions.
/// Sent on every position change event from Quantower.
/// Maps to the engine's "position_snapshot" event in platform_bridge.py.
/// </summary>
public class PositionSnapshot
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "position_snapshot";

    [JsonPropertyName("accountId")]
    public string AccountId { get; set; } = "";

    [JsonPropertyName("positions")]
    public List<PositionItem> Positions { get; set; } = new();
}

public class PositionItem
{
    [JsonPropertyName("symbol")]
    public string Symbol { get; set; } = "";

    /// <summary>
    /// Signed quantity: positive = LONG, negative = SHORT.
    /// The engine infers direction from the sign.
    /// </summary>
    [JsonPropertyName("quantity")]
    public double Quantity { get; set; }

    [JsonPropertyName("avgPrice")]
    public double AvgPrice { get; set; }

    [JsonPropertyName("unrealizedPnL")]
    public double UnrealizedPnL { get; set; }
}
