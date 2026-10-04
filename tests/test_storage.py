from jobagent.models import JobExtraction, LLMMatch
from jobagent.storage import Storage, content_hash
from tests.conftest import make_post


def _match(score: int) -> LLMMatch:
    return LLMMatch(score=score, reasons="r")


def test_dedupe_by_external_id():
    store = Storage(":memory:")
    post = make_post("a", "We are hiring")
    assert not store.is_seen(post)
    store.save_post(post, "job")
    assert store.is_seen(post)


def test_dedupe_by_content_hash_across_ids():
    store = Storage(":memory:")
    store.save_post(make_post("a", "We are HIRING!  https://x.co/1"), "job")
    assert store.is_seen(make_post("b", "we are hiring https://y.co/2"))
    assert content_hash("Hello, world") == content_hash("hello world")


def test_errored_posts_are_retried():
    store = Storage(":memory:")
    post = make_post("a", "We are hiring")
    store.save_post(post, "error", "boom")
    assert not store.is_seen(post)
    store.save_post(post, "job")
    assert store.is_seen(post)


def test_pending_notifications_threshold_and_mark():
    store = Storage(":memory:")
    job = JobExtraction(is_job_opportunity=True, reason="r", role="Dev")
    high = store.save_job(store.save_post(make_post("a", "one"), "job"), job, _match(90))
    store.save_job(store.save_post(make_post("b", "two"), "job"), job, _match(50))

    pending = store.pending_notifications(70)
    assert [p[0] for p in pending] == [high]
    store.mark_notified(high)
    assert store.pending_notifications(70) == []
    assert store.stats()["jobs_notified"] == 1
