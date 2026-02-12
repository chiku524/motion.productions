# Deploy the Interpretation Worker

The interpretation worker fills the **interpretation registry** (D1 `interpretations` table) by polling the queue and interpreting user prompts. It does **not** create or render videos — it only processes prompts and stores resolved instructions for the main loop to use.

**Learning loop:** The worker also **generates** diverse prompts (slang, dialect, informal), interprets them, **extracts** linguistic mappings (span → canonical by domain), and **grows** the linguistic registry (D1 `linguistic_registry` table). This enables the system to learn English variations and prepare for "anything and everything" from users.

## Prerequisites

- A Railway project with at least one existing service (Explorer, Exploiter, or Balanced)
- `API_BASE` pointing to your motion.productions instance

## Steps to Deploy on Railway

### 1. Create a new service

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Open your motion.productions project
3. Click **+ New** → **Empty Service**
4. Name it (e.g. `motion-interpret` or `motion-interpretation`)

### 2. Link the same repo

1. The new service should use the **same repository** as your main loop services
2. **Root Directory:** leave empty (repo root)
3. **Builder:** Dockerfile (same as other services)

### 3. Set the start command

In **Settings** → **Deploy** → **Start Command**, set:

```
python scripts/interpret_loop.py
```

Or use the **Custom start command** field if your Railway UI shows it.

### 4. Set environment variables

| Variable | Value |
|----------|--------|
| `API_BASE` | `https://motion.productions` |
| `INTERPRET_DELAY_SECONDS` | `10` (optional; default 10) |
| `HEALTH_PORT` | `8080` (optional; enables HTTP health check for Railway) |

### 5. Deploy

Trigger a deploy (push to main if auto-deploy is on, or manually deploy from the Railway UI). The worker will start polling the interpretation queue every 10 seconds.

## Verify it's working

1. **Railway logs** — You should see:
   - `Interpretation worker started (no create/render)`
   - `interpreted:` or `backfill:` messages when items are processed

2. **API** — `GET https://motion.productions/api/knowledge/for-creation` should return `interpretation_prompts` when the worker has stored results.

3. **UI** — The Registries pane → Interpretation tab will show resolved prompts once the queue has been processed.

## Local / Procfile

For local runs or Procfile-based platforms:

```
interpret: python scripts/interpret_loop.py
```

Then run: `py -m procfile start` or `foreman start` (if using Foreman).

## Populate interpretation registry (one-time)

If the registry is empty, run the backfill script locally:

```bash
py scripts/backfill_interpretations.py --api-base https://motion.productions --limit 100
```

This fetches prompts from jobs, interprets them, and stores results. The interpret worker will then have data to serve via `interpretation_prompts`.

## Linguistic registry migration

Run the D1 migration to create the `linguistic_registry` table:

```bash
cd cloudflare && wrangler d1 migrations apply <DATABASE_NAME>
```

(Replace `<DATABASE_NAME>` with your D1 database binding name from `wrangler.toml`.)

## Backfill registry names (replace gibberish)

If prompts or registries show gibberish names (e.g. "liworazagura", "botucaveraka"):

```bash
# Preview what would be updated
py scripts/backfill_registry_names.py --dry-run

# Apply updates
py scripts/backfill_registry_names.py --api-base https://motion.productions
```

## Troubleshooting

- **No interpretation_prompts:** Run the backfill script above, or ensure the interpret worker is running and polling. Check Railway logs for `backfill:` or `interpreted:` messages.
- **API errors:** Ensure `API_BASE` is correct and the motion.productions API is reachable from Railway.
- **Delay:** Increase `INTERPRET_DELAY_SECONDS` if you hit rate limits.
