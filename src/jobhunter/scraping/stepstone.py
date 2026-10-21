"""StepStone adapter. No public search API exists (confirmed during research —
see architecture.html compliance note), so this drives a real browser.

Extraction strategy: find <a> elements whose href matches StepStone's job-detail
URL pattern (`/stellenangebote--...--<id>.html` or `/jobs/...`), then read the
link's own text as the title and walk up to the nearest card-like ancestor for
company/location. This is deliberately selector-light so it survives class-name
churn better than a hardcoded CSS path — see base.py for why exact selectors
couldn't be verified live.

Pagination: StepStone's results page honors a `?page=N` query param — see
base.py's `paginate_search` for why URL-based paging replaced scroll/click
detection (a live run showed every search stopping at exactly 25 results,
StepStone's single-page size, because the click-based approach never found
StepStone's actual "next page" control).
"""

from __future__ import annotations

import re
from urllib.parse import quote

from playwright.sync_api import Browser

from ..models import JobPosting, JobSource
from .base import JobSiteAdapter, paginate_search, polite_delay

JOB_URL_RE = re.compile(r"/stellenangebote--|/jobs/[^/]+--\d+")
BASE_URL = "https://www.stepstone.de"


class StepStoneAdapter(JobSiteAdapter):
    source = "stepstone"

    def fetch(self, browser: Browser, query: str, location: str, max_postings: int | None = None) -> list[JobPosting]:
        page = self.new_page(browser)
        try:
            return paginate_search(
                page,
                lambda page_num: self._page_url(query, location, page_num),
                JOB_URL_RE,
                JobSource.STEPSTONE,
                BASE_URL,
                location,
                max_postings=max_postings,
            )
        finally:
            page.close()
            polite_delay()

    @staticmethod
    def _page_url(query: str, location: str, page_num: int) -> str:
        # safe="" so a query containing "/" (e.g. "Systemingenieur/in") encodes as
        # %2F instead of splitting the path into an extra, bogus segment.
        url = f"{BASE_URL}/jobs/{quote(query, safe='')}/in-{quote(location, safe='')}"
        return url if page_num == 1 else f"{url}?page={page_num}"
