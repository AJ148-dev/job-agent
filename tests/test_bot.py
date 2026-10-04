from jobagent.bot import HELP, Bot, summarize
from jobagent.pipeline import RunStats

OWNER = "6040284887"


class FakeTelegram:
    chat_id = OWNER

    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


class Clock:
    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _update(update_id: int, text: str, date: float, chat_id=OWNER) -> dict:
    return {"update_id": update_id, "message": {"chat": {"id": int(chat_id)}, "text": text, "date": date}}


def _bot(run_result=RunStats(fetched=40, notified=3)):
    calls = []
    clock = Clock(1000)

    def run():
        calls.append(clock.now)
        clock.now += 300  # a run takes a while
        if isinstance(run_result, Exception):
            raise run_result
        return run_result

    tg = FakeTelegram()
    return Bot(tg, run, clock), tg, calls, clock


def test_run_command_runs_and_reports():
    bot, tg, calls, _ = _bot()
    bot.handle(_update(1, "/run", date=1001))
    assert len(calls) == 1
    assert tg.sent[-1] == "Done: read 40 posts, 3 new jobs sent above."
    assert bot.offset == 2


def test_ignores_other_chats():
    bot, tg, calls, _ = _bot()
    bot.handle(_update(1, "/run", date=1001, chat_id="999"))
    assert calls == [] and tg.sent == []
    assert bot.offset == 2


def test_stale_and_during_run_commands_are_skipped():
    bot, tg, calls, _ = _bot()
    bot.handle(_update(1, "/run", date=900))           # sent while bot was offline
    bot.handle(_update(2, "/run", date=1001))          # runs, clock moves to 1300
    bot.handle(_update(3, "/run", date=1100))          # sent during that run
    bot.handle(_update(4, "/run@my_jobs_bot", date=1400))
    assert len(calls) == 2
    assert sum("Skipped" in m for m in tg.sent) == 2


def test_failed_run_is_reported_and_bot_keeps_going():
    bot, tg, calls, _ = _bot(run_result=RuntimeError("Ollama <down>"))
    bot.handle(_update(1, "/run", date=1001))
    assert tg.sent[-1] == "Run failed: Ollama &lt;down&gt;"


def test_other_text_gets_help():
    bot, tg, calls, _ = _bot()
    bot.handle(_update(1, "hello", date=1001))
    assert tg.sent == [HELP] and calls == []


def test_summaries():
    assert summarize(RunStats(fetched=60)) == "Done: read 60 posts, no new jobs."
    assert summarize(RunStats(fetched=60, notified=1, errors=2)).startswith("Done: read 60 posts, 1 new job sent above.")
    assert "jobagent login" in summarize(RunStats(fetched=0, errors=1))
