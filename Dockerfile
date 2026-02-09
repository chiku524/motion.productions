# Python worker for self-feeding learning loop
# Railway / Render: builds from repo root
FROM python:3.11-slim

WORKDIR /app

# Install FFmpeg for audio mixing (pydub) and Python deps
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "scripts/automate_loop.py"]
