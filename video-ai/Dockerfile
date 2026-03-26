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
# Fly.io / Railway set PORT; local default still works via VIDEO_AI_RENDER_PORT
EXPOSE 8788

CMD ["npm", "run", "start"]
