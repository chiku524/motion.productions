# Video AI FFmpeg render API — deploy root directory: video-ai/ (Railway, Fly.io, Render).
FROM node:22-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src

ENV NODE_ENV=production
# Fly http_service uses 8080 by default; Railway overwrites PORT at runtime when set.
ENV PORT=8080
EXPOSE 8080

# Run tsx via node (PID 1). npm as PID 1 often mishandles SIGTERM during Railway health checks / restarts.
CMD ["node", "node_modules/tsx/dist/cli.mjs", "src/render/server.ts"]
