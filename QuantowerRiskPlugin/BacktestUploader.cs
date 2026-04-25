using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

namespace QuantowerRiskPlugin;

/// <summary>
/// Uploads a Quantower backtest result to the Risk Engine's
/// POST /api/backtest/qt-import endpoint.
///
/// HOW TO USE:
///   1. Run a Strategy backtest in Quantower (Strategy Manager → Backtest).
///   2. After the run completes, call BacktestUploader.UploadAsync(result, engineBaseUrl).
///      The engine will store the results and display them in the Backtest panel.
///
/// The uploader reuses the HttpClient from RiskEngineConnection to stay within
/// the same connection pool — pass the connection's base URL on construction.
///
/// INTEGRATION POINT (when wiring into RiskEnginePlugin.cs):
///   After a strategy finishes (Quantower fires a strategy-completed event),
///   build a BacktestResult from the strategy's statistics, then call:
///       await new BacktestUploader(EngineUrl).UploadAsync(result);
/// </summary>
public sealed class BacktestUploader
{
    private readonly string _restBaseUrl;
    private static readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(30) };

    public BacktestUploader(string engineUrl)
    {
        // Accept ws:// or http:// — normalise to http base
        _restBaseUrl = engineUrl
            .Replace("ws://", "http://")
            .Replace("wss://", "https://");
        if (_restBaseUrl.EndsWith("/ws/platform"))
            _restBaseUrl = _restBaseUrl[..^"/ws/platform".Length];
        _restBaseUrl = _restBaseUrl.TrimEnd('/');
    }

    /// <summary>
    /// Upload a completed backtest result to the engine.
    /// Returns the session_id assigned by the engine, or -1 on failure.
    /// </summary>
    public async Task<int> UploadAsync(BacktestResult result)
    {
        string json;
        try
        {
            json = JsonSerializer.Serialize(result, new JsonSerializerOptions
            {
                WriteIndented = false,
                DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            });
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[BacktestUploader] Serialization error: {ex.Message}");
            return -1;
        }

        try
        {
            var content  = new StringContent(json, Encoding.UTF8, "application/json");
            var response = await _http.PostAsync(_restBaseUrl + "/api/backtest/qt-import", content);

            if (!response.IsSuccessStatusCode)
            {
                System.Diagnostics.Debug.WriteLine($"[BacktestUploader] HTTP {(int)response.StatusCode}");
                return -1;
            }

            var body = await response.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("session_id", out var sid))
                return sid.GetInt32();
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[BacktestUploader] Upload failed: {ex.Message}");
        }
        return -1;
    }
}


// ── Data models ───────────────────────────────────────────────────────────────

/// <summary>
/// Full backtest result payload matching the engine's qt-import schema.
/// Build this from Quantower's strategy statistics after a backtest run.
/// </summary>
public sealed class BacktestResult
{
    [JsonPropertyName("session_name")]
    public string SessionName { get; set; } = "Quantower Backtest";

    [JsonPropertyName("strategy")]
    public string Strategy { get; set; } = "";

    [JsonPropertyName("date_from")]
    public string DateFrom { get; set; } = "";   // "YYYY-MM-DD"

    [JsonPropertyName("date_to")]
    public string DateTo { get; set; } = "";     // "YYYY-MM-DD"

    [JsonPropertyName("trades")]
    public List<BacktestTrade> Trades { get; set; } = new();

    [JsonPropertyName("summary")]
    public BacktestSummary Summary { get; set; } = new();
}


/// <summary>
/// One closed trade from Quantower's backtest result.
/// Map Quantower's HistoryItem / TradeStatistic fields to these properties.
/// </summary>
public sealed class BacktestTrade
{
    [JsonPropertyName("symbol")]
    public string Symbol { get; set; } = "";

    [JsonPropertyName("side")]
    public string Side { get; set; } = "";       // "long" | "short"

    [JsonPropertyName("entry_dt")]
    public string EntryDt { get; set; } = "";    // ISO 8601

    [JsonPropertyName("exit_dt")]
    public string ExitDt { get; set; } = "";     // ISO 8601

    [JsonPropertyName("entry_price")]
    public double EntryPrice { get; set; }

    [JsonPropertyName("exit_price")]
    public double ExitPrice { get; set; }

    [JsonPropertyName("size_usdt")]
    public double SizeUsdt { get; set; }

    /// <summary>R-multiple (net PnL / initial risk). Quantower may call this "R-Factor" or compute it as GrossPnL / MaxDrawdown.</summary>
    [JsonPropertyName("pnl_r")]
    public double PnlR { get; set; }

    [JsonPropertyName("pnl_usdt")]
    public double PnlUsdt { get; set; }

    /// <summary>Round-trip slippage in basis points.</summary>
    [JsonPropertyName("slippage_bps")]
    public double SlippageBps { get; set; }

    /// <summary>Fill quality 0–1 (1 = perfect fill at intended price).</summary>
    [JsonPropertyName("exec_quality")]
    public double ExecQuality { get; set; }

    [JsonPropertyName("exit_reason")]
    public string ExitReason { get; set; } = "";   // "sl" | "tp" | "signal" | etc.
}


/// <summary>
/// Aggregate statistics from Quantower's backtest report.
/// </summary>
public sealed class BacktestSummary
{
    [JsonPropertyName("total_r")]
    public double TotalR { get; set; }

    [JsonPropertyName("win_rate")]
    public double WinRate { get; set; }

    [JsonPropertyName("avg_slippage_bps")]
    public double AvgSlippageBps { get; set; }

    [JsonPropertyName("profit_factor")]
    public double ProfitFactor { get; set; }

    [JsonPropertyName("max_drawdown_pct")]
    public double MaxDrawdownPct { get; set; }

    [JsonPropertyName("sharpe")]
    public double Sharpe { get; set; }
}
