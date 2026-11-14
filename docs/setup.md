# Setup

This page is for developers and for whoever hosts the demo. Visitors of the hosted page never need any of it.

## Install

You need git and Python 3.12.

```bash
git clone https://github.com/melocalex/music-store-ai-agent.git && cd music-store-ai-agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

`requirements.txt` pins the three runtime packages for hosting: `pydantic`, `pydantic-ai-slim[google]`, and `streamlit`. `pyproject.toml` adds the dev tools: `pytest`, `ruff`, and `pyyaml`.

## Check it offline

None of these calls a model provider.

```bash
ruff check .                         # the smell gate
pytest                               # unit and agent tests with scripted models
python -m evals.run --stub --runs 1  # 28 scenarios through the real tools and price check
python -m music_store_agent --stub   # the terminal chat with a canned greeting
```

## Model key and model id

A live answer needs a Gemini API key. The app reads it from `GOOGLE_API_KEY`.

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and create an API key for a Google Cloud project.
2. For anything public, use a project with billing and a budget alert. The free tier allows only a small number of requests per day, and Google may use free-tier prompts to improve its products. Check the current limits on the [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) page.
3. Never commit the key. Only `.env.example` and `.streamlit/secrets.toml.example` are tracked, both empty.

`MODEL` picks the model. It takes any Pydantic AI id with the `google:` prefix, and the default is `google:gemini-3.8-flash`. A cheaper choice is `google:gemini-3.5-flash-lite`. An id with another prefix, such as the old `google-gla:`, stops the app at startup with a message, before any customer question.

`.env.example` lists every variable:

```bash
cp .env.example .env      # fill GOOGLE_API_KEY; .env is gitignored
set -a; source .env; set +a
```

The app does not read `.env` by itself, so load it into the shell as above or export the variables another way.

## Chat locally

```bash
python -m music_store_agent        # terminal chat; type "sair" to leave
streamlit run app.py               # the same assistant in the browser
```

| CLI flag | Effect |
|---|---|
| `--once "Qual o preço do C40?"` | asks one question and exits |
| `--phone "(67) 99812-3456"` | the WhatsApp sender. It is one more way to confirm an order, never a replacement for what the customer typed |
| `--today 2026-04-01` | a fixed date chosen by the operator |
| `--real-clock` | the real Campo Grande clock |
| `--stub` | no provider call, only a canned greeting |

## Clock

Business rules read a store clock in `America/Campo_Grande`.

| Mode | How to get it | Label shown |
|---|---|---|
| Pinned (default) | nothing to set. The day after the last order, 2026-03-23 at 10:00 | fixo, um dia após o último pedido |
| Fixed | `--today` or `MUSIC_STORE_TODAY=YYYY-MM-DD` | data definida pelo operador |
| Real | `--real-clock` or `MUSIC_STORE_CLOCK=real` | relógio real |

The daily cap always counts on the real local date, whatever the mode.

`MUSIC_STORE_DATA` points the loader at another folder with the same six CSVs.

## Host the page

Streamlit Community Cloud runs `app.py` with `requirements.txt`.

1. Create the app from the repository, with Python 3.12 and `app.py` as the entry point.
2. In the app settings, add the secret `GOOGLE_API_KEY = "..."`. Locally, the same line goes in `.streamlit/secrets.toml`, which is gitignored. Start from `.streamlit/secrets.toml.example`.
3. Replace the `LIVE_DEMO_URL` placeholder in the README with the app address.

The key stays on the server. The page has no key field. Without a key it says that the site is not configured yet. `.streamlit/config.toml` hides error details from visitors. A Community Cloud app sleeps after a while without visits and wakes on the next one.

## Caps and rate limits

| Limit | Value | Where |
|---|---|---|
| Turns per conversation | 30 | `SESSION_TURN_CAP` |
| Turns per day, all visitors together | 80, on the real local date | `DAILY_TURN_CAP`, counted in `var/daily_turns.json` |
| Characters per message | 600 | `MAX_INPUT_CHARS` |
| Retries of a reply that fails the price check | 2 | `OUTPUT_RETRIES` |
| Retries of a tool call with bad arguments | 1 | `TOOL_RETRIES` |

When the provider refuses, the customer gets a fixed message: one for the daily quota, one for the rate limit, and one for any other provider error. None of them shows a stack trace. Size `DAILY_TURN_CAP` to the budget of the key: a turn takes one model request per round of tool calls, plus one for the reply, plus any retry.

## Live runs

These need the key and spend quota.

```bash
python -m evals.run --runs 3        # writes evals/results/<model>.md
python -m examples.generate         # writes examples/transcripts/*.md
```

Both outputs are meant to be committed. See [evals.md](evals.md) for flags and resuming a stopped run.

## Local files

The app writes two gitignored files under `var/` and nothing else: `handoffs.jsonl`, the handoff log, and `daily_turns.json`, the daily counter. Neither holds an email or a phone.
