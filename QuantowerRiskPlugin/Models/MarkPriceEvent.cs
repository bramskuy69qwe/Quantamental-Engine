using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

public class MarkPriceEvent
{
    [JsonPropertyName("type")]      public string Type      { get; set; } = "mark_price";
    [JsonPropertyName("symbol")]    public string Symbol    { get; set; } = "";
    [JsonPropertyName("price")]     public double Price     { get; set; }
    [JsonPropertyName("timestamp")] public long   Timestamp { get; set; }
}
