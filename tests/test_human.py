import pytest

from nocturna import human
from nocturna.human import LicenceError


@pytest.mark.parametrize("licence", [
    "CC BY-NC 4.0", "Attribution NonCommercial", "CC BY-ND 3.0", "Sampling+", "personal use only",
])
def test_blocked_licences(licence):
    with pytest.raises(LicenceError):
        human.check("freesound", licence, "someone", "x", "https://freesound.org/s/1/")


def test_freesound_cc0_and_cc_by():
    cc0 = human.check("freesound", "Creative Commons 0", "anon", "rain", "")
    assert cc0.licence == "CC0 1.0" and cc0.needs_credit is False
    by = human.check("freesound", "Attribution 4.0", "kayrecs", "cimbalom",
                     "https://freesound.org/s/9/")
    assert by.licence == "CC BY 4.0" and by.needs_credit
    with pytest.raises(LicenceError, match="author"):
        human.check("freesound", "CC BY 4.0", "", "x", "")
    with pytest.raises(LicenceError, match="CC0 or CC BY"):
        human.check("freesound", "", "a", "x", "")


def test_other_sources():
    assert human.check("own_recording", "").licence == "owned"
    with pytest.raises(LicenceError):
        human.check("public_domain", "")  # needs evidence link
    assert human.check("public_domain", "", source_url="https://archive.org/details/78_x").licence == "public domain"
    with pytest.raises(LicenceError):
        human.check("sample_pack", "royalty-free")  # needs vendor
    with pytest.raises(LicenceError):
        human.check("session_player")
    with pytest.raises(LicenceError):
        human.check("youtube_rip")
    with pytest.raises(LicenceError, match="http"):
        human.check("public_domain", source_url="file:///etc/passwd")


def test_credit_lines():
    by = human.check("freesound", "CC BY 3.0", "kayrecs", "cimbalom", "https://freesound.org/s/9/")
    assert human.credit_line(by.as_provenance()) == (
        '"cimbalom" by kayrecs (https://freesound.org/s/9/), licensed under CC BY 3.0')
    assert human.credit_line(human.check("own_recording", author="J").as_provenance()) == (
        "Field recording / played part: J")
    assert human.credit_line(human.check("own_recording").as_provenance()) is None
