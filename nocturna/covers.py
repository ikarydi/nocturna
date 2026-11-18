"""Infrared Archive cover generator.

A cover is a night place rendered as a heat map: one dominant heat source on near-black,
then grain, scanlines and a slight channel misregistration so nothing looks clean. The
capture time is the largest thing on it, so it still reads as a 200 px thumbnail.

Covers are procedural (Pillow only, no model), deterministic per release and seed, and can be
regraded by hand afterwards and uploaded as artwork.
"""

import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

VERSION = "covers-1"
SIZE = 3000

NIGHT = (7, 7, 10)
BONE = (233, 228, 218)
# Thermal ramp: value -> colour. Heat is earned: most of the frame stays night.
RAMP = [(0, NIGHT), (80, (59, 30, 110)), (150, (176, 48, 106)), (205, (242, 102, 43)),
        (255, (255, 231, 176))]

SERIF_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "C:/Windows/Fonts/timesi.ttf",
]
MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "C:/Windows/Fonts/consola.ttf",
]


@dataclass
class CoverText:
    catalog_no: str
    capture_time: str
    title: str
    meta: str


def _lut() -> tuple[list[int], list[int], list[int]]:
    r, g, b = [], [], []
    for v in range(256):
        for (x0, c0), (x1, c1) in zip(RAMP, RAMP[1:]):
            if x0 <= v <= x1:
                t = (v - x0) / (x1 - x0)
                col = [round(a + (bb - a) * t) for a, bb in zip(c0, c1)]
                break
        r.append(col[0]); g.append(col[1]); b.append(col[2])
    return r, g, b


def _font(path: str | None, candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in ([path] if path else []) + candidates:
        if p and Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def heat_field(rng: random.Random, size: int = 600) -> Image.Image:
    """A greyscale heat field: one hot source plus a few cooler ones, heavily blurred."""
    field = Image.new("L", (size, size), 0)
    blob = Image.radial_gradient("L").point(lambda v: 255 - v)  # bright centre, dark edge
    kind = rng.choice(["window", "line", "lamp"])
    sources = []
    if kind == "window":
        sources.append((rng.uniform(.35, .7), rng.uniform(.3, .55), rng.uniform(.25, .4),
                        rng.uniform(.35, .55), 255))
    elif kind == "line":
        sources.append((.5, rng.uniform(.55, .72), rng.uniform(.9, 1.3), rng.uniform(.06, .1), 255))
    else:
        sources.append((rng.uniform(.6, .8), rng.uniform(.2, .35), rng.uniform(.2, .3),
                        rng.uniform(.2, .3), 255))
    for _ in range(rng.randint(1, 3)):  # cooler residual heat
        sources.append((rng.uniform(.1, .9), rng.uniform(.5, 1.0), rng.uniform(.3, .7),
                        rng.uniform(.15, .4), rng.randint(70, 130)))
    for cx, cy, w, h, peak in sources:
        bw, bh = max(2, int(w * size)), max(2, int(h * size))
        b = blob.resize((bw, bh)).point(lambda v, p=peak: v * p // 255)
        layer = Image.new("L", (size, size), 0)
        layer.paste(b, (int(cx * size - bw / 2), int(cy * size - bh / 2)))
        field = ImageChops.lighter(field, layer)
    return field.filter(ImageFilter.GaussianBlur(size * 0.02))


def render(text: CoverText, seed: int, out: Path, *, serif_font: str | None = None,
           mono_font: str | None = None, size: int = SIZE) -> dict:
    """Render a cover PNG to `out`. Returns the settings recorded in provenance."""
    rng = random.Random(seed)
    field = heat_field(rng).resize((size, size), Image.Resampling.BICUBIC)
    lr, lg, lb = _lut()
    img = Image.merge("RGB", [field.point(lr), field.point(lg), field.point(lb)])

    # Misregistration: nudge the red channel a few pixels.
    r, g, b = img.split()
    shift = max(1, size // 500)
    img = Image.merge("RGB", [ImageChops.offset(r, shift, 0), g, b])

    # Grain and scanlines.
    noise = Image.frombytes("L", (size, size), rng.randbytes(size * size)).convert("RGB")
    img = ImageChops.add(img, noise.point(lambda v: max(0, v - 128) // 6))
    lines = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(lines)
    step = max(3, size // 330)
    for y in range(0, size, step):
        d.line([(0, y), (size, y)], fill=60)
    img = ImageChops.subtract(img, Image.merge("RGB", [lines] * 3))

    # Type.
    d = ImageDraw.Draw(img)
    pad = size * 0.06
    mono_s = _font(mono_font, MONO_CANDIDATES, int(size * 0.022))
    mono_m = _font(mono_font, MONO_CANDIDATES, int(size * 0.018))
    d.text((pad, pad), "N O C T U R N A", font=mono_s, fill=BONE)
    d.text((size - pad, pad), text.catalog_no, font=mono_s, fill=BONE, anchor="ra")
    serif_xl = _font(serif_font, SERIF_CANDIDATES, int(size * 0.27))
    serif_m = _font(serif_font, SERIF_CANDIDATES, int(size * 0.055))
    d.text((pad, size - pad - size * 0.05), text.meta.upper(), font=mono_m, fill=BONE, anchor="ls")
    d.text((pad, size - pad - size * 0.085), text.title, font=serif_m, fill=BONE, anchor="ls")
    d.text((pad - size * 0.01, size - pad - size * 0.16), text.capture_time, font=serif_xl,
           fill=BONE, anchor="ls")

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return {"generator": VERSION, "seed": seed, "size": size, "palette": "infrared",
            "text": text.__dict__}


def capture_time_for(seed: int) -> str:
    """A deterministic night-time capture time (00:00 to 05:59) for releases without one."""
    rng = random.Random(seed ^ 0x4E43)
    return f"{rng.randint(0, 5):02d}:{rng.randint(0, 59):02d}"
