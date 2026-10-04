import time
from html import escape
from typing import Protocol

import httpx

from jobagent.models import JobExtraction, LLMMatch, RawPost

TELEGRAM_LIMIT = 4096
EXCERPT_CHARS = 500  # keeps every job block well under TELEGRAM_LIMIT
BLOCK_SEP = "\n\n"
SEND_INTERVAL_S = 1.0  # Telegram allows roughly one message per second per chat.


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


def format_job(number: int, post: RawPost, job: JobExtraction, match: LLMMatch) -> str:
    title = escape(job.role or "Unknown role")
    company = escape(job.company or post.author or "Unknown company")
    lines = [f"<b>{number}. {title}</b> at <b>{company}</b> ({match.score}/100)"]

    details = [x for x in (job.location, job.work_mode if job.work_mode != "unknown" else None) if x]
    years = job.min_years_experience
    details.append(f"Experience: {f'{years}+ yrs' if years is not None else 'not mentioned'}")
    lines.append(escape(" | ".join(details)))

    excerpt = post.text if len(post.text) <= EXCERPT_CHARS else post.text[:EXCERPT_CHARS].rstrip() + "…"
    lines.append(f"<blockquote>{escape(excerpt)}</blockquote>")

    links = []
    if post.url:
        links.append(f'<a href="{escape(post.url, quote=True)}">Open post</a>')
    if job.apply_url:
        links.append(f'<a href="{escape(job.apply_url, quote=True)}">Apply</a>')
    if job.contact_email:
        links.append(escape(job.contact_email))
    if links:
        lines.append(" | ".join(links))
    return "\n".join(lines)


def build_digest(
    jobs: list[tuple[int, RawPost, JobExtraction, LLMMatch]],
) -> list[tuple[str, list[int]]]:
    """Pack all jobs of a run into as few messages as Telegram's size limit allows.

    Returns (message, job_ids_in_message) pairs; a job is never split across messages.
    """
    if not jobs:
        return []
    messages: list[tuple[str, list[int]]] = []
    text, ids = f"<b>{len(jobs)} new job{'s' if len(jobs) > 1 else ''} from your feed</b>", []
    for number, (job_id, post, job, match) in enumerate(jobs, 1):
        block = format_job(number, post, job, match)
        if ids and len(text) + len(BLOCK_SEP) + len(block) > TELEGRAM_LIMIT:
            messages.append((text, ids))
            text, ids = block, []
        else:
            text = f"{text}{BLOCK_SEP}{block}"
        ids.append(job_id)
    messages.append((text, ids))
    return messages


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
