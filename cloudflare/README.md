# Motion Productions — Cloudflare Worker

API and storage for **motion.productions**: Worker (API), D1 (registries + jobs), R2 (videos), KV (cache/config).

**Mission context:** Registries hold colors, sounds, narratives, and interpretations (from primitives, then named discoveries). The Worker is the source of truth; Fly workers and the procedural/Video AI render path create videos from user instruction using those values. See [../docs/WORKFLOWS_AND_REGISTRIES.md](../docs/WORKFLOWS_AND_REGISTRIES.md).

## Quick start (terminal)

```bash
npm install
npm run gen:color-primaries   # sync CSS color list from ../src/knowledge/static_registry.py
npx wrangler login
npx wrangler d1 migrations apply motion-productions-db --remote
npx wrangler deploy
```

If you use **Wrangler 4.45+**, the first `deploy` can auto-create D1/KV/R2; then run the migrations command above (use the database name from your config if it differs).

Full steps and troubleshooting: **[../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md)** (Cloudflare Worker section).

## API

- `POST /api/jobs` — create job (`{ "prompt": "...", "duration_seconds": 6 }`). Requires `MOTION_API_SECRET` when set.
- `GET /api/jobs/:id` — job status and `download_url` when completed.
- `POST /api/jobs/:id/upload` — upload video (body or multipart `file`).
- `GET /api/jobs/:id/download` — stream video from R2.
- `GET /api/knowledge/for-creation` — registry values for creation / loops.
- `POST /api/knowledge/discoveries` — record novel named discoveries.

Video generation runs on **Fly.io** workers (`generate_bridge`, learning loops, procedural-render) or locally via Python scripts — not inside this Worker. The Worker plans Video AI jobs and stores results. See [../docs/LOCAL_COMPUTE.md](../docs/LOCAL_COMPUTE.md) and [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).
