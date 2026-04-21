
from hedge_automation.data_handler import BrokerHandler
from hedge_automation.hedge_orders_sender import BitgetOrderSender
from hedge_automation.hl_order_sender import HyperliquidOrderSender
from config import get_config
from common.hedge_exchange import get_hedge_exchange_config

class OrderManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(OrderManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        config = get_config() or {}
        hedge_cfg = get_hedge_exchange_config(config)
        hedge_exchange = hedge_cfg["exchange"]

        if hedge_exchange == "hyperliquid":
            self.bh = None
            self.order_sender = HyperliquidOrderSender()
        else:
            params = {
                'exchange_trade': hedge_exchange,
                'account_trade': 'H1',
                'send_orders': hedge_exchange
            }
            end_point = BrokerHandler.build_end_point(hedge_exchange, account='H1')
            self.bh = BrokerHandler(
                market_watch=hedge_exchange,
                strategy_param=params,
                end_point_trade=end_point,
                logger_name=f'{hedge_exchange}_order_sender'
            )
            self.order_sender = BitgetOrderSender(self.bh)

    async def close(self):
        await self.order_sender.close()

    def get_order_sender(self):
        return self.order_sender