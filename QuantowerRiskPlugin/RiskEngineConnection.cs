using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using QuantowerRiskPlugin.Models;

namespace QuantowerRiskPlugin;

/// <summary>
/// Manages the WebSocket connection to the risk engine's /ws/platform endpoint.
///
/// Connection strategy:
///   1. Attempt WebSocket connection (ws://host:port/ws/platform) with 5s timeout.
///   2. On success: stream fill/position events as JSON text frames.
///      Receive loop handles risk-state pushes from the engine (e.g. risk alerts).
///   3. On failure / disconnect: fall back to REST polling and retry WS on a 30s timer.
///
/// Thread safety: all public methods are async and safe to call from any thread.
/// </summary>
public sealed class RiskEngineConnection : IDisposable
{
    private readonly string _wsUrl;         // ws://localhost:8000/ws/platform
    private readonly string _restBaseUrl;   // http://localhost:8000

    private ClientWebSocket? _ws;
    private CancellationTokenSource _cts = new();
    private Task? _receiveLoop;
    private Task? _reconnectTimer;

    private bool _wsConnected;
    private bool _disposed;

    // REST fallback
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(5) };
    private bool _restFallback;

    /// <summary>Fired when the engine pushes a risk_state payload.</summary>
    public event Action<JsonElement>? RiskStateReceived;

    /// <summary>Fired when the engine sends a request_positions message (reconciliation on connect).</summary>
    public event Action? PositionsRequested;

    public RiskEngineConnection(string engineUrl)
    {
        // Accept either ws:// or http:// — normalise both
        string httpBase = engineUrl
            .Replace("ws://", "http://")
            .Replace("wss://", "https://");
        if (httpBase.EndsWith("/ws/platform"))
            httpBase = httpBase[..^"/ws/platform".Length];

        _restBaseUrl = httpBase.TrimEnd('/');
        _wsUrl = engineUrl.StartsWith("ws") ? engineUrl.TrimEnd('/')
               : engineUrl.Replace("http://", "ws://").Replace("https://", "wss://").TrimEnd('/')
                           + "/ws/platform";
    }

    // ── Connection lifecycle ──────────────────────────────────────────────────

    public async Task ConnectAsync()
    {
        // Cancel and dispose the previous token source before creating a new one.
        // Without this the old _reconnectTimer keeps running on the stale token and
        // can race with the new connection attempt.
        _cts.Cancel();
        _cts.Dispose();
        _cts = new CancellationTokenSource();
        await TryConnectWsAsync();
    }

    private async Task TryConnectWsAsync()
    {
        if (_disposed) return;
        try
        {
            _ws?.Dispose();
            _ws = new ClientWebSocket();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            using var linked  = CancellationTokenSource.CreateLinkedTokenSource(timeout.Token, _cts.Token);

            await _ws.ConnectAsync(new Uri(_wsUrl), linked.Token);
            _wsConnected = true;
            _restFallback = false;

            _receiveLoop = Task.Run(() => ReceiveLoopAsync(_cts.Token));
            ScheduleReconnect(delay: TimeSpan.Zero, isRetry: false);   // cancel any pending retry
        }
        catch (Exception ex) when (!_disposed)
        {
            _wsConnected = false;
            _restFallback = true;
            System.Diagnostics.Debug.WriteLine($"[RiskEngine] WS connect failed: {ex.Message} — using REST fallback");
            ScheduleReconnect(delay: TimeSpan.FromSeconds(30), isRetry: true);
        }
    }

    private void ScheduleReconnect(TimeSpan delay, bool isRetry)
    {
        if (!isRetry) return;  // already connected — nothing to do
        _reconnectTimer = Task.Run(async () =>
        {
            await Task.Delay(delay, _cts.Token).ContinueWith(_ => { });
            if (!_disposed && !_wsConnected)
                await TryConnectWsAsync();
        });
    }

    // ── Receive loop — handles engine → plugin push ───────────────────────────

    private async Task ReceiveLoopAsync(CancellationToken ct)
    {
        var buf = new byte[16 * 1024];
        var sb  = new StringBuilder();

        try
        {
            while (_ws!.State == WebSocketState.Open && !ct.IsCancellationRequested)
            {
                WebSocketReceiveResult result;
                sb.Clear();
                do
                {
                    result = await _ws.ReceiveAsync(buf, ct);
                    if (result.MessageType == WebSocketMessageType.Close)
                        break;
                    sb.Append(Encoding.UTF8.GetString(buf, 0, result.Count));
                }
                while (!result.EndOfMessage);

                if (result.MessageType == WebSocketMessageType.Close)
                    break;

                try
                {
                    var doc = JsonDocument.Parse(sb.ToString());
                    if (doc.RootElement.TryGetProperty("type", out var t))
                    {
                        switch (t.GetString())
                        {
                            case "risk_state":
                                RiskStateReceived?.Invoke(doc.RootElement.Clone());
                                break;
                            case "request_positions":
                                // Engine is asking for a fresh position snapshot (reconciliation on connect)
                                PositionsRequested?.Invoke();
                                break;
                        }
                    }
                }
                catch { /* ignore malformed JSON */ }
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[RiskEngine] WS receive error: {ex.Message}");
        }
        finally
        {
            _wsConnected = false;
            _restFallback = true;
            if (!_disposed)
                ScheduleReconnect(TimeSpan.FromSeconds(30), isRetry: true);
        }
    }

    // ── Send helpers ──────────────────────────────────────────────────────────

    public async Task SendFillAsync(FillEvent fill)
    {
        var json = JsonSerializer.Serialize(fill);
        if (_wsConnected)
            await SendTextAsync(json);
        else
            await PostRestAsync("/api/platform/event", json);
    }

    public async Task SendPositionSnapshotAsync(PositionSnapshot snap)
    {
        var json = JsonSerializer.Serialize(snap);
        if (_wsConnected)
            await SendTextAsync(json);
        else
            await PostRestAsync("/api/platform/positions", json);
    }

    private async Task SendTextAsync(string text)
    {
        if (_ws is null || _ws.State != WebSocketState.Open) return;
        var bytes = Encoding.UTF8.GetBytes(text);
        try
        {
            await _ws.SendAsync(bytes, WebSocketMessageType.Text, true, _cts.Token);
        }
        catch
        {
            _wsConnected = false;
            _restFallback = true;
            ScheduleReconnect(TimeSpan.FromSeconds(30), isRetry: true);
        }
    }

    private async Task PostRestAsync(string path, string json)
    {
        try
        {
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            await _http.PostAsync(_restBaseUrl + path, content);
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[RiskEngine] REST post failed: {ex.Message}");
        }
    }

    public void Dispose()
    {
        _disposed = true;
        _cts.Cancel();
        _ws?.Dispose();
        _http.Dispose();
    }
}
