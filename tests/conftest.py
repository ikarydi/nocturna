import pytest
from fastapi.testclient import TestClient

from nocturna.api import create_app
from nocturna.config import Settings
from nocturna.generator import GenerationResult, GeneratorError


class FakeGenerator:
    def __init__(self, result=None, error=None):
        self.result = result or GenerationResult("take1.wav", None, {"seed": 7, "model": "fake"})
        self.error = error
        self.calls = []

    def health(self):
        return {"status": "ok", "model": "fake"}

    def generate(self, prompt, duration_s, seed=None):
        self.calls.append((prompt, duration_s))
        if self.error:
            raise GeneratorError(self.error)
        return self.result


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        audio_dir=tmp_path / "audio",
        ace_step_enabled=False,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def make_client():
    clients = []

    def _make(settings, generator=None):
        c = TestClient(create_app(settings, generator))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)
