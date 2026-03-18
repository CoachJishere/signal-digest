"""Scoring: trust weight, cross-source frequency, novelty."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to",
    "for", "of", "and", "or", "but", "with", "by", "from", "this", "that",
    "it", "as", "be", "has", "have", "had", "not", "no", "will", "can",
    "do", "does", "did", "about", "how", "what", "when", "where", "who",
    "why", "new", "just", "now", "up", "out", "so", "if", "than", "its",
    "all", "more", "some", "into", "over", "after", "also", "been", "would",
    "could", "should", "may", "might", "get", "got", "one", "two", "like",
    "your", "you", "they", "their", "them", "our", "his", "her", "she", "he",
    "we", "my", "me", "us", "i",
}

SEEN_TOPICS_PATH = Path(__file__).parent.parent / "data" / "seen_topics.json"


def title_tokens(title: str) -> set[str]:
    """Extract meaningful tokens from a title."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


def score_items(items: list[dict], config_id: str) -> list[dict]:
    """Score all items and return sorted by score descending.

    Mutates items in-place, adding 'score' and 'score_breakdown'.
    """
    seen_topics = _load_seen_topics(config_id)

    # Pre-compute title tokens for all items
    item_tokens = [(item, title_tokens(item["title"])) for item in items]

    for item, tokens in item_tokens:
        trust = item["source_trust_weight"]
        freq = _cross_source_frequency(item, tokens, item_tokens)
        novelty = _novelty_score(tokens, seen_topics)

        item["score"] = trust + freq + novelty
        item["score_breakdown"] = {
            "trust": trust,
            "frequency": freq,
            "novelty": novelty,
        }

    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def update_seen_topics(items: list[dict], config_id: str, threshold: int = 4) -> None:
    """Add high-scoring items to seen_topics for novelty tracking."""
    all_topics = _load_all_seen_topics()

    if config_id not in all_topics:
        all_topics[config_id] = {"topics": []}

    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        if item.get("score", 0) >= threshold:
            tokens = list(title_tokens(item["title"]))
            if tokens:
                all_topics[config_id]["topics"].append({
                    "tokens": tokens,
                    "title": item["title"],
                    "first_seen": now,
                })

    _save_seen_topics(all_topics)


def _cross_source_frequency(
    item: dict, tokens: set[str], all_item_tokens: list[tuple[dict, set[str]]]
) -> int:
    """Count distinct other sources mentioning a similar topic. Returns 0-3."""
    if not tokens:
        return 0

    other_sources = set()
    for other_item, other_tokens in all_item_tokens:
        if other_item["source_name"] == item["source_name"]:
            continue
        if jaccard_similarity(tokens, other_tokens) >= 0.35:
            other_sources.add(other_item["source_name"])

    count = len(other_sources)
    return min(count, 3)


def _novelty_score(tokens: set[str], seen_topics: list[dict]) -> int:
    """Score novelty against recently seen topics. Returns 0, 1, or 2."""
    if not tokens:
        return 1

    for topic in seen_topics:
        seen_tokens = set(topic["tokens"])
        sim = jaccard_similarity(tokens, seen_tokens)
        if sim >= 0.5:
            return 0  # Already covered recently

    for topic in seen_topics:
        seen_tokens = set(topic["tokens"])
        sim = jaccard_similarity(tokens, seen_tokens)
        if sim >= 0.25:
            return 1  # Related but new angle

    return 2  # Completely novel


def _load_seen_topics(config_id: str) -> list[dict]:
    """Load and prune seen topics for a specific config."""
    all_topics = _load_all_seen_topics()

    if config_id not in all_topics:
        return []

    # Prune entries older than 7 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    topics = all_topics[config_id].get("topics", [])
    pruned = []
    for topic in topics:
        try:
            first_seen = datetime.fromisoformat(topic["first_seen"])
            if first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=timezone.utc)
            if first_seen >= cutoff:
                pruned.append(topic)
        except (ValueError, KeyError):
            pass  # Drop malformed entries

    # Save pruned version back
    all_topics[config_id]["topics"] = pruned
    _save_seen_topics(all_topics)

    return pruned


def _load_all_seen_topics() -> dict:
    """Load the full seen_topics.json file."""
    if not SEEN_TOPICS_PATH.exists():
        return {}
    try:
        with open(SEEN_TOPICS_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logger.warning("Could not read seen_topics.json, starting fresh")
        return {}


def _save_seen_topics(data: dict) -> None:
    """Write seen_topics.json."""
    SEEN_TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_TOPICS_PATH, "w") as f:
        json.dump(data, f, indent=2)
