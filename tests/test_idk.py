from core.idk import (
    action_keywords,
    keyword_density,
    parse_phrase,
    score_prompt,
    starts_with_idk,
    suggestions,
)


def test_course_example_is_balanced_and_dense():
    s = score_prompt("UPDATE main.py: REPLACE word count print WITH word_count_bar_chart, MOVE threshold logic after for loop")
    assert s.level == "balanced"
    assert s.action_keywords == ["UPDATE", "REPLACE", "MOVE"]
    assert s.has_location


def test_vague_high_level_prompt_is_too_high():
    s = score_prompt("Enhance the visualization of our data top and bottom")
    assert s.level == "too_high"
    assert "data" in s.vague_words and "enhance" in s.vague_words


def test_verbose_prompt_is_too_low():
    words = "please go through the function and carefully look at every single line and then think about " * 3
    s = score_prompt("UPDATE word_count_bar_chart: " + words)
    assert s.level == "too_low"


def test_parse_location_action_detail():
    p = parse_phrase("UPDATE main.py, output_format.py: ADD format_as_yaml MIRROR format_as_json")
    assert p.location == "main.py, output_format.py"
    assert [(a.action, a.detail) for a in p.actions] == [("ADD", "format_as_yaml"), ("MIRROR", "format_as_json")]


def test_parse_location_first_form():
    p = parse_phrase("word_count_bar_chart: APPEND legend, REPLACE colors WITH palette")
    assert p.location == "word_count_bar_chart"
    assert [a.action for a in p.actions] == ["APPEND", "REPLACE"]


def test_starts_with_idk_and_aliases():
    assert starts_with_idk("create def f() -> int")
    assert not starts_with_idk("build a parser")
    assert any("use CREATE" in s for s in suggestions("build a parser for logs.py"))


def test_density_rewards_signal():
    dense = keyword_density("CREATE def format_as_str(t: TranscriptAnalysis) -> str")
    fluffy = keyword_density("could you maybe help me make something that formats things nicely")
    assert dense > 0.4 > fluffy


def test_lowercase_action_only_counts_at_start():
    assert action_keywords("update the move logic") == ["UPDATE"]
