# Name generator — algorithm and functions

Names generated for registry discoveries (Pure, Blended, Semantic, Interpretation) must be **semantic and have meaning** — no gibberish. The algorithms are **precise** so the generator can assign such names to the many elements that have yet to be discovered. See [REGISTRY_FOUNDATION.md](REGISTRY_FOUNDATION.md).

---

## Design goals

- **Semantic:** Names are meaningful (real words or clearly name-like, e.g. *amber*, *velvet*, *drift*). Not random character strings.
- **Short:** Typically one prefix + one word of 4–14 characters (e.g. `color_velvet`, `motion_drift`).
- **Pleasant:** Pronounceable, consistent in style, never nonsensical.
- **Unique:** Compare against existing names so no duplicate is returned.
- **Precise:** The same seed and rules always produce the same candidate; the algorithm is deterministic and extensible for undiscovered elements.

---

## Algorithm

### 1. Word invention (`_invent_word(seed)`)

- **Input:** An integer seed (from domain, value_hint, and existing count).
- **Process (precise, semantic-only):**
  1. **Prefer known semantic words:** A curated list `_REAL_WORDS` (amber, velvet, coral, drift, haven, etc.) is used. The seed maps deterministically to an index into this list, so many names are **real words** with clear meaning.
  2. **Fallback:** If a real word is not used, two curated lists (**start parts** and **end parts**) form one word: `start + end` (e.g. `am` + `ber` → `amber`, `vel` + `vet` → `velvet`). No awkward double letters at the boundary. Result is capped at 14 characters and at least 4.
- **Output:** A single word of 4–14 characters that is always semantic or name-like (never gibberish).

The combination of real-word list and start/end parts keeps the **name space large and deterministic** while ensuring every output has meaning.

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
