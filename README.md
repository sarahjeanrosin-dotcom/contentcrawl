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
├── score_content.py          # runs the rubric via Claude API, writes scores + suggestions
├── diff_quarters.py          # compares this run's scores to last quarter's
├── data/
│   ├── inventory_YYYY-QQ.csv
│   ├── with_content_YYYY-QQ.csv
│   ├── scored_YYYY-QQ.xlsx
│   └── diff_YYYY-QQ.csv
└── run_audit.py               # orchestrates the steps end-to-end
```

**SharePoint is on hold for now** — Sarah wants to hand-pick which SharePoint
assets go into the audit rather than auto-including everything in the
Marketing library. For now: add SharePoint rows manually to the inventory
CSV in the same schema (Link = SharePoint URL, Type = whatever fits) before
running `extract_content.py`. The `inventory_sharepoint.py` script can be
built later once the manual list stabilizes and it's clear what "include"
should mean.

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
- **Gated PDFs (Whitepapers/eBooks)**: this is scored on the real asset, not
  just the landing page. The script fetches the landing page, looks for a
  direct `.pdf` link in the page HTML, downloads it, and extracts its text
  with `pypdf`. Both landing-page copy and PDF text are combined into the
  `Content` field so the scorer sees the whole picture.
  - Caveat: some gated PDFs only reveal their download link after a form
    submission (no direct link in the page source). The script logs a
    warning for any download page where it couldn't find a direct PDF link
    — those will need the PDF URL added by hand (there's likely a copy
    already in SharePoint/OneDrive per the doc-audit notes, which is a
    faster source than reverse-engineering the gated form).
- Manually-added SharePoint rows: same extraction logic applies once a
  reachable file URL is in the `Link` column.
- Cache extracted text locally so re-scoring doesn't require re-fetching
  unchanged files (compare against stored last-modified date).

## Step 3 — Scoring (`score_content.py`)
For each asset, one Claude API call with the extracted text + a fixed
rubric prompt (see below). Even weighting, 20 points per factor:

1. **SEO** — title/H1, meta description, header structure, keyword
   targeting, internal linking
2. **Brand & Messaging** — matches current positioning/product names,
   no deprecated claims
3. **Freshness & Accuracy** — last-updated recency, references to
   current products/integrations/pricing
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
Composite Score | Action Flag | Notes | Suggestions | Last Audited`

## Step 4 — Quarterly Diff (`diff_quarters.py`)
- Load this quarter's and last quarter's scored files
- Flag: new assets (not in prior quarter), removed assets, score deltas
  beyond a threshold (e.g. ±10 points), and anything still flagged
  Update/Refresh two quarters running (chronic problem content)

## Running it
```
python run_audit.py --quarter 2026-Q4
```
Produces `data/scored_2026-Q4.xlsx` and `data/diff_2026-Q4.csv`.

## Open items to confirm before first run
- SharePoint: deferred — will be added manually, row by row, until scope
  is clearer
- Gated PDFs with no direct link in page source: need the PDF URL supplied
  manually (check SharePoint/OneDrive copies first)
- Rate limiting: hundreds of assets × 1 API call each — budget for API
  cost and runtime per quarter
