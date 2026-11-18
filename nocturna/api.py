import json
import random
import zipfile
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import __version__, assets, audio, card, covers, human, migrate, publishing, youtube
from .config import Settings, get_settings
from .db import make_engine, make_session_factory, session_scope
from .freesound import Freesound, FreesoundError
from .generator import Generator, build_generator
from .models import (
    CHECKLIST_ITEMS,
    Asset,
    PromptTemplate,
    Release,
    ReleaseEvent,
    ReleaseStatus,
    YouTubeUpload,
)
from .schemas import (
    METADATA_FIELDS,
    AssetOut,
    ChecklistUpdate,
    Comment,
    Decision,
    FreesoundImport,
    ReleaseCreate,
    ReleaseDetail,
    ReleaseOut,
    ReleaseUpdate,
    ScheduleRequest,
    TemplateCreate,
    TemplateOut,
    TemplateUpdate,
    UploadOut,
)
from .transitions import TransitionError, approval_blockers, transition
from .workflow import build_workflow

STATIC_DIR = Path(__file__).parent / "static"
EDITABLE = {ReleaseStatus.draft, ReleaseStatus.rejected, ReleaseStatus.failed}
REVIEWABLE = EDITABLE | {ReleaseStatus.review}
AI_DISCLOSURE = (
    "This track was created with the help of generative AI, layered with real human-made "
    "recordings, and curated, edited and approved by a human. YouTube uploads always set "
    "'Altered or synthetic content' to Yes."
)


def create_app(
    settings: Settings | None = None,
    generator: Generator | None = None,
    uploader_factory: Callable[[], youtube.Uploader] | None = None,
    freesound_client: Freesound | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    generator = generator or build_generator(
        settings.ace_step_enabled, settings.ace_step_url, settings.ace_step_timeout_s
    )
    workflow = build_workflow(generator)
    media_root = settings.audio_dir.resolve()
    make_uploader = uploader_factory or (lambda: youtube.GoogleUploader(settings.youtube_token_path))

    def get_freesound() -> Freesound:
        if freesound_client is not None:
            return freesound_client
        try:
            return Freesound(settings.freesound_api_key)
        except FreesoundError as exc:
            raise HTTPException(503, str(exc)) from exc

    def run_uploads(upload_ids: list[int]) -> None:
        """Background task: render and upload, each in its own session."""
        for upload_id in upload_ids:
            for db in session_scope(factory):
                upload = db.get(YouTubeUpload, upload_id)
                if upload is not None and upload.status == "queued":
                    publishing.process(db, upload, media_root, make_uploader)

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
            out.human_credits = human.credits(release.assets)
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
            "freesound_enabled": bool(settings.freesound_api_key) or freesound_client is not None,
            "youtube": {
                "enabled": settings.youtube_enabled,
                "auto_schedule": settings.youtube_auto_schedule,
                "authorized": settings.youtube_token_path.is_file() or uploader_factory is not None,
                "long_slots": settings.youtube_long_slots,
                "short_slots": settings.youtube_short_slots,
                "timezone": settings.youtube_timezone,
            },
            "delivery_target": {
                "lufs": settings.delivery_lufs, "true_peak_dbtp": settings.delivery_true_peak_dbtp
            },
        }

    @app.get("/api/checklist")
    def checklist_items():
        return CHECKLIST_ITEMS

    @app.get("/api/human/sources")
    def human_sources():
        return human.SOURCE_TYPES

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
    def decide(release_id: int, body: Decision, background: BackgroundTasks,
               db: Session = Depends(get_db)):
        release = load(db, release_id)
        try:
            transition(db, release, body.action, note=body.note, actor=body.actor)
        except TransitionError as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc
        if body.action == "approve" and settings.youtube_enabled and settings.youtube_auto_schedule:
            try:
                booked = publishing.schedule(db, release, settings, actor=body.actor)
            except publishing.PublishError as exc:
                status = release.status.value
                release.events.append(ReleaseEvent(
                    action="youtube_schedule", from_status=status, to_status=status,
                    actor=body.actor, note=f"not scheduled: {exc}"))
            else:
                db.flush()
                background.add_task(run_uploads, [u.id for u in booked])
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
        source_type: str = Form(""),
        author: str = Form(""),
        source_url: str = Form(""),
        sound_title: str = Form(""),
        db: Session = Depends(get_db),
    ):
        release = load(db, release_id)
        if release.status not in REVIEWABLE:
            raise HTTPException(409, f"cannot add files in status {release.status.value!r}")
        if kind == "human":
            try:
                source = human.check(source_type, license, author or actor, sound_title,
                                     source_url, notes)
            except human.LicenceError as exc:
                raise HTTPException(422, str(exc)) from exc
            provenance = {**source.as_provenance(), "uploaded_by": actor or None,
                          "uploaded_at": datetime.now(UTC).isoformat()}
        else:
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

    # ------------------------------------------------------- human layer

    @app.get("/api/freesound/search")
    def freesound_search(q: str, fs: Freesound = Depends(get_freesound)):
        if not q.strip():
            raise HTTPException(422, "empty query")
        try:
            return [s.as_dict() for s in fs.search(q.strip())]
        except FreesoundError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/releases/{release_id}/human/freesound", response_model=AssetOut,
              status_code=201)
    def freesound_import(release_id: int, body: FreesoundImport, db: Session = Depends(get_db),
                         fs: Freesound = Depends(get_freesound)):
        release = load(db, release_id)
        if release.status not in REVIEWABLE:
            raise HTTPException(409, f"cannot add files in status {release.status.value!r}")
        try:
            sound = fs.sound(body.sound_id)
            source = human.check("freesound", sound.licence or sound.licence_url, sound.username,
                                 sound.name, sound.url,
                                 "Freesound HQ MP3 preview; download the original for final mixes")
        except FreesoundError as exc:
            raise HTTPException(502, str(exc)) from exc
        except human.LicenceError as exc:
            raise HTTPException(422, f"{sound.name}: {exc}") from exc
        n = len(release.assets) + 1
        dest = assets.release_dir(media_root, release) / (
            f"human-{n:03d}-freesound-{sound.id}-{assets.safe_name(sound.name)}.mp3")
        try:
            fs.download_preview(sound, dest, settings.max_upload_mb << 20)
            asset = assets.register(
                db, media_root, release, kind="human", path=dest, original_name=sound.name,
                provenance={**source.as_provenance(), "freesound_id": sound.id,
                            "license_url": sound.licence_url, "uploaded_by": body.actor or None,
                            "uploaded_at": datetime.now(UTC).isoformat()},
            )
        except (FreesoundError, assets.AssetError) as exc:
            db.rollback()
            dest.unlink(missing_ok=True)
            raise HTTPException(502 if isinstance(exc, FreesoundError) else 422, str(exc)) from exc
        status = release.status.value
        release.events.append(ReleaseEvent(
            action="add_human", from_status=status, to_status=status, actor=body.actor,
            note=f"Freesound {sound.id} {sound.name!r} by {sound.username} ({source.licence})",
        ))
        db.commit()
        return asset

    # ------------------------------------------------------------- cover/card

    @app.post("/api/releases/{release_id}/cover", response_model=ReleaseDetail)
    def make_cover(release_id: int, actor: str = "", db: Session = Depends(get_db)):
        release = load(db, release_id)
        if release.status not in REVIEWABLE:
            raise HTTPException(409, f"cannot add files in status {release.status.value!r}")
        seed = (release.seed if release.seed is not None else release.id * 7919) + sum(
            1 for a in release.assets if a.kind == "artwork")
        if not release.capture_time:
            release.capture_time = covers.capture_time_for(seed)
        layer = next((a for a in release.assets if a.kind == "human"), None)
        meta = " · ".join(x for x in [
            f"{release.bpm} BPM" if release.bpm else "", release.musical_key or "",
            f"field rec: {layer.provenance.get('title') or layer.original_name}"[:48] if layer else "",
        ] if x) or (release.lane or "Nocturna")
        n = len(release.assets) + 1
        dest = assets.release_dir(media_root, release) / f"artwork-{n:03d}-cover.png"
        text_ = covers.CoverText(release.catalog_no, release.capture_time, release.title, meta)
        settings_used = covers.render(text_, seed, dest, serif_font=settings.cover_font_serif,
                                      mono_font=settings.cover_font_mono)
        try:
            asset = assets.register(db, media_root, release, kind="artwork", path=dest,
                                    original_name=dest.name,
                                    provenance={"source": "generated", **settings_used,
                                                "license": "owned (procedural, no model)",
                                                "generated_at": datetime.now(UTC).isoformat()})
        except assets.AssetError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc
        status = release.status.value
        release.events.append(ReleaseEvent(action="add_artwork", from_status=status,
                                           to_status=status, actor=actor,
                                           note=f"Infrared cover (seed {seed}, sha256 {asset.sha256[:12]})"))
        db.commit()
        return to_out(release, ReleaseDetail)

    @app.get("/api/releases/{release_id}/card", response_class=PlainTextResponse)
    def provenance_card(release_id: int, db: Session = Depends(get_db)):
        return card.render(load(db, release_id))

    # ---------------------------------------------------------------- youtube

    @app.post("/api/releases/{release_id}/youtube", response_model=list[UploadOut],
              status_code=201)
    def schedule_youtube(release_id: int, body: ScheduleRequest, background: BackgroundTasks,
                         db: Session = Depends(get_db)):
        release = load(db, release_id)
        try:
            booked = publishing.schedule(db, release, settings, kinds=body.kinds, actor=body.actor)
        except (publishing.PublishError, youtube.YouTubeError) as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        background.add_task(run_uploads, [u.id for u in booked])
        return booked

    @app.get("/api/youtube/uploads", response_model=list[UploadOut])
    def list_uploads(db: Session = Depends(get_db)):
        return db.scalars(select(YouTubeUpload).order_by(YouTubeUpload.publish_at.desc())).all()

    @app.post("/api/youtube/uploads/{upload_id}/retry", response_model=UploadOut)
    def retry_upload(upload_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
        upload = db.get(YouTubeUpload, upload_id)
        if upload is None:
            raise HTTPException(404, "upload not found")
        if upload.status != "failed":
            raise HTTPException(409, "only failed uploads can be retried")
        if not settings.youtube_enabled:
            raise HTTPException(409, "YouTube uploads are off")
        if publishing._aware(upload.publish_at) <= datetime.now(UTC):
            raise HTTPException(409, "its slot has passed; schedule the release again")
        upload.status, upload.error = "queued", None
        db.commit()
        background.add_task(run_uploads, [upload.id])
        return upload

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
                "catalog_no": release.catalog_no, "capture_time": release.capture_time,
                "human_credits": human.credits(release.assets),
                "ai_disclosure": AI_DISCLOSURE,
            },
            "checklist": {
                key: {"label": label, "done": bool((release.checklist or {}).get(key))}
                for key, label in CHECKLIST_ITEMS.items()
            },
            "assets": [asset_dict(a) for a in release.assets],
            "youtube_uploads": [
                UploadOut.model_validate(u).model_dump(mode="json") for u in release.uploads
            ],
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
            zf.writestr("PROVENANCE-CARD.txt", card.render(release),
                        compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("UPLOAD-CHECKLIST.txt", upload_notes(release),
                        compress_type=zipfile.ZIP_DEFLATED)
        return FileResponse(out, media_type="application/zip", filename=out.name)

    def upload_notes(release: Release) -> str:
        return "\n".join([
            f"{release.title}",
            "",
            "If YouTube uploads are enabled, Nocturna uploads this release as PRIVATE with a",
            "scheduled publish time and the AI disclosure set. Manual upload steps otherwise:",
            "1. Upload the delivery WAV with the artwork as private or unlisted.",
            "2. YouTube Studio > Details > Altered or synthetic content: Yes (AI-generated music).",
            "3. Paste title, description, credits, human_credits and tags from metadata.json.",
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
