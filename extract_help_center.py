"""
Crawls help.getgenea.com (Genea's Intercom-backed public help center) and
builds a local reference corpus of current product documentation, used by
score_content.py to check marketing content for staleness/inaccuracy
against what the software actually does today.

Each article page ships its real content server-rendered inside a Next.js
__NEXT_DATA__ script tag (props.pageProps.articleContent), as a list of
typed blocks (paragraph / heading / image / ...) — far more reliable than
scraping rendered HTML, and it's what this pulls from.

Output: data/help_center.json — a list of
  {title, url, description, text, lastUpdated}

Requires: pip install requests beautifulsoup4
"""

import json
import re
import sys

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (content-audit-bot)"}
SITEMAP_URL = "https://help.getgenea.com/sitemap.xml"

TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(text: str) -> str:
    return TAG_RE.sub("", text or "").strip()


def list_article_urls(sitemap_url: str = SITEMAP_URL) -> list:
    resp = requests.get(sitemap_url, timeout=30, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "xml")
    return [loc.text.strip() for loc in soup.find_all("loc") if loc.text.strip()]


def extract_article(url: str) -> dict:
    try:
        resp = requests.get(url, timeout=30, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [warn] failed to fetch {url}: {e}", file=sys.stderr)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        print(f"  [warn] no __NEXT_DATA__ on {url} — template may have changed", file=sys.stderr)
        return None

    try:
        data = json.loads(tag.string)
        article = data["props"]["pageProps"]["articleContent"]
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  [warn] couldn't parse articleContent on {url}: {e}", file=sys.stderr)
        return None

    parts = []
    for block in article.get("blocks", []):
        text = strip_tags(block.get("text", ""))
        if text:
            parts.append(f"## {text}" if block.get("type") == "heading" else text)

    return {
        "title": article.get("title", ""),
        "url": url,
        "description": article.get("description", ""),
        "text": "\n".join(parts),
        "lastUpdated": article.get("lastUpdatedDate", ""),
    }


def main(output_json: str = "data/help_center.json"):
    urls = list_article_urls()
    print(f"Found {len(urls)} help center articles")

    articles = []
    for i, url in enumerate(urls):
        print(f"Extracting [{i+1}/{len(urls)}]: {url}")
        article = extract_article(url)
        if article:
            articles.append(article)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(articles)}/{len(urls)} articles to {output_json}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/help_center.json")
