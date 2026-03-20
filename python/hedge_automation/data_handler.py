import logging
import ccxt
import ccxt.async_support as ccxt_async


def extract_coin_with_factor(symbol: str) -> tuple[str, float]:
    normalized = (symbol or "").upper()
    normalized = normalized.replace("/USDT:USDT", "")
    normalized = normalized.replace("/USDC:USDC", "")
    normalized = normalized.replace("USDT", "")
    normalized = normalized.replace("USDC", "")
    normalized = normalized.replace("-", "")
    normalized = normalized.replace("_", "")
    factor = 1.0
    if normalized.startswith("10000"):
        return normalized[5:], 10000.0
    if normalized.startswith("1000"):
        return normalized[4:], 1000.0
    return normalized, factor


def build_symbol(coin: str, market: str, universal: bool = False) -> tuple[str, float]:
    coin_up = (coin or "").upper()
    market_name = (market or "").lower()
    if universal and market_name in {"bitget", "hyperliquid"}:
        return f"{coin_up}/USDT:USDT", 1.0
    return f"{coin_up}USDT", 1.0


class CcxtMarketEndpoint:
    """Minimal endpoint wrapper compatible with BrokerHandler expectations."""

    def __init__(self, exchange_id: str):
        exchange_class_sync = getattr(ccxt, exchange_id)
        exchange_class_async = getattr(ccxt_async, exchange_id)
        options = {"enableRateLimit": True}
        self._exchange = exchange_class_sync(options)
        self._exchange_async = exchange_class_async(options)


class DummyMarketEndpoint:
    def __init__(self):
        options = {"enableRateLimit": True}
        self._exchange = ccxt.bitget(options)
        self._exchange_async = ccxt_async.bitget(options)

class BrokerHandler:
    def __init__(self, market_watch, strategy_param, end_point_trade, logger_name):
        """
        :param market_watch: name of exchange for data format names of coins
        :type market_watch: str
        :param strategy_param: dict with configuration including 'send_orders' and 'exchange_trade'
        :type strategy_param: dict
        :param end_point_trade: market endpoint for orders
        :type end_point_trade: MotherFeeder
        :param logger_name: name for logger
        :type logger_name: str
        """
        self.market_watch = market_watch
        self._destination = strategy_param.get('send_orders', 'dummy')
        self._end_point_trade = end_point_trade
        self.market_trade = strategy_param['exchange_trade']
        self._logger = logging.getLogger(logger_name)

    @staticmethod
    def build_end_point(market, account=0):
        """
        Build the appropriate market endpoint based on the market name.
        """
        if market in {'bitget', 'hyperliquid'}:
            end_point = CcxtMarketEndpoint(market)
        else:
            end_point = DummyMarketEndpoint()
        return end_point

    def symbol_to_market_with_factor(self, symbol, universal=False):
        """
        Transform a symbol name in data exchange format into trade format and returns the price factor
        :param symbol: symbol of coin
        :type symbol: str
        :param universal: true if universal ccxt name, false if exchange specific name
        :type universal: bool
        :return: tuple of (symbol, factor)
        :rtype: (str, float)
        """
        coin, factor1 = extract_coin_with_factor(symbol)
        symbol, factor2 = build_symbol(coin, self.market_trade, universal=universal)
        return symbol, factor1 * factor2

    def get_contract_qty_from_coin(self, coin, quantity):
        """
        Convert coin quantity to contract quantity based on exchange info
        :param coin: symbol of coin
        :type coin: str
        :param quantity: amount in coin units
        :type quantity: float
        :return: quantity in contracts
        :rtype: float
        """
        info = self._end_point_trade._exchange.market(coin)
        factor = 1
        if 'contractSize' in info and info['contractSize'] is not None:
            factor = info['contractSize']
        return quantity / factor

    async def close_exchange_async(self):
        """
        Close the exchange connection
        """
        self._logger.info('Closing exchange connection')
        await self._end_point_trade._exchange_async.close()