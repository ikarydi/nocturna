from nocturna.mixing import Layer, build_filter, layer_gain

from .conftest import make_tone, needs_ffmpeg
from .test_api import ALL_DONE, to_review, upload


def test_layer_gain_is_relative_to_take():
    assert layer_gain(-14.0, -30.0, -10.0) == 6.0      # quiet field recording is lifted
    assert layer_gain(-14.0, -8.0, -10.0) == -16.0     # hot loop is pulled down
    assert layer_gain(-14.0, -80.0, -10.0) == 24.0     # never boost silence into noise
    assert layer_gain(None, -20.0, -10.0) == -10.0     # unmeasured take: plain attenuation


def test_filter_loops_and_fades():
    filt, used = build_filter(-14.0, [Layer(None, -20.0, 4.0)], 30.0, level_db=-10.0, fade_s=3.0,
                              loop=True, sample_rate=48000)
    assert "amix=inputs=2:duration=first:normalize=0" in filt and "alimiter" in filt
    assert used[0]["looped"] and used[0]["length_s"] == 30.0 and used[0]["gain_db"] == -4.0
    _, used = build_filter(-14.0, [Layer(None, -20.0, 4.0)], 30.0, level_db=-10.0, fade_s=3.0,
                           loop=False, sample_rate=48000)
    assert not used[0]["looped"] and used[0]["length_s"] == 4.0 and used[0]["fade_s"] <= 4.0 / 3


@needs_ffmpeg
def test_mix_makes_new_take_and_requires_reexport(client, tmp_path):
    rid = to_review(client, duration_s=15)["id"]
    assert client.post(f"/api/releases/{rid}/mix", json={}).status_code == 422  # nothing yet
    take = upload(client, rid, make_tone(tmp_path / "take.wav", seconds=6, volume=0.3),
                  model="acestep-v15-turbo", license="MIT", seed="7").json()
    r = client.post(f"/api/releases/{rid}/mix", json={})
    assert r.status_code == 422 and "human layer" in r.json()["detail"]
    upload(client, rid, make_tone(tmp_path / "rain.wav", seconds=2, volume=0.05), kind="human",
           source_type="own_recording", sound_title="Rain")
    assert client.post(f"/api/releases/{rid}/export").status_code == 200
    client.put(f"/api/releases/{rid}/checklist", json={"items": ALL_DONE})

    r = client.post(f"/api/releases/{rid}/mix", json={"level_db": -10, "actor": "J"})
    assert r.status_code == 200, r.text
    detail = r.json()
    mixed = [a for a in detail["assets"] if a["kind"] == "take"][-1]
    p = mixed["provenance"]
    assert p["source"] == "mix" and p["from_asset"] == take["id"] and mixed["parent_id"] == take["id"]
    assert p["model"] == "acestep-v15-turbo" and p["license"] == "MIT" and p["seed"] == 7
    assert p["human_layers"][0]["title"] == "Rain" and p["settings"]["layers"][0]["looped"]
    assert round(mixed["duration_s"]) == 6 and mixed["bit_depth"] == 24
    assert mixed["true_peak_dbtp"] <= 0.0
    assert detail["events"][-1]["action"] == "mix"

    # The old delivery no longer matches the newest take.
    r = client.post(f"/api/releases/{rid}/decision", json={"action": "approve"})
    assert r.status_code == 409 and "export again" in r.json()["detail"]

    # Mixing again starts from the original take, not from the previous mix.
    again = client.post(f"/api/releases/{rid}/mix", json={"level_db": -16}).json()
    assert [a for a in again["assets"] if a["kind"] == "take"][-1]["provenance"]["from_asset"] == take["id"]

    assert client.post(f"/api/releases/{rid}/export").status_code == 200
    r = client.post(f"/api/releases/{rid}/decision", json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/releases/{rid}/mix", json={}).status_code == 409  # frozen
