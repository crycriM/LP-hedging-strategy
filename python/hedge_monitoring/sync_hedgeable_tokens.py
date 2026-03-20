import asyncio
import json
import logging
import sys
import os
import pandas as pd
import aiohttp
from common.path_config import LOG_DIR, METEORA_LATEST_CSV, KRYSTAL_LATEST_CSV, HEDGEABLE_TOKENS_JSON, ENCOUNTERED_TOKENS_JSON
from common.bot_reporting import TGMessenger
from common.data_loader import load_hedgeable_tokens, load_encountered_tokens, load_ticker_mappings
from common.hedge_exchange import CcxtHedgeMarket, get_hedge_exchange_config
from config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'sync_hedgeable_tokens.log')),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

mappings = load_ticker_mappings()
SYMBOL_MAP=  mappings["SYMBOL_MAP"]
HEDGE_TOKENS_WITH_FACTOR_1000 =  mappings.get("HEDGE_TOKENS_WITH_FACTOR_1000", mappings.get("BITGET_TOKENS_WITH_FACTOR_1000", {}))
HEDGE_TOKENS_WITH_FACTOR_10000 =  mappings.get("HEDGE_TOKENS_WITH_FACTOR_10000", mappings.get("BITGET_TOKENS_WITH_FACTOR_10000", {}))


def ensure_data_directory():
    """Ensure lp-data directory exists."""
    data_dir = HEDGEABLE_TOKENS_JSON.parent
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Error creating data directory {data_dir}: {str(e)}")

async def fetch_hedge_markets(hedge_exchange: str) -> list:
    """Fetch hedge exchange perpetual market symbols."""
    try:
        market = CcxtHedgeMarket(hedge_exchange, use_auth=False)
        markets = await market.fetch_usdt_perp_symbols()
        if not markets:
            logger.error(f"No markets returned from {hedge_exchange}")
            await market.close()
            return []

        await market.close()
        logger.info(f"Fetched {len(markets)} {hedge_exchange} perpetual market symbols")
        return markets
    except Exception as e:
        logger.error(f"Error fetching {hedge_exchange} perpetual markets: {str(e)}")
        return []

async def fetch_lp_positions(platform: str) -> list:
    """Fetch LP positions from Meteora or Krystal CSVs."""
    logger.info(f"Fetching LP positions for {platform}...")
    try:
        csv_path = METEORA_LATEST_CSV if platform == "meteora" else KRYSTAL_LATEST_CSV
        # Ensure csv_path is a string for os.path.exists
        csv_path_str = str(csv_path)
        if not os.path.exists(csv_path_str):
            logger.warning(f"CSV file not found: {csv_path_str}")
            return []
        
        df = pd.read_csv(csv_path_str)
        positions = []
        for _, row in df.iterrows():
            chain = 'solana' if platform == 'meteora' else row.get('Chain', '').lower()
            if row.get('Token X Symbol') and row.get('Token X Address'):
                positions.append({
                    'ticker': row['Token X Symbol'],
                    'contract_address': row['Token X Address'],
                    'chain': chain
                })
            if row.get('Token Y Symbol') and row.get('Token Y Address'):
                positions.append({
                    'ticker': row['Token Y Symbol'],
                    'contract_address': row['Token Y Address'],
                    'chain': chain
                })
        logger.info(f"Fetched {len(positions)} tokens from {csv_path_str}")
        return positions
    except Exception as e:
        logger.error(f"Error fetching {platform} positions: {str(e)}")
        return []

def save_hedgeable_tokens(tokens: dict):
    """Save hedgeable tokens to JSON."""
    try:
        with HEDGEABLE_TOKENS_JSON.open('w') as f:
            json.dump(tokens, f, indent=2)
        logger.info(f"Saved hedgeable tokens to {HEDGEABLE_TOKENS_JSON}")
    except Exception as e:
        logger.error(f"Error saving hedgeable tokens: {str(e)}")

def save_encountered_tokens(tokens: dict):
    """Save encountered tokens to JSON."""
    try:
        with ENCOUNTERED_TOKENS_JSON.open('w') as f:
            json.dump(tokens, f, indent=2)
        logger.info(f"Saved encountered tokens to {ENCOUNTERED_TOKENS_JSON}")
    except Exception as e:
        logger.error(f"Error saving encountered tokens: {str(e)}")

def normalize_ticker(ticker: str) -> str:
    """
    Normalize ticker using SYMBOL_MAP and factored token dictionaries, converting to uppercase.
    
    Args:
        ticker: The ticker to normalize (e.g., "WPOL", "BONK").
    
    Returns:
        str: Normalized ticker (e.g., "POL", "1000BONK").
    """
    ticker = ticker.upper()
    # Check all mapping dictionaries in priority order
    if ticker in SYMBOL_MAP:
        return SYMBOL_MAP[ticker].upper()
    if ticker in HEDGE_TOKENS_WITH_FACTOR_1000:
        return HEDGE_TOKENS_WITH_FACTOR_1000[ticker].upper()
    if ticker in HEDGE_TOKENS_WITH_FACTOR_10000:
        return HEDGE_TOKENS_WITH_FACTOR_10000[ticker].upper()
    return ticker

async def send_telegram_alert(message: str):
    """Send Telegram alert asynchronously."""
    logger.info(f"Sending Telegram alert: {message}")
    try:
        async with aiohttp.ClientSession() as session:
            response = await TGMessenger.send_async(session, message, 'LP eagle')
            if not response.get('ok', False):
                logger.error(f"Telegram response error: {response}")
    except Exception as e:
        logger.error(f"Telegram alert failed: {e}")

async def sync_hedgeable_tokens():
    """Sync new LP tokens with configured hedge exchange perpetual futures."""
    logger.info("Starting hedgeable tokens sync...")
    ensure_data_directory()
    config = get_config() or {}
    hedge_cfg = get_hedge_exchange_config(config)
    hedge_exchange = hedge_cfg["exchange"]
    hedge_account = hedge_cfg["account"]
    logger.info("Hedge exchange configuration: exchange=%s account=%s", hedge_exchange, hedge_account)

    # Fetch hedge exchange perpetual markets
    hedge_symbols = await fetch_hedge_markets(hedge_exchange)
    if not hedge_symbols:
        logger.error(f"No {hedge_exchange} perpetual symbols fetched")
        return

    # Create set of hedge symbols for exact matching
    hedge_symbol_set = set(hedge_symbols)

    # Fetch LP positions
    meteora_positions = await fetch_lp_positions("meteora")
    krystal_positions = await fetch_lp_positions("krystal")
    all_positions = meteora_positions + krystal_positions

    if not all_positions:
        logger.warning("No LP positions found")
        return

    # Load existing hedgeable and encountered tokens
    hedgeable_tokens = load_hedgeable_tokens()
    encountered_tokens = load_encountered_tokens()
    existing_contracts = {}  # chain -> set of CAs
    encountered_contracts = set()

    # Map hedgeable tokens to tickers and CAs
    ticker_to_symbol = {}  # base ticker -> hedge symbol
    for symbol, chains in hedgeable_tokens.items():
        base = symbol.split('USDT')[0].upper()
        ticker_to_symbol[base] = symbol
        for chain, addresses in chains.items():
            if chain not in existing_contracts:
                existing_contracts[chain] = set()
            for addr in addresses:
                existing_contracts[chain].add(addr)

    for symbol, chains in encountered_tokens.items():
        for chain, addresses in chains.items():
            for addr in addresses:
                encountered_contracts.add(addr)

    # Process new tokens
    new_tokens_added = False
    encountered_updated = False
    for position in all_positions:
        ticker = position["ticker"]
        contract_address = position["contract_address"]
        chain = position["chain"].lower()

        if not ticker or not contract_address or not chain:
            logger.warning(f"Invalid position data: {position}")
            continue

        normalized_ticker = normalize_ticker(ticker)
        hedge_symbol = f"{normalized_ticker}USDT"

        # Add to encountered tokens if new
        if contract_address not in encountered_contracts:
            if hedge_symbol not in encountered_tokens:
                encountered_tokens[hedge_symbol] = {}
            if chain not in encountered_tokens[hedge_symbol]:
                encountered_tokens[hedge_symbol][chain] = []
            if contract_address not in encountered_tokens[hedge_symbol][chain]:
                encountered_tokens[hedge_symbol][chain].append(contract_address)
                encountered_contracts.add(contract_address)
                encountered_updated = True
                logger.info(f"New token encountered: {ticker} ({contract_address}) on {chain}")

                # Check if token is non-hedgeable (not in hedge exchange symbols)
                if hedge_symbol not in hedge_symbol_set:
                    await send_telegram_alert(
                        f"🚨 New Non-Hedgeable Token Encountered 🚨:  \n"
                        f" Ticker: {normalized_ticker} \n"
                        f" Contract Address: {contract_address} \n"
                        f" Chain: {chain} \n"
                        f" Hedge Exchange: {hedge_exchange} \n"
                        f"🚨 Action: Check {hedge_exchange} for alternative ticker. 🚨"
                    )

        # Skip if CA already in hedgeable tokens for this chain
        if chain in existing_contracts and contract_address in existing_contracts[chain]:
            logger.debug(f"Contract {contract_address} ({ticker}) already in hedgeable tokens for {chain}")
            continue

        # Skip USDC and USDT for hedgeable tokens
        if normalized_ticker in ['USDC', 'USDT']:
            logger.info(f"Skipping {normalized_ticker} ({contract_address}) for hedgeable tokens")
            continue

        # Check if ticker matches an existing hedgeable token
        if normalized_ticker in ticker_to_symbol:
            hedge_symbol = ticker_to_symbol[normalized_ticker]
            if hedge_symbol not in hedgeable_tokens:
                hedgeable_tokens[hedge_symbol] = {}
            if chain not in hedgeable_tokens[hedge_symbol]:
                hedgeable_tokens[hedge_symbol][chain] = []
            if contract_address not in hedgeable_tokens[hedge_symbol][chain]:
                hedgeable_tokens[hedge_symbol][chain].append(contract_address)
                new_tokens_added = True
                logger.info(f"Added new CA for existing token: {normalized_ticker} ({contract_address}) on {chain}, matched {hedge_symbol}")
                await send_telegram_alert(
                    f" 🚨 New Contract Address for Existing Token: 🚨 \n"
                    f" Ticker: {normalized_ticker} \n"
                    f" Contract Address: {contract_address} \n"
                    f" Chain: {chain} \n"
                    f" Hedge Exchange: {hedge_exchange} \n"
                    f" Hedge Symbol: {hedge_symbol}"
                )
            continue

        # Exact match with hedge exchange
        if hedge_symbol in hedge_symbol_set:
            if hedge_symbol not in hedgeable_tokens:
                hedgeable_tokens[hedge_symbol] = {}
            if chain not in hedgeable_tokens[hedge_symbol]:
                hedgeable_tokens[hedge_symbol][chain] = []
            if contract_address not in hedgeable_tokens[hedge_symbol][chain]:
                hedgeable_tokens[hedge_symbol][chain].append(contract_address)
                new_tokens_added = True
                logger.info(f"Added new hedgeable token: {normalized_ticker} ({contract_address}) on {chain}, matched {hedge_symbol}")
                await send_telegram_alert(
                    f" 🚨 New Hedgeable Token Added: 🚨\n"
                    f" Ticker: {normalized_ticker} \n"
                    f" Contract Address: {contract_address} \n"
                    f" Chain: {chain} \n"
                    f" Hedge Exchange: {hedge_exchange} \n"
                    f" 🚨 Matched Hedge Symbol: {hedge_symbol} 🚨"
                )

    # Save updated files
    if new_tokens_added:
        save_hedgeable_tokens(hedgeable_tokens)
    if encountered_updated:
        save_encountered_tokens(encountered_tokens)

    if not (new_tokens_added or encountered_updated):
        logger.info("No new hedgeable or encountered tokens added")

async def main():
    """Main function to run sync."""
    try:
        await sync_hedgeable_tokens()
    except Exception as e:
        logger.error(f"Sync error: {str(e)}")
        await send_telegram_alert(f"🚨🚨🚨 Hedgeable Tokens Syncronization Error:\n Error: {str(e)}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())