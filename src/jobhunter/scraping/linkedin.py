"""LinkedIn adapter — HIGHEST RISK, see architecture.html compliance note.

LinkedIn's Terms of Service prohibit scraping outright and LinkedIn has won
breach-of-contract rulings on exactly that basis (hiQ v. LinkedIn) and is
actively pursuing similar action against scraping services in 2026. This
adapter uses LinkedIn's unauthenticated public job-search pages (no login,
no stored session) and is deliberately run least-often by the orchestrator
(see orchestrator/pipeline.py: LINKEDIN_MIN_INTERVAL_HOURS). Do not lower
that interval or add authentication to this adapter without re-reading the
compliance note — logging into a real account turns "elevated risk" into
"the account most likely to be restricted."

Pagination: LinkedIn's public search page honors a `start=` offset stepped by
25 (its per-page size) — see base.py's `paginate_search` for why URL-based
paging replaced scroll/click detection. `strip_query=True` because job links
carry `?position=&pageNum=&trackingId=...` params that would otherwise defeat
the seen-URL dedupe across pages (same job, different tracking values each
time it's re-shown).

Extraction: confirmed live that a real job link is
`/jobs/view/<title-slug>-at-<company-slug>-<numeric-id>`, not `/jobs/view/`
immediately followed by digits — the numeric id sits at the end of the slug,
so the old digits-right-after-view/ pattern never matched a single real link.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from playwright.sync_api import Browser

from ..models import JobPosting, JobSource
from .base import JobSiteAdapter, paginate_search, polite_delay

JOB_URL_RE = re.compile(r"/jobs/view/[\w-]+-\d+")
BASE_URL = "https://www.linkedin.com"


class LinkedInAdapter(JobSiteAdapter):
    source = "linkedin"

    def fetch(self, browser: Browser, query: str, location: str, max_postings: int | None = None) -> list[JobPosting]:
        page = self.new_page(browser)
        try:
            return paginate_search(
                page,
                lambda page_num: self._page_url(query, location, page_num),
                JOB_URL_RE,
                JobSource.LINKEDIN,
                BASE_URL,
                location,
                max_postings=max_postings,
                strip_query=True,
            )
        finally:
            page.close()
            polite_delay(4.0, 8.0)

    @staticmethod
    def _page_url(query: str, location: str, page_num: int) -> str:
        url = f"{BASE_URL}/jobs/search/?keywords={quote(query)}&location={quote(location)}"
        return url if page_num == 1 else f"{url}&start={(page_num - 1) * 25}"
