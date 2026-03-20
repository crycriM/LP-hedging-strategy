import asyncio
import json
import logging
import os
from datetime import datetime
import pandas as pd
import websockets
import traceback
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)

EXECUTION_IP = os.getenv("EXECUTION_IP")

def today_utc() -> pd.Timestamp:
    tz_info = datetime.now().astimezone().tzinfo
    now = pd.Timestamp(datetime.today()).tz_localize(tz_info).tz_convert('UTC')

    return now


class WebSpreaderListener:
    AMAZON_WS_UPI = f'ws://{EXECUTION_IP}:8080/wsapi/strat/update'

    def __init__(self):
        self.listener_task = None
        self.subscriptions = set()
        self.results = {'errors': [], 'last_modified': pd.Timestamp(year=2000, month=1, day=1, tz='UTC')}

    def message_age(self) -> float:
        """
        Age in seconds
        :return: message age
        """
        return (today_utc() - self.results['last_modified']).total_seconds()

    async def _listen(self):
        self._logger = logger
        greeting = 'Allo?'
        logger.info('Starting WebSocket listener')
        try:
            async with websockets.connect(self.AMAZON_WS_UPI, max_size=4194304, ping_interval=30) as websocket:
                await websocket.send(greeting)
                while True:
                    try:
                        message = await websocket.recv()
                        if message:
                            messages = json.loads(message)
                            events = messages.get('stratEvents', [])
                            self.results['last_modified'] = today_utc()

                            for event in events:
                                strat_id = event.get('stratId', '')
                                if strat_id in self.subscriptions:
                                    result = event.get('results', {})
                                    self.results[strat_id] = result
                                    logger.debug(f"Stored update for strat_id {strat_id}: {result}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse WebSocket message: {e}")
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("WebSocket connection closed")
                        break
                    except Exception as e:
                        logger.error(f"Error processing WebSocket message: {e}", exc_info=True)
                        continue
        except Exception as e:
            logger.error(f"WebSocket listener error: {e}", exc_info=True)
            raise

    def _start_listener(self):
        async def rerun_forever(coro, *args, **kwargs):
            while True:
                try:
                    await coro(*args, **kwargs)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    msg = traceback.format_exc()
                    self.results['errors'].append(msg)
                    logger.warning(f'Listener error: {msg}')
                    await asyncio.sleep(60)

        def done_listener(task):
            self.listener_task = None
            logger.info("Listener task completed")

        self.results['errors'].clear()
        self.listener_task = asyncio.create_task(rerun_forever(self._listen))
        self.listener_task.add_done_callback(done_listener)

    def subscribe(self, strat_id):
        logger.info(f"Subscribing to strat_id: {strat_id}")
        self.subscriptions.add(strat_id)
        if self.listener_task is None:
            self._start_listener()

    async def stop_listener(self, strat_id=None):
        logger.info(f"Stopping listener for strat_id: {strat_id if strat_id else 'all'}")
        if strat_id is not None:
            self.subscriptions.discard(strat_id)
            self.results.pop(strat_id, None)
            logger.info(f"Unsubscribed from strat_id: {strat_id}")
            if len(self.subscriptions) > 0:
                return
        self.subscriptions.clear()
        self.results = {'errors': [], 'last_modified': pd.Timestamp(year=2000, month=1, day=1, tz='UTC')}
        if self.listener_task is not None:
            logger.info('Cancelling listener task')
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                logger.info("Listener task cancelled")
            self.listener_task = None

    def get_strat_result(self, strat_id):
        if strat_id in self.results:
            return self.results.get(strat_id, {})
        else:
            logger.warning(f'Retrieving non-existing strat_id {strat_id} from listener with state {self.results["errors"]}')
            return {}