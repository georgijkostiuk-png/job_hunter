# jobhunter

Documents -> structured profile -> scraped job postings -> locally-scored matches -> email digest -> inbox tracking.

100% free to run: every LLM call — document extraction, job-posting matching, and email-thread triage — runs on a local model through [Ollama](https://ollama.com). No API key, no account, no per-token billing, no data leaving your machine.

Full design rationale, diagram, and defaults: [architecture.html](architecture.html) (open in a browser) / [architecture.pdf](architecture.pdf).

## Setup

```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m playwright install chromium
copy .env.example .env
```

At any point, check what's configured and what's still missing (no external calls made):

```
.venv\Scripts\python -m jobhunter.cli check
```

It reports the local LLM status (Ollama reachable + model pulled), whether Google credentials are found, and the active search/matching config — useful right after each setup step below to confirm it took effect.

### Local LLM (Ollama) — no API key needed

1. Install Ollama from **[ollama.com](https://ollama.com)** (Windows installer runs the server automatically in the background afterwards).
2. Pull the model this project defaults to:
   ```
   ollama pull qwen2.5:1.5b
   ```
   It's a small (~1GB), fast, fully local model — good enough for structured extraction/scoring and light enough to run comfortably on a laptop CPU. Every call uses grammar-constrained JSON output (Ollama's `format` parameter set to the exact Pydantic schema for the field being extracted), with an automatic validate-and-retry loop (up to 3 attempts) layered on top, since small models don't always get every field right on the first try.
3. **Want better quality and have the hardware for it?** Swap `llm.model` in `config.yaml` for any larger Ollama model you've pulled (e.g. `qwen2.5:7b`, `llama3.1:8b`) — no code changes needed, just `ollama pull <model>` and update the config. Bigger models are slower per call but more accurate, especially for extraction from messy CVs.

**Verify it's picked up** without spending anything (there's nothing to spend — it's local):

```
.venv\Scripts\python -m jobhunter.cli check
```

`check` reports whether the Ollama server is reachable and whether the configured model is pulled — it makes a local HTTP call to Ollama, never any external/paid API.

**Cost:** $0. There is no subscription, no metered billing, and nothing to watch under a billing dashboard — the only resource consumed is your own CPU/GPU/RAM while a `run` or `extract` pass is executing.

**Remote/alternate host:** if you run Ollama on another machine (e.g. a GPU box on your LAN) or on a non-default port, set `OLLAMA_HOST` in `.env` (e.g. `http://192.168.1.50:11434`) instead of editing `config.yaml`.

### Gmail OAuth client secret

1. Go to **[console.cloud.google.com](https://console.cloud.google.com)**, sign in with the Google account you want jobhunter to read/send mail from.
2. **Create a project** (or pick an existing one) — top-left project dropdown → "New Project" → give it any name, e.g. `jobhunter`.
3. **Enable the Gmail API** — left menu → "APIs & Services" → "Library" → search "Gmail API" → click it → "Enable".
4. **Configure the OAuth consent screen** — "APIs & Services" → "OAuth consent screen":
   - User type: **External** (unless you have a Google Workspace account, then Internal works too)
   - Fill in app name (e.g. "jobhunter"), your email as support/developer contact — the rest can stay default
   - Under "Test users", add your own Gmail address (required while the app is unverified — otherwise Google blocks the login)
5. **Create the OAuth client** — "APIs & Services" → "Credentials" → "Create Credentials" → "OAuth client ID":
   - Application type: **Desktop app**
   - Name: anything, e.g. `jobhunter-desktop`
   - Click "Create"
6. **Download the JSON** — click the download icon next to the client you just created.
7. **Save it** as exactly:
   ```
   data/google_credentials.json
   ```

The first real run opens a browser for the one-time consent screen (log in, click through the "unverified app" warning since it's just for you, approve the two scopes); after that a `data/google_token.json` is cached and refreshed automatically.

Verify everything is wired up (no external calls made):

```
.venv\Scripts\python -m jobhunter.cli check
```

## Usage

1. Drop documents (CV, diplomas, reference letters — PDF/DOCX/TXT/scanned images) into `data/inbox/` (subfolders are cosmetic).
2. Build/update your profile from those documents:
   ```
   .venv\Scripts\python -m jobhunter.cli extract
   ```
   Review `data/profile/profile.json` — this is what every match is scored against.
3. Run one pass (scrape all configured sources, score new postings, email a match digest for anything above threshold + a dashboard of everything found, optionally triage inbox replies):
   ```
   .venv\Scripts\python -m jobhunter.cli run
   ```
   **Tip:** Ollama unloads a model from memory after ~5 minutes of inactivity. If it's been idle, the first LLM call has to reload the model *and* process a long prompt on CPU, which can be slow enough to time out. Warm it up first:
   ```
   ollama run qwen2.5:1.5b "hi"
   ```
   Run it in any terminal (VS Code's integrated terminal or a separate cmd/PowerShell window — it just talks to the same local Ollama service) right before `run`, so matching starts with the model already loaded. A one-off timeout on a single posting no longer aborts the whole run (it's logged and retried next run), but pre-warming avoids the slowdown in the first place.
4. Or start the recurring scheduler (blocks; runs at the hours set in `config.yaml`, default 09:00 & 18:00, in your system's local timezone — auto-detected, no config needed):
   ```
   .venv\Scripts\python -m jobhunter.cli schedule
   ```

Every command accepts `--dry-run` where it makes sense (`extract`, `run`) to preview what would happen without calling the local LLM, Gmail, or a browser — `run --dry-run` still does the real scrape (so you see genuine results), it just skips matching, tracker writes, and the match-threshold digest email.

**`--dry-run` still sends an email** — worth knowing precisely what it does and doesn't skip:

| | `run --dry-run` | `run` (real) |
|---|---|---|
| Scrapes job sites | ✅ real requests | ✅ real requests |
| LLM matching / tracker writes | ❌ skipped | ✅ |
| Match-threshold digest email | ❌ skipped | ✅ (only postings ≥ `score_threshold`) |
| Dashboard + console log email | ✅ sent | ✅ sent |

The dashboard/console-log email fires on **every** run, dry-run included, so you get the full picture regardless of scoring — see "What `run` prints and saves" below. `--dry-run` means "no scoring, no tracking, no match-digest email," not "nothing happens."

### What `run` prints and saves

While scraping, each search logs live as it completes (`[12/51] stepstone @ Data Scientist (Germany): 6 posting(s) — 74 total so far`), so you can watch progress instead of staring at a silent terminal for several minutes. When it finishes, every run (dry-run included) writes four files to the project root:

- **`jobhunter_results.json`** — every posting found, both flat (`by_query`) and clustered (`by_group`, see Query groups below), machine-readable. Overwritten each run.
- **`jobhunter_dashboard_<YYYYMMDD>_<HHMMSS>.html`** — a self-contained, filterable HTML page (search box, per-source toggles, noise filter) built from the same data. Double-click to open in a browser; no server, nothing fetched at view time. Timestamped, so past runs' dashboards stick around instead of being overwritten.
- **`jobhunter_console_INFO_<YYYYMMDD>_<HHMMSS>.txt`** — that run's progress/log lines (`logger.info` output: per-search progress, warnings, "Dashboard written to...", "Sent results email to...").
- **`jobhunter_console_RESULTS_<YYYYMMDD>_<HHMMSS>.txt`** — that run's printed output (the grouped job listing + final stats), separate from the log noise above.

Both console files share the same timestamp as each other but not as the dashboard (each is stamped the moment it's actually written). If an email client is configured (see Notification email below), the dashboard + both console files are emailed together as three attachments at the end of every run — separate from, and in addition to, the match-threshold digest (which only fires on a real `run`, and only for postings scoring at/above `matching.score_threshold`). This lets you see everything that was found, not just what cleared the bar.

## Configuration

Everything tunable lives in `config.yaml`. See the "Defaults I've decided" table in `architecture.html` for the reasoning behind each default.

### Job preferences

```yaml
search:
  target_domains:
    - "Life Science & Quality Control"
    - "Coding & Data Science"
  queries:
    - "Quality Control"
    - "Qualitätsmanager/in"
    - "Qualitätskontrolle"
    - "Product Manager/in"
    - "Data Scientist"
    - "Data Science"
    - "Life Science-Profi"
    - "Life Science Verbindungsexperte/in"
    - "System-Ingenieur/in"
    - "Biochemie"
    - "Proteinbiochemie"
    - "Protein Biochemie"
    - "Wissenschaft, Labor"
    - "Research Associate"
    - "Team Lead Research and Development"
    - "Research and Development Engineer"
    - "Research and Development"
  locations:
    - "Germany"
  sources: ["stepstone", "jobvector", "indeed", "linkedin"]

  query_groups:
    "Quality Control": ["Quality Control", "Qualitätsmanager/in", "Qualitätskontrolle", "Product Manager/in"]
    "Data Science": ["Data Scientist", "Data Science", "System-Ingenieur/in"]
    "Life Science": ["Life Science-Profi", "Life Science Verbindungsexperte/in"]
    "Biochemistry & Research": ["Biochemie", "Proteinbiochemie", "Protein Biochemie", "Wissenschaft, Labor", "Research Associate"]
    "R&D": ["Team Lead Research and Development", "Research and Development Engineer", "Research and Development"]

  # Max postings collected per (query, location) search, per source. null = no
  # cap — each adapter scrolls/paginates until the listing is exhausted.
  max_postings_per_search: null

matching:
  score_threshold: 70   # 0-100; only postings at/above this get emailed
```

- `target_domains` — passed straight into the matching prompt; a posting outside both scores low even if individual skills overlap. Add/remove/reword freely.
- `queries` / `locations` — every query is searched against every location (so 17 queries × 1 location = 17 searches per source per run).
- `sources` — which sites to scrape and in what order; drop `"linkedin"` from the list entirely if you'd rather not touch it (see the compliance note below).
- `max_postings_per_search` — caps how many postings one search collects from one source. `null` (default) means all of them — every adapter keeps paginating until the listing runs out (see the note under Compliance below). Set an integer (e.g. `50`) to stop early instead, which also means fewer page-loads/requests per search.
- `score_threshold` — raise it for a quieter inbox, lower it to see more borderline matches.

No restart needed — each `jobhunter run` re-reads `config.yaml` fresh.

#### Query groups

`query_groups` is optional and purely presentational — every query in `queries` still gets searched individually regardless of whether it's grouped. Its only job is to cluster near-duplicate/related queries (e.g. `"Data Scientist"` and `"Data Science"`) under one label for reporting: results in `jobhunter_results.json`'s `by_group`, the dashboard, and the console output are deduplicated by URL *within* each group, so a posting that matched two related queries shows up once, tagged with which query(ies) found it, instead of twice. Queries not listed in any group still show up individually in `by_query`; nothing is dropped, just organized. Leave `query_groups` out entirely to skip clustering and get the flat per-query view everywhere.

### Notification email

```yaml
email:
  notify_to: ""   # blank = sends to the Gmail account you authenticated with
```

Set `notify_to` to a different address (e.g. a dedicated job-search inbox) if you don't want digests going to the same account the agent reads from. This only controls where the digest is *sent* — which account it *reads/sends from* is whichever Google account you complete the OAuth consent screen with (see Setup above).

**Skip the OAuth flow just for notifications:** set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `.env` (generate an app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), requires 2-Step Verification) and the digest is sent over plain SMTP instead of the Gmail API — no `google_credentials.json`, no browser consent screen. `jobhunter check` reports which path is active. Inbox triage (reading recruiter replies) still requires the Gmail OAuth setup above regardless.

Two separate emails can go out per `run`, both to `notify_to`, both via whichever path (SMTP or OAuth) is configured — sent by two different modules, from two different slices of the Tracker DB. Notifier (`email_agent/notifier.py`) sends the **match digest**, filtered to postings that scored ≥ `matching.score_threshold` — "here's what's worth your attention." Dashboard (`reporting/dashboard.py`) sends **everything scraped this pass**, matched or not — "here's the full picture." That's also why dry-run still triggers the dashboard email but never the digest: dry-run skips LLM scoring entirely, so there's nothing for Notifier to filter on.

| | Match digest | Dashboard + console logs |
|---|---|---|
| When it sends | Real `run` only | Every `run`, dry-run included |
| What triggers it | Only postings scoring ≥ `matching.score_threshold` | Every `run` where `query_groups` is set, regardless of score |
| Subject | `Job matches — {total} total, {new} new` | `jobhunter dashboard — {total} unique posting(s) ({mode})` |
| Contents | Two sorted sections — "New matches" then "All other matches" (body also states the new/total/scanned counts) | 3 attachments: dashboard `.html`, console `_INFO.txt`, console `_RESULTS.txt` |

"Total" in the match digest is the all-time count of postings that have ever scored at/above `score_threshold` (cumulative across every run, via `Tracker.all_matches`), not just this batch — "new" is what's actually in the "New matches" section (postings not yet notified). The remaining all-time matches (previously notified, still valid) are listed in a second "All other matches" section below it, both sections sorted highest score first.

If no email client is configured, `run` still completes normally and still writes the four output files locally — it just skips sending, with a warning logged.

**Inbox triage (reading recruiter replies) is separate from sending, and always needs Gmail OAuth** — the SMTP app-password path only covers outbound mail. If you haven't completed the OAuth consent screen yet, every real `run` blocks waiting for it. Set `triage_enabled: false` under `email:` in `config.yaml` to skip inbox reading entirely (sending still works via SMTP) until you're ready to finish that one-time setup step:

```yaml
email:
  triage_enabled: false   # default true; set false to stop `run` waiting on Gmail OAuth consent
```

#### What inbox triage actually does when enabled

It's broader and looser than "check replies to my applications" — it has no visibility into what you've sent, so it can't literally look for replies:

1. Pulls **every thread in your inbox from the last 3 days** (`newer_than:3d`, no other filter — not restricted to replies, not restricted to threads connected to a sent application).
2. **Every one of those threads gets classified independently** by the local LLM, with no awareness of what you've applied to — it judges the subject+body text alone: is this job-related, and what status does it imply (`discovered / notified / applied / responded / interview / closed`)?
3. **Only for threads flagged job-related** does it try to connect the dots back to something you're tracking — a fuzzy `LIKE` match on the company name the LLM guessed, against the Tracker DB's company field. A match updates that posting's status (e.g. a reply reading as an interview invite flips it to `interview`); no match still records the thread, just unlinked.

In practice this catches recruiter replies fine, since they show up in the recent-inbox window and mention a company — but a newsletter or unrelated personal email in that same 3-day window gets scanned and classified too (and discarded, since `is_job_related` comes back false). It never sends anything or modifies your mailbox — read-only on the inbox, write-only to the local Tracker DB.

## Compliance note

StepStone, Indeed, jobvector, and LinkedIn have no public search API as of 2026 (confirmed during design — Indeed's was retired in 2024), so all four adapters drive a real browser via Playwright, patched with [`playwright-stealth`](https://pypi.org/project/playwright-stealth/) (masks common automation fingerprints like `navigator.webdriver`) to reduce — not eliminate — fingerprint-based blocks. LinkedIn specifically has documented ToS enforcement (*hiQ v. LinkedIn*) — its adapter is throttled to run at most once per 24h regardless of how often the scheduler fires, uses no stored login/session, and is ordered last. Read the full compliance section in `architecture.html` before increasing scrape frequency on any of the four.

**Each search now walks every results page, not just the first.** `scraping/base.py`'s `paginate_search()` requests `?page=2`, `?page=3`, ... (or each site's equivalent offset param — `start=` for Indeed and LinkedIn) directly by URL, stopping once a page adds no new postings, `search.max_postings_per_search` is reached (if set), or a 40-page safety cap is hit. (An earlier version tried to detect and click a "next"/"load more" control instead; a live run showed that never actually firing — every StepStone search stopped at exactly 25, that site's single-page size — which is why this was rebuilt as direct URL pagination, confirmed live against StepStone/Indeed to pull in genuinely new, non-overlapping postings per page.) This means one search can now issue several page-loads instead of one, on all four sites including LinkedIn — set `max_postings_per_search` in `config.yaml` (see Job preferences above) or drop `"linkedin"` from `sources` if you'd rather not rely on it staying single-page.

**Indeed's extraction was also rebuilt.** A live check found every job link on today's Indeed — sponsored or organic — now routes through a `/pagead/clk` click-tracking redirect, with the old `/rc/clk`/`/viewjob?jk=` href pattern only ever matching stray "similar postings" links instead of real results (explaining Indeed's unusually low, inconsistent counts before this fix). It now reads the real job id off each card's `data-jk` attribute and builds the canonical `/viewjob?jk=<id>` URL directly, instead of following the tracking redirect.

**LinkedIn had two bugs, both confirmed and fixed live.** Its job-link pattern was `/jobs/view/` immediately followed by digits, but a real LinkedIn URL is `/jobs/view/<title-slug>-at-<company-slug>-<numeric-id>` — the id sits at the *end* of the slug, so that pattern never matched a single real link; LinkedIn's adapter was effectively always returning ~0 postings. Fixing the pattern then surfaced a second, more serious issue in the shared `nearest_card_text()` helper used by every adapter: a candidate ancestor selector that matches zero elements for a given link makes Playwright auto-wait its full default action timeout (20s) before falling through to the next one, and LinkedIn's DOM structure hits that non-matching path far more than the others do — one live test measured a *9+ minute* stall processing a single page of results before it was killed. `nearest_card_text()` now passes an explicit `timeout=800` to fail fast instead; a follow-up run with the fix completed in 53s for 30 real postings (with correct titles and companies) across two pages.

**Known limitation:** jobvector currently blocks all requests with a Cloudflare Turnstile challenge (`403`, "Just a moment..."), confirmed to be server-side bot detection that `playwright-stealth`'s JS-level patches don't get past. It's left in `sources` as a harmless no-op (contributes 0 results, costs one wasted request per query) rather than removed, since getting past it for real would need more invasive measures than are appropriate here.

## Project layout

```
src/jobhunter/
  models.py            Pydantic schemas: CandidateProfile, JobPosting, MatchResult
  config.py             config.yaml + .env loader
  llm/                    local Ollama client: schema-constrained JSON + validate/retry loop
  ingestion/             documents -> raw text (OCR fallback for scans)
  extraction/            raw text -> profile.json (local LLM, schema-constrained)
  scraping/               one adapter per job site + shared base/registry
  matching/               profile x posting -> score (local LLM, schema-constrained)
  tracker/                SQLite: dedupe, notification state, application lifecycle
  reporting/              renders the self-contained HTML results dashboard
  email_agent/            Gmail OAuth client + SMTP app-password client (with
                          attachment support), digest sender, inbound triage
  orchestrator/           wires it all together; theme-grouping; scheduler loop
  cli.py                  jobhunter check|extract|run|schedule; live progress
                          logging; captures jobhunter_console_INFO/RESULTS_<timestamp>.txt
tests/                   26 tests covering models, tracker, ingestion, config,
                          and the structured-output plumbing (mocked, no Ollama server needed)
```

`jobhunter run` (and `run --dry-run`) write four files to the project root each time — `jobhunter_results.json` (overwritten each run), plus a timestamped `jobhunter_dashboard_<timestamp>.html`, `jobhunter_console_INFO_<timestamp>.txt`, and `jobhunter_console_RESULTS_<timestamp>.txt` per run — all gitignored (see "What `run` prints and saves" above).

## Tests

```
.venv\Scripts\python -m pytest
```
