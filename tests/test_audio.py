from nocturna import audio
from nocturna.audio import Inspection, parse_ebur128_summary, qc_warnings

from .conftest import make_image, make_tone, needs_ffmpeg

SUMMARY = """
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -18.4 LUFS
    Threshold: -28.6 LUFS

  Loudness range:
    LRA:         6.2 LU
    Threshold: -38.5 LUFS
    LRA low:   -22.1 LUFS
    LRA high:  -15.9 LUFS

  Sample peak:
    Peak:       -0.4 dBFS

  True peak:
    Peak:        0.3 dBFS
"""


def test_parse_ebur128_summary():
    assert parse_ebur128_summary(SUMMARY) == {
        "integrated_lufs": -18.4, "loudness_range_lu": 6.2,
        "sample_peak_dbfs": -0.4, "true_peak_dbtp": 0.3,
    }


def test_parse_silence():
    out = parse_ebur128_summary(SUMMARY.replace("-18.4 LUFS", "-inf LUFS").replace("-0.4 dBFS", "-inf dBFS"))
    assert out["integrated_lufs"] is None and out["sample_peak_dbfs"] is None


def test_qc_warnings():
    info = Inspection(codec="mp3", duration_s=60, sample_rate=22050, channels=1,
                      integrated_lufs=-12, true_peak_dbtp=0.2, sample_peak_dbfs=0.0)
    w = " | ".join(qc_warnings(info, expected_duration_s=180))
    for needle in ("clipping", "above -1 dBTP", "mono", "low sample rate", "lossy", "differs"):
        assert needle in w
    clean = Inspection(codec="flac", duration_s=180, sample_rate=48000, channels=2,
                       integrated_lufs=-14, true_peak_dbtp=-1.5, sample_peak_dbfs=-2)
    assert qc_warnings(clean, 180) == []
    assert "silent" in qc_warnings(Inspection(integrated_lufs=None))[0]


@needs_ffmpeg
def test_inspect_and_export_round_trip(tmp_path):
    src = make_tone(tmp_path / "t.wav", seconds=5, volume=0.1)
    info = audio.inspect_audio(src)
    assert info.sample_rate == 44100 and info.channels == 2 and info.bit_depth == 16
    assert info.integrated_lufs < -20

    audio.export_master(src, tmp_path / "m.flac")
    m = audio.inspect_audio(tmp_path / "m.flac")
    assert m.codec == "flac" and m.bit_depth == 24 and m.sample_rate == 44100
    assert abs(m.integrated_lufs - info.integrated_lufs) < 0.2  # lossless: loudness unchanged

    settings = audio.export_delivery(tmp_path / "m.flac", tmp_path / "d.wav", -14.0, -1.0)
    d = audio.inspect_audio(tmp_path / "d.wav")
    assert d.sample_rate == 48000 and d.bit_depth == 24
    assert abs(d.integrated_lufs - -14.0) <= 0.5 and d.true_peak_dbtp <= -0.9
    assert settings["first_pass"]["input_i"]


@needs_ffmpeg
def test_inspect_image(tmp_path):
    small = audio.inspect_image(make_image(tmp_path / "s.png", "800x600"))
    assert small.width == 800 and any("small" in w for w in small.qc_warnings)
    assert any("aspect" in w for w in small.qc_warnings)
    assert audio.inspect_image(make_image(tmp_path / "w.png", "1920x1080")).qc_warnings == []
