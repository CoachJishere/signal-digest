# Gimme Gimme

Automated newsletter digest tool that monitors RSS feeds, scores items by trust/frequency/novelty, summarizes with Claude, and delivers via email.

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Set environment variables:
   - `ANTHROPIC_API_KEY` — Claude API key
   - `RESEND_API_KEY` — Resend email API key
   - `RECIPIENT_EMAIL` — delivery email address

## Usage

```bash
# Run a single config
python -m gimme_gimme.main --run configs/config-ai.json

# Dry run (no Claude, no email)
python -m gimme_gimme.main --test configs/config-ai.json

# Test with email (sends with [TEST] prefix)
python -m gimme_gimme.main --test-email configs/config-ai.json

# Run all active configs matching their cron schedule
python -m gimme_gimme.main --run-all
```

## Configs

- `config-ai.json` — AI, ML, and vibe coding signals
- `config-culture.json` — Memes, viral moments, cultural shifts
- `config-mainstream.json` — General public consciousness
- `config-privacy.json` — Privacy, security, data rights

## Roadmap: Social Media Integration

### Current approach

The culture and mainstream digests use Reddit subreddits (r/OutOfTheLoop, r/TikTokCringe, r/FYP) and YouTube Trending as proxies for what's viral on TikTok and Instagram. This captures moments that have crossed over to broader discussion but may miss platform-native trends that haven't reached Reddit yet.

### Full TikTok/Instagram integration via Apify

Direct TikTok and Instagram trending data is available through Apify web scraping actors. Placeholder sources are already configured in `config-culture.json` and `config-mainstream.json` (set to `active: false`).

**To enable:**

1. Sign up at [apify.com](https://apify.com) and get an API key
2. Add `APIFY_API_KEY` as a GitHub Actions secret
3. Set `"active": true` on the Apify sources in the config files

**Estimated cost:** ~$20/month for daily trending data across both actors.

**Recommended Apify actors:**

- `clockworks~tiktok-scraper` — TikTok trending videos and hashtags
- `apify~instagram-hashtag-scraper` — Instagram trending content by hashtag
