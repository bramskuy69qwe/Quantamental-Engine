using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

public class DepthSnapshotEvent
{
    [JsonPropertyName("type")]   public string       Type   { get; set; } = "depth_snapshot";
    [JsonPropertyName("symbol")] public string       Symbol { get; set; } = "";
    [JsonPropertyName("bids")]   public double[][]   Bids   { get; set; } = [];
    [JsonPropertyName("asks")]   public double[][]   Asks   { get; set; } = [];
}
