"""
Orchestrates the quarterly audit end-to-end: inventory -> extract -> score -> diff.

Usage:
  python run_audit.py --quarter 2026-Q4

First run for a quarter only builds data/inventory_<quarter>.csv from the
website sitemap, then stops — this is your chance to hand-add any
SharePoint rows (see README) before spending API calls scoring anything.
Run the same command again and it picks up from the existing inventory CSV
and runs extraction, scoring, and (if a prior quarter's scored file exists)
the diff.

Flags:
  --force-inventory   re-crawl the sitemap even if data/inventory_<quarter>.csv
                       already exists (overwrites it — any hand-added rows
                       will be lost)
  --prior-quarter      defaults to the quarter immediately before --quarter
                       (e.g. --quarter 2026-Q4 -> 2026-Q3); pass this if your
                       comparison quarter doesn't follow that pattern
  --sitemap-url        defaults to inventory_website.SITEMAP_URL
"""

import argparse
import os
import re
import sys

import diff_quarters
import extract_content
import inventory_website
import score_content

DATA_DIR = "data"


def prior_quarter_label(quarter: str) -> str:
    m = re.match(r"^(\d{4})-Q([1-4])$", quarter)
    if not m:
        return ""
    year, q = int(m.group(1)), int(m.group(2))
    if q == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{q - 1}"


def main():
    parser = argparse.ArgumentParser(description="Run the quarterly Genea marketing content audit.")
    parser.add_argument("--quarter", required=True, help="e.g. 2026-Q4")
    parser.add_argument("--prior-quarter", default=None,
                         help="defaults to the quarter immediately before --quarter")
    parser.add_argument("--force-inventory", action="store_true",
                         help="re-crawl the sitemap even if the inventory CSV already exists")
    parser.add_argument("--sitemap-url", default=inventory_website.SITEMAP_URL)
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)

    inventory_csv = os.path.join(DATA_DIR, f"inventory_{args.quarter}.csv")
    with_content_csv = os.path.join(DATA_DIR, f"with_content_{args.quarter}.csv")
    scored_xlsx = os.path.join(DATA_DIR, f"scored_{args.quarter}.xlsx")
    diff_csv = os.path.join(DATA_DIR, f"diff_{args.quarter}.csv")

    if os.path.exists(inventory_csv) and not args.force_inventory:
        print(f"=== Step 1: skipped, using existing {inventory_csv} ===")
    else:
        print("=== Step 1: Website inventory ===")
        inventory_website.main(inventory_csv, args.sitemap_url)
        print(f"\nInventory written to {inventory_csv}.")
        print("Add any SharePoint rows by hand now (same columns: Link, Last Updated, Type, Title),")
        print("then re-run this exact command to continue with extraction, scoring, and diff.")
        return

    print("=== Step 2: Content extraction ===")
    extract_content.main(inventory_csv, with_content_csv)

    print("=== Step 3: Scoring ===")
    score_content.main(with_content_csv, scored_xlsx)

    prior_quarter = args.prior_quarter or prior_quarter_label(args.quarter)
    prior_xlsx = os.path.join(DATA_DIR, f"scored_{prior_quarter}.xlsx") if prior_quarter else None
    if prior_xlsx and os.path.exists(prior_xlsx):
        print(f"=== Step 4: Diff against {prior_quarter} ===")
        diff_quarters.main(prior_xlsx, scored_xlsx, diff_csv)
    else:
        print(f"=== Step 4: skipped — no prior scored file found ({prior_xlsx}) ===")

    print(f"\nDone. See {scored_xlsx}" + (f" and {diff_csv}" if prior_xlsx and os.path.exists(prior_xlsx) else "."))


if __name__ == "__main__":
    main()
