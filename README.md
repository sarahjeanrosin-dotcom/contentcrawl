# Genea Marketing Content Audit — Project Spec

## Purpose
A recurring (quarterly) programmatic audit of all Genea marketing content —
website + SharePoint — that inventories every asset, pulls its content, and
scores it against a consistent rubric so the team knows what to Update,
Optimize, Refresh, or Retain.

## Why Claude Code
This needs to (a) crawl the full website beyond what a search-first fetch
tool allows, (b) enumerate every SharePoint file via the Microsoft 365 MCP
connector in a loop, (c) persist results across quarters in a real repo, and
(d) re-run on a schedule with a diff against the prior run. Claude Code (or
any local Claude agent with MCP + shell access) can do all four; the
claude.ai chat interface can do none of them at scale.

## Architecture

```
audit-project/
├── inventory_website.py      # crawls sitemap.xml, extracts every URL
├── extract_content.py        # pulls page text + gated PDF text per item
├── extract_help_center.py    # crawls help.getgenea.com into a reference corpus
├── help_reference.py         # keyword-overlap retrieval over that corpus
├── score_content.py          # runs the marketing rubric via Claude API, writes scores + suggestions
├── diff_quarters.py          # compares this run's scores to last quarter's
├── build_gated_content.py    # one-time: real PDF text for gated assets, pulled from SharePoint
├── score_gated_assets.py     # runs the separate gated-asset rubric via Claude API
├── combine_workbook.py       # merges both scoring runs into one two-sheet workbook
├── build_site.py             # renders the scored workbook into site/ (both tabs)
├── run_audit.py              # orchestrates the website side end-to-end: inventory -> extract -> score -> diff -> build_site
├── data/
│   ├── inventory_YYYY-QQ.csv
│   ├── with_content_YYYY-QQ.csv
│   ├── scored_YYYY-QQ.xlsx           # two sheets after combine_workbook.py: Marketing Surface + Gated Asset Quality
│   ├── gated_pdf_content.json        # captured gated-PDF text (output of build_gated_content.py)
│   ├── scored_gated_assets_YYYY-QQ.xlsx
│   └── diff_YYYY-QQ.csv
└── site/                      # static dashboard, Netlify-deployed
    ├── index.html              # two tabs: Marketing Surface, Gated Asset Quality
    ├── data.json / scored_latest.csv           # Marketing Surface tab
    └── gated_data.json / gated_scored_latest.csv  # Gated Asset Quality tab
```

**SharePoint**: full auto-enumeration of the Marketing library is still on
hold — Sarah wants to hand-pick which SharePoint assets go into the audit.
What *is* automated now is the one category that needed it most: the ~26
gated whitepapers/eBooks that sit behind a JS-driven HubSpot form with no
static PDF link, so `extract_content.py` can't reach them on its own. Those
are captured by hand once via `build_gated_content.py` — pulling the real
PDF text from SharePoint through the Microsoft 365 MCP connector in a live
session — and then scored automatically every quarter from that cached
capture (see "Gated Assets" below). Any other SharePoint asset can still be
added manually to the inventory CSV in the same schema (Link = SharePoint
URL, Type = whatever fits) before running `extract_content.py`.

## Step 1 — Website Inventory (`inventory_website.py`)
- Fetch `https://www.getgenea.com/sitemap.xml` (and any sub-sitemaps it
  references — WordPress sites typically split by post type: post-sitemap,
  page-sitemap, case-study-sitemap, etc.)
- Parse every `<loc>` URL, `<lastmod>` date
- Classify `Type` by URL pattern (`/blog/` → Blog, `/case-studies/` →
  Case Study, `/downloads/` → Whitepaper/eBook, `/webinars/` → Webinar,
  everything else → Web Page)
- Output: one row per URL with Link, Last Updated (from sitemap), Type

## Step 2 — Content Extraction (`extract_content.py`)
- Website pages: fetch main-body text (strips nav/footer/header boilerplate)
- **Gated PDFs (Whitepapers/eBooks)**: the script fetches the landing page,
  looks for a direct `.pdf` link in the page HTML, downloads it, and
  extracts its text with `pypdf`, combining landing-page copy and PDF text
  into the `Content` field.
  - Caveat: most gated PDFs only reveal their download link after a form
    submission (no direct link in the page source), so this only catches a
    minority of them. The script logs a warning for any download page where
    it couldn't find a direct PDF link. Those ~26 assets are the ones
    `build_gated_content.py` captures by hand instead (see "Gated Assets"
    below) — they're scored on the real document either way, just through
    a different path depending on whether a direct link exists.
- Manually-added SharePoint rows: same extraction logic applies once a
  reachable file URL is in the `Link` column.
- Cache extracted text locally so re-scoring doesn't require re-fetching
  unchanged files (compare against stored last-modified date).

## Step 3 — Scoring (`score_content.py`)
This is the "Marketing Surface" rubric — it scores what's live on the
website (landing-page copy included), i.e. "is this page good at
converting a visitor into a lead." For each asset, one Claude API call
with the extracted text + a fixed rubric prompt. Even weighting, 20 points
per factor:

1. **SEO** — title/H1, meta description, header structure, keyword
   targeting, internal linking
2. **Brand & Messaging** — matches current positioning/product names,
   no deprecated claims
3. **Freshness & Accuracy** — last-updated recency, references to
   current products/integrations/pricing. Grounded against
   `data/help_center.json` (crawled by `extract_help_center.py`) via
   keyword-overlap retrieval in `help_reference.py`, so this is checked
   against Genea's actual current product docs rather than just the
   model's general knowledge.
4. **Readability & Quality** — clarity, structure, grammar, appropriate
   length
5. **CTA & Conversion Clarity** — clear next step, working links

Composite = sum of five scores (0–100).
Action Flag: 80+ Retain · 60–79 Optimize · 40–59 Update · <40 Refresh/Retire

**Suggestions for low scorers**: for anything scoring below 80, Claude also
returns 3–5 concrete, specific fixes ordered by impact (e.g. "Add a meta
description targeting X — none currently exists," not generic advice like
"improve SEO"). Assets scoring 80+ get an empty suggestions list since
they're already in good shape.

Output columns appended to inventory:
`SEO Score | Brand Score | Freshness Score | Readability Score | CTA Score |
Composite Score | Action Flag | Notes | Suggestions | Impact | Effort |
Priority | Last Audited`

## Step 4 — Quarterly Diff (`diff_quarters.py`)
- Load this quarter's and last quarter's scored files
- Flag: new assets (not in prior quarter), removed assets, score deltas
  beyond a threshold (e.g. ±10 points), and anything still flagged
  Update/Refresh two quarters running (chronic problem content)

## Gated Assets — Separate Rubric (`build_gated_content.py`, `score_gated_assets.py`)
The ~26 gated whitepapers/eBooks get scored twice, on purpose, because
they're answering two different questions:
- **Marketing Surface** (above) scores the *landing page* — is it good at
  converting a visitor into a lead. SEO applies here; the page is meant to
  be found via search.
- **Gated Asset Quality** scores the *actual document* a prospect gets
  after converting, or that a rep hands directly to a deal. SEO is
  meaningless for a static PDF nobody finds via search, so this uses its
  own 5-factor rubric instead, even weighting, 20 points per factor:

  1. **Accuracy & Currency** — references to current products,
     integrations, pricing; grounded against the same help-center corpus
     as Step 3
  2. **Brand & Messaging** — current positioning, no stale competitor
     comparisons
  3. **Sales Usability** — would a rep confidently attach this to a live
     deal email today
  4. **Substance & Depth** — enough real value to justify gating it behind
     a lead-capture form
  5. **Next-Step Clarity** — does the document itself end with a clear CTA

  Composite/Action Flag/suggestions/Impact/Effort/Priority work the same
  way as Step 3, just as a separate set of columns.

**Getting the content**: these PDFs sit behind a JS-driven HubSpot form
with no static link, so they can't be crawled automatically. Capture is a
manual, occasional step — `build_gated_content.py` is a one-time script
that gets edited by hand (during a live session with SharePoint access via
the Microsoft 365 MCP connector) whenever the list of gated assets changes,
and writes the result to `data/gated_pdf_content.json`. Once that file
exists, `score_gated_assets.py` re-scores from it automatically every
quarter — no live SharePoint session needed unless a new gated asset
appears or an existing PDF gets swapped out.

## Combining and Publishing (`combine_workbook.py`, `build_site.py`)
`combine_workbook.py` merges the Step 3 output and the gated-asset output
into one workbook, two sheets — `Marketing Surface` and
`Gated Asset Quality` — matching the dashboard's two tabs. `build_site.py`
then reads that workbook and writes both `site/data.json` +
`site/scored_latest.csv` (Marketing Surface tab) and
`site/gated_data.json` + `site/gated_scored_latest.csv` (Gated Asset
Quality tab). `site/index.html` renders both as separate tabs, each with
its own score columns and filters, since the two rubrics don't share axes.

`build_site.py` deliberately does **not** publish the gated tab's `Source`
column (the real internal SharePoint file path, e.g. `Sales2/SALES Main
Folder/Content/Whitepapers/...`) into `site/` — that's fine to have in the
internal workbook under `data/`, but it has no reason to be on the public
dashboard. It's still visible in `data/scored_gated_assets_YYYY-QQ.xlsx`
and the combined `data/scored_YYYY-QQ.xlsx` for internal reference.

Netlify redeploys the dashboard automatically whenever `site/` changes and
gets pushed. It does need one manual setup step, though — see below.

## Access Control
The dashboard sits behind whole-site HTTP Basic Auth, enforced by a Netlify
Edge Function (`netlify/edge-functions/basic-auth.js`, wired up in
`netlify.toml`) that runs on every request — including the JSON/CSV data
files, not just `index.html`. This exists because the dashboard has content
that shouldn't be publicly readable even with the `Source` column removed:
candid internal audit notes on both tabs (e.g. calling out exactly why an
asset is weak), and the fact that `Gated Asset Quality` scores are on real
document content in the first place.

**Setup (one-time, in the Netlify UI — not something this repo can do on
its own):**
1. Site settings → Environment variables → add `DASHBOARD_USER` and
   `DASHBOARD_PASS`
2. Trigger a redeploy so the edge function picks them up

**It fails closed.** If those two env vars aren't set, every request
returns a 500 instead of silently serving the site unprotected — so a
misconfigured deploy is *inaccessible*, never *unprotected*. If the
dashboard is returning 500s, this is the first thing to check.

This is shared-credential Basic Auth, not per-user login — treat the
password like any other shared team password (don't paste it in plaintext
into Slack, rotate it if it leaks). `site/index.html` also carries a
`noindex, nofollow` meta tag as defense-in-depth against accidental search
engine indexing, though that's not a substitute for the auth itself.

## Running it
```
python run_audit.py --quarter 2026-Q4
```
Runs the website side end-to-end (inventory → extract → score → diff) and
rebuilds `site/` from `data/scored_2026-Q4.xlsx`. This does **not** yet run
the gated-asset pipeline automatically — run those separately (only needed
each quarter for `score_gated_assets.py`; `build_gated_content.py` only
needs re-running when the gated asset list itself changes):
```
python score_gated_assets.py data/gated_pdf_content.json data/scored_gated_assets_2026-Q4.xlsx
python combine_workbook.py data/scored_2026-Q4.xlsx data/scored_gated_assets_2026-Q4.xlsx data/scored_2026-Q4.xlsx
python build_site.py data/scored_2026-Q4.xlsx
```
Then `git add`, commit, and push to deploy.

## Open items to confirm before first run
- SharePoint: full auto-enumeration is still deferred — anything beyond
  the gated-asset capture gets added to the inventory CSV manually
- `run_audit.py` doesn't yet call the gated-asset steps automatically —
  worth folding in once the manual-capture cadence settles
- Rate limiting: hundreds of assets × 1 API call each — budget for API
  cost and runtime per quarter
