import logging
from dataclasses import dataclass

from jobagent.config import Profile
from jobagent.llm.ollama import LLM
from jobagent.llm.tasks import extract_job, judge_match
from jobagent.matching import excluded_keyword, passes_prefilter, too_much_experience
from jobagent.notify.telegram import Notifier, format_job
from jobagent.sources.base import Source
from jobagent.storage import Storage

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    duplicates: int = 0
    skipped: int = 0
    not_job: int = 0
    too_senior: int = 0
    jobs: int = 0
    errors: int = 0
    notified: int = 0


def run_pipeline(
    sources: list[Source],
    store: Storage,
    llm: LLM,
    profile: Profile,
    notifier: Notifier | None,
    limit: int,
) -> RunStats:
    """Fetch, analyse and store new posts, then notify all unsent matches.

    With notifier=None (dry run) matches are logged instead of sent.
    """
    stats = RunStats()
    for source in sources:
        try:
            posts = source.fetch(limit)
        except Exception:
            log.exception("Source %s failed", source.name)
            stats.errors += 1
            continue
        stats.fetched += len(posts)

        for post in posts:
            if store.is_seen(post):
                stats.duplicates += 1
                continue
            if kw := excluded_keyword(post.text, profile):
                store.save_post(post, "skipped", f"excluded keyword: {kw}")
                stats.skipped += 1
                continue
            if not passes_prefilter(post.text):
                store.save_post(post, "skipped", "no job signals")
                stats.skipped += 1
                continue
            try:
                job = extract_job(llm, post.text)
                if not job.is_job_opportunity:
                    store.save_post(post, "not_job", job.reason)
                    stats.not_job += 1
                    log.info("Not a job: %s | %s", post.external_id, job.reason)
                    continue
                if reason := too_much_experience(job, profile):
                    store.save_post(post, "too_senior", reason)
                    stats.too_senior += 1
                    log.info("Too senior: %s at %s | %s", job.role, job.company, reason)
                    continue
                match = judge_match(llm, job, post.text, profile)
            except Exception as e:
                log.exception("Analysis failed for %s", post.external_id)
                store.save_post(post, "error", repr(e)[:500])
                stats.errors += 1
                continue
            post_id = store.save_post(post, "job")
            store.save_job(post_id, job, match)
            stats.jobs += 1
            log.info("Job: %s at %s -> score %d", job.role, job.company, match.score)

    for job_id, post, job, match in store.pending_notifications(profile.min_score):
        message = format_job(post, job, match)
        if notifier is None:
            log.info("[dry run] would send:\n%s", message)
            continue
        try:
            notifier.send(message)
        except Exception:
            log.exception("Telegram send failed for job %d; will retry next run", job_id)
            stats.errors += 1
            continue
        store.mark_notified(job_id)
        stats.notified += 1

    log.info("Run finished: %s", stats)
    return stats
