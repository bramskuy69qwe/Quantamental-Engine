using System.Text.Json.Serialization;

namespace QuantowerRiskPlugin.Models;

/// <summary>
/// Streamed by the plugin on every Account.Updated event. The engine writes
/// the values directly into app_state.account_state, replacing the periodic
/// Binance fetch_account() call while the plugin is connected.
/// </summary>
public class AccountStateEvent
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "account_state";

    /// <summary>Quantower's Account.Id — used for routing to the engine row.</summary>
    [JsonPropertyName("account_id")]
    public string AccountId { get; set; } = "";

    /// <summary>Wallet balance in account currency (no unrealized).</summary>
    [JsonPropertyName("balance")]
    public double Balance { get; set; }

    /// <summary>Wallet + unrealized PnL = margin balance / equity.</summary>
    [JsonPropertyName("total_equity")]
    public double TotalEquity { get; set; }

    /// <summary>Sum of unrealized PnL across all positions on this account.</summary>
    [JsonPropertyName("unrealized_pnl")]
    public double UnrealizedPnL { get; set; }

    /// <summary>Free margin available for new positions.</summary>
    [JsonPropertyName("available_margin")]
    public double AvailableMargin { get; set; }

    /// <summary>Sum of maintenance margin requirements across positions.</summary>
    [JsonPropertyName("maintenance_margin")]
    public double MaintenanceMargin { get; set; }

    /// <summary>Decimal margin ratio (0.0028 = 0.28%).</summary>
    [JsonPropertyName("margin_ratio")]
    public double MarginRatio { get; set; }

    /// <summary>Account currency name (e.g. "USDT", "USD").</summary>
    [JsonPropertyName("currency")]
    public string Currency { get; set; } = "";

    /// <summary>Unix milliseconds when the snapshot was captured.</summary>
    [JsonPropertyName("timestamp")]
    public long Timestamp { get; set; }
}
