"""
Sound: procedural audio, SFX, mix with video. Phase 6.
Procedural audio uses origins: tempo, mood, presence.
Requires: pydub, ffmpeg and ffprobe on PATH.
"""
from __future__ import annotations

import logging
import os
import random
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Sound v2: the synth used to squeeze every amplitude into -30..-18 dB, so measured RMS above ~0.13 was
# unreachable and amplitude keys collapsed. amp_to_db maps a registry amplitude (target RMS, 0..1) to the
# dB of a sine whose measured RMS equals it, capped at PEAK_CEILING_DB so clips never clip.
PEAK_CEILING_DB = -1.0
SILENT_DB = -60.0
# Creative (video) clips stay at the old listening level: headroom shifts the whole range down, so the old
# mid amplitude (0.5 -> -23 dB) is unchanged while the span is now ~-77..-18 dB instead of -28..-18.
CREATIVE_HEADROOM_DB = float(os.environ.get("SOUND_CREATIVE_HEADROOM_DB", "20") or 20)


def amp_to_db(amplitude: float) -> float:
    """Volume (dB, for a sine) whose RMS equals ``amplitude`` (0..1); log-scale, capped at the peak ceiling."""
    import math

    a = max(0.0, min(1.0, float(amplitude or 0.0)))
    if a < 0.001:
        return SILENT_DB
    return max(SILENT_DB, min(PEAK_CEILING_DB, 20.0 * math.log10(a) + 3.0103))


def limit_peak(audio, ceiling_db: float = PEAK_CEILING_DB):
    """Scale an AudioSegment down (never up) so its peak stays at or below ceiling_db. Deterministic."""
    try:
        if audio.max > 0 and audio.max_dBFS > ceiling_db:
            return audio.apply_gain(ceiling_db - audio.max_dBFS)
    except Exception:  # pragma: no cover - defensive: never fail a clip over the limiter
        pass
    return audio


def generate_silence(duration_seconds: float, sample_rate: int = 44100) -> "bytes":
    """Generate silence as raw PCM bytes."""
    try:
        from pydub import AudioSegment
    except ImportError:
        return b""
    seg = AudioSegment.silent(duration=int(duration_seconds * 1000), frame_rate=sample_rate)
    return seg.raw_data


def generate_tone(
    frequency: float,
    duration_seconds: float,
    *,
    volume_db: float = -20,
    sample_rate: int = 44100,
) -> "bytes":
    """Generate a simple sine tone. For procedural SFX building blocks."""
    try:
        from pydub.generators import Sine
    except ImportError:
        return b""
    gen = Sine(frequency)
    seg = gen.to_audio_segment(duration=int(duration_seconds * 1000))
    seg = seg + volume_db
    return seg.raw_data


def mix_audio_to_video(
    video_path: Path,
    output_path: Path | None = None,
    *,
    audio_path: Path | None = None,
    mood: str = "neutral",
    tempo: str = "medium",
    presence: str = "ambient",
    cut_times: list[float] | None = None,
    pure_sounds: list[dict] | None = None,
    sound_pairing: str | None = None,
    audio_genre: str = "none",
    audio_vocals: bool = False,
    sfx_events: list[dict] | None = None,
    vocal_phrase: str | None = None,
    music_sections: list[str] | None = None,
    script_beats: list[dict] | None = None,
    cut_transitions: list[str] | None = None,
    seed: int | None = None,
) -> Path:
    """
    Add audio to a video. Phase 6+.
    - If audio_path: mix that file.
    - Else if sound_pairing / pure_sounds: mix a unique registry pairing (static or window).
    - Else if presence=music or audio_genre set: in-house arrangement engine.
    - Else: procedural ambient from origins.
    - Overlay event SFX (bounce etc.) and optional offline vocals.
    - cut_times: soft click accents at scene cuts.
    """
    try:
        from pydub import AudioSegment
    except ImportError as e:
        raise RuntimeError(
            "pydub is required for audio. Install with: pip install pydub"
        ) from e

    import subprocess

    video_path = Path(video_path)
    output_path = output_path or video_path.parent / (video_path.stem + "_with_audio" + video_path.suffix)
    in_place = output_path.resolve() == video_path.resolve()

    final_output = output_path
    if in_place:
        fd, tmp_out = tempfile.mkstemp(suffix=".mp4", prefix="mux_")
        os.close(fd)
        output_path = Path(tmp_out)

    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        duration = float(out.stdout.strip() or 5.0)
    except FileNotFoundError as e:
        raise RuntimeError(
            "ffprobe not found. Audio requires ffmpeg. Install: winget install FFmpeg / brew install ffmpeg / apt install ffmpeg"
        ) from e
    except (subprocess.CalledProcessError, ValueError) as e:
        logger.warning("ffprobe failed for %s: %s — using duration 5.0s", video_path, e)
        duration = 5.0

    duration_ms = int(duration * 1000)

    if audio_path and audio_path.exists():
        audio = AudioSegment.from_file(str(audio_path))
        audio = audio[:duration_ms]
    else:
        audio = _build_audio_bed(
            duration_ms=duration_ms,
            mood=mood,
            tempo=tempo,
            presence=presence,
            pure_sounds=pure_sounds,
            sound_pairing=sound_pairing,
            audio_genre=audio_genre,
            music_sections=music_sections,
            script_beats=script_beats,
            seed=seed,
        )

    # Cut accents + event SFX
    from .event_sfx import schedule_sfx_events, cut_accent_events
    events = list(sfx_events or [])
    events.extend(cut_accent_events(cut_times, transition_types=cut_transitions))
    audio = schedule_sfx_events(audio, events, duration_ms=duration_ms)

    # Offline vocals
    if audio_vocals or (presence == "music" and audio_genre not in ("none", "")):
        from .vocals import mix_vocals_into
        # Only force vocal bed when explicitly requested
        if audio_vocals:
            audio = mix_vocals_into(
                audio,
                enable=True,
                mood=mood,
                phrase=vocal_phrase,
                duration_ms=duration_ms,
                script_beats=script_beats,
            )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = f.name
    try:
        audio.export(tmp_wav, format="wav")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path), "-i", tmp_wav, "-c:v", "copy", "-c:a", "aac", "-shortest", str(output_path)],
                capture_output=True,
                check=True,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "ffmpeg not found. Audio requires ffmpeg on PATH. Install: winget install FFmpeg / brew install ffmpeg / apt install ffmpeg"
            ) from e
    finally:
        Path(tmp_wav).unlink(missing_ok=True)

    if in_place:
        shutil.move(str(output_path), str(final_output))
        return final_output
    return output_path


def _build_audio_bed(
    *,
    duration_ms: int,
    mood: str,
    tempo: str,
    presence: str,
    pure_sounds: list[dict] | None,
    sound_pairing: str | None = None,
    audio_genre: str,
    music_sections: list[str] | None = None,
    script_beats: list[dict] | None = None,
    seed: int | None = None,
):
    """Select music arrangement vs ambient vs sfx-only bed."""
    from pydub import AudioSegment

    presence = (presence or "ambient").lower()
    genre = (audio_genre or "none").lower()

    if presence == "silence":
        return AudioSegment.silent(duration=duration_ms, frame_rate=44100)

    if sound_pairing and pure_sounds:
        return generate_audio_from_pure_sounds(
            pure_sounds,
            duration_ms=duration_ms,
            pairing_kind=sound_pairing,
            seed=seed,
        )

    use_music = presence in ("music", "full") or genre not in ("none", "", "ambient")
    if use_music and genre in ("none", "", "ambient") and presence == "music":
        genre = "deep_house"

    section_durations_ms = None
    if script_beats:
        durs = []
        for b in script_beats:
            if not isinstance(b, dict):
                continue
            if b.get("duration_sec") is not None:
                durs.append(float(b["duration_sec"]) * 1000.0)
            elif b.get("t_end") is not None and b.get("t_start") is not None:
                durs.append(max(1.0, (float(b["t_end"]) - float(b["t_start"])) * 1000.0))
        if durs:
            section_durations_ms = durs

    if use_music and genre not in ("none", ""):
        from .music import generate_arrangement_audio
        music = generate_arrangement_audio(
            duration_ms,
            genre=genre if genre != "ambient" else "ambient",
            tempo=tempo,
            mood=mood,
            music_sections=music_sections,
            section_durations_ms=section_durations_ms,
        )
        if presence == "full":
            # Layer light ambient under music
            amb = _generate_procedural_audio(duration_ms, mood=mood, tempo=tempo, presence="ambient")
            music = music.overlay(amb + (-8))
        return music

    if presence == "sfx":
        # Sparse transient bed only (events overlay later)
        base = AudioSegment.silent(duration=duration_ms, frame_rate=44100)
        sparse = _generate_procedural_audio(duration_ms, mood=mood, tempo=tempo, presence="sfx")
        return base.overlay(sparse + (-4))

    if pure_sounds and len(pure_sounds) > 0:
        return generate_audio_from_pure_sounds(pure_sounds, duration_ms=duration_ms)

    return _generate_procedural_audio(duration_ms, mood=mood, tempo=tempo, presence=presence)


def _tone_to_freq_db(tone: str, amplitude: float) -> tuple[float, float]:
    """Map tone (low/mid/high/silent) and amplitude (0–1) to (frequency_hz, volume_db)."""
    tone_lower = (tone or "").strip().lower()
    if tone_lower in ("silent", "silence", "") or (amplitude or 0) < 0.01:
        return 0.0, -60.0  # effectively silent
    freq_map = {"low": 82.0, "mid": 220.0, "high": 880.0}
    freq = freq_map.get(tone_lower, 220.0)
    # Amplitude 0–1 → dB about -30 (quiet) to -18 (audible)
    amp = max(0.0, min(1.0, float(amplitude or 0.5)))
    db = amp_to_db(amp) - CREATIVE_HEADROOM_DB  # log scale; was -30..-18 dB (amplitude keys > ~0.13 unreachable)
    return freq, db


def _primitive_from_entry(entry: dict) -> str:
    """Resolve a registry sound to an origin primitive (diversity-aware; see pairing.entry_primitive)."""
    from .pairing import entry_primitive

    return entry_primitive(entry)


def _primitive_texture_legacy(
    prim: str,
    duration_ms: int,
    *,
    db: float = -20.0,
    tempo_ms: int = 2500,
    sample_rate: int = 44100,
):
    """One SOUND_ORIGIN_PRIMITIVES texture for the full duration (pairing building block)."""
    from pydub import AudioSegment
    from pydub.generators import Sine

    try:
        from pydub.generators import WhiteNoise
    except ImportError:
        WhiteNoise = None  # type: ignore[misc, assignment]

    prim = (prim or "tone").strip().lower()
    base = AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)
    if prim in ("silence", "silent") or duration_ms <= 0:
        return base

    def _noise(dur: int, volume: float):
        if WhiteNoise is None:
            return Sine(4000).to_audio_segment(duration=max(1, dur)) + volume
        return WhiteNoise().to_audio_segment(duration=max(1, dur)) + volume

    if prim == "hiss":
        return base.overlay(_repeat_to_duration(_noise(min(800, duration_ms), db - 4), duration_ms))
    if prim == "hum":
        hum = Sine(60).to_audio_segment(duration=min(2000, duration_ms)) + (db - 2)
        return base.overlay(_repeat_to_duration(hum, duration_ms))
    if prim == "rumble":
        rumble = Sine(40).to_audio_segment(duration=min(2500, duration_ms)) + db
        return base.overlay(_repeat_to_duration(rumble, duration_ms))
    if prim == "rustle":
        result = base
        for t in range(0, duration_ms, 180):
            result = result.overlay(_noise(min(60, duration_ms - t), db - 4), position=t)
        return result
    if prim == "click":
        result = base
        step = max(400, tempo_ms // 2)
        for t in range(0, duration_ms, step):
            click = Sine(2000).to_audio_segment(duration=18) + (db + 2)
            result = result.overlay(click, position=t)
            if WhiteNoise is not None:
                result = result.overlay(_noise(12, db), position=t)
        return result
    if prim == "whoosh":
        result = base.overlay(_noise(min(900, duration_ms), db - 2), position=max(0, duration_ms // 4))
        sweep = Sine(800).to_audio_segment(duration=min(600, duration_ms)) + (db - 6)
        return result.overlay(_repeat_to_duration(sweep, duration_ms))
    if prim == "thump":
        result = base
        thump = Sine(55).to_audio_segment(duration=80).fade_out(70) + (db + 4)
        for t in range(0, duration_ms, max(500, tempo_ms)):
            result = result.overlay(thump, position=t)
        return result
    if prim == "drip":
        result = base
        for t in range(200, duration_ms, 700):
            result = result.overlay(Sine(1200).to_audio_segment(duration=30) + (db - 2), position=t)
        return result
    # tone (default)
    mid = Sine(330).to_audio_segment(duration=min(1500, duration_ms)) + (db - 4)
    return base.overlay(_repeat_to_duration(mid, duration_ms))


def _audio_rng(seed: int, *salt) -> random.Random:
    """Deterministic RNG for audio parameters, keyed by clip seed + salt."""
    import hashlib

    key = "|".join(str(x) for x in (int(seed), *salt)).encode()
    return random.Random(int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big"))


def layer_seed(seed: int | None, idx: int) -> int | None:
    """Per-layer seed derived from the clip seed (None keeps legacy fixed textures)."""
    if seed is None:
        return None
    return (int(seed) * 31 + int(idx) * 7919) & 0x7FFFFFFF


def _primitive_texture(
    prim: str,
    duration_ms: int,
    *,
    db: float = -20.0,
    tempo_ms: int = 2500,
    sample_rate: int = 44100,
    seed: int | None = None,
):
    """One SOUND_ORIGIN_PRIMITIVES texture for the full duration.

    seed=None: the legacy fixed texture (same frequency/rhythm/envelope every time).
    seed set: frequency, partials, rhythm (step + jitter + accents), burst length,
    filter band and envelope are all drawn per primitive from the seed, so two clips
    that share a primitive no longer share a spectrum or groove.
    """
    if seed is None:
        return _primitive_texture_legacy(
            prim, duration_ms, db=db, tempo_ms=tempo_ms, sample_rate=sample_rate
        )

    import math

    from pydub import AudioSegment
    from pydub.generators import Sine

    prim = (prim or "tone").strip().lower()
    base = AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)
    if prim in ("silence", "silent") or duration_ms <= 0:
        return base
    rng = _audio_rng(seed, prim)

    def sine(freq: float, dur: int, gain: float):
        return Sine(freq, sample_rate=sample_rate).to_audio_segment(duration=max(2, int(dur))) + gain

    def noise(dur: int, gain: float, lo: float | None = None, hi: float | None = None):
        import numpy as np

        n = max(2, int(sample_rate * max(2, int(dur)) / 1000))
        nrng = np.random.default_rng(rng.getrandbits(32))
        samples = np.clip(nrng.standard_normal(n) * 0.25, -1.0, 1.0)
        seg = AudioSegment(
            data=(samples * 32767).astype("<i2").tobytes(),
            sample_width=2,
            frame_rate=sample_rate,
            channels=1,
        )
        if hi:
            seg = seg.low_pass_filter(hi)
        if lo:
            seg = seg.high_pass_filter(lo)
        return seg + gain

    def shaped(seg, attack: int, release: int):
        n = len(seg)
        if attack > 0:
            seg = seg.fade_in(min(attack, max(1, n - 1)))
        if release > 0:
            seg = seg.fade_out(min(release, max(1, n - 1)))
        return seg

    def pulses(make, step: float, jitter: float, first: int = 0, accent_every: int = 0, accent_db: float = 4.0):
        """Place make() at jittered intervals (the per-primitive rhythm)."""
        out = base
        t = float(first)
        k = 0
        while t < duration_ms:
            ev = make(k)
            if accent_every and k % accent_every == 0:
                ev = ev + accent_db
            out = out.overlay(ev, position=int(t))
            t += max(60.0, step * (1.0 + rng.uniform(-jitter, jitter)))
            k += 1
        return out[:duration_ms]

    def gate(seg, period: int, duty: float):
        """Chop a continuous texture into pulses (rhythm for drones)."""
        out = base
        on = max(20, int(period * duty))
        for t in range(0, duration_ms, max(40, period)):
            piece = seg[t : t + on]
            if len(piece) > 8:
                out = out.overlay(shaped(piece, 6, min(25, len(piece) // 2)), position=t)
        return out[:duration_ms]

    jitter = rng.uniform(0.0, 0.35)
    first = rng.randint(0, max(1, min(400, duration_ms // 4)))
    accent_every = rng.choice((0, 0, 2, 3, 4))
    chop = rng.random() < 0.45
    period = rng.randint(120, 650)
    duty = rng.uniform(0.35, 0.9)

    def sustained(seg):
        loop = _repeat_to_duration(seg, duration_ms)
        if chop:
            loop = gate(loop, period, duty)
        loop = shaped(loop, rng.choice((0, 30, 120, 300)), rng.choice((0, 40, 160)))
        return base.overlay(loop)

    if prim == "hiss":
        hi = rng.uniform(3500, 14000)
        lo = rng.choice((None, rng.uniform(800, 5000)))
        burst = noise(rng.randint(120, 900), db - 4, lo=lo, hi=hi)
        return sustained(burst)
    if prim == "hum":
        f = math.exp(rng.uniform(math.log(45), math.log(240)))
        seg = sine(f, rng.randint(300, 1600), db - 2)
        for mult in rng.sample((2, 3, 4, 5), rng.randint(0, 2)):
            seg = seg.overlay(sine(f * mult, len(seg), db - 2 - rng.uniform(5, 14)))
        return sustained(seg)
    if prim == "rumble":
        f = rng.uniform(26, 78)
        seg = sine(f, rng.randint(500, 2500), db)
        seg = seg.overlay(noise(len(seg), db - rng.uniform(6, 14), hi=rng.uniform(80, 220)))
        return sustained(seg)
    if prim == "rustle":
        lo = rng.uniform(300, 3000)
        hi = lo + rng.uniform(1500, 7000)
        blen = rng.randint(25, 110)
        return pulses(
            lambda k: shaped(noise(blen, db - 4 + rng.uniform(-3, 2), lo=lo, hi=hi), 4, blen // 2),
            step=rng.uniform(70, 320), jitter=max(jitter, 0.2), first=first,
        )
    if prim == "click":
        f = rng.uniform(900, 4800)
        clen = rng.randint(6, 30)
        with_noise = rng.random() < 0.6
        def make_click(k):
            c = shaped(sine(f * rng.uniform(0.97, 1.03), clen, db + 2), 0, clen - 1)
            if with_noise:
                c = c.overlay(noise(max(6, clen // 2), db))
            return c
        return pulses(make_click, step=rng.uniform(140, 700), jitter=jitter, first=first,
                      accent_every=accent_every)
    if prim == "whoosh":
        lo = rng.choice((None, rng.uniform(200, 1500)))
        hi = rng.uniform(2500, 9000)
        n_swells = rng.choice((1, 1, 2))
        out = base
        for s in range(n_swells):
            dur = rng.randint(300, 900)
            start = rng.randint(0, max(1, duration_ms - 200))
            swell = shaped(noise(dur, db - 2, lo=lo, hi=hi), dur // 3, dur // 3)
            out = out.overlay(swell, position=start)
            f0 = rng.uniform(250, 1600)
            f1 = f0 * rng.uniform(0.4, 2.6)
            glide = AudioSegment.empty()
            steps = 4
            for i in range(steps):
                glide += sine(f0 + (f1 - f0) * i / (steps - 1), dur // steps, db - 6)
            out = out.overlay(shaped(glide, 40, 80), position=start)
        return out[:duration_ms]
    if prim == "thump":
        f = rng.uniform(38, 125)
        tlen = rng.randint(55, 190)
        return pulses(
            lambda k: shaped(sine(f * rng.uniform(0.96, 1.04), tlen, db + 4), 0, tlen - 4),
            step=rng.uniform(230, 950), jitter=jitter, first=first, accent_every=accent_every, accent_db=3.0,
        )
    if prim == "drip":
        f = rng.uniform(600, 2700)
        dlen = rng.randint(18, 70)
        drop = rng.uniform(0.55, 0.95)
        def make_drip(k):
            ff = f * rng.uniform(0.9, 1.1)
            half = max(4, dlen // 2)
            d = sine(ff, half, db - 2) + sine(ff * drop, half, db - 4)
            return shaped(d, 2, len(d) // 2)
        return pulses(make_drip, step=rng.uniform(200, 900), jitter=max(jitter, 0.15), first=first)
    # tone
    f = math.exp(rng.uniform(math.log(170), math.log(1500)))
    seg = sine(f, rng.randint(400, 1500), db - 4)
    seg = seg.overlay(sine(f * rng.uniform(1.004, 1.03), len(seg), db - 7))
    if rng.random() < 0.5:
        seg = seg.overlay(sine(f * rng.choice((1.5, 2.0, 2.5)), len(seg), db - rng.uniform(8, 15)))
    return sustained(seg)


def generate_audio_from_pure_sounds(
    pure_sounds: list[dict],
    duration_ms: int,
    *,
    sample_rate: int = 44100,
    pairing_kind: str = "frame",
    seed: int | None = None,
):
    """
    Mix a unique registry pairing into one track.

    frame: two (or more) textures held together for the clip - static instants.
    window: every layer plays under the whole clip while the lead rotates through
    the layers inside each window, so ALL layers are audible even in a 1 s clip.

    seed: when given, per-primitive frequency/rhythm/envelope, layer gain, start
    offsets, window length and lead order are drawn from it (None = legacy fixed sound).
    """
    try:
        from pydub import AudioSegment
    except ImportError as e:
        raise RuntimeError("pydub is required for audio. Install with: pip install pydub") from e

    entries = [e for e in (pure_sounds or []) if isinstance(e, dict)]
    if not entries:
        return AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)

    rng = _audio_rng(seed, "mix") if seed is not None else None
    layers = []
    for idx, entry in enumerate(entries):
        prim = _primitive_from_entry(entry)
        amp = float(entry.get("amplitude") or entry.get("weight") or 0.5)
        db = amp_to_db(amp) - CREATIVE_HEADROOM_DB  # was -28 + amp*10 (10 dB span); now log-scale full range
        if rng is not None:
            db += rng.uniform(-2.5, 2.5)
        layers.append(
            _primitive_texture(
                prim, duration_ms, db=db, sample_rate=sample_rate, seed=layer_seed(seed, idx)
            )
        )

    n = len(layers)
    layer_db = -8.0 * (1.0 / n) ** 0.5
    kind = (pairing_kind or "frame").strip().lower()
    base = AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)

    if kind != "window" or n < 2:
        for i, layer in enumerate(layers):
            if rng is not None:
                offset_ms = rng.randint(0, max(1, duration_ms // 4)) if i > 0 else 0
            else:
                offset_ms = (i * 47) % max(1, duration_ms // 4) if n > 2 else 0
            base = base.overlay(layer + layer_db, position=offset_ms)
        return limit_peak(base)

    window_ms = rng.choice((500, 700, 1000)) if rng is not None else 1000
    n_win = max(1, (duration_ms + window_ms - 1) // window_ms)
    fade = max(30, window_ms // 4)
    order0 = list(range(n))
    if rng is not None:
        rng.shuffle(order0)
    bed_db = layer_db - 7.0
    for wi in range(n_win):
        pos = wi * window_ms
        chunk_ms = min(window_ms, duration_ms - pos)
        if chunk_ms <= 0:
            break
        order = order0[wi % n :] + order0[: wi % n]
        slot = max(1, chunk_ms // n)
        for rank, li in enumerate(order):
            seg = layers[li][pos : pos + chunk_ms]
            # Every layer sounds for the whole window (quiet bed) ...
            base = base.overlay(seg + bed_db, position=pos)
            # ... and takes the lead for its own slot of the window.
            start = rank * slot
            lead_len = min(chunk_ms - start, slot + fade)
            if lead_len <= 2:
                continue
            lead = layers[li][pos + start : pos + start + lead_len] + (layer_db + 1.0)
            f = max(1, min(fade, lead_len // 2 - 1))
            lead = lead.fade_in(f).fade_out(f)
            base = base.overlay(lead, position=pos + start)
    return limit_peak(base)


def _repeat_to_duration(segment, duration_ms: int):
    """Repeat an AudioSegment until at least duration_ms, then slice to exact length. pydub has no .loop()."""

    n = len(segment)
    if n >= duration_ms:
        return segment[:duration_ms]
    repeats = (duration_ms + n - 1) // n
    repeated = segment * repeats
    return repeated[:duration_ms]


def _generate_procedural_audio(
    duration_ms: int,
    mood: str = "neutral",
    tempo: str = "medium",
    presence: str = "ambient",
    target_primitive: str | None = None,
) -> AudioSegment:
    """
    Generate procedural audio from origin primitives (AUDIO_ORIGINS).
    When target_primitive is set (rustle/click/whoosh/…), shape the waveform so
    Pure sound depth_breakdown can record that origin noise.
    """
    from pydub import AudioSegment

    frame_rate = 44100
    base = AudioSegment.silent(duration=duration_ms, frame_rate=frame_rate)

    if presence == "silence":
        return base

    try:
        from pydub.generators import Sine
    except ImportError as e:
        logger.warning("pydub.generators.Sine not available: %s — using silence for procedural audio", e)
        return base

    # Mood: frequency and volume (full AUDIO_ORIGINS mood set + film aliases).
    mood_config = {
        "neutral": (110, -22),
        "calm": (82, -20),
        "tense": (55, -18),
        "uplifting": (165, -20),
        "dark": (55, -18),
        "dramatic": (82, -15),
        "peaceful": (87, -25),
        "chaotic": (220, -14),
        "soft": (131, -26),
        "harsh": (247, -12),
        "dreamy": (174, -23),
        "bright": (262, -15),
        "energetic": (294, -13),
        "moody": (55, -20),
        "melancholy": (73, -22),
        "hopeful": (185, -17),
        "ominous": (48, -18),
        "playful": (330, -16),
        "suspenseful": (92, -17),
        "intense": (140, -12),
        "noir": (49, -19),
        "thriller": (44, -18),
    }
    freq, db = mood_config.get(mood, (110, -22))

    tempo_ms = {"slow": 4000, "medium": 2500, "fast": 1200}.get(tempo, 2500)
    tone_dur = min(tempo_ms, duration_ms)

    if presence == "full":
        db = max(db - 4, -24)
    elif presence == "sfx":
        # Sparse transient-oriented bed (events add the real hits)
        db = db - 6
    elif presence == "music":
        # Fallback if arrangement engine unavailable — harmonic stack
        db = db - 2
    elif presence == "ambient":
        db = db

    tone = Sine(freq).to_audio_segment(duration=tone_dur) + db
    looped = _repeat_to_duration(tone, duration_ms)
    result = base.overlay(looped)

    if presence == "music":
        # Extra harmonic layers for music-like bed fallback
        for mul, g_off in ((1.5, -10), (2.0, -14), (3.0, -18)):
            harm = Sine(freq * mul).to_audio_segment(duration=min(tone_dur, duration_ms)) + (db + g_off)
            result = result.overlay(_repeat_to_duration(harm, duration_ms))

    if presence == "sfx":
        # Only sparse clicks/thumps — no continuous bed dominance
        result = base
        for t in range(0, duration_ms, max(500, tempo_ms)):
            thump = Sine(60).to_audio_segment(duration=70).fade_out(65) + (db + 2)
            result = result.overlay(thump, position=t)
        return result

    # Cover all ten SOUND_ORIGIN_PRIMITIVES via spectral shape (mission: touch every origin noise).
    prim = (target_primitive or "").strip().lower()
    if not prim:
        prim = random.choice(
            ["tone", "hum", "hiss", "rumble", "rustle", "click", "whoosh", "thump", "drip", "tone"]
        )
    return result.overlay(_primitive_texture(prim, duration_ms, db=db, tempo_ms=tempo_ms) + (-4))


def generate_audio_only(
    duration_seconds: float,
    output_path: Path,
    *,
    mood: str = "neutral",
    tempo: str = "medium",
    presence: str = "ambient",
    target_primitive: str | None = None,
    pure_sounds: list[dict] | None = None,
    pairing_kind: str = "frame",
    seed: int | None = None,
    target_v2_cells: list[int] | None = None,
) -> Path:
    """
    Generate procedural audio to a WAV file (no video). Used by the sound-only
    workflow to discover pure sound values without rendering video.
    Prefer pure_sounds pairing when provided; else mood bed + target_primitive.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = int(duration_seconds * 1000)
    if target_v2_cells:
        # Sound v2 survey: aim frames at specific unseen sound.L1 cells (closed-loop, deterministic by seed).
        from .v2_synth import synth_v2_cells

        audio, _plans = synth_v2_cells(list(target_v2_cells), duration_ms, seed=int(seed or 0))
    elif pure_sounds:
        audio = generate_audio_from_pure_sounds(
            pure_sounds,
            duration_ms=duration_ms,
            pairing_kind=pairing_kind,
            seed=seed,
        )
    else:
        audio = _generate_procedural_audio(
            duration_ms=duration_ms,
            mood=mood,
            tempo=tempo,
            presence=presence,
            target_primitive=target_primitive,
        )
    audio.export(str(output_path), format="wav")
    return output_path
