# Motion Productions

**One prompt → one full video.**  
User instruction drives generation; registries supply the named values that prompt controls. The continuous loop grows those registries from every output.

## Mission

**Exhaustive registries** — record all combinations of **colors**, **sounds**, **semantics (narratives)**, and **interpretations (linguistics)**. Each registry starts from **primitives (origins)**; as loops continue, newly discovered values are stored with **non-gibberish, sensible names**.

**End goal** — a **photoreal engine** that can generate any sort of video from arbitrary user input, resorting to the registries for the values the prompt is in control of. Today’s default path is a **procedural** engine (our algorithms + data + FFmpeg); photoreal is the destination on that same registry-backed foundation. No external generative “model” is required for the current loop.

- **Core foundation and loop:** [docs/INTENDED_LOOP.md](./docs/INTENDED_LOOP.md) — origins, extraction, creation, growth
- **Architecture:** [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — layout, procedural engine, interpreter & learning
- **Workflows & registries:** [docs/WORKFLOWS_AND_REGISTRIES.md](./docs/WORKFLOWS_AND_REGISTRIES.md) — Pure / Blended / Semantic / Interpretation
- **Automation & deployment:** [docs/AUTOMATION.md](./docs/AUTOMATION.md) — automate_loop, **Fly.io** workers (`fly.loop-*.toml`, `video-ai/fly.toml`)
- **Local compute / Fly from scratch:** [docs/LOCAL_COMPUTE.md](./docs/LOCAL_COMPUTE.md) — Docker Compose on your CPU, tunnel, recreate Fly apps
- **Deployment:** [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) — Cloudflare Worker (D1, R2, KV), security, and Fly.io background workers
- **Registry improvements:** [docs/REGISTRY_AND_WORKFLOW_IMPROVEMENTS.md](./docs/REGISTRY_AND_WORKFLOW_IMPROVEMENTS.md)
- **Brand kit:** [docs/BRAND.md](./docs/BRAND.md)

---

## Approach

- **Input:** One text prompt (and optional duration, style, tone).
- **Output:** One video file. No scene list or manual combining.
- **Registries → interpretation → creation:** Prompt maps to registry values (color, sound, narrative, linguistic interpretation). Creation builds a spec from those values; the engine renders one video. The loop extracts what appeared and grows registries. See [docs/INTENDED_LOOP.md](docs/INTENDED_LOOP.md).
- **No reliance on other software:** We do **not** use Runway, Replicate, PyTorch, diffusers, or any trained neural network for the default path. The pipeline uses a **procedural engine** we built:
  - **Prompt → parameters:** Interpretation + registry lookup (origins + learned named values).
  - **Parameters → pixels:** Our renderer (gradients, noise, motion curves — our algorithms).
  - **Pixels → video file:** Minimal encoding (imageio + FFmpeg) to write the result.
- **Exception:** The only “external” dependency is **data we use** for video (pixels, color, motion) — all defined in our repo — plus a minimal way to encode frames to MP4 (imageio/imageio-ffmpeg). See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

---

## Setup

1. **Clone and enter the project**
   ```bash
   cd motion.productions
   ```

2. **Create a virtual environment and install dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
   This installs the repo as an **editable package** (`pyproject.toml`) so `from src.…` works when you run scripts (no `PYTHONPATH` or `sys.path` hacks).

3. **FFmpeg** (for encoding; imageio-ffmpeg may bundle it, or install system FFmpeg)
   - Windows: e.g. `winget install FFmpeg`
   - macOS: `brew install ffmpeg`
   - Linux: `apt install ffmpeg` / `dnf install ffmpeg`

No API keys, no downloaded “models,” no PyTorch — just our code and our data.

---

## Usage

**CLI (one prompt → one video file):**

```bash
# Default: 6 seconds, procedural engine (no external model)
python scripts/generate.py "Sunset over the ocean, dreamy"

# Custom duration and output path
python scripts/generate.py "Neon city at night" --duration 10 --output my_video.mp4

# Optional seed for reproducibility
python scripts/generate.py "Fire and rain" --duration 5 --seed 123

# Log this run for learning (interpret output and store for training)
python scripts/generate.py "Ocean at sunset" --duration 5 --learn
```

**Interpreter & learning (algorithmic, no external model):**

- After generating, use `--learn` to **interpret** the video (color, motion, consistency) and **log** it for training.
- Run a **learning report** to aggregate logged runs and get **suggestions** (e.g. intensity or palette tweaks):

```bash
python scripts/learn_report.py           # summary by palette and keyword
python scripts/learn_report.py --suggest # include update suggestions
python scripts/learn_report.py --json    # machine-readable report
```

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

**From Python:**

```python
from src.config import load_config
from src.pipeline import generate_full_video
from src.procedural import ProceduralVideoGenerator

config = load_config()
generator = ProceduralVideoGenerator(width=512, height=512, fps=24)
path = generate_full_video(
    "Sunset over the ocean",
    duration_seconds=10,
    generator=generator,
    config=config,
)
print(path)  # one output video file
```

---

## Web app

Visit **https://motion.productions** for the library, loop status, and registries browser. Public browser job-create is paused when `MOTION_API_SECRET` is set; authenticated workers create jobs via the API. Pending jobs are fulfilled by `scripts/generate_bridge.py` (local or Fly `motion-loop-webjobs`). See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Project layout

```
motion.productions/
├── config/                      # default.yaml, workflows.yaml
├── knowledge/                   # Local registry cache/export (D1 is source of truth)
│   ├── static/                  # static_colors.json, static_sound.json
│   ├── dynamic/                 # dynamic_*.json (motion, time, gradient, …)
│   └── narrative/               # narrative_*.json (genre, mood, themes, …)
├── docs/                        # Architecture, registries, deployment, roadmap
├── cloudflare/                  # Worker API (D1, R2, KV) + static app
│   ├── migrations/              # D1 schema 0000…0021
│   ├── public/                  # Site, registries UI, /video-ai lab
│   └── src/                     # index.ts, routes/, videoAiApi.ts
├── video-ai/                    # Node FFmpeg recipe render (Fly)
├── src/                         # Python package (procedural + registries)
│   ├── pipeline.py              # One prompt → one video
│   ├── interpretation/          # Prompt → instruction (+ linguistics)
│   ├── creation/                # Instruction → SceneSpec
│   ├── procedural/              # Parser, renderer, generator, data/
│   ├── knowledge/               # Origins, growth, static/dynamic/narrative
│   ├── audio/, automation/, analysis/, learning/, …
│   └── cinematography/, depth/, graphics/, lighting/, narrative/
├── scripts/                     # Entrypoints (see ARCHITECTURE.md for full list)
│   ├── worker_start.py          # Fly/Docker dispatcher (WORKER_START_SCRIPT)
│   ├── automate_loop.py         # Learning loops (explorer/exploiter/balanced)
│   ├── generate_bridge.py       # Pending jobs → generate → upload
│   ├── interpret_loop.py        # Interpretation registry worker
│   ├── sound_loop.py            # Pure sound discovery worker
│   ├── procedural_render_server.py  # HTTP POST /render (engine=procedural)
│   ├── generate.py              # CLI one-shot generate
│   └── run_d1_migrations.py, color_sweep.py, registry_*, seed_*, …
├── fly.loop-*.toml              # Explorer, exploiter, balanced, interpret, sound, webjobs
├── fly.procedural-render.toml
├── docker-compose.local.yml     # Local fleet (see LOCAL_COMPUTE.md)
├── Dockerfile                   # Python workers
└── requirements.txt
```

Full path table: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §4. Registry taxonomy: [docs/WORKFLOWS_AND_REGISTRIES.md](docs/WORKFLOWS_AND_REGISTRIES.md).

---

## Extending

- **Primitives / registries:** Seed and grow via `src/knowledge/` (origins, static/dynamic/narrative); names via the name-generator (non-gibberish).
- **More keywords / palettes:** Edit `src/procedural/data/keywords.py` and `palettes.py` (our data).
- **Richer motion or visuals:** Extend `src/procedural/motion.py` and `renderer.py` (our algorithms).
- **Interpreter / linguistics:** `src/interpretation/` (parser, linguistic registry); creation pulls registry values the prompt controls.
- **Optional:** You can plug in a different `VideoGenerator` later (including a photoreal path) — the default remains **no external model**, only our procedural engine on the same registries.
