"""
Converts a scored .xlsx into the static dashboard in site/. Netlify
redeploys the dashboard automatically whenever site/ changes and gets pushed.

Reads a workbook produced by combine_workbook.py: two sheets, "Marketing
Surface" (every asset, landing-page copy vs. the standard SEO/conversion
rubric) and "Gated Asset Quality" (the gated whitepapers/eBooks, real PDF
content vs. the separate sales-enablement rubric). Each becomes its own
JSON + CSV pair so the dashboard can render them as two distinct tabs
without conflating two different rubrics into one score column.

A workbook with only a "Marketing Surface" sheet (or no sheet names at all,
i.e. a single-sheet file from before the gated-asset rubric existed) still
works -- the gated tab is simply empty.

Usage:
  python build_site.py <scored.xlsx>
  python build_site.py                 # auto-picks the newest data/scored_*.xlsx
"""

import glob
import json
import os
import sys

import pandas as pd


def newest_scored_file() -> str:
    candidates = sorted(glob.glob(os.path.join("data", "scored_*.xlsx")), key=os.path.getmtime)
    if not candidates:
        sys.exit("No data/scored_*.xlsx found. Run score_content.py first, or pass a path explicitly.")
    return candidates[-1]


def load_sheet(scored_xlsx: str, sheet_name: str, fallback_to_first: bool = False) -> pd.DataFrame:
    try:
        df = pd.read_excel(scored_xlsx, sheet_name=sheet_name)
    except ValueError:
        if not fallback_to_first:
            return pd.DataFrame()
        df = pd.read_excel(scored_xlsx)  # single-sheet file predating the two-sheet workbook
    return df.where(pd.notna(df), "")


def marketing_records(df: pd.DataFrame) -> list:
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
    return records


def gated_records(df: pd.DataFrame) -> list:
    # Deliberately omits the "Source" column (real internal SharePoint file
    # paths, e.g. "Sales2/SALES Main Folder/Content/Whitepapers/...") --
    # that's fine to have in the internal workbook in data/, but it has no
    # business being published to site/, even behind Basic Auth.
    records = []
    for _, row in df.iterrows():
        suggestions = str(row.get("Suggestions", "") or "")
        records.append({
            "title": row.get("Title") or row.get("Link", ""),
            "link": row.get("Link", ""),
            "accuracy": row.get("Accuracy Score", ""),
            "brand": row.get("Brand Score", ""),
            "salesUsability": row.get("Sales Usability Score", ""),
            "substance": row.get("Substance Score", ""),
            "nextStep": row.get("Next Step Score", ""),
            "composite": row.get("Composite Score", ""),
            "actionFlag": row.get("Action Flag", ""),
            "notes": row.get("Notes", ""),
            "suggestions": [s.lstrip("- ").strip() for s in suggestions.split("\n") if s.strip()],
            "impact": row.get("Impact", ""),
            "effort": row.get("Effort", ""),
            "priority": row.get("Priority", ""),
            "lastAudited": str(row.get("Last Audited", "")),
        })
    return records


def main(scored_xlsx: str):
    marketing_df = load_sheet(scored_xlsx, "Marketing Surface", fallback_to_first=True)
    gated_df = load_sheet(scored_xlsx, "Gated Asset Quality", fallback_to_first=False)

    os.makedirs("site", exist_ok=True)

    with open(os.path.join("site", "data.json"), "w", encoding="utf-8") as f:
        json.dump({
            "source": os.path.basename(scored_xlsx),
            "generatedFrom": scored_xlsx,
            "items": marketing_records(marketing_df),
        }, f, indent=2, ensure_ascii=False)
    marketing_df.drop(columns=["Content"], errors="ignore").to_csv(os.path.join("site", "scored_latest.csv"), index=False)

    with open(os.path.join("site", "gated_data.json"), "w", encoding="utf-8") as f:
        json.dump({
            "source": os.path.basename(scored_xlsx),
            "generatedFrom": scored_xlsx,
            "items": gated_records(gated_df),
        }, f, indent=2, ensure_ascii=False)
    gated_df.drop(columns=["Content", "Source"], errors="ignore").to_csv(os.path.join("site", "gated_scored_latest.csv"), index=False)

    print(f"Wrote site/data.json ({len(marketing_df)} items) and site/scored_latest.csv")
    print(f"Wrote site/gated_data.json ({len(gated_df)} items) and site/gated_scored_latest.csv")
    print(f"  from {scored_xlsx}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else newest_scored_file()
    main(path)
