# LP-hedging-strategy

Standalone (NOT part of the `mm_core` brain stack) pipeline for automated monitoring, hedging, and
rebalancing of DEX liquidity-pool positions, with short-hedge execution on centralized exchanges
(BitGet / HyperLiquid). Multi-chain LP tracking (Solana Meteora DLMM + EVM chains via Krystal),
PnL calc with CSV archival, TVL/volume enrichment (GeckoTerminal), WS order management, funding-rate
alerts, and a visualization webapp.

## Layout

- `lp-monitor/` — TypeScript / Node.js: LP position fetching & PnL (chain + DEX adapters). Uses npm.
- `python/` — Python hedging pipeline: metrics fetching, hedge monitoring, Krystal PnL, hedge rebalancer,
  hedge automation (WS + REST), shared utils/exchange adapters/reporting, `display_results` webapp.

## Rules

- Test Driven Design: write tests first, confirm they FAIL, commit, then implement. One task per loop. Update planning docs, commit after completion.
- Compulsory virtual env: the Python side must run in its own dedicated `.venv` (never global Python).
  The TypeScript side manages deps via its own `package.json`/`node_modules` in `lp-monitor/`.
- This repo is separate from the amm-solution MM brain: do not introduce shared-brain coupling;
  `PONYTAIL-DEBT.md` at the monorepo root captures related debt — read it.
- Editing: prefer `patch` with unique context over `write_file`. Re-read the file first; patch hallucinates old_string often.
- When prompting for selection, list items numbered (1, 2, 3...). Never ask more than one yes/no question.
- Safety-first: reversible actions only (trash > rm). Scientific rigor: verify everything, never guess. Minimalist and lean.
- Secrets/keys/wallet config stay in env/config files, never committed. Hedging touches real funds:
  validate orders and thresholds before placing; direct infra changes ask first, or give the exact sudo command.
- Communication: concise, terse, English only. "y" = go ahead — don't second-guess.