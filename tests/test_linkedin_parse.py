from bs4 import BeautifulSoup

from jobagent.sources.linkedin_parse import POST_SELECTOR, parse_post
from tests.conftest import FIXTURES


def _rows() -> list[str]:
    """Mirror ROW_JS: the listitem row around each post."""
    soup = BeautifulSoup((FIXTURES / "linkedin_feed.html").read_text(), "html.parser")
    return [str(el.find_parent(attrs={"role": "listitem"})) for el in soup.select(POST_SELECTOR)]


def test_finds_all_posts():
    assert len(_rows()) == 4


def test_parses_hiring_post():
    post = parse_post(_rows()[0])
    assert post is not None
    assert post.external_id == "TOKENaaa111"
    assert post.author == "Neha Kapoor"
    assert post.url == "https://www.linkedin.com/in/neha-test/"
    assert post.text == "We're hiring SDE-1 at Acme Bengaluru!\n\nC++ / Java, strong DSA. Apply: https://acme.dev/jobs/1"


def test_skips_promoted_and_textless_posts():
    rows = _rows()
    assert parse_post(rows[1]) is None
    assert parse_post(rows[3]) is None


def test_activity_url_from_comments_and_promoted_word_in_text_kept():
    post = parse_post(_rows()[2])
    assert post is not None
    assert post.external_id == "TOKENccc333"
    assert post.url == "https://www.linkedin.com/feed/update/urn:li:activity:7512422060573306880/"
    assert post.author == "Arjun Rao"
    assert "promoted" in post.text
