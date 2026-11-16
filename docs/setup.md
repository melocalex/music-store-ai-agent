# Setup

This page is for developers and for whoever hosts the demo. Visitors of the hosted page never need any of it.

## Install

You need git and Python 3.12.

```bash
git clone https://github.com/melocalex/music-store-ai-agent.git && cd music-store-ai-agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

`requirements.txt` pins the three runtime packages for hosting: `pydantic`, `pydantic-ai-slim[google]`, and `streamlit`. `requirements-dev.txt` pins the dev tools: `pytest`, `pyyaml`, and `ruff`. `pyproject.toml` keeps compatible ranges for a local install.

## Check it offline

None of these calls a model provider.

```bash
ruff check .                         # the smell gate
ruff format --check .                # formatting
pytest                               # unit and agent tests with scripted models
python -m evals.run --stub --runs 1  # 28 scenarios through the real tools and price check
python -m music_store_agent --stub   # the terminal chat with a canned greeting
```

## Model key and models

A live answer needs a Gemini API key. The app reads it from `GOOGLE_API_KEY`.

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and create an API key for a Google Cloud project.
2. For anything public, use a project with billing and a budget alert. The free tier allows only a small number of requests per day, and Google may use free-tier prompts to improve its products. Check the current limits on the [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) page.
3. Never commit the key. Only `.env.example` and `.streamlit/secrets.toml.example` are tracked, both empty.

| Variable | Default | Sets |
|---|---|---|
| `MODEL` | `google:gemini-3.8-flash` | the primary model |
| `MODEL_FALLBACK` | `google:gemini-3.6-flash` | the backup model |
| `MODEL_RESERVE` | `google:gemini-3.5-flash-lite` | the last model, a lite one with a larger daily allowance |
| `MODEL_TIMEOUT_SECONDS` | `15` | seconds each model gets for one request, above 0 and at most 15 |
| `MODEL_BREAKER_SECONDS` | `300` | seconds a model is skipped after an outage, 0 or more. `0` turns the breaker off |

The model variables take any Pydantic AI id with the `google:` prefix. A cheaper choice is `google:gemini-3.5-flash-lite`. An id with another prefix, such as the old `google-gla:`, or a timeout or breaker window outside its range, stops the app at startup with a message, before any customer question.

### Fallback, timeouts, and the breaker

Every model request goes to the primary first, unless the breaker described below is open. A 503 or another 5xx, a connection failure, or a request past `MODEL_TIMEOUT_SECONDS` sends that same request to the fallback, with a fresh timeout. A rate limit or a quota on one model also moves the request on, because the next model has its own allowance. A bad key or an unknown model stays where it failed and gets its own message, because the next model would fail the same way or hide the cause.

The timeout is enforced twice. The HTTP client gets it as its timeout for each attempt, and each request also runs under a hard deadline: when `MODEL_TIMEOUT_SECONDS` pass, the app stops waiting, cancels the request, and leaves it behind instead of waiting for it to wind down. A socket that ignores the cancel therefore cannot hold the turn. The miss counts as a timeout, so the fallback runs.

After an outage, a circuit breaker skips that model for `MODEL_BREAKER_SECONDS`, five minutes by default. After a per-minute rate limit it skips the model for one minute, and after a daily quota for one hour. While it is open, every request goes straight to the next model, which then has the full 15 seconds and the full turn budget. That includes the later tool rounds of the same turn and other visitors' turns. After the window, the next request tries the primary again: a success closes the breaker, and another outage starts a new window. A rejected request never opens it. The breaker lives in memory, so a restart closes it, and each process (the hosted page, a terminal chat, an eval run) has its own.

The provider SDK does not retry by itself, so moving to the next model is the only retry. The whole turn, tool rounds and price-check retries included, stops after 45 seconds (`TURN_TIMEOUT_SECONDS`). Three 15-second attempts fit inside that budget, which is why the timeout cannot go above 15. If every model fails, or the turn runs out of time, the customer gets a fixed message: the rate-limit one if every model hit a limit, the quota one if every model spent its day, otherwise the provider one.

When the fallback answers, the app logs a warning such as `fallback model google:gemini-3.6-flash answered after gemini-3.8-flash failed with ModelUnavailableError`. Opening the breaker and each skip also log a warning, such as `model google:gemini-3.8-flash skipped: breaker open for 287 more seconds`. Every failure also logs one warning with its type, HTTP status, and model, such as `provider error: ModelAuthenticationError status=401 model=gemini-3.8-flash` for a bad key, `turn failed: UnexpectedModelBehavior` for a reply that broke the schema, and `daily cap of 80 turns reached`. These lines go to stderr: the terminal for the CLI, the server log for the page. Answers from the primary are logged at info level, which shows only when logging is set to info. The log holds model ids and error types, never the key or the provider's response body.

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

Without `GOOGLE_API_KEY`, the terminal chat prints one line that suggests `--stub` and exits with code 2. A model id, timeout, or breaker window it cannot use prints one line and exits with code 3.

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
| Seconds per model request, HTTP timeout and hard deadline | 15 | `MODEL_TIMEOUT_SECONDS`, default `DEFAULT_REQUEST_TIMEOUT_SECONDS` |
| Seconds per turn | 45 | `TURN_TIMEOUT_SECONDS` |
| Provider SDK retries | 0 | `PROVIDER_SDK_RETRIES`. The next model is the only retry |
| Seconds a model is skipped after an outage | 300 | `MODEL_BREAKER_SECONDS`, default `DEFAULT_BREAKER_SECONDS` |
| Seconds a model is skipped after a rate limit, or a daily quota | 60, or 3600 | `RATE_LIMIT_BREAKER_SECONDS`, `QUOTA_BREAKER_SECONDS` |

When the provider refuses, the customer gets a fixed message: one for the daily quota, one for the rate limit, and one for any other provider error the fallback could not absorb or a turn past 45 seconds. None of them shows a stack trace. Size `DAILY_TURN_CAP` to the budget of the key: a turn takes one model request per round of tool calls, plus one for the reply, plus any retry, and a request that falls over costs one request on each model it tries. A turn that no model answered is given back to the daily cap. A free key allows only about 20 requests a day on each flash model, so the lite reserve carries the rest of the day, and a project with billing removes the limit. While the breaker is open, a request costs one on the fallback only.

## Live runs

These need the key and spend quota.

```bash
python -m evals.run --runs 3        # writes evals/results/<model>.md
python -m examples.generate         # writes examples/transcripts/*.md
```

Both outputs are meant to be committed. See [evals.md](evals.md) for flags and resuming a stopped run.

## Local files

The app writes two gitignored files under `var/` and nothing else: `handoffs.jsonl`, the handoff log, and `daily_turns.json`, the daily counter. Neither holds an email or a phone.
