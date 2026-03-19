"""CLI entry point for Damelo."""

import argparse
import logging
import sys
import traceback
from datetime import datetime, timedelta, timezone

from croniter import croniter

from .config import load_config, load_manifest, resolve_config_path
from .deliver import send_digest, send_error_notification
from .ingest import run_ingestion, fetch_full_content_for_items
from .score import score_items, update_seen_topics
from .summarize import summarize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_MANIFEST = "configs/configs.json"


def main():
    parser = argparse.ArgumentParser(description="Damelo — newsletter digest tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", metavar="CONFIG", help="Run digest for a config file")
    group.add_argument(
        "--test", metavar="CONFIG",
        help="Dry run: fetch and score only, print results (no email, no Claude)",
    )
    group.add_argument(
        "--test-email", metavar="CONFIG",
        help="Full pipeline including Claude, but sends with [TEST] subject prefix",
    )
    group.add_argument("--run-all", action="store_true", help="Run all active configs from manifest")
    group.add_argument(
        "--validate", metavar="CONFIG", nargs="?", const="all",
        help="Validate config(s). Pass a config path or 'all' for manifest",
    )

    parser.add_argument(
        "--manifest", default=DEFAULT_MANIFEST,
        help=f"Path to configs.json manifest (default: {DEFAULT_MANIFEST})",
    )

    args = parser.parse_args()

    if args.run:
        _run_digest(args.run, test_email=False)
    elif args.test:
        _test_digest(args.test)
    elif args.test_email:
        _run_digest(args.test_email, test_email=True)
    elif args.run_all:
        _run_all(args.manifest)
    elif args.validate is not None:
        _validate(args.validate, args.manifest)


def _run_digest(config_path: str, test_email: bool = False) -> None:
    """Execute the full digest pipeline for a single config."""
    config = None
    config_name = config_path

    try:
        config = load_config(config_path)
        config_name = config.get("name", config_path)
        logger.info(f"Running digest: {config_name}")

        # Ingest
        items = run_ingestion(config)
        logger.info(f"Ingested {len(items)} items")

        # Score
        items = score_items(items, config["id"])
        logger.info(f"Scored {len(items)} items. Top score: {items[0]['score']:.0f}/8")

        # Fetch full content for qualifying items
        fetch_count = fetch_full_content_for_items(items, config)
        logger.info(f"Full content fetches this run: {fetch_count}")

        # Update seen topics
        update_seen_topics(items, config["id"], config.get("score_threshold", 4))

        # Summarize
        body = summarize(items, config)
        logger.info("Summarization complete")

        # Deliver
        send_digest(body, config, test_mode=test_email)

        mode_label = "[TEST-EMAIL] " if test_email else ""
        logger.info(f"{mode_label}Digest complete: {config_name}")

    except Exception as e:
        logger.error(f"Digest run failed for {config_name}: {e}")
        logger.error(traceback.format_exc())
        try:
            send_error_notification(config_name, str(e))
        except Exception:
            logger.error("Failed to send error notification", exc_info=True)
        sys.exit(1)


def _test_digest(config_path: str) -> None:
    """Dry run: fetch and score, print results. No Claude, no email."""
    config = load_config(config_path)
    logger.info(f"Test run: {config.get('name', config_path)}")

    items = run_ingestion(config)
    items = score_items(items, config["id"])

    top_n = config.get("top_n_items", 20)
    print(f"\n{'='*80}")
    print(f"TEST RUN: {config.get('name', config_path)}")
    print(f"Total items after filtering/dedup: {len(items)}")
    print(f"Showing top {min(top_n, len(items))} by score:")
    print(f"{'='*80}\n")

    for i, item in enumerate(items[:top_n], 1):
        bd = item["score_breakdown"]
        print(
            f"{i:2}. [{item['score']:.0f}/8] "
            f"(T:{bd['trust']} F:{bd['frequency']} N:{bd['novelty']}) "
            f"[{item['signal_type']}] "
            f"{item['source_name']}"
        )
        print(f"    {item['title'][:100]}")
        print(f"    {item['url']}")
        fc = "yes" if item.get("fetch_full_content") and item["score"] >= config.get("score_threshold", 4) else "no"
        print(f"    Would fetch full content: {fc}")
        print()


def _run_all(manifest_path: str) -> None:
    """Run all active configs whose cron schedule matches the current time."""
    entries = load_manifest(manifest_path)
    active = [e for e in entries if e.get("active", True)]

    if not active:
        logger.info("No active configs in manifest")
        return

    logger.info(f"Found {len(active)} active configs in manifest")

    ran = 0
    for entry in active:
        config_path = resolve_config_path(entry["file"], manifest_path)

        try:
            config = load_config(config_path)
        except Exception as e:
            logger.error(f"Failed to load config {entry['file']}: {e}")
            continue

        schedule = config.get("schedule", "")
        if schedule and not _should_run_now(schedule):
            logger.info(f"Skipping {config.get('name', entry['file'])} — not scheduled now")
            continue

        logger.info(f"Running {config.get('name', entry['file'])}")
        _run_digest(config_path, test_email=False)
        ran += 1

    logger.info(f"Completed {ran} digest runs")


def _should_run_now(cron_expr: str, window_minutes: int = 60) -> bool:
    """Check if a cron expression matches within the current window."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)
    cron = croniter(cron_expr, window_start)
    next_run = cron.get_next(datetime)
    # Ensure timezone-aware comparison
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    return next_run <= now


def _validate(target: str, manifest_path: str) -> None:
    """Validate one or all configs."""
    if target == "all":
        entries = load_manifest(manifest_path)
        for entry in entries:
            path = resolve_config_path(entry["file"], manifest_path)
            try:
                load_config(path)
                print(f"OK: {entry['file']}")
            except Exception as e:
                print(f"FAIL: {entry['file']} — {e}")
    else:
        try:
            config = load_config(target)
            print(f"OK: {config.get('name', target)}")
            print(f"  Sources: {len(config['sources'])}")
            print(f"  Schedule: {config.get('schedule', 'none')}")
        except Exception as e:
            print(f"FAIL: {target} — {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
