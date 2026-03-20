import pandas as pd
import logging
import sys
import csv
from datetime import datetime
import json
from datafeed import bitgetfeed as bg
from datafeed.broker_handler import BrokerHandler
import asyncio
from pathlib import Path
from config import get_config
from common.bot_reporting import TGMessenger
from common.data_loader import load_hedgeable_tokens, load_ticker_mappings, load_smoothed_quantities
from common.path_config import (
    LOG_DIR, METEORA_LATEST_CSV, KRYSTAL_LATEST_CSV, HEDGING_LATEST_CSV,
    REBALANCING_HISTORY_DIR, REBALANCING_LATEST_CSV, CONFIG_DIR
)
from hedge_rebalancer.quantity_smoothing import compute_ma

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'hedge_rebalancer.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

HEDGABLE_TOKENS = load_hedgeable_tokens()

last_smoothing_timestamp, last_smoothing_dict = load_smoothed_quantities()


mappings = load_ticker_mappings()
SYMBOL_MAP = mappings["SYMBOL_MAP"]
BITGET_TOKENS_WITH_FACTOR_1000 = mappings["BITGET_TOKENS_WITH_FACTOR_1000"]
BITGET_TOKENS_WITH_FACTOR_10000 = mappings["BITGET_TOKENS_WITH_FACTOR_10000"]

AUTO_HEDGE_TOKENS_PATH = CONFIG_DIR / "auto_hedge_tokens.json"

def load_auto_hedge_tokens():
    """
    Load tokens' automation status from auto_hedge_tokens.json.
    If the file doesn't exist, initialize it with all hedgeable tokens set to false.
    Returns: dict of token symbols to automation status (e.g., {"ETH": false, "BTC": false}).
    """
    try:
        if AUTO_HEDGE_TOKENS_PATH.exists():
            with AUTO_HEDGE_TOKENS_PATH.open('r') as f:
                content = f.read().strip()
                if not content:
                    raise ValueError("File is empty")
                data = json.loads(content)
                return data
        else:
            # Initialize with all hedgeable tokens set to false
            data = sync_auto_hedge_tokens()
            return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Error loading auto_hedge_tokens.json: {e}")
        # Initialize with defaults on error
        data = sync_auto_hedge_tokens()
        return data

def save_auto_hedge_tokens(tokens):
    """
    Save token automation status to auto_hedge_tokens.json.
    Args:
        tokens: dict of token symbols to automation status (e.g., {"ETH": false, "BTC": true}).
    """
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        with AUTO_HEDGE_TOKENS_PATH.open('w') as f:
            json.dump(tokens, f, indent=2)
        logger.info("Configuration saved successfully to auto_hedge_tokens.json")
    except Exception as e:
        logger.error(f"Error saving auto_hedge_tokens.json: {e}")

def sync_auto_hedge_tokens():
    """
    Sync auto_hedge_tokens.json with HEDGABLE_TOKENS, adding new tokens and removing obsolete ones.
    Returns: Updated dict of token symbols to automation status.
    """
    # Load current tokens, if any
    auto_hedge_tokens = {}
    if AUTO_HEDGE_TOKENS_PATH.exists():
        try:
            with AUTO_HEDGE_TOKENS_PATH.open('r') as f:
                content = f.read().strip()
                if content:
                    auto_hedge_tokens = json.loads(content)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Error reading auto_hedge_tokens.json during sync: {e}")

    # Get current hedgeable tokens (strip USDT from symbols)
    hedgable_tokens = sorted([ticker.replace("USDT", "") for ticker in HEDGABLE_TOKENS.keys()])
    
    # Track changes
    added_tokens = []
    removed_tokens = []
    
    # Add new tokens with False status
    for token in hedgable_tokens:
        if token not in auto_hedge_tokens:
            auto_hedge_tokens[token] = False
            added_tokens.append(token)
    
    # Remove obsolete tokens
    for token in list(auto_hedge_tokens.keys()):
        if token not in hedgable_tokens:
            del auto_hedge_tokens[token]
            removed_tokens.append(token)
    
    # Save if updated
    if added_tokens or removed_tokens:
        save_auto_hedge_tokens(auto_hedge_tokens)
        if added_tokens:
            logger.info(f"Added tokens to auto_hedge_tokens.json: {', '.join(added_tokens)}")
        if removed_tokens:
            logger.info(f"Removed tokens from auto_hedge_tokens.json: {', '.join(removed_tokens)}")
    
    return auto_hedge_tokens

def calculate_hedge_quantities():
    """Calculate total hedged quantities from Bitget positions by symbol (always negative or zero)."""
    hedge_quantities = {symbol: 0.0 for symbol in HEDGABLE_TOKENS}
    if HEDGING_LATEST_CSV.exists():
        try:
            hedge_df = pd.read_csv(HEDGING_LATEST_CSV)
            for _, row in hedge_df.iterrows():
                symbol = row["symbol"]
                qty = float(row["quantity"] or 0)  # Negative for short positions
                if symbol in HEDGABLE_TOKENS:
                    hedge_quantities[symbol] += qty
        except Exception as e:
            logger.error(f"Error reading {HEDGING_LATEST_CSV}: {e}")
    else:
        logger.warning(f"{HEDGING_LATEST_CSV} not found.")
    return hedge_quantities

def calculate_lp_quantities():
    """Calculate total LP quantities by Bitget symbol, matching addresses by chain, converting to Bitget units."""
    lp_quantities = {symbol: 0.0 for symbol in HEDGABLE_TOKENS}
    
    if METEORA_LATEST_CSV.exists():
        try:
            meteora_df = pd.read_csv(METEORA_LATEST_CSV)
            logger.debug(f"Meteora CSV rows: {len(meteora_df)}")
            for _, row in meteora_df.iterrows():
                token_x = row["Token X Address"]
                token_y = row["Token Y Address"]
                qty_x = float(row["Token X Qty"] or 0)
                qty_y = float(row["Token Y Qty"] or 0)
                chain = "solana"
                logger.debug(f"Meteora row: token_x={token_x}, qty_x={qty_x}, token_y={token_y}, qty_y={qty_y}")

                for symbol, chains in HEDGABLE_TOKENS.items():
                    if chain in chains:
                        addresses = chains[chain]
                        logger.debug(f"Checking {symbol} for chain={chain}, addresses={addresses}")
                        # Convert to Bitget units for factored tokens
                        factor = (
                            1000 if any(symbol.startswith(factor_symbol) for factor_symbol in BITGET_TOKENS_WITH_FACTOR_1000.values())
                            else 10000 if any(symbol.startswith(factor_symbol) for factor_symbol in BITGET_TOKENS_WITH_FACTOR_10000.values())
                            else 1
                        )
                        logger.debug(f"Factor for {symbol}: {factor}")
                        if token_x in addresses:
                            lp_quantities[symbol] += qty_x / factor
                            logger.debug(f"Matched {symbol} for token_x={token_x}, added {qty_x / factor}, total: {lp_quantities[symbol]}")
                        if token_y in addresses:
                            lp_quantities[symbol] += qty_y / factor
                            logger.debug(f"Matched {symbol} for token_y={token_y}, added {qty_y / factor}, total: {lp_quantities[symbol]}")
        except Exception as e:
            logger.error(f"Error reading {METEORA_LATEST_CSV}: {e}")
    else:
        logger.warning(f"{METEORA_LATEST_CSV} not found.")

    if KRYSTAL_LATEST_CSV.exists():
        try:
            krystal_df = pd.read_csv(KRYSTAL_LATEST_CSV)
            logger.debug(f"Krystal CSV rows: {len(krystal_df)}")
            for _, row in krystal_df.iterrows():
                token_x = row["Token X Address"]
                token_y = row["Token Y Address"]
                qty_x = float(row["Token X Qty"] or 0)
                qty_y = float(row["Token Y Qty"] or 0)
                chain = row["Chain"].lower()
                logger.debug(f"Krystal row: chain={chain}, token_x={token_x}, qty_x={qty_x}, token_y={token_y}, qty_y={qty_y}")

                for symbol, chains in HEDGABLE_TOKENS.items():
                    if chain in chains:
                        addresses = chains[chain]
                        logger.debug(f"Checking {symbol} for chain={chain}, addresses={addresses}")
                        factor = (
                            1000 if any(symbol.startswith(factor_symbol) for factor_symbol in BITGET_TOKENS_WITH_FACTOR_1000.values())
                            else 10000 if any(symbol.startswith(factor_symbol) for factor_symbol in BITGET_TOKENS_WITH_FACTOR_10000.values())
                            else 1
                        )
                        logger.debug(f"Factor for {symbol}: {factor}")
                        if token_x in addresses:
                            lp_quantities[symbol] += qty_x / factor
                            logger.debug(f"Matched {symbol} for token_x={token_x}, added {qty_x / factor}, total: {lp_quantities[symbol]}")
                        if token_y in addresses:
                            lp_quantities[symbol] += qty_y / factor
                            logger.debug(f"Matched {symbol} for token_y={token_y}, added {qty_y / factor}, total: {lp_quantities[symbol]}")
        except Exception as e:
            logger.error(f"Error reading {KRYSTAL_LATEST_CSV}: {e}")
    else:
        logger.warning(f"{KRYSTAL_LATEST_CSV} not found.")
    
    logger.debug(f"Final LP quantities: {lp_quantities}")
    return lp_quantities

# Set event loop policy for Windows compatibility
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def get_token_prices_usd(symbols):
    """Fetch token prices in USD for all symbols in a single Bitget API call."""
    params = {'exchange_trade': 'dummy', 'account_trade': 'dummy'}
    end_point = BrokerHandler.build_end_point('bitget', 'dummy')
    bh = BrokerHandler(market_watch='bitget', end_point_trade=end_point, strategy_param=params, logger_name='default')
    prices = {symbol: 1.0 for symbol in symbols}
    try:
        if not symbols:
            logger.warning("No symbols provided for price fetch")
            return {symbol: 1.0 for symbol in HEDGABLE_TOKENS}
        
        logger.debug(f"Fetching prices for symbols: {symbols}")
        # Use symbol map to handle potential format differences (e.g., GMXUSDT -> GMX/USDT)
        symbol_map = {symbol: SYMBOL_MAP.get(symbol, symbol) for symbol in symbols}
        async def fetch_ticker(symbol):
            try:
                ticker = await end_point._exchange_async.fetch_ticker(symbol)
                return symbol, float(ticker.get('last', 1.0))
            except Exception as e:
                logger.warning(f"Error fetching price for {symbol} on bitget: {str(e)}")
                return symbol, 1.0
        
        tasks = [fetch_ticker(symbol) for symbol in set(symbol_map.values())]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        symbol_prices = {symbol: price for symbol, price in results if not isinstance(price, Exception)}
        for symbol in symbols:
            mapped_symbol = symbol_map[symbol]
            price = symbol_prices.get(mapped_symbol, 1.0)
            prices[symbol] = price
            logger.debug(f"Fetched price for {symbol} (mapped: {mapped_symbol}): ${price:.2f}")
    except Exception as e:
        logger.error(f"Error fetching prices for symbols on bitget: {str(e)}")
        prices = {symbol: 1.0 for symbol in symbols}
        logger.warning(f"Set default price of $1.0 for all symbols due to fetch error")
    finally:
        await end_point._exchange_async.close()
        await bh.close_exchange_async()
    return prices

def check_hedge_rebalance():
    """Compare LP quantities with absolute hedge quantities using net/gross ratio and output results."""
    # Load triggers from centralized config
    config = get_config()
    config_hr = config.get('hedge_rebalancer', {})
    triggers = config_hr.get('triggers', {})
    positive_trigger = triggers.get('positive', 0.2)
    negative_trigger = triggers.get('negative', -0.2)
    min_usd_trigger = triggers.get('min_usd_trigger', 200.0)
    smoother = config_hr.get('smoother', {})
    use_smoothed_qty = smoother.get('use_smoothed_qty', False)
    qty_smoothing_lookback = smoother.get('smoothing_lookback_h', 24)  # hours

    logger.info(f"Starting hedge-rebalancer with positive_trigger={positive_trigger}, "
                f"negative_trigger={negative_trigger}, min_usd_trigger={min_usd_trigger}, "
                f"use_smoothed_qty={use_smoothed_qty}, qty_smoothing_lookback={qty_smoothing_lookback}...")
    
    # Sync auto_hedge_tokens.json with HEDGABLE_TOKENS before calculations
    sync_auto_hedge_tokens()
    
    hedge_quantities = calculate_hedge_quantities()
    lp_quantities = calculate_lp_quantities()
    lp_quantities_ma = compute_ma(lp_quantities, qty_smoothing_lookback)
    auto_hedge_tokens = load_auto_hedge_tokens()

    # Fetch prices for all relevant tokens at once
    relevant_symbols = [symbol for symbol in HEDGABLE_TOKENS if lp_quantities.get(symbol, 0) != 0 or hedge_quantities.get(symbol, 0) != 0]
    prices = asyncio.run(get_token_prices_usd(relevant_symbols))

    rebalance_results = []
    timestamp_for_csv = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')
    timestamp_for_filename = datetime.utcnow().strftime('%Y%m%d_%H%M%S')

    for symbol in HEDGABLE_TOKENS:
        logger.debug(f"Processing token: {symbol}")
        hedge_qty = hedge_quantities[symbol]
        lp_qty_raw = lp_quantities[symbol]
        lp_qty_smoothed = lp_quantities_ma.get(symbol, lp_qty_raw)  # Use raw if smoothed is missing
        lp_qty = lp_qty_smoothed if use_smoothed_qty else lp_qty_raw
        abs_hedge_qty = abs(hedge_qty)

        if lp_qty == 0 and hedge_qty == 0:
            logger.debug(f"Skipping {symbol}: LP and hedge quantities are zero")
            continue

        if lp_qty < 0:
            logger.warning(f"Unexpected negative LP quantity for {symbol}: {lp_qty}")
            continue

        if hedge_qty > 0:
            logger.warning(f"Unexpected positive hedge quantity for {symbol}: {hedge_qty}")
            message = (
                        f"*LONG HEDGE WARNING* \n"
                        f"Token: {symbol} \n"
                        f"Positive Hedge Qty: {hedge_qty} \n"
                        f"Long position in the hedging positions"
                    )
            TGMessenger.send(message,'LP eagle')
            # continue

        difference = lp_qty + hedge_qty
        raw_abs_difference = abs(lp_qty_raw + hedge_qty)
        abs_difference = abs(difference)
        gross = lp_qty + abs(hedge_qty)
        percentage_diff = (abs_difference / gross) * 100 if gross > 0 else 0
        # Calculate net/gross ratio: (lp + hedge) / (lp - hedge)
        net_gross_ratio = (
            (lp_qty_raw + hedge_qty) / (lp_qty_raw - hedge_qty)
            if (lp_qty_raw - hedge_qty) != 0 else float('inf')
        )

        net_gross_ratio_ma = (
            (lp_qty_smoothed + hedge_qty) / (lp_qty_smoothed - hedge_qty)
            if (lp_qty_smoothed - hedge_qty) != 0 else float('inf')
        )

        logger.info(f"  Token: {symbol}")
        logger.info(f"  LP Qty Raw: {lp_qty_raw:.4f}, Smoothed: {lp_qty_smoothed:.4f})")
        logger.info(f"  Last Smoothed Qty: {last_smoothing_dict[symbol]:.4f}, last Smoothing Timestamp: {last_smoothing_timestamp}")
        logger.info(f"  Hedged Qty: {hedge_qty:.4f}")
        logger.info(f"  Difference: {difference:.4f} ({percentage_diff:.2f}%)")
        logger.info(f"  Net/Gross Ratio MA: {net_gross_ratio_ma:.2f}")

        # Calculate USD difference using batched prices
        price_usd = prices.get(symbol, 1.0)
        usd_difference = abs_difference * price_usd

        # Check if token is auto-hedged
        is_auto = auto_hedge_tokens.get(symbol.replace("USDT", ""), False)
        
        # Initialize defaults
        rebalance_action = "nothing"
        rebalance_value = 0.0
        trigger_auto_order = False

        if is_auto:
            # Auto-hedge: Apply full rebalancing logic with USD trigger
            skip_rebalance = usd_difference < min_usd_trigger

            if skip_rebalance:
                logger.info(f"  Skipping rebalance for {symbol}: USD difference ${usd_difference:.2f} < ${min_usd_trigger}")
            elif lp_qty > 0 and difference != 0:
                if difference > 0:
                    rebalance_action = "sell"
                    rebalance_value = abs_difference
                    logger.warning(f"  *** REBALANCE SIGNAL: {rebalance_action} {rebalance_value:.5f} for {symbol} ***")
                else:
                    rebalance_action = "buy"
                    rebalance_value = abs_difference
                    logger.warning(f"  *** REBALANCE SIGNAL: {rebalance_action} {rebalance_value:.5f} for {symbol} ***")
            elif lp_qty == 0 and hedge_qty != 0:
                rebalance_action = "buy"
                rebalance_value = abs_hedge_qty
                logger.warning(f"  *** REBALANCE SIGNAL: {rebalance_action} {rebalance_value:.5f} for {symbol} (no LP exposure) ***")

            # Auto-hedging triggers using net/gross ratio
            if lp_qty > 0:
                if skip_rebalance:
                    logger.info(f"  Skipping auto-hedge for {symbol}: USD difference ${usd_difference:.2f} < ${min_usd_trigger}")
                elif hedge_qty == 0:
                    trigger_auto_order = True
                    logger.warning(f"  *** AUTO HEDGE TRIGGER: sell {lp_qty:.5f} for {symbol} (no hedge position) ***")
                    # Send Telegram alert
                    message = (
                        f"*AUTO HEDGE TRIGGER* \n"
                        f"Token: {symbol} \n"
                        f"Hedge Qty: {hedge_qty}, LP Qty Raw: {lp_qty_raw:.4f}, Smoothed: {lp_qty_smoothed:.4f}) \n"
                        f"Last Smoothed Qty: {last_smoothing_dict[symbol]:.4f}, last Smoothing Timestamp: {last_smoothing_timestamp} \n"
                        f"positive_trigger={positive_trigger}, negative_trigger={negative_trigger}, min_usd_trigger={min_usd_trigger},smoothing_lookback_hrs={qty_smoothing_lookback}"
                        f"Action: Sell {lp_qty:.5f} \n"
                        f"Net/Gross Ratio MA: {net_gross_ratio_ma:.2f} \n"
                        f"Timestamp: {timestamp_for_csv}"
                    )
                    TGMessenger.send(message,'LP eagle')
                elif hedge_qty < 0:
                    if net_gross_ratio > positive_trigger:
                        trigger_auto_order = True
                        logger.warning(f"  *** AUTO HEDGE TRIGGER: sell {rebalance_value:.5f} for {symbol} (net/gross ratio: {net_gross_ratio:.2f}) ***")
                        message = (
                        f"*AUTO HEDGE TRIGGER* \n"
                        f"Token: {symbol} \n"
                        f"Hedge Qty: {hedge_qty}, LP Qty Raw: {lp_qty_raw:.4f}, Smoothed: {lp_qty_smoothed:.4f}) \n"
                        f"Last Smoothed Qty: {last_smoothing_dict[symbol]:.4f}, last Smoothing Timestamp: {last_smoothing_timestamp} \n"
                        f"positive_trigger={positive_trigger}, negative_trigger={negative_trigger}, min_usd_trigger={min_usd_trigger},smoothing_lookback_hrs={qty_smoothing_lookback}"
                        f"Action: Sell {rebalance_value:.5f} \n"
                        f"Net/Gross Ratio MA: {net_gross_ratio_ma:.2f} \n"
                        f"Timestamp: {timestamp_for_csv}"
                        )
                        TGMessenger.send(message,'LP eagle')
                    elif net_gross_ratio < negative_trigger:
                        trigger_auto_order = True
                        logger.warning(f"  *** AUTO HEDGE TRIGGER: buy {rebalance_value:.5f} for {symbol} (net/gross ratio: {net_gross_ratio:.2f}) ***")
                        message = (
                            f"*AUTO HEDGE TRIGGER* \n"
                            f"Token: {symbol} \n"
                            f"Hedge Qty: {hedge_qty}, LP Qty Raw: {lp_qty_raw:.4f}, Smoothed: {lp_qty_smoothed:.4f}) \n"
                            f"Last Smoothed Qty: {last_smoothing_dict[symbol]:.4f}, last Smoothing Timestamp: {last_smoothing_timestamp} \n"
                            f"positive_trigger={positive_trigger}, negative_trigger={negative_trigger}, min_usd_trigger={min_usd_trigger},smoothing_lookback_hrs={qty_smoothing_lookback}"
                            f"Action: Buy {rebalance_value:.5f} \n"
                            f"Net/Gross Ratio: {net_gross_ratio:.2f} \n"
                            f"Timestamp: {timestamp_for_csv}"
                        )
                        TGMessenger.send(message,'LP eagle')
        else:
            # Non-auto-hedge: Suggest action based on difference
            if difference != 0:
                if difference > 0:
                    rebalance_action = "sell"
                    rebalance_value = abs_difference
                    logger.info(f"  Non-auto-hedge token {symbol}: Suggest {rebalance_action} {rebalance_value:.5f} for manual rebalancing")
                else:
                    rebalance_action = "buy"
                    rebalance_value = abs_difference
                    logger.info(f"  Non-auto-hedge token {symbol}: Suggest {rebalance_action} {rebalance_value:.5f} for manual rebalancing")
                    logger.info(f"  Non-auto-hedge token {symbol}: Suggest {rebalance_action} {rebalance_value:.5f} for manual rebalancing")
            else:
                logger.info(f"  Non-auto-hedge token {symbol}: No rebalancing needed (difference = 0)")

        rebalance_results.append({
            "Timestamp": timestamp_for_csv,
            "Token": symbol,
            "LP Qty": lp_qty_raw,
            "LP Qty MA": lp_qty_smoothed,
            "Hedged Qty": hedge_qty,
            "Difference": difference,
            "Percentage Diff": round(percentage_diff, 2),
            "Net/Gross Ratio": round(net_gross_ratio, 2),
            "Net/Gross Ratio MA": round(net_gross_ratio_ma, 2),
            "Rebalance Action": rebalance_action,
            "Rebalance Value": round(rebalance_value, 5),
            "Auto Hedge": is_auto,
            "Trigger Auto Order": trigger_auto_order
        })

    if rebalance_results:
        output_dir = REBALANCING_HISTORY_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        
        history_filename = output_dir / f"rebalancing_results_{timestamp_for_filename}.csv"
        latest_filename = REBALANCING_LATEST_CSV
        
        headers = [
            "Timestamp", "Token", "LP Qty", "LP Qty MA", "Hedged Qty", "Difference",
            "Percentage Diff", "USD Difference", "Net/Gross Ratio","Net/Gross Ratio MA",
            "Rebalance Action", "Rebalance Value", "Auto Hedge", "Trigger Auto Order"
        ]
        
        with open(history_filename, mode='w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rebalance_results)
        logger.info(f"Rebalancing results written to history: {history_filename}")
        
        with open(latest_filename, mode='w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rebalance_results)
        logger.info(f"Latest rebalancing results written to: {latest_filename}")

    logger.info("Hedge rebalance check completed.")
    return rebalance_results

if __name__ == "__main__":
    check_hedge_rebalance()