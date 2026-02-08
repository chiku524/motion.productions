# Python worker for self-feeding learning loop
# Railway / Render: builds from repo root
FROM python:3.11-slim

WORKDIR /app

# Install Python deps (imageio-ffmpeg bundles FFmpeg, no system install needed)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "scripts/automate_loop.py"]
