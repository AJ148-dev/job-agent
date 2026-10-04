import logging
import random
import time

import typer

from jobagent.config import Settings, load_profile
from jobagent.llm.ollama import OllamaClient
from jobagent.notify.telegram import TelegramNotifier
from jobagent.pipeline import RunStats, run_pipeline
from jobagent.sources.linkedin import LinkedInSource, NotLoggedInError
from jobagent.storage import Storage

MIN_INTERVAL_HOURS = 6.0  # Protects the LinkedIn account from looking automated.

app = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger("jobagent")


def _setup_logging(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(settings.data_dir / "jobagent.log")],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _linkedin(settings: Settings) -> LinkedInSource:
    return LinkedInSource(settings.browser_profile_dir, settings.data_dir / "debug", settings.browser_channel)


def _run_once(settings: Settings, limit: int, dry_run: bool) -> RunStats:
    profile = load_profile(settings.profile_path)
    llm = OllamaClient(settings.ollama_url, settings.ollama_model)
    llm.check()
    notifier = None if dry_run else TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    # Dry runs use a throwaway DB so they never mark anything as seen or sent.
    store = Storage(":memory:" if dry_run else settings.db_path)
    return run_pipeline([_linkedin(settings)], store, llm, profile, notifier, limit)


@app.command()
def login() -> None:
    """Open the browser so you can log in to LinkedIn once; the session is saved."""
    settings = Settings()
    _setup_logging(settings)
    try:
        _linkedin(settings).login()
    except NotLoggedInError as e:
        typer.echo(f"Login failed: {e}", err=True)
        raise typer.Exit(1)
    typer.echo("Session saved.")


@app.command()
def run(
    limit: int = typer.Option(None, help="Max posts to collect (default MAX_POSTS_PER_RUN)."),
    dry_run: bool = typer.Option(False, help="Analyse and log, but store nothing and send nothing."),
) -> None:
    """Run one pass: collect feed posts, analyse, and send matches to Telegram."""
    settings = Settings()
    _setup_logging(settings)
    stats = _run_once(settings, limit or settings.max_posts_per_run, dry_run)
    typer.echo(stats)


@app.command()
def schedule(
    every_hours: float = typer.Option(8.0, help=f"Hours between runs (minimum {MIN_INTERVAL_HOURS:g})."),
) -> None:
    """Run forever, one pass every N hours (with +-10% jitter)."""
    if every_hours < MIN_INTERVAL_HOURS:
        raise typer.BadParameter(f"must be at least {MIN_INTERVAL_HOURS:g} to protect your LinkedIn account")
    settings = Settings()
    _setup_logging(settings)
    while True:
        try:
            _run_once(settings, settings.max_posts_per_run, dry_run=False)
        except Exception:
            log.exception("Run failed")
        delay = every_hours * 3600 * random.uniform(0.9, 1.1)
        log.info("Next run in %.1f hours", delay / 3600)
        time.sleep(delay)


@app.command("test-telegram")
def test_telegram() -> None:
    """Send a test message to check the Telegram bot setup."""
    settings = Settings()
    TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id).send("jobagent: Telegram is set up.")
    typer.echo("Sent.")


@app.command()
def stats() -> None:
    """Show counts of processed posts and jobs."""
    for key, value in Storage(Settings().db_path).stats().items():
        typer.echo(f"{key}: {value}")
