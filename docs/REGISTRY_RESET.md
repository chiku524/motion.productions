# Registry reset — primitives-first reseed

Controlled wipe + reseed so every registry starts from **known primitives**, then Docker loops grow named discoveries. Jobs and R2 videos are preserved.

**Compute note:** Loop workers run via **Docker Compose** on your machine (`docker-compose.local.yml`) — same contracts as Fly, not paid Fly machines. Cloudflare still hosts the Worker + D1/R2/KV.

---

## Mission reminder

- **Pure:** colors + sounds  
- **Blended:** dynamic origin grids (motion, camera, gradient, lighting, …)  
- **Semantic:** narrative origins  
- **Interpretation:** linguistic mappings (+ interpretations grow from prompts)  

Each starts from primitives; novel values get **non-gibberish names**. Creation resorts to D1 via `GET /api/knowledge/for-creation`.

---

## Before you start

1. **Pause Docker loops** (leave API/Worker up):

```bash
docker compose -f docker-compose.local.yml --profile loops stop
# optional: also stop webjobs during wipe
docker compose -f docker-compose.local.yml stop webjobs
```

2. Confirm `MOTION_API_SECRET` is set in `.env` and on the Worker (mutating API requires it).

3. Optional backup: export registries from the site / `GET /api/registries` if you want a snapshot of old discoveries.

---

## Step 1 — Wipe D1 registry tables only

Does **not** delete `jobs`, `learning_runs`, `events`, `feedback`, `video_ai_jobs`, or R2 objects.

```bash
# Counts first
python scripts/wipe_registry_tables.py --remote --dry-run

# Destructive
python scripts/wipe_registry_tables.py --remote --yes
```

If a large table hits D1 CPU **7429**, re-run `--yes` (batched deletes) or trim in the Cloudflare D1 console with small `DELETE … LIMIT` batches.

Tables wiped: `static_colors`, `static_sound`, `narrative_entries`, all `learned_*` (incl. entities / dynamic_meta), `interpretations`, `linguistic_registry`, `name_reserve`, `discovery_runs`.

---

## Step 2 — Reseed primitives (local + D1)

```bash
# Clear local knowledge/ cache so it matches D1, then seed everything and POST
python scripts/seed_registries_d1.py --reset-local --api-base https://motion.productions
```

What it does:

| Registry | Source | Mechanism |
|----------|--------|-----------|
| Static colors/sounds | `STATIC_*_PRIMITIVES` | `ensure_static_primitives_seeded(force_novel=True)` → POST |
| Dynamic / blended | Full `get_all_origins()` grids | `ensure_dynamic_primitives_seeded(force_novel=True)` → POST |
| Narrative | `NARRATIVE_ORIGINS` | `ensure_narrative_primitives_seeded(force_novel=True)` → POST |
| Linguistics | `scripts/seed_linguistic_domains.py` items | `POST /api/linguistic-registry/batch` |

Local-only (no API):

```bash
python scripts/seed_registries_d1.py --reset-local --local-only
```

---

## Step 3 — Verify

```bash
curl -s -H "Authorization: Bearer $MOTION_API_SECRET" \
  "https://motion.productions/api/knowledge/for-creation" \
  | jq '{static_colors:(.static_colors|length), static_sound:(.static_sound|length), narrative:(.narrative|keys), gradient:(.learned_gradient|length), camera:(.learned_camera|length)}'
```

Expect non-zero `static_colors` / `static_sound`, narrative aspects present, and origin-backed gradient/camera lists.

Also: `python scripts/registry_cleanup.py audit --api-base https://motion.productions` (if available).

---

## Step 4 — Restart Docker workers

```bash
docker compose -f docker-compose.local.yml up -d webjobs procedural-render
docker compose -f docker-compose.local.yml --profile loops up -d
```

Explorer/Exploiter (`LOOP_EXTRACTION_FOCUS=frame`) grow **pure** discoveries. Balanced (`window`) grows **blended + semantic**. Interpret / sound workers fill interpretation + pure sound separately.

---

## Optional follow-ups

- Broader color grid (not primitives): `python scripts/color_sweep.py --api-base https://motion.productions --steps 6`
- Name repair if anything numeric slips in: `python scripts/backfill_registry_names.py --api-base https://motion.productions`

---

## Why this exists

Primitives used to seed **local JSON** without always landing in **D1**. Creation reads D1. This runbook + `seed_registries_d1.py` close that gap so the photoreal/procedural path can resort to a complete primitive baseline.
