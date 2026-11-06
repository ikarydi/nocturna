"""The release state machine. Every status change goes through `transition`."""

from sqlalchemy.orm import Session

from .models import Release, ReleaseEvent, ReleaseStatus as S


class TransitionError(ValueError):
    pass


# action -> (allowed source statuses, target status)
ACTIONS: dict[str, tuple[frozenset[S], S]] = {
    "start_generation": (frozenset({S.draft}), S.generating),
    "submit_for_review": (frozenset({S.draft, S.generating}), S.review),
    "fail": (frozenset({S.draft, S.generating}), S.failed),
    "approve": (frozenset({S.review}), S.approved),
    "reject": (frozenset({S.review}), S.rejected),
    "reopen": (frozenset({S.rejected, S.failed, S.approved}), S.draft),
}

HUMAN_DECISIONS = {"approve", "reject", "reopen"}


def can(release: Release, action: str) -> bool:
    sources, _ = ACTIONS[action]
    return release.status in sources


def transition(db: Session, release: Release, action: str, note: str = "") -> Release:
    if action not in ACTIONS:
        raise TransitionError(f"unknown action {action!r}")
    sources, target = ACTIONS[action]
    if release.status not in sources:
        raise TransitionError(
            f"cannot {action} a release in status {release.status.value!r}"
        )
    if action == "reject" and not note.strip():
        raise TransitionError("a rejection needs a note explaining why")
    previous = release.status
    release.status = target
    release.events.append(
        ReleaseEvent(action=action, from_status=previous.value, to_status=target.value, note=note)
    )
    db.flush()
    return release
