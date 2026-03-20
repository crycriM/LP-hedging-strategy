# LP Hedging Strategy

LP Hedging Strategy is a multi-part project designed to monitor liquidity pool (LP) positions and implement automated hedging on BitGet and rebalancing strategies across various blockchain networks. The project is divided into two main components:

- **lp-monitor (TypeScript/Node.js):**  
  This module retrieves and processes LP positions from decentralized exchanges on Solana and Ethereum. It gathers data, calculates profit & loss (PnL), and generates CSV reports for tracking the latest positions and overall liquidity profiles.

- **Python Modules:**  
  Packages for hedge monitoring, hedge rebalancing, and hedge automation. 

## Features

- **Multi-Chain Support:**  
  Track LP positions on Solana (only Meteora via meteora API) and EVM chains (via Krystal API).

- **Real-Time Position Tracking:**  
  Retrieve LP positions from multiple wallet addresses, calculate PnL (only for meteora positions), and generate CSV reports.

- **Automated Hedging & Rebalancing:**  
  Python scripts to monitor, hedge, and rebalance positions automatically based on market changes.



## Installation & Setup

0. **Clone repository:**
   ```bash
   cd <your repo path>
   git clone <repo github url>

### For lp-monitor (Node.js/TypeScript)

1. **Install Dependencies:**
   ```bash
   cd lp-monitor
   npm install

2. **Build project:**
   ```bash
   npm run build

3. **Run project:**
   ```bash
   npm start

4. **Run Pnl calculations for meteora**
   ```bash
   npm run pnlMeteora

### For python/various-hedging-tools (Python)

1. **install the tools as modules from the root directory (where setup.py is located):**
   ```bash
   pip install -e .

2. **run hedging tools, from the python/ folder which is the base dir for the python packages**
   ```bash
   cd python

   2. ** fetch tvl and volume data from gecko terminal API **
      ```bash
        python -m LP_metrics_fetching.tvl_fetcher 

   2a. **run hedge-monitoring for fetching active hedge positions on Bitget:**
        ```bash
        python -m hedge_monitoring.sync_bitget_hedgeable_tokens 

        python -m hedge_monitoring.bitget_position_fetcher

   2b. **run hedge-rebalancer to compute which positions needs rebalancing**
        ```bash
        python -m hedge_rebalancer.hedge_rebalancer

   2c. **run krystal_pnl workflow **
        ```bash
        python -m krystal_pnl.run_krystal_pnl

   2c. **run auto hedging workflow **
        ```bash
        python -m hedge_automation.auto_hedge

3. **run simple visualization webapp:**
    ```bash
    python -m display_results


### Configuration

1. **Configure Environment:**
   Update the configuration in config.ts or set the environment variables (wallet addresses, API keys, output folders paths etc.).

   ENV vars for lp-monitor:
    BITGET_HEDGE1_API_KEY=...
    BITGET_HEDGE1_API_SECRET=...
    BITGET_API_PASSWORD=...

   other ENV vars:
    TELEGRAM_TOKEN
      EXECUTION_IP=your.execution.host

    ROOT_DIR=absolute_path\LP-hedging-strategy
    LP_HEDGE_LOG_DIR=absolute_path\LP-hedging-strategy\logs
    LP_HEDGE_DATA_DIR=absolute_path\LP-hedging-strategy\lp-data
    PYTHON_YAML_CONFIG_PATH=absolute_path\LP-hedging-strategy\python\config.yaml

2. **Configure yaml files**

   # lp-monitor configuration: /lp-monitor/lpMonitorConfig.yaml

      # insert krystal chain id for what blockchains to monitor
      krystal_chain_ids:
         - "1" # Ethereum
         - "137" # Polygon
         - "56" # BSC
         - "42161" # Arbitrum
         - "146" # Sonic
         - "8453" # Base

      # insert desired solana rpc to connect to
      rpc_endpoint: "https://rpc-proxy.segfaultx0.workers.dev"

      # insert desired solana and evm wallets to monitor
      solana_wallet_addresses:
         - "sol_addr_1"
         - "sol_addr_2"

      evm_wallet_addresses:
         - "evm_addr_1"
         - "evm_addr_2"

      
      # insert desired krystal vaults to monitor, with respective krystal chain id and vault share
      krystal_vault_wallet_chain_ids:
      - wallet: "vault_addr_1"
         chains: ["137"]
         vault_share: 0.915
      - wallet: "vault_addr_2"
         chains: ["8453"]
         vault_share: 1

   # python code configuration /python/pythonConfig.yaml

      # Automatic Hedge triggers configuration
      hedge_rebalancer:

         # Triggers for initiating rebalancing actions
         triggers:
            # Positive trigger: underhedged pctg
            positive: 0.02
            # Negative trigger: overhedged pctg
            negative: -0.02
            # minimum value to trigger a rebalance
            min_usd: 200



