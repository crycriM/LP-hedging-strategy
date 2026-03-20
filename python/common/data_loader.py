import pandas as pd
import json
import logging
import os
from pathlib import Path
from datetime import datetime
from common.path_config import (
    REBALANCING_LATEST_CSV, KRYSTAL_LATEST_CSV, METEORA_LATEST_CSV, HEDGING_LATEST_CSV, HEDGE_ERROR_FLAGS_PATH, LP_ERROR_FLAGS_PATH,
    METEORA_PNL_CSV, KRYSTAL_POOL_PNL_CSV, LOG_DIR, HEDGEABLE_TOKENS_JSON, ENCOUNTERED_TOKENS_JSON, TICKER_MAPPINGS_PATH, CONFIG_DIR,
    ACTIVE_POOLS_TVL, LP_SMOOTHED_CSV
)


logger = logging.getLogger(__name__)

def load_data():
    dataframes = {}
    error_flags = {'hedge': {}, 'lp': {}}
    errors = {
        'has_error': False,
        'krystal_error': False,
        'meteora_error': False,
        'hedging_error': False,
        'vault_error': False,  # Added vault_error
        'messages': []
    }

    # Load hedging error flags 
    try:
        if HEDGE_ERROR_FLAGS_PATH.exists():
            with HEDGE_ERROR_FLAGS_PATH.open('r') as f:
                error_flags['hedge'] = json.load(f)
                hedge_fetch_error = (
                    error_flags['hedge'].get("HEDGING_FETCHING_EXCHANGE_ERROR", False)
                    or error_flags['hedge'].get("HEDGING_FETCHING_BITGET_ERROR", False)
                )
                if hedge_fetch_error:
                    errors['has_error'] = True
                    errors['hedging_error'] = True
                    error_msg = (
                        error_flags['hedge'].get("hedge_error_message")
                        or error_flags['hedge'].get("bitget_error_message")
                        or "Failed to fetch hedge exchange data"
                    )
                    errors['messages'].append(f"Hedging exchange error: {error_msg}")
                if "last_updated_hedge" not in error_flags['hedge']:
                    logger.warning("last_updated_hedge missing in hedge_fetching_errors.json")
        else:
            logger.warning(f"Hedging error flags file not found: {HEDGE_ERROR_FLAGS_PATH}")
            errors['has_error'] = True
            errors['hedging_error'] = True
            errors['messages'].append("Hedging error flags file missing")
    except Exception as e:
        logger.error(f"Error reading hedging error flags: {str(e)}")
        errors['has_error'] = True
        errors['hedging_error'] = True
        errors['messages'].append(f"Error reading hedging error flags: {str(e)}")

    # Load LP error flags 
    try:
        if LP_ERROR_FLAGS_PATH.exists():
            with LP_ERROR_FLAGS_PATH.open('r') as f:
                error_flags['lp'] = json.load(f)
                if error_flags['lp'].get("LP_FETCHING_KRYSTAL_ERROR", False):
                    errors['has_error'] = True
                    errors['krystal_error'] = True
                    error_msg = error_flags['lp'].get("krystal_error_message", "Failed to fetch Krystal LP data")
                    errors['messages'].append(f"LP Krystal error: {error_msg}")
                if error_flags['lp'].get("LP_FETCHING_METEORA_ERROR", False):
                    errors['has_error'] = True
                    errors['meteora_error'] = True
                    error_msg = error_flags['lp'].get("meteora_error_message", "Failed to fetch Meteora LP data")
                    errors['messages'].append(f"LP Meteora error: {error_msg}")
                if error_flags['lp'].get("LP_FETCHING_VAULT_ERROR", False):
                    errors['has_error'] = True
                    errors['vault_error'] = True
                    error_msg = error_flags['lp'].get("vault_error_message", "Failed to fetch vault LP data")
                    errors['messages'].append(f"LP Vault error: {error_msg}")
                if "last_meteora_lp_update" not in error_flags['lp']:
                    logger.warning("last_meteora_lp_update missing in lp_fetching_errors.json")
                if "last_krystal_lp_update" not in error_flags['lp']:
                    logger.warning("last_krystal_lp_update missing in lp_fetching_errors.json")
                if "last_vault_lp_update" not in error_flags['lp']:
                    logger.warning("last_vault_lp_update missing in lp_fetching_errors.json")
        else:
            logger.warning(f"LP error flags file not found: {LP_ERROR_FLAGS_PATH}")
            errors['has_error'] = True
            errors['krystal_error'] = True
            errors['meteora_error'] = True
            errors['vault_error'] = True
            errors['messages'].append("LP error flags file missing")
    except Exception as e:
        logger.error(f"Error reading LP error flags: {str(e)}")
        errors['has_error'] = True
        errors['krystal_error'] = True
        errors['meteora_error'] = True
        errors['vault_error'] = True
        errors['messages'].append(f"Error reading LP error flags: {str(e)}")

    # Load CSVs 
    csv_files = {
        "Rebalancing": REBALANCING_LATEST_CSV,
        "Krystal": KRYSTAL_LATEST_CSV,
        "Meteora": METEORA_LATEST_CSV,
        "Hedging": HEDGING_LATEST_CSV,
        "Meteora PnL": METEORA_PNL_CSV,
        "Krystal PnL": KRYSTAL_POOL_PNL_CSV,
        "Active Pools TVL": ACTIVE_POOLS_TVL,
    }

    for name, path in csv_files.items():
        if not os.path.exists(path):
            logger.warning(f"CSV file not found: {path}")
            errors['messages'].append(f"Error: {path} not found")
            continue
        try:
            dataframes[name] = pd.read_csv(path)
            logger.info(f"Loaded CSV: {path}")
            if name == "Krystal" and errors['krystal_error']:
                logger.warning(f"Krystal CSV {path} may be stale due to LP fetching error")
            if name == "Meteora" and errors['meteora_error']:
                logger.warning(f"Meteora CSV {path} may be stale due to LP fetching error")
            if name == "Hedging" and errors['hedging_error']:
                logger.warning(f"Hedging CSV {path} may be stale due to hedging fetching error")
        except Exception as e:
            logger.error(f"Error reading CSV {path}: {str(e)}")
            errors['messages'].append(f"Error reading {name} CSV: {str(e)}")

    return {
        'dataframes': dataframes,
        'error_flags': error_flags,
        'errors': errors
    }


def load_hedgeable_tokens() -> dict:
    """Load hedgeable tokens from JSON."""
    try:
        if HEDGEABLE_TOKENS_JSON.exists():
            with HEDGEABLE_TOKENS_JSON.open('r') as f:
                return json.load(f)
        else:
            logger.info(f"{HEDGEABLE_TOKENS_JSON} not found, initializing empty dictionary")
            return {}
    except Exception as e:
        logger.error(f"Error loading hedgeable tokens: {str(e)}")
        return {}

def load_encountered_tokens() -> dict:
    """Load encountered tokens from JSON."""
    try:
        if ENCOUNTERED_TOKENS_JSON.exists():
            with ENCOUNTERED_TOKENS_JSON.open('r') as f:
                return json.load(f)
        else:
            logger.info(f"{ENCOUNTERED_TOKENS_JSON} not found, initializing empty dictionary")
            return {}
    except Exception as e:
        logger.error(f"Error loading encountered tokens: {str(e)}")
        return {}

def load_json(file_path) -> dict:
    """Load JSON file."""
    try:
        if file_path.exists():
            with file_path.open('r') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    logger.error(f"Invalid format in {file_path}: Expected dictionary")
                    return {}
                logger.debug(f"Loaded: {data}")
                return data
        else:
            logger.info(f"{file_path} not found, returning empty dictionary")
            return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON in {file_path}: {str(e)}")
        return {}
    except Exception as e:
        logger.error(f"Error loading {file_path}: {str(e)}")
        return {}
    
def load_ticker_mappings() -> dict:
    """Load ticker mappings from ticker_mappings.json or initialize with defaults."""
    default_mappings = {
        "SYMBOL_MAP": {},
        "HEDGE_TOKENS_WITH_FACTOR_1000": {},
        "HEDGE_TOKENS_WITH_FACTOR_10000": {},
        "BITGET_TOKENS_WITH_FACTOR_1000": {},
        "BITGET_TOKENS_WITH_FACTOR_10000": {}
    }
    try:
        if TICKER_MAPPINGS_PATH.exists():
            with TICKER_MAPPINGS_PATH.open('r') as f:
                content = f.read().strip()
                if not content:
                    logger.warning("ticker_mappings.json is empty, returning defaults")
                    return default_mappings
                data = json.loads(content)
                # Backward/forward compatibility between generic and legacy keys
                if "HEDGE_TOKENS_WITH_FACTOR_1000" not in data and "BITGET_TOKENS_WITH_FACTOR_1000" in data:
                    data["HEDGE_TOKENS_WITH_FACTOR_1000"] = data["BITGET_TOKENS_WITH_FACTOR_1000"]
                if "HEDGE_TOKENS_WITH_FACTOR_10000" not in data and "BITGET_TOKENS_WITH_FACTOR_10000" in data:
                    data["HEDGE_TOKENS_WITH_FACTOR_10000"] = data["BITGET_TOKENS_WITH_FACTOR_10000"]
                if "BITGET_TOKENS_WITH_FACTOR_1000" not in data and "HEDGE_TOKENS_WITH_FACTOR_1000" in data:
                    data["BITGET_TOKENS_WITH_FACTOR_1000"] = data["HEDGE_TOKENS_WITH_FACTOR_1000"]
                if "BITGET_TOKENS_WITH_FACTOR_10000" not in data and "HEDGE_TOKENS_WITH_FACTOR_10000" in data:
                    data["BITGET_TOKENS_WITH_FACTOR_10000"] = data["HEDGE_TOKENS_WITH_FACTOR_10000"]
                # Ensure all expected keys exist
                for key in default_mappings:
                    if key not in data:
                        data[key] = {}
                logger.info("Ticker mappings loaded from ticker_mappings.json")
                return data
        else:
            logger.info("ticker_mappings.json not found, creating with defaults")
            save_ticker_mappings(default_mappings)
            return default_mappings
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Error loading ticker_mappings.json: {e}")
        save_ticker_mappings(default_mappings)
        return default_mappings

def save_ticker_mappings(mappings: dict):
    """Save ticker mappings to ticker_mappings.json."""
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        with TICKER_MAPPINGS_PATH.open('w') as f:
            json.dump(mappings, f, indent=2)
        logger.info("Ticker mappings saved to ticker_mappings.json")
    except Exception as e:
        logger.error(f"Error saving ticker_mappings.json: {e}")


def load_smoothed_quantities() -> tuple[datetime, dict]:
    """
    Load the most recent smoothed quantities and timestamp from LP_SMOOTHED_CSV.
    :return: Tuple of (timestamp: datetime, quantities: dict) where quantities has token symbols as keys and smoothed quantities as values
    """
    try:
        if not LP_SMOOTHED_CSV.exists():
            logger.warning(f"Smoothed quantities file not found: {LP_SMOOTHED_CSV}")
            return None, {}

        df = pd.read_csv(LP_SMOOTHED_CSV, index_col=0, parse_dates=True)
        if df.empty:
            logger.warning(f"Smoothed quantities CSV is empty: {LP_SMOOTHED_CSV}")
            return None, {}

        # Get the most recent row and its timestamp
        latest_timestamp = df.index[-1]
        latest_quantities = df.iloc[-1].to_dict()
        logger.debug(f"Loaded smoothed quantities at {latest_timestamp}: {latest_quantities}")
        return latest_timestamp, {k: float(v) for k, v in latest_quantities.items() if not pd.isna(v)}
    
    except Exception as e:
        logger.error(f"Error loading smoothed quantities from {LP_SMOOTHED_CSV}: {str(e)}")
        return None, {}

