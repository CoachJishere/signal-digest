# ADR 0001 — Config-driven output formatting for the summarizer

**Date:** 2026-06-26
**Status:** Accepted

## Context

`summarize._build_user_message()` hard-coded newsletter formatting onto every
config's user message: an intro line ("…top stories to summarize for the
newsletter digest") and a closing instruction ("Format each item as:
**[TITLE] (X min read)** — … — [Read more →]").

This is correct for the newsletter-style configs (config-ai, config-culture,
etc.) but directly contradicts the Mystery Maker Reddit Monitor, whose
`system_prompt` instructs the model to output a different format (SUBREDDIT /
PRIORITY / POST TITLE / SUGGESTED ANGLE).

On 2026-06-26 this contradiction surfaced in production: handed a system prompt
saying "you are a Reddit monitor, output PRIORITY blocks" and a user message
saying "summarize as a newsletter," Sonnet 4.6 broke character and emailed
meta-commentary questioning which tool the prompt was meant for — instead of a
digest. The model was right; the prompt fought itself.

## Decision

Make output formatting config-driven via an optional `output_instructions`
field.

- `_build_user_message()` reads `config.get("output_instructions", DEFAULT_OUTPUT_INSTRUCTIONS)`.
- `DEFAULT_OUTPUT_INSTRUCTIONS` preserves the existing newsletter behavior, so
  the 7 newsletter configs are unchanged (they omit the field).
- The intro line was neutralized to "Here are today's items:"; the newsletter
  framing moved into the default instructions, keeping newsletter prompts
  functionally equivalent.
- The Mystery Maker config sets its own `output_instructions`, so its
  `system_prompt` fully owns the output format with no conflicting guidance.

Considered and rejected: moving *all* formatting into each config's
`system_prompt` and having the user message carry only data. Cleaner long-term
but touches all 8 configs and risks regressing the working newsletter outputs.
The surgical field keeps blast radius to the one broken config.

## Consequences

- New configs can specify any output shape without code changes.
- A latent contradiction (system prompt vs. user message) is removed for
  non-newsletter configs.
- Slight risk: a config author can still write an `output_instructions` that
  conflicts with its own `system_prompt`. Mitigated by keeping the format
  authority in one place per config.

## Related

- Empty-signal suppression (same change set): when the summarizer returns the
  `NO_OPPORTUNITIES` sentinel or an empty body, delivery is suppressed rather
  than emailing an empty digest. See CHANGELOG 2026-06-26.
