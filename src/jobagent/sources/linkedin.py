import logging
import random
import time
from collections import Counter
from pathlib import Path

from playwright.sync_api import BrowserContext, ElementHandle, Page, Response, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from jobagent.matching import passes_prefilter
from jobagent.models import RawPost
from jobagent.sources.linkedin_parse import (
    COPY_LINK_TEXT, KEY_JS, MENU_SELECTOR, POST_SELECTOR, ROW_JS, SEE_MORE_SELECTOR, parse_post, post_url,
    token_urns,
)

log = logging.getLogger(__name__)

FEED_URL = "https://www.linkedin.com/feed/"
LOGIN_URL = "https://www.linkedin.com/login"
MAX_SCROLLS = 40
MAX_IDLE_SCROLLS = 5
PAYLOAD_SNIPPET_CHARS = 6000

# Keeps "Copy link to post" from overwriting the user's system clipboard: the page's copy
# calls are redirected into window.__jobagentCopied instead.
CAPTURE_COPY_JS = """
(() => {
  const capture = (t) => { window.__jobagentCopied = String(t); return Promise.resolve(); };
  if (navigator.clipboard) {
    navigator.clipboard.writeText = capture;
    navigator.clipboard.write = async (items) => {
      for (const item of items) {
        if (item.types.includes('text/plain')) capture(await (await item.getType('text/plain')).text());
      }
    };
  }
  const exec = document.execCommand.bind(document);
  document.execCommand = (cmd, ...rest) => {
    if (String(cmd).toLowerCase() !== 'copy') return exec(cmd, ...rest);
    const a = document.activeElement;
    const fromField = a && 'value' in a && a.selectionEnd > a.selectionStart
      ? a.value.slice(a.selectionStart, a.selectionEnd) : '';
    capture(fromField || String(window.getSelection()));
    return true;
  };
})();
"""


class NotLoggedInError(RuntimeError):
    pass


def _pause(low: float = 1.5, high: float = 4.0) -> None:
    time.sleep(random.uniform(low, high))


class _FeedNetwork:
    """Collects post URNs (and raw payloads, for debugging) from the feed's network responses."""

    def __init__(self) -> None:
        self.urns: dict[str, str] = {}
        self.payloads: list[str] = []
        self.body_errors: Counter[str] = Counter()

    def on_response(self, resp: Response) -> None:
        kind = resp.request.resource_type
        if "linkedin.com" not in resp.url or kind not in ("document", "fetch", "xhr"):
            return
        try:
            body = resp.text()
        except PlaywrightError as e:  # redirects, aborted requests, evicted bodies
            self.body_errors[f"{kind} {resp.url.split('?')[0][:80]}: {str(e).splitlines()[0][:80]}"] += 1
            return
        if found := token_urns(body):
            self.urns.update(found)
        if "FeedType_" in body:
            self.payloads.append(body)


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
        network = _FeedNetwork()
        with sync_playwright() as p:
            ctx = self._open(p)
            try:
                ctx.add_init_script(CAPTURE_COPY_JS)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.on("response", network.on_response)
                page.goto(FEED_URL, wait_until="domcontentloaded")
                _pause(3, 6)
                if any(s in page.url for s in ("/login", "/authwall", "/checkpoint", "/uas/")):
                    raise NotLoggedInError("LinkedIn session expired. Run: jobagent login")
                posts = self._collect(page, limit, network)
            finally:
                ctx.close()

        for post in posts:
            if urn := network.urns.get(post.external_id):
                post.url = post_url(urn)
        unmapped = [p.external_id for p in posts if p.external_id not in network.urns]
        log.info("LinkedIn: links from network for %d of %d posts; %d still without a link",
                 len(posts) - len(unmapped), len(posts), sum(p.url is None for p in posts))
        if unmapped:
            self._dump_payloads(unmapped, network.payloads)
        for error, count in network.body_errors.most_common(5):
            log.info("Unreadable network response x%d: %s", count, error)
        return posts

    def _collect(self, page: Page, limit: int, network: _FeedNetwork) -> list[RawPost]:
        posts: dict[str, RawPost] = {}
        done: set[str] = set()
        seen_containers: set[str] = set()
        idle = 0
        for _ in range(MAX_SCROLLS):
            before = len(posts)
            for el in page.query_selector_all(POST_SELECTOR):
                if len(posts) >= limit:
                    break
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
                    # Only likely job posts are worth the extra clicks of the menu fallback.
                    if (post.url is None and post.external_id not in network.urns
                            and passes_prefilter(post.text)):
                        post.url = self._copy_link(page, el)
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
        return list(posts.values())

    def _copy_link(self, page: Page, el: ElementHandle) -> str | None:
        """Get the post link via its "…" menu -> "Copy link to post"."""
        menu = el.query_selector(MENU_SELECTOR)
        if menu is None:
            log.warning("Copy link: no post menu found")
            return None
        try:
            page.evaluate("window.__jobagentCopied = null")
            menu.click()
            _pause(0.6, 1.4)
            page.get_by_text(COPY_LINK_TEXT, exact=True).first.click(timeout=5000)
            _pause(0.5, 1.0)
            link = page.evaluate("window.__jobagentCopied")
        except PlaywrightError as e:
            log.warning("Copy link to post failed: %s", str(e).splitlines()[0])
            page.keyboard.press("Escape")
            return None
        if isinstance(link, str) and link.startswith("http"):
            return link
        log.warning("Copy link: nothing usable captured (%r)", link)
        return None

    def _dump(self, page: Page) -> None:
        """Save the page so stale selectors can be fixed against real markup."""
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.debug_dir / "linkedin_feed.html"
        path.write_text(page.content(), encoding="utf-8")
        log.error("No posts parsed; selectors may be stale. Page saved to %s", path)

    def _dump_payloads(self, tokens: list[str], payloads: list[str]) -> None:
        """Save network snippets around posts whose URN wasn't found, to fix TOKEN_URN_RE."""
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.debug_dir / "unmapped_post_payloads.txt"
        chunks = []
        for token in tokens:
            hits = [(body, i) for body in payloads if (i := body.find(token)) >= 0]
            chunks.append(f"=== {token} ({len(hits)} payloads contain it)")
            chunks += [body[max(0, i - PAYLOAD_SNIPPET_CHARS): i + PAYLOAD_SNIPPET_CHARS] for body, i in hits[:2]]
        path.write_text("\n\n".join(chunks), encoding="utf-8")
        log.info("Saved payload snippets for %d unmapped posts to %s", len(tokens), path)
