# Changelog

All notable changes to Damelo are documented here.

## [Unreleased]

### Changed
- Renamed project from Signal Digest to Damelo across all files, package directory, workflow, and email templates

### Added
- Within-digest deduplication: items with >=0.5 Jaccard similarity on title tokens are collapsed, keeping the higher-scoring one
- Cross-config deduplication: novelty scoring now checks seen_topics from other configs (last 24h) so sequential digest runs don't repeat lead stories
- Culture config: added r/OutOfTheLoop (weight 3), r/TikTokCringe, r/FYP, YouTube Trending as TikTok/Instagram proxies
- Culture config: system prompt now prioritizes viral/meme content from proxy sources
- Mainstream config: added r/OutOfTheLoop (weight 3), r/popculturechat, r/movies, YouTube Trending, Variety, Entertainment Weekly
- Mainstream config: removed r/all and r/entertainment
- Privacy config: added noyb (weight 3), IAPP News, Euractiv Tech for EU/international coverage
- Apify integration placeholder in ingest.py for future TikTok/Instagram scraping
- Inactive Apify source entries in culture and mainstream configs
- `active` flag support in ingestion — sources with `"active": false` are skipped
- README.md with setup, usage, and social media integration roadmap
- `requests` added to requirements.txt for Apify HTTP calls

### Changed
- All configs: "Why It Matters" / "Cultural Analysis" / "Worth Knowing" sections now require distinct linked articles instead of commentary on previous section
- Privacy config: added geographic balance prompt so EU/international stories get fair representation alongside US stories
- All configs: explicit instructions that every main section item must have its own title, read time, TLDR, and "Read more" link

## [2025-03-18]

### Changed
- Bold the read time alongside the title in digest items

## [2025-03-17]

### Added
- `config-mainstream.json` profile for general public consciousness signal

## [2025-03-16]

### Changed
- Send digest as HTML email with markdown-to-HTML conversion

## [2025-03-15]

### Fixed
- Grant workflow write permission for seen_topics push
- Fix workflow: stage seen_topics before git pull --rebase
- Bail early on full content fetching after 3 consecutive failures
- Fix Resend 'from' field key and Medium full content fetching

## [2025-03-14]

### Added
- Initial commit: damelo newsletter tool
