# Exhaustive Registry Plan: discovering and recording every combination

Status: DESIGN ONLY. No code is changed by this document. Branch `exhaustive-registry-plan`, local, not pushed.
Date: 2026-10-26. Author: Grok Bot for Nico Chikuji.
Mission (Nico, 2026-10-26): "for both colors and sound and motion (etc), every combination in the long run
[should] be discovered and recorded into the registry ... so that it can be later used within video generation."

All file:line references are against `main` at f773e67. Sizes are computed from the key formulas in the code,
not measured from live D1 (D1 was over its daily read limit while this was written). Anything inferred rather than
read from code or computed is marked **(inferred)**. Cloudflare limits are from the vendor docs
(D1 pricing page, KV limits page) fetched 2026-10-26.

---------------------------------------------------------------------------------------------------

## 0. Summary

1. **Literal "every combination" is possible only for some spaces.** It is realistic for: static colour at the
   current 25-step grid plus opacity (27,951 cells), colour at a 5-step grid (140,608 RGB cells), pure sound (a
   few thousand cells), camera / transition / depth / technical / audio-semantic / narrative / gradient (all
   under ~200 cells each), and the origin-defined "intent" grids (hundreds to low thousands per axis). It is
   possible but long for 8-bit-exact colour (16.8M RGB, 352M with opacity). It is **impossible** for the full
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
   level 0); (b) a cell ordinal (mixed-radix integer) per key so coverage is a **bitset** (44 MB covers
   352M colour cells; 0.4 MB covers the 5-step colour grid with opacity); (c) a **one-row-per-clip claim ledger**
   folded into bitset chunks by a cron, so cost per clip is ~2 D1 row writes instead of ~65; (d) a **seeded
   permutation work queue** (cycle-walking Feistel over cell ordinals, leased in blocks) so workers
   deterministically target unseen cells with no table scans; (e) a **closed-loop render -> extract ->
   compare** verifier with three evidence tiers (observed / render-verified / declared), so coverage numbers are
   honest; (f) **survey clips** (calibration swatches and sweeps that are never published) that fill dense
   spaces cheaply, alongside normal creative clips that fill the dynamic axes.
5. **Smallest first step (Phase 0 + 1, about a week of work):** stop the read/write amplification, add the
   ledger plus bitset for the colour 5-step grid at opacity 1.0 (140,608 cells, ~6k survey clips, about one day of
   loop time), and report honest coverage. See section 5.

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
| Free-tier reset | 00:00 UTC (8 PM ET) | n/a |

D1 counts **rows scanned**, a full-table `ORDER BY` on an unindexed column costs the whole table, an index adds
one written row per indexed write, and one row costs one read regardless of size. That last point is why
chunked bitset BLOBs (one row = 64 KB = 524,288 cells) are the cheapest coverage store in D1.

Separate blocker found this session: the Cloudflare Worker deploy fails with R2 error 10136 (R2 not enabled on the
account). R2 / paid-plan decisions are in section 7.

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

- **Key.** `_static_color_key` (`growth_per_instance.py:32-41`) = floor each channel to a multiple of 25
  (`registry.py:156-164`) -> values 0,25,...,250 (11 bins; the top bin 250 covers 250-255), plus opacity rounded to
  21 steps. 11^3 = 1,331 RGB cells, x21 = 27,951.
- **Coverage.** 1,331 RGB cells at opacity 1.0 are present (parent audit); 26,620 cells (95.2%) have opacity < 1.0
  and are unreachable because the extractor decodes RGB only (`extractor_per_instance.py:236`).
- **Finite and enumerable.** Yes. The only blockers are opacity observability and the codec at finer levels.
- **Finer levels, nested so level 0 stays valid** (`floor(v/25) = floor(floor(v/5)/5)`):

| Level | Step | RGB cells | x21 opacity | Bitset size (x21) |
|---|---|---|---|---|
| L0 (existing) | 25 | 1,331 | 27,951 | 3.5 KB |
| L1 | 5 | 52^3 = 140,608 | 2,952,768 | 0.37 MB |
| L2 | 1 (exact 8-bit) | 256^3 = 16,777,216 | 352,321,536 | 44.0 MB |

- **Opacity.** A decoded RGB frame has no alpha. Options in section 4.6: (T2) the renderer composites the target
  colour at alpha a over a known backdrop and the verifier checks the composite against the expected value
  pre-encode (evidence tier "render-verified"); (T1) add an RGBA / matte pass so the extractor can read alpha
  (needs renderer and extractor work). Without one of these, opacity < 1 cells can only be "declared" and must not
  count toward coverage.
- **Capacity per clip.** One colour per frame (`extractor:217`; it is really the frame mean, see 4.6) -> ~24 cells per 1 s clip at 24 fps
  (assumption: fps 24, the key default). Multi-region extraction (e.g. a 4x4 tile grid per frame, 16 cells per
  frame -> 384 per clip) is the biggest lever and is a decision (section 7).

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
| `color.L0` | r25(11) g25(11) b25(11) opacity(21) | 27,951 | existing `static_colors.color_key` (unchanged) |
| `color.L1` | r5(52) g5(52) b5(52) opacity(21) | 2,952,768 | new; L0 is the parent |
| `color.L2` | r(256) g(256) b(256) opacity(21) | 352,321,536 | new; L1 is the parent |
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
coverage_ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id, space_id, tier, kind,   -- kind = seen|fail
                ordinals BLOB, n INTEGER, created_at)          -- one row per clip per space; varint-encoded
cell_failures(space_id, ordinal, n, last_reason, PRIMARY KEY (space_id, ordinal))      -- sparse
target_cursors(space_id PRIMARY KEY, seed, next_index, lease_epoch)                    -- 1 row per space
```

- **Write path (per clip).** Python dedupes the clip's observed ordinals, then `POST /api/coverage/claims` with
  one body listing `{space, tier, ordinals[]}` for all spaces. The Worker inserts one `coverage_ledger` row per
  (clip, space) with no secondary index: ~1-12 row writes per clip, independent of how many cells the clip hit.
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
- **Size.** `color.L2` x opacity = 44.0 MB per tier (about 672 chunk rows); three tiers = 132 MB. `color.L1` x
  opacity = 0.37 MB. Everything else together < 1 MB. Well inside D1 5 GB and the 2 MB row limit.

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

### 4.7 Cost model (Cloudflare)

Current pattern, from code reading (**inferred**, confirm with D1 analytics):

| Per clip | Reads | Writes | KV ops |
|---|---|---|---|
| ~65 discovery items (SELECT + UPDATE/INSERT, `knowledge.ts:173-504`) | ~65 | ~65-130 | ~5 writes/deletes (`browseCache.ts:50-83`) |
| for-creation rebuild after each POST (`knowledge.ts:587-598`) | ~5,400 (scan of unindexed `ORDER BY count`) | 0 | 1 put |

At ~5,760 clips/day that is ~31M reads and ~375k+ writes per day, i.e. about 6x the free read limit and 3.7x the free
write limit, plus >28k KV writes against a 1,000/day limit.

Proposed pattern:

| Item | Per clip | Per day at 5,760 clips |
|---|---|---|
| Claim ledger writes (1 row per space touched, ~1-6 spaces) | 1-6 | ~6k-35k writes |
| Lease calls (block of 64 indices, ~24 cells/clip consumed) | ~0.4 | ~2.3k writes |
| Chunk reads for skip-seen (cached per run) | ~0.1 | ~0.6k reads |
| Compaction cron (144 runs: ~70 ledger rows + ~50 chunk read/write each) | n/a | ~17k reads, ~7k writes |
| Legacy per-item writes, only for *novel* L0 cells (saturating) | ~0-2 | < 12k writes |
| KV writes | 0 (cursors and state live in D1) | 0 |
| **Total** | | **~20-55k writes, ~20-30k reads** |

This fits inside the free tier (100k writes, 5M reads, 1,000 KV writes) with headroom, provided Phase 0 removes
the per-POST for-creation invalidation and KV writes. At 20k clips/day it still fits paid limits trivially
(50M writes/month included). Storage: ledger ~3.5 MB/day pruned at 7 days; coverage chunks <= 132 MB for the
whole colour L2 x opacity x 3-tier space.

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

- **Colour L2 x opacity (352M):** literal coverage needs tile extraction (~5-8 months at current capacity, 3 tiers
  of bitset), otherwise years. Recommend committing to L1 x opacity (2.95M) as the "exhaustive" milestone and
  treating L2 as a long-run background fill with a stated progress percentage.
- **Cross-axis:** commit to *t-wise coverage* (pairs first, then triples) over macro cells.
- **Entity extended key (~3.9M):** cover base (182), base x colour family, then pairwise over the remaining fields.
- **Composition / lighting raw grids (1M / 154k):** the nested bins in 2.4 replace them; the raw 0.01 grids are
  not a goal.
- **Open text:** not enumerated.

Every report must show, per space: `observed / size`, `render-verified / size`, `declared / size`, `quarantined`.

---------------------------------------------------------------------------------------------------

## 5. Phased roadmap

**Phase 0 - stop the bleeding (about 2-3 days, no new features).** Required before anything else.
1. Cut the for-creation rebuild cost: add an index (or a pre-aggregated top-N cache) for `ORDER BY count DESC`
   queries, and stop bumping the generation on every POST; use a time-based key (for example 5-10 min) instead.
2. Stop KV writes per POST (`browseCache.ts:50-83`) or move the state into D1.
3. Batch/dedupe discoveries client-side (24 identical-colour frames -> 1 item) and write counts only for novel
   cells.
4. Measure with D1 analytics (`meta.rows_read/rows_written`) over one day to confirm the section 4.7 numbers.
5. Fix R2 enablement so the Worker can deploy (account-side).
Exit: a full day with zero D1/KV limit errors at the current cadence.

**Phase 1 - smallest useful exhaustive step: colour L1 at opacity 1.0 (about 1 week).**
1. `keyspace.py` / `keyspace.ts` plus test vectors; `key_spaces`, `coverage_chunks`, `coverage_ledger`,
   `target_cursors` migrations; claims, chunk, lease endpoints; compaction cron.
2. Offline acceptance test (no D1): render the 140,608 L1 cell centres as flat swatches, encode with the loop's
   settings, extract, and measure round-trip accuracy. This yields the real efficiency number.
3. Survey template + Feistel queue for `color.L1`; honest coverage endpoint.
Exit: 140,608/140,608 L1 cells observed (T1) or quarantined with reasons, in about 1-3 days of loop time.

**Phase 2 - sound and the finite dynamic axes (2-3 weeks).**
`sound.L1` key from already-measured features and an amplitude/band/flatness synthesiser; fix transition duration
measurement; render-verified camera/depth from render metadata; motion/lighting/composition/graphics/gradient
nested bins; replace "primitives present" coverage with real per-level coverage.

**Phase 3 - cross-axis guarantee (2-3 weeks).**
Covering-array generator over macro cells; calibration sweeps (4.5); creative-clip targets as soft constraints;
pairwise coverage report, then 3-wise.

**Phase 4 - opacity and fine colour (open-ended).**
Opacity via T2 composite verification or an RGBA matte pass; tile extraction; `color.L1 x 21`, then `color.L2`
as background fill.

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
- **Scale of names.** Naming millions of cells would blow D1 and OpenAI budgets; names are lazy.
- **Free-tier headroom** is real but thin if survey volume grows; see decision 1.
- **No live D1 numbers.** All coverage figures here are from the earlier audit and the container mirror; re-baseline
  after Phase 0.

---------------------------------------------------------------------------------------------------

## 7. Decisions for Nico

1. **Plan:** stay on Workers Free (feasible only after Phase 0, thin headroom) or move to Workers Paid
   (removes D1/KV daily limits, needed anyway if R2 billing must be enabled). Recommendation: Phase 0 first, then
   decide with a measured day of usage; moving to Paid is cheap insurance.
2. **Colour milestone:** is "every colour" = L1 (5-step, 140,608 RGB; 2.95M with opacity) or exact 8-bit L2
   (16.8M RGB; 352M with opacity)? Recommendation: L1 as the milestone, L2 as background.
3. **Tile extraction:** may a frame contribute many colours (tile grid), changing the extractor's "one colour per
   frame" semantics? It is the biggest speed-up (about 16x) and the only way L2 x opacity is realistic.
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