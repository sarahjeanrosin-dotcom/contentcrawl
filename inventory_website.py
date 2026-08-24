"""
Crawls https://www.getgenea.com/sitemap.xml (and any sub-sitemaps it
references) and writes an inventory CSV of every page: Link, Last Updated,
Type, Title.

WordPress sites typically split their sitemap by post type (post-sitemap.xml,
page-sitemap.xml, case-study-sitemap.xml, etc.) under one sitemap index —
this follows the index recursively so every sub-sitemap gets crawled.

Title is left blank here; extract_content.py fills it in from the live page
when it pulls body copy (avoids fetching every URL twice).

SharePoint rows are NOT included — per the project spec, add those by hand
to the output CSV (same columns: Link, Last Updated, Type, Title) before
running extract_content.py.

Requires: pip install requests beautifulsoup4 lxml
"""

import csv
import re
import sys

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (content-audit-bot)"}
SITEMAP_URL = "https://www.getgenea.com/sitemap.xml"

# Checked in order; first match wins. Adjust/extend as the site's URL
# patterns evolve.
TYPE_RULES = [
    (r"/blog/", "Blog"),
    (r"/case-studies?/", "Case Study"),
    (r"/downloads?/", "Whitepaper/eBook"),
    (r"/webinars?/", "Webinar"),
]
DEFAULT_TYPE = "Web Page"


def classify(url: str) -> str:
    for pattern, type_name in TYPE_RULES:
        if re.search(pattern, url, re.IGNORECASE):
            return type_name
    return DEFAULT_TYPE


def fetch_xml(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=30, headers=HEADERS)
    resp.raise_for_status()
    return BeautifulSoup(resp.content, "xml")


def collect_urls(sitemap_url: str, seen: set) -> list:
    if sitemap_url in seen:
        return []
    seen.add(sitemap_url)

    print(f"Fetching sitemap: {sitemap_url}", file=sys.stderr)
    try:
        soup = fetch_xml(sitemap_url)
    except Exception as e:
        print(f"  [warn] failed to fetch {sitemap_url}: {e}", file=sys.stderr)
        return []

    rows = []
    if soup.find("sitemapindex") is not None:
        for sitemap_tag in soup.find_all("sitemap"):
            loc = sitemap_tag.find("loc")
            if loc and loc.text:
                rows.extend(collect_urls(loc.text.strip(), seen))
    else:
        for url_tag in soup.find_all("url"):
            loc = url_tag.find("loc")
            if not loc or not loc.text:
                continue
            link = loc.text.strip()
            lastmod_tag = url_tag.find("lastmod")
            rows.append({
                "Link": link,
                "Last Updated": lastmod_tag.text.strip() if lastmod_tag else "",
                "Type": classify(link),
                "Title": "",
            })
    return rows


def main(output_csv: str, sitemap_url: str = SITEMAP_URL):
    rows = collect_urls(sitemap_url, seen=set())
    if not rows:
        print("No URLs found — check the sitemap URL and site availability.", file=sys.stderr)

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Link", "Last Updated", "Type", "Title"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output_csv}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage: python inventory_website.py <output_inventory.csv> [sitemap_url]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else SITEMAP_URL)
