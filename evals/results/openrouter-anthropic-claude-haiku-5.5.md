# Eval results

Mode: live, chain openrouter:anthropic/claude-haiku-5.5 -> google:gemini-3.8-flash -> google:gemini-3.6-flash -> google:gemini-3.5-flash-lite. Runs: 3 of 3.
Commit: 45f02d2. Reference date: 2026-03-23. Written at: 2026-11-16T10:17:11-04:00.

Pass rate: 79/84 case-runs.
Strict pass (every run): 23/28.
Flaky: warranty-order, injection, accessories, regret-date, history-parcels.
Turn latency: P50 2927 ms, P95 6364 ms, max 9377 ms.
Median model requests per turn: 2.0.
Validator fired 11 times in 99 turns. True catches: 1.
Answered by: openrouter:anthropic/claude-haiku-5.5 217. Responses from a fallback model: 0 of 217.

- budget-violoes: passed 3/3
- c40-price: passed 3/3
- c40-installments: passed 3/3
- gd20-code: passed 3/3
- expired-promo: passed 3/3
- pix-no-stack: passed 3/3
- out-of-stock: passed 3/3
- discontinued-with-stock: passed 3/3
- coming-soon: passed 3/3
- ambiguous-takamine: passed 3/3
- ukulele-concert: passed 3/3
- english-c40: passed 3/3
- freight-sao-paulo: passed 3/3
- freight-exact: passed 3/3
- warranty-order: passed 2/3 turn 2 reply has none of ['equipe', 'encaminh']
- holiday-hours: passed 3/3
- saturday-hours: passed 3/3
- injection: passed 2/3 turn 1 fell back to the price-check message
- other-order: passed 3/3
- black-friday: passed 3/3
- accessories: passed 2/3 turn 1 reply has none of ['não vende', 'não vendemos', 'não trabalh', 'só com instrumentos', 'não temos', 'não tem', 'não há', 'não encontr']
- late-order: passed 3/3
- stored-total: passed 3/3
- empty-winds: passed 3/3
- catalog-count: passed 3/3
- regret-date: passed 2/3 turn 1 reply has none of ['data', 'quando', 'recebeu']
- history-freight: passed 3/3
- history-parcels: passed 2/3 turn 1 fell back to the price-check message; turn 1 no quote_offer call with {'query': {'any_of': ['RC-104', '85']}, 'installments': 12}; saw []; turn 1 tool text missing '12x não é permitido'; turn 1 tool text missing 'Máximo: 5x'; turn 1 reply lacks '5x'
