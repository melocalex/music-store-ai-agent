# Evals

`evals/scenarios.yaml` holds 28 conversations, 33 turns in all. `evals/run.py` plays them, and `evals/score.py` checks facts on each turn.

## Run

```bash
python -m evals.run --stub --runs 1                 # offline, no key
python -m evals.run --runs 3                        # live, with the model in MODEL
python -m evals.run --runs 3 --model google:gemini-3.5-flash-lite
python -m evals.run --runs 3 --from late-order      # resume a stopped live run
```

A live run needs the key described in [setup.md](setup.md).

| Flag | Meaning |
|---|---|
| `--stub` | scripted model turns, no provider call |
| `--runs N` | passes over the file. Default 3. Several passes expose flaky cases |
| `--model ID` | the primary, a `google:` model id. Default: `MODEL`, then `google:gemini-3.8-flash`. The fallback comes from `MODEL_FALLBACK` |
| `--from ID` | start at this case, after a stopped run |

| Exit code | Meaning |
|---|---|
| 0 | every case passed |
| 1 | at least one case failed |
| 2 | no key for a live run |
| 3 | the provider kept refusing, both models failed, or a turn passed 45 seconds; the run stopped and the partial report was saved |

## What each mode proves

**Stub.** Each turn's `stub` block lists the tool calls and the reply a model would give. The runner sends them through the real tools, the real ledger, and the real price check, quoting amounts the way the prompt asks. The scorer then checks the `expect` block, which the stub never reads. A stub pass shows that the tools return the right facts and that the guard accepts a grounded reply. Tests in `tests/test_evals.py` show the other side: a stub reply with another product's price falls back and fails, and a wrong tool argument fails. The stub is not a model score.

**Live.** The same prompts go to Gemini, and the same `expect` checks score the replies. A live run uses the same fallback, per-request deadline, and 45-second turn budget as the app. A warning on stderr names every response the fallback gave, so a score can be checked against the model named in the report file. Keywords are folded for case and accents, arguments are compared by meaning (`"1000"` matches `"1.000,00"`, `"C40"` matches `"Yamaha C40"`, `"13/06"` matches `"2026-06-13"`), and amounts are parsed, so a reply can use its own words.

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
| `tools` | each listed tool ran at least once with these key arguments |
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
| Median turn latency | wall time per turn, model and tools included |
| Median model requests per turn | model responses per turn, tool rounds included |
| Validator fired / true catches | replies the price check rejected, and how many carried an amount no tool returned at all |

Then one line per case with its failures.

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
