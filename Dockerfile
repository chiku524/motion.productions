# Python worker for self-feeding learning loop
# Fly.io (recommended): use fly.loop-*.toml at repo root — see docs/DEPLOYMENT.md (Fly.io section).
# Video loops use automate_loop.py by default; interpretation/sound set WORKER_START_SCRIPT (see docs/DEPLOYMENT.md).
FROM python:3.11-slim

WORKDIR /app

# FFmpeg (includes ffprobe) for audio mux; Python deps from pyproject.toml (editable install)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src/
RUN pip install --no-cache-dir -e .

COPY . .

# Default process: worker_start.py dispatches from WORKER_START_SCRIPT (see docs/DEPLOYMENT.md).
CMD ["python", "scripts/worker_start.py"]
