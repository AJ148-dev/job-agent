import time
from html import escape
from typing import Protocol

import httpx

from jobagent.models import JobExtraction, MatchResult, RawPost

TELEGRAM_LIMIT = 4096
SEND_INTERVAL_S = 1.0  # Telegram allows roughly one message per second per chat.


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


def format_job(post: RawPost, job: JobExtraction, match: MatchResult) -> str:
    title = escape(job.role or "Unknown role")
    company = escape(job.company or post.author or "Unknown company")
    lines = [f"<b>{title}</b> at <b>{company}</b>", f"Score: <b>{match.score}/100</b>"]

    where = ", ".join(x for x in (job.location, job.work_mode if job.work_mode != "unknown" else None) if x)
    if where:
        lines.append(f"Location: {escape(where)}")
    if job.min_years_experience is not None:
        lines.append(f"Experience: {job.min_years_experience}+ yrs")
    if job.summary:
        lines.append(f"\n{escape(job.summary)}")
    lines.append(f"\n<i>Why:</i> {escape(match.reasons)}")
    if match.matched_skills:
        lines.append(f"<i>Matched:</i> {escape(', '.join(match.matched_skills))}")
    if match.missing_skills:
        lines.append(f"<i>Missing:</i> {escape(', '.join(match.missing_skills))}")
    if match.penalties:
        lines.append(f"<i>Flags:</i> {escape('; '.join(match.penalties))}")

    links = []
    if post.url:
        links.append(f'<a href="{escape(post.url, quote=True)}">Post</a>')
    if job.apply_url:
        links.append(f'<a href="{escape(job.apply_url, quote=True)}">Apply</a>')
    if job.contact_email:
        links.append(escape(job.contact_email))
    if links:
        lines.append("\n" + " | ".join(links))

    text = "\n".join(lines)
    return text if len(text) <= TELEGRAM_LIMIT else text[: TELEGRAM_LIMIT - 1] + "…"


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        if not token or not chat_id:
            raise ValueError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id

    def send(self, text: str) -> None:
        resp = httpx.post(
            self._url,
            json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        body = resp.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram error: {body.get('description', resp.text)}")
        time.sleep(SEND_INTERVAL_S)
