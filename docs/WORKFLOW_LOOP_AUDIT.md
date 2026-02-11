# Workflow loop — algorithm and function audit

This document audits every algorithm and function in the workflow loop against the registries (REGISTRY_FOUNDATION, REGISTRIES). All must be on the same page: Pure = single frame/primitives; Blended = categories + elements with name + depth_breakdown; Semantic = same; Interpretation = resolved prompts.

---

## 1. Entry points

| Entry point | What runs | Registries touched |
|-------------|-----------|--------------------|
| **automate_loop.py** | pick_prompt → create job → wait → analysis → grow_from_video, grow_dynamic_from_video, grow_narrative_from_spec → POST discoveries | Static, Dynamic, Narrative; uses for-creation (Interpretation) |
| **generate_bridge.py** | Single run + growth (grow_from_video, grow_narrative_from_spec) | Static, Narrative |
| **Worker POST /api/knowledge/discoveries** | Receives static_colors, static_sound, narrative, colors, motion, …; writes to D1 | All four (D1 tables) |
| **Worker GET /api/knowledge/for-creation** | Returns static, dynamic, narrative, interpretation_prompts for creation/pick_prompt | Read-only |

---

## 2. Extraction (per-instance)

| Function | File | Alignment |
|----------|------|-----------|
| **extract_static_per_frame** | extractor_per_instance.py | Yields one dict per frame: color (r,g,b, opacity 1.0), sound (placeholder or amplitude/tone). Pure = single frame. ✓ |
| **extract_dynamic_per_window** | extractor_per_instance.py | Yields one dict per window: motion, time, gradient, camera, lighting, composition, graphics; audio_semantic={} (filled from spec). Blended = multi-frame. ✓ |
| **_extract_audio_segments** | extractor_per_instance.py | Returns list of {amplitude, weight, tone, timbre}; tone is measurement (low/mid/high/silent). Used for static sound only. ✓ |

---

## 3. Keys (deduplication)

| Key function | Rule | Alignment |
|---------------|------|-----------|
| **_static_color_key** | rgb_key + opacity step (0, 0.05, …, 1.0). Each color at each opaqueness = distinct pure blend. | REGISTRY_FOUNDATION: color at each opaqueness gets a name. ✓ |
| **_static_sound_key** | amplitude_tone_timbre_tempo. | Sound key uses measurements (tone) for keying; primitive names (rumble, tone, hiss) in depth_breakdown. ✓ |
| **_motion_key** | level_trend_direction_rhythm | Blended motion element. ✓ |
| **_audio_semantic_key** | role_mood_tempo_presence | Blended audio_semantic element. ✓ |
| **_time_key, _lighting_key, _composition_key, _graphics_key, _temporal_key, _technical_key** | Domain-specific. | All Blended. ✓ |
| **gradient/camera/transition keys** | From window payload. | From origins. ✓ |

---

## 4. Depth (origin weights)

| Function | Purpose | Alignment |
|----------|---------|-----------|
| **compute_color_depth(r,g,b)** | Weights of **origin primitives** (black, white, red, green, blue) that compose this RGB. | REGISTRY_FOUNDATION: origin color %. Now uses COLOR_ORIGIN_PRIMITIVES, not palettes. ✓ |
| **compute_sound_depth(amplitude, tone)** | Maps tone (measurement) → noise name (silence, rumble, tone, hiss). Returns origin_noises + strength_pct. | low/mid/high = measurements; actual noises = primitives. ✓ |
| **compute_motion_depth** | Speeds: static, slow, medium, fast. | Blended motion primitives. ✓ |
| **compute_lighting_depth, compute_composition_depth, compute_graphics_depth, compute_temporal_depth, compute_technical_depth** | Per-domain primitive weights. | Blended depth. ✓ |
| **compute_full_blend_depths** | Calls per-domain depth for blend. | Uses compute_color_depth (now origin-based). ✓ |

---

## 5. Growth (ensure_* in registry)

| Function | Registry | depth_breakdown / name | Alignment |
|----------|----------|------------------------|-----------|
| **ensure_static_color_in_registry** | Pure | depth_breakdown = {origin_colors: compute_color_depth(…), opacity}. Name from generate_sensible_name. | ✓ |
| **ensure_static_sound_in_registry** | Pure | depth_breakdown = compute_sound_depth(amp, tone) (origin_noises + strength_pct). Name + strength_pct stored. | ✓ |
| **ensure_static_primitives_seeded** | Pure | Seeds STATIC_COLOR_PRIMITIVES, STATIC_SOUND_PRIMITIVES. | ✓ |
| **ensure_dynamic_primitives_seeded** | Blended | Seeds gradient_type, camera motion_type, transition type, audio_semantic (one per presence). | ✓ |
| **_ensure_dynamic_in_registry** | Blended | Generic: name + entry_payload (can include depth_breakdown). api_payload for sync. | ✓ |
| **ensure_dynamic_motion_in_registry** … **ensure_dynamic_depth_in_registry** | Blended | Each passes key, payload, api_payload. audio_semantic adds depth_breakdown (role, mood, tempo, presence). | ✓ |
| **ensure_dynamic_audio_semantic_in_registry** | Blended | depth_breakdown in payload and api_payload. | ✓ |
| **ensure_narrative_in_registry** | Semantic | aspect + value; name from generate_sensible_name. | ✓ |
| **ensure_narrative_primitives_seeded** | Semantic | Seeds genre, mood, style, plots, settings, themes, scene_type from NARRATIVE_ORIGINS. | ✓ |

---

## 6. Name generator

| Function | Requirement | Alignment |
|----------|-------------|-----------|
| **generate_sensible_name(domain, value_hint, existing_names)** | Semantic or name-like; no gibberish. | Uses _REAL_WORDS + start/end parts. ✓ |
| **_invent_word(seed)** | Prefer known semantic words. | _REAL_WORDS list + fallback. ✓ |

---

## 7. Spec-derived values (no pure sound from spec)

| Function | Output | Registry | Alignment |
|----------|--------|----------|-----------|
| **derive_static_sound_from_spec** | One static sound from audio_mood, audio_tempo, audio_presence (amplitude, tone= mood). | Pure (one entry per combo). | Spec-derived sound is still a single “sample” proxy until per-frame audio; key includes mood/tempo/presence. ✓ |
| **derive_audio_semantic_from_spec** | role, mood, tempo, presence. | Blended (audio_semantic). | Kick/snare/etc. are Blended; spec-derived mood/tempo/presence = Blended element. ✓ |

---

## 8. Sync to API (remote_sync, Worker)

| Path | Payload | Alignment |
|------|---------|-----------|
| **post_discoveries / POST /api/knowledge/discoveries** | static_colors (key, r, g, b, opacity, depth_breakdown, name), static_sound (key, amplitude, strength_pct, depth_breakdown, name), narrative, motion, … | Worker accepts depth_breakdown, strength_pct. ✓ |
| **Worker INSERT static_colors / static_sound** | Persists depth_breakdown_json, strength_pct. | ✓ |
| **Worker GET /api/registries** | Returns static_primitives (color 16, sound 4), dynamic_canonical, static/dynamic/narrative/interpretation. | ✓ |

---

## 9. Fixes applied in this audit

1. **compute_color_depth** — Switched from palette means to **COLOR_ORIGIN_PRIMITIVES** (black, white, red, green, blue) so static color depth_breakdown uses Pure registry origin colors per REGISTRY_FOUNDATION.

---

## 10. Summary

- **Pure:** Keys include opacity; depth_breakdown uses origin colors (5) and origin_noises + strength_pct; no kick/snare in static.
- **Blended:** Categories (gradient_type, motion_type, role, mood, tempo, presence) seeded; elements get name + depth_breakdown; audio_semantic has depth_breakdown.
- **Semantic:** All NARRATIVE_ORIGINS aspects seeded (genre, mood, style, plots, settings, themes, scene_type); name per entry.
- **Interpretation:** Stored in D1; for-creation returns interpretation_prompts for pick_prompt.

All algorithms and functions used in the workflow loop are aligned with the four registries and REGISTRY_FOUNDATION.
