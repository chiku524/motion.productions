# Exhaustive Registry Plan: discovering and recording every combination

Status: DESIGN ONLY. No code is changed by this document. Branch `exhaustive-registry-plan`.
Revision 2 (2026-10-26, evening): **Nico decided "every colour" means EXACT 8-bit colour from the start** (`color.L2`, 16,777,216 RGB cells; the 25-step and 5-step grids become derived roll-up levels). Tile extraction (many colours per frame) is a core requirement, not an option. Cost tables now carry KV writes and an explicit free-tier budget (sections 1 and 4.7). R2 is enabled on the account (the earlier error-10136 blocker is gone).
Date: 2026-10-26. Author: Grok Bot for Nico Chikuji.
Mission (Nico, 2026-10-26): "for both colors and sound and motion (etc), every combination in the long run
[should] be discovered and recorded into the registry ... so that it can be later used within video generation."

All file:line references are against `main` at f773e67. Sizes are computed from the key formulas in the code,
not measured from live D1 (D1 was over its daily read limit while this was written). Anything inferred rather than
read from code or computed is marked **(inferred)**. Cloudflare limits are from the vendor docs
(D1 pricing page, KV limits page) fetched 2026-10-26.

---------------------------------------------------------------------------------------------------

## 0. Summary

1. **Literal "every combination" is possible only for some spaces.** It is realistic for: **exact 8-bit colour,
   opaque (16,777,216 RGB cells: a 2 MiB bitset, a few thousand tiled survey clips)**, the 25-step and 5-step colour
   grids as roll-ups of it, pure sound (a
   few thousand cells), camera / transition / depth / technical / audio-semantic / narrative / gradient (all
   under ~200 cells each), and the origin-defined "intent" grids (hundreds to low thousands per axis). It is
   possible for 8-bit-exact colour **with opacity** (352M cells) only with tile extraction and render-verified (T2) opacity,
   on the order of weeks of loop time, not years. It is **impossible** for the full
   cross product of axes (the 11 macro axes below multiply to 5.1e13; a clip is a point in all of them at once)
   and for open-ended spaces (entity x expression x personality x gag at ~3.9M, free-text names, composition at
   1.03M raw). Those need **hierarchical coverage with a stated guarantee** (every cell at level k, every pair /
   triple of macro cells), not enumeration.
2. **The registry today does not measure what it claims to cover.** Static colour discoveries are partly
   *declared by the builder*, not *observed in the video* (`src/creation/novelty.py:126-132`,
   `src/knowledge/growth_per_instance.py:117-160`: "Frame extraction only keeps a dominant color, so the
   per-video values would otherwise never reach the discovery registries"). Opacity is hard-coded to 1.0
   (`src/knowledge/extractor_per_instance.py:236`), so 26,620 of 27,951 colour cells (95.2%) are unreachable by
   construction. Camera, transition, depth and audio-semantic extraction can emit only a tiny subset of their key
   spaces (sections 2.9-2.12). Dynamic keys are measurement-quantised (open-ended) while coverage % is computed
   against the finite origin grids, so the two do not line up (section 2.0).
3. **The free tier cannot carry this mission.** By code reading, every discoveries POST bumps the for-creation
   cache generation and deletes KV keys (`cloudflare/src/browseCache.ts:50-83`, called from
   `cloudflare/src/routes/knowledge.ts:540-547`), so each loop iteration rebuilds a for-creation snapshot of
   ~12 `ORDER BY count DESC` queries on tables with no index on `count` (`knowledge.ts:587-598`): roughly 5,400
   rows scanned per rebuild **(inferred; D1 analytics will confirm)**. At ~5,760 clips/day that is ~31M reads/day
   against a 5M/day free limit. KV free allows 1,000 writes/day; the per-POST invalidation alone can do ~5 KV
   write/delete operations per POST. D1 free writes are 100,000/day; the per-item SELECT-then-UPDATE/INSERT
   pattern at ~65 items per clip is ~375k writes/day at 5,760 clips. This is the most likely root cause of the
   repeated D1 limit failures and it blocks any exhaustive design. **Phase 0 (below) fixes it before anything
   else.**
4. **Proposed core design:** (a) a versioned, finite, *nested* key space per axis (existing keys stay valid as
   level 0); (b) a cell ordinal (mixed-radix integer) per key so coverage is a **bitset** (**2 MiB = exact 8-bit RGB, stored as
   32 D1 rows of 64 KB**; 42 MiB per tier covers all 352M colour x opacity cells; the 25-step grid is `floor(v/25)` of it); (c) a **one-row-per-clip claim ledger**
   folded into bitset chunks by a cron, so cost per clip is ~2 D1 row writes instead of ~65; (d) a **seeded
   permutation work queue** (cycle-walking Feistel over cell ordinals, leased in blocks) so workers
   deterministically target unseen cells with no table scans; (e) a **closed-loop render -> extract ->
   compare** verifier with three evidence tiers (observed / render-verified / declared), so coverage numbers are
   honest; (f) **survey clips** (calibration swatches and sweeps that are never published) that fill dense
   spaces cheaply, alongside normal creative clips that fill the dynamic axes.
5. **Smallest first step (Phase 0 + 1):** Phase 0 (stop the read/write amplification) is implemented and tested on
   branch `phase0-read-write-reduction` (measured: D1 statements per clip 217-261 -> 41-51, rows read per clip
   297k-377k -> 64-110, KV mutations per clip ~49 -> 0). Phase 1 is then the ledger plus 2 MiB bitset for **exact
   8-bit opaque colour** with tile extraction: with 144 tiles per frame that is **4,855 survey clips (under one day of loop
   time at 5,760 clips/day; ~2 days at 50% efficiency)**, with 16 tiles 43,691 clips (7.6 days; 15 days at 50%). See sections 4.8 and 5.
6. **Feasible coverage target (free tier):** 100% of `color.L0/L1/L2` opaque (T1, raw-frame measured) about 3 weeks after Phase 0
   ships; 100% of `color.L2` x 21 opacity (352M cells, T2) in about 6-8 weeks (compute 4-9 days at 576 tiles; the rest is build and
   verification work). The binding free-tier constraints are D1 writes (100k/day), KV writes (1,000/day), Worker requests
   (100k/day) and R2 storage (10 GB), budgeted in section 4.7.

---------------------------------------------------------------------------------------------------

## 1. Ground truth: how a cell gets into the registry today

Pipeline (evidence):

- The loop (`scripts/automate_loop.py`) calls `get_knowledge_for_creation` per iteration (`automate_loop.py:459`
  -> `src/knowledge/lookup.py:68`, GET `/api/knowledge/for-creation`), builds a spec (`src/creation/builder.py`),
  renders (`src/procedural/renderer.py`), extracts (`src/knowledge/extractor_per_instance.py`), and POSTs
  discoveries (`src/knowledge/remote_sync.py:190-223`).
- Targeting today is **weighted-random by underfill over coarse families**, not enumeration:
  `src/knowledge/mission_targets.py:74-127` (`underfill_weights`, `pick_target_color_family`,
  `pick_target_sound_origin`), fed by `cloudflare/src/missionStats.ts` (GROUP BY stats, 15 min soft TTL).
  Random picks over 1,331 or 5,050 cells show the coupon-collector tail (the last cells take ~N ln N draws).
- Colours: the builder stamps 2 "novel" 25-step bins per clip, chosen from a seeded shuffle of the 1,331 cells that
  are not in the for-creation sample (`src/creation/novelty.py:49-62`). `_occupied_bins` only sees the
  `static_colors` rows returned by for-creation (limited to `colorScan` = 60-120 rows, `knowledge.ts:578`), so
  "occupied" is a sample, not the full set. The stamped value is posted as the discovery with `opacity: 1.0`
  hard-coded (`novelty.py:126-132`). It is **declared, not observed**.
- Sounds: the builder retunes the last sound's amplitude to an unseen value in 0.02-0.95
  (`novelty.py:65-96`). Also **declared**. The extractor does measure real per-frame sound
  (`extractor_per_instance.py:123-186`) and posts it too.
- Per item the Worker does one SELECT, then an UPDATE (count) or INSERT, plus a `name_reserve` insert
  (`cloudflare/src/routes/knowledge.ts:64-543`, per-table blocks at 173-504).
- Coverage reporting: static colours vs `STATIC_COLOR_ESTIMATED_CELLS = 27,951`
  (`src/knowledge/completion_targets.py:20-23`, `cloudflare/src/routes/registries.ts:521`); static sound is
  reported as "primitives present, 10 of 10" (`registries.ts:579-591`), i.e. 100% while the real key space is
  5,050 cells; narrative is vs origin sizes (`registries.ts:524-541`).

Platform limits that bind the design (vendor docs, 2026-10-26):

| Resource | Workers Free | Workers Paid |
|---|---|---|
| D1 rows read | 5 M/day | 25 B/month included, then $0.001/M |
| D1 rows written | 100 k/day | 50 M/month included, then $1.00/M |
| D1 storage | 5 GB total | 5 GB included, $0.75/GB-mo |
| KV reads / writes (different keys) | 100 k/day / **1,000/day** | unlimited |
| KV same-key writes | 1/s | 1/s |
| Worker requests | 100 k/day | 10 M/month included |
| D1 row size | ~2 MB max (so a 2 MiB bitset must be chunked) | same |
| R2 storage | 10 GB-month | 10 GB-month included, then $0.015/GB-mo |
| R2 Class A (writes, lists) / Class B (reads) | 1 M / 10 M per month | same included, then paid |
| R2 deletes, egress | free | free |
| Free-tier reset (D1, KV, requests) | 00:00 UTC (8 PM ET) | n/a |

D1 counts **rows scanned**, a full-table `ORDER BY` on an unindexed column costs the whole table, an index adds
one written row per indexed write, and one row costs one read regardless of size. That last point is why
chunked bitset BLOBs (one row = 64 KB = 524,288 cells) are the cheapest coverage store in D1.

R2 is now enabled on the account (the earlier deploy error 10136 is resolved). R2 is **not** on any hot path of this design: the
coverage store is D1, and R2 is limited to published-clip storage (capped, 7-day retention, `docs/R2_FREE_TIER.md`) and an optional
daily bitset backup. The D1 write ceiling after Phase 0 is ~700-1,000 creative clips/day (91-145 rows written per clip, measured);
the survey path below avoids it by writing ~2 rows per clip.

---------------------------------------------------------------------------------------------------

## 2. Axis-by-axis analysis

Definitions used below. **Observed** = the value is measured from the rendered video by the extractor.
**Declared** = value comes from the spec / builder, never measured. **Space** = number of distinct keys the
current key formula can produce. **Reachable** = keys the *extractor* can actually emit. **Coverage** = what is
recorded now; where live D1 counts were unavailable I cite the container-local mirror (`knowledge/**`,
git-ignored cache, may be a subset of D1) and say so.

### 2.0 Cross-cutting structural findings

- **Two incompatible spaces.** Origins (`src/knowledge/origins.py:12-197`) define finite, producible *intent*
  grids (e.g. MOTION 4x4x5x4x4 = 1,280; LIGHTING 4^5 x 3 = 3,072; CAMERA 16x3x4 = 192; AUDIO 3x20x5x5 = 1,500).
  Registry keys for dynamic axes are *measurement buckets* (e.g. motion level at 0.1 resolution). Coverage and
  `DYNAMIC_CANONICAL` (`completion_targets.py:83-109`) count against the origin grids, but keys are written in
  the measurement space. The local mirror shows several dynamic files pre-filled with the full origin product
  (camera 192, audio_semantic 180, technical 64, transition 16, depth 16, time 8, temporal 20), which means
  those counts are seeded, not discovered.
- **Axes are not independent in the extractor.** Camera is a function of motion
  (`extractor_per_instance.py:352-363`); `composition.luminance_balance` = brightness/255
  (`:348`) = lighting brightness; `graphics.busyness` = 0.5 edge + 0.5 variance (`:424`); gradient type comes
  from gradient direction (`:351`). Counting them as separate axes overstates the space and understates what
  the extractor can distinguish.
- **Lossy codec limits fine colour.** The pipeline extracts from the encoded video. H.264 4:2:0 shifts RGB by a
  few levels, so a 1-step (L2) colour cell cannot be verified post-encode; a 5-step cell can if the target is
  rendered at the cell centre (section 4.6).
- **Per-clip yield.** Loops run `LOOP_DURATION_SECONDS=1` at `LOOP_DELAY_SECONDS=15`
  (`docker-compose.local.yml:104-147`); sound runs 2.5 s every 75 s (`:177-178`). The `loops` profile starts
  explorer, balanced, interpret, sound (plus webjobs and procedural-render). `exploiter` is only in `loops-full`.
  Throughput numbers in section 4.8 are parameterised because the effective period (delay + render + extract +
  post) is not measured here.

### 2.1 Summary table

| # | Axis | Current key (file:line) | Space today | Level-0 / reachable by extractor | Discrete? | Recorded now | Blocker to exhaustive |
|---|---|---|---|---|---|---|---|
| 1 | Static colour | `r,g,b` bin of 25 + `_opacity` (21 steps) (`growth_per_instance.py:32-41`, `registry.py:156-164`) | 11^3 x 21 = **27,951** | 1,331 (opacity always 1.0, `extractor_per_instance.py:236`) | Yes, finite | 1,331 of 27,951 = 4.8% (all at opacity 1.0) (parent audit) | Opacity unobservable; grid is coarse; frames carry one dominant colour (`:217`); some entries declared not observed |
| 2 | Static sound | `amp(0.01)_tone_timbre` (`growth_per_instance.py:44-58`) | 101 amp x 5 tones x 10 timbres = **5,050** | about 11 (tone,timbre) pairs x 100 amps + near-silent keys = ~1,100-1,400 (by reading `blend_depth.py:137-174`) **(inferred)** | Yes, finite | 2,317 rows (parent audit, 46% of 5,050) | 2,317 exceeds the ~1,400 reachable, so >=900 rows are spec-stamped combos the extractor never emits; features (flatness, attack, zcr) measured but dropped from key (`extractor:182-184`) |
| 3 | Motion | `round(level,1)_trend_dir_rhythm` (`growth_per_instance.py:163-168`) | level 0..255 at 0.1 -> 2,551 x 3 x 3 x 2 = **45,918** raw; practical level <= ~100 -> ~18k | extractor emits trend 3, direction 3, rhythm 2 | Continuous (quantised at 0.1) | local mirror 29 entries (**inferred** small vs space) | Open-ended resolution; origin intent grid (1,280) is a different space |
| 4 | Lighting | `round(b/25)*25_round(c,1)_round(s,1)` (`:177-181`) | 11 x ~1,276 x 11 = **~154k** raw | all reachable in principle | Continuous contrast | local 29 | Contrast at 0.1 is effectively continuous |
| 5 | Composition | `cx(.01)_cy(.01)_lb(.01)` (`:184-188`) | 101^3 = **1,030,301** raw | lb duplicates brightness | Continuous | local 19 | 1M raw cells, strongly correlated |
| 6 | Graphics | `edge(.01)_var(.01)_busy(.01)` (`:191-195`) | 101^3 raw, busyness derived (`extractor:424`) so ~10k-20k effective **(inferred)** | reachable | Continuous | local 14 | Correlated, open-ended |
| 7 | Gradient | `type_strength(.01)` (`:212-215`) | ~5 types x 101 = **~505** | reachable (`extractor:351`) | Finite | local 19 | Few blockers; strength fine grid is the only size |
| 8 | Camera | `type_speed_steadiness` (`:218-222`) | 16 x 3 x 4 = **192** | extractor: static/pan/tilt/zoom/zoom_out x slow/medium x `stable` = <=9; builder can draw 7 (`camera_variation.py:17`) | Finite | local 192 (seeded) | Extractor infers camera from motion heuristics, cannot see rotate/arc/steadiness (`extractor:352-363,421`) |
| 9 | Transition | `type_duration(.01)` (`:225-228`) | 4 types x 4 durations = **16** (origins); key allows any duration | extractor: cut/dissolve/fade, duration **always 0.0** (`extractor:388-405`) | Finite | local 16 (seeded) | Duration never measured; only 3 types observable |
| 10 | Depth | `parallax(.01)_layers` (`:231-234`) | 4 x 4 = **16** | extractor emits `depth: {}` (`extractor:427`) | Finite | local 16 (seeded) | **Never observed**; only declared |
| 11 | Audio semantic | `role_mood_tempo` (`:237-243`) | 3 x 20 x 3 = **180** | extractor emits few mood/tempo values (`extractor:258-278`) | Finite | local 180 (seeded) | Mostly declared from spec (`derive_audio_semantic_from_spec`) |
| 12 | Time | `duration(.1)_fps(.1)` (`:171-174`) | ~8 distinct in practice | reachable | Finite | local 8 | Trivial |
| 13 | Temporal | `duration(.1)_trend` (`:198-203`) | few dozen | reachable | Finite | local 20 | Trivial |
| 14 | Technical | `WxH_fps` (`:206-209`) | 8 res x 8 fps = **64** (aspect ratio not in key) | reachable | Finite | local 64 (seeded) | Trivial; renderer must support each |
| 15 | Narrative | `aspect, entry_key` (`narrative_registry.py:11-19`, UNIQUE in migration 0005) | genre 24, tone 20, style 11, tension 4, settings 25, themes 17, scene_type 17 = **118** (`origins.py:137-181`) | declared from prompt / script | Finite | local 4-31 per aspect | Declared (script-driven), open-ended free-text entries |
| 16 | Entities | `kind_traj_bounce_color_dir[_expr_pers_gag]` (`entity_registry.py:13-37`) | base 13 x 7 x 2 = **182**; with colour hint (~17) x direction (~5) = **15,470**; with expression x personality x gag (252) = **~3.9M** | declared from scene graph | Finite but huge | (parent audit) small | Combinatorial; hierarchical coverage only |
| 17 | Linguistic / interpretation | free text (`linguistic_registry`, migration 0021) | open-ended | n/a | Open | n/a | Not enumerable; out of scope |

Notes on 15-17: the entity base grid (182) is what `ENTITY_ESTIMATED_CELLS` counts; the real keys carry more
fields, so reported entity coverage % is against a space far smaller than the key space.

### 2.2 Static colour (axis 1) in detail

- **Key today.** `_static_color_key` (`growth_per_instance.py:32-41`) = floor each channel to a multiple of 25
  (`registry.py:156-164`) -> values 0,25,...,250 (11 bins; the top bin 250 covers 250-255), plus opacity rounded to
  21 steps. 11^3 = 1,331 RGB cells, x21 = 27,951.
- **Coverage today.** 1,331 RGB cells at opacity 1.0 are present (parent audit); 26,620 cells (95.2%) have opacity < 1.0
  and are unreachable because the extractor decodes RGB only (`extractor_per_instance.py:236`).
- **Decision (Nico): the primary target is exact 8-bit colour.** `color.L2` is the source of truth; the ordinal of an opaque cell is
  simply `(r << 16) | (g << 8) | b` (24 bits). The older grids are **derived roll-ups, never separate bitsets to fill**:
  `L1 = floor(v/5)` per channel (52^3) and `L0 = floor(v/25)` per channel (11^3), valid because
  `floor(v/25) = floor(floor(v/5)/5)`. A claimed L2 cell implies its L1 and L0 parents; L0/L1 numbers are recomputed by OR-ing parents in
  compaction, so the existing UI and `STATIC_COLOR_ESTIMATED_CELLS` keep working unchanged.
- **Levels (opaque first, opacity as later planes):**

| Level | Step | RGB cells (opaque) | x21 opacity | Bitset, opaque | Bitset, x21 | Role |
|---|---|---|---|---|---|---|
| L0 (existing) | 25 | 1,331 | 27,951 | 167 B | 3.5 KB | derived roll-up (UI compatibility) |
| L1 | 5 | 140,608 | 2,952,768 | 17.6 KB | 0.37 MB | derived roll-up (published clips can count here) |
| **L2** | **1 (exact 8-bit)** | **16,777,216** | **352,321,536** | **2,097,152 B = 2 MiB = 32 D1 rows x 64 KB** | **42 MiB (44.0 MB) per tier = 672 rows** | **primary target** |

- **Bitset layout.** One opacity *plane* per opacity level: `color.L2.a20` (opacity 1.0) is the first deliverable; planes `a00..a19` are
  later. Each plane is exactly 2 MiB, which is above D1's ~2 MB row limit, so it is stored as 32 chunk rows of 64 KB (524,288 cells each;
  chunk index = `r >> 3`, i.e. 8 red values per chunk). D1 bills one row read/written per chunk regardless of size, so a full read of a plane is 32 rows
  and a compaction pass touching all of it is 32 row writes. R2 is not needed and must not be on the hot path (optional nightly backup, section 4.7).
- **Opacity.** A decoded RGB frame has no alpha. Options in section 4.6: (T2) the renderer composites the target
  colour at alpha a over a known backdrop and the verifier checks the composite against the expected value
  pre-encode (evidence tier "render-verified"); (T1) add an RGBA / matte pass so the extractor can read alpha
  (needs renderer and extractor work). Without one of these, opacity < 1 cells can only be "declared" and must not
  count toward coverage.
- **Tile extraction is a core requirement.** The extractor's colour is the *mean of the whole frame* (`metrics.py:26-38`), i.e. one colour per frame,
  ~24 cells per 1 s clip at 24 fps (assumption: fps 24). Exact 8-bit coverage at one cell per frame is 699,051 clips (121 days at
  5,760 clips/day), so the survey renderer must paint a grid of `k x k` flat tiles per frame and the extractor must read each tile centre
  (new `extract_tiles(frame, grid)`, per-tile mean of a small centre patch, no codec in the path). Supported grids: 1, 16 (4x4), 144 (12x12),
  576 (24x24), 2,304 (48x48), 3,600 (60x60). Cells per clip = 24 x tiles (best case, all tiles distinct). Pre-encode raw-frame
  measurement is exact (**T1, lossless-frame measured**); H.264 4:2:0 shifts RGB by a few levels (**inferred**, measured in Phase 1), so published
  clips only count at L0/L1 through roll-up, never at exact L2.

### 2.3 Static sound (axis 2) in detail

- **Key.** `amplitude(0.01)_tone_timbre` (`growth_per_instance.py:44-58`), tone in {silent, low, mid, high,
  neutral} (`blend_depth.py:81`), timbre in 10 primitives (`blend_depth.py:60-71`). 101 x 5 x 10 = 5,050 raw.
- **Reachable.** From `classify_sound_primitive` (`blend_depth.py:137-174`) with the extractor's tones
  low/mid/high/silent: low -> thump, rumble, hum; mid -> click, drip, rustle, tone; high -> click, whoosh, hiss;
  silent -> silence; near-silent amplitude (< 0.01) forces timbre "silence" for any tone. `neutral` is never
  produced by the extractor. So ~11 live pairs x ~100 amplitudes = ~1,100 cells, plus a few hundred near-silent
  and edge keys **(inferred; confirm with a unit test that enumerates the classifier over a feature grid)**.
- **Current 2,317 rows exceeds that**, which implies about 900+ rows are declared combinations (builder stamp,
  `novelty.py:65-96`) that the extractor could never confirm.
- **Better key (v2, nested above level 0).** The extractor already measures peak frequency, spectral flatness,
  attack ratio and zero-crossing rate per frame (`extractor:146-185`) and then throws them away. Proposed:
  amplitude 12 log-spaced levels x peak-band 8 octave bands x flatness 4 x attack 4 x zcr 4 = **6,144 cells**,
  primitive derived. Finite, every dimension is already measured, and the bitset is under 1 KB.

### 2.4 Dynamic axes (motion, lighting, composition, graphics, gradient, camera, transition, depth, audio semantic, time, temporal, technical)

Keys are produced per window by `extract_window_dynamics` (`extractor_per_instance.py:281-428`) and formatted by
the `_*_key` functions (`growth_per_instance.py:163-243`). Details per axis are in the table above. Proposed
levels (macro = used for pairwise coverage, mid = default exhaustive target, fine = long-run):

| Axis | Macro cells | Mid cells | Fine cells | Notes |
|---|---|---|---|---|
| Motion (observed) | speed 4 x dir 3 x rhythm 2 = 24 | level 32 log bins x trend 3 x dir 3 x rhythm 2 = 576 | level 128 bins x 18 = 2,304 | Legacy `round(level,1)` kept as L0 key, mapped up |
| Lighting | bright 3 x contrast 3 x sat 3 = 27 | 8 x 8 x 8 = 512 | 11 x 32 x 11 = 3,872 | Legacy 25-step brightness already aligns |
| Composition | thirds 3x3 x balance 3 = 27 | 9 x 9 x 8 = 648 | 21 x 21 x 16 = 7,056 | Replace 0.01 grid with nested bins |
| Graphics | edge 3 x var 3 = 9 | 8 x 8 = 64 | 32 x 32 = 1,024 | busyness dropped (derived) |
| Gradient | 5 types x 3 = 15 | 5 x 8 = 40 | 5 x 101 = 505 | |
| Camera | 7 builder moves x 3 speeds = 21 | 192 (origins) | 192 | Extractor must be upgraded to observe more (section 4.6) |
| Transition | 4 | 16 | 16 | Duration must be measured |
| Depth | 4 | 16 | 16 | Needs a depth/parallax estimator |
| Audio semantic | 3 roles x 5 moods x 3 tempi = 45 | 180 | 180 | Extractor emits few values |

### 2.5 Narrative, entities, linguistic (axes 15-17)

- Narrative aspects are finite and small (118 cells over 7 aspects, `origins.py:137-181`). They are *declared*
  from the prompt / script, not measured from pixels. Treat them as "authored coverage", fully enumerable,
  tracked as tier T3 (declared) by design.
- Entities: base grid 182 is cheap; the extended key (colour hint, direction, expression, personality, gag) is
  ~3.9M and should be covered hierarchically (all base cells, all base x colour family, all pairs of the extra
  fields), never literally.
- Linguistic registry is open-ended text. Out of scope for "every combination".

### 2.6 Cross-axis combinations

A clip window sits at one cell in every axis simultaneously, so coverage of a *combination* is a tuple. Macro
cells per axis (colour family x shade 48, sound 30, motion 24, camera 21, gradient 15, lighting 27,
composition 27, graphics 9, transition 4, depth 4, audio semantic 45) multiply to **5.14 x 10^13**. Literal
enumeration is impossible at any throughput. A covering-array guarantee is not:

| Guarantee | Lower bound on windows | Practical estimate |
|---|---|---|
| Every cell of every axis (single-axis) | max axis size (macro 48) | ~100 windows |
| Every PAIR of macro cells across all axes | 48 x 45 = 2,160 | ~2,500-3,000 windows |
| Every TRIPLE of macro cells | 48 x 45 x 30 = 64,800 | ~80,000-100,000 windows |
| Full cross product | 5.14e13 | never |

Pairwise and 3-wise covering arrays are standard (IPOG family); the plan uses them for the dynamic axes and
for colour-family x sound x motion in survey and creative clips respectively. Dependencies between axes
(section 2.0) reduce the number of *observable* tuples; the generator should skip tuples the extractor cannot
distinguish and record them as "dependent", not "unreachable".

---------------------------------------------------------------------------------------------------

## 3. Design principles

1. **Observed beats declared.** A cell counts toward coverage only if the pipeline measured it (tier T1) or the
   renderer can prove it pre-encode (T2). Declared cells (T3) are tracked in a separate bitset and never in the
   headline number. This also repairs today's inflated numbers (section 2.1 rows 1, 2, 10, 11).
2. **Intent and observed are two keys.** The builder targets an *intent* (what to render), the extractor
   reports an *observed* cell. The registry stores observed cells; a learned calibration table
   (intent -> observed, section 4.5) lets the loop aim at an observed cell. Origins (`origins.py`) stay as the
   intent vocabulary.
3. **Finite, nested, versioned.** Every axis has a fixed set of levels; each finer level subdivides the coarser
   one exactly, so coarse coverage is derivable from fine coverage and old keys never become invalid.
4. **Coverage is a bitset, not a table.** Cell ordinal -> one bit. Reads and writes are per 64 KB chunk or per
   clip, never per cell.
5. **Deterministic targeting of the unseen.** A seeded permutation walks the space once with no repeats and no
   coupon-collector tail; seen cells are skipped by bit test.
6. **Honest about size.** Where a space is too large (colour L2 x opacity, entity extended key, cross-axis),
   the plan states a hierarchical guarantee instead of a promise of literal enumeration.

---------------------------------------------------------------------------------------------------

## 4. Detailed design

### 4.1 Key spaces (finite, nested)

A **space** is `(axis, version, level)` with a fixed list of dimensions and radices.

| Space id | Dimensions (radix) | Cells | Replaces / maps from |
|---|---|---|---|
| `color.L2` (**primary**) | r(256) g(256) b(256) x opacity plane(21); plane `a20` = opaque first | 16,777,216 per plane; 352,321,536 total | new; ordinal = `(r<<16)|(g<<8)|b` |
| `color.L1` (derived) | `floor(v/5)`: r(52) g(52) b(52) x opacity(21) | 140,608 per plane; 2,952,768 | roll-up of L2, no own bitset to fill |
| `color.L0` (derived) | `floor(v/25)`: r(11) g(11) b(11) x opacity(21) | 1,331 per plane; 27,951 | existing `static_colors.color_key` (unchanged), roll-up of L2 |
| `sound.L0` | amp(101) tone(5) timbre(10) | 5,050 | existing `static_sound.sound_key` (unchanged) |
| `sound.L1` | amp(12 log) band(8) flatness(4) attack(4) zcr(4) | 6,144 | new, from already-measured features |
| `motion.macro/mid/fine` | see 2.4 | 24 / 576 / 2,304 | `learned_motion.profile_key` maps up |
| `lighting`, `composition`, `graphics`, `gradient` | see 2.4 | 27..7,056 per level | maps up from existing keys |
| `camera`, `transition`, `depth`, `audio_sem` | origin products | 192 / 16 / 16 / 180 | existing keys (already finite) |
| `narrative.*` | origin lists | 118 total | existing `narrative_entries` |
| `entity.base/colour/full` | 182 / 15,470 / ~3.9M | | hierarchical only for `full` |

Rule: a measured continuous value is mapped to a bin by a **pure function with test vectors**, implemented
identically in Python (`src/knowledge/keyspace.py`, new) and TypeScript (`cloudflare/src/keyspace.ts`, new). The
Worker only needs to *decode ordinals for display*; targeting and claiming are Python-side.

### 4.2 Ordinals, versioning and migration

- **Ordinal** = mixed-radix integer of the dimension indices. Example `color.L1`:
  `((ri*52 + gi)*52 + bi)*21 + oi`. Decode is the inverse. Python and TS must agree on shared JSON test vectors.
- **Space registry table** `key_spaces(space_id, axis, version, level, dims_json, size, created_at, frozen)`.
  A space is **frozen** once published. A change in binning creates `version+1`; old claims stay valid for the
  old version and are re-projected (never rewritten).
- **Roll-up.** A claimed `color.L1` cell implies its L0 parent (`floor(v/5)` per channel, then `floor(/5)`)
  is seen. The compaction job (4.3) ORs parent bits so L0 numbers stay consistent with the current UI/APIs.
  A seen L0 cell does **not** imply any L1 child is seen (so the existing 1,331 L0 cells do not count for L1).
- **Existing tables are untouched.** `static_colors`, `static_sound`, `learned_*`, `narrative_entries` stay as
  they are and keep names/counts for the UI and for-creation. Migration is additive (new tables only).
  One-time back-fill: map each existing row key to its L0 ordinal and set the bit (one pass, ~5k rows).
- **Legacy sound rows that the extractor cannot emit** (section 2.3) are back-filled into the **declared**
  bitset, not the observed one.

### 4.3 Coverage store (D1 chunks plus claim ledger)

New tables (additive migrations 0023+):

```
key_spaces(space_id TEXT PK, axis, version, level, dims_json, size INTEGER, frozen INTEGER, created_at)
coverage_chunks(space_id, tier TEXT, chunk_idx INTEGER, bits BLOB, set_count INTEGER, updated_at,
                PRIMARY KEY (space_id, tier, chunk_idx))       -- 64 KB per row = 524,288 cells
coverage_ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id, tier, kind,            -- kind = seen|fail
                payload BLOB, n INTEGER, created_at)           -- ONE row per clip (all spaces in the blob)
cell_failures(space_id, ordinal, n, last_reason, PRIMARY KEY (space_id, ordinal))      -- sparse
target_cursors(space_id PRIMARY KEY, seed, next_index, lease_epoch)                    -- 1 row per space
```

- **Write path (per clip).** Python dedupes the clip's observed ordinals, then `POST /api/coverage/claims` with
  one body listing `{space, tier, ordinals[]}` for all spaces. The Worker inserts **one** `coverage_ledger` row per
  clip (all spaces packed in one varint/delta-encoded blob, no secondary index): **1 row write per clip (+1 when the prune deletes it)**,
  independent of how many cells the clip hit. A 3,600-tile clip is <= 86,400 ordinals, ~100-260 KB, well under the 2 MB row limit;
  a 16-tile clip is ~1 KB. Survey clips write nothing to the legacy per-item tables (only the ledger), which is how they avoid the
  91-145 rows/clip of the creative path.
- **Compaction.** A Worker cron (`triggers.crons`, e.g. every 10 minutes; no scheduled handler exists today,
  grep of `cloudflare/src` and `wrangler.jsonc` found none) reads ledger rows since the last watermark, groups by
  chunk, does one read-modify-write per touched chunk in a `batch`, ORs roll-up parents, and prunes ledger rows
  older than 7 days. The single compaction writer removes the lost-update race that concurrent bit writes would
  have.
- **Read path.** `GET /api/coverage/chunk?space=..&tier=..&chunk=..` returns one row. Python caches chunks in
  memory for the run. Whole-space summary (`seen / size`, per tier, per level) is `SUM(set_count)` over at most
  ~700 chunk rows and is cached for 15 minutes.
- **Counts and names.** Per-cell hit counts are not needed for exhaustiveness. Keep counts only where the UI uses
  them (L0 rows). Names (`name_reserve`) are generated lazily for cells that are actually used in generation, not
  for every one of 3M-352M cells.
- **Size.** `color.L2` opaque plane = 2 MiB per tier = 32 chunk rows; three tiers (T1/T2/T3) = 6 MiB = 96 rows. All 21 planes = 42 MiB per tier
  (672 rows), 126 MiB for three tiers. `color.L1`/`L0` are derived, a few KB. Everything else together < 1 MB. Well inside D1 5 GB and the 2 MB row limit.
- **Chunk rows, not one row.** A 2 MiB bitset cannot be a single D1 row (limit ~2 MB), so the chunking is 64 KB / 32 rows per plane. 64 KB keeps one
  compaction read-modify-write small and still means a whole plane costs only 32 row reads to load.
- **R2.** Optional only: a daily export of the chunks to `_backup/coverage/{date}.bin` (<= 6 MiB opaque, 126 MiB all planes, 1 Class A op) and a
  7-day retention. No read or write on the claim, lease or chunk-read path touches R2.

### 4.4 Work queue: deterministic targeting of unseen cells

- **Permutation.** For each space, `target_cursors.seed` fixes a permutation of `[0, size)` implemented as a
  4-round balanced Feistel network over the next even power of two with **cycle-walking** (standard
  format-preserving permutation): `cell(i) = P_seed(i)`, computable in O(1) with no stored list. Same code in
  Python for targeting; the Worker never needs it.
- **Chunk-aware order for big spaces.** For spaces with more than one chunk (`color.L2`), permute the *chunk
  order* first, then permute cells *within* a chunk. A lease then maps to one chunk, so a worker fetches one chunk
  (1 D1 row) and gets up to 524,288 candidate cells.
- **Leases.** `POST /api/coverage/lease {space, n}` does `UPDATE target_cursors SET next_index = next_index + n
  RETURNING next_index` (1 write) and returns `[start, start+n)`. Workers draw blocks of 64-4,096 indices per call,
  so lease cost per clip is a fraction of a row. Four workers never collide.
- **Skip seen.** The worker bit-tests each leased cell against its cached chunk (observed tier) and keeps the
  unseen ones. When the cursor wraps (all cells visited once) the next pass revisits only cells still unseen or
  failed < 3 times.
- **Failures.** A cell that fails verification (extracted cell != target after the allowed attempts) gets a
  `fail` ledger row; after 3 fails it is recorded in `cell_failures` and exposed as *quarantined*. Reported
  coverage is both `seen/size` and `seen/(size - quarantined)`. Quarantine reasons ("codec drift",
  "extractor cannot emit") feed the extractor roadmap.
- **Opportunistic claims.** The ledger claims every observed cell in the clip, not only the targeted ones, so
  creative clips contribute coverage for free.
- **Mixed strategy.** Survey queue for dense, controllable per-frame spaces; covering-array queue for macro tuples
  on dynamic axes (4.5). The existing weighted-random picker (`mission_targets.py:106-127`) stays as the creative
  fallback and as a diversity source.

### 4.5 Directing the renderer / builder to a target cell

New concept: a `TargetSpec` (list of `(space, ordinal)` plus a mode) produced by the queue and passed into
`build_spec` the same way `knowledge` and `creation_seed` are today (`builder.py:476-483` is where the colour/sound
stamp happens now; `builder.py:382-417` is where camera is chosen).

**Survey clips (new template, never published, `survey=1` flag):** synthetic and cheap, exact control.

| Axis | Survey rendering | Frames or windows per clip | Control |
|---|---|---|---|
| Colour | one flat swatch per frame, at the cell *centre*, hard cuts | 24 cells at 24 fps (1 s) | exact; opacity via known-backdrop composite (4.6) |
| Colour (tile mode) | k x k swatches per frame, each extracted separately | 24 x k^2 (384 at k=4) | needs tile extraction (section 7, decision 3) |
| Sound | synthesised tone/noise per frame window from (amp, band, flatness, attack, zcr) | 24-60 per clip | synth in `src/audio/sound.py` / `event_sfx.py` needs per-feature control (spike) |
| Lighting / composition / graphics / gradient | procedural test patterns (ramps, blob at (cx,cy), edge/variance generators, gradients) | 1 window per second | closed-loop calibration |

**Creative clips (existing loops):** targets are *soft constraints* on macro cells (colour family+shade, motion
class, camera move from the 7 field moves in `camera_variation.py:17`, lighting class, gradient, graphics
class), drawn from the pairwise / 3-wise covering array. The builder already accepts a family/shade bias and a
camera draw; the new part is a deterministic tuple instead of weighted random. Anything extra the clip hits is
claimed anyway (4.4).

**Calibration.** Each controllable parameter (motion speed multiplier, brightness gain, contrast, saturation,
blob position, edge density, gradient strength...) gets a response curve learned by a one-time sweep: render
parameter values, extract, store `parameter -> observed ordinal` in `calibration(axis, param_json, observed_ordinal)`.
Targeting inverts the curve (nearest observed cell), renders, verifies, and retries up to 3 times (4.6).

### 4.6 Verifying that a clip exhibits the target cell (round trip)

Procedure per clip: render -> encode -> extract with the **same extractor the loop uses** -> map measured values to
ordinals -> compare to target -> claim every observed cell at tier T1; attempt-fail the target otherwise.

Axis-specific facts that shape verification:

- **Colour.** The extractor's "dominant colour" is actually the *mean of a subsampled grid over the whole frame*
  (`src/analysis/metrics.py:26-38`, `n` is ignored), so only flat or exactly-balanced frames produce a controlled
  cell. Survey swatches must be flat. Render at the cell centre (L1: `5*i+2`) to absorb codec drift; L2
  (exact 8-bit) can only be verified on pre-encode frames (tier T2) because H.264 4:2:0 alters RGB by a few levels
  (**inferred**, to be measured in the Phase 1 acceptance test).
- **Opacity.** Not observable from RGB. T2 design: render the swatch as a layer at alpha a over a known backdrop,
  compute the expected composite, verify the pre-encode frame equals it. T1 design: add a matte pass so alpha is
  extractable (renderer + extractor change). Until one exists, opacity < 1 cells stay declared (T3).
- **Sound.** Verified on the encoded audio with the existing extractor (`extractor:123-186`); v2 adds only the
  peak-band bucket from `peak_hz`. Timbre is derived from the features, so the reachability list in 2.3 is the
  gate.
- **Camera.** Today's observed camera is inferred from motion (`extractor:352-363`) and cannot represent rotate
  / arc / steadiness. For creative clips the renderer already knows the true move; record it as T2
  (render-verified) from render metadata, keep the extractor-inferred value as T1 for the 5 types it can see.
- **Transition.** Duration is hard-coded 0.0 (`extractor:405`). Fix by measuring the number of boundary frames
  whose diff is between thresholds; until then only type is observed.
- **Depth.** `depth: {}` (`extractor:427`): render-verified at best (known layer count and parallax from the
  scene graph).
- **Audio semantic / narrative / entities.** Authored; tier T3 by design unless an analyser is added.

### 4.7 Cost model and free-tier budget (Cloudflare Workers Free)

**Measured, not inferred.** The earlier version of this section guessed ~5,400 rows read per clip from code reading. Phase 0 measurement
(`cloudflare/scripts/measure-d1.mjs`, local Miniflare, DB seeded with ~6.6k rows, real production tables are larger so this is a lower bound) found:

| Per creative clip | POSTs | D1 statements | D1 requests | Rows read | Rows written | KV puts / deletes / gets | KV writes+deletes |
|---|---|---|---|---|---|---|---|
| Before Phase 0 (baseline `main` f773e67) | 8 | 217-261 | 218-262 | 297k-377k | 91-149 | 17 / 32 / 25 | **~49** |
| After Phase 0 (`phase0-read-write-reduction`) | 2 | 41-51 | 7-8 | 64-110 | 91-145 | 0 / 0 / 0 | **0** |
| Survey clip (this plan, proposed) | 1 claim + amortised lease | ~2-3 | 2 | ~1-2 | **~2** (ledger insert + prune) | 0 / 0 / 0 | **0** |

At ~5,760 creative clips/day the baseline would have been ~1.7-2.2 billion rows read (340-430x the 5M free read cap; the cap is exhausted after about
14-17 clips) and ~282k KV mutations (282x the 1,000/day cap). That explains the D1 and KV limit emails. After Phase 0 reads are no longer the problem; **rows
written (91-145 per creative clip) is**: 100k/day allows only ~700-1,000 creative clips/day. Survey clips avoid that by writing only the ledger row.

**Daily free-tier budget for the proposed steady state** (5,760 clips/day total; survey share s, creative share 1-s; rows are D1 rows):

| Resource (free cap) | Per survey clip | Per creative clip (Phase 0 shape) | Fixed daily cost | Budget at 5,000 survey + 500 creative |
|---|---|---|---|---|
| D1 rows written (100,000/day) | ~2 (ledger insert + prune delete) | 91-145 (target <= 15 after count aggregation) | compaction ~6k (144 runs x ~42 touched chunks), leases ~1k, loop-state ~0.3k | 5,000 survey x 2 = 10k; 500 creative x 91-145 = 45-73k; fixed ~7.3k => **~63-90k (63-90% of cap)**. Hard rule: creative clips/day <= (100k - 17.3k - survey rows) / per-clip rows, i.e. ~500-800 |
| D1 rows read (5,000,000/day) | ~1-2 | 64-110 | snapshot rebuilds <= ~1M (coverage summary 48 x ~700 chunk rows, for-creation ~6, progress ~96), chunk loads 32 x 4 workers x 144 refreshes = ~18k | **~1.1-1.5M (about 25%)** |
| KV writes (1,000/day) | 0 | 0 | loop state <= ~240, snapshot persists ~100-250, counts <= 48 | **<= ~540 (about 54%)** |
| KV reads (100,000/day) | 0 | 0-3 | snapshot cold starts | < 5k |
| Worker requests (100,000/day) | ~2 (lease share + claim) | ~8 (for-creation, 2 POSTs, loop state, job create/complete, status) | status/UI polling ~5k | 10k + 4k + 5k = **~19k (about 19%)** |
| R2 storage (10 GB-month) | 0 (never uploaded) | 0 by default (loop uploads off; ~3 MB each if on) | optional bitset backup 6 MiB, 7-day retention | published clips only; cap `R2_BUDGET_BYTES` 8 GB, retention 7 days => <= ~380 stored clips/day at 3 MB |
| R2 Class A (1M/month = ~33k/day) | 0 | 2 per stored upload | daily sweep list (1 per 1,000 objects) + backup 1 | ~0.8k/day at 380 uploads, 2.5% |
| R2 Class B (10M/month = ~333k/day) | 0 | 0 | usage counter read memoised 60 s per isolate; downloads | < 5k/day |

If creative clips must reach thousands per day, Phase 0 needs a follow-up: **aggregate count bumps client-side** (one multi-row upsert per distinct key per
N minutes) so a creative clip costs <= 15 rows written. Until then the plan runs ~500 creative + ~5,000 survey clips per day.

**Stored size.** Ledger: 1 row per clip, 1 KB (16 tiles) to ~260 KB (3,600 tiles); pruned after compaction (7 days max) so <= ~6k rows live. Coverage chunks
6 MiB (opaque, 3 tiers) to 126 MiB (all planes, 3 tiers). Everything fits 5 GB D1 many times over. If the daily write cap becomes the binding constraint,
moving to Workers Paid removes D1/KV/request daily limits (decision 1) but the design is built to not need it.

### 4.8 Throughput and timelines

Capacity model: `cells/day = clips/day x tiles per frame x 24 frames x efficiency`. Clips/day depends on effective loop period; `86,400 / period`
per loop. With two render loops at a 30 s effective period the ceiling is 5,760 clips/day (survey clips render flat swatches from numpy, so they are cheaper than creative
clips; the number is conservative); a 4-worker case is ~11,520. Efficiency (verified hits / attempts) is unknown until Phase 1 measures it, so the tables show 100% and 50%.
Tile count is the dominant lever: it multiplies cells per clip by up to 3,600.

**Exact 8-bit RGB, opaque (primary target, 16,777,216 cells, T1 raw-frame measured):**

| Target | Tiles per frame | Cells per clip | Clips needed | Days @ 5,760/day | Days @ 11,520/day | Days @ 5,760/day, 50% eff. |
|---|---|---|---|---|---|---|
| **color.L2 opaque** (16,777,216; T1) | 1 | 24 | 699,051 | 121.4 | 60.7 | 242.7 |
| **color.L2 opaque** (16,777,216; T1) | 16 | 384 | 43,691 | 7.6 | 3.8 | 15.2 |
| **color.L2 opaque** (16,777,216; T1) | 144 | 3,456 | 4,855 | < 1 | < 1 | 1.7 |
| **color.L2 opaque** (16,777,216; T1) | 576 | 13,824 | 1,214 | < 1 | < 1 | < 1 |
| **color.L2 opaque** (16,777,216; T1) | 2,304 | 55,296 | 304 | < 1 | < 1 | < 1 |
| **color.L2 opaque** (16,777,216; T1) | 3,600 | 86,400 | 195 | < 1 | < 1 | < 1 |

**Exact 8-bit RGB x 21 opacity planes (352,321,536 cells, T2 render-verified; same tile grids):**

| Target | Tiles per frame | Cells per clip | Clips needed | Days @ 5,760/day | Days @ 11,520/day | Days @ 5,760/day, 50% eff. |
|---|---|---|---|---|---|---|
| color.L2 x 21 opacity (352,321,536; T2) | 1 | 24 | 14,680,064 | 2548.6 | 1274.3 | 5097.2 |
| color.L2 x 21 opacity (352,321,536; T2) | 16 | 384 | 917,504 | 159.3 | 79.6 | 318.6 |
| color.L2 x 21 opacity (352,321,536; T2) | 144 | 3,456 | 101,945 | 17.7 | 8.8 | 35.4 |
| color.L2 x 21 opacity (352,321,536; T2) | 576 | 13,824 | 25,487 | 4.4 | 2.2 | 8.8 |
| color.L2 x 21 opacity (352,321,536; T2) | 2,304 | 55,296 | 6,372 | 1.1 | < 1 | 2.2 |
| color.L2 x 21 opacity (352,321,536; T2) | 3,600 | 86,400 | 4,078 | < 1 | < 1 | 1.4 |

**Derived roll-up levels (for reference; filled for free by L2 claims):**

| Target | Tiles per frame | Cells per clip | Clips needed | Days @ 5,760/day | Days @ 11,520/day | Days @ 5,760/day, 50% eff. |
|---|---|---|---|---|---|---|
| color.L1 opaque (140,608) | 1 | 24 | 5,859 | 1.0 | < 1 | 2.0 |
| color.L1 opaque (140,608) | 16 | 384 | 367 | < 1 | < 1 | < 1 |
| color.L1 opaque (140,608) | 144 | 3,456 | 41 | < 1 | < 1 | < 1 |
| color.L1 opaque (140,608) | 576 | 13,824 | 11 | < 1 | < 1 | < 1 |
| color.L1 opaque (140,608) | 2,304 | 55,296 | 3 | < 1 | < 1 | < 1 |
| color.L1 opaque (140,608) | 3,600 | 86,400 | 2 | < 1 | < 1 | < 1 |
| color.L1 x 21 (2,952,768; T2) | 1 | 24 | 123,032 | 21.4 | 10.7 | 42.7 |
| color.L1 x 21 (2,952,768; T2) | 16 | 384 | 7,690 | 1.3 | < 1 | 2.7 |
| color.L1 x 21 (2,952,768; T2) | 144 | 3,456 | 855 | < 1 | < 1 | < 1 |
| color.L1 x 21 (2,952,768; T2) | 576 | 13,824 | 214 | < 1 | < 1 | < 1 |
| color.L1 x 21 (2,952,768; T2) | 2,304 | 55,296 | 54 | < 1 | < 1 | < 1 |
| color.L1 x 21 (2,952,768; T2) | 3,600 | 86,400 | 35 | < 1 | < 1 | < 1 |

**Other axes (unchanged from revision 1):**

| Target | Cells | Cells per clip | Clips needed | Days @ 5,760/day | Days @ 11,520/day | Days @ 5,760/day, 50% eff. |
|---|---|---|---|---|---|---|
| sound.L1 (6,144, sound loop) | 6,144 | ~60 (2.5 s at 24 fps) | ~100 | < 1 | < 1 | < 1 (synth control permitting) |
| sound.L0 (all ~1,400 reachable) | ~1,400 | ~60 | ~25 | < 1 | < 1 | < 1 |
| Dynamic fine levels, 1 window/axis/clip, balanced loop only (~2,880 clips/day) | motion 2,304; lighting 3,872; composition 7,056 | 1 each, jointly | ~7,100 to cover the largest, ideal | ~2.5 | ~1.3 | ~5 |
| Pairwise macro covering array (all pairs) | ~2,160-3,000 windows | 1 | ~3,000 | ~1 | < 1 | ~2 |
| 3-wise macro covering array | ~65k-100k windows | 1 | ~100,000 | ~35 (on 2,880/day) | ~17 | ~70 |
| Full cross product of macro axes | 5.14e13 | n/a | n/a | never | never | never |

**Tile-grid trade-offs.** More tiles = fewer clips but larger claims and a stricter pre-encode extraction path. Recommended starting point: **144 tiles
(12x12) for the opaque L2 pass** (4,855 clips, 3,456 ordinals per clip, ~10 KB claims), **576 tiles (24x24) for the opacity planes** (25,487 clips
for all 21 planes). 3,600 tiles is available if the opaque pass should finish in ~195 clips (about an hour of loop time), at ~260 KB per claim. At 16 tiles the opaque pass is
the slowest acceptable choice (7.6 days).

**Realistic timeline (calendar, from the day Phase 0 is deployed, includes build and verification, not just render time):**

| Week | Milestone | Cells newly covered |
|---|---|---|
| 0 | Phase 0 deployed; free-tier counters stay green for a day after 00:00 UTC | none |
| 1 | `keyspace.py/ts`, ledger/chunk/lease tables and endpoints, compaction cron, tile renderer and extractor, raw-frame round-trip test | 0 (pipeline ready) |
| 2 | Opaque L2 survey pass at 144 tiles: ~4,855 clips (1-2 days), then quarantine retries for failures | 16,777,216 opaque cells (T1); L1 and L0 roll up to 100% |
| 3 | Verification report, quarantine triage, extractor patches, nightly bitset backup | opaque L2 declared complete with `seen/(size-quarantined)` |
| 4-5 | Opacity T2 composite design and calibration; L1 x 21 planes as the pilot (2.95M, ~2 days) | 2,952,768 (L1 x 21) |
| 6-8 | L2 x 21 planes at 576 tiles: ~25,487 clips = 4.4 days at 100% / 8.9 days at 50%, run as a 30-50% share of loop capacity (decision 5) => ~2-4 weeks | 335,544,320 more cells (planes a00..a19) |

**Feasible coverage target on the free tier:** 100% of exact 8-bit **opaque** colour (T1) about 2-3 weeks after Phase 0 is live; 100% of colour x opacity (352M, T2) in
about 6-8 weeks; >= 99.9% with a published quarantine list if the verification failure rate is higher than hoped. Compute is never the constraint any more
once tile extraction exists: the real constraints are the D1 write budget (kept at ~2 rows per survey clip), tile-extraction correctness, and opacity verification.

Reading the table honestly: **exact 8-bit opaque is hours to days of loop time with tiles, and 121 days without them** (699,051 clips at one colour per frame);
**colour x 21 opacity is feasible only with tile extraction and pre-encode (T2) verification**; **cross-axis is a guarantee (pairs, triples), not an enumeration.**

### 4.8 Throughput and timelines

Capacity model: `cells/day = clips/day x cells per clip x efficiency`. Clips/day depends on effective loop
period; `86,400 / period` per loop. With two render loops (explorer, balanced) at a 30 s effective period the
ceiling is 5,760 clips/day; the parent's "4 render workers" case is ~11,520; 23,040 would need 8 loops. Efficiency
(verified hits / attempts) is unknown until Phase 1 measures it; the table assumes 100% (ideal) and shows the
50% case in the last column. Survey clips only: they would take a share of loop capacity (decision 5).

| Target | Cells | Cells per clip | Clips needed | Days @ 5,760/day | Days @ 11,520/day | Days @ 5,760/day, 50% eff. |
|---|---|---|---|---|---|---|
| color.L0 opacity 1.0 (already done) | 1,331 | 24 | 56 | 0 | 0 | 0 |
| color.L1 opacity 1.0 | 140,608 | 24 | 5,859 | 1.0 | 0.5 | 2.0 |
| color.L1 x 21 opacity (T2) | 2,952,768 | 24 | 123,032 | 21 | 11 | 43 |
| color.L2 opacity 1.0 (T2) | 16,777,216 | 24 | 699,051 | 121 | 61 | 243 |
| color.L2 opacity 1.0 (T2), tile mode k=4 | 16,777,216 | 384 | 43,691 | 7.6 | 3.8 | 15 |
| color.L2 x 21 (T2) | 352,321,536 | 24 | 14.68 M | 2,549 (7 yr) | 1,274 (3.5 yr) | impractical |
| color.L2 x 21 (T2), tile mode k=4 | 352,321,536 | 384 | 917,504 | 159 | 80 | 319 |
| sound.L1 (6,144, sound loop) | 6,144 | ~60 (2.5 s at 24 fps) | ~100 | < 1 | < 1 | < 1 (synth control permitting) |
| sound.L0 (all ~1,400 reachable) | ~1,400 | ~60 | ~25 | < 1 | < 1 | < 1 |
| Dynamic fine levels, 1 window/axis/clip, balanced loop only (~2,880 clips/day) | motion 2,304; lighting 3,872; composition 7,056 | 1 each, jointly | ~7,100 to cover the largest, ideal | ~2.5 | ~1.3 | ~5 |
| Pairwise macro covering array (all pairs) | ~2,160-3,000 windows | 1 | ~3,000 | ~1 | < 1 | ~2 |
| 3-wise macro covering array | ~65k-100k windows | 1 | ~100,000 | ~35 (on 2,880/day) | ~17 | ~70 |
| Full cross product of macro axes | 5.14e13 | n/a | n/a | never | never | never |

Reading the table honestly: **colour and sound dense spaces are days to a few months** if survey clips are
allowed and tile extraction is accepted; **exact 8-bit colour x 21 opacity is feasible only with tile extraction
and pre-encode (T2) verification**; **cross-axis is a guarantee (pairs, triples), not an enumeration.**

### 4.9 Spaces that are too large for literal enumeration

- **Colour L2 x opacity (352M):** literal coverage is feasible with tile extraction (4-9 days of compute at 576 tiles, ~6-8 weeks calendar), and
  impossible without it (~7 years). Exact 8-bit opaque (16.7M) is the first milestone and is not treated as too large. L1 x 21 (2.95M) is the pilot
  for the opacity design.
- **Cross-axis:** commit to *t-wise coverage* (pairs first, then triples) over macro cells.
- **Entity extended key (~3.9M):** cover base (182), base x colour family, then pairwise over the remaining fields.
- **Composition / lighting raw grids (1M / 154k):** the nested bins in 2.4 replace them; the raw 0.01 grids are
  not a goal.
- **Open text:** not enumerated.

Every report must show, per space: `observed / size`, `render-verified / size`, `declared / size`, `quarantined`.

---------------------------------------------------------------------------------------------------

## 5. Phased roadmap

**Phase 0 - stop the bleeding (IMPLEMENTED on branch `phase0-read-write-reduction`, tested).** Required before anything else.
1. Layered snapshot cache (memory -> Cache API -> rarely-written KV) with single-flight, stale-on-failure and `degraded`; no per-POST invalidation.
2. Zero KV writes per POST; KV throttled to <= ~540/day (30 min loop-state throttle).
3. Table-driven batched upsert with in-request dedupe (chunk 36); name checks via the PK-indexed `name_reserve`.
4. Graceful degradation: GET -> 200 `{degraded:true,...}` on D1/KV limit errors, writes -> 503 + Retry-After; Python client cooldown.
5. R2 limits: 25 MB upload cap, 8 GB budget with counter-based tracking (no `list()` on hot paths), 7-day retention cron, loop uploads off by default.
Measured: statements per clip 217-261 -> 41-51, rows read per clip 297k-377k -> 64-110, KV mutations per clip ~49 -> 0. **Follow-up (not done):** client-side
aggregation of count bumps to cut the 91-145 rows written per creative clip toward <= 15.
Exit: a full day with zero D1/KV limit errors at the current cadence (verify after the 00:00 UTC reset).

**Phase 1 - smallest useful exhaustive step: exact 8-bit opaque colour with tile extraction (about 1-2 weeks).**
1. `keyspace.py` / `keyspace.ts` plus test vectors (L2 ordinal, `floor(v/5)`, `floor(v/25)` roll-ups); `key_spaces`, `coverage_chunks` (32 x 64 KB per plane),
   `coverage_ledger` (1 row/clip), `target_cursors` migrations; claims, chunk, lease endpoints; compaction cron.
2. Tile renderer and `extract_tiles(frame, grid)` (1/16/144/576/2,304/3,600); offline acceptance test (no D1): render all 16,777,216 colours as flat tiles,
   extract from raw frames (expect exact equality, T1) and from H.264 (measure drift, decides what published clips may claim).
3. Survey template + Feistel queue for `color.L2.a20`; honest coverage endpoint (`seen/size`, `seen/(size-quarantined)`).
Exit: 16,777,216/16,777,216 opaque cells observed (T1) or quarantined with reasons; L0/L1 roll-ups at 100%.

**Phase 2 - sound and the finite dynamic axes (2-3 weeks).**
`sound.L1` key from already-measured features and an amplitude/band/flatness synthesiser; fix transition duration
measurement; render-verified camera/depth from render metadata; motion/lighting/composition/graphics/gradient
nested bins; replace "primitives present" coverage with real per-level coverage.

**Phase 3 - cross-axis guarantee (2-3 weeks).**
Covering-array generator over macro cells; calibration sweeps (4.5); creative-clip targets as soft constraints;
pairwise coverage report, then 3-wise.

**Phase 4 - opacity planes (2-4 weeks of calendar, mostly shared-loop time).**
Opacity via T2 composite verification or an RGBA matte pass; `color.L1 x 21` as the pilot, then planes `a00..a19` of `color.L2` at 576 tiles
(~25,487 clips total); nightly backup to R2.

**Phase 5 - generation integration.**
Expose "give me a verified cell/set of cells for axis X near Y" to the builder so generation draws from verified
registry cells (ordinal decode in both languages; names for the hot set only).

---------------------------------------------------------------------------------------------------

## 6. Risks and what this plan does not solve

- **Quality of discovery clips.** Survey clips are flat swatches and sweeps. They are for the registry, not for
  viewers. Publishing them would hurt the channel; the plan assumes they are not published (decision 5).
- **Codec drift.** Unmeasured until Phase 1; L1 centre-rendering is a mitigation, not a proof.
- **Extractor realism.** The extractor mean-colour and heuristic camera/transition/depth/audio fields mean some
  axes are observable only in a degraded form until upgraded; coverage claims stay tiered.
- **Correlated axes** make some macro tuples unobservable; they are recorded as dependent, not unreachable.
- **Single compaction writer** is a (small) availability dependency; the ledger keeps claims safe if it stalls.
- **Scale of names.** Naming millions of cells would blow the D1 write budget; names are lazy.
- **Free-tier headroom** is real but thin: D1 rows written is the binding resource (creative clips ~91-145 rows each; budget in 4.7); see decision 1.
- **Tile extraction correctness.** Tiles must be flat, large enough to sample a clean centre patch, and extracted on raw frames; published (H.264) clips cannot
  claim exact cells. Verified by the Phase 1 acceptance test before any claim is trusted.
- **No live D1 numbers.** All coverage figures here are from the earlier audit and the container mirror; re-baseline
  after Phase 0.

---------------------------------------------------------------------------------------------------

## 7. Decisions for Nico

1. **Plan:** stay on Workers Free (feasible after Phase 0; the D1 write budget in 4.7 is the binding limit) or move to Workers Paid
   (removes D1/KV/request daily limits; R2 is already enabled on the free plan). Recommendation: Phase 0 first, then
   decide with a measured day of usage; moving to Paid is cheap insurance.
2. **Colour milestone: DECIDED by Nico** - exact 8-bit L2 from the start (16.7M RGB opaque first; 352M with opacity later). The 25-step and 5-step grids are roll-ups.
3. **Tile extraction: now a core requirement** (consequence of decision 2). A frame may contribute many colours (tile grid); this changes the extractor's "one colour
   per frame" semantics for survey clips only. Speed-up up to 3,600x; the only way L2 is realistic. Confirm the starting grid (144 for opaque, 576 for opacity planes).
4. **Opacity:** accept render-verified (T2) opacity cells in headline coverage, or require extractor-observed
   alpha (needs an RGBA/matte pass)?
5. **Survey clips:** may a share of loop capacity (suggest 30-50%) go to unpublished calibration clips? Or must
   every clip be publishable (much slower; the dense spaces become multi-year)?
6. **Cross-axis scope:** pairs only, or pairs then triples? (Triples are ~35 days of balanced-loop time.)
7. **Declared vs observed:** agree to separate declared (authored) cells from observed ones, which will lower
   today's reported sound/narrative coverage figures.
8. **Extractor investment:** order of upgrades (transition duration, camera, depth, audio semantic).
9. **Scope exclusions:** confirm linguistic/interpretation text and the full entity key are out of "every
   combination".

---------------------------------------------------------------------------------------------------

## Appendix A. Evidence index

- Colour key: `src/knowledge/growth_per_instance.py:32-41`; bin: `src/knowledge/registry.py:156-164`;
  opacity hard-coded: `src/knowledge/extractor_per_instance.py:236`; frame mean colour: `src/analysis/metrics.py:26-38`;
  per-frame extraction: `extractor_per_instance.py:208-239`.
- Sound key: `growth_per_instance.py:44-58`; classifier: `src/knowledge/blend_depth.py:60-81,137-174`;
  per-frame audio features: `extractor_per_instance.py:123-186`.
- Dynamic keys: `growth_per_instance.py:163-243`; window extraction: `extractor_per_instance.py:281-428`
  (camera 352-363, transition 388-405, depth 427, audio semantic 258-278, 365-367).
- Origins and sizes: `src/knowledge/origins.py:12-197`; `src/knowledge/completion_targets.py:20-109`;
  `cloudflare/src/registryConstants.generated.ts`.
- Declared stamping: `src/creation/novelty.py:49-133`; `growth_per_instance.py:117-160,1154`;
  builder call sites `src/creation/builder.py:382-417,476-483`.
- Targeting today: `src/knowledge/mission_targets.py:74-127`; `cloudflare/src/missionStats.ts`.
- Worker costs: `cloudflare/src/routes/knowledge.ts:64-543,572-867`; `cloudflare/src/browseCache.ts:50-83`;
  `cloudflare/src/routes/registries.ts:424-641`; schemas `cloudflare/migrations/0003-0022`.
- Loop cadence: `docker-compose.local.yml:91-183`; camera moves `src/procedural/camera_variation.py:17-40`.
- Vendor limits: Cloudflare D1 pricing and KV limits pages (fetched 2026-10-26).