from bs4 import BeautifulSoup

from jobagent.sources.linkedin_parse import POST_SELECTOR, parse_post
from tests.conftest import FIXTURES


def _containers() -> list[str]:
    soup = BeautifulSoup((FIXTURES / "linkedin_feed.html").read_text(), "html.parser")
    return [str(el) for el in soup.select(POST_SELECTOR)]


def test_finds_all_post_containers():
    assert len(_containers()) == 4


def test_parses_hiring_post():
    post = parse_post(_containers()[0])
    assert post is not None
    assert post.external_id == "urn:li:activity:7100000000000000001"
    assert post.url == "https://www.linkedin.com/feed/update/urn:li:activity:7100000000000000001/"
    assert post.author == "Priya Sharma"
    assert post.posted_at == "2h •"
    assert "Backend Engineer" in post.text and "https://jobs.example.com/123" in post.text
    assert "see more" not in post.text


def test_skips_promoted_and_textless_posts():
    containers = _containers()
    assert parse_post(containers[1]) is None
    assert parse_post(containers[3]) is None


def test_data_id_fallback_and_more_suffix_stripped():
    post = parse_post(_containers()[2])
    assert post is not None
    assert post.external_id == "urn:li:activity:7100000000000000003"
    assert post.author == "Rahul Verma"
    assert not post.text.endswith("more")
