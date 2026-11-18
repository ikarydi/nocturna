"""Mix the human layer(s) into a take with ffmpeg.

Each layer is set by loudness relative to the take (e.g. 10 LU under it), so a quiet field
recording and a hot sample-pack loop both land at the same place in the mix. Layers shorter
than the take can loop; every layer gets fades so nothing starts or stops with a click.
The result is a new 24-bit WAV take; the original take is never changed.
"""

from dataclasses import dataclass
from pathlib import Path

from . import audio

LEVELS = {"subtle": -16.0, "balanced": -10.0, "upfront": -6.0}
MAX_GAIN_DB = 24.0  # never boost a near-silent layer into pure noise


@dataclass
class Layer:
    path: Path
    lufs: float | None  # measured integrated loudness of the layer file
    duration_s: float | None


def layer_gain(take_lufs: float | None, layer_lufs: float | None, level_db: float) -> float:
    """Gain (dB) that puts the layer `level_db` LU relative to the take."""
    if take_lufs is None or layer_lufs is None:
        return level_db  # unmeasurable: fall back to a plain attenuation
    gain = (take_lufs + level_db) - layer_lufs
    return round(max(-60.0, min(MAX_GAIN_DB, gain)), 2)


def build_filter(take_lufs: float | None, layers: list[Layer], duration_s: float, *,
                 level_db: float, fade_s: float, loop: bool, sample_rate: int) -> tuple[str, list[dict]]:
    fmt = f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo"
    parts = [f"[0:a]{fmt}[take]"]
    labels = ["[take]"]
    used = []
    for i, layer in enumerate(layers, start=1):
        gain = layer_gain(take_lufs, layer.lufs, level_db)
        length = duration_s if loop or not layer.duration_s else min(layer.duration_s, duration_s)
        fade = max(0.0, min(fade_s, length / 3))
        chain = [fmt, f"atrim=0:{length:.3f}", "asetpts=PTS-STARTPTS", f"volume={gain}dB"]
        if fade:
            chain += [f"afade=t=in:d={fade:.3f}", f"afade=t=out:st={length - fade:.3f}:d={fade:.3f}"]
        parts.append(f"[{i}:a]{','.join(chain)}[h{i}]")
        labels.append(f"[h{i}]")
        used.append({"gain_db": gain, "length_s": round(length, 2), "looped": bool(
            loop and layer.duration_s and layer.duration_s < duration_s), "fade_s": round(fade, 2)})
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0,"
                 "alimiter=limit=0.944:level=disabled[out]")  # -0.5 dBFS safety
    return ";".join(parts), used


def mix(take: Path, take_lufs: float | None, duration_s: float, sample_rate: int,
        layers: list[Layer], out: Path, *, level_db: float = -10.0, fade_s: float = 3.0,
        loop: bool = True) -> dict:
    if not layers:
        raise audio.AudioError("no human layer to mix in")
    filt, used = build_filter(take_lufs, layers, duration_s, level_db=level_db, fade_s=fade_s,
                              loop=loop, sample_rate=sample_rate)
    args = ["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(take)]
    for layer in layers:
        args += (["-stream_loop", "-1"] if loop else []) + ["-i", str(layer.path)]
    out.parent.mkdir(parents=True, exist_ok=True)
    args += ["-filter_complex", filt, "-map", "[out]", "-t", f"{duration_s:.3f}",
             "-ar", str(sample_rate), "-c:a", "pcm_s24le", str(out)]
    audio._run(args, timeout=1800)
    return {"level_db": level_db, "fade_s": fade_s, "loop": loop, "layers": used,
            "sample_rate": sample_rate, "format": "wav pcm_s24le", "limiter_dbfs": -0.5}
