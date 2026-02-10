# Name generator — algorithm and functions

Names generated for registry discoveries (static, dynamic, narrative) are **sensible**, **short**, and **authentic-looking**: they resemble real words and are pleasant to the eye and ear. No lengthy or unpleasant strings.

---

## Design goals

- **Sensible:** Names depict words and resemble authentic names (e.g. *amber*, *velvet*, *drift*).
- **Short:** Not lengthy; typically one prefix + one word of 4–10 characters (e.g. `color_velvet`, `motion_drift`).
- **Pleasant:** Pronounceable, consistent in style, never nonsensical.
- **Unique:** Compare against existing names so no duplicate is returned.

---

## Algorithm

### 1. Word invention (`_invent_word(seed)`)

- **Input:** A integer seed (from domain, value_hint, and existing count).
- **Process:**
  1. Two curated lists are used: **start parts** (e.g. `am`, `vel`, `cor`, `mist`, `dawn`, `drift`, `glow`) and **end parts** (e.g. `ber`, `vet`, `al`, `ver`, `er`, `ow`, `ine`). These are chosen to form English-like words when concatenated.
  2. The seed is turned into two indices (deterministic LCG-style) to pick one start and one end.
  3. `word = start + end` (e.g. `am` + `ber` → `amber`, `vel` + `vet` → `velvet`).
  4. The result is **capped at 14 characters** to allow variety and a large pool of possible names (many elements/non-pure blends may need names). If the word is shorter than 4 characters, it is padded from the end part.
- **Output:** A single word of 4–14 characters (e.g. `amber`, `velvet`, `coral`, `drift`).

No pre-made list of full names is stored; words are **generated** from the start/end parts and the seed so the space of names is large and deterministic.

### 2. Sensible name with prefix (`generate_sensible_name(domain, value_hint, ...)`)

- **Input:** `domain` (e.g. `color`, `motion`, `lighting`), optional `value_hint` (e.g. key or prompt snippet), optional `existing_names` set, and `use_prefix` (default True).
- **Process:**
  1. Resolve a short **prefix** from the domain (e.g. `color`, `sound`, `motion`, `light`, `theme`). See `_DOMAIN_PREFIX` in code.
  2. Build a seed from `(domain, value_hint, len(existing_names))`.
  3. Try up to 200 times: invent a word with `_invent_word(seed + i * 7919)` and form `prefix_word`. If that candidate is not in `existing_names`, return it.
  4. If no unique name is found, fallback to `prefix_XXXXX` (5-digit number).
- **Output:** A name like `color_velvet`, `motion_drift`, `light_amber` — word part 4–14 chars for variety and name count.

### 3. Blend name (`generate_blend_name(domain, prompt, ...)`)

- **Input:** `domain`, optional `prompt`, and optional `existing_names`.
- **Process:**
  1. If `prompt` is given, extract up to 3 words (3+ letters) and combine them into one short token (e.g. `azure` + `serene` → `azureserene`), **capped at 10 characters**. If that token is at least 4 characters and not in `existing_names`, return it.
  2. Otherwise call `generate_sensible_name(domain, prompt, existing_names=existing, use_prefix=True)` and return if not in existing.
  3. Else try up to 100 times: `domain` + `_invent_word(...)` and return first unique.
  4. Final fallback: `blend_XXXXX` (5-digit number).
- **Output:** A unique, short name that prefers prompt-derived or prefix+word form.

---

## Functions (reference)

| Function | Purpose |
|----------|---------|
| `_invent_word(seed)` | Build one word (4–14 char) from start+end parts for variety and name count. Used by the reserve and by sensible/blend name generators. |
| `generate_sensible_name(domain, value_hint, existing_names=..., use_prefix=True)` | Main entry for registry growth: returns `prefix_word` (e.g. `color_velvet`). Used for static (color, sound), dynamic (motion, lighting, etc.), and narrative. |
| `generate_blend_name(domain, prompt, existing_names=...)` | For blends: tries prompt-word combination, then sensible name, then domain+word, then numeric fallback. |
| `_words_from_prompt(prompt)` | Extract 3+ letter words from prompt for combination. |
| `_combine_words(words, max_len=10)` | Concatenate words into one token, capped at `max_len`. |

---

## Name reserve

The **name reserve** (`src/knowledge/name_reserve.py`) keeps a pool of pre-generated names (from `_invent_word`) in `knowledge/name_reserve.json`. When the pool is low, it is refilled using the **same** word-invention algorithm, so all names stay consistent and short. The reserve does **not** store a fixed list of names in code; it stores a JSON file that can be **deleted** to force a fresh pool. After deleting `knowledge/name_reserve.json`, the next refill (or next `take()`) will repopulate using the current algorithm.

- **Refill:** Generates names in batch via `_invent_word` and appends to the pool.
- **Take:** Returns the next name from the pool (and refills if below threshold). Used by legacy registry paths; growth typically uses `generate_sensible_name` directly with the registry’s existing names set.

---

## Where names are used

- **Static registry (color, sound):** `ensure_static_color_in_registry` / `ensure_static_sound_in_registry` → `generate_sensible_name("color", key, ...)` or `"sound", key, ...`.
- **Dynamic registry (motion, time, lighting, etc.):** `_ensure_dynamic_in_registry` → `generate_sensible_name(aspect, key, ...)`.
- **Narrative registry:** `ensure_narrative_in_registry` → `generate_sensible_name(aspect, key, ...)`.
- **Legacy / blend registry:** Some code paths use `name_reserve.take()` for a single word from the pool.

All three registries (static, dynamic, narrative) use the same sensible-name logic so that **any element or blend that is truly unknown gets a short, authentic-looking generated name**.
