import os
from datetime import datetime, timezone
from typing import Any

import ccxt.async_support as ccxt_async


DEFAULT_HEDGE_EXCHANGE = "bitget"
DEFAULT_HEDGE_ACCOUNT = "H1"


def get_hedge_exchange_config(config: dict | None = None) -> dict:
    """
    Return normalized hedge exchange config with safe defaults.

    Supported keys:
    - hedge.exchange
    - hedge.account

    Backward-compatible aliases:
    - hedge_monitoring.exchange
    - hedge_monitoring.account
    """
    cfg = config or {}
    hedge_cfg = cfg.get("hedge", {}) if isinstance(cfg, dict) else {}
    monitoring_cfg = cfg.get("hedge_monitoring", {}) if isinstance(cfg, dict) else {}

    exchange = (
        hedge_cfg.get("exchange")
        or monitoring_cfg.get("exchange")
        or DEFAULT_HEDGE_EXCHANGE
    )
    account = (
        hedge_cfg.get("account")
        or monitoring_cfg.get("account")
        or DEFAULT_HEDGE_ACCOUNT
    )

    return {
        "exchange": str(exchange).lower(),
        "account": str(account),
    }


def _get_exchange_credentials(exchange_id: str) -> dict[str, str]:
    """
    Load credentials from env vars.

    Priority:
    1) Generic hedge credentials: HEDGE_API_KEY/HEDGE_API_SECRET/HEDGE_API_PASSWORD
    2) Exchange-specific legacy credentials (Bitget-compatible names)
    """
    exchange_upper = exchange_id.upper()

    api_key = (
        os.getenv("HEDGE_API_KEY")
        or os.getenv(f"{exchange_upper}_API_KEY")
        or os.getenv("BITGET_HEDGE1_API_KEY")
    )
    api_secret = (
        os.getenv("HEDGE_API_SECRET")
        or os.getenv(f"{exchange_upper}_API_SECRET")
        or os.getenv("BITGET_HEDGE1_API_SECRET")
    )
    api_password = (
        os.getenv("HEDGE_API_PASSWORD")
        or os.getenv(f"{exchange_upper}_API_PASSWORD")
        or os.getenv("BITGET_API_PASSWORD")
    )

    return {
        "apiKey": api_key or "",
        "secret": api_secret or "",
        "password": api_password or "",
    }


def _normalize_symbol_to_usdt(symbol: str) -> str:
    """
    Convert unified or raw symbol strings to BASEUSDT format.
    Treats USDC and USDT as equivalent (1:1).

    Examples:
    - BTC/USDT:USDT -> BTCUSDT
    - BTC/USDC:USDC -> BTCUSDT  (Hyperliquid)
    - BTCUSDT -> BTCUSDT
    - BTCUSDC -> BTCUSDT
    """
    s = (symbol or "").upper()
    if not s:
        return ""

    if "/" in s:
        base, quote_part = s.split("/", 1)
        quote = quote_part.split(":", 1)[0]
        if quote in ("USDT", "USDC"):
            return f"{base}USDT"
        return ""

    if s.endswith("USDT"):
        return s
    if s.endswith("USDC"):
        return s[:-4] + "USDT"

    return ""


def _unified_symbol(raw_symbol: str, exchange_id: str = "") -> str:
    """Convert BASEUSDT into unified perpetual notation for the given exchange.
    Hyperliquid uses BASE/USDC:USDC; all others use BASE/USDT:USDT.
    """
    symbol = (raw_symbol or "").upper()
    if symbol.endswith("USDT") or symbol.endswith("USDC"):
        base = symbol[:-4]
    else:
        return symbol
    if exchange_id.lower() == "hyperliquid":
        return f"{base}/USDC:USDC"
    return f"{base}/USDT:USDT"


def _position_timestamp_ms(position: dict[str, Any]) -> int:
    for key in ("timestamp", "entryTime", "openTime"):
        value = position.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


class CcxtHedgeMarket:
    """Small async ccxt wrapper for hedge exchange operations."""

    def __init__(self, exchange_id: str, use_auth: bool = False):
        self.exchange_id = (exchange_id or DEFAULT_HEDGE_EXCHANGE).lower()
        if not hasattr(ccxt_async, self.exchange_id):
            raise ValueError(f"Unsupported hedge exchange: {self.exchange_id}")

        options: dict[str, Any] = {"enableRateLimit": True}
        if use_auth:
            creds = _get_exchange_credentials(self.exchange_id)
            if creds["apiKey"]:
                options["apiKey"] = creds["apiKey"]
            if creds["secret"]:
                options["secret"] = creds["secret"]
            if creds["password"]:
                options["password"] = creds["password"]

        exchange_class = getattr(ccxt_async, self.exchange_id)
        self._exchange = exchange_class(options)

    async def close(self):
        await self._exchange.close()

    async def fetch_usdt_perp_symbols(self) -> list[str]:
        markets = await self._exchange.load_markets()
        symbols: list[str] = []
        valid_quotes = {"USDT", "USDC"} if self.exchange_id == "hyperliquid" else {"USDT"}
        for market in markets.values():
            if market.get("quote") not in valid_quotes:
                continue
            if not market.get("swap", False):
                continue

            normalized = _normalize_symbol_to_usdt(market.get("symbol", ""))
            if normalized:
                symbols.append(normalized)

        return sorted(set(symbols))

    async def fetch_positions(self) -> dict[str, tuple[float, float, float, int]]:
        """
        Return {symbol: (qty, amount, entry_price, entry_ts_ms)} with symbol in BASEUSDT format.
        """
        positions = await self._exchange.fetch_positions()
        result: dict[str, tuple[float, float, float, int]] = {}

        for pos in positions or []:
            contracts = pos.get("contracts")
            side = (pos.get("side") or "").lower()
            if contracts in (None, 0):
                continue

            signed_contracts = float(contracts)
            if side == "short":
                signed_contracts = -abs(signed_contracts)
            elif side == "long":
                signed_contracts = abs(signed_contracts)

            raw_symbol = pos.get("symbol") or (pos.get("info") or {}).get("symbol") or ""
            symbol = _normalize_symbol_to_usdt(raw_symbol)
            if not symbol:
                continue

            notional = pos.get("notional")
            amount = float(notional) if notional is not None else 0.0
            entry_price = float(pos.get("entryPrice") or 0.0)
            entry_ts = _position_timestamp_ms(pos)

            result[symbol] = (signed_contracts, amount, entry_price, entry_ts)

        return result

    async def fetch_funding_rate(self, symbol: str) -> float:
        unified = _unified_symbol(symbol, self.exchange_id)
        data = await self._exchange.fetch_funding_rate(unified)
        return float(data.get("fundingRate") or 0.0)
