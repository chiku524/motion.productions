# Python worker for self-feeding learning loop
# Railway / Render: builds from repo root.
# Services: Explorer, Exploiter, Balanced use CMD below.
# Fourth service (Interpretation): same image; in Railway set Start Command to: python scripts/interpret_loop.py
FROM python:3.11-slim

WORKDIR /app

# FFmpeg (includes ffprobe) for audio mux; pydub comes from requirements.txt below
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "scripts/automate_loop.py"]
