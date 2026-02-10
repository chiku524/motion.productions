# Codebase structure — where everything lives

Clean organization: every file is in its respective directory. This doc is the single reference for layout.

---

## Repository root

| Path | Purpose |
|------|--------|
| `config/` | YAML config: `default.yaml`, `workflows.yaml`. |
| `docs/` | All documentation (architecture, registries, deployment, roadmap). |
| `knowledge/` | **Runtime data** (not code): learned_*.json, name_reserve.json, static/, dynamic/, narrative/. Written by src/knowledge. |
| `output/` | Default video output directory (configurable). |
| `scripts/` | Entrypoints: generate.py, generate_bridge.py, automate_loop.py, automate.py, learn_from_api.py, learn_report.py, run_d1_migrations.py, seed_name_reserve.py. |
| `cloudflare/` | Worker API (D1, R2, KV), migrations, static app. |
| `src/` | Python source (see below). |
| `Dockerfile`, `Procfile`, `railway.toml`, `render.yaml` | Deployment. |

---

## `src/` — Python package

| Path | Purpose |
|------|--------|
| `src/config.py` | Load YAML config; output dir, video params. |
| `src/pipeline.py` | One prompt → one video file; uses concat, prompt, video_generator. |
| `src/concat.py` | Concatenate segment clips into one file (FFmpeg). |
| `src/prompt.py` | Prompt enrichment (optional style/tone suffix). |
| `src/api_client.py` | HTTP client for Cloudflare API (jobs, upload, learning, knowledge). |
| `src/analysis/` | Video analysis: metrics, analyzer (extract_from_video → analysis dict). |
| `src/interpretation/` | Parse user prompt → InterpretedInstruction (parser, schema). |
| `src/creation/` | Build SceneSpec from instruction; scene_script. |
| `src/procedural/` | Procedural video engine: generator, motion, parser, renderer; data/keywords, data/palettes. |
| `src/video_generator/` | Base VideoGenerator interface; pipeline uses it. |
| `src/knowledge/` | Registries (static, dynamic, narrative), extraction, growth, blending, name-generator, lookup, remote_sync. |
| `src/learning/` | Log runs (JSONL), aggregate, suggest updates (local learning). |
| `src/audio/` | Sound generation. |
| `src/automation/` | Prompt generation for loops (prompt_gen). |
| `src/cinematography/` | Shot types, transitions, schema. |
| `src/depth/` | Parallax, layers, assets. |
| `src/graphics/` | Primitives, templates, text. |
| `src/lighting/` | Grading. |
| `src/narrative/` | Genre rules, story (narrative/film logic). |

---

## `cloudflare/`

| Path | Purpose |
|------|--------|
| `cloudflare/src/index.ts` | Worker: API routes (jobs, upload, learning, knowledge/discoveries, for-creation). |
| `cloudflare/migrations/` | D1 migrations (0000–0005): jobs, learning_runs, learned_*, static_colors, static_sound, narrative_entries. |
| `cloudflare/public/` | Static app (HTML/CSS/JS). |
| `cloudflare/wrangler.jsonc` | Wrangler config (D1, R2, KV). |

---

## `scripts/` — entrypoints only

All scripts live under `scripts/`; none at repo root. Each has a single responsibility (generate, bridge, automate, learn, migrations, seed).

---

## Data vs code

- **Code:** `src/`, `cloudflare/src/`, `scripts/`.  
- **Data/config:** `config/`, `knowledge/`, `output/`.  
- **Docs:** `docs/`.

No redundant or unused top-level directories. Unused code has not been found; all referenced modules are part of the pipeline, API, or tooling.
