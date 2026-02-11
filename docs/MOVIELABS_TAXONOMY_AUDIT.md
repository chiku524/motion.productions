# MovieLabs Ontology Taxonomy Audit

**Audit date:** 2026-02-10  
**Reference:** [MovieLabs Ontology for Media Creation (OMC)](https://mc.movielabs.com/docs/ontology/), Camera Metadata v2.8

## Summary

The MovieLabs Ontology for Media Creation (OMC) covers **technical production metadata** (sensor, lens, recorder, color space, LUTs) rather than **creative camera moves**. Motion.productions focuses on creative primitives for procedural video (pan, tilt, dolly, zoom, etc.). Our taxonomy aligns with industry film terminology (StudioBinder, CineTechBench) where applicable.

## MovieLabs Camera Metadata Scope

- **Recorder Metadata** — shooting configuration (log vs linear, color space)
- **Lens Metadata** — focal length, aperture, focus
- **Camera Metadata** — asset-level metadata for post processing (e.g. LUT selection)

MovieLabs does **not** define a controlled vocabulary for creative camera movements (pan, tilt, dolly). Those come from film craft practice and external references.

## Motion.productions Camera Primitives

Our `origins.py` and Worker static registry define:

| Primitive   | Definition                          | Industry alignment        |
|------------|--------------------------------------|---------------------------|
| static     | No movement                          | Standard                  |
| pan        | Horizontal rotation                  | Standard                  |
| tilt       | Vertical rotation                    | Standard                  |
| dolly      | Push in / pull out                   | Standard                  |
| crane      | Vertical movement + zoom             | Standard                  |
| zoom       | Zoom in (focal change)               | Standard                  |
| zoom_out   | Zoom out                             | Standard                  |
| handheld   | Handheld feel                        | Standard                  |
| roll       | Camera roll (rotation on axis)       | Standard                  |
| truck      | Lateral movement                     | Standard                  |
| pedestal   | Vertical camera move                 | Standard                  |
| arc        | Orbital / arc movement               | Standard                  |
| tracking   | Follow subject horizontally          | Standard                  |
| birds_eye  | Overhead / aerial feel               | Standard                  |
| whip_pan   | Fast horizontal sweep                | Standard                  |
| rotate     | General rotation (used in builder)   | Standard                  |

## Alignment

- **MovieLabs:** Technical metadata for interoperability and post workflows.
- **Motion.productions:** Creative primitives for procedural generation.

No conflicts. Where MovieLabs defines concepts (e.g. Shot, Scene, Slate), our narrative/composition primitives (framing, scene_type, settings) are compatible. Our camera moves are orthogonal to MovieLabs Camera Metadata (which is about sensor/lens configuration, not movement type).

## Recommendations

1. **Keep current taxonomy** — aligned with film craft and widely used terminology.
2. **Future:** If MovieLabs publishes a creative-move vocabulary, consider aligning new primitives.
3. **Docs:** Reference this audit when adding camera primitives to ensure consistency.
