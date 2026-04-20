## Learned User Preferences

- Primary mission is exhaustive, named registry growth across video aspects (pure, blended, semantic, interpretation) to support a precise prompt interpreter.
- Wants distinct pure-sound vs pure-color workflows; blended/semantic emphasis on roughly one-second windows; frame-level sound mesh blending primitives with discoveries over loop iterations.
- Prefers Cloudflare for edge APIs and storage orchestration; AI video should use numeric or recipe-style parameters rather than fixed template catalogs when possible.
- Will spend on the order of tens of dollars per month when it clearly improves reliability or throughput.
- Prefers Fly.io over Railway or Render for documented long-running FFmpeg and video-ai hosting; Railway should not be the primary deployment story in docs.

## Learned Workspace Facts

- `motion.productions` is served by a Cloudflare Worker with D1, R2, and KV; Python loop and automation scripts call the same HTTP API.
- The `video-ai` render path uses Node and FFmpeg on dedicated compute; the Worker plans and proxies only, so `VIDEO_AI_RENDER_URL` must be a public HTTPS origin, not localhost.
- Fly.io hosts the video-ai app (for example `motion-productions`); the process should bind `0.0.0.0` and use a `PORT` that matches Fly `internal_port` so health checks succeed.
- Remote D1 migrations and heavy batches can fail with CPU time exceeded (error `7429`); run during quieter periods and retry.
- The main site exposes a Video AI lab under `/video-ai/`; planning runs on the Worker while MP4 encoding depends on the external render service.
