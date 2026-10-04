from jobagent.models import JobExtraction, LLMMatch
from jobagent.notify.telegram import TELEGRAM_LIMIT, build_digest, format_job
from jobagent.pipeline import run_pipeline
from jobagent.storage import Storage
from tests.conftest import FakeLLM, FakeNotifier, FakeSource, make_post

POSTS = [
    make_post("1", "We are hiring a Python backend engineer in Bangalore"),
    make_post("2", "We are hiring, weak match role"),           # job, low fit score: still sent
    make_post("3", "Excited to share I got a new job at Acme"),  # passes prefilter, LLM says not a job
    make_post("4", "Lovely sunset today"),                       # fails prefilter, no LLM call
    make_post("5", "Hiring an unpaid intern"),                   # excluded keyword
    make_post("6", "we are hiring a python backend engineer in bangalore!"),  # repost of 1
    make_post("7", "We are hiring a senior engineer"),           # asks 8 yrs: dropped, no match call
]


def test_end_to_end_and_no_duplicates_on_rerun(profile):
    store, llm, notifier = Storage(":memory:"), FakeLLM(), FakeNotifier()
    stats = run_pipeline([FakeSource(POSTS)], store, llm, profile, notifier, limit=50)

    assert (stats.fetched, stats.jobs, stats.not_job, stats.too_senior, stats.skipped, stats.duplicates) == \
        (7, 2, 1, 1, 2, 1)
    assert stats.notified == 2 and len(notifier.sent) == 1  # one digest for the run
    assert notifier.sent[0].startswith("<b>2 new jobs from your feed</b>")
    assert "Experience: not mentioned" in notifier.sent[0]
    assert llm.calls == 6  # 2 jobs x (extract + match) + not-job extract + too-senior extract

    stats2 = run_pipeline([FakeSource(POSTS)], store, llm, profile, notifier, limit=50)
    assert stats2.duplicates == 7 and stats2.notified == 0
    assert len(notifier.sent) == 1 and llm.calls == 6


def test_failed_send_is_retried_next_run(profile):
    store = Storage(":memory:")
    run_pipeline([FakeSource(POSTS[:1])], store, FakeLLM(), profile, FakeNotifier(fail=True), limit=50)
    notifier = FakeNotifier()
    run_pipeline([FakeSource(POSTS[:1])], store, FakeLLM(), profile, notifier, limit=50)
    assert len(notifier.sent) == 1


def test_llm_error_is_isolated_and_retried(profile):
    store = Storage(":memory:")
    stats = run_pipeline([FakeSource(POSTS[:2])], store, FakeLLM(fail_on="weak"), profile, None, limit=50)
    assert stats.errors == 1 and stats.jobs == 1
    stats2 = run_pipeline([FakeSource(POSTS[:2])], store, FakeLLM(), profile, None, limit=50)
    assert stats2.jobs == 1 and stats2.duplicates == 1


def test_source_failure_does_not_crash(profile):
    class Broken:
        name = "broken"

        def fetch(self, limit):
            raise RuntimeError("browser died")

    stats = run_pipeline([Broken(), FakeSource(POSTS[:1])], Storage(":memory:"), FakeLLM(), profile, None, 50)
    assert stats.errors == 1 and stats.jobs == 1


def test_format_job_escapes_html_and_shows_post_not_reasons():
    post = make_post("x", "Hiring <interns> & more")
    post.url = "https://www.linkedin.com/feed/update/urn:li:activity:1/"
    job = JobExtraction(is_job_opportunity=True, reason="r", role="Dev <Lead>", company="A&B",
                        apply_url="https://a.com/?x=1&y=2")
    match = LLMMatch(score=80, matched_skills=["Python"], reasons="SECRET REASONS")
    text = format_job(1, post, job, match)
    assert "Dev &lt;Lead&gt;" in text and "A&amp;B" in text
    assert "<blockquote>Hiring &lt;interns&gt; &amp; more</blockquote>" in text
    assert '<a href="https://www.linkedin.com/feed/update/urn:li:activity:1/">Open post</a>' in text
    assert 'href="https://a.com/?x=1&amp;y=2"' in text
    assert "SECRET REASONS" not in text and "Python" not in text


def test_excerpt_is_truncated():
    post = make_post("x", "word " * 400)
    text = format_job(1, post, JobExtraction(is_job_opportunity=True, reason="r"), LLMMatch(score=50, reasons="r"))
    assert len(text) < 800 and "…</blockquote>" in text


def test_digest_splits_without_breaking_jobs():
    match = LLMMatch(score=50, reasons="r")
    jobs = [(i, make_post(str(i), "x" * 600), JobExtraction(is_job_opportunity=True, reason="r"), match)
            for i in range(20)]
    messages = build_digest(jobs)
    assert len(messages) > 1
    assert all(len(text) <= TELEGRAM_LIMIT for text, _ in messages)
    assert [i for _, ids in messages for i in ids] == list(range(20))
    assert messages[0][0].startswith("<b>20 new jobs")
    assert build_digest([]) == []
