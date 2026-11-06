"""Turn a release brief into a constrained, instrumental-only generation prompt."""

import re
from dataclasses import dataclass, field

BASE_TAGS = ["dark instrumental", "no vocals", "cinematic", "atmospheric"]

# Phrases that ask the model to imitate a specific artist or track. These are removed
# and reported, never passed to a generator.
_IMITATION = re.compile(
    r"\b(?:in the style of|style of|sounds? like|inspired by|similar to|a la|à la|cover of)\b"
    r"[^,.;\n]*",
    re.IGNORECASE,
)
_VOCALS = re.compile(
    r"\b(?:vocals?|vocalist|singing|singer|sung|lyrics?|rap(?:ping)?|choir|spoken word|voice)\b",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")

MAX_PROMPT_CHARS = 600


@dataclass
class PromptResult:
    prompt: str
    warnings: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    text = _WS.sub(" ", text).strip(" ,.;")
    return re.sub(r"\s*,\s*(,\s*)+", ", ", text)


def build_prompt(
    *,
    lane: str = "",
    brief: str = "",
    bpm: int | None = None,
    musical_key: str | None = None,
    duration_s: int = 180,
) -> PromptResult:
    warnings: list[str] = []

    text = f"{lane}, {brief}" if lane else brief
    for match in _IMITATION.finditer(text):
        warnings.append(f"removed artist/track imitation: {match.group(0).strip()!r}")
    text = _IMITATION.sub("", text)

    # Drop every comma/semicolon-separated phrase that asks for a voice, so modifiers like
    # "female" or "haunting" don't leak into the prompt on their own.
    segments = re.split(r"[,;\n]", text)
    kept = [seg for seg in segments if not _VOCALS.search(seg)]
    if len(kept) != len(segments):
        warnings.append("removed vocal phrases: Nocturna releases are instrumental only")
        text = ", ".join(kept)

    parts = [_clean(text)] if _clean(text) else []
    parts.extend(t for t in BASE_TAGS if t not in text.lower())
    if bpm is not None:
        if not 40 <= bpm <= 200:
            raise ValueError("bpm must be between 40 and 200")
        parts.append(f"{bpm} bpm")
    if musical_key:
        parts.append(f"key of {musical_key.strip()}")
    if not 15 <= duration_s <= 900:
        raise ValueError("duration_s must be between 15 and 900 seconds")

    prompt = _clean(", ".join(parts))
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS].rsplit(",", 1)[0]
        warnings.append(f"prompt truncated to {MAX_PROMPT_CHARS} characters")
    return PromptResult(prompt=prompt, warnings=warnings)
