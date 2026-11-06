from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import __version__, migrate
from .config import Settings, get_settings
from .db import make_engine, make_session_factory, session_scope
from .generator import Generator, build_generator
from .models import Release, ReleaseEvent, ReleaseStatus
from .schemas import Decision, ReleaseCreate, ReleaseDetail, ReleaseOut, ReleaseUpdate
from .transitions import TransitionError, transition
from .workflow import build_workflow

STATIC_DIR = Path(__file__).parent / "static"
EDITABLE = {ReleaseStatus.draft, ReleaseStatus.rejected, ReleaseStatus.failed}


def create_app(settings: Settings | None = None, generator: Generator | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    generator = generator or build_generator(
        settings.ace_step_enabled, settings.ace_step_url, settings.ace_step_timeout_s
    )
    workflow = build_workflow(generator)
    audio_root = settings.audio_dir.resolve()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        audio_root.mkdir(parents=True, exist_ok=True)
        if settings.auto_migrate:
            migrate.upgrade(settings.database_url)
        yield
        engine.dispose()

    app = FastAPI(title="Nocturna", version=__version__, lifespan=lifespan)

    def get_db() -> Iterator[Session]:
        yield from session_scope(factory)

    def resolve_audio(release: Release) -> Path | None:
        if not release.audio_path:
            return None
        path = Path(release.audio_path)
        path = (path if path.is_absolute() else audio_root / path).resolve()
        if not path.is_relative_to(audio_root) or not path.is_file():
            return None
        return path

    def to_out(release: Release, model=ReleaseOut):
        out = model.model_validate(release)
        out.has_audio = resolve_audio(release) is not None
        return out

    def load(db: Session, release_id: int) -> Release:
        release = db.get(Release, release_id)
        if release is None:
            raise HTTPException(404, "release not found")
        return release

    @app.get("/health")
    def health(db: Session = Depends(get_db)):
        db.execute(text("SELECT 1"))
        gen = generator.health() if settings.ace_step_enabled else {"status": "disabled"}
        return {
            "status": "ok",
            "version": __version__,
            "database": engine.dialect.name,
            "generation_enabled": settings.ace_step_enabled,
            "generator": gen,
        }

    @app.get("/api/releases", response_model=list[ReleaseOut])
    def list_releases(status: ReleaseStatus | None = None, db: Session = Depends(get_db)):
        query = select(Release).order_by(Release.updated_at.desc(), Release.id.desc())
        if status is not None:
            query = query.where(Release.status == status)
        return [to_out(r) for r in db.scalars(query)]

    @app.post("/api/releases", response_model=ReleaseDetail, status_code=201)
    def create_release(body: ReleaseCreate, db: Session = Depends(get_db)):
        release = Release(**body.model_dump(), status=ReleaseStatus.draft)
        release.events.append(ReleaseEvent(action="create", from_status=None, to_status="draft"))
        db.add(release)
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.get("/api/releases/{release_id}", response_model=ReleaseDetail)
    def get_release(release_id: int, db: Session = Depends(get_db)):
        return to_out(load(db, release_id), ReleaseDetail)

    @app.patch("/api/releases/{release_id}", response_model=ReleaseDetail)
    def update_release(release_id: int, body: ReleaseUpdate, db: Session = Depends(get_db)):
        release = load(db, release_id)
        if release.status not in EDITABLE:
            raise HTTPException(409, f"cannot edit a release in status {release.status.value!r}")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(release, key, value)
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.post("/api/releases/{release_id}/run", response_model=ReleaseDetail)
    def run_workflow(release_id: int, db: Session = Depends(get_db)):
        release = load(db, release_id)
        if release.status != ReleaseStatus.draft:
            raise HTTPException(409, "only draft releases can run the workflow")
        if settings.ace_step_enabled:
            transition(db, release, "start_generation")
            db.commit()
        state = workflow.invoke(
            {
                "lane": release.lane,
                "brief": release.brief,
                "bpm": release.bpm,
                "musical_key": release.musical_key,
                "duration_s": release.duration_s,
                "generation_enabled": settings.ace_step_enabled,
            }
        )
        release.prompt = state.get("prompt")
        notes = list(state.get("warnings", []))
        if state.get("generation_metadata"):
            notes.append(f"generation metadata: {state['generation_metadata']}")
        if state.get("audio_path") or state.get("audio_url"):
            release.audio_path = state.get("audio_path")
            release.audio_url = state.get("audio_url")
        if state.get("outcome") == "failed":
            transition(db, release, "fail", note=state.get("error") or "")
            notes.insert(0, state.get("error") or "workflow failed")
        else:
            transition(db, release, "submit_for_review", note="; ".join(notes))
        release.workflow_note = "\n".join(notes) or None
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.post("/api/releases/{release_id}/decision", response_model=ReleaseDetail)
    def decide(release_id: int, body: Decision, db: Session = Depends(get_db)):
        release = load(db, release_id)
        try:
            transition(db, release, body.action, note=body.note)
        except TransitionError as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.get("/api/releases/{release_id}/audio")
    def get_audio(release_id: int, db: Session = Depends(get_db)):
        path = resolve_audio(load(db, release_id))
        if path is None:
            raise HTTPException(404, "no audio for this release")
        return FileResponse(path)

    @app.exception_handler(TransitionError)
    async def transition_error(_: Request, exc: TransitionError):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def __getattr__(name: str):
    # `uvicorn nocturna.api:app` builds the app lazily, so importing this module in tests
    # never touches the default database.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
