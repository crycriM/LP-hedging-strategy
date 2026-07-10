# display_results.py — Minimal Specifications

## Purpose
Entry point for the hedging dashboard application. Orchestrates data loading, user interaction flows, and back-end operations (workflow scripts, config updates, order management).

---

## Global State

### `order_manager`
- Type: `OrderManager`
- Initialized at module load.
- Provides the order sender for `HedgeActions`.

### `hedge_actions`
- Type: `HedgeActions`
- Initialized with `order_manager.get_order_sender()`.

---

## Utility Functions

### `format_usd(value) -> str`
- Formats a numeric value as `$X,XXX.XX`.
- Returns `"N/A"` if the value is `NaN` (pandas `pd.na`).

---

## Asynchronous Functions

### `handle_vault_share_change()`
**Trigger:** User clicks the vault-share change button.

**Behavior:**
1. Reads `krystal_vault_wallet_chain_ids` from `LPMONITOR_YAML_CONFIG_PATH`.
2. Maps integer chain IDs to human-readable names (ethereum, bsc, polygon, sonic, arbitrum, base).
3. Collects wallet options (label includes chains and current vault share).
4. Presents a form to select a wallet and enter a new vault share (validated to `[0, 1]`).
5. On save, writes the updated vault share back to the YAML file (preserving key order, `default_flow_style=False`).

**Error handling:**
- File not found → warning toast.
- YAML parse error → error toast.
- Missing/invalid config structure → error toast.
- Generic exception → error toast.

---

### `render_lp_summary(dataframes, error_flags)`
**Trigger:** User clicks the LP Summary button.

**Behavior:**
1. Aggregates LP data from two sources:
   - **Krystal** — reads `"Actual Value USD"`, `"Chain"`, `"Protocol"`, `"Token X/Y Symbol"`, `"Pool Address"`.
   - **Meteora** — computes USD value as `(qty_x * price_x) + (qty_y * price_y)`, hard-codes chain to `"solana"`.
2. Skips a source if its error flag is set.
3. If no LP data exists, shows a fallback text.
4. Displays the **total LP value across all chains**.
5. Presents a chain selector (options: "All Chains" + each unique chain, capitalized).
6. **When "All Chains" is selected:**
   - Groups by `Protocol` → shows protocol-level totals.
   - Groups by `(Pool Address, Pair)` → shows pool-level breakdown (truncated address).
7. **When a specific chain is selected:**
   - Shows the chain's total LP value.
   - Groups by `Protocol` → shows protocol-level totals.
   - Presents a protocol selector (options: "All Protocols" + each unique protocol).
   - Groups by `(Pool Address, Pair)`, optionally filtered by the selected protocol, showing pool-level breakdown.

---

### `main()`
**Configuration:** `theme="yeti"`

**Rendering order (scoped as `'dashboard'`):**

1. **Header** — title and subtitle text.
2. **Data Loading** — calls `load_hedgeable_tokens()` and `load_data()`.
3. **Error Reporting** — if `errors['has_error']` is true, renders an error block with each message.
4. **Hedging Dashboard** — only if `"Rebalanced"` or `"Hedging"` DataFrames exist:
   - Shows timestamps for last Meteora LP update, Krystal LP update, and hedge data update.
   - **"Update LP and Hedge Data" button** → runs `WORKFLOW_SHELL_SCRIPT` asynchronously.
   - **"Update Hedge Data" button** → runs `HEDGE_SHELL_SCRIPT` asynchronously.
   - Calls `render_hedging_table(dataframes, errors, hedge_actions)`.
5. **Vault Share Configuration** — explanatory text + button that triggers `handle_vault_share_change()`.
6. **Hedge Automation** — explanatory text, calls `render_hedge_automation()`, presents a checkbox form built from `HEDGABLE_TOKENS` (stripped of `"USDT"` suffix). On save, calls `save_auto_hedge_tokens()`.
7. **Custom Hedge Section** — awaits `render_custom_hedge_section(hedge_actions)`.
8. **Token Mapping Section** — awaits `render_add_token_mapping_section()`.
9. **Wallet Positions** — shows last Meteora/Krystal LP update timestamps, calls `render_wallet_positions(dataframes, error_flags)`.
10. **LP Positions P&L** — "Calculate P&L" button that runs `PNL_SHELL_SCRIPT` asynchronously, calls `render_pnl_tables(dataframes, error_flags)`.
11. **LP Summary** — "View LP Summary" button that triggers `render_lp_summary(dataframes, error_flags)`.

---

## Lifecycle

### `cleanup()`
- Calls `order_manager.close()` via `asyncio.run()`.
- Registered with `atexit.register()`.

### Entry Point
- Starts the application server on `0.0.0.0:8080` with debug enabled.

---

## Platform Notes
- On Windows (`sys.platform == 'win32'`), sets the asyncio event loop policy to `WindowsSelectorEventLoopPolicy` to work around a known event-loop issue.

---

## Logging
- Level: `INFO`.
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`.
- Handlers: file (in `LOG_DIR`) + stdout.
- Logger name: `__name__` (module-level logger).

---

## Dependencies (non-UI)

| Symbol | Source |
|---|---|
| `load_data`, `load_hedgeable_tokens` | `common.data_loader` |
| `WORKFLOW_SHELL_SCRIPT`, `PNL_SHELL_SCRIPT`, `HEDGE_SHELL_SCRIPT`, `LOG_DIR`, `LPMONITOR_YAML_CONFIG_PATH` | `common.path_config` |
| `OrderManager` | `hedge_automation.order_manager` |
| `HedgeActions` | `hedge_automation.hedge_actions` |
| `run_shell_script` | `common.utils` |
| `render_add_token_mapping_section` | `ui.ticker_mapping` |
| `render_wallet_positions`, `render_pnl_tables`, `render_hedging_table`, `render_hedge_automation`, `save_auto_hedge_tokens`, `load_auto_hedge_tokens`, `render_custom_hedge_section` | `ui.table_renderer` |