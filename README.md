# Motion Productions

**One prompt → one full video.**  
Create and produce videos from text, script, or prompt — driven by base knowledge of everything in video files (colors, graphics, resolutions, motion, etc.). The continuous loop extracts every aspect from this knowledge; the software creates videos from user input informed by that extraction. **No external “model”** — the default engine is **our own procedural system**: algorithms and data (pixels, graphics, motion, color) only.

- **Core foundation:** [docs/FOUNDATION.md](./docs/FOUNDATION.md) — base knowledge, extraction, creation
- **Architecture:** [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — procedural engine, interpreter & learning
- **Automation & deployment:** [docs/AUTOMATION.md](./docs/AUTOMATION.md) — automate_loop, Railway/Render
- **Deploy to Cloudflare:** [docs/DEPLOY_CLOUDFLARE.md](./docs/DEPLOY_CLOUDFLARE.md)
- **Brand kit:** [docs/BRAND.md](./docs/BRAND.md)

---

## Approach

- **Input:** One text prompt (and optional duration, style, tone).
- **Output:** One video file. No scene list or manual combining.
- **Base knowledge → extraction → creation:** The loop extracts color, motion, resolution, and other aspects from every output. User prompts map to parameters drawn from this knowledge; the procedural engine produces videos informed by it. See [docs/FOUNDATION.md](docs/FOUNDATION.md).
- **No reliance on other software:** We do **not** use Runway, Replicate, PyTorch, diffusers, or any trained neural network. The pipeline uses a **procedural engine** we built:
  - **Prompt → parameters:** Our keyword/rules parser (palettes, motion hints, intensity — from base knowledge).
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

Visit **https://motion.productions** to generate videos from a prompt. The app creates a job, and the procedural engine (run via `scripts/generate_bridge.py` locally or on a server) processes it and uploads the result. See [docs/DEPLOY_CLOUDFLARE.md](docs/DEPLOY_CLOUDFLARE.md).

## Project layout

```
motion.productions/
├── config/
│   └── default.yaml           # Output dir, resolution, fps
├── docs/
│   ├── FOUNDATION.md           # Core: base knowledge, extraction, creation
│   ├── ARCHITECTURE.md         # Procedural engine, interpreter & learning
│   ├── AUTOMATION.md           # Scripts, Railway/Render deployment
│   ├── DEPLOY_CLOUDFLARE.md    # Cloudflare Worker deploy
│   └── BRAND.md                # Brand kit
├── output/                     # Generated videos
├── src/
│   ├── config.py               # Load YAML config
│   ├── prompt.py               # Optional prompt enrichment
│   ├── pipeline.py             # One prompt → one video path
│   ├── concat.py               # FFmpeg concat (for long-form segments)
│   ├── video_generator/
│   │   └── base.py             # VideoGenerator interface
│   ├── procedural/             # Procedural engine — no external model
│   │   ├── parser.py           # Prompt → spec (keywords & rules)
│   │   ├── renderer.py         # Spec + time → pixels
│   │   ├── generator.py        # ProceduralVideoGenerator
│   │   ├── motion.py           # Motion curves
│   │   └── data/               # palettes.py, keywords.py
│   ├── knowledge/              # Base-knowledge extraction (every aspect in video)
│   │   ├── schema.py           # BaseKnowledgeExtract
│   │   └── extractor.py        # extract_from_video()
│   ├── interpretation/         # User-instruction parser (precise)
│   │   ├── schema.py           # InterpretedInstruction
│   │   └── parser.py           # interpret_user_prompt()
│   ├── creation/               # Build output from extracted knowledge
│   │   └── builder.py          # build_spec_from_instruction()
│   ├── analysis/               # analyze_video → OutputAnalysis (backward compat)
│   │   ├── analyzer.py
│   │   └── metrics.py
│   └── learning/               # Log, aggregate, suggest
│       ├── log.py
│       ├── aggregate.py
│       └── suggest.py
├── cloudflare/                 # Worker API + static app
│   ├── public/                 # Web app (index.html, app.css, app.js)
│   └── src/index.ts            # Jobs API
├── scripts/                    # Python entry points
│   ├── generate.py             # CLI: generate video
│   ├── generate_bridge.py      # Process pending jobs from API
│   ├── automate_loop.py        # Self-feeding loop (Railway/Render)
│   ├── automate.py             # Interval-based automation
│   ├── learn_report.py         # Learning report (local JSONL)
│   └── learn_from_api.py       # Fetch events/feedback, produce suggestions
└── requirements.txt
```

---

## Extending

- **More keywords / palettes:** Edit `src/procedural/data/keywords.py` and `palettes.py` (our data).
- **Richer motion or visuals:** Extend `src/procedural/motion.py` and `renderer.py` (our algorithms).
- **Interpreter / learning:** Add metrics in `src/analysis/metrics.py`, tune aggregation and suggestion rules in `src/learning/aggregate.py` and `suggest.py`.
- **Optional:** You can plug in a different `VideoGenerator` in `scripts/generate.py` if you later choose — but the default is **no external model**, only our procedural engine.
