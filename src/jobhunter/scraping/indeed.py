"""Indeed adapter. Publisher API + XML feed were both retired in 2024 (confirmed
during research), so a real search-jobs API no longer exists for independent
use — this is the only remaining path. Indeed is known to rate-limit and
CAPTCHA aggressive traffic; keep this adapter's call frequency low.

Extraction: every job title link on today's Indeed — sponsored or organic —
routes through a `/pagead/clk?...` click-tracking redirect, confirmed live;
there is no stable `/rc/clk` or `/viewjob?jk=` href to regex-match anymore
(that pattern now mostly catches decoy/"similar postings" links, which is
why counts were low and included junk). Each real job card instead carries a
`data-jk` attribute with the actual job id, so extraction keys off that and
builds the canonical `/viewjob?jk=<id>` URL directly instead of following
the tracking redirect.

Pagination: the classic `start=` offset (stepped by 10) — see base.py's
`paginate_search` for why URL-based paging replaced scroll/click detection.
"""

from __future__ import annotations

from urllib.parse import quote

from playwright.sync_api import Browser, Page

from ..models import JobPosting, JobSource
from .base import JobSiteAdapter, combine_location, nearest_card_text, paginate_search, polite_delay

BASE_URL = "https://de.indeed.com"
ARIA_LABEL_PREFIX = "alle details zu "


def _extract(page: Page, source: JobSource, base_url: str, location: str, seen_urls: set[str]) -> list[JobPosting]:
    postings: list[JobPosting] = []
    for card in page.locator("a[data-jk]").all():
        jk = card.get_attribute("data-jk") or ""
        if not jk:
            continue
        full_url = f"{base_url}/viewjob?jk={jk}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = (card.get_attribute("aria-label") or "").strip()
        if title.lower().startswith(ARIA_LABEL_PREFIX):
            title = title[len(ARIA_LABEL_PREFIX):].strip()
        if not title:
            title = (card.inner_text() or "").strip()
        if not title or len(title) > 200:
            continue

        card_text = nearest_card_text(card)
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


class IndeedAdapter(JobSiteAdapter):
    source = "indeed"

    def fetch(self, browser: Browser, query: str, location: str, max_postings: int | None = None) -> list[JobPosting]:
        page = self.new_page(browser)
        try:
            return paginate_search(
                page,
                lambda page_num: self._page_url(query, location, page_num),
                None,
                JobSource.INDEED,
                BASE_URL,
                location,
                max_postings=max_postings,
                extract=_extract,
            )
        finally:
            page.close()
            polite_delay(3.0, 6.0)

    @staticmethod
    def _page_url(query: str, location: str, page_num: int) -> str:
        url = f"{BASE_URL}/jobs?q={quote(query)}&l={quote(location)}"
        return url if page_num == 1 else f"{url}&start={(page_num - 1) * 10}"
