from core.pitfalls import check


def kinds(found):
    return {p.kind for p in found}


def test_balanced_prompt_has_no_pitfalls(tmp_path):
    (tmp_path / "scorer.py").write_text("x = 1\n")
    found = check("UPDATE scorer.py: CREATE def score(x: int) -> int", ["scorer.py"], base_dir=tmp_path)
    assert found == []


def test_missing_context():
    assert "missing_context" in kinds(check("UPDATE scorer.py: USE helpers.py", ["scorer.py"]))


def test_excessive_context_by_tokens_and_duplicates(tmp_path):
    (tmp_path / "big.py").write_text("x" * 50_000)
    assert "excessive_context" in kinds(check("UPDATE big.py: ADD def f() -> int", ["big.py"], token_budget=1_000, base_dir=tmp_path))
    assert "excessive_context" in kinds(check("UPDATE app.py: ADD def f() -> int", ["app.py", "app_v2.py"]))


def test_prompt_levels():
    assert "prompt_too_high" in kinds(check("improve the data handling", ["app.py"]))
    verbose = "UPDATE app.py: " + "go line by line and carefully consider each and every statement then " * 4
    assert "prompt_too_low" in kinds(check(verbose, ["app.py"]))


def test_model_fit():
    prompt = "UPDATE app.py: ADD def f() -> int"
    assert "weak_model" in kinds(check(prompt, ["app.py"], model="haiku", task_class="heavy"))
    assert "model_overkill" in kinds(check(prompt, ["app.py"], model="claude-opus-5-5", task_class="mechanical"))
