# Core Foundation

This document defines the foundational principle of Motion Productions.

---

## The Foundation

**Base knowledge** is everything that resides within video files: colors, graphics, resolutions, motion, frame rate, composition, brightness, contrast, consistency over time — every aspect that makes a video what it is.

As the program loops continuously, it **extracts every single thing** from this base knowledge. Each generation is analyzed; each analysis feeds back into the knowledge base.

With all that information extracted and available, the software is **capable of creating and producing videos** from a text, script, or prompt provided by a user. User input drives generation; generation is informed by everything we have learned from the base knowledge.

---

## The Cycle

```
┌─────────────────────────────────────────────────────────────────┐
│  BASE KNOWLEDGE                                                  │
│  Colors · Graphics · Resolutions · Motion · Frame rate ·         │
│  Composition · Brightness · Contrast · Consistency · etc.        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  CONTINUOUS LOOP                                                 │
│  Extract every aspect from base knowledge as the program runs    │
│  Each output → analysis → knowledge update                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  VIDEO CREATION                                                  │
│  User provides text / script / prompt                            │
│  Software creates and produces video from extracted knowledge    │
└─────────────────────────────────────────────────────────────────┘
```

---

## In Practice

1. **Base knowledge** — Our data and algorithms define the full vocabulary of video aspects (palettes, motion types, resolutions, etc.). The interpreter analyzes outputs to capture color, motion, consistency, and other attributes.

2. **Extraction** — The learning loop generates videos, analyzes each one, and logs the results. Over time, we extract and accumulate knowledge about what combinations produce which outcomes.

3. **Creation** — When a user submits a prompt, the system maps it to parameters drawn from this knowledge and produces a video. The more the loop runs, the richer the knowledge and the better the output.

---

## Summary

| Concept | Role |
|---------|------|
| **Base knowledge** | Everything incorporated in video files (colors, graphics, resolutions, motion, etc.) |
| **Extraction** | The loop extracts every aspect from base knowledge as it runs |
| **Creation** | Software creates videos from user text/script/prompt, informed by extracted knowledge |

This foundation is the core of the project. All architecture, features, and improvements serve it.
