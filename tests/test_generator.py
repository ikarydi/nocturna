import httpx
import pytest

from nocturna.generator import (
    DisabledGenerator,
    GenerationDisabled,
    GeneratorError,
    HttpGenerator,
    parse_generation_response,
)


def test_parse_audio_path_and_metadata():
    r = parse_generation_response({"audio_path": "a.wav", "seed": 3, "model": "acestep-v15-turbo"})
    assert r.audio_path == "a.wav" and r.audio_url is None
    assert r.metadata == {"seed": 3, "model": "acestep-v15-turbo"}


def test_parse_audio_url():
    assert parse_generation_response({"audio_url": "http://gpu:8001/a.wav"}).audio_url


@pytest.mark.parametrize(
    "payload",
    [[], {}, {"audio_path": ""}, {"audio_path": 5}, {"audio_url": "file:///etc/passwd"}],
)
def test_parse_rejects_bad_payloads(payload):
    with pytest.raises(GeneratorError):
        parse_generation_response(payload)


def test_disabled_generator_refuses():
    with pytest.raises(GenerationDisabled):
        DisabledGenerator().generate("p", 60)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://gen")


def test_http_generator_round_trip():
    def handler(request: httpx.Request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        assert request.url.path == "/generate"
        return httpx.Response(200, json={"audio_path": "x.wav", "seed": 1})

    gen = HttpGenerator("http://gen", client=_client(handler))
    assert gen.health()["status"] == "ok"
    assert gen.generate("p", 60).audio_path == "x.wav"


@pytest.mark.parametrize(
    "response,message",
    [
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(200, content=b"not json"), "invalid JSON"),
        (httpx.Response(200, json={"status": "queued"}), "neither"),
    ],
)
def test_http_generator_errors(response, message):
    gen = HttpGenerator("http://gen", client=_client(lambda r: response))
    with pytest.raises(GeneratorError, match=message):
        gen.generate("p", 60)


def test_http_generator_health_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert HttpGenerator("http://gen", client=_client(handler)).health()["status"] == "unreachable"
