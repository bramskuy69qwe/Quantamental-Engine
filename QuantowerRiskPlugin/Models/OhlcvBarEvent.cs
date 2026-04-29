using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

public class OhlcvBarEvent
{
    [JsonPropertyName("type")]      public string Type     { get; set; } = "ohlcv_bar";
    [JsonPropertyName("symbol")]    public string Symbol   { get; set; } = "";
    [JsonPropertyName("interval")]  public string Interval { get; set; } = "1m";
    [JsonPropertyName("open_time")] public long   OpenTime { get; set; }
    [JsonPropertyName("open")]      public double Open     { get; set; }
    [JsonPropertyName("high")]      public double High     { get; set; }
    [JsonPropertyName("low")]       public double Low      { get; set; }
    [JsonPropertyName("close")]     public double Close    { get; set; }
    [JsonPropertyName("volume")]    public double Volume   { get; set; }
    [JsonPropertyName("closed")]    public bool   Closed   { get; set; } = true;
}
