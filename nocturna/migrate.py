"""Run Alembic migrations programmatically so there is a single source of schema truth."""

from pathlib import Path

from alembic import command
from alembic.config import Config

def _root() -> Path:
    # Source checkout (editable install) first, then the current working directory.
    for candidate in (Path(__file__).resolve().parents[1], Path.cwd()):
        if (candidate / "alembic.ini").is_file():
            return candidate
    raise FileNotFoundError("alembic.ini not found; run from the project directory")


def upgrade(database_url: str) -> None:
    root = _root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "head")
