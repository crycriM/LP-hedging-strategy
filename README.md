# LP Hedging Strategy

Automated monitoring, hedging, and rebalancing pipeline for decentralized exchange (DEX) liquidity pool positions, with short hedge execution on centralized exchanges (BitGet / HyperLiquid).

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Pipeline Overview](#pipeline-overview)
- [Output Files](#output-files)
- [License](#license)
- [Disclaimer](#disclaimer)

---

## Features

- **Multi-Chain LP Tracking**
  Solana (Meteora DLMM via on-chain RPC + Meteora API) and EVM chains (Ethereum, Polygon, BSC, Arbitrum, Sonic, Base) via the Krystal API.

- **PnL Calculation**
  Per-position profit & loss for Meteora LPs and Krystal V3 pools, with historical CSV archival.

- **TVL & Volume Enrichment**
  Fetches pool-level TVL and volume data from the GeckoTerminal API.

- **Automated Hedging**
  Syncs hedgeable tokens, fetches active hedge positions from BitGet or HyperLiquid, and places rebalancing orders automatically.

- **Smart Rebalancing**
  Configurable deviation triggers (over/under-hedged thresholds) with optional quantity smoothing over a lookback window.

- **WebSocket Order Management**
  Real-time order monitoring and execution via exchange WebSocket connections.

- **Funding Rate Alerts**
  Alerts when funding rates cross a configurable threshold (in basis points).

- **Visualization Dashboard**
  Built-in webapp (`display_results`) for inspecting positions, hedge status, and rebalancing decisions.

---

## Architecture

```
.
├── lp-monitor/                    # TypeScript / Node.js — LP position fetching & PnL
│   ├── src/
│   │   ├── chains/                # Chain-specific adapters (Solana, EVM)
│   │   ├── dexes/                 # DEX integrations (Meteora, etc.)
│   │   ├── services/              # API / data services
│   │   ├── utils/                 # Shared utilities
│   │   ├── config.ts              # TS environment config
│   │   ├── index.ts               # Main entry — fetch positions
│   │   └── meteoraCalculations.ts # Meteora PnL computations
│   ├── lpMonitorConfig.yaml       # Wallet addresses, chains, RPC
│   └── package.json
│
├── python/                        # Python — hedging pipeline
│   ├── LP_metrics_fetching/       # TVL / volume from GeckoTerminal API
│   ├── hedge_monitoring/          # Sync hedgeable tokens + fetch active hedges
│   ├── krystal_pnl/               # Krystal LP PnL calculations
│   ├── hedge_rebalancer/          # Compute rebalance actions + smoothing
│   ├── hedge_automation/          # Execute hedge orders (WS + REST)
│   ├── common/                    # Shared utils, exchange adapters, reporting
│   ├── ui/                        # Table rendering, ticker mapping
│   ├── config/                    # Token lists, ticker mappings (JSON)
│   ├── config.py                  # YAML config loader
│   ├── display_results.py         # Webapp dashboard
│   └── pythonConfig.yaml          # Python pipeline configuration
│
├── setup.py                       # Python package install
├── .env.example                   # Environment variable template
└── README.md
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Node.js | >= 18 |
| npm | >= 9 |
| Python | >= 3.10 |
| pip | >= 22 |
| Git | any |

You also need:
- A **BitGet** or **HyperLiquid** account with API credentials (key, secret, passphrase)
- A **Solana RPC endpoint** (public or private)
- (Optional) A **Telegram bot** token for notifications

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/crycriM/LP-hedging-strategy.git
cd LP-hedging-strategy
```

### 2. lp-monitor (TypeScript / Node.js)

```bash
cd lp-monitor
npm install
npm run build
```

### 3. Python modules

From the repository root (where `setup.py` is located):

```bash
pip install -e .
```

### 4. Environment variables

```bash
cp .env.example .env
# Edit .env with your API keys and paths
```

---

## Configuration

### lp-monitor — `lp-monitor/lpMonitorConfig.yaml`

```yaml
# Solana RPC endpoint
rpc_endpoint: "https://your-solana-rpc.example.com"

# Wallet addresses to monitor
solana_wallet_addresses:
  - "sol_addr_1"
  - "sol_addr_2"

evm_wallet_addresses:
  - "evm_addr_1"
  - "evm_addr_2"

# Krystal chain IDs to scan for EVM LPs
krystal_chain_ids:
  - "1"      # Ethereum
  - "137"    # Polygon
  - "56"     # BSC
  - "42161"  # Arbitrum
  - "146"    # Sonic
  - "8453"   # Base

# Krystal vault positions (optional)
krystal_vault_wallet_chain_ids:
  - wallet: "vault_addr_1"
    chains: ["137"]
    vault_share: 0.915
  - wallet: "vault_addr_2"
    chains: ["8453"]
    vault_share: 1.0
```

### Python pipeline — `python/pythonConfig.yaml`

```yaml
hedge:
  exchange: bitget           # Supported: bitget, hyperliquid
  account: H1                # Account selector for multi-account setups

hedge_rebalancer:
  triggers:
    positive: 0.2            # Rebalance if under-hedged by > 20%
    negative: -0.2           # Rebalance if over-hedged by > 20%
    min_usd: 200             # Minimum USD deviation to trigger
  smoother:
    use_smoothed_qty: true
    smoothing_lookback_h: 36 # Hours to average position quantities

hedge_monitoring:
  funding_rate_alert_threshold: -20  # Alert when funding rate < -20 bips
```

### Environment variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Description |
|---|---|
| `BITGET_HEDGE1_API_KEY` | BitGet API key |
| `BITGET_HEDGE1_API_SECRET` | BitGet API secret |
| `BITGET_API_PASSWORD` | BitGet API passphrase |
| `TELEGRAM_TOKEN` | Telegram bot token for notifications |
| `EXECUTION_IP` | Remote execution host (optional) |
| `ROOT_DIR` | Absolute path to this repository |
| `LP_HEDGE_LOG_DIR` | Path for log output |
| `LP_HEDGE_DATA_DIR` | Path for CSV data output |
| `PYTHON_YAML_CONFIG_PATH` | Path to `pythonConfig.yaml` |

---

## Usage

### lp-monitor commands

```bash
cd lp-monitor

# Fetch LP positions from all configured chains
npm start

# Run Meteora PnL calculations
npm run pnlMeteora
```

### Python pipeline commands

All commands are run from the `python/` directory:

```bash
cd python
```

**Step 1 — Enrich with TVL / volume data**

```bash
python -m LP_metrics_fetching.tvl_fetcher
```

**Step 2 — Sync hedgeable tokens & fetch hedge positions**

```bash
python -m hedge_monitoring.sync_hedgeable_tokens
python -m hedge_monitoring.hedge_position_fetcher
```

**Step 3 — Compute rebalance actions**

```bash
python -m hedge_rebalancer.hedge_rebalancer
```

**Step 4 — Compute Krystal PnL**

```bash
python -m krystal_pnl.run_krystal_pnl
```

**Step 5 — Execute automated hedging**

```bash
python -m hedge_automation.auto_hedge
```

**Dashboard — Visualization webapp**

```bash
python -m display_results
```

---

## Pipeline Overview

The modules are designed to run in sequence. A typical automated workflow:

```
┌──────────────────────┐
│  lp-monitor          │  Fetch LP positions (Solana + EVM)
│  npm start           │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  LP_metrics_fetching │  Enrich with TVL / volume from GeckoTerminal
│  tvl_fetcher         │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  hedge_monitoring    │  Sync hedgeable tokens + fetch active hedge positions
│  sync + fetch        │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  hedge_rebalancer    │  Compute deviations, apply quantity smoothing,
│  rebalancer          │  generate rebalance orders
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  hedge_automation    │  Execute / cancel hedge orders via WebSocket + REST
│  auto_hedge          │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  display_results     │  Webapp dashboard for monitoring
└──────────────────────┘
```

---

## Output Files

All data files are written to `$LP_HEDGE_DATA_DIR` (default: `<repo_root>/lp-data/`):

| File | Description |
|---|---|
| `LP_meteora_positions_latest.csv` | Current Meteora LP positions |
| `LP_krystal_positions_latest.csv` | Current Krystal EVM LP positions |
| `LP_positions_smoothed.csv` | Position quantities after smoothing |
| `hedging_positions_latest.csv` | Active hedge positions on exchange |
| `rebalancing_results.csv` | Rebalance recommendations |
| `position_pnl_results.csv` | Meteora PnL per position |
| `krystal_pnl_by_pool.csv` | Krystal PnL per pool |
| `active_pools.csv` | TVL & volume enriched pool data |
| `automatic_order_monitor.csv` | Automated hedge order tracking |
| `manual_order_monitor.csv` | Manual order tracking |

History files are appended on each run (e.g. `LP_meteora_positions_history.csv`).

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Disclaimer

This software is provided for educational and research purposes only. It interacts with real financial instruments (CEX perpetual futures) and DeFi protocols. Use at your own risk. The authors are not responsible for any financial losses incurred through the use of this software. This is not financial advice. Always test with paper-trading or small positions before deploying significant capital.
