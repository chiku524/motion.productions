"""
Concatenate segment clips into one video file. Used internally for long-form output;
the user always receives a single file. Requires FFmpeg on the system.
"""
import subprocess
from pathlib import Path


def concat_segments(
    segment_paths: list[Path],
    output_path: Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """
    Concatenate segment files in order into one video. All segments must have
    the same codec, resolution, and fps (use -c copy for speed).
    """
    if not segment_paths:
        raise ValueError("concat_segments: segment_paths cannot be empty")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Concat demuxer: list file with lines "file 'path'"
    list_file = output_path.with_suffix(".concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in segment_paths:
            path = Path(p).resolve()
            f.write(f"file '{path.as_posix()}'\n")

    try:
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        if list_file.exists():
            list_file.unlink(missing_ok=True)

    return output_path
