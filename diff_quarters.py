"""
Compares this quarter's scored inventory (.xlsx from score_content.py) against
last quarter's and flags:
  - New assets      — in this quarter's inventory but not the prior one
  - Removed assets   — in the prior inventory but not this one
  - Score Delta      — Composite Score moved by more than DELTA_THRESHOLD
  - Chronic          — flagged Update or Refresh in both quarters running

Requires: pip install pandas openpyxl
"""

import sys

import pandas as pd

DELTA_THRESHOLD = 10
CHRONIC_FLAGS = {"Update", "Refresh"}


def load(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df["Link"] = df["Link"].astype(str).str.strip()
    return df.set_index("Link")


def main(prior_xlsx: str, current_xlsx: str, output_csv: str):
    prior = load(prior_xlsx)
    current = load(current_xlsx)

    prior_links = set(prior.index)
    current_links = set(current.index)

    rows = []

    for link in sorted(current_links - prior_links):
        rows.append({"Link": link, "Change": "New", "Detail": "Not present in prior quarter"})

    for link in sorted(prior_links - current_links):
        rows.append({"Link": link, "Change": "Removed", "Detail": "No longer in current inventory"})

    for link in sorted(current_links & prior_links):
        prev_row = prior.loc[link]
        curr_row = current.loc[link]

        try:
            prev_score = float(prev_row["Composite Score"])
            curr_score = float(curr_row["Composite Score"])
        except (KeyError, ValueError, TypeError):
            prev_score = curr_score = None

        if prev_score is not None and curr_score is not None:
            delta = curr_score - prev_score
            if abs(delta) >= DELTA_THRESHOLD:
                direction = "improved" if delta > 0 else "declined"
                rows.append({
                    "Link": link,
                    "Change": "Score Delta",
                    "Detail": f"Composite {direction}: {prev_score:.0f} -> {curr_score:.0f} ({delta:+.0f})",
                })

        prev_flag = str(prev_row.get("Action Flag", ""))
        curr_flag = str(curr_row.get("Action Flag", ""))
        if prev_flag in CHRONIC_FLAGS and curr_flag in CHRONIC_FLAGS:
            rows.append({
                "Link": link,
                "Change": "Chronic",
                "Detail": f"Flagged '{curr_flag}' two quarters running",
            })

    out = pd.DataFrame(rows, columns=["Link", "Change", "Detail"])
    out.to_csv(output_csv, index=False)
    print(f"Wrote {len(rows)} diff rows to {output_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python diff_quarters.py <prior_scored.xlsx> <current_scored.xlsx> <output_diff.csv>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
