using System.Globalization;
using TradingPlatform.BusinessLayer;
using QuantowerRiskPlugin.Models;

namespace QuantowerRiskPlugin;

/// <summary>
/// Maps Quantower domain objects to engine event payloads.
/// All symbol normalization happens here so the bridge stays clean.
/// </summary>
internal static class RiskEngineEventMapper
{
    /// <summary>
    /// Map a Quantower Trade (a fill report) to a FillEvent for the engine.
    /// Returns null if the trade is missing a required field (account, symbol).
    /// </summary>
    public static FillEvent? MapFill(Trade trade)
    {
        if (trade.Account is null)
        {
            System.Diagnostics.Debug.WriteLine("[RiskEngine] MapFill: skipping — trade.Account is null");
            return null;
        }

        string symbol = NormalizeSymbol(trade.Symbol?.Name ?? "");
        if (string.IsNullOrEmpty(symbol))
        {
            System.Diagnostics.Debug.WriteLine("[RiskEngine] MapFill: skipping — symbol is null/empty");
            return null;
        }

        bool isBuy = trade.Side == Side.Buy;
        string impact = "";
        try { impact = trade.PositionImpactType.ToString().ToLower(); } catch { }
        bool isClose = impact.Contains("close") || impact.Contains("reverse") || impact.Contains("decrease");

        // Position direction: for closing fills, opposite of trade side
        string direction;
        if (isClose)
            direction = isBuy ? "SHORT" : "LONG";  // BUY closes SHORT, SELL closes LONG
        else
            direction = isBuy ? "LONG" : "SHORT";

        long timestampMs;
        try { timestampMs = ((DateTimeOffset)trade.DateTime).ToUnixTimeMilliseconds(); }
        catch { timestampMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); }

        return new FillEvent
        {
            ExchangeFillId  = trade.Id ?? "",
            TerminalFillId  = trade.UniqueId ?? "",
            ExchangeOrderId = trade.OrderId ?? "",
            Symbol     = symbol,
            Side       = isBuy ? "BUY" : "SELL",
            Direction  = direction,
            PositionId = trade.PositionId ?? "",
            IsClose    = isClose,
            Price      = trade.Price,
            Quantity   = Math.Abs(trade.Quantity),
            GrossPnL   = (double)trade.GrossPnl.Value,
            Fee        = Math.Abs((double)trade.Fee.Value),
            Timestamp  = timestampMs,
            AccountId  = trade.Account.Id,
        };
    }

    /// <summary>
    /// Build a position snapshot from the given positions belonging to the account.
    /// </summary>
    public static PositionSnapshot MapPositions(Account account, IEnumerable<Position> positions)
    {
        var snap = new PositionSnapshot { AccountId = account.Id };
        foreach (var p in positions)
        {
            // Signed quantity: positive for LONG, negative for SHORT
            double signedQty = p.Side == Side.Buy
                ? p.Quantity
                : -p.Quantity;

            double unreal = 0.0;
            try { if (p.GrossPnL != null) unreal = (double)p.GrossPnL.Value; } catch { }

            long openTimeMs = 0;
            try { openTimeMs = ((DateTimeOffset)p.OpenTime).ToUnixTimeMilliseconds(); } catch { }

            double liqPrice = 0.0;
            try { liqPrice = p.LiquidationPrice; } catch { }

            snap.Positions.Add(new PositionItem
            {
                PositionId       = p.Id ?? "",
                Symbol           = NormalizeSymbol(p.Symbol?.Name ?? ""),
                Quantity         = signedQty,
                AvgPrice         = p.OpenPrice,
                UnrealizedPnL    = unreal,
                OpenTimeMs       = openTimeMs,
                LiquidationPrice = liqPrice,
                // TP/SL not sent here — engine fetches directly from exchange
                // via fetch_open_orders_tpsl() for reliable, real-time values.
            });
        }
        return snap;
    }

    /// <summary>
    /// Build a hello payload for first-connect introduction.
    /// account.Id in Quantower is the connection alias ("binance"), not the
    /// broker UID. The real UID lives in account.AdditionalInfo under a
    /// broker-specific key. We probe a list of likely keys and fall back to
    /// account.Id only if none match.
    /// </summary>
    public static HelloEvent MapHello(Account account)
    {
        string broker = "unknown";
        try
        {
            var conn = account.Connection;
            broker = (conn?.VendorName ?? conn?.Name ?? "unknown").Trim();
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[RiskEngine] MapHello: connection lookup failed: {ex.Message}");
        }

        string brokerAccountId = ResolveBrokerAccountId(account);
        var addInfo = DumpAdditionalInfo(account);

        return new HelloEvent
        {
            Type            = "hello",
            Terminal        = "quantower",
            Broker          = broker,
            BrokerAccountId = brokerAccountId,
            AccountName     = account.Name ?? "",
            AccountCurrency = account.AccountCurrency?.Name ?? "",
            AdditionalInfo  = addInfo,
        };
    }

    private static Dictionary<string, string> DumpAdditionalInfo(Account account)
    {
        var dump = new Dictionary<string, string>();

        // Raw account identity fields (not in AdditionalInfo collection but useful)
        try { dump["__Account.Id"] = account.Id ?? ""; } catch { }
        try { dump["__Account.Name"] = account.Name ?? ""; } catch { }
        try { dump["__ComplexId.AccountId"]    = account.ComplexId.AccountId ?? ""; } catch { }
        try { dump["__ComplexId.ConnectionId"] = account.ComplexId.ConnectionId ?? ""; } catch { }
        try { dump["__Connection.Name"]       = account.Connection?.Name ?? ""; } catch { }
        try { dump["__Connection.VendorName"] = account.Connection?.VendorName ?? ""; } catch { }

        try
        {
            var info = account.AdditionalInfo;
            if (info == null) return dump;
            foreach (var item in info)
            {
                var name = item?.Id;
                if (string.IsNullOrEmpty(name)) continue;
                var val = item?.Value?.ToString() ?? "";
                dump[name] = val;
            }
        }
        catch { }
        return dump;
    }

    /// <summary>
    /// Resolve the broker-side account identifier. Quantower exposes two
    /// candidates and they are NOT the same:
    ///   - Account.Id              -> connection alias (e.g. "binance")
    ///   - Account.ComplexId.AccountId -> the broker-issued account UID
    ///
    /// We prefer ComplexId.AccountId when it differs from Id (i.e. when it
    /// actually carries broker information), otherwise fall back to Id.
    /// </summary>
    private static string ResolveBrokerAccountId(Account account)
    {
        string id = account.Id ?? "";
        string complexId = "";

        try
        {
            var cx = account.ComplexId;
            complexId = cx.AccountId ?? "";
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[RiskEngine] ComplexId.AccountId read failed: {ex.Message}");
        }

        // Prefer ComplexId.AccountId when it carries something distinct.
        if (!string.IsNullOrEmpty(complexId) && complexId != id)
            return complexId;

        return id;
    }

    /// <summary>
    /// Build an order snapshot from the given orders belonging to the account.
    /// positionSideLookup maps PositionId → "LONG"/"SHORT" from live positions.
    /// </summary>
    public static OrderSnapshot MapOrders(
        Account account,
        IEnumerable<Order> orders,
        Dictionary<string, string>? positionSideLookup = null)
    {
        var snap = new OrderSnapshot { AccountId = account.Id ?? "" };
        foreach (var o in orders)
        {
            string symbol = NormalizeSymbol(o.Symbol?.Name ?? "");
            if (string.IsNullOrEmpty(symbol)) continue;

            string side = o.Side == Side.Buy ? "BUY" : "SELL";

            // Map Quantower OrderType to engine name for status mapping
            string status;
            try { status = o.Status.ToString(); }
            catch { status = "Opened"; }

            string orderType;
            try { orderType = o.OrderType.ToString(); }
            catch { orderType = "Market"; }

            string timeInForce;
            try { timeInForce = o.TimeInForce.ToString(); }
            catch { timeInForce = ""; }

            // Quantower Order SDK only exposes LastUpdateTime, not creation time.
            // True creation time comes from exchange REST adapter (created_at_ms).
            long createdAt = 0;
            try { createdAt = ((DateTimeOffset)o.LastUpdateTime).ToUnixTimeMilliseconds(); }
            catch { }

            double triggerPrice = 0.0;
            try { triggerPrice = o.TriggerPrice; } catch { }

            double avgFill = 0.0;
            try { avgFill = o.AverageFillPrice; } catch { }

            double filledQty = 0.0;
            try { filledQty = Math.Abs(o.FilledQuantity); } catch { }

            // Quantower SDK doesn't expose ReduceOnly on Order;
            // infer from order type — TP/SL orders are inherently reduce-only
            bool reduceOnly = orderType.Contains("TakeProfit") || orderType.Contains("Stop");

            // Determine position side:
            // 1. Best: look up from live position via PositionId
            // 2. Fallback: infer from side + reduceOnly
            string positionSide = "";
            string posId = o.PositionId ?? "";
            if (positionSideLookup != null && !string.IsNullOrEmpty(posId)
                && positionSideLookup.TryGetValue(posId, out var resolvedSide))
            {
                positionSide = resolvedSide;
            }
            else if (reduceOnly)
                positionSide = side == "BUY" ? "SHORT" : "LONG";
            else
                positionSide = side == "BUY" ? "LONG" : "SHORT";

            snap.Orders.Add(new OrderItem
            {
                ExchangeOrderId = o.Id ?? "",
                TerminalOrderId = o.UniqueId ?? "",
                ClientOrderId   = o.Comment ?? "",
                Symbol          = symbol,
                Side            = side,
                OrderType       = orderType,
                Status          = status,
                Price           = o.Price,
                StopPrice       = triggerPrice,
                Quantity        = Math.Abs(o.TotalQuantity),
                FilledQuantity  = filledQty,
                AvgFillPrice    = avgFill,
                ReduceOnly      = reduceOnly,
                TimeInForce     = timeInForce,
                PositionSide    = positionSide,
                PositionId      = o.PositionId ?? "",
                CreatedAt       = createdAt,
            });
        }
        return snap;
    }

    /// <summary>
    /// Map a Quantower historical Trade (from Core.GetTrades) to a
    /// HistoricalFillEvent for the engine's exchange_history backfill.
    /// Returns null when required fields are missing.
    /// </summary>
    public static HistoricalFillEvent? MapHistoricalFill(Trade trade)
    {
        if (trade.Account is null) return null;
        string symbol = NormalizeSymbol(trade.Symbol?.Name ?? "");
        if (string.IsNullOrEmpty(symbol)) return null;

        long ts;
        try { ts = ((DateTimeOffset)trade.DateTime).ToUnixTimeMilliseconds(); }
        catch { ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); }

        double grossPnl = 0.0; try { grossPnl = (double)trade.GrossPnl.Value; } catch { }
        double netPnl   = 0.0; try { netPnl   = (double)trade.NetPnl.Value;   } catch { }
        double fee      = 0.0; try { fee      = Math.Abs((double)trade.Fee.Value); } catch { }

        return new HistoricalFillEvent
        {
            Type               = "historical_fill",
            TradeId            = trade.Id ?? "",
            AccountId          = trade.Account.Id ?? "",
            Symbol             = symbol,
            Side               = trade.Side == Side.Buy ? "BUY" : "SELL",
            Price              = trade.Price,
            Quantity           = Math.Abs(trade.Quantity),
            GrossPnL           = grossPnl,
            NetPnL             = netPnl,
            Fee                = fee,
            Timestamp          = ts,
            OrderId            = trade.OrderId ?? "",
            PositionId         = trade.PositionId ?? "",
            PositionImpactType = trade.PositionImpactType.ToString() ?? "",
        };
    }

    /// <summary>
    /// Build an account state snapshot from a Quantower Account using its
    /// broker-specific AdditionalInfo bag. The keys here match Binance Futures'
    /// integration; if a key is missing (e.g. on a different broker), the
    /// field falls back to the closest top-level Account property.
    /// </summary>
    public static AccountStateEvent MapAccountState(Account account)
    {
        string ccy = (account.AccountCurrency?.Name ?? "USDT").Trim();

        double balance        = TryGetNumber(account, $"{ccy}walletBalance");
        double totalEquity    = TryGetNumber(account, "totalMarginBalance");
        double unrealized     = TryGetNumber(account, "totalUnrealizedProfit");
        double availMargin    = TryGetNumber(account, "totalAvailableBalance");
        double maintMargin    = TryGetNumber(account, "totalMaintenanceMargin");
        double marginRatio    = TryGetPercent(account, "marginRatio");

        // Fallbacks if broker uses different keys
        if (balance == 0.0) {
            try { balance = (double)account.Balance; } catch { }
        }
        if (totalEquity == 0.0) totalEquity = balance + unrealized;

        return new AccountStateEvent {
            Type              = "account_state",
            AccountId         = account.Id ?? "",
            Balance           = balance,
            TotalEquity       = totalEquity,
            UnrealizedPnL     = unrealized,
            AvailableMargin   = availMargin,
            MaintenanceMargin = maintMargin,
            MarginRatio       = marginRatio,
            Currency          = ccy,
            Timestamp         = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
        };
    }

    private static double TryGetNumber(Account account, string key)
    {
        try
        {
            var info = account.AdditionalInfo;
            if (info != null && info.TryGetItem(key, out var item) && item?.Value != null)
            {
                var s = item.Value.ToString();
                if (!string.IsNullOrWhiteSpace(s) && s != "NaN" &&
                    double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var d))
                    return d;
            }
        }
        catch { }
        return 0.0;
    }

    private static double TryGetPercent(Account account, string key)
    {
        try
        {
            var info = account.AdditionalInfo;
            if (info != null && info.TryGetItem(key, out var item) && item?.Value != null)
            {
                var s = item.Value.ToString()?.TrimEnd('%').Trim() ?? "";
                if (!string.IsNullOrEmpty(s) && s != "NaN" &&
                    double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var d))
                    return d / 100.0;   // "0.28%" -> 0.0028
            }
        }
        catch { }
        return 0.0;
    }

    /// <summary>
    /// Normalize Quantower symbol names to engine format.
    /// "BTC/USDT" → "BTCUSDT", "BTC USDT" → "BTCUSDT"
    /// </summary>
    public static string NormalizeSymbol(string qtSymbol)
        => qtSymbol.Replace("/", "").Replace(" ", "").Replace("-", "").ToUpperInvariant();
}
