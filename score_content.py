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
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import pandas as pd
from anthropic import Anthropic

import help_reference

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

# Lazy-loaded (not at import time): run_audit.py imports this module before
# it's had a chance to build data/help_center.json on a first-time run, so
# loading eagerly here would permanently freeze HELP_CORPUS empty for that
# whole process. Loaded once, on first actual use, and cached from then on.
_HELP_CORPUS = None


def get_help_corpus():
    global _HELP_CORPUS
    if _HELP_CORPUS is None:
        _HELP_CORPUS = help_reference.load_corpus()
    return _HELP_CORPUS

RUBRIC_PROMPT = """You are auditing one piece of Genea marketing content (Genea is a \
cloud-native physical access control / smart building SaaS company). Score it 0-20 on \
each of the following five factors, then sum for a composite 0-100 score.

1. SEO — title/H1 quality, meta description presence, header structure, keyword \
   targeting, internal linking opportunities.
2. Brand & Messaging — matches current Genea positioning (cloud-native, non-proprietary \
   hardware, "extend beyond the door"), correct current product names, no deprecated \
   claims or competitor comparisons that may be stale.
3. Freshness & Accuracy — does the content reference current products, integrations, or \
   figures that could be outdated? If a HELP CENTER REFERENCE section is provided below, \
   treat it as ground truth for how the product actually works today: flag any place the \
   content contradicts it, describes a workflow/feature that reference shows has changed, \
   or misses a current capability the reference shows exists that the content could be \
   promoting. If no reference section is provided, or none of it is relevant to this \
   content, fall back to general judgment. Penalize content that reads as stale.
4. Readability & Quality — clarity, structure, grammar, appropriate length for the format.
5. CTA & Conversion Clarity — is there a clear, appropriate next step (demo, download, \
   contact)?

Also provide concrete, specific improvement suggestions — not generic advice. Reference
actual phrases, headers, or gaps in the content provided. Where a suggestion is grounded
in the HELP CENTER REFERENCE, say so explicitly and name the specific article (e.g. "Per
the help article 'How do I create an Access Group?', this page still describes the older
workflow — update it to match" — invent nothing; only cite what's actually in the
reference below). If the composite score is 80+, suggestions can be an empty list. Below
80, give 3-5 suggestions ordered by expected impact (highest-impact first), each one
sentence and actionable (e.g. "Add a meta description targeting 'cloud-based access
control for schools' — none currently exists" rather than "improve SEO").

If there are any suggestions, also rate the suggested work as a whole on two dimensions, so
low-effort/high-value fixes can be triaged first:
- impact: "High" if implementing these suggestions would meaningfully move SEO, conversion,
  brand accuracy, or credibility; "Low" if it's a minor/cosmetic improvement.
- effort: "Low" if this is a same-day copy/metadata edit with no new assets, research, or
  design needed; "High" if it requires new content creation (e.g. a rewrite, new case study
  data, design work, or engineering).
Leave impact and effort as empty strings if there are no suggestions (composite 80+).

Respond ONLY with valid JSON, no markdown fences, in this exact shape:
{{"seo_score": int, "brand_score": int, "freshness_score": int, "readability_score": int, \
"cta_score": int, "composite_score": int, "action_flag": "Retain|Optimize|Update|Refresh", \
"notes": "1-2 sentence summary of the biggest issue and biggest strength", \
"suggestions": ["suggestion 1", "suggestion 2", ...], \
"impact": "High|Low|", "effort": "Low|High|"}}

Title: {title}
Type: {content_type}
Last Updated: {last_updated}
Content:
{content}
{reference}
"""


# Priority is computed here, not trusted to the model's own judgment call,
# so it's applied consistently across every asset rather than drifting
# call-to-call. Classic impact/effort quadrant: "low hanging fruit" is
# High impact + Low effort.
PRIORITY_MATRIX = {
    ("High", "Low"): "Quick Win",
    ("High", "High"): "Major Project",
    ("Low", "Low"): "Fill-In",
    ("Low", "High"): "Low Priority",
}


def compute_priority(impact, effort):
    return PRIORITY_MATRIX.get((impact, effort), "")


def build_reference_block(title, content):
    relevant = help_reference.find_relevant(get_help_corpus(), title, content)
    formatted = help_reference.format_reference(relevant)
    if not formatted:
        return ""
    return f"\nHELP CENTER REFERENCE (current product docs — {len(relevant)} article(s), use per factor 3 above):\n{formatted}\n"


def score_one(title, content_type, last_updated, content, max_chars=8000, max_retries=4):
    prompt = RUBRIC_PROMPT.format(
        title=title,
        content_type=content_type,
        last_updated=last_updated or "unknown",
        content=(content or "")[:max_chars],
        reference=build_reference_block(title, content),
    )
    # 500 was too tight: a full 5-suggestion response commonly runs 400-540
    # output tokens, so about half of real responses were getting cut off
    # mid-string (stop_reason "max_tokens") and silently failing to parse,
    # leaving that row's scores blank. 1024 leaves real headroom.
    #
    # A ~464-call, hour-long run WILL hit a transient network blip somewhere
    # (confirmed: the first real full run died on call #1 with a DNS
    # lookup failure) -- retry with backoff rather than letting one hiccup
    # kill the whole run.
    response = None
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.APIConnectionError as e:
            if attempt == max_retries - 1:
                print(f"  [warn] connection error for '{title}' after {max_retries} attempts: {e}", file=sys.stderr)
                return None
            wait = 2 ** attempt
            print(f"  [warn] connection error for '{title}' (attempt {attempt+1}/{max_retries}), retrying in {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code == 429 or e.status_code >= 500:
                if attempt == max_retries - 1:
                    print(f"  [warn] API error {e.status_code} for '{title}' after {max_retries} attempts", file=sys.stderr)
                    return None
                wait = 2 ** attempt
                print(f"  [warn] API error {e.status_code} for '{title}' (attempt {attempt+1}/{max_retries}), retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  [warn] API error {e.status_code} for '{title}': {e}", file=sys.stderr)
                return None
    if response is None:
        return None

    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        reason = f" (stop_reason={response.stop_reason})" if response.stop_reason != "end_turn" else ""
        print(f"  [warn] could not parse response for '{title}'{reason}: {text[:200]}", file=sys.stderr)
        return None


SCORE_COLS = ["SEO Score", "Brand Score", "Freshness Score", "Readability Score",
              "CTA Score", "Composite Score", "Action Flag", "Notes", "Suggestions",
              "Impact", "Effort", "Priority", "Last Audited"]


def main(input_csv: str, output_xlsx: str, checkpoint_every: int = 15, max_workers: int = 6):
    df = pd.read_csv(input_csv)
    if "Content" not in df.columns:
        raise SystemExit("Input CSV needs a 'Content' column — run extract_content.py first.")

    for col in SCORE_COLS:
        # dtype=object, not the bare "" default: pandas 3.x infers a strict
        # string dtype from an empty-string column, which then rejects the
        # ints (seo_score, composite_score, etc.) we assign into it below.
        df[col] = pd.Series([""] * len(df), dtype="object")

    # Resume support: a ~464-call run takes 45-60 min and WILL occasionally
    # hit something it can't recover from (confirmed: a DNS blip killed the
    # first real attempt at call #1). If output_xlsx already has results
    # from a prior attempt, reuse them by Link and only score what's left,
    # instead of re-paying for and re-running everything from scratch.
    if os.path.exists(output_xlsx):
        prior = pd.read_excel(output_xlsx)
        if "Link" in prior.columns and "Last Audited" in prior.columns:
            # pd.notna(), not a string/truthiness check: an unscored cell
            # reads back from Excel as float NaN, and str(nan) is the
            # non-empty string "nan" -- a truthiness check would treat
            # every never-scored row as "already done" and copy NaN into
            # it forever instead of actually scoring it.
            prior_by_link = {
                row["Link"]: row for _, row in prior.iterrows()
                if pd.notna(row.get("Last Audited"))
            }
            resumed = 0
            for idx, row in df.iterrows():
                prior_row = prior_by_link.get(row.get("Link"))
                if prior_row is not None:
                    for col in SCORE_COLS:
                        df.at[idx, col] = prior_row.get(col, "")
                    resumed += 1
            if resumed:
                print(f"Resuming: {resumed}/{len(df)} rows already scored in a prior attempt, reusing them.")

    today = pd.Timestamp.now().strftime("%Y-%m-%d")

    def save():
        df.drop(columns=["Content"], errors="ignore").to_excel(output_xlsx, index=False)

    def apply_result(idx, result):
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
            impact = result.get("impact", "") or ""
            effort = result.get("effort", "") or ""
            df.at[idx, "Impact"] = impact
            df.at[idx, "Effort"] = effort
            df.at[idx, "Priority"] = compute_priority(impact, effort)
            # Only stamped on success: resume treats a non-empty Last
            # Audited as "done, skip it" -- a row that failed (result is
            # None) should stay eligible for retry on the next resume,
            # not get silently skipped forever.
            df.at[idx, "Last Audited"] = today

    def score_task(idx, title, content_type, last_updated, content):
        # Runs in a worker thread. Deliberately touches nothing but its own
        # local arguments and the network call -- no DataFrame access here,
        # so there's no concurrent-pandas-mutation risk to reason about.
        # Anything unexpected (not just the connection/API errors score_one
        # already retries) is caught here so one bad row can't take down
        # the pool or the other rows.
        try:
            return idx, score_one(title, content_type, last_updated, content)
        except Exception as e:
            print(f"  [warn] unexpected error scoring '{title}': {e}", file=sys.stderr)
            return idx, None

    pending = [
        idx for idx, _ in df.iterrows()
        if not (pd.notna(df.at[idx, "Last Audited"]) and str(df.at[idx, "Last Audited"]).strip())
    ]

    if not pending:
        print("Nothing left to score -- all rows already done.")
    else:
        print(f"Scoring {len(pending)} row(s) with {max_workers} concurrent workers...")
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    score_task, idx,
                    df.at[idx, "Title"], df.at[idx, "Type"],
                    df.at[idx, "Last Updated"], df.at[idx, "Content"],
                )
                for idx in pending
            ]
            for future in as_completed(futures):
                idx, result = future.result()
                apply_result(idx, result)  # all DataFrame writes happen here, main thread only
                completed += 1
                title = df.at[idx, "Title"] or df.at[idx, "Link"]
                print(f"Scored [{completed}/{len(pending)}]: {title}")
                if completed % checkpoint_every == 0:
                    save()
                    print(f"  [checkpoint] saved progress ({completed}/{len(pending)} this run)")

    save()
    print(f"Wrote {output_xlsx}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python score_content.py <input_inventory.csv> <output_scored.xlsx>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
