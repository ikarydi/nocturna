"""The provenance card: a short, human-readable account of how a release was made.

It ships in every delivery package and is meant to be shown (pinned comment, Bandcamp notes,
press). Machine-readable detail stays in provenance.json.
"""

from . import human
from .models import Release


def _row(label: str, value: str) -> str:
    return f"{label:<14}{value}"


def render(release: Release) -> str:
    take = release.latest_asset("take")
    tp = (take.provenance or {}) if take else {}
    delivery = release.latest_asset("delivery")
    artwork = release.latest_asset("artwork")
    approved = next((e for e in reversed(release.events) if e.action == "approve"), None)
    layers = [a for a in release.assets if a.kind == "human"]

    music = "not recorded"
    if take:
        bits = [tp.get("model") or "model not recorded"]
        if tp.get("model_revision"):
            bits.append(f"rev {tp['model_revision']}")
        if tp.get("seed") is not None:
            bits.append(f"seed {tp['seed']}")
        if tp.get("license"):
            bits.append(f"licence {tp['license']}")
        music = " · ".join(bits)

    lines = [
        f"{release.catalog_no} · {release.title.upper()}",
        " · ".join(x for x in [
            f"CAPTURED {release.capture_time}" if release.capture_time else "",
            f"{release.bpm} BPM" if release.bpm else "", (release.musical_key or "").upper(),
            release.lane,
        ] if x),
        "-" * 60,
        _row("MUSIC", music),
    ]
    if layers:
        for i, a in enumerate(layers):
            p = a.provenance or {}
            what = human.SOURCE_TYPES.get(p.get("source_type"), "human layer")
            desc = human.credit_line(p) or what
            lines.append(_row("HUMAN LAYER" if i == 0 else "", f"{desc} [{p.get('license')}]"))
    else:
        lines.append(_row("HUMAN LAYER", "none yet"))
    if artwork:
        ap = artwork.provenance or {}
        how = "Infrared Archive cover generator" if ap.get("generator") else "uploaded artwork"
        lines.append(_row("ARTWORK", how))
    if delivery:
        lines.append(_row("MASTER", f"{delivery.integrated_lufs} LUFS · {delivery.true_peak_dbtp} dBTP"))
    lines.append(_row("AI DISCLOSURE", "set on every YouTube upload (altered or synthetic content)"))
    if approved:
        lines.append(_row("APPROVED", f"{approved.actor or 'reviewer'} · {approved.created_at:%Y-%m-%d}"))
    lines.append("")
    lines.append("Made with machines, kept by a human.")
    return "\n".join(lines) + "\n"
