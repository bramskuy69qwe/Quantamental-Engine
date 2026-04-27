using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

/// <summary>
/// Sent by the plugin once on WebSocket connect, carrying the active account's
/// broker identity. The engine uses this to auto-populate broker_account_id on
/// the matching account row, so the user does not have to type their broker UID.
/// </summary>
public class HelloEvent
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "hello";

    /// <summary>"quantower" today; future plugins will identify themselves here.</summary>
    [JsonPropertyName("terminal")]
    public string Terminal { get; set; } = "quantower";

    /// <summary>Broker / vendor name as reported by Quantower (e.g. "Binance Futures").</summary>
    [JsonPropertyName("broker")]
    public string Broker { get; set; } = "";

    /// <summary>Broker-side account UID (Quantower's Account.Id).</summary>
    [JsonPropertyName("broker_account_id")]
    public string BrokerAccountId { get; set; } = "";

    /// <summary>Display name (Quantower's Account.Name).</summary>
    [JsonPropertyName("account_name")]
    public string AccountName { get; set; } = "";

    /// <summary>Account currency (e.g. "USDT", "USD").</summary>
    [JsonPropertyName("account_currency")]
    public string AccountCurrency { get; set; } = "";

    /// <summary>
    /// Snapshot of Account.AdditionalInfo (broker-specific extras: UID, margin,
    /// position counts, etc.). Engine logs this so the user can inspect what
    /// keys their broker exposes — useful for finding the right UID field.
    /// </summary>
    [JsonPropertyName("additional_info")]
    public Dictionary<string, string> AdditionalInfo { get; set; } = new();
}
