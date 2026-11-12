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


def test_summarize_insights():
    from clipper import analytics
    rows = [{"title": f"t{i}", "channel": "A" if i % 2 else "B", "dur": 30 + i * 5, "kind": "short",
             "views": i * 100, "retention_pct": 50 + i} for i in range(10)]
    assert analytics.summarize(rows[:3]) is None  # too few samples
    text = analytics.summarize(rows)
    assert "Best source channels: A" in text
    assert "t9 (900)" in text.split("Titles that worked:")[1]
    assert "% watched" in text


def test_explainer_validate():
    from clipper import explainer
    sec = {"heading": "A heading", "text": "word " * 90, "broll": [["nope", 0, 10]]}
    bad = explainer.validate({"title": "A fine title", "sections": [sec] * 6})
    assert any("not prepared" in b for b in bad)
    assert not any("sections" in b or "words of narration" in b for b in bad)
    ok = explainer.validate({"title": "A fine title", "sections": [sec | {"text": "GTA 6 on PS5 " * 30}] * 6})
    assert not any("spell numbers" in b for b in ok)
    assert any("spell numbers" in b for b in explainer.validate(
        {"title": "A fine title", "sections": [sec | {"text": "it runs at 30 fps " * 20}] * 6}))
    assert any("sections; use" in b for b in explainer.validate({"title": "x", "sections": []}))
