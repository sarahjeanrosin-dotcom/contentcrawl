"""
Lightweight keyword-overlap retrieval over the local help center corpus
(data/help_center.json, built by extract_help_center.py). Used by
score_content.py to ground Freshness & Accuracy scoring in Genea's actual
current product documentation instead of just the model's general
knowledge about the company. Deliberately not embedding-based: plain token
overlap is enough to answer "is this marketing page talking about a real,
current feature," and it avoids an extra API dependency and cost on every
one of ~464 scoring calls.
"""

import json
import os
import re
from collections import Counter

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "of", "is", "are", "was", "were", "be", "been", "being", "with", "this",
    "that", "these", "those", "it", "its", "as", "by", "from", "you", "your",
    "we", "our", "i", "do", "does", "how", "what", "when", "where", "why",
    "can", "will", "would", "should", "not", "no", "yes", "have", "has",
    "had", "my", "me", "us",
}
TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> Counter:
    return Counter(w for w in TOKEN_RE.findall((text or "").lower()) if w not in STOPWORDS and len(w) > 2)


def load_corpus(path: str = "data/help_center.json") -> list:
    """Returns [] (silently) if the corpus hasn't been built yet — reference
    grounding is an enhancement, not a hard requirement to run scoring."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        articles = json.load(f)
    for a in articles:
        # Title words counted 3x: a title match is a much stronger relevance
        # signal than an incidental body-text match. Fields can be None (not
        # just missing/"") for some Intercom articles, so coerce each one.
        title = a.get("title") or ""
        description = a.get("description") or ""
        text = a.get("text") or ""
        pool = (title + " ") * 3 + description + " " + text[:1500]
        a["_tokens"] = _tokens(pool)
    return articles


def find_relevant(corpus: list, title: str, content: str, top_k: int = 5, min_score: int = 2) -> list:
    query = _tokens((title or "") + " " + (content or "")[:3000])
    if not query or not corpus:
        return []
    scored = []
    for a in corpus:
        overlap = sum(min(query[w], a["_tokens"][w]) for w in query if w in a["_tokens"])
        if overlap >= min_score:
            scored.append((overlap, a))
    scored.sort(key=lambda pair: -pair[0])
    return [a for _, a in scored[:top_k]]


def format_reference(articles: list, max_chars_each: int = 500) -> str:
    if not articles:
        return ""
    parts = []
    for a in articles:
        text = (a.get("text") or "")[:max_chars_each]
        description = a.get("description") or ""
        parts.append(f"### {a['title']} ({a['url']})\n{description}\n{text}")
    return "\n\n".join(parts)
