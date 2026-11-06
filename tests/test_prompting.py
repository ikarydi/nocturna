import pytest

from nocturna.prompting import MAX_PROMPT_CHARS, build_prompt


def test_prompt_is_instrumental_and_includes_parameters():
    r = build_prompt(lane="dark ambient", brief="slow organ drones", bpm=70, musical_key="D minor")
    assert "dark ambient" in r.prompt and "slow organ drones" in r.prompt
    assert "no vocals" in r.prompt and "70 bpm" in r.prompt and "key of D minor" in r.prompt
    assert r.warnings == []


def test_artist_imitation_is_removed_and_reported():
    r = build_prompt(brief="cold strings, in the style of Some Famous Artist, distant bells")
    assert "Famous" not in r.prompt
    assert "distant bells" in r.prompt
    assert any("imitation" in w for w in r.warnings)


def test_vocal_terms_are_stripped():
    r = build_prompt(brief="low piano, haunting choir; female vocals, tape hiss")
    lowered = r.prompt.lower()
    assert "choir" not in lowered and "female" not in lowered and "haunting" not in lowered
    assert "low piano" in r.prompt and "tape hiss" in r.prompt
    assert any("instrumental" in w for w in r.warnings)


def test_long_prompt_is_truncated():
    r = build_prompt(brief=", ".join(["shimmering texture"] * 80))
    assert len(r.prompt) <= MAX_PROMPT_CHARS
    assert any("truncated" in w for w in r.warnings)


@pytest.mark.parametrize("kwargs", [{"bpm": 10}, {"duration_s": 5}])
def test_out_of_range_values_raise(kwargs):
    with pytest.raises(ValueError):
        build_prompt(brief="x", **kwargs)
