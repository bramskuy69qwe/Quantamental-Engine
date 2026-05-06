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
    /// <summary>Broker-side position ID (stable within session).</summary>
    [JsonPropertyName("positionId")]
    public string PositionId { get; set; } = "";

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

    /// <summary>Position open time as Unix milliseconds (0 = unknown).</summary>
    [JsonPropertyName("openTimeMs")]
    public long OpenTimeMs { get; set; }

    /// <summary>Take-profit price (0 = none set).</summary>
    [JsonPropertyName("tpPrice")]
    public double TpPrice { get; set; }

    /// <summary>Stop-loss price (0 = none set).</summary>
    [JsonPropertyName("slPrice")]
    public double SlPrice { get; set; }

    /// <summary>Liquidation price (0 = unknown).</summary>
    [JsonPropertyName("liquidationPrice")]
    public double LiquidationPrice { get; set; }
}
