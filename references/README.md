# Reference clips for loop origins

Drop an MP4 you have **rights** to (your own, CC0, or public domain) using the loop name:

```text
references/cartoon.mp4
```

Then extract measurements into the registries (not a copy of the file):

```bash
python scripts/ingest_reference.py references/cartoon.mp4 --loop cartoon --api-base https://motion.productions
```

That writes a recipe (limited palette, ink amount, hold/snap timing, and a palette-indexed pixel field from the sampled frames) and grows named colors/sounds/motion from the clip. The cartoon renderer starts from that field. Source RGB is not stored or replayed.

Do not ingest a copyrighted cartoon in order to reproduce that show.
