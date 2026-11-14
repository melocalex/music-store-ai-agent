# Data quality

Generated from the CSVs by `python -m music_store_agent.quality`. Each finding is computed from the data. Decisions are what the agent does. The eval id names the scenario in `evals/scenarios.yaml` that covers it, or `unit` for a pytest check.

| Finding | Decision | Eval id |
| --- | --- | --- |
| 65 products, 61 for sale, 9 categories | Answer with the catalog count, not the manual's 300+ claim | catalog-count |
| Categories without products: Instrumentos de Sopro (Madeiras); Instrumentos de Sopro (Metais); Cordas Orquestrais | Say the family is listed and has nothing for sale | empty-winds |
| States: available 61, out of stock 1, discontinued 2, coming soon 1, unknown status 0 | Sell only available items. Coming soon, discontinued, and an unknown status have no price | coming-soon |
| Description brand conflicts: 135, 137, 139, 140, 142, 144 | Drop the blurb and keep name, price, and specs | unit |
| Customers sharing an email: 11 and 43 | A shared email needs the order's phone. Verification is order-scoped | unit |
| Stored totals that differ from the item sums: order 3 stored 3450 vs items 3498; order 20 stored 1400 vs items 1488 | Report the stored total and never recompute history | stored-total |
| PIX orders stored at the item sum: 1, 5, 10, 13, 17. Stored at the item sum minus 5%: none | Do not rewrite historical PIX totals | stored-total |
| Stored totals equal to the item sum plus the R$ 35,00 freight: none | Do not add freight back into a historical total | history-freight |
| Installment history: order 2 credit_6x parcel 999.83; order 3 credit_12x parcel 287.50; order 6 credit_12x parcel 624.91; order 7 credit_3x parcel 53.30; order 9 credit_6x parcel 58.31, below today's floor; order 12 credit_3x parcel 199.66; order 15 credit_12x parcel 695.66; order 16 credit_6x parcel 71.65, below today's floor; order 18 credit_12x parcel 38.32, below today's floor; order 20 credit_3x parcel 466.66 | History is not a precedent for the installment floors | history-parcels |
| Stored estimates span 10–15 calendar days from the order | A general question uses 1–3 business days. A specific order uses its stored estimate | late-order |
| 8 tracking codes, 0 outside BR + 9 + BR | Null tracking before dispatch is normal. Do not claim an order lacks a code | unit |
| Open orders past their estimate on 2026-03-23: order 8 (shipped, estimate 2026-02-28) | Say the estimate passed and offer a handoff. Do not invent a resolution | late-order |
| Promotions outside their campaign band in the manual: 1 Black Friday 10%, 17 Aniversário da Loja 30%. Campaigns with no band: Desconto Exclusivo, Liquidação de Inverno, Oferta Especial, Promoção de Páscoa, Queima de Estoque, Semana do Músico | Only an active promotion changes the price | expired-promo |
| Black Friday rows: 3, active: 0 | Answer only from is_active. Black Friday is not a current price | black-friday |
| Takamine GD20 Dreadnought Natural: active promotion none; inactive Oferta Especial 12% | Quote the current price and PIX. Do not emit the inactive percent | gd20-code |
