"""
Scores the actual gated PDF content (data/gated_pdf_content.json) against a
SEPARATE 5-axis rubric built for sales enablement, not SEO/conversion. The
landing page each PDF sits behind is already scored by score_content.py
against the standard marketing rubric -- that's a different question ("is
this webpage good at converting a visitor into a lead") from what this
script answers ("is the actual document any good once someone has it").

Why a different rubric: SEO is close to meaningless for a static PDF nobody
finds via search -- it's read post-conversion, or handed directly to a
prospect by a rep. What matters instead is whether the document is
accurate, on-brand, actually useful to a rep in a live deal, substantial
enough to justify the lead-gen gate, and ends with a next step.

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

client = Anthropic()

_HELP_CORPUS = None


def get_help_corpus():
    global _HELP_CORPUS
    if _HELP_CORPUS is None:
        _HELP_CORPUS = help_reference.load_corpus()
    return _HELP_CORPUS


RUBRIC_PROMPT = """You are auditing one gated sales-enablement asset (a whitepaper or eBook \
PDF) for Genea, a cloud-native physical access control / smart building SaaS company. This \
document sits behind a lead-capture form on the website -- it is read by a prospect who \
already converted, or handed directly to a deal by a sales rep. It is NOT an SEO or organic \
discovery surface, so do not score it on SEO grounds. Score it 0-20 on each of the following \
five factors, then sum for a composite 0-100 score.

1. Accuracy & Currency — does the content reference current products, integrations, pricing, \
   or figures that could be outdated? If a HELP CENTER REFERENCE section is provided below, \
   treat it as ground truth for how the product actually works today: flag any place the \
   content contradicts it, describes a workflow/feature that reference shows has changed, or \
   uses old product naming. If no reference section is provided or none is relevant, fall \
   back to general judgment. Penalize content that reads as stale (references to discontinued \
   programs like COVID-era features presented as current, dead links implied, etc.)
2. Brand & Messaging — matches current Genea positioning (cloud-native, non-proprietary \
   hardware, "extend beyond the door"), correct current product names, no deprecated claims \
   or competitor comparisons that may be stale or inflammatory in a way that could embarrass \
   a rep sending this to a prospect.
3. Sales Usability — would a rep confidently attach this to a live deal email today? \
   Consider: professional tone, no glaring errors or placeholder text, appropriately scoped \
   for its stated audience, doesn't require the rep to caveat or apologize for anything in it.
4. Substance & Depth — does this asset deliver enough real value to justify gating it behind \
   a lead-capture form? A one-page teaser or thin content doesn't earn the friction of a form \
   fill. Reward genuine frameworks, data, worked examples, or reference detail a prospect \
   couldn't get from the blog.
5. Next-Step Clarity — does the document itself (not just the landing page around it) end \
   with a clear, appropriate call to action for where the reader should go next (demo, \
   contact sales, related resource)?

Also provide concrete, specific improvement suggestions — not generic advice. Reference \
actual phrases, sections, or gaps in the content provided. Where a suggestion is grounded in \
the HELP CENTER REFERENCE, say so explicitly and name the specific article (e.g. "Per the \
help article 'How do I create an Access Group?', this document still describes the older \
workflow" — invent nothing; only cite what's actually in the reference below). If the \
composite score is 80+, suggestions can be an empty list. Below 80, give 3-5 suggestions \
ordered by expected impact (highest-impact first), each one sentence and actionable.

If there are any suggestions, also rate the suggested work as a whole on two dimensions, so \
low-effort/high-value fixes can be triaged first:
- impact: "High" if implementing these suggestions would meaningfully move accuracy, deal \
  usability, or credibility; "Low" if it's a minor/cosmetic improvement.
- effort: "Low" if this is a same-day copy/metadata edit; "High" if it requires new content \
  creation (new data, a rewrite, design work, or sourcing a current customer example).
Leave impact and effort as empty strings if there are no suggestions (composite 80+).

Respond ONLY with valid JSON, no markdown fences, in this exact shape:
{{"accuracy_score": int, "brand_score": int, "sales_usability_score": int, "substance_score": int, \
"next_step_score": int, "composite_score": int, "action_flag": "Retain|Optimize|Update|Refresh", \
"notes": "1-2 sentence summary of the biggest issue and biggest strength", \
"suggestions": ["suggestion 1", "suggestion 2", ...], \
"impact": "High|Low|", "effort": "Low|High|"}}

Title: {title}
Source: {source}
Content:
{content}
{reference}
"""

# Same fixed quadrant as score_content.py, kept independent on purpose --
# this script has its own rubric and shouldn't import internals from that
# module just to share four lines of logic.
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
    return f"\nHELP CENTER REFERENCE (current product docs — {len(relevant)} article(s), use per factor 1 above):\n{formatted}\n"


def score_one(title, source, content, max_chars=10000, max_retries=4):
    prompt = RUBRIC_PROMPT.format(
        title=title,
        source=source,
        content=(content or "")[:max_chars],
        reference=build_reference_block(title, content),
    )
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
            print(f"  [warn] connection error for '{title}' (attempt {attempt+1}/{max_retries}), retrying in {wait}s", file=sys.stderr)
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


SCORE_COLS = ["Accuracy Score", "Brand Score", "Sales Usability Score", "Substance Score",
              "Next Step Score", "Composite Score", "Action Flag", "Notes", "Suggestions",
              "Impact", "Effort", "Priority", "Last Audited"]


def main(input_json="data/gated_pdf_content.json", output_xlsx="data/scored_gated_assets_2026-Q3.xlsx", max_workers=6):
    with open(input_json, encoding="utf-8") as f:
        assets = json.load(f)

    df = pd.DataFrame(assets)
    df = df.rename(columns={"link": "Link", "title": "Title", "sharepoint_source": "Source", "text": "Content"})

    for col in SCORE_COLS:
        df[col] = pd.Series([""] * len(df), dtype="object")

    if os.path.exists(output_xlsx):
        prior = pd.read_excel(output_xlsx)
        if "Link" in prior.columns and "Last Audited" in prior.columns:
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
            df.at[idx, "Accuracy Score"] = result.get("accuracy_score", "")
            df.at[idx, "Brand Score"] = result.get("brand_score", "")
            df.at[idx, "Sales Usability Score"] = result.get("sales_usability_score", "")
            df.at[idx, "Substance Score"] = result.get("substance_score", "")
            df.at[idx, "Next Step Score"] = result.get("next_step_score", "")
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
            df.at[idx, "Last Audited"] = today

    def score_task(idx, title, source, content):
        try:
            return idx, score_one(title, source, content)
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
        print(f"Scoring {len(pending)} gated asset(s) with {max_workers} concurrent workers...")
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(score_task, idx, df.at[idx, "Title"], df.at[idx, "Source"], df.at[idx, "Content"])
                for idx in pending
            ]
            for future in as_completed(futures):
                idx, result = future.result()
                apply_result(idx, result)
                completed += 1
                print(f"Scored [{completed}/{len(pending)}]: {df.at[idx, 'Title']}")
                if completed % 10 == 0:
                    save()
                    print(f"  [checkpoint] saved progress ({completed}/{len(pending)} this run)")

    save()
    print(f"Wrote {output_xlsx}")


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else "data/gated_pdf_content.json",
        sys.argv[2] if len(sys.argv) > 2 else "data/scored_gated_assets_2026-Q3.xlsx",
    )
