import pytest

from specs.spec_validator import main, parse_spec, validate, validate_file

from .conftest import EXAMPLES, REPO

TEMPLATES = sorted((REPO / "specs" / "templates").glob("*.md"))


@pytest.mark.parametrize("path", TEMPLATES + [REPO / "examples" / e / "spec.md" for e in EXAMPLES], ids=lambda p: p.parent.name + "/" + p.name)
def test_shipped_specs_validate(path):
    report = validate_file(path)
    assert report.ok, report.issues


def test_parse_layers_and_context():
    spec = parse_spec((REPO / "examples" / "software" / "spec.md").read_text())
    assert spec.title == "Opportunity Scorer"
    assert len(spec.mid_level_objectives) == 4
    assert spec.editable_files == ["src/opportunity_scorer.py"]
    assert "src/opportunity_types.py" in spec.read_only_files
    assert [t.title for t in spec.low_level_tasks] == ["Load opportunities", "Score one opportunity", "Rank opportunities"]
    assert spec.low_level_tasks[0].prompt.startswith("UPDATE src/opportunity_scorer.py:")


BROKEN = """# Broken
## High-Level Objective
- Make things better with the data
## Context
### Beginning context
- app.py
### Ending context
- other.py
## Low-Level Tasks
1. Do it
```
build something nice
```
"""


def test_broken_spec_reports_every_layer():
    report = validate(parse_spec(BROKEN))
    assert not report.ok
    errors = {i.layer for i in report.issues if i.level == "error"}
    assert {"mid_level_objectives", "implementation_notes", "context", "low_level_tasks[1]"} <= errors
    messages = " ".join(i.message for i in report.issues)
    assert "use CREATE" in messages and "app.py is in Beginning context" in messages
    assert any(i.level == "warning" and i.layer == "high_level_objective" for i in report.issues)


def test_numbered_lines_inside_fences_are_not_tasks():
    text = BROKEN.replace("build something nice", "CREATE app.py:\n1. not a task\n    ADD def f() -> int")
    assert len(parse_spec(text).low_level_tasks) == 1


def test_cli_exit_codes(tmp_path, capsys):
    bad = tmp_path / "bad.md"
    bad.write_text(BROKEN)
    assert main([str(bad)]) == 1
    assert main([str(TEMPLATES[0])]) == 0
