"""
Scores each inventoried content asset against the 5-factor rubric using the
Claude API. Reads an inventory CSV (with a "Content" column already
populated by extract_content.py), writes a scored .xlsx.

Requires: pip install anthropic openpyxl pandas
Requires: ANTHROPIC_API_KEY environment variable set.
"""

import json
import os
import sys
import time

import pandas as pd
from anthropic import Anthropic

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

RUBRIC_PROMPT = """You are auditing one piece of Genea marketing content (Genea is a \
cloud-native physical access control / smart building SaaS company). Score it 0-20 on \
each of the following five factors, then sum for a composite 0-100 score.

1. SEO — title/H1 quality, meta description presence, header structure, keyword \
   targeting, internal linking opportunities.
2. Brand & Messaging — matches current Genea positioning (cloud-native, non-proprietary \
   hardware, "extend beyond the door"), correct current product names, no deprecated \
   claims or competitor comparisons that may be stale.
3. Freshness & Accuracy — does the content reference current products, integrations, \
   or figures that could be outdated? Penalize content that reads as stale.
4. Readability & Quality — clarity, structure, grammar, appropriate length for the format.
5. CTA & Conversion Clarity — is there a clear, appropriate next step (demo, download, \
   contact)?

Also provide concrete, specific improvement suggestions — not generic advice. Reference
actual phrases, headers, or gaps in the content provided. If the composite score is 80+,
suggestions can be an empty list. Below 80, give 3-5 suggestions ordered by expected impact
(highest-impact first), each one sentence and actionable (e.g. "Add a meta description
targeting 'cloud-based access control for schools' — none currently exists" rather than
"improve SEO").

Respond ONLY with valid JSON, no markdown fences, in this exact shape:
{{"seo_score": int, "brand_score": int, "freshness_score": int, "readability_score": int, \
"cta_score": int, "composite_score": int, "action_flag": "Retain|Optimize|Update|Refresh", \
"notes": "1-2 sentence summary of the biggest issue and biggest strength", \
"suggestions": ["suggestion 1", "suggestion 2", ...]}}

Title: {title}
Type: {content_type}
Last Updated: {last_updated}
Content:
{content}
"""


def score_one(title, content_type, last_updated, content, max_chars=8000):
    prompt = RUBRIC_PROMPT.format(
        title=title,
        content_type=content_type,
        last_updated=last_updated or "unknown",
        content=(content or "")[:max_chars],
    )
    # 500 was too tight: a full 5-suggestion response commonly runs 400-540
    # output tokens, so about half of real responses were getting cut off
    # mid-string (stop_reason "max_tokens") and silently failing to parse,
    # leaving that row's scores blank. 1024 leaves real headroom.
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        reason = f" (stop_reason={response.stop_reason})" if response.stop_reason != "end_turn" else ""
        print(f"  [warn] could not parse response for '{title}'{reason}: {text[:200]}", file=sys.stderr)
        return None


def main(input_csv: str, output_xlsx: str):
    df = pd.read_csv(input_csv)
    if "Content" not in df.columns:
        raise SystemExit("Input CSV needs a 'Content' column — run extract_content.py first.")

    score_cols = ["SEO Score", "Brand Score", "Freshness Score", "Readability Score",
                  "CTA Score", "Composite Score", "Action Flag", "Notes", "Suggestions",
                  "Last Audited"]
    for col in score_cols:
        # dtype=object, not the bare "" default: pandas 3.x infers a strict
        # string dtype from an empty-string column, which then rejects the
        # ints (seo_score, composite_score, etc.) we assign into it below.
        df[col] = pd.Series([""] * len(df), dtype="object")

    today = pd.Timestamp.now().strftime("%Y-%m-%d")

    for idx, row in df.iterrows():
        print(f"Scoring [{idx+1}/{len(df)}]: {row.get('Title') or row.get('Link')}")
        result = score_one(row.get("Title", ""), row.get("Type", ""),
                            row.get("Last Updated", ""), row.get("Content", ""))
        if result:
            df.at[idx, "SEO Score"] = result.get("seo_score", "")
            df.at[idx, "Brand Score"] = result.get("brand_score", "")
            df.at[idx, "Freshness Score"] = result.get("freshness_score", "")
            df.at[idx, "Readability Score"] = result.get("readability_score", "")
            df.at[idx, "CTA Score"] = result.get("cta_score", "")
            df.at[idx, "Composite Score"] = result.get("composite_score", "")
            df.at[idx, "Action Flag"] = result.get("action_flag", "")
            df.at[idx, "Notes"] = result.get("notes", "")
            suggestions = result.get("suggestions", [])
            df.at[idx, "Suggestions"] = "\n".join(f"- {s}" for s in suggestions) if suggestions else ""
        df.at[idx, "Last Audited"] = today
        time.sleep(0.5)  # gentle rate limiting

    df.drop(columns=["Content"], errors="ignore").to_excel(output_xlsx, index=False)
    print(f"Wrote {output_xlsx}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python score_content.py <input_inventory.csv> <output_scored.xlsx>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
