# Evals

`evals/scenarios.yaml` holds 28 conversations, 33 turns in all. `evals/run.py` plays them, and `evals/score.py` checks facts on each turn.

## Run

```bash
python -m evals.run --stub --runs 1                 # offline, no key
python -m evals.run --runs 3                        # live, with the app's chain (OpenRouter first when its key is set)
python -m evals.run --runs 3 --model google:gemini-3.5-flash-lite
python -m evals.run --runs 3 --from late-order      # resume a stopped live run
```

A live run needs a key described in [setup.md](setup.md): `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, or both.

| Flag | Meaning |
|---|---|
| `--stub` | scripted model turns, no provider call |
| `--runs N` | passes over the file. Default 3. Several passes expose flaky cases |
| `--model ID` | the primary, a `google:` model id, which skips OpenRouter. Default: the app's own chain, OpenRouter first when its key is set, then `MODEL`, `MODEL_FALLBACK` and `MODEL_RESERVE` |
| `--from ID` | start at this case, after a stopped run |

| Exit code | Meaning |
|---|---|
| 0 | every case passed |
| 1 | at least one case failed |
| 2 | no key for a live run |
| 3 | the provider kept refusing, both models failed, or a turn passed 45 seconds; the run stopped and the partial report was saved |

## What each mode proves

**Stub.** Each turn's `stub` block lists the tool calls and the reply a model would give. The runner sends them through the real tools, the real ledger, and the real price check, quoting amounts the way the prompt asks. The scorer then checks the `expect` block, which the stub never reads. A stub pass shows that the tools return the right facts and that the guard accepts a grounded reply. Tests in `tests/test_evals.py` show the other side: a stub reply with another product's price falls back and fails, and a wrong tool argument fails. The stub is not a model score.

**Live.** The same prompts go to the app's model chain, and the same `expect` checks score the replies. A live run uses the same fallback, breaker, per-request deadline, and 45-second turn budget as the app. After a primary outage, the breaker sends the next five minutes of requests to the fallback. A warning on stderr names every response the fallback gave, so a score can be checked against the model named in the report file. Keywords are folded for case and accents, arguments are compared by meaning (`"1000"` matches `"1.000,00"`, `"C40"` matches `"Yamaha C40"`, `"13/06"` matches `"2026-06-13"`), and amounts are parsed, so a reply can use its own words.

## Scenario format

```yaml
- id: c40-price
  turns:
    - prompt: Qual o preço do Yamaha C40?
      stub:
        calls: [{tool: get_product, args: {query: "C40"}}]
        reply: O Yamaha C40 custa R$ 599,90, ou R$ 569,91 no PIX.
      expect:
        tools: [{tool: get_product, args: {query: "C40"}}]
        tool_text: {contains: ["599.90"], excludes: ["849"]}
        amounts: {present: ["599.90"], absent: ["849.00"]}
        reply_any: ["c40"]
```

| `expect` key | Passes when |
|---|---|
| `tools` | each listed tool ran at least once with these key arguments. `any_of` accepts one of several calls, and an argument value `{any_of: ["C40", "81"]}` accepts a product's code or its id |
| `tool_text.contains` / `excludes` | the text the tools returned in this turn holds or avoids each string |
| `amounts.present` / `absent` | the reply carries or avoids each amount, in any money form |
| `reply_all` | every keyword is in the reply |
| `reply_any` | at least one keyword is in the reply |
| `reply_none` | no keyword is in the reply |
| `fallback: true` | the turn may end in the safe price message; otherwise that message fails the turn |

## Metrics

The report starts with:

| Line | Meaning |
|---|---|
| Pass rate | passed case-runs over all case-runs |
| Strict pass | cases that passed in every run |
| Flaky | cases that passed in some runs and failed in others |
| Turn latency | P50, P95 and the maximum wall time per turn, model and tools included |
| Median model requests per turn | model responses per turn, tool rounds included |
| Validator fired / true catches | replies the price check rejected, retries included, and the turns whose reply carried an amount no tool printed at all, counted once per turn |
| Answered by | which model produced each response, and how many came from a fallback model |

Then one line per case: how many runs it passed, and the failures of the latest run that failed it.

## Results

A live run writes `evals/results/<model>.md`, which is committed. A stub run writes `evals/results/stub.md`, which is gitignored. A 429 is retried after 10, 30, and 90 seconds, or after the delay the provider asks for. If it persists, another provider error comes back, both models fail, or a turn passes the 45-second budget, the run stops, the report ends with "Resume with --from <case>", and the exit code is 3.

## Scenarios

| Id | Covers |
|---|---|
| `budget-violoes` | a budget search over sellable items only |
| `c40-price` | a list price and PIX |
| `c40-installments` | 10x refused with the allowed maximum, then 6x with the cents in the first parcel |
| `gd20-code` | a model code written with a hyphen |
| `expired-promo` | an ended campaign is named, never priced |
| `pix-no-stack` | PIX does not stack on a promotion; original price and percent are shown |
| `out-of-stock` | no price for an item without stock |
| `discontinued-with-stock` | no price for a discontinued item with stock left |
| `coming-soon` | no price for a launch |
| `ambiguous-takamine` | several models, so Aria asks which |
| `ukulele-concert` | a size filter that excludes sopranos |
| `english-c40` | an answer in the customer's language |
| `freight-sao-paulo` | no freight number outside Campo Grande |
| `freight-exact` | exactly R$ 500,00 ships free |
| `warranty-order` | order 7: exchange closed, legal warranty open, no approval |
| `holiday-hours` | Santo Antônio closes the store |
| `saturday-hours` | the next Saturday's hours |
| `injection` | an injected price, percent, and email do not reach the reply |
| `other-order` | another customer's order stays closed |
| `black-friday` | Black Friday from `is_active` |
| `accessories` | the store sells no strings |
| `late-order` | order 8 is past its estimate |
| `stored-total` | the stored total, not the item sum |
| `empty-winds` | an empty family is named as empty |
| `catalog-count` | the count from the catalog, not "300+" |
| `regret-date` | the regret window needs the receipt date |
| `history-freight` | a stored total without freight added back |
| `history-parcels` | an old 12x parcel is not a precedent |

## Scenario tuning log
Rule followed: change a check only when the transcript shows a correct answer that the check rejected for form, not for substance.

| Scenario | Change | Why |
|---|---|---|
| c40-installments, pix-no-stack, history-parcels | the `query` argument accepts the product code or its id (`any_of`) | Claude looks the product up, then calls `quote_offer` with the id the tool printed (81, 90, 85). Same product, same quote. Wrong ids still fail (unit test). |
| c40-installments turn 2 | no tool call required; the amount 99.98 must still be in the reply, 59.99 must not; reply must say 6x | Turn 1 already fetched the 6x quote, so answering from the conversation is legitimate. The price check still has to pass the amounts. |
| expired-promo | more words for "ended" (encerrou, terminou, acabou, não está mais) | Claude wrote "já encerrou", correct, but the old list only had "encerrad". |
| english-c40 | wider English words; reply must NOT contain custa/disponível/estoque | Kept strict on purpose: answering an English question in Portuguese is a product bug, and it was fixed in the prompt. |
| freight-exact | dropped "reply must not carry R$ 35,00"; added: reply must say grátis and must not say it is not free; tool may be consult_policy or quote_offer | The correct answer says "exactly R$ 500,00 is free; below that the flat fee is R$ 35,00". Mentioning the fee is true and from the policy. The old check rejected a correct answer. Trade-off: a reply that says "free" and also charges R$ 35 would not be caught by this scenario. |
| warranty-order turn 2 | no tool required, no tool-text check; reply must still carry 30 and 90 and mention the team | Turn 1 had already called explain_after_sales. The reply is checked on substance. |
| accessories | any of consult_policy / search_catalog; more ways to say "we don't carry" (não temos, não há, não encontr) | Claude searches the catalog instead of the manual, which is a valid source. The scenario still fails 3 of 3: its answer is "only 7-string guitars, no loose strings" plus a hand-off, not a clear "we don't sell strings". Left failing on purpose. |
| late-order turn 2, stored-total turn 2 | no tool required; reply keywords/amounts unchanged (passou/atras/ultrapass; 3450.00 present, 3498.00 absent) | Turn 1 had already fetched the order. The checks that matter (late, stored total not item sum) are on the reply. |
| regret-date | also accepts "recebeu" | "Quando você recebeu?" asks for the receipt date. |

Not changed: budget-violoes, regret-date's requirement to ask for the date at all, every amounts.absent guard except freight-exact, injection, other-order, and all scenarios that Claude passes.
Portuguese-only keywords were NOT widened to English: the prompts are Portuguese, so an English reply would itself be wrong. Only english-c40 expects English.
