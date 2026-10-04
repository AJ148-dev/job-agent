# jobagent

Personal job-finding agent. Scrolls your LinkedIn feed in your own logged-in Chrome profile,
keeps posts that are real hiring posts, extracts the job with a local LLM (Ollama), scores it
against your resume, and sends good matches to Telegram. Every post is stored in SQLite, so you
never get the same job twice (reposts with the same text are caught too).

Everything runs locally and costs nothing.

## Setup

```bash
uv sync
ollama pull qwen2.5:7b            # or set OLLAMA_MODEL to another pulled model
cp .env.example .env              # fill in Telegram values (below)
cp profile.example.yaml profile.yaml   # edit; put your resume next to it
uv run jobagent login             # log in to LinkedIn once in the opened Chrome window
uv run jobagent test-telegram
```

Telegram: message @BotFather, `/newbot`, copy the token into `TELEGRAM_BOT_TOKEN`. Send any
message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy
`result[0].message.chat.id` into `TELEGRAM_CHAT_ID`.

Run all commands from the project directory (paths in `.env` are relative to it).

## Usage

```bash
uv run jobagent run --dry-run --limit 20   # analyse and log only; stores and sends nothing
uv run jobagent run                        # one real pass
uv run jobagent schedule                   # a pass every 8h (+-10%); minimum 6h
uv run jobagent stats
```

Logs go to the terminal and `data/jobagent.log`. A Chrome window opens during each pass; leave it alone
until it closes. The Mac must be awake for scheduled runs.

## How a post is processed

1. Skip if already seen (same post ID, or same normalised text).
2. Drop if it contains an `exclude_keywords` entry, or has no job-related words (no LLM call).
3. LLM: is this someone hiring? If yes, extract role, company, location, experience, skills, links.
4. LLM: score 0-100 against your resume and preferences.
5. Rule penalties: experience far above `max_years` (-25), location outside `locations` and not remote (-20),
   none of `must_have_skills` listed (-15).
6. Jobs with score >= `min_score` are sent. Failed sends are retried on the next run.

## LinkedIn account safety

Automating LinkedIn is against its Terms of Service. To keep risk low this tool uses your real Chrome
(not headless), random human-like pauses, at most `MAX_POSTS_PER_RUN` posts (default 60), and refuses
schedules under 6 hours. Avoid running `jobagent run` many times a day by hand.

## When LinkedIn changes its page

All selectors are in `src/jobagent/sources/linkedin_parse.py`. If a run parses zero posts, the page is
saved to `data/debug/linkedin_feed.html`; update the selectors against it and refresh
`tests/fixtures/linkedin_feed.html`.

## Adding a source

Implement the `Source` protocol in `src/jobagent/sources/base.py` (`name` and `fetch(limit) -> list[RawPost]`)
and add it to the list passed to `run_pipeline` in `cli.py`.

## Tests

```bash
uv run pytest
```
