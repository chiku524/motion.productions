#!/usr/bin/env bash
# Run D1 migrations for motion.productions (current and any future migrations).
# Usage: ./scripts/run_d1_migrations.sh [--local]
#   Default: apply to --remote. Use --local for local D1 (development).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLOUDFLARE_DIR="$REPO_ROOT/cloudflare"
DB_NAME="motion-productions-db"

TARGET="--remote"
for arg in "$@"; do
  if [ "$arg" = "--local" ]; then
    TARGET="--local"
    break
  fi
done

if [ ! -f "$CLOUDFLARE_DIR/wrangler.jsonc" ]; then
  echo "Error: cloudflare/wrangler.jsonc not found. Run from repo root." >&2
  exit 1
fi

echo "Applying D1 migrations ($TARGET) from $CLOUDFLARE_DIR ..."
cd "$CLOUDFLARE_DIR"
npx wrangler d1 migrations apply "$DB_NAME" $TARGET
echo "Done."
