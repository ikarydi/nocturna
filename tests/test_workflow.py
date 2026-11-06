from nocturna.generator import DisabledGenerator
from nocturna.workflow import build_workflow

from .conftest import FakeGenerator


def test_disabled_workflow_stops_at_review_without_generating():
    gen = FakeGenerator()
    state = build_workflow(gen).invoke({"brief": "low drones", "generation_enabled": False})
    assert state["outcome"] == "review"
    assert "no vocals" in state["prompt"]
    assert gen.calls == []


def test_enabled_workflow_generates_then_reviews():
    gen = FakeGenerator()
    state = build_workflow(gen).invoke({"brief": "low drones", "duration_s": 60, "generation_enabled": True})
    assert state["outcome"] == "review"
    assert state["audio_path"] == "take1.wav"
    assert gen.calls == [(state["prompt"], 60)]


def test_generator_failure_marks_failed():
    state = build_workflow(FakeGenerator(error="cuda oom")).invoke(
        {"brief": "x", "generation_enabled": True}
    )
    assert state["outcome"] == "failed" and "cuda oom" in state["error"]


def test_invalid_input_fails_before_generation():
    gen = FakeGenerator()
    state = build_workflow(gen).invoke({"brief": "x", "bpm": 999, "generation_enabled": True})
    assert state["outcome"] == "failed" and gen.calls == []


def test_disabled_generator_flagged_is_harmless():
    state = build_workflow(DisabledGenerator()).invoke({"brief": "x", "generation_enabled": True})
    assert state["outcome"] == "review"
    assert "generation skipped: disabled" in state["warnings"]
