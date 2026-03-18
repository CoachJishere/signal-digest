"""Claude API summarization."""

import logging
import os
import time
from datetime import datetime, timezone

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096


def summarize(items: list[dict], config: dict) -> str:
    """Send top items to Claude for summarization. Returns formatted newsletter text."""
    top_n = config.get("top_n_items", 20)
    selected = items[:top_n]

    system_prompt = config["system_prompt"]
    user_message = _build_user_message(selected, config)

    logger.info(f"Sending {len(selected)} items to Claude for summarization")

    # Try up to 2 times
    last_error = None
    for attempt in range(2):
        try:
            return _call_claude(system_prompt, user_message)
        except Exception as e:
            last_error = e
            if attempt == 0:
                logger.warning(f"Claude API call failed (attempt 1), retrying in 5s: {e}")
                time.sleep(5)

    raise RuntimeError(f"Claude API failed after 2 attempts: {last_error}")


def _build_user_message(items: list[dict], config: dict) -> str:
    """Build the user message containing all items for summarization."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    parts = [
        "Here are today's top stories to summarize for the newsletter digest:\n"
    ]

    for i, item in enumerate(items, 1):
        content = item.get("full_content") or item.get("summary") or "No content available"
        content_label = "Full Content" if item.get("full_content") else "Summary"
        score = item.get("score", 0)
        breakdown = item.get("score_breakdown", {})

        parts.append(f"---")
        parts.append(
            f"ITEM {i} (Score: {score:.0f}/8 | "
            f"Source: {item['source_name']} | "
            f"Type: {item['signal_type']} | "
            f"Trust: {breakdown.get('trust', '?')}/3 | "
            f"Frequency: {breakdown.get('frequency', '?')}/3 | "
            f"Novelty: {breakdown.get('novelty', '?')}/2)"
        )
        parts.append(f"Title: {item['title']}")
        parts.append(f"URL: {item['url']}")
        parts.append(f"{content_label}: {content}")
        parts.append("")

    parts.append("---")
    parts.append("")
    parts.append(
        f"Format each item as: **[TITLE] (X min read)** — 2-4 sentence TLDR paragraph — [Read more →]\n"
        f"Include the URL for each item's 'Read more' link.\n"
        f"Today's date: {today}"
    )

    return "\n".join(parts)


def _call_claude(system_prompt: str, user_message: str) -> str:
    """Make a Claude API call."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text
