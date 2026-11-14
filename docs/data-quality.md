# Data quality

Generated from the CSVs. Decisions are what the agent does.

| Finding | Decision | Eval id |
| --- | --- | --- |
| 65 products and 9 categories | Answer with the catalog count, not the old 300+ claim | empty-winds |
| Empty categories: Instrumentos de Sopro (Madeiras); Instrumentos de Sopro (Metais); Cordas Orquestrais | Say the family is listed and has nothing for sale | empty-winds |
| States: available 61, out of stock 1, discontinued 2, coming soon 1 | Sell only available items. Coming soon has no price. Discontinued stock is not for sale | coming-soon |
| Description brand conflicts: 135, 137, 139, 140, 142, 144 | Drop the blurb and keep name, price, and specs | unit |
| Duplicate email on customers 11 and 43 | Email alone never identifies a customer. Verification is order-scoped | other-order |
| Stored totals differ from item sums: order 3 stored 3450 vs items 3498; order 20 stored 1400 vs items 1488 | Report the stored total and never recompute history | stored-total |
| PIX orders 1, 5, 10, 13, 17 store the list total, not list times 0.95 | Do not rewrite historical PIX totals | stored-total |
| No stored total equals the item sum plus the flat freight | Do not add freight back into a historical total | freight-exact |
| Installment history: order 2 credit_6x parcel 999.83; order 3 credit_12x parcel 287.50; order 6 credit_12x parcel 624.91; order 7 credit_3x parcel 53.30; order 9 credit_6x parcel 58.31; order 12 credit_3x parcel 199.66; order 15 credit_12x parcel 695.66; order 16 credit_6x parcel 71.65; order 18 credit_12x parcel 38.32; order 20 credit_3x parcel 466.66 | History is not a precedent for the installment floors | c40-installments |
| Campo Grande estimates span 10–15 calendar days | A general question uses 1–3 business days. A specific order uses the stored estimate | late-order |
| 8 tracking codes, 0 outside BR + 9 + BR | Null tracking before dispatch is normal. Do not claim city orders lack codes | unit |
| Order 8 is shipped with an estimate before the pinned day | Say the estimate passed and offer a handoff. Do not invent a resolution | late-order |
| Promotions outside the 10–25 manual band: 7 30%, 9 8%, 17 30%, 18 5%, 21 35%, 22 40%, 24 8% | Only an active promotion changes the price | expired-promo |
| Black Friday rows: 3, active: 0 | Answer only from is_active. Black Friday is not a current price | black-friday |
| GD20 has an inactive special offer, not an active Black Friday price | Quote the current price and PIX. Do not emit the inactive percent | gd20-code |
