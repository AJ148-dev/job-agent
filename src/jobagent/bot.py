"""Telegram command listener: send /run to the bot to start a pass on demand."""

import logging
import time
from collections.abc import Callable
from html import escape

from jobagent.notify.telegram import TelegramNotifier
from jobagent.pipeline import RunStats

log = logging.getLogger(__name__)

COMMANDS = {"run": "Check my LinkedIn feed for new jobs now"}
HELP = "Send /run to check your LinkedIn feed for new jobs."
RETRY_DELAY_S = 5


def summarize(stats: RunStats) -> str:
    if stats.fetched == 0:
        return "Run finished but no posts were read. LinkedIn may need <code>jobagent login</code>; see data/jobagent.log."
    found = f"{stats.notified} new job{'s' if stats.notified != 1 else ''} sent above" if stats.notified \
        else "no new jobs"
    text = f"Done: read {stats.fetched} posts, {found}."
    if stats.errors:
        text += f" ({stats.errors} errors, see data/jobagent.log)"
    return text


class Bot:
    def __init__(self, telegram: TelegramNotifier, run: Callable[[], RunStats],
                 clock: Callable[[], float] = time.time):
        self.telegram = telegram
        self.run = run
        self.clock = clock
        # Commands sent before this moment (bot offline, or a run in progress) are not executed,
        # so a backlog of /run messages can't trigger back-to-back LinkedIn sessions.
        self.accept_after = clock()
        self.offset: int | None = None

    def handle(self, update: dict) -> None:
        self.offset = update["update_id"] + 1
        msg = update.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != str(self.telegram.chat_id):
            return  # only the owner's chat may control the agent
        text = (msg.get("text") or "").strip()
        if text.split("@")[0] != "/run":
            self.telegram.send(HELP)
            return
        if msg.get("date", 0) < self.accept_after:
            self.telegram.send("Skipped a /run sent while I was offline or busy. Send /run again if you still want one.")
            return
        self.telegram.send("Checking your feed now. This takes a few minutes.")
        try:
            self.telegram.send(summarize(self.run()))
        except Exception as e:
            log.exception("Run triggered from Telegram failed")
            self.telegram.send(f"Run failed: {escape(str(e)[:300])}")
        self.accept_after = self.clock()

    def serve_forever(self) -> None:
        self.telegram.set_commands(COMMANDS)
        log.info("Listening for Telegram commands")
        while True:
            try:
                for update in self.telegram.get_updates(self.offset):
                    self.handle(update)
            except Exception:
                log.exception("Telegram polling failed; retrying in %ds", RETRY_DELAY_S)
                time.sleep(RETRY_DELAY_S)
