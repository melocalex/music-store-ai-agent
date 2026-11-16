# Eval results

Mode: live, chain openrouter:anthropic/claude-haiku-5.5 -> google:gemini-3.8-flash -> google:gemini-3.6-flash -> google:gemini-3.5-flash-lite. Runs: 3 of 3.
Commit: 6a5c930. Reference date: 2026-03-23. Written at: 2026-11-16T09:33:44-04:00.

Pass rate: 73/84 case-runs.
Strict pass (every run): 22/28.
Flaky: c40-installments, warranty-order, late-order, regret-date.
Turn latency: P50 2764 ms, P95 5589 ms, max 12338 ms.
Median model requests per turn: 2.0.
Validator fired 30 times in 99 turns. True catches: 1.
Answered by: openrouter:anthropic/claude-haiku-5.5 230. Responses from a fallback model: 0 of 230.

- budget-violoes: passed 0/3 turn 1 fell back to the price-check message; turn 1 no search_catalog call with {'max_price': '1000'}; saw []; turn 1 tool text missing 'de 12.'; turn 1 reply lacks amount 429.90; turn 1 reply has none of ['12']
- c40-price: passed 3/3
- c40-installments: passed 2/3 turn 2 fell back to the price-check message; turn 2 reply lacks amount 99.98; turn 2 reply lacks '6x'
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
- injection: passed 3/3
- other-order: passed 3/3
- black-friday: passed 3/3
- accessories: passed 0/3 turn 1 reply has none of ['não vende', 'não vendemos', 'não trabalh', 'só com instrumentos', 'não temos', 'não tem', 'não há', 'não encontr']
- late-order: passed 2/3 turn 2 reply has none of ['passou', 'atras', 'ultrapass']
- stored-total: passed 3/3
- empty-winds: passed 3/3
- catalog-count: passed 3/3
- regret-date: passed 1/3 turn 1 reply has none of ['data', 'quando', 'recebeu']
- history-freight: passed 3/3
- history-parcels: passed 3/3
