"""
Combines the two independent scoring runs into one workbook with two sheets
-- a literal second Excel tab, matching the dashboard's second view:

  "Marketing Surface"    -- every asset (all 464), landing-page copy scored
                            against the standard 5-factor SEO/conversion
                            rubric (score_content.py). The apples-to-apples
                            leaderboard across the whole site.
  "Gated Asset Quality"  -- the ~26 gated whitepapers/eBooks, scored on the
                            REAL PDF content against a separate sales-
                            enablement rubric (score_gated_assets.py):
                            accuracy, brand, sales usability, substance,
                            next-step clarity. No SEO factor -- it doesn't
                            apply to a document nobody finds via search.

Run this after both score_content.py and score_gated_assets.py have
produced their output files for the quarter.
"""

import sys

import openpyxl
import pandas as pd


def main(marketing_xlsx: str, gated_xlsx: str, output_xlsx: str):
    marketing = pd.read_excel(marketing_xlsx)
    gated = pd.read_excel(gated_xlsx)

    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        marketing.to_excel(writer, sheet_name="Marketing Surface", index=False)
        gated.to_excel(writer, sheet_name="Gated Asset Quality", index=False)

    wb = openpyxl.load_workbook(output_xlsx)
    print(f"Wrote {output_xlsx} with sheets: {wb.sheetnames}")
    print(f"  Marketing Surface: {len(marketing)} rows")
    print(f"  Gated Asset Quality: {len(gated)} rows")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python combine_workbook.py <marketing_scored.xlsx> <gated_scored.xlsx> <output.xlsx>")
        print("  (if <output.xlsx> is the same path as <marketing_scored.xlsx>, it's rewritten in place)")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
