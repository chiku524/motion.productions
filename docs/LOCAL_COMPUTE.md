# Local compute + Fly bootstrap from scratch

Use this when Fly apps were deleted or you want the same worker contracts on a local CPU. GPU is optional and not required for the procedural/FFmpeg path.

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

### Start core services (webjobs + procedural render)

```bash
docker compose -f docker-compose.local.yml up -d --build
```

| Service | Host port | Role |
|---------|-----------|------|
| `webjobs` | `8081` | Polls pending jobs → procedural generate → upload |
| `procedural-render` | `8082` | `POST /render` for Video AI `engine=procedural` |

Health checks:

```bash
curl -s http://127.0.0.1:8081/          # webjobs
curl -s http://127.0.0.1:8082/health    # procedural-render
```

### Optional: learning loops

```bash
docker compose -f docker-compose.local.yml --profile loops up -d --build
```

Ports: explorer `8083`, exploiter `8084`, balanced `8085`, interpret `8086`, sound `8087`.

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

## 2. Fly.io from scratch (apps were deleted)

Recreate apps, set secrets, deploy. Do this from the **repository root** (except Video AI Node, which uses `video-ai/`).

### Prerequisites

- [flyctl](https://fly.io/docs/hands-on/install-flyctl/) installed
- `fly auth login`
- Same `MOTION_API_SECRET` as the Worker

### Create apps (once each)

```bash
fly apps create motion-loop-explorer
fly apps create motion-loop-exploiter
fly apps create motion-loop-balanced
fly apps create motion-loop-interpret
fly apps create motion-loop-sound
fly apps create motion-loop-webjobs
fly apps create motion-procedural-render
# Video AI Node render (name must match video-ai/fly.toml `app`)
fly apps create motion-productions
```

### Set secrets on every Python app

```bash
SECRET='your-long-secret'   # same as Worker MOTION_API_SECRET

for app in motion-loop-explorer motion-loop-exploiter motion-loop-balanced \
           motion-loop-interpret motion-loop-sound motion-loop-webjobs \
           motion-procedural-render; do
  fly secrets set MOTION_API_SECRET="$SECRET" API_BASE=https://motion.productions -a "$app"
done
```

Video AI Node (optional TTS + Worker render key):

```bash
fly secrets set VIDEO_AI_RENDER_SECRET="$SECRET" -a motion-productions
# optional: fly secrets set OPENAI_API_KEY=sk-... -a motion-productions
```

### Deploy

```bash
fly deploy --config fly.loop-explorer.toml
fly deploy --config fly.loop-exploiter.toml
fly deploy --config fly.loop-balanced.toml
fly deploy --config fly.loop-interpret.toml
fly deploy --config fly.loop-sound.toml
fly deploy --config fly.loop-webjobs.toml
fly deploy --config fly.procedural-render.toml

cd video-ai && fly deploy && cd ..
```

Or use GitHub Actions **Deploy Fly apps** after adding repo secret `FLY_API_TOKEN`.

### Wire Worker → Fly origins

```bash
cd cloudflare
printf '%s' 'https://motion-procedural-render.fly.dev' | npx wrangler secret put PROCEDURAL_RENDER_URL
printf '%s' 'https://motion-productions.fly.dev' | npx wrangler secret put VIDEO_AI_RENDER_URL
printf '%s' 'your-long-secret' | npx wrangler secret put VIDEO_AI_RENDER_SECRET
printf '%s' 'your-long-secret' | npx wrangler secret put MOTION_API_SECRET
```

Confirm hostnames with `fly status -a motion-procedural-render` / `fly apps list` if the default `*.fly.dev` name differs.

### Verify

```bash
curl -s https://motion.productions/api/health
curl -s https://motion-procedural-render.fly.dev/health
# Authenticated job create (example):
curl -s -X POST https://motion.productions/api/jobs \
  -H "Authorization: Bearer $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"ocean dusk, calm","duration_seconds":3}'
# webjobs / Fly webjobs should pick it up; poll GET /api/jobs/:id
```

### Ops checklist

- [ ] Workers Paid + D1 Read Replication
- [ ] `LOOP_EXTRACTION_FOCUS`: explorer/exploiter=`frame`, balanced=`window`
- [ ] Stagger offsets already in tomls / Compose
- [ ] Public browser writes remain paused; workers use the secret

---

## 3. Recommended path right now

1. **Local Compose** for webjobs + procedural-render (fast iteration, no Fly bill while rebuilding).
2. Deploy **Cloudflare Worker** with `MOTION_API_SECRET`.
3. When ready for 24/7: recreate Fly apps with the script above; point `PROCEDURAL_RENDER_URL` / `VIDEO_AI_RENDER_URL` at Fly instead of the tunnel.
4. Turn on learning loops (`--profile loops` or Fly explorer/exploiter/balanced) once D1 auth + Paid/replication are confirmed.

See also: [DEPLOYMENT.md](DEPLOYMENT.md), [AUTOMATION.md](AUTOMATION.md), [video-ai/README.md](../video-ai/README.md).
