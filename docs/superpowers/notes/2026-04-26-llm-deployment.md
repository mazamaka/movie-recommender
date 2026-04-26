# LLM Reranker Deployment Notes

**Date:** 2026-04-26
**Branch:** `feat/llm-rerank`

## Pre-deployment checklist

- [x] All 18 tests pass: `pytest tests/ -v`
- [x] Model ID verified working — `claude-sonnet-4-6` returns 200 OK with `OK` echo (verified 2026-04-26)
- [ ] `ANTHROPIC_API_KEY` ready for Portainer env (use the first key from `~/Projects/CREDENTIALS.md`)

## Verified model IDs (2026-04-26)

```
claude-sonnet-4-5-20250929 — VALID
claude-sonnet-4-5          — VALID (alias)
claude-sonnet-4-6          — VALID  ← we use this (latest)
claude-3-5-sonnet-20241022 — 404 (deprecated)
```

Default in `core/config.py`: `claude-sonnet-4-6`. Override via `LLM_MODEL` env if needed.

## Portainer deployment (admin server 94.156.232.242)

Stack name: `movie-recommender`. Stack ID needs confirmation through Portainer API:

```bash
curl -s -H "X-API-Key: $PORTAINER_API_KEY" \
  https://portainer.your-host/api/stacks | \
  jq '.[] | select(.Name | contains("movie")) | {Id, Name, EndpointId}'
```

Add `ANTHROPIC_API_KEY` env to stack (via Portainer UI Editor → Env variables, OR via API), then redeploy with "Re-pull image".

Easier: dispatch the `deployer` agent — it auto-detects the stack and adds env from local `.env`.

## Smoke check after deploy

1. Tail container logs:

```bash
# Via Portainer UI or:
docker logs movie-recommender 2>&1 | grep -E "llm_rerank|Pipeline" | tail -20
```

2. Manual pipeline trigger:

```bash
curl -X POST http://94.156.232.242:9200/api/v1/pipeline/run
```

3. Expected log lines (within ~3 minutes):
   - `INFO  llm_rerank_started ... candidates=30, feedback_count=N`
   - `INFO  llm_rerank_completed ... picked=10, with_reason=10, input_tokens=...`
   - In Telegram channel: 10 new posts, most with `🤖 ...` lines in caption

## Rollback

Set `LLM_RERANK_ENABLED=false` in Portainer env and redeploy. Pipeline immediately reverts to old behavior (top-10 by `score_movie` order, no LLM call). Existing data on disk (`reaction_feedback.json`, `published_messages.json`) remains intact.

## Cost monitoring

Each daily run logs `input_tokens` and `output_tokens`. Expected:
- Input: ~2000-3000 tokens (system prompt + taste summary + 30 candidates)
- Output: ~500-1000 tokens (10 picks with reasons)
- Daily cost on Sonnet 4.6: ~$0.02-0.05 → **~$1-3/month**

If `output_tokens` >> 1500 — Claude wrote too much, tune prompt to be terser.
If logs show frequent `llm_rerank_failed` — investigate cause (timeout? API status?).

## Lampa plugin re-deploy reminder

The plugin file at `src/movie_recommender/static/lampa_plugin.js` was extended to send `time_watched`/`duration` per item. Container rebuild auto-publishes the new file at `/static/lampa_plugin.js`. **Lampa users do NOT need to reinstall the plugin** — Lampa fetches the URL each session.

## Open follow-up

- Stack ID and Portainer endpoint number for `movie-recommender` — confirm via Portainer API or UI.
- After 1-2 weeks: review actual reaction ratio in channel (positive vs negative emoji counts) to assess whether LLM rerank improved relevance.
