"""Turn an approved release into YouTube-ready files with ffmpeg.

- render_long():  1920x1080 H.264 + AAC, the square cover on night black, full delivery audio
- render_short(): 1080x1920 vertical clip of up to 45 s from the strongest part of the track
- make_thumbnail(): 1280x720 JPEG under 2 MB (YouTube's custom thumbnail limit)

Still images keep files small and render fast on CPU. Animated loops (Wan 2.2) can replace
the still later without changing the uploader.
"""

from pathlib import Path

from PIL import Image

from .audio import _run

SHORT_MAX_S = 45.0


def _still(cover: Path, out: Path, size: tuple[int, int], offset: tuple[int, int]) -> Path:
    """Compose the frame once with Pillow, so ffmpeg never rescales a 3000 px PNG per frame."""
    with Image.open(cover) as src:
        art = src.convert("RGB").resize((1080, 1080), Image.Resampling.LANCZOS)
    frame = Image.new("RGB", size, (7, 7, 10))
    frame.paste(art, offset)
    path = out.with_suffix(".frame.png")
    frame.save(path, "PNG")
    return path


def render_long(cover: Path, audio: Path, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = _still(cover, out, (1920, 1080), (420, 0))
    vf = "format=yuv420p"
    _run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-loop", "1", "-framerate", "2",
          "-i", str(frame), "-i", str(audio), "-map", "0:v", "-map", "1:a",
          "-vf", vf, "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
          "-crf", "20", "-r", "2", "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
          "-shortest", "-movflags", "+faststart", str(out)], timeout=7200)
    return {"format": "1920x1080 h264 2fps, aac 320k", "tool": "ffmpeg"}


def short_window(duration_s: float, length: float = SHORT_MAX_S) -> tuple[float, float]:
    """Start and length of the Short: from about a third in, where most tracks have built."""
    length = min(length, duration_s)
    start = max(0.0, min(duration_s * 0.33, duration_s - length))
    return round(start, 2), round(length, 2)


def render_short(cover: Path, audio: Path, out: Path, duration_s: float) -> dict:
    start, length = short_window(duration_s)
    fade = min(1.5, length / 4)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = _still(cover, out, (1080, 1920), (0, 420))
    vf = "format=yuv420p"
    af = f"afade=t=in:d={fade},afade=t=out:st={max(0.0, length - fade)}:d={fade}"
    _run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-loop", "1", "-framerate", "30",
          "-i", str(frame), "-ss", str(start), "-t", str(length), "-i", str(audio),
          "-map", "0:v", "-map", "1:a", "-vf", vf, "-af", af, "-c:v", "libx264",
          "-preset", "veryfast", "-crf", "20", "-r", "30", "-c:a", "aac", "-b:a", "256k",
          "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)], timeout=1800)
    return {"format": "1080x1920 h264 30fps, aac 256k", "start_s": start, "length_s": length,
            "tool": "ffmpeg"}


def make_thumbnail(cover: Path, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(cover) as src:
        art = src.convert("RGB").resize((720, 720), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (1280, 720), (7, 7, 10))
    canvas.paste(art, (280, 0))
    canvas.save(out, "JPEG", quality=90, optimize=True)
    if out.stat().st_size > 2 * 1024 * 1024:
        canvas.save(out, "JPEG", quality=75, optimize=True)
    return {"format": "1280x720 jpeg", "tool": "pillow"}
