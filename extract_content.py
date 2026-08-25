"""
Reads an inventory CSV (from inventory_website.py, or a manually-curated
CSV in the same schema — e.g. your SharePoint additions) and populates a
"Content" column:
  - For normal pages: extracted main-body text from the URL.
  - For gated downloads (Whitepaper/eBook "Download" type): both the
    landing-page copy AND the actual PDF's text, concatenated, so scoring
    sees the real asset, not just the gate page.

Requires: pip install requests beautifulsoup4 pypdf
"""

import csv
import io
import re
import sys
import time

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

HEADERS = {"User-Agent": "Mozilla/5.0 (content-audit-bot)"}


def get_page_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""


def get_page_body(soup: BeautifulSoup) -> str:
    """
    getgenea.com runs an Enfold/Avia-themed WordPress site, which doesn't use
    semantic <article>/<header>/<footer> tags — and puts TWO unrelated <main>
    elements on every page (a CTA banner and a footer sitemap block), neither
    of which is the real body. Real content lives in one of two places
    depending on template:
      - Post-type templates (Blog, Case Study, Whitepaper/eBook landing,
        Webinar): '.single-post-content-inner'.
      - Page-builder templates (Products, Integrations, other Web Pages):
        the '#main' container, once its footer-class sections are stripped.
    Falls back to <body> text if neither pattern matches (e.g. a future
    template change) rather than silently returning the wrong fragment.
    """
    post = soup.find("div", class_="single-post-content-inner")
    if post:
        return post.get_text(separator="\n", strip=True)

    main = soup.find(id="main")
    if main:
        for tag in main.find_all(class_=lambda c: c and "footer" in " ".join(c)):
            tag.decompose()
        text = main.get_text(separator="\n", strip=True)
        if text:
            return text

    return soup.body.get_text(separator="\n", strip=True) if soup.body else ""


def get_page_text(url: str) -> tuple:
    """Returns (title, body_text) for a page; ("", "") on fetch failure."""
    try:
        resp = requests.get(url, timeout=30, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [warn] failed to fetch {url}: {e}", file=sys.stderr)
        return "", ""

    soup = BeautifulSoup(resp.text, "html.parser")
    title = get_page_title(soup)
    text = get_page_body(soup)
    return title, re.sub(r"\n{3,}", "\n\n", text)


def find_pdf_link(url: str) -> str:
    """Look for a direct .pdf link on a gated download landing page."""
    try:
        resp = requests.get(url, timeout=30, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [warn] failed to fetch {url} for PDF link: {e}", file=sys.stderr)
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            return a["href"]
    # Common WP gated-form pattern: PDF referenced in a data attribute or embed
    for tag in soup.find_all(attrs={"data-file": True}):
        if tag["data-file"].lower().endswith(".pdf"):
            return tag["data-file"]
    return ""


def get_pdf_text(pdf_url: str) -> str:
    try:
        resp = requests.get(pdf_url, timeout=60, headers=HEADERS)
        resp.raise_for_status()
        reader = PdfReader(io.BytesIO(resp.content))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        print(f"  [warn] failed to extract PDF at {pdf_url}: {e}", file=sys.stderr)
        return ""


def extract_for_row(url: str, content_type: str) -> tuple:
    """Returns (title, content) for a row."""
    title, landing_text = get_page_text(url)

    if content_type in ("Download", "Whitepaper", "eBook", "Whitepaper/eBook"):
        pdf_url = find_pdf_link(url)
        if pdf_url:
            if pdf_url.startswith("/"):
                base = re.match(r"https?://[^/]+", url).group(0)
                pdf_url = base + pdf_url
            pdf_text = get_pdf_text(pdf_url)
            if pdf_text:
                return title, f"[LANDING PAGE COPY]\n{landing_text}\n\n[GATED PDF CONTENT]\n{pdf_text}"
            else:
                print(f"  [warn] found PDF link but couldn't extract text: {pdf_url}", file=sys.stderr)
        else:
            print(f"  [warn] no direct PDF link found on gated page: {url} — form may require submission first", file=sys.stderr)

    return title, landing_text


def main(input_csv: str, output_csv: str):
    with open(input_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fieldnames = list(rows[0].keys())
    if "Title" not in fieldnames:
        fieldnames.append("Title")
    if "Content" not in fieldnames:
        fieldnames.append("Content")

    for i, row in enumerate(rows):
        print(f"Extracting [{i+1}/{len(rows)}]: {row.get('Link')}")
        title, content = extract_for_row(row["Link"], row.get("Type", ""))
        row["Content"] = content
        if not row.get("Title"):
            row["Title"] = title
        # A real full-site run (464 sequential requests, no delay) got
        # rate-limited/blocked partway through -- pages fetched successfully
        # (no exception) but returned empty content for ~115 rows near the
        # end. A small pause keeps this from recurring.
        time.sleep(0.2)

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {output_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python extract_content.py <input_inventory.csv> <output_with_content.csv>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
