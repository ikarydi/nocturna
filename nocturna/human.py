"""The human layer: real recordings and licensed human-made sounds in every release.

Streaming services now treat fully AI-generated tracks differently (Tidal pays no royalties
on them, Deezer hides them from recommendations, Bandcamp bans them). Every Nocturna release
therefore carries at least one human-made layer, and this module decides which sources and
licences are acceptable and how they must be credited.
"""

import re
from dataclasses import dataclass

# source_type -> human label
SOURCE_TYPES: dict[str, str] = {
    "own_recording": "Own recording (field recording, played part)",
    "freesound": "Freesound (CC0 or CC BY only)",
    "public_domain": "Public-domain recording",
    "sample_pack": "Royalty-free sample pack",
    "session_player": "Session player (work for hire)",
}

_BLOCKED = re.compile(
    r"\b(nc|non-?commercial|noncommercial|nd|no-?deriv\w*|noderiv\w*|sampling\s*\+|"
    r"sampling\s*plus|personal use|editorial)\b",
    re.IGNORECASE,
)
_CC0 = re.compile(r"\b(cc0|cc-0|creative commons 0|public ?domain dedication)\b", re.IGNORECASE)
_CC_BY = re.compile(r"\b(cc[ -]?by|attribution)\b", re.IGNORECASE)


class LicenceError(ValueError):
    pass


@dataclass
class HumanSource:
    source_type: str
    licence: str
    author: str
    title: str
    source_url: str
    needs_credit: bool
    notes: str = ""

    def as_provenance(self) -> dict:
        return {
            "source": "human",
            "source_type": self.source_type,
            "license": self.licence,
            "author": self.author or None,
            "title": self.title or None,
            "source_url": self.source_url or None,
            "needs_credit": self.needs_credit,
            "notes": self.notes or None,
        }


def check(source_type: str, licence: str = "", author: str = "", title: str = "",
          source_url: str = "", notes: str = "") -> HumanSource:
    """Validate a human-layer source and normalise its licence. Raises LicenceError."""
    licence, author, title, source_url = (
        licence.strip(), author.strip(), title.strip(), source_url.strip()
    )
    if source_type not in SOURCE_TYPES:
        raise LicenceError(f"source_type must be one of {sorted(SOURCE_TYPES)}")
    if licence and _BLOCKED.search(licence):
        raise LicenceError(
            f"licence {licence!r} does not allow commercial use or changes; "
            "use CC0, CC BY, public domain, your own recording, or a royalty-free licence"
        )
    if source_url and not source_url.startswith(("https://", "http://")):
        raise LicenceError("source_url must be an http(s) link")

    needs_credit = False
    if source_type == "own_recording":
        licence = "owned"
    elif source_type == "session_player":
        if not author:
            raise LicenceError("name the session player (author)")
        licence = licence or "work for hire"
        needs_credit = True
    elif source_type == "freesound":
        if _CC0.search(licence):
            licence = "CC0 1.0"
        elif _CC_BY.search(licence):
            version = re.search(r"\d\.\d", licence)
            licence = f"CC BY {version.group(0) if version else '4.0'}"
            needs_credit = True
            if not (author and source_url):
                raise LicenceError("CC BY sounds need the author and the Freesound link for credit")
        else:
            raise LicenceError("Freesound sounds must be CC0 or CC BY")
    elif source_type == "public_domain":
        if not source_url:
            raise LicenceError("public-domain recordings need the source page link as evidence")
        licence = licence or "public domain"
    elif source_type == "sample_pack":
        if not author:
            raise LicenceError("name the sample pack or vendor (author)")
        licence = licence or "royalty-free sample licence"
    return HumanSource(source_type, licence, author, title, source_url, needs_credit, notes.strip())


def credit_line(prov: dict) -> str | None:
    """One credit line for a human-layer asset's provenance, or None if not needed."""
    st = prov.get("source_type")
    author, title, url, lic = (prov.get("author"), prov.get("title"), prov.get("source_url"),
                               prov.get("license"))
    what = f'"{title}"' if title else "Sound"
    if st == "own_recording":
        return f"Field recording / played part: {author}" if author else None
    if st == "session_player":
        return f"Performed by {author}"
    if st == "freesound":
        if prov.get("needs_credit"):
            return f"{what} by {author} ({url}), licensed under {lic}"
        return f"{what} by {author} via Freesound ({lic})" if author else None
    if st == "public_domain":
        return f"{what}{f' by {author}' if author else ''}, public domain ({url})"
    if st == "sample_pack":
        return f"Samples: {author}"
    return None


def credits(assets) -> list[str]:
    """Credit lines for every human layer on a release, de-duplicated, in order."""
    lines: list[str] = []
    for asset in assets:
        if asset.kind != "human":
            continue
        line = credit_line(asset.provenance or {})
        if line and line not in lines:
            lines.append(line)
    return lines
