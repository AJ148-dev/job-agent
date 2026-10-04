from jobagent.models import JobExtraction, LLMMatch
from jobagent.notify.telegram import format_job
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
    assert stats.notified == 2 and len(notifier.sent) == 2
    assert "Experience: not mentioned" in notifier.sent[0]
    assert llm.calls == 6  # 2 jobs x (extract + match) + not-job extract + too-senior extract

    stats2 = run_pipeline([FakeSource(POSTS)], store, llm, profile, notifier, limit=50)
    assert stats2.duplicates == 7 and stats2.notified == 0
    assert len(notifier.sent) == 2 and llm.calls == 6


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


def test_format_job_escapes_html():
    post = make_post("x", "t")
    job = JobExtraction(is_job_opportunity=True, reason="r", role="Dev <Lead>", company="A&B",
                        apply_url="https://a.com/?x=1&y=2")
    match = LLMMatch(score=80, matched_skills=["Python"], reasons="ok")
    text = format_job(post, job, match)
    assert "Dev &lt;Lead&gt;" in text and "A&amp;B" in text
    assert 'href="https://a.com/?x=1&amp;y=2"' in text
