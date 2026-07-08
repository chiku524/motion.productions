#!/usr/bin/env bash
# Recreate Fly apps from scratch and set MOTION_API_SECRET + API_BASE.
# Usage (repo root):
#   export MOTION_API_SECRET='your-long-secret'
#   bash scripts/fly_bootstrap.sh
#
# Does NOT deploy — run fly deploy --config … afterward (or GitHub Actions).

set -euo pipefail

SECRET="${MOTION_API_SECRET:-}"
if [[ -z "$SECRET" ]]; then
  echo "Set MOTION_API_SECRET in the environment first." >&2
  exit 1
fi

API_BASE="${API_BASE:-https://motion.productions}"

APPS=(
  motion-loop-explorer
  motion-loop-exploiter
  motion-loop-balanced
  motion-loop-interpret
  motion-loop-sound
  motion-loop-webjobs
  motion-procedural-render
  motion-productions
)

echo "Creating apps (ok if already exists)…"
for app in "${APPS[@]}"; do
  fly apps create "$app" 2>/dev/null || echo "  (exists) $app"
done

echo "Setting secrets on Python workers…"
PYTHON_APPS=(
  motion-loop-explorer
  motion-loop-exploiter
  motion-loop-balanced
  motion-loop-interpret
  motion-loop-sound
  motion-loop-webjobs
  motion-procedural-render
)
for app in "${PYTHON_APPS[@]}"; do
  fly secrets set MOTION_API_SECRET="$SECRET" API_BASE="$API_BASE" -a "$app"
done

echo "Setting VIDEO_AI_RENDER_SECRET on motion-productions (Node render)…"
fly secrets set VIDEO_AI_RENDER_SECRET="$SECRET" -a motion-productions

cat <<EOF

Next:
  fly deploy --config fly.loop-explorer.toml
  fly deploy --config fly.loop-exploiter.toml
  fly deploy --config fly.loop-balanced.toml
  fly deploy --config fly.loop-interpret.toml
  fly deploy --config fly.loop-sound.toml
  fly deploy --config fly.loop-webjobs.toml
  fly deploy --config fly.procedural-render.toml
  (cd video-ai && fly deploy)

Worker secrets (cloudflare/):
  wrangler secret put MOTION_API_SECRET
  wrangler secret put PROCEDURAL_RENDER_URL   # https://motion-procedural-render.fly.dev
  wrangler secret put VIDEO_AI_RENDER_URL     # https://motion-productions.fly.dev
  wrangler secret put VIDEO_AI_RENDER_SECRET

Full guide: docs/LOCAL_COMPUTE.md
EOF
