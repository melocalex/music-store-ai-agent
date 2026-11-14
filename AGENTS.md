# Working on this repo

Think before editing. Name the rule you are changing, then change the smallest place that holds it.

Prefer a named constant and a direct branch over a new abstraction. If a function needs a seventh parameter, group the data. Do not raise the lint limits to keep a long function.

Verify the claim you are about to make. Run `ruff check .` and `pytest`. A live model call is a separate command and needs `GOOGLE_API_KEY`. Do not describe a run you did not execute. Do not invent a tool result, a transcript, or an eval score.

When a test fails, fix the code. Do not weaken the assertion to go green. If the same attempt fails twice, stop and look at the design instead of trying a third variation of the same patch.

## Tools

The agent exposes only these tools:

`search_catalog`, `get_product`, `quote_offer`, `list_active_promotions`, `consult_policy`, `verify_customer`, `get_order`, `explain_after_sales`, `check_hours`, `handoff_to_human`.

Tool text is short. Catalog search returns at most five rows and says how many matched. Do not add a search index over the manual. This repo does not use nonce fencing. The tool list is the boundary.

## Data access

Load the CSVs into SQLite once. Every list query has a `LIMIT`. Do not run a query inside a loop. Do not open a network call inside a transaction. Prices are stored as text and parsed as `Decimal`.

`handoff_to_human` is the only write. The row goes to a gitignored local file and has no email or phone. Do not log message bodies. Mask email and phone before anything is shown back.

## Secrets and commits

Commit `.env.example` only. Never commit a key, `secrets.toml`, or a filled `.env`.

Commits are conventional, in English, with a scope: `feat(catalog): filter sellable rows`.

## Smell gate

`ruff check .` is the gate. There is no baseline file and no block disable.

| Rule | Limit |
| --- | --- |
| McCabe C901 | 15 |
| PLR1702 nested blocks | 4 |
| PLR0913 arguments | 6 |
| PLR0915 statements | 50 |
| Also on | E, F, I, PLR5501, PLR1714, SIM114 |

Money, policy, and caps live in `music_store_agent/constants.py`. Tests assert those names.
