using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

/// <summary>
/// Full order snapshot sent to the engine on OrderAdded/OrderRemoved and on connect.
/// Maps to the engine's "order_snapshot" event type in platform_bridge.py.
/// </summary>
public class OrderSnapshot
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "order_snapshot";

    [JsonPropertyName("accountId")]
    public string AccountId { get; set; } = "";

    [JsonPropertyName("orders")]
    public List<OrderItem> Orders { get; set; } = new();
}

/// <summary>
/// Individual order within an OrderSnapshot.
/// Maps to the engine's NormalizedOrder / orders DB table.
/// </summary>
public class OrderItem
{
    [JsonPropertyName("exchangeOrderId")]
    public string ExchangeOrderId { get; set; } = "";

    [JsonPropertyName("terminalOrderId")]
    public string TerminalOrderId { get; set; } = "";

    [JsonPropertyName("clientOrderId")]
    public string ClientOrderId { get; set; } = "";

    [JsonPropertyName("symbol")]
    public string Symbol { get; set; } = "";

    [JsonPropertyName("side")]
    public string Side { get; set; } = "";

    [JsonPropertyName("orderType")]
    public string OrderType { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("price")]
    public double Price { get; set; }

    [JsonPropertyName("stopPrice")]
    public double StopPrice { get; set; }

    [JsonPropertyName("quantity")]
    public double Quantity { get; set; }

    [JsonPropertyName("filledQuantity")]
    public double FilledQuantity { get; set; }

    [JsonPropertyName("avgFillPrice")]
    public double AvgFillPrice { get; set; }

    [JsonPropertyName("reduceOnly")]
    public bool ReduceOnly { get; set; }

    [JsonPropertyName("timeInForce")]
    public string TimeInForce { get; set; } = "";

    [JsonPropertyName("positionSide")]
    public string PositionSide { get; set; } = "";

    [JsonPropertyName("positionId")]
    public string PositionId { get; set; } = "";

    [JsonPropertyName("createdAt")]
    public long CreatedAt { get; set; }
}
