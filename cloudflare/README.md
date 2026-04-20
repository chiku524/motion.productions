# Motion Productions — Cloudflare Worker

API and storage for **motion.productions**: Worker (API), D1 (jobs), R2 (videos), KV (cache/config).

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

- `POST /api/jobs` — create job (`{ "prompt": "...", "duration_seconds": 6 }`).
- `GET /api/jobs/:id` — job status and `download_url` when completed.
- `POST /api/jobs/:id/upload` — upload video (body or multipart `file`).
- `GET /api/jobs/:id/download` — stream video from R2.

Video generation runs **locally** (Python); this Worker stores jobs and files and serves them at **motion.productions**.
