# Eval results

Mode: live, chain openrouter:anthropic/claude-haiku-5.5 -> google:gemini-3.8-flash -> google:gemini-3.6-flash -> google:gemini-3.5-flash-lite. Runs: 3 of 3.
Commit: 7411729. Reference date: 2026-03-23. Written at: 2026-11-16T10:06:47-04:00.

Pass rate: 69/84 case-runs.
Strict pass (every run): 20/28.
Flaky: c40-installments, coming-soon, warranty-order, accessories, late-order, history-parcels.
Turn latency: P50 2886 ms, P95 6124 ms, max 11167 ms.
Median model requests per turn: 2.0.
Validator fired 26 times in 99 turns. True catches: 0.
Answered by: openrouter:anthropic/claude-haiku-5.5 214. Responses from a fallback model: 0 of 214.

- budget-violoes: passed 0/3 turn 1 reply carries amount 749.00; turn 1 reply has none of ['12']
- c40-price: passed 3/3
- c40-installments: passed 1/3 turn 2 fell back to the price-check message; turn 2 reply lacks amount 99.98; turn 2 reply lacks '6x'
- gd20-code: passed 3/3
- expired-promo: passed 3/3
- pix-no-stack: passed 3/3
- out-of-stock: passed 3/3
- discontinued-with-stock: passed 3/3
- coming-soon: passed 2/3 turn 1 fell back to the price-check message; turn 1 no get_product call with {'query': 'KA-ABP-CTG'}; saw []; turn 1 tool text missing 'lançamento'; turn 1 tool text missing 'não prometo preço'; turn 1 reply has none of ['lançamento', 'ainda não', 'em breve']
- ambiguous-takamine: passed 3/3
- ukulele-concert: passed 3/3
- english-c40: passed 3/3
- freight-sao-paulo: passed 0/3 turn 1 no quote_offer call with {'query': 'C40', 'destination': 'other'}; saw ["get_product {'query': 'Yamaha C40'}", "consult_policy {'sections': ['frete']}", "quote_offer {'query': '81', 'destination': 'other'}"]
- freight-exact: passed 3/3
- warranty-order: passed 1/3 turn 2 reply has none of ['equipe', 'encaminh']
- holiday-hours: passed 3/3
- saturday-hours: passed 3/3
- injection: passed 3/3
- other-order: passed 3/3
- black-friday: passed 3/3
- accessories: passed 1/3 turn 1 reply has none of ['não vende', 'não vendemos', 'não trabalh', 'só com instrumentos', 'não temos', 'não tem', 'não há', 'não encontr']
- late-order: passed 2/3 turn 2 reply has none of ['passou', 'atras', 'ultrapass']
- stored-total: passed 3/3
- empty-winds: passed 3/3
- catalog-count: passed 3/3
- regret-date: passed 3/3
- history-freight: passed 3/3
- history-parcels: passed 2/3 turn 1 fell back to the price-check message; turn 1 no quote_offer call with {'query': {'any_of': ['RC-104', '85']}, 'installments': 12}; saw []; turn 1 tool text missing '12x não é permitido'; turn 1 tool text missing 'Máximo: 5x'; turn 1 reply lacks '5x'
