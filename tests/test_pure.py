"""Fast tests for logic that needs no GPU, network or YouTube credentials."""
from clipper import review, transcribe
from clipper.__main__ import _secs
from clipper.download import parse_channel_line


def test_secs():
    assert _secs("75") == 75.0
    assert _secs("1:15") == 75.0
    assert _secs("1:02:03") == 3723.0


def test_parse_channel_line():
    assert parse_channel_line("https://x/@a | gta 6, GTA VI  # note") == ("https://x/@a", ["gta 6", "gta vi"])
    assert parse_channel_line("https://x/@a") == ("https://x/@a", [])
    assert parse_channel_line("# comment only") == ("", [])


def test_overlap():
    a, b = {"start": 0, "end": 10}, {"start": 5, "end": 30}
    assert review._overlap(a, b) == 0.5
    assert review._overlap(a, {"start": 20, "end": 30}) < 0


def _segs(words):
    return [{"words": [{"word": w} for w in words]}]


def test_caption_problem_flags_garbage():
    assert transcribe.caption_problem(_segs(["taco"] * 40 + ["another"] * 40)) is not None


def test_caption_problem_accepts_speech():
    text = ("rockstar confirmed the new map is bigger than anything they built before and the police now need "
            "witnesses before they respond which changes how every heist plays out in vice city this time around "
            "players can split up hide stolen cars in garages and even remove trackers before selling them later on")
    assert transcribe.caption_problem(_segs(text.split() * 2)) is None
