"""Turn one LinkedIn feed post's HTML into a RawPost.

All LinkedIn DOM knowledge lives here and in the selectors below, so when LinkedIn changes
its markup this is the only file to fix (and tests/fixtures/linkedin_feed.html to refresh).
"""

import re

from bs4 import BeautifulSoup, Tag

from jobagent.models import RawPost

SOURCE = "linkedin"

POST_SELECTOR = 'div[data-urn^="urn:li:activity:"], div[data-id^="urn:li:activity:"]'
SEE_MORE_SELECTOR = "button.feed-shared-inline-show-more-text__see-more-less-toggle"

TEXT_SELECTORS = [
    ".update-components-text",
    ".feed-shared-inline-show-more-text",
    ".feed-shared-update-v2__description",
]
AUTHOR_SELECTORS = [
    ".update-components-actor__title span[aria-hidden=true]",
    ".update-components-actor__name span[aria-hidden=true]",
    ".update-components-actor__title",
]
TIME_SELECTORS = [".update-components-actor__sub-description span[aria-hidden=true]"]

URN_RE = re.compile(r"urn:li:activity:\d+")
SEE_MORE_RE = re.compile(r"\s*…\s*(see more|more)\s*$", re.IGNORECASE)


def _first_text(root: Tag, selectors: list[str]) -> str | None:
    for sel in selectors:
        el = root.select_one(sel)
        if el and (text := el.get_text("\n", strip=True)):
            return text
    return None


def parse_post(html: str) -> RawPost | None:
    """Return None for posts we can't or shouldn't use (no URN, no text, promoted)."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find(attrs={"data-urn": URN_RE}) or soup.find(attrs={"data-id": URN_RE})
    if root is None:
        return None
    urn = URN_RE.search(root.get("data-urn") or root.get("data-id") or "").group(0)

    posted_at = _first_text(root, TIME_SELECTORS)
    if posted_at and "promoted" in posted_at.lower():
        return None

    text = _first_text(root, TEXT_SELECTORS)
    if not text:
        return None
    text = SEE_MORE_RE.sub("", text).strip()

    return RawPost(
        source=SOURCE,
        external_id=urn,
        url=f"https://www.linkedin.com/feed/update/{urn}/",
        author=_first_text(root, AUTHOR_SELECTORS),
        posted_at=posted_at,
        text=text,
    )
