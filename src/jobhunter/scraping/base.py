"""Shared adapter contract + politeness helpers for every job-site scraper.

IMPORTANT: selectors in the concrete adapters (stepstone.py, indeed.py,
jobvector.py, linkedin.py) are best-effort. Live verification against these
sites from an automated fetcher failed during development (StepStone reset
the connection, jobvector returned 403) — which is itself the expected
behavior of sites that actively block non-browser clients, and consistent
with the ToS risk flagged in architecture.html. Each adapter uses a
resilient, class-name-independent extraction strategy (find links matching
the site's job-URL pattern, then read nearby text) specifically because
exact selectors could not be confirmed and WILL drift. Re-run
`jobhunter scrape --source <name> --debug` after install and adjust the
adapter if it returns zero results — that means the site's markup moved,
not that the interface is wrong.

Pagination walks each results page by URL (`paginate_search` below), not by
scrolling + clicking a "next"/"load more" control — a live run showed every
StepStone search stopping at exactly that site's single-page size (25)
regardless of how many broader results existed, meaning generic click
detection never actually found and fired StepStone's control. Requesting
`?page=2`, `?page=3`, ... (or each site's equivalent offset param) directly
doesn't depend on finding the right element at all, just on that param
existing — which is standard for all four sites' plain (non-JS-app) search
result pages.
"""

from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Callable

from playwright.sync_api import Browser, Page
from playwright_stealth import Stealth

from ..models import JobPosting, JobSource

logger = logging.getLogger(__name__)

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Patches over common automation fingerprints (navigator.webdriver, missing
# chrome.* objects, etc.) on every page any adapter creates. Reduces but does
# not eliminate fingerprint-based blocks (e.g. jobvector's Cloudflare
# challenge) — see base.py module docstring above.
_stealth = Stealth()


def polite_delay(min_s: float = 2.0, max_s: float = 5.0) -> None:
    """Human-scale pause between requests. Not a substitute for a low-frequency schedule."""
    time.sleep(random.uniform(min_s, max_s))


CARD_ANCESTOR_SELECTORS = (
    "xpath=ancestor::article[1]",
    "xpath=ancestor::li[1]",
    "xpath=ancestor::div[contains(@data-testid,'card')][1]",
    "xpath=ancestor::div[contains(@class,'job')][1]",
    "xpath=ancestor::td[1]",
)


def combine_location(town: str, search_location: str) -> str:
    """"Gräfelfing bei München, Germany" instead of just the town or just the
    search location (the previous fallback whenever town extraction failed)."""
    town = town.strip()
    if not town or town.lower() == search_location.strip().lower():
        return search_location
    return f"{town}, {search_location}"


def nearest_card_text(link) -> str:
    """Text of the nearest card-like ancestor of a job link.

    Tries each candidate ancestor selector individually — a single Playwright
    locator string combining multiple "xpath=..." prefixes with "|" is invalid
    (Playwright chokes on chained xpath= prefixes inside one union) and was
    silently swallowed by an except-and-return-"" in each adapter, which is why
    company/town extraction was always falling back to empty/default.

    `timeout=800` on `inner_text()` matters as much as trying each selector
    individually: a selector that matches zero elements for this particular
    link (a real, expected case — not every site puts every card inside an
    `<li>`, say) otherwise auto-waits Playwright's full default action
    timeout (20s) hoping one appears, before falling through to the next
    selector. Multiplied across every job link on a results page and up to
    5 candidate selectors each, that turned one page's extraction into a
    multi-minute stall the one time it hit live (LinkedIn — confirmed by
    reproducing it directly).
    """
    for selector in CARD_ANCESTOR_SELECTORS:
        try:
            card = link.locator(selector).first
            text = (card.inner_text(timeout=800) or "").strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _postings_from_page(
    page: Page,
    job_url_re: re.Pattern[str],
    source: JobSource,
    base_url: str,
    location: str,
    seen_urls: set[str],
    *,
    strip_query: bool = False,
) -> list[JobPosting]:
    postings: list[JobPosting] = []
    for link in page.locator("a[href]").all():
        href = link.get_attribute("href") or ""
        if not job_url_re.search(href):
            continue
        full_url = href if href.startswith("http") else f"{base_url}{href}"
        if strip_query:
            full_url = full_url.split("?")[0]
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = (link.inner_text() or "").strip()
        if not title or len(title) > 200:
            continue

        card_text = nearest_card_text(link)
        lines = [l.strip() for l in card_text.splitlines() if l.strip() and l.strip() != title]
        company = lines[0] if lines else ""
        town = lines[1] if len(lines) > 1 else ""

        postings.append(
            JobPosting(
                source=source,
                title=title,
                company=company,
                location=combine_location(town, location),
                url=full_url,
            )
        )
    return postings


def paginate_search(
    page: Page,
    url_for_page: Callable[[int], str],
    job_url_re: re.Pattern[str] | None,
    source: JobSource,
    base_url: str,
    location: str,
    *,
    max_postings: int | None = None,
    max_pages: int = 40,
    wait_ms: int = 2500,
    strip_query: bool = False,
    extract: Callable[[Page, JobSource, str, str, set[str]], list[JobPosting]] | None = None,
) -> list[JobPosting]:
    """Walks page 1, 2, 3, ... of a search-results listing, requesting each
    directly by URL via `url_for_page(page_num)`, until a page adds no new
    postings, `max_postings` is reached (from `search.max_postings_per_search`
    — None means no cap), or `max_pages` is hit as a safety cap against a
    query with an unbounded number of real result pages. See the module
    docstring for why URL pagination replaced scroll/click detection.

    Extraction is the default href-matches-`job_url_re` strategy unless
    `extract` is given (a `(page, source, base_url, location, seen_urls) ->
    postings` callable) — needed for a site like Indeed, whose real job
    links live behind a `/pagead/clk` click-tracking redirect for every
    listing (not just sponsored ones), with the actual job identifier only
    available via each card's `data-jk` attribute. In that case `job_url_re`
    is unused and may be `None`.
    """
    extract_fn = extract or (
        lambda pg, src, burl, loc, seen: _postings_from_page(
            pg, job_url_re, src, burl, loc, seen, strip_query=strip_query
        )
    )
    postings: list[JobPosting] = []
    seen_urls: set[str] = set()
    for page_num in range(1, max_pages + 1):
        page.goto(url_for_page(page_num), wait_until="domcontentloaded")
        page.wait_for_timeout(wait_ms)
        page.mouse.wheel(0, 20_000)
        page.wait_for_timeout(600)

        new_postings = extract_fn(page, source, base_url, location, seen_urls)
        if not new_postings:
            break
        for posting in new_postings:
            postings.append(posting)
            if max_postings is not None and len(postings) >= max_postings:
                return postings
        polite_delay(1.0, 2.5)
    return postings


class JobSiteAdapter(ABC):
    source: str

    @abstractmethod
    def fetch(self, browser: Browser, query: str, location: str, max_postings: int | None = None) -> list[JobPosting]:
        """Return normalized postings for one (query, location) search.

        `max_postings` (from `search.max_postings_per_search`, None = no cap)
        stops pagination as soon as that many postings are collected.
        """

    def new_page(self, browser: Browser) -> Page:
        context = browser.new_context(user_agent=DESKTOP_USER_AGENT, locale="en-US")
        page = context.new_page()
        page.set_default_timeout(20_000)
        _stealth.apply_stealth_sync(page)
        return page

    def safe_fetch(self, browser: Browser, query: str, location: str, max_postings: int | None = None) -> list[JobPosting]:
        try:
            return self.fetch(browser, query, location, max_postings)
        except Exception:
            logger.exception("%s adapter failed for query=%r location=%r", self.source, query, location)
            return []
