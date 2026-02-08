# Motion — Brand Kit

**Domain:** [motion.productions](https://motion.productions)  
**Product name:** **Motion** (or **Motion Productions** in formal contexts)

This document is the single source of truth for brand, theme, color palette, typography, voice, and motion/animation for the text-to-video AI product.

---

## 1. Slogan & taglines

### Primary slogan

**"From prompt to production."**

Clear and literal: a single prompt becomes a full production (video). Professional and memorable for the site, ads, and one-liners.

### Alternate taglines

| Use case | Tagline |
|----------|--------|
| Hero / homepage | **From prompt to production.** |
| Subhead | Turn your script into video in minutes. |
| Social / short | Your idea, in motion. |
| Feature / CTA | Put it in motion. |

---

## 2. Brand positioning & theme

- **What we do:** Turn a single text prompt into a unique, creative video — short clips to longer sequences. We’re a **production** in the literal sense: ideas become moving pictures.
- **Theme:** **Motion** = movement, flow, cinema, and production. The brand should feel:
  - **In motion** — UI and messaging suggest flow and progression (e.g. prompt → script → video).
  - **Production-grade** — Serious about quality and control (styles, duration, tone), not a toy.
  - **Creative & confident** — Dark, cinematic base with bold accents; animations that feel purposeful, not flashy.
- **Audience:** Creators, marketers, educators, and anyone who wants to “see their idea as video” without heavy production.

---

## 3. Color palette

A **cinema + production** palette: dark bases with clear hierarchy and accents that feel modern and creative.

### Primary (brand & main actions)

| Name | Hex | Use |
|------|-----|-----|
| **Primary** | `#6366F1` | Main brand, primary buttons, key links (indigo) |
| **Primary hover** | `#4F46E5` | Hover state for primary |
| **Primary muted** | `#A5B4FC` | Soft backgrounds, badges |

### Secondary (creativity & “go”)

| Name | Hex | Use |
|------|-----|-----|
| **Secondary** | `#EC4899` | Accents, “Create” / “Generate” actions, highlights (pink) |
| **Secondary hover** | `#DB2777` | Hover for secondary |
| **Secondary muted** | `#F9A8D4` | Soft accents, tags |

### Motion accent (flow & progression)

| Name | Hex | Use |
|------|-----|-----|
| **Motion** | `#06B6D4` | Progress, “in progress” states, motion trails, links to “flow” (cyan) |
| **Motion hover** | `#0891B2` | Hover for motion accent |
| **Motion muted** | `#67E8F9` | Soft progress indicators, subtle highlights |

### Neutrals (UI & text)

| Name | Hex | Use |
|------|-----|-----|
| **Background** | `#0A0A0C` | Main app background (dark) |
| **Surface** | `#141418` | Cards, panels, inputs |
| **Border** | `#27272A` | Dividers, borders |
| **Muted text** | `#71717A` | Secondary text, placeholders |
| **Body text** | `#A1A1AA` | Default body copy |
| **Heading** | `#FAFAFA` | Headings, emphasis |

### Semantic

| Name | Hex | Use |
|------|-----|-----|
| **Success** | `#22C55E` | Success states, completed, “done” |
| **Warning** | `#F59E0B` | Warnings, in progress (or use Motion) |
| **Error** | `#EF4444` | Errors, destructive |
| **Info** | `#3B82F6` | Info messages, links |

### Gradients

- **Hero / premium:** `linear-gradient(135deg, #6366F1 0%, #EC4899 100%)`
- **Motion (progress / flow):** `linear-gradient(90deg, #06B6D4 0%, #6366F1 100%)`
- Use sparingly for hero, one main CTA, or progress bars.

---

## 4. Typography

- **Headings:** **Plus Jakarta Sans** (600–700) — clean, modern, slightly rounded; fits “motion” and production.
- **Body:** Plus Jakarta Sans (400) or **Inter** (400) for readability.
- **Monospace (prompts / code):** **JetBrains Mono** or **Fira Code**.

Load from Google Fonts: Plus Jakarta Sans, Inter; optional JetBrains Mono.

---

## 5. Voice & tone

- **Confident and clear:** “Words in. Motion out.” — no filler.
- **Friendly but capable:** “We’ll turn your idea into a video” not “Leverage our video synthesis pipeline.”
- **Encouraging:** “Describe your scene” / “What do you want to see?” — invite creativity.
- **Honest:** “Generation usually takes a few minutes” — set expectations.

Avoid: corporate buzzwords, hype (“revolutionary”), or overly casual slang.

---

## 6. Logo & wordmark

- **Wordmark:** **Motion** in the heading font. Primary color or hero gradient. For formal contexts: “Motion Productions” with “Motion” dominant.
- **Icon concept:** A single **motion** mark — e.g. a play triangle merged with a forward streak, or a minimal film frame with a “motion” line. Should read as “movement” and “video” at a glance.
- **Favicon:** Minimal icon (single color or gradient) for motion.productions.

---

## 7. Motion & animation

Animations reinforce “motion” and make the product feel alive and production-oriented. Keep them **purposeful and smooth**, not distracting.

### Principles

- **Direction:** Prefer **forward** movement (e.g. left-to-right, bottom-to-top) to suggest progress (prompt → video).
- **Duration:** Short for UI feedback (150–300 ms), medium for entrances (300–500 ms), longer only for loading or success (500 ms–1.5 s).
- **Easing:** Prefer **ease-out** for entrances and **ease-in-out** for transitions; avoid linear for organic feel.
- **Restraint:** One primary motion per view (e.g. one hero animation); use subtle motion for hover and focus.

### Standard durations

| Token | Value | Use |
|-------|--------|-----|
| **Fast** | 150 ms | Hover, focus, small feedback |
| **Normal** | 300 ms | Buttons, toggles, small entrances |
| **Medium** | 500 ms | Card/section entrance, modals |
| **Slow** | 800 ms | Hero or onboarding reveal |
| **Loading** | 1–2 s (loop) | Shimmer, spinner, “generating” |

### Easing

- **Ease-out:** `cubic-bezier(0.33, 1, 0.68, 1)` — entrances, elements appearing.
- **Ease-in-out:** `cubic-bezier(0.65, 0, 0.35, 1)` — transitions, toggles.
- **Ease-out-expo (snappy):** `cubic-bezier(0.16, 1, 0.3, 1)` — CTAs, important buttons.

### Animation patterns

| Pattern | Use | Notes |
|--------|-----|------|
| **Fade in + slide up** | Section/card entrance | opacity 0→1, translateY(8px)→0 |
| **Shimmer** | Loading skeleton / “generating” | Gradient sweep; use Motion accent |
| **Pulse (soft)** | Loading spinner or “in progress” | Scale or opacity; subtle |
| **Progress fill** | Generation progress bar | Left-to-right fill; Motion gradient |
| **Success check** | Video ready | Short scale + opacity; optional checkmark draw |
| **Hover lift** | Cards, buttons | translateY(-2px) + shadow |

Implementation: see **`cloudflare/public/app.css`** — colors, typography, duration, easing, and keyframes are defined there.

---

## 8. Usage summary

- **Domain:** motion.productions. Use “Motion” as the product name in UI and marketing.
- **Slogan:** Lead with “From prompt to production.” on the site and in key touchpoints.
- **Backgrounds:** Dark (`#0A0A0C` / `#141418`) for a production/studio feel.
- **Primary actions:** Indigo primary; pink secondary for “Create” / “Generate”; cyan (Motion) for progress and flow.
- **Animations:** Use tokens and patterns above so motion feels consistent and on-brand.

---

## 9. Files that implement this

| File | Purpose |
|------|--------|
| **docs/BRAND.md** | This document — brand, slogan, theme, palette, voice, motion principles |
| **cloudflare/public/app.css** | CSS variables (colors, typography, duration, easing) and keyframes for the web app |
