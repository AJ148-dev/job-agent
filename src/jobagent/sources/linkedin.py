import logging
import random
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from jobagent.models import RawPost
from jobagent.sources.linkedin_parse import (
    KEY_JS, POST_SELECTOR, ROW_JS, SEE_MORE_SELECTOR, parse_post, post_url, token_urns,
)

log = logging.getLogger(__name__)

FEED_URL = "https://www.linkedin.com/feed/"
LOGIN_URL = "https://www.linkedin.com/login"
MAX_SCROLLS = 40
MAX_IDLE_SCROLLS = 5


class NotLoggedInError(RuntimeError):
    pass


def _pause(low: float = 1.5, high: float = 4.0) -> None:
    time.sleep(random.uniform(low, high))


def _record_urns(resp: Response, urns: dict[str, str]) -> None:
    if "linkedin.com" not in resp.url or resp.request.resource_type not in ("document", "fetch", "xhr"):
        return
    try:
        urns.update(token_urns(resp.text()))
    except Exception:  # redirects, aborted requests and binary bodies have no usable text
        pass


class LinkedInSource:
    name = "linkedin"

    def __init__(self, profile_dir: Path, debug_dir: Path, channel: str = "chrome"):
        self.profile_dir = profile_dir
        self.debug_dir = debug_dir
        self.channel = channel or None

    def _open(self, playwright) -> BrowserContext:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        # Headful on purpose: headless browsers are far more likely to be flagged.
        return playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            channel=self.channel,
            headless=False,
            viewport={"width": 1280, "height": 900},
        )

    def login(self, timeout_s: int = 600) -> None:
        """Open LinkedIn and wait until the user has logged in and reached the feed."""
        with sync_playwright() as p:
            ctx = self._open(p)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(LOGIN_URL)
                log.info("Log in to LinkedIn in the opened browser (waiting up to %ds)...", timeout_s)
                try:
                    page.wait_for_url("**/feed/**", timeout=timeout_s * 1000)
                except PlaywrightTimeoutError:
                    raise NotLoggedInError("Did not reach the LinkedIn feed in time; session not saved.")
                _pause(3, 5)
            finally:
                ctx.close()

    def fetch(self, limit: int) -> list[RawPost]:
        with sync_playwright() as p:
            ctx = self._open(p)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                urns: dict[str, str] = {}
                page.on("response", lambda resp: _record_urns(resp, urns))
                page.goto(FEED_URL, wait_until="domcontentloaded")
                _pause(3, 6)
                if any(s in page.url for s in ("/login", "/authwall", "/checkpoint", "/uas/")):
                    raise NotLoggedInError("LinkedIn session expired. Run: jobagent login")
                posts = self._collect(page, limit)
            finally:
                ctx.close()
        for post in posts:
            if urn := urns.get(post.external_id):
                post.url = post_url(urn)
        log.info("LinkedIn: post links found for %d of %d posts", sum(p.external_id in urns for p in posts), len(posts))
        return posts

    def _collect(self, page: Page, limit: int) -> list[RawPost]:
        posts: dict[str, RawPost] = {}
        done: set[str] = set()
        seen_containers: set[str] = set()
        idle = 0
        for _ in range(MAX_SCROLLS):
            before = len(posts)
            for el in page.query_selector_all(POST_SELECTOR):
                key = el.evaluate(KEY_JS)
                seen_containers.add(key)
                if key in done:
                    continue
                btn = el.query_selector(SEE_MORE_SELECTOR)
                if btn and btn.is_visible() and "more" in (btn.inner_text() or "").lower():
                    btn.click()
                    _pause(0.4, 1.2)
                # Unparsed containers (e.g. text not rendered yet) are retried next scroll.
                if post := parse_post(el.evaluate(ROW_JS)):
                    done.add(key)
                    posts.setdefault(post.external_id, post)
            if len(posts) >= limit:
                break
            idle = idle + 1 if len(posts) == before else 0
            if idle >= MAX_IDLE_SCROLLS:
                break
            page.mouse.wheel(0, random.randint(600, 1300))
            _pause()

        log.info("LinkedIn: %d post containers seen, %d posts parsed", len(seen_containers), len(posts))
        if not posts:
            self._dump(page)
        return list(posts.values())[:limit]

    def _dump(self, page: Page) -> None:
        """Save the page so stale selectors can be fixed against real markup."""
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.debug_dir / "linkedin_feed.html"
        path.write_text(page.content(), encoding="utf-8")
        log.error("No posts parsed; selectors may be stale. Page saved to %s", path)
