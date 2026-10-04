"""Turn one LinkedIn feed post's HTML into a RawPost.

All LinkedIn DOM knowledge lives here, so when LinkedIn changes its markup this is the only
file to fix (and tests/fixtures/linkedin_feed.html to refresh). Class names on the feed are
obfuscated, so only data-view-name / componentkey / aria-label attributes are used.
"""

import re

from bs4 import BeautifulSoup

from jobagent.models import RawPost

SOURCE = "linkedin"

POST_SELECTOR = '[data-view-name="feed-full-update"]'
SEE_MORE_SELECTOR = 'button[data-testid="expandable-text-button"]'
# Run in the browser on a POST_SELECTOR element: the row holding the post (and its comments).
ROW_JS = "e => (e.closest('[role=\"listitem\"]') || e).outerHTML"
KEY_JS = "e => (e.closest('[componentkey*=\"FeedType_\"]') || e).getAttribute('componentkey') || ''"

TOKEN_RE = re.compile(r"(?:expanded|update-card-focus)(.+?)FeedType_")
ACTIVITY_RE = re.compile(r"activity:(\d{15,})")
# In the feed's network payloads each post's state block names its token, then its URN.
TOKEN_URN_RE = re.compile(
    r"TranslationState-null([A-Za-z0-9_-]{20,}).{0,600}?reactionState-(urn:li:(?:activity|ugcPost|share):\d+)",
    re.DOTALL,
)
AUTHOR_LABEL_PREFIX = "Open control menu for post by "
TRAILING_MORE_RE = re.compile(r"\s*…\s*(more)?\s*$", re.IGNORECASE)


def post_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/"


def token_urns(payload: str) -> dict[str, str]:
    """Map post tokens (RawPost.external_id) to post URNs found in a feed network response."""
    return {m.group(1): m.group(2) for m in TOKEN_URN_RE.finditer(payload)}


def parse_post(html: str) -> RawPost | None:
    """Parse one feed row. Returns None for ads and posts without text."""
    soup = BeautifulSoup(html, "html.parser")
    full = soup.select_one(POST_SELECTOR)
    if full is None:
        return None
    if soup.find(string=lambda s: s.strip() == "Promoted"):
        return None

    keyed = soup.find(attrs={"componentkey": TOKEN_RE})
    if keyed is None:
        return None
    token = TOKEN_RE.search(keyed["componentkey"]).group(1)

    paragraphs = []
    for p in full.select('p[data-view-name="feed-commentary"]'):
        for button in p.find_all("button"):
            button.decompose()
        for br in p.find_all("br"):
            br.replace_with("\n")
        paragraphs.append(p.get_text(""))
    text = TRAILING_MORE_RE.sub("", "\n".join(paragraphs)).strip()
    if not text:
        return None

    author = None
    if menu := soup.find(attrs={"aria-label": re.compile("^" + AUTHOR_LABEL_PREFIX)}):
        author = menu["aria-label"].removeprefix(AUTHOR_LABEL_PREFIX).strip()
    actor = full.select_one('a[data-view-name="feed-actor"]')
    if not author and actor:
        author = actor.get_text(" ", strip=True).split("•")[0].strip() or None

    # In the DOM the post URN only appears inside comment ids. LinkedInSource replaces this
    # with the URN from network payloads when it can; the author profile is the last resort.
    activity = ACTIVITY_RE.search(html)
    if activity:
        url = post_url(f"urn:li:activity:{activity.group(1)}")
    else:
        url = actor.get("href") if actor else None

    return RawPost(source=SOURCE, external_id=token, url=url, author=author, text=text)
