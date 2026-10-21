"""jobvector adapter (science/medicine/IT specialist board) — no public API found.

Pagination: `page=N` query param — see base.py's `paginate_search` for why
URL-based paging replaced scroll/click detection. Note the known Cloudflare
block on this source (README "Known limitation"): every page request
currently returns a 403 challenge, so this loop stops after page 1 regardless
(0 matching links -> no growth -> break).
"""

from __future__ import annotations

import re
from urllib.parse import quote

from playwright.sync_api import Browser

from ..models import JobPosting, JobSource
from .base import JobSiteAdapter, paginate_search, polite_delay

JOB_URL_RE = re.compile(r"/job/|/jobs/[a-z0-9-]+-\d+")
BASE_URL = "https://www.jobvector.com"


class JobvectorAdapter(JobSiteAdapter):
    source = "jobvector"

    def fetch(self, browser: Browser, query: str, location: str, max_postings: int | None = None) -> list[JobPosting]:
        page = self.new_page(browser)
        try:
            return paginate_search(
                page,
                lambda page_num: self._page_url(query, location, page_num),
                JOB_URL_RE,
                JobSource.JOBVECTOR,
                BASE_URL,
                location,
                max_postings=max_postings,
            )
        finally:
            page.close()
            polite_delay()

    @staticmethod
    def _page_url(query: str, location: str, page_num: int) -> str:
        url = f"{BASE_URL}/en/jobs/?q={quote(query)}&l={quote(location)}"
        return url if page_num == 1 else f"{url}&page={page_num}"
