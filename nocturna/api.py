import json
import random
import zipfile
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import __version__, assets, audio, migrate
from .config import Settings, get_settings
from .db import make_engine, make_session_factory, session_scope
from .generator import Generator, build_generator
from .models import CHECKLIST_ITEMS, Asset, PromptTemplate, Release, ReleaseEvent, ReleaseStatus
from .schemas import (
    METADATA_FIELDS,
    AssetOut,
    ChecklistUpdate,
    Comment,
    Decision,
    ReleaseCreate,
    ReleaseDetail,
    ReleaseOut,
    ReleaseUpdate,
    TemplateCreate,
    TemplateOut,
    TemplateUpdate,
)
from .transitions import TransitionError, approval_blockers, transition
from .workflow import build_workflow

STATIC_DIR = Path(__file__).parent / "static"
EDITABLE = {ReleaseStatus.draft, ReleaseStatus.rejected, ReleaseStatus.failed}
REVIEWABLE = EDITABLE | {ReleaseStatus.review}
AI_DISCLOSURE = (
    "This track was created with the help of generative AI and curated, edited and approved "
    "by a human. Set YouTube Studio > Altered or synthetic content to 'Yes' on upload."
)


def create_app(settings: Settings | None = None, generator: Generator | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    generator = generator or build_generator(
        settings.ace_step_enabled, settings.ace_step_url, settings.ace_step_timeout_s
    )
    workflow = build_workflow(generator)
    media_root = settings.audio_dir.resolve()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        media_root.mkdir(parents=True, exist_ok=True)
        if settings.auto_migrate:
            migrate.upgrade(settings.database_url)
        yield
        engine.dispose()

    app = FastAPI(title="Nocturna", version=__version__, lifespan=lifespan)

    def get_db() -> Iterator[Session]:
        yield from session_scope(factory)

    def playable(release: Release) -> Path | None:
        for kind in ("delivery", "master", "take"):
            asset = release.latest_asset(kind)
            if asset and (path := assets.resolve(media_root, asset.path)):
                return path
        return assets.resolve(media_root, release.audio_path) if release.audio_path else None

    def to_out(release: Release, model=ReleaseOut):
        out = model.model_validate(release)
        out.has_audio = playable(release) is not None
        if isinstance(out, ReleaseDetail):
            out.approval_blockers = (
                approval_blockers(release) if release.status == ReleaseStatus.review else []
            )
        return out

    def load(db: Session, release_id: int) -> Release:
        release = db.get(Release, release_id)
        if release is None:
            raise HTTPException(404, "release not found")
        return release

    def load_template(db: Session, template_id: int | None) -> PromptTemplate | None:
        if template_id is None:
            return None
        template = db.get(PromptTemplate, template_id)
        if template is None:
            raise HTTPException(422, "template not found")
        return template

    # ---------------------------------------------------------------- health

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
            "ffmpeg": audio.ffmpeg_version(),
            "delivery_target": {
                "lufs": settings.delivery_lufs, "true_peak_dbtp": settings.delivery_true_peak_dbtp
            },
        }

    @app.get("/api/checklist")
    def checklist_items():
        return CHECKLIST_ITEMS

    # ------------------------------------------------------------- templates

    @app.get("/api/templates", response_model=list[TemplateOut])
    def list_templates(db: Session = Depends(get_db)):
        return db.scalars(select(PromptTemplate).order_by(PromptTemplate.name)).all()

    @app.post("/api/templates", response_model=TemplateOut, status_code=201)
    def create_template(body: TemplateCreate, db: Session = Depends(get_db)):
        template = PromptTemplate(**body.model_dump())
        db.add(template)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "a template with that name already exists") from exc
        return template

    @app.patch("/api/templates/{template_id}", response_model=TemplateOut)
    def update_template(template_id: int, body: TemplateUpdate, db: Session = Depends(get_db)):
        template = load_template(db, template_id)
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(template, key, value)
        if template.bpm_min and template.bpm_max and template.bpm_min > template.bpm_max:
            raise HTTPException(422, "bpm_min must not exceed bpm_max")
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "a template with that name already exists") from exc
        return template

    # -------------------------------------------------------------- releases

    @app.get("/api/releases", response_model=list[ReleaseOut])
    def list_releases(status: ReleaseStatus | None = None, db: Session = Depends(get_db)):
        query = select(Release).order_by(Release.updated_at.desc(), Release.id.desc())
        if status is not None:
            query = query.where(Release.status == status)
        return [to_out(r) for r in db.scalars(query)]

    @app.post("/api/releases", response_model=ReleaseDetail, status_code=201)
    def create_release(body: ReleaseCreate, db: Session = Depends(get_db)):
        template = load_template(db, body.template_id)
        data = body.model_dump()
        if template is not None:
            data["lane"] = data["lane"] or template.name
            data["musical_key"] = data["musical_key"] or template.default_key
        release = Release(**data, status=ReleaseStatus.draft, checklist={})
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
        changes = body.model_dump(exclude_unset=True)
        allowed = REVIEWABLE if set(changes) <= METADATA_FIELDS else EDITABLE
        if release.status not in allowed:
            raise HTTPException(409, f"cannot edit these fields in status {release.status.value!r}")
        if "template_id" in changes:
            load_template(db, changes["template_id"])
        for key, value in changes.items():
            setattr(release, key, value)
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.post("/api/releases/{release_id}/run", response_model=ReleaseDetail)
    def run_workflow(release_id: int, db: Session = Depends(get_db)):
        release = load(db, release_id)
        if release.status != ReleaseStatus.draft:
            raise HTTPException(409, "only draft releases can run the workflow")
        template = release.template
        if settings.ace_step_enabled:
            if release.seed is None:
                release.seed = random.randrange(2**31)
            transition(db, release, "start_generation")
            db.commit()
        state = workflow.invoke(
            {
                # The lane name only adds noise when it is just the template's name.
                "lane": "" if template and release.lane == template.name else release.lane,
                "brief": release.brief,
                "bpm": release.bpm,
                "musical_key": release.musical_key,
                "duration_s": release.duration_s,
                "template_tags": template.tags if template else "",
                "bpm_range": (template.bpm_min, template.bpm_max) if template else (None, None),
                "seed": release.seed,
                "generation_enabled": settings.ace_step_enabled,
            }
        )
        release.prompt = state.get("prompt")
        notes = list(state.get("warnings", []))
        error = state.get("error")
        meta = state.get("generation_metadata") or {}
        if state.get("audio_path") or state.get("audio_url"):
            release.audio_path = state.get("audio_path")
            release.audio_url = state.get("audio_url")
        if state.get("audio_path") and not error:
            provenance = {
                "source": "generated",
                "prompt": release.prompt,
                "seed": meta.get("seed", release.seed),
                "duration_s": release.duration_s,
                "template": {"name": template.name, "tags": template.tags} if template else None,
                "model": meta.get("model"),
                "model_revision": meta.get("model_revision"),
                "license": meta.get("license"),
                "generator_metadata": meta,
                "generated_at": datetime.now(UTC).isoformat(),
            }
            try:
                take = assets.adopt_generated(db, media_root, release, state["audio_path"], provenance)
            except assets.AssetError as exc:
                error = f"generated audio could not be read: {exc}"
            else:
                if take is None:
                    notes.append("generated audio_path is outside AUDIO_DIR or missing; not stored")
                elif not meta.get("model") or not meta.get("license"):
                    notes.append("generator did not report model and license; provenance incomplete")
        if error:
            transition(db, release, "fail", note=error)
            notes.insert(0, error)
        else:
            transition(db, release, "submit_for_review", note="; ".join(notes))
        release.workflow_note = "\n".join(notes) or None
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.post("/api/releases/{release_id}/decision", response_model=ReleaseDetail)
    def decide(release_id: int, body: Decision, db: Session = Depends(get_db)):
        release = load(db, release_id)
        try:
            transition(db, release, body.action, note=body.note, actor=body.actor)
        except TransitionError as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.post("/api/releases/{release_id}/comments", response_model=ReleaseDetail, status_code=201)
    def comment(release_id: int, body: Comment, db: Session = Depends(get_db)):
        release = load(db, release_id)
        status = release.status.value
        release.events.append(ReleaseEvent(action="comment", from_status=status, to_status=status,
                                           note=body.note, actor=body.actor))
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.put("/api/releases/{release_id}/checklist", response_model=ReleaseDetail)
    def update_checklist(release_id: int, body: ChecklistUpdate, db: Session = Depends(get_db)):
        release = load(db, release_id)
        if release.status not in REVIEWABLE:
            raise HTTPException(409, f"cannot change the checklist in status {release.status.value!r}")
        unknown = set(body.items) - set(CHECKLIST_ITEMS)
        if unknown:
            raise HTTPException(422, f"unknown checklist items: {sorted(unknown)}")
        checklist = dict(release.checklist or {})
        changed = {k: v for k, v in body.items.items() if checklist.get(k, False) != v}
        checklist.update(body.items)
        release.checklist = checklist
        if changed:
            status = release.status.value
            note = ", ".join(f"{k} {'✓' if v else '✗'}" for k, v in changed.items())
            release.events.append(ReleaseEvent(action="checklist", from_status=status,
                                               to_status=status, note=note, actor=body.actor))
        db.commit()
        return to_out(release, ReleaseDetail)

    # ---------------------------------------------------------------- assets

    @app.post("/api/releases/{release_id}/assets", response_model=AssetOut, status_code=201)
    def upload_asset(
        release_id: int,
        file: UploadFile = File(...),
        kind: str = Form("take"),
        model: str = Form(""),
        model_revision: str = Form(""),
        license: str = Form(""),
        seed: str = Form(""),
        notes: str = Form(""),
        actor: str = Form(""),
        db: Session = Depends(get_db),
    ):
        release = load(db, release_id)
        if release.status not in REVIEWABLE:
            raise HTTPException(409, f"cannot add files in status {release.status.value!r}")
        provenance = {
            "source": "uploaded",
            "uploaded_by": actor or None,
            "uploaded_at": datetime.now(UTC).isoformat(),
            "model": model or None,
            "model_revision": model_revision or None,
            "license": license or None,
            "seed": int(seed) if seed.strip().isdigit() else None,
            "prompt": release.prompt,
            "notes": notes or None,
        }
        try:
            asset = assets.save_upload(
                db, media_root, release, kind=kind, filename=file.filename or "upload",
                stream=file.file, max_bytes=settings.max_upload_mb << 20, provenance=provenance,
            )
        except assets.AssetError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc
        status = release.status.value
        release.events.append(ReleaseEvent(
            action=f"add_{kind}", from_status=status, to_status=status, actor=actor,
            note=f"{asset.original_name} (sha256 {asset.sha256[:12]})",
        ))
        db.commit()
        return asset

    @app.post("/api/releases/{release_id}/export", response_model=ReleaseDetail)
    def export(release_id: int, actor: str = "", db: Session = Depends(get_db)):
        release = load(db, release_id)
        if release.status not in REVIEWABLE:
            raise HTTPException(409, f"cannot export in status {release.status.value!r}")
        try:
            master, delivery = assets.export_masters(
                db, media_root, release,
                target_lufs=settings.delivery_lufs, true_peak=settings.delivery_true_peak_dbtp,
            )
        except assets.AssetError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc
        status = release.status.value
        release.events.append(ReleaseEvent(
            action="export", from_status=status, to_status=status, actor=actor,
            note=f"master {master.sha256[:12]}, delivery {delivery.integrated_lufs} LUFS / "
                 f"{delivery.true_peak_dbtp} dBTP",
        ))
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.get("/api/assets/{asset_id}/file")
    def asset_file(asset_id: int, db: Session = Depends(get_db)):
        asset = db.get(Asset, asset_id)
        path = assets.resolve(media_root, asset.path) if asset else None
        if path is None:
            raise HTTPException(404, "file not found")
        return FileResponse(path)

    @app.get("/api/releases/{release_id}/audio")
    def get_audio(release_id: int, db: Session = Depends(get_db)):
        path = playable(load(db, release_id))
        if path is None:
            raise HTTPException(404, "no audio for this release")
        return FileResponse(path)

    # ----------------------------------------------------- provenance/package

    def provenance_record(release: Release) -> dict:
        def asset_dict(a: Asset) -> dict:
            return AssetOut.model_validate(a).model_dump(mode="json")

        return {
            "nocturna_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(),
            "release": {
                "id": release.id, "title": release.title, "status": release.status.value,
                "lane": release.lane, "brief": release.brief, "bpm": release.bpm,
                "key": release.musical_key, "duration_s": release.duration_s,
                "seed": release.seed, "prompt": release.prompt,
                "template": (
                    {"name": release.template.name, "tags": release.template.tags}
                    if release.template else None
                ),
            },
            "metadata": {
                "title": release.title, "description": release.description,
                "credits": release.credits, "tags": release.tags,
                "ai_disclosure": AI_DISCLOSURE,
            },
            "checklist": {
                key: {"label": label, "done": bool((release.checklist or {}).get(key))}
                for key, label in CHECKLIST_ITEMS.items()
            },
            "assets": [asset_dict(a) for a in release.assets],
            "history": [
                {"action": e.action, "from": e.from_status, "to": e.to_status, "note": e.note,
                 "actor": e.actor, "at": e.created_at.isoformat()}
                for e in release.events
            ],
        }

    @app.get("/api/releases/{release_id}/provenance")
    def provenance(release_id: int, db: Session = Depends(get_db)):
        return provenance_record(load(db, release_id))

    @app.get("/api/releases/{release_id}/package")
    def package(release_id: int, db: Session = Depends(get_db)):
        release = load(db, release_id)
        if release.status != ReleaseStatus.approved:
            raise HTTPException(409, "only approved releases have a delivery package")
        files: list[tuple[Path, str]] = []
        base = assets.safe_name(release.title).lower()
        for kind in ("master", "delivery", "artwork"):
            asset = release.latest_asset(kind)
            if asset is None:
                continue
            path = assets.resolve(media_root, asset.path)
            if path is None:
                raise HTTPException(409, f"{kind} file is missing on disk")
            files.append((path, f"{base}-{kind}{path.suffix}"))
        record = provenance_record(release)
        out_dir = media_root / "packages"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{release.id:04d}-{base}.zip"
        with zipfile.ZipFile(out, "w") as zf:
            for path, name in files:
                zf.write(path, name, compress_type=zipfile.ZIP_STORED)
            zf.writestr("provenance.json", json.dumps(record, indent=2),
                        compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("metadata.json", json.dumps(record["metadata"], indent=2),
                        compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("UPLOAD-CHECKLIST.txt", upload_notes(release),
                        compress_type=zipfile.ZIP_DEFLATED)
        return FileResponse(out, media_type="application/zip", filename=out.name)

    def upload_notes(release: Release) -> str:
        return "\n".join([
            f"{release.title}",
            "",
            "Manual upload steps (Nocturna never publishes automatically):",
            "1. Upload the delivery WAV with the artwork as private or unlisted.",
            "2. YouTube Studio > Details > Altered or synthetic content: Yes (AI-generated music).",
            "3. Paste title, description, credits and tags from metadata.json.",
            "4. Wait for copyright/Content ID checks before changing visibility.",
            "5. Keep the master FLAC and provenance.json in your archive.",
        ]) + "\n"

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
