"""
Converts a scored .xlsx (from score_content.py) into the static dashboard in
site/: site/data.json (what the dashboard renders) and site/scored_latest.csv
(what the dashboard's Download CSV button serves). Netlify redeploys the
dashboard automatically whenever site/ changes and gets pushed.

Usage:
  python build_site.py <scored.xlsx>
  python build_site.py                 # auto-picks the newest data/scored_*.xlsx
"""

import glob
import json
import os
import sys

import pandas as pd

SCORE_COLS = ["SEO Score", "Brand Score", "Freshness Score", "Readability Score", "CTA Score"]


def newest_scored_file() -> str:
    candidates = sorted(glob.glob(os.path.join("data", "scored_*.xlsx")), key=os.path.getmtime)
    if not candidates:
        sys.exit("No data/scored_*.xlsx found. Run score_content.py first, or pass a path explicitly.")
    return candidates[-1]


def main(scored_xlsx: str):
    df = pd.read_excel(scored_xlsx)
    df = df.where(pd.notna(df), "")

    records = []
    for _, row in df.iterrows():
        suggestions = str(row.get("Suggestions", "") or "")
        records.append({
            "title": row.get("Title") or row.get("Link", ""),
            "link": row.get("Link", ""),
            "type": row.get("Type", ""),
            "lastUpdated": str(row.get("Last Updated", "")),
            "seo": row.get("SEO Score", ""),
            "brand": row.get("Brand Score", ""),
            "freshness": row.get("Freshness Score", ""),
            "readability": row.get("Readability Score", ""),
            "cta": row.get("CTA Score", ""),
            "composite": row.get("Composite Score", ""),
            "actionFlag": row.get("Action Flag", ""),
            "notes": row.get("Notes", ""),
            "suggestions": [s.lstrip("- ").strip() for s in suggestions.split("\n") if s.strip()],
            "impact": row.get("Impact", ""),
            "effort": row.get("Effort", ""),
            "priority": row.get("Priority", ""),
            "lastAudited": str(row.get("Last Audited", "")),
        })

    os.makedirs("site", exist_ok=True)

    with open(os.path.join("site", "data.json"), "w", encoding="utf-8") as f:
        json.dump({
            "source": os.path.basename(scored_xlsx),
            "generatedFrom": scored_xlsx,
            "items": records,
        }, f, indent=2, ensure_ascii=False)

    df.to_csv(os.path.join("site", "scored_latest.csv"), index=False)

    print(f"Wrote site/data.json ({len(records)} items) and site/scored_latest.csv, from {scored_xlsx}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else newest_scored_file()
    main(path)
