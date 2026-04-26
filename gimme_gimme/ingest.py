"""RSS ingestion, normalization, deduplication, and full content fetching."""

from __future__ import annotations

import html
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import os

import feedparser
import requests
import trafilatura
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

USER_AGENT = "web:gimme-gimme:v1.0 (by /u/miller_jm)"


def run_ingestion(config: dict) -> list[dict]:
    """Fetch, normalize, filter, and deduplicate items from all sources."""
    all_items = []
    failed_sources = []

    for source in config["sources"]:
        if not source.get("active", True):
            logger.info(f"Skipping inactive source: {source['name']}")
            continue

        try:
            if source.get("source_type") == "apify":
                entries = _fetch_apify_source(source)
            else:
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

    # Keyword filter (if configured)
    keyword_filter = config.get("keyword_filter")
    if keyword_filter:
        before = len(items)
        items = _apply_keyword_filter(items, keyword_filter)
        logger.info(f"After keyword filter: {len(items)} items (filtered {before - len(items)})")

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
    consecutive_failures = 0
    max_consecutive_failures = 3  # Bail early if a site is fully blocking

    for item in candidates:
        if fetch_count >= max_fetches:
            break
        if consecutive_failures >= max_consecutive_failures:
            logger.warning(
                f"Stopping full content fetches after {max_consecutive_failures} "
                f"consecutive failures — site likely blocking server requests"
            )
            break

        is_medium = _is_medium_url(item["url"])
        if is_medium and medium_count >= max_medium:
            continue

        # Clean URL before fetching (strip RSS tracking params)
        fetch_url = _clean_fetch_url(item["url"])

        logger.info(f"Fetching full content: {item['title'][:60]}...")
        content = _fetch_article_content(fetch_url)

        if content:
            item["full_content"] = content
            fetch_count += 1
            consecutive_failures = 0
            if is_medium:
                medium_count += 1
        else:
            consecutive_failures += 1
            logger.warning(f"Full content fetch failed, using RSS excerpt: {item['url']}")

        # Polite delay between requests
        time.sleep(random.uniform(2.0, 3.0))

    logger.info(
        f"Full content fetches: {fetch_count} total ({medium_count} from Medium)"
    )
    return fetch_count


def _apply_keyword_filter(items: list[dict], keyword_filter: list[str]) -> list[dict]:
    """Filter items to only those matching at least one keyword/phrase.

    Matches against title + summary, case-insensitive.
    """
    patterns = [kw.lower() for kw in keyword_filter]
    matched = []
    for item in items:
        text = f"{item['title']} {item.get('summary', '')}".lower()
        if any(pattern in text for pattern in patterns):
            matched.append(item)
    return matched


def _fetch_apify_source(source: dict) -> list[dict]:
    """Fetch items from an Apify actor. Requires APIFY_API_KEY env var."""
    api_key = os.environ.get("APIFY_API_KEY")
    if not api_key:
        logger.warning(
            f"Apify source skipped — APIFY_API_KEY not set. "
            f"See README for setup instructions."
        )
        return []

    actor_url = source.get("apify_actor_url")
    if not actor_url:
        logger.warning(f"Apify source {source['name']} missing apify_actor_url")
        return []

    # Get the latest run's dataset
    resp = requests.get(
        f"{actor_url}/last/dataset/items",
        params={"token": api_key},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    items = []
    for entry in data:
        title = entry.get("text", entry.get("description", "")).strip()
        url = entry.get("url", entry.get("webUrl", "")).strip()
        if not title or not url:
            continue

        # Truncate long TikTok captions
        if len(title) > 200:
            title = title[:200] + "..."

        published = None
        for date_field in ("createTime", "timestamp", "created_at"):
            date_str = entry.get(date_field)
            if date_str:
                try:
                    published = dateparser.parse(str(date_str))
                    if published and published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass
                break

        if not published:
            published = datetime.now(timezone.utc)

        items.append({
            "title": title,
            "url": url,
            "published": published,
            "source_name": source["name"],
            "source_trust_weight": source["trust_weight"],
            "signal_type": source["signal_type"],
            "fetch_full_content": False,
            "summary": title,
            "full_content": None,
            "score": 0.0,
            "score_breakdown": {},
        })

    return items


def _fetch_url_via_apify_proxy(url: str, proxy_password: str) -> bytes:
    """Fetch a URL through Apify's rotating proxy to bypass IP blocks (e.g. Reddit)."""
    proxy_url = f"http://groups-RESIDENTIAL:{proxy_password}@proxy.apify.com:8000"
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        proxies={"http": proxy_url, "https": proxy_url},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def _fetch_feed(source: dict) -> list[dict]:
    """Fetch and normalize a single RSS feed."""
    url = source["url"]
    proxy_password = os.environ.get("APIFY_PROXY_PASSWORD")

    if proxy_password and "reddit.com" in url:
        content = _fetch_url_via_apify_proxy(url, proxy_password)
        feed = feedparser.parse(content)
    else:
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


def _clean_fetch_url(url: str) -> str:
    """Clean a URL before full content fetching.

    Strips RSS tracking params that can trigger 403s (especially on Medium).
    """
    parsed = urlparse(url)
    # Strip all query params for Medium — the ?source=rss... params trigger 403
    if _is_medium_url(url):
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    # For other sites, just strip common tracking params
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
