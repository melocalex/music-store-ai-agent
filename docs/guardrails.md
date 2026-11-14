# Guardrails

Every value below is a named constant in `music_store_agent/constants.py`, and a test pins it. The source is the policy PDF in `data/store_policies.pdf` unless the row says otherwise.

## Prices

| Rule | Detail |
|---|---|
| Prices come from tools | The prompt asks for it, and the price check enforces it on every reply |
| Common money forms count | `R$ 1.749,00`, `R$ 1.749`, `1.749,00`, `1,749.00`, `BRL 599,90`, `599,90 reais`, `99,98`, `12x de 50`, `2,2 mil`, `R$ 2,2 mil`, `600 conto`, and "quinhentos e noventa e nove reais e noventa centavos" are read as amounts. Dates, phones, order numbers, counts, measures such as `3,50 kg`, versions such as `versão 2.10`, and a dotted decimal with no currency such as `9.00` are not |
| Product values use the product id | price, PIX, line total, and installment |
| Rule values use a null id | freight, a floor, a threshold, a stored order total, each tagged with its kind. The customer's budget, echoed by the search, is kept apart and is never a store value |
| A price stays with its product | a sentence that names catalog products may only carry prices quoted for one of them |
| A price follows its own model | when a singular price verb (`custa`, `sai`, `fica`, `vale`, `por`) links an amount to the model right before it, the amount must be that model's. "O C40 custa R$ 849,00 e o C70 custa R$ 599,90" is refused; "custam R$ 599,90 e R$ 849,00, respectivamente" is not checked this way |
| A rule value keeps its kind | in a sentence that names a product, a null-id amount needs a word of its kind: `frete` for freight, `mínima` for a floor, `acima` for a threshold, `total` or `pedido` for an order total, `até` or `teto` for the budget. "O Shelby SU-21S custa R$ 35,00" is refused; "o frete do SU-21S é R$ 35,00" passes |
| Percents come from tools | a percent in the reply must appear in tool text |
| Failure | two retries, then a short message with no amount and a `price_check` handoff |

## What is for sale

| State | Rule |
|---|---|
| Available | `active` and stock above zero. The only state with a price |
| Out of stock | `active` with no stock. No price. Similar models are offered |
| Discontinued | not for sale, even with stock left. No price. Similar models are offered |
| Coming soon | not for sale and no price promised |
| Unknown status | not for sale. The quality report counts it |

A list of several matches shows each model's state, and prices only the available ones.

## Promotions

- Only a promotion with `is_active = 1` changes the price. With two active, the larger percent wins.
- A promotional price is shown with the original price and the percent, as the manual asks.
- Promotions do not stack, and PIX does not apply on top of one.
- Black Friday status comes from the promotion rows, never from a fixed sentence.

## Payment

| Rule | Value |
|---|---|
| PIX | 5% off the list price, rounded half up to the cent |
| Credit | 1x to 12x without interest. 1x is cash |
| 2x and 3x | parcel of at least R$ 50,00 |
| 4x to 6x | parcel of at least R$ 80,00 |
| 7x to 12x | parcel of at least R$ 100,00 |
| Floor test | on the exact parcel, `total >= floor x n`. R$ 479,97 in 6x is 79,995 a parcel, so it is refused |
| Parcels | rounded down to the cent, with the leftover cents in the first one: the C40 in 6x is R$ 100,00 plus five of R$ 99,98 |
| PIX plus card | only above R$ 2.000,00. Exactly R$ 2.000,00 does not qualify |
| Quantity | 1 to 10 units, and never more than the stock |

## Freight

| Rule | Value |
|---|---|
| Campo Grande, from R$ 500,00 | free, including exactly R$ 500,00 |
| Campo Grande, below R$ 500,00 | R$ 35,00 |
| Threshold base | the item value before the PIX discount. The manual does not say; paying by PIX never adds freight |
| Other cities | not calculated. The team quotes PAC, SEDEX, or Jadlog |
| Delivery time | 1 to 3 business days for a general question. A specific order uses its stored estimate |

## Orders and identity

- An order opens only with its id plus the full email or the full phone of that order's customer. Last digits are not enough. Phones match with or without +55, with a trunk zero, and with area code 55.
- An email shared by two customers needs the order's phone too.
- The CLI sender phone is one more way to match, never a replacement for what the customer typed.
- An unknown order and a wrong contact get the same message.
- Three failed attempts per session lock verification and hand off. A later success does not reset the count.
- Order tools read only the confirmed customer's orders.
- Stored totals, old parcels, and old PIX totals are reported as recorded, never recomputed.

## After-sales

| Window | Counted from | What Aria says |
|---|---|---|
| Defect exchange, 30 days | purchase | inside or outside, by the date |
| Legal warranty, 90 days | receipt | open while the purchase itself is within 90 days. Otherwise it asks for the receipt date |
| Regret, 7 days, online only | receipt | the same lower-bound reading |
| Preference exchange, 7 days | not stated in the manual | open within 7 days of purchase under either reading. Otherwise it asks for the receipt date |
| Factory warranty | the certificate | 6 months to 2 years, by manufacturer |

An order that has not been delivered has not started the receipt windows. Aria never approves an exchange. It hands off only when the customer asks to open one.

## Hours

- Monday to Friday 09:00 to 18:00, Saturday 09:00 to 13:00, closed on Sunday and fixed holidays. Opening and closing minutes count as open.
- Fixed holidays include Santo Antônio (13/06) in Campo Grande and the national Dia Nacional de Zumbi e da Consciência Negra (20/11).
- Carnival, Good Friday, and Corpus Christi move every year. Their dates are computed from Easter. Good Friday closes the store. Carnival (Monday and Tuesday) and Corpus Christi have no set hours: the hours answer flags them, and Aria does not confirm hours and hands off.
- For today, the answer uses the current time. For another day, it gives that day's hours. A DD/MM date means its next occurrence.

## Privacy

- Email and phone are masked in every shown message, in tool-call lines on the page, and in handoff rows.
- Handoff rows hold a fixed reason, a capped summary, the conversation's protocol, the confirmed customer and order ids when there are any, the store-clock time, and the real time the row was written. Message bodies are not logged.
- The model never receives a customer's email or phone from a tool.

## Scope and handoffs

A rule can be explained. A purchase, cancellation, address change, return, complaint, discount request, or freight to another city is handed off with a reason from a fixed list. The reply says the team answers within 24 business hours and, when the store is closed, when it reopens. It also says how the team gets back: through the contact of a confirmed order, or, for a visitor who confirmed none, on WhatsApp with the conversation's protocol. The safe-price message carries the same line.

## Caps and failures

| Situation | What the customer sees |
|---|---|
| 30 turns in one conversation | a message to start a new one |
| 80 turns in one day, all visitors | a message to come back tomorrow or use WhatsApp |
| More than 600 characters | a request to shorten the message |
| Provider quota or rate limit | a message naming the limit, with no promise of a minute |
| Any other provider error | a generic message, never a stack trace |

## Conflicts in the manual

| Where | The PDF says | Aria does |
|---|---|---|
| Catalog size | more than 300 instruments; three families are empty | uses the catalog count |
| Phones | the cover lists one number as phone and WhatsApp | WhatsApp is (67) 3321-4500, the landline is (67) 3341-4444 |
| Email | an accented spelling in the company table | `contato@emporiodamusica.com.br` |
| Credit | "minimum parcel R$ 100,00" in the table, tiers in the rules | the tiers |
| 2x and 3x | "no minimum parcel, except below R$ 50,00" | R$ 50,00 per parcel, in line with the other tiers |
| Free freight | "above R$ 500,00", and the flat fee "below R$ 500,00" | exactly R$ 500,00 ships free |
| Preference exchange | "up to 7 days" with no start | the lower-bound reading above |
| Delivery time | 1 to 3 business days; stored estimates are 10 to 15 calendar days | policy for a general question, the stored date for an order |
| Partner stores | suggest one when possible | there is no list, so none is named |
