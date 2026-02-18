"""
Audio: music, SFX, sync with cuts. Phase 6.
"""
from .sound import mix_audio_to_video, generate_silence, generate_tone, generate_audio_only

__all__ = [
    "mix_audio_to_video",
    "generate_silence",
    "generate_tone",
    "generate_audio_only",
]
