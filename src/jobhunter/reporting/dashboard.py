"""Renders a self-contained HTML dashboard from grouped scrape results.

Single-file output (CSS + JSON data + JS all inline) so it works as a plain
attachment or a double-clickable local file — no server, no external
requests. Mirrors the schema `orchestrator.pipeline._group_by_theme` produces:
{group_name: {"entries": [...], "raw_count": int, "member_queries": [...]}}
"""

from __future__ import annotations

import json

_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Job Search Results</title>
<style>
  :root{
    --bg:#f6f5f1;
    --surface:#ffffff;
    --surface-2:#efece3;
    --ink:#211f1a;
    --ink-soft:#5c584e;
    --ink-faint:#8a8577;
    --line:#dcd8cc;
    --line-strong:#c6c1b1;
    --accent:#a85f26;
    --accent-2:#2b6e67;
    --warn:#9c6a10;
    --code-bg:#efece2;
    --shadow: 0 1px 2px rgba(33,31,26,0.06), 0 8px 24px -12px rgba(33,31,26,0.12);
    --radius: 4px;
    --src-stepstone: #3b6ea5;
    --src-indeed: #7a5296;
    --src-jobvector: #2f8f5b;
    --src-linkedin: #3a5f8a;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      --bg:#17160f; --surface:#201e17; --surface-2:#262319;
      --ink:#ece8db; --ink-soft:#b3ad9b; --ink-faint:#7d7869;
      --line:#38341f; --line-strong:#4a442b;
      --accent:#dd9a58; --accent-2:#6fbdb4; --warn:#dcab4c;
      --code-bg:#1c1a12;
      --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);
      --src-stepstone:#7fa8d4; --src-indeed:#b596d6; --src-jobvector:#6bc797; --src-linkedin:#8fb2dd;
    }
  }
  :root[data-theme="dark"]{
    --bg:#17160f; --surface:#201e17; --surface-2:#262319;
    --ink:#ece8db; --ink-soft:#b3ad9b; --ink-faint:#7d7869;
    --line:#38341f; --line-strong:#4a442b;
    --accent:#dd9a58; --accent-2:#6fbdb4; --warn:#dcab4c;
    --code-bg:#1c1a12;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5);
    --src-stepstone:#7fa8d4; --src-indeed:#b596d6; --src-jobvector:#6bc797; --src-linkedin:#8fb2dd;
  }

  *{ box-sizing: border-box; }
  body{
    margin:0; background: var(--bg); color: var(--ink);
    font-family: Charter, "Iowan Old Style", "Palatino Linotype", Georgia, serif;
    font-size: 16px; line-height: 1.5; -webkit-font-smoothing: antialiased;
  }
  .page{ max-width: 880px; margin: 0 auto; padding: 48px 24px 96px; }

  h1{
    font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    font-weight: 600; font-size: 32px; line-height: 1.15; margin: 8px 0 10px;
    text-wrap: balance;
  }
  .eyebrow{
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 11.5px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--accent);
  }
  header.cover{ border-bottom: 1px solid var(--line-strong); padding-bottom: 22px; margin-bottom: 22px; }
  header.cover p.lede{ font-size: 16.5px; color: var(--ink-soft); max-width: 62ch; margin: 0 0 18px; }
  .meta-row{
    display:flex; flex-wrap:wrap; gap: 8px 26px;
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 13px; color: var(--ink-soft);
  }
  .meta-row b{ color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }

  .controls{
    position: sticky; top: 0; z-index: 5;
    background: var(--bg);
    padding: 14px 0 12px;
    border-bottom: 1px solid var(--line);
    margin-bottom: 18px;
    display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  }
  #search{
    flex: 1 1 220px; min-width: 160px;
    font: inherit; font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 14px; padding: 8px 12px;
    border: 1px solid var(--line-strong); border-radius: var(--radius);
    background: var(--surface); color: var(--ink);
  }
  #search:focus-visible{ outline: 2px solid var(--accent-2); outline-offset: 1px; }
  .src-toggle{
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 12.5px; font-weight: 600; letter-spacing: 0.02em;
    padding: 6px 10px; border-radius: 999px;
    border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink-soft);
    cursor: pointer; user-select: none;
  }
  .src-toggle .dot{ width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .src-toggle[data-active="true"]{ color: var(--ink); border-color: currentColor; background: var(--surface-2); }
  .src-toggle[data-src="stepstone"][data-active="true"]{ color: var(--src-stepstone); }
  .src-toggle[data-src="indeed"][data-active="true"]{ color: var(--src-indeed); }
  .src-toggle[data-src="jobvector"][data-active="true"]{ color: var(--src-jobvector); }
  .src-toggle[data-src="linkedin"][data-active="true"]{ color: var(--src-linkedin); }
  label.noise-toggle{
    display:inline-flex; align-items:center; gap:6px;
    font-size: 12.5px; color: var(--ink-soft); cursor: pointer; white-space: nowrap;
  }
  .count-line{
    font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 12.5px; color: var(--ink-faint); margin-left: auto; white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .group-card{
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
    box-shadow: var(--shadow); margin-bottom: 16px; overflow: hidden;
  }
  .group-card.empty{ box-shadow: none; background: transparent; border-style: dashed; }
  .group-head{
    padding: 12px 16px; background: var(--surface-2); border-bottom: 1px solid var(--line);
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  }
  .group-head-top{ display:flex; align-items: baseline; gap: 10px; }
  .group-name{ font-weight: 600; font-size: 15.5px; color: var(--ink); }
  .group-count{
    font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 12px; color: var(--ink-faint); font-variant-numeric: tabular-nums;
  }
  .group-members{
    margin-top: 4px; font-size: 11.5px; color: var(--ink-faint);
    font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
  }

  ul.rows{ list-style: none; margin: 0; padding: 0; }
  li.row{
    display: grid; grid-template-columns: 84px 1fr; gap: 4px 12px;
    padding: 10px 16px; border-bottom: 1px solid var(--line);
  }
  li.row:last-child{ border-bottom: none; }
  li.row:hover{ background: var(--surface-2); }
  .src-tag{
    font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 10.5px; font-weight: 600; letter-spacing: 0.02em; text-transform: uppercase;
    align-self: start; padding-top: 2px;
  }
  .src-tag.stepstone{ color: var(--src-stepstone); }
  .src-tag.indeed{ color: var(--src-indeed); }
  .src-tag.jobvector{ color: var(--src-jobvector); }
  .src-tag.linkedin{ color: var(--src-linkedin); }
  .row-main a{
    color: var(--ink); text-decoration: none; font-size: 14.5px;
    border-bottom: 1px solid var(--line-strong);
  }
  .row-main a:hover{ color: var(--accent-2); border-color: var(--accent-2); }
  .row-main a:focus-visible{ outline: 2px solid var(--accent-2); outline-offset: 2px; }
  .row-meta{
    display:flex; flex-wrap: wrap; gap: 2px 10px; margin-top: 2px;
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 12px; color: var(--ink-faint);
  }
  .row-meta .via{
    font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 11px; color: var(--accent-2);
  }
  .row.noise{ opacity: 0.55; }
  .row.noise .row-main a{ font-style: italic; }

  .no-results{ color: var(--ink-faint); font-size: 14px; padding: 24px 4px; text-align: center; }

  footer{
    margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--line);
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 12px; color: var(--ink-faint);
  }
</style>
</head>
<body>
<div class="page">
  <header class="cover">
    <span class="eyebrow">__EYEBROW__</span>
    <h1>Job Search Results</h1>
    <p class="lede">__LEDE__</p>
    <div class="meta-row" id="metaRow"></div>
  </header>

  <div class="controls">
    <input id="search" type="text" placeholder="Filter by title, location, or query…" autocomplete="off">
    <div id="srcToggles"></div>
    <label class="noise-toggle"><input type="checkbox" id="hideNoise" checked> Hide "similar listings" noise</label>
    <span class="count-line" id="countLine"></span>
  </div>

  <div id="results"></div>

  <footer>Generated by jobhunter. Source data embedded below, nothing fetched at view time. "via" tags show which of the group's member queries surfaced each posting.</footer>
</div>

<script id="data" type="application/json">__DATA_JSON__</script>
<script>
  const GROUPED = JSON.parse(document.getElementById('data').textContent);
  const NOISE_TITLES = new Set(["Ähnliche Stellenanzeigen von diesem Arbeitgeber anzeigen"]);

  const allSources = new Set();
  let totalRaw = 0, totalUnique = 0;
  for (const g in GROUPED) {
    totalRaw += GROUPED[g].raw_count;
    totalUnique += GROUPED[g].entries.length;
    for (const e of GROUPED[g].entries) allSources.add(e.source);
  }

  const srcToggles = document.getElementById('srcToggles');
  const activeSrc = new Set(allSources);
  [...allSources].sort().forEach(src => {
    const el = document.createElement('span');
    el.className = 'src-toggle';
    el.dataset.src = src;
    el.dataset.active = 'true';
    el.innerHTML = `<span class="dot"></span>${src}`;
    el.addEventListener('click', () => {
      if (activeSrc.has(src)) { activeSrc.delete(src); el.dataset.active = 'false'; }
      else { activeSrc.add(src); el.dataset.active = 'true'; }
      render();
    });
    srcToggles.appendChild(el);
  });

  document.getElementById('metaRow').innerHTML = `
    <span><b>${Object.keys(GROUPED).length}</b> groups</span>
    <span><b>${[...allSources].join(', ')}</b> sources</span>
    <span><b>${totalRaw}</b> raw matches</span>
    <span><b>${totalUnique}</b> unique postings</span>
  `;

  const searchEl = document.getElementById('search');
  const hideNoiseEl = document.getElementById('hideNoise');
  const resultsEl = document.getElementById('results');
  const countLineEl = document.getElementById('countLine');

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function render() {
    const q = searchEl.value.trim().toLowerCase();
    const hideNoise = hideNoiseEl.checked;
    let shown = 0, matched = 0;
    resultsEl.innerHTML = '';

    for (const groupName in GROUPED) {
      const group = GROUPED[groupName];
      const entries = group.entries.filter(e => {
        if (!activeSrc.has(e.source)) return false;
        if (hideNoise && NOISE_TITLES.has(e.title)) return false;
        if (q) {
          const haystack = (e.title + ' ' + e.location + ' ' + e.company + ' ' + e.queries.join(' ')).toLowerCase();
          if (!haystack.includes(q)) return false;
        }
        return true;
      });
      matched += entries.length;

      if (entries.length === 0 && (q || !activeSrc.size)) continue;
      shown++;

      const card = document.createElement('div');
      card.className = 'group-card' + (entries.length === 0 ? ' empty' : '');

      const head = document.createElement('div');
      head.className = 'group-head';
      head.innerHTML = `
        <div class="group-head-top">
          <span class="group-name">${escapeHtml(groupName)}</span>
          <span class="group-count">${entries.length} unique${entries.length !== group.raw_count ? ` · ${group.raw_count} raw matches` : ''}</span>
        </div>
        <div class="group-members">${group.member_queries.map(escapeHtml).join(' · ')}</div>`;
      card.appendChild(head);

      if (entries.length === 0) {
        const note = document.createElement('div');
        note.style.padding = '10px 16px 14px';
        note.style.fontSize = '13px';
        note.style.color = 'var(--ink-faint)';
        note.style.fontStyle = 'italic';
        note.textContent = 'no matches found';
        card.appendChild(note);
      } else {
        const ul = document.createElement('ul');
        ul.className = 'rows';
        for (const e of entries) {
          const li = document.createElement('li');
          li.className = 'row' + (NOISE_TITLES.has(e.title) ? ' noise' : '');
          const locBits = [e.company, e.location].filter(Boolean).join(' · ');
          li.innerHTML = `
            <span class="src-tag ${e.source}">${e.source}</span>
            <div class="row-main">
              ${e.url ? `<a href="${escapeHtml(e.url)}" target="_blank" rel="noopener">${escapeHtml(e.title)}</a>` : escapeHtml(e.title)}
              <div class="row-meta">
                ${locBits ? `<span>${escapeHtml(locBits)}</span>` : ''}
                <span class="via">via: ${e.queries.map(escapeHtml).join(', ')}</span>
              </div>
            </div>`;
          ul.appendChild(li);
        }
        card.appendChild(ul);
      }
      resultsEl.appendChild(card);
    }

    if (shown === 0) {
      resultsEl.innerHTML = '<p class="no-results">No results match the current filters.</p>';
    }
    countLineEl.textContent = `showing ${matched} of ${totalUnique} unique`;
  }

  searchEl.addEventListener('input', render);
  hideNoiseEl.addEventListener('change', render);
  render();
</script>
</body></html>
"""


def render_dashboard_html(by_group: dict, *, dry_run: bool) -> str:
    total_queries = len({q for g in by_group.values() for q in g["member_queries"]})
    mode = "dry-run scrape" if dry_run else "run"
    eyebrow = f"jobhunter · {mode}"
    lede = (
        f"All postings found across your {total_queries} configured queries, grouped into "
        f"{len(by_group)} theme clusters and deduplicated by URL within each cluster"
        + (" — no matching or emailing performed" if dry_run else " — scored, tracked, and notified as usual")
        + ". Click a title to open the listing."
    )
    html = _TEMPLATE.replace("__EYEBROW__", eyebrow)
    html = html.replace("__LEDE__", lede)
    html = html.replace("__DATA_JSON__", json.dumps(by_group, ensure_ascii=False))
    return html
