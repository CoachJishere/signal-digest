"""RSS ingestion, normalization, deduplication, and full content fetching."""

from __future__ import annotations

import html
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import feedparser
import trafilatura
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

USER_AGENT = "signal-digest/1.0 (newsletter bot)"


def run_ingestion(config: dict) -> list[dict]:
    """Fetch, normalize, filter, and deduplicate items from all sources."""
    all_items = []
    failed_sources = []

    for source in config["sources"]:
        try:
            entries = _fetch_feed(source)
            all_items.extend(entries)
            logger.info(f"Fetched {len(entries)} items from {source['name']}")
        except Exception as e:
            logger.warning(f"Failed to fetch {source['name']}: {e}")
            failed_sources.append(source["name"])

    if not all_items:
        raise RuntimeError(
            f"All sources failed. Failed sources: {', '.join(failed_sources)}"
        )

    if failed_sources:
        logger.warning(f"Skipped {len(failed_sources)} failed sources: {', '.join(failed_sources)}")

    # Filter to 24-hour lookback window
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    items = [item for item in all_items if item["published"] >= cutoff]
    logger.info(f"After 24h filter: {len(items)} items (from {len(all_items)} total)")

    # Deduplicate
    items = _deduplicate(items)
    logger.info(f"After dedup: {len(items)} items")

    return items


def fetch_full_content_for_items(
    items: list[dict], config: dict
) -> int:
    """Fetch full article content for top-scoring items that qualify.

    Mutates items in-place. Returns count of successful fetches.
    """
    threshold = config.get("score_threshold", 4)
    max_fetches = config.get("max_full_content_fetches", 5)
    max_medium = config.get("max_medium_fetches", 3)

    # Filter to items that qualify for full content fetch
    candidates = [
        item for item in items
        if item.get("fetch_full_content") and item.get("score", 0) >= threshold
    ]
    # Sort by score descending, take top candidates
    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)

    fetch_count = 0
    medium_count = 0

    for item in candidates:
        if fetch_count >= max_fetches:
            break

        is_medium = _is_medium_url(item["url"])
        if is_medium and medium_count >= max_medium:
            continue

        logger.info(f"Fetching full content: {item['title'][:60]}...")
        content = _fetch_article_content(item["url"])

        if content:
            item["full_content"] = content
            fetch_count += 1
            if is_medium:
                medium_count += 1
        else:
            logger.warning(f"Full content fetch failed, using RSS excerpt: {item['url']}")

        # Polite delay between requests
        time.sleep(random.uniform(2.0, 3.0))

    logger.info(
        f"Full content fetches: {fetch_count} total ({medium_count} from Medium)"
    )
    return fetch_count


def _fetch_feed(source: dict) -> list[dict]:
    """Fetch and normalize a single RSS feed."""
    url = source["url"]
    feed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})

    if feed.bozo and not feed.entries:
        raise RuntimeError(f"Feed parse error for {url}: {feed.bozo_exception}")

    items = []
    for entry in feed.entries:
        item = _normalize_entry(entry, source)
        if item:
            items.append(item)

    return items


def _normalize_entry(entry: dict, source: dict) -> dict | None:
    """Normalize a feedparser entry into a standard item dict."""
    title = entry.get("title", "").strip()
    link = entry.get("link", "").strip()

    if not title or not link:
        return None

    # Parse published date
    published = None
    for date_field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(date_field)
        if parsed:
            try:
                published = datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
            break

    if not published:
        # Try string parsing
        for date_str_field in ("published", "updated"):
            date_str = entry.get(date_str_field, "")
            if date_str:
                try:
                    published = dateparser.parse(date_str)
                    if published and published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass
                break

    if not published:
        published = datetime.now(timezone.utc)

    # Extract summary, strip HTML
    summary = entry.get("summary", "") or entry.get("description", "") or ""
    summary = _strip_html(summary).strip()
    # Truncate very long summaries
    if len(summary) > 2000:
        summary = summary[:2000] + "..."

    return {
        "title": title,
        "url": link,
        "published": published,
        "source_name": source["name"],
        "source_trust_weight": source["trust_weight"],
        "signal_type": source["signal_type"],
        "fetch_full_content": source.get("fetch_full_content", False),
        "summary": summary,
        "full_content": None,
        "score": 0.0,
        "score_breakdown": {},
    }


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication: lowercase host, strip tracking params."""
    parsed = urlparse(url.lower())
    # Strip common tracking query params
    tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "ref", "source"}
    if parsed.query:
        params = parse_qs(parsed.query)
        filtered = {k: v for k, v in params.items() if k not in tracking_params}
        query = urlencode(filtered, doseq=True)
    else:
        query = ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def _deduplicate(items: list[dict]) -> list[dict]:
    """Deduplicate items by normalized URL."""
    seen_urls = {}
    deduped = []

    for item in items:
        norm_url = _normalize_url(item["url"])
        if norm_url in seen_urls:
            # Keep the one from the higher-trust source
            existing = seen_urls[norm_url]
            if item["source_trust_weight"] > existing["source_trust_weight"]:
                deduped.remove(existing)
                seen_urls[norm_url] = item
                deduped.append(item)
        else:
            seen_urls[norm_url] = item
            deduped.append(item)

    return deduped


def _is_medium_url(url: str) -> bool:
    """Check if a URL is from Medium."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return "medium.com" in host or host.endswith(".medium.com")


def _fetch_article_content(url: str) -> str | None:
    """Fetch and extract article text, truncated to 1000 words."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None

        text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=False
        )
        if not text:
            return None

        words = text.split()
        if len(words) > 1000:
            return " ".join(words[:1000]) + "..."
        return text
    except Exception as e:
        logger.warning(f"trafilatura failed for {url}: {e}")
        return None
