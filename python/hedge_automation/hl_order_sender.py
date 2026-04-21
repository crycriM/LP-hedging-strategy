import asyncio
import logging
import os

import aiohttp
import numpy as np
from dotenv import load_dotenv

load_dotenv()

OPMS_BASE_URL = os.getenv("OPMS_BASE_URL", "http://localhost:8000")
OPMS_ACCOUNT_ID = os.getenv("OPMS_ACCOUNT_ID", "hedge1")

# OPMS strategy status → internal status codes
_STATUS_MAP = {
    "pending": "EXECUTING",
    "running": "EXECUTING",
    "completed": "SUCCESS",
    "failed": "EXECUTION_ERROR",
    "cancelled": "EXECUTION_ERROR",
}

FILL_THRESHOLD = 90.0  # mark SUCCESS when fill % reaches this


class HyperliquidOrderSender:
    """Send hedge orders to Hyperliquid via the local OPMS service."""

    def __init__(self):
        self.base_url = OPMS_BASE_URL.rstrip("/")
        self.account_id = OPMS_ACCOUNT_ID
        self.logger = logging.getLogger(
            f"hl_order_sender-account:{self.account_id}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coin(ticker: str) -> str:
        """Extract base coin from ticker: BTCUSDT → BTC, BTCUSDC → BTC."""
        return ticker.upper().replace("USDT", "").replace("USDC", "")

    async def _get(self, session: aiohttp.ClientSession, path: str) -> dict:
        url = f"{self.base_url}{path}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(
        self,
        session: aiohttp.ClientSession,
        path: str,
        json_data: dict | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        async with session.post(
            url, json=json_data or {}, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _check_health(self, session: aiohttp.ClientSession) -> None:
        """Raise ConnectionError if OPMS is unreachable."""
        try:
            await self._get(session, "/health")
        except Exception as e:
            raise ConnectionError(
                f"OPMS service unreachable at {self.base_url}: {e}"
            ) from e

    async def _fetch_mid_price(
        self, session: aiohttp.ClientSession, coin: str
    ) -> float | None:
        """Fetch mid-price from OPMS L1 orderbook."""
        try:
            data = await self._get(
                session, f"/api/v1/accounts/{self.account_id}/l1/{coin}"
            )
            bid = float(data.get("bid") or 0)
            ask = float(data.get("ask") or 0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            return bid or ask or None
        except Exception as e:
            self.logger.warning(f"Could not fetch price for {coin}: {e}")
            return None

    # ------------------------------------------------------------------
    # Public interface (mirrors BitgetOrderSender)
    # ------------------------------------------------------------------

    async def send_order(
        self, ticker: str, direction: int, hedge_qty: float
    ) -> tuple[bool, dict]:
        """
        Submit a hedge order via OPMS.

        Returns (success, request_dict).
        request_dict always contains 'clientOrderId' (= OPMS strategy_id on success).
        """
        coin = self._coin(ticker)
        side = "buy" if direction > 0 else "sell"
        total_quantity = round(abs(hedge_qty), 6)

        request: dict = {
            "clientOrderId": "",
            "coin": coin,
            "side": side,
            "total_quantity": total_quantity,
        }

        try:
            async with aiohttp.ClientSession() as session:
                await self._check_health(session)

                # Child order quantity: ~$1 000 per child, same logic as Bitget
                price = await self._fetch_mid_price(session, coin)
                if price and price > 0:
                    child_qty = round(1000.0 / price, 6)
                    if child_qty > total_quantity:
                        child_qty = total_quantity
                else:
                    self.logger.warning(
                        f"No price for {coin}, using full qty as child order"
                    )
                    child_qty = total_quantity

                child_time_step = round(float(np.random.uniform(20, 40)), 1)
                child_refresh_time = round(float(np.random.uniform(5, 10)), 1)

                payload = {
                    "name": f"hedge-{coin}-{side}",
                    "exchange_type": "hyperliquid",
                    "account_id": self.account_id,
                    "symbol": coin,
                    "side": side,
                    "total_quantity": str(total_quantity),
                    "child_order_quantity": str(child_qty),
                    "child_order_time_step": child_time_step,
                    "child_order_refresh_time": child_refresh_time,
                }

                self.logger.info(f"Creating OPMS strategy: {payload}")
                strategy = await self._post(session, "/api/v1/strategies", payload)
                strategy_id = strategy["strategy_id"]

                await self._post(
                    session, f"/api/v1/strategies/{strategy_id}/start"
                )
                self.logger.info(
                    f"Started OPMS strategy {strategy_id}: "
                    f"{coin} {side} {total_quantity} (child={child_qty})"
                )

        except Exception as e:
            self.logger.error(f"Failed to send order for {ticker}: {e}")
            return False, request

        request["clientOrderId"] = strategy_id
        request["child_order_quantity"] = child_qty
        return True, request

    async def poll_status(self, strategy_id: str) -> dict:
        """
        Poll OPMS for strategy status.

        Returns dict with:
          - status: internal status string
          - fillPercentage: float 0.0-1.0 (fraction, to match handle_order_update)
          - avgPrice: float
        """
        try:
            async with aiohttp.ClientSession() as session:
                data = await self._get(
                    session, f"/api/v1/strategies/{strategy_id}/status"
                )

            opms_status = data.get("status", "")
            internal_status = _STATUS_MAP.get(opms_status, "EXECUTING")
            fill_fraction = float(data.get("progress_percent") or 0.0) / 100.0

            # Promote to SUCCESS if fill threshold reached even before completion
            if fill_fraction * 100 >= FILL_THRESHOLD and internal_status not in (
                "SUCCESS",
                "EXECUTION_ERROR",
            ):
                internal_status = "SUCCESS"

            avg_price = 0.0
            if internal_status == "SUCCESS":
                try:
                    async with aiohttp.ClientSession() as session:
                        details = await self._get(
                            session, f"/api/v1/strategies/{strategy_id}"
                        )
                    avg_price_str = details.get("average_fill_price") or "0"
                    avg_price = float(avg_price_str) if avg_price_str else 0.0
                except Exception:
                    pass

            return {
                "status": internal_status,
                "fillPercentage": fill_fraction,
                "avgPrice": avg_price,
            }

        except Exception as e:
            self.logger.warning(f"Failed to poll strategy {strategy_id}: {e}")
            return {"status": "EXECUTING", "fillPercentage": 0.0, "avgPrice": 0.0}

    async def cancel_order(self, strategy_id: str) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                await self._post(
                    session, f"/api/v1/strategies/{strategy_id}/stop"
                )
            return True
        except Exception as e:
            self.logger.warning(f"Failed to cancel strategy {strategy_id}: {e}")
            return False

    async def close(self) -> None:
        pass  # No persistent connection
