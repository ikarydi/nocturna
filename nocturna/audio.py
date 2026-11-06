"""Audio inspection and export with ffmpeg/ffprobe.

- inspect(): duration, sample rate, channels, bit depth, EBU R128 loudness, true/sample peak
- export_master(): lossless 24-bit FLAC at the source sample rate
- export_delivery(): two-pass loudnorm to a streaming target, 48 kHz 24-bit WAV
"""

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

LOSSY_CODECS = {"mp3", "aac", "vorbis", "opus", "wmav2", "ac3"}


class AudioError(RuntimeError):
    pass


@dataclass
class Inspection:
    codec: str | None = None
    duration_s: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    integrated_lufs: float | None = None
    loudness_range_lu: float | None = None
    true_peak_dbtp: float | None = None
    sample_peak_dbfs: float | None = None
    width: int | None = None
    height: int | None = None
    qc_warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@lru_cache
def ffmpeg_version() -> str | None:
    if not ffmpeg_available():
        return None
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
    return out.splitlines()[0] if out else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args: list[str], timeout: float = 900) -> subprocess.CompletedProcess:
    if not ffmpeg_available():
        raise AudioError("ffmpeg/ffprobe not installed (run scripts/setup-wsl.sh)")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"{args[0]} timed out") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise AudioError(f"{args[0]} failed: {' | '.join(tail)}")
    return proc


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value in {"-inf", "inf", "nan", ""}:
        return None
    return float(value)


def probe(path: Path) -> dict:
    proc = _run(["ffprobe", "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", str(path)])
    return json.loads(proc.stdout or "{}")


_SUMMARY = {
    "integrated_lufs": re.compile(r"I:\s+(-?[\d.]+|-inf) LUFS"),
    "loudness_range_lu": re.compile(r"LRA:\s+(-?[\d.]+|-inf) LU\b"),
}
_PEAKS = re.compile(r"(True|Sample) peak:\s*\n\s*Peak:\s+(-?[\d.]+|-inf) dBFS")


def parse_ebur128_summary(stderr: str) -> dict:
    summary = stderr.rsplit("Summary:", 1)[-1]
    out: dict = {}
    for key, rx in _SUMMARY.items():
        m = rx.search(summary)
        out[key] = _float(m.group(1)) if m else None
    for kind, value in _PEAKS.findall(summary):
        key = "true_peak_dbtp" if kind == "True" else "sample_peak_dbfs"
        out[key] = _float(value)
    return out


def loudness(path: Path) -> dict:
    proc = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                 "-filter_complex", "ebur128=peak=true+sample", "-f", "null", "-"])
    return parse_ebur128_summary(proc.stderr)


def qc_warnings(info: Inspection, expected_duration_s: int | None = None) -> list[str]:
    w: list[str] = []
    if info.sample_peak_dbfs is not None and info.sample_peak_dbfs >= -0.1:
        w.append(f"possible clipping: sample peak {info.sample_peak_dbfs} dBFS")
    if info.true_peak_dbtp is not None and info.true_peak_dbtp > -1.0:
        w.append(f"true peak {info.true_peak_dbtp} dBTP is above -1 dBTP")
    if info.integrated_lufs is None or info.integrated_lufs < -45:
        w.append("audio is silent or nearly silent")
    if info.channels == 1:
        w.append("mono audio")
    if info.sample_rate and info.sample_rate < 44100:
        w.append(f"low sample rate {info.sample_rate} Hz")
    if info.codec in LOSSY_CODECS:
        w.append(f"lossy source ({info.codec}); master will not be truly lossless")
    if expected_duration_s and info.duration_s:
        if abs(info.duration_s - expected_duration_s) > max(10, 0.15 * expected_duration_s):
            w.append(f"duration {info.duration_s:.0f}s differs from planned {expected_duration_s}s")
    return w


def inspect_audio(path: Path, expected_duration_s: int | None = None) -> Inspection:
    data = probe(path)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if stream is None:
        raise AudioError("file has no audio stream")
    bits = stream.get("bits_per_raw_sample") or stream.get("bits_per_sample")
    info = Inspection(
        codec=stream.get("codec_name"),
        duration_s=_float(stream.get("duration") or data.get("format", {}).get("duration")),
        sample_rate=int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        channels=stream.get("channels"),
        bit_depth=int(bits) if bits and int(bits) > 0 else None,
    )
    for key, value in loudness(path).items():
        setattr(info, key, value)
    info.qc_warnings = qc_warnings(info, expected_duration_s)
    return info


def inspect_image(path: Path) -> Inspection:
    data = probe(path)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if stream is None:
        raise AudioError("file is not an image")
    info = Inspection(codec=stream.get("codec_name"), width=stream.get("width"),
                      height=stream.get("height"))
    w, h = info.width or 0, info.height or 0
    if min(w, h) < 1080:
        info.qc_warnings.append(f"artwork {w}x{h} is small; aim for 3000x3000 (square) or 1920x1080+")
    if w and h and w != h and abs(w / h - 16 / 9) > 0.02:
        info.qc_warnings.append(f"artwork aspect {w}x{h} is neither square nor 16:9")
    return info


def export_master(src: Path, dst: Path) -> None:
    """Lossless FLAC, 24-bit, source sample rate and channels."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(src), "-map", "0:a:0",
          "-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24",
          "-compression_level", "8", str(dst)])


def measure_loudnorm(src: Path, target_lufs: float, true_peak: float, lra: float) -> dict:
    proc = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af",
                 f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=json",
                 "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        raise AudioError("could not read loudnorm measurement")
    return json.loads(m.group(0))


def export_delivery(src: Path, dst: Path, target_lufs: float = -14.0,
                    true_peak: float = -1.0, lra: float = 11.0) -> dict:
    """Two-pass EBU R128 normalization to a 48 kHz / 24-bit WAV. Returns the settings used."""
    measured = measure_loudnorm(src, target_lufs, true_peak, lra)
    if _float(measured.get("input_i")) is None:
        raise AudioError("source is silent; cannot normalize")
    filt = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}"
        f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true"
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(src), "-map", "0:a:0",
          "-af", filt, "-ar", "48000", "-c:a", "pcm_s24le", str(dst)])
    return {
        "target_lufs": target_lufs, "target_true_peak_dbtp": true_peak, "target_lra": lra,
        "first_pass": measured, "filter": filt, "sample_rate": 48000, "format": "wav pcm_s24le",
    }
