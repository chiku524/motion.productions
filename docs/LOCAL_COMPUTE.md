# Local compute (Docker Compose)

Run the worker fleet on a local CPU with Docker Compose against `https://motion.productions` (Worker/D1/R2 on Cloudflare). GPU is optional and not required for the procedural/FFmpeg path.

Registry wipe + primitive reseed: **[REGISTRY_RESET.md](REGISTRY_RESET.md)**.

---

## 1. Local fleet (Docker Compose)

### Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- Cloudflare Worker deployed at `https://motion.productions` (or local wrangler)
- A shared API secret

### One-time setup

```bash
# Repo root
cp .env.example .env
# Edit .env: set MOTION_API_SECRET to a long random string
```

Set the **same** secret on the Worker (if not already):

```bash
cd cloudflare
printf '%s' 'your-long-secret' | npx wrangler secret put MOTION_API_SECRET
```

### Live Python mounts

Compose bind-mounts `./src`, `./scripts`, and `./knowledge` into every Python worker so loop/render code picks up host edits without `--build`. Dependency or `Dockerfile` changes still need a rebuild. Long-running workers still need a container recreate to reload already-imported Python. Set `PYTHONDONTWRITEBYTECODE=1` (already in compose) to avoid host/`__pycache__` fights.

Clear accumulated MP4s inside containers periodically (`/app/output`) — they inflate the Docker VHDX even after upload.

### Start core services (webjobs + procedural render)

```bash
docker compose -f docker-compose.local.yml up -d --build
```

| Service | Host port | Role |
|---------|-----------|------|
| `webjobs` | `8081` | Polls pending jobs → procedural generate → upload |
| `procedural-render` | `8082` | `POST /render` for Video AI `engine=procedural\|enhanced\|photoreal` |

Health checks:

```bash
curl -s http://127.0.0.1:8081/          # webjobs
curl -s http://127.0.0.1:8082/health    # procedural-render
```

### Learning loops (Cloudflare Free + D1)

**Supported free path — Core 4** (explorer, balanced, interpret, sound). No exploiter; keeps D1 under the free CPU limit.

```bash
docker compose -f docker-compose.local.yml --profile free up -d --build
# Alias: --profile loops  (same Core 4)
```

| Service | Host port | Role | Free delay |
|---------|-----------|------|------------|
| explorer | `8083` | Pure color (frame) | 15s |
| balanced | `8085` | Window / blended + narrative | 15s |
| interpret | `8086` | Interpretation + linguistic | 90s |
| sound | `8087` | Pure sound | 75s |

**Opt-in heavier load** (second color frame worker):

```bash
docker compose -f docker-compose.local.yml --profile loops-full up -d --build
# Adds exploiter on 8084 — only when 500/503s stay rare for a stretch
```

**D1 write contract (avoid 7429 / discovery storms):**
- Shared env: `DISCOVERIES_MAX_ITEMS` (default **8**), `DISCOVERIES_CHUNK_PAUSE_SECONDS` (default **3.5**). Blends count as weight 3 toward the budget so Free D1 stays under ~50 queries/request. Empty `job_id`-only discovery posts skip the write lease.
- Single-writer lease on `POST /api/knowledge/discoveries` → 429 + wait (not a crash).
- Explorer: `LOOP_EXTRACTION_FOCUS=frame` + `LOOP_STATIC_FOCUS=color`. Sound owns pure sound; balanced uses `window`.
- Stagger via `LOOP_WORKER_OFFSET_SECONDS` so workers do not POST discoveries in lockstep.
- Public explorer findability: `GET /api/registries/mission`.
- Fill missing sound origin brackets: `python scripts/sound_origin_sweep.py --api-base https://motion.productions`
- Parity check (for-creation vs explorer families): `python scripts/check_for_creation_parity.py`
- Shareable explorer URLs: `/registries/?tab=colors&family=blue&shade=light`

### Optional: Video AI Node (recipe / solid FFmpeg)

```bash
docker compose -f docker-compose.local.yml --profile video-ai up -d --build
# http://127.0.0.1:8788/health
```

### Point the Worker at local procedural render

The Worker cannot reach `localhost` on your PC. Use a tunnel:

```bash
# Example with cloudflared (install separately)
# Windows: if ~/.cloudflared/config.yml exists for another named tunnel,
# it can force quick tunnels to 404. Temporarily rename it, or run:
#   cloudflared tunnel --config path/to/empty-or-motion.yml --url http://127.0.0.1:8082
cloudflared tunnel --url http://127.0.0.1:8082
# Copy the https://….trycloudflare.com URL, then:
cd cloudflare
printf '%s' 'https://YOUR-TUNNEL.trycloudflare.com' | npx wrangler secret put PROCEDURAL_RENDER_URL
```

Quick tunnel URLs change every restart — update `PROCEDURAL_RENDER_URL` each time (or use a named tunnel hostname for stability).

For recipe FFmpeg locally, tunnel `8788` and set `VIDEO_AI_RENDER_URL` the same way (and match `VIDEO_AI_RENDER_SECRET`).

### Without Docker (venv)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
export API_BASE=https://motion.productions
export MOTION_API_SECRET=your-long-secret
export HEALTH_PORT=8081
python scripts/generate_bridge.py --learn --interval 20

# Other terminal
export HEALTH_PORT=8082 PORT=8082
python scripts/procedural_render_server.py
```

### GPU note

Current engines are **CPU** (procedural numpy/Pillow + FFmpeg). A local GPU does not speed them up today. If you later add CUDA/ONNX models, run that process as another Compose service with the NVIDIA Container Toolkit — keep the same HTTP contracts (`POST /render`, job upload).

---

## 2. Wire the Worker to your containers

Set the Worker secrets so it can reach the local render services (via public HTTPS tunnel origins, see above):

```bash
cd cloudflare
printf '%s' 'https://YOUR-PROCEDURAL-TUNNEL' | npx wrangler secret put PROCEDURAL_RENDER_URL
printf '%s' 'https://YOUR-VIDEO-AI-TUNNEL' | npx wrangler secret put VIDEO_AI_RENDER_URL
printf '%s' 'your-long-secret' | npx wrangler secret put VIDEO_AI_RENDER_SECRET
printf '%s' 'your-long-secret' | npx wrangler secret put MOTION_API_SECRET
```

### Verify

```bash
curl -s https://motion.productions/api/health
curl -s http://127.0.0.1:8082/health   # procedural-render
# Authenticated job create (example):
curl -s -X POST https://motion.productions/api/jobs \
  -H "Authorization: Bearer $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"ocean dusk, calm","duration_seconds":3}'
# webjobs should pick it up; poll GET /api/jobs/:id
```

### Ops checklist (free-tier)

- [ ] Cloudflare Free Worker + D1 + KV + R2 (no Paid required for Core 4)
- [ ] Learning loops via `--profile free` (explorer + balanced + interpret + sound)
- [ ] `LOOP_EXTRACTION_FOCUS`: explorer=`frame`, balanced=`window`
- [ ] Stagger offsets already in Compose; discoveries lease handles write contention
- [ ] Public browser writes remain paused; workers use the secret

---

## 3. Recommended path right now

1. **Local Compose** for webjobs + procedural-render (fast iteration).
2. Deploy **Cloudflare Worker** with `MOTION_API_SECRET` (Free plan is fine for Core 4).
3. Turn on learning loops: `docker compose -f docker-compose.local.yml --profile free up -d --build`.
4. Only add `--profile loops-full` (exploiter) when 500/503s stay rare.

See also: [DEPLOYMENT.md](DEPLOYMENT.md), [AUTOMATION.md](AUTOMATION.md), [video-ai/README.md](../video-ai/README.md).
