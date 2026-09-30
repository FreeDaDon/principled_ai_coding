import subprocess

from adws.adw_architect_editor import architect_edit
from adws.adw_doctor import main as doctor_main
from adws.adw_spec_runner import build_prompts, run_spec
from adws.adw_version_release import bump_version, prepend_changelog, release
from core.llm import MockRunner
from specs.spec_validator import parse_spec

VALIDATE = "{python} -m pytest tests -q -p no:cacheprovider"


def test_spec_runner_hands_off_to_director(example_copy, capsys):
    root = example_copy("devops")
    code = run_spec(root / "spec.md", root, validate_cmd=VALIDATE, director_on_fail=3,
                    mock_solution="solution", runner=MockRunner())
    out = capsys.readouterr().out
    assert code == 0 and "handing off to the Director" in out and "PASSED" in out


def test_spec_runner_without_healing_fails(example_copy):
    root = example_copy("devops")
    assert run_spec(root / "spec.md", root, validate_cmd=VALIDATE, runner=MockRunner()) == 1


def test_spec_runner_rejects_invalid_spec(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("# Bad\n## High-Level Objective\n- x\n")
    assert run_spec(bad, tmp_path, runner=MockRunner()) == 2


def test_per_task_prompts(example_copy):
    root = example_copy("security")
    text = (root / "spec.md").read_text()
    prompts = build_prompts(parse_spec(text), text, per_task=True)
    assert len(prompts) == 3 and "Task 2/3: Parse sshd lines" in prompts[1]
    assert all("Editable: src/log_triage.py" in p for p in prompts)


def test_architect_editor_chain(example_copy):
    root = example_copy("iam")
    runner = MockRunner({"editor": lambda r, a: _copy_solution(root)})
    code = architect_edit("implement the spec", root, ["src/iam_policy.py"], ["src/iam_types.py"],
                          validate_cmd=VALIDATE, runner=runner)
    assert code == 0
    assert [c.role for c in runner.calls] == ["architect", "editor"]
    assert "Architect plan" in runner.calls[1].prompt and "UPDATE src/iam_policy.py" in runner.calls[1].prompt


def _copy_solution(root):
    (root / "src/iam_policy.py").write_text((root / "solution/src/iam_policy.py").read_text())
    return "applied"


def test_bump_version():
    assert bump_version("1.2.3", "patch") == "1.2.4"
    assert bump_version("1.2.3", "minor") == "1.3.0"
    assert bump_version("1.2.3", "major") == "2.0.0"


def test_release_bumps_and_writes_changelog(tmp_path):
    from datetime import date

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n\n[tool.other]\nversion = "9.9.9"\n')
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "Add scorer"],
                   cwd=tmp_path, check=True)
    assert release(tmp_path, "minor", use_ai=True, runner=MockRunner()) == 0
    text = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in text and 'version = "9.9.9"' in text
    log = (tmp_path / "CHANGELOG.md").read_text()
    assert log.startswith("# Changelog\n\n## v0.2.0") and "### Added\n- Add scorer" in log  # Jev path, no agent
    prepend_changelog(tmp_path / "CHANGELOG.md", "0.3.0", "- more", date(2026, 1, 1))
    assert (tmp_path / "CHANGELOG.md").read_text().index("v0.3.0") < (tmp_path / "CHANGELOG.md").read_text().index("v0.2.0")


def test_doctor_runs(capsys):
    code = doctor_main()
    out = capsys.readouterr().out
    assert code in (0, 1) and ("READY" in out) and "claude auth" in out


def _escape_spec(example_copy):
    work = example_copy("software")
    (work / "spec.md").write_text((work / "spec.md").read_text().replace("src/opportunity_scorer.py", "../outside.py"))
    return work


def test_spec_runner_rejects_context_outside_the_working_dir_before_any_agent(example_copy, capsys):
    work = _escape_spec(example_copy)
    runner = MockRunner()
    assert run_spec(work / "spec.md", work, validate_cmd="false", director_on_fail=2, runner=runner) == 2
    assert runner.calls == [] and "escapes" in capsys.readouterr().out


def test_architect_editor_rejects_context_outside_the_working_dir(tmp_path, capsys):
    runner = MockRunner()
    assert architect_edit("UPDATE x.py: ADD f", tmp_path, ["../x.py"], [], runner=runner) == 2
    assert architect_edit("UPDATE x.py: ADD f", tmp_path, ["x.py"], ["/etc/passwd"], runner=runner) == 2
    assert runner.calls == []


def test_doctor_reports_a_hanging_or_silent_tool_instead_of_crashing(monkeypatch, capsys):
    import adws.adw_doctor as doctor

    def fake_run(argv, **kwargs):
        if argv[0] == "claude":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")  # exits 0, prints nothing

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    monkeypatch.setattr(doctor.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert doctor.main() == 1
    out = capsys.readouterr().out
    assert "NOT READY: fix claude, claude auth" in out and "did not answer within 20s" in out
    assert "ok    git          installed" in out and "not found or not responding" in out


def test_architect_editor_cli_dry_run_passes_in_mock_mode(example_copy, capsys):
    from adws.adw_architect_editor import main as architect_main

    root = example_copy("devops")
    code = architect_main(["--spec", str(root / "spec.md"), "--mock-solution", "solution", "--validate-cmd", VALIDATE])
    assert code == 0 and "DONE: plan applied and validated" in capsys.readouterr().out
