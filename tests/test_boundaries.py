from core.boundaries import EditableCheckpoint, guarded_run, out_of_bounds, restore, snapshot
from core.llm import MockRunner
from core.types import AgentRequest


def test_out_of_bounds_edits_are_detected_and_reverted(tmp_path):
    (tmp_path / "ok.py").write_text("a")
    (tmp_path / "ro.py").write_text("keep")
    before = snapshot(tmp_path)
    (tmp_path / "ok.py").write_text("changed")
    (tmp_path / "ro.py").write_text("tampered")
    (tmp_path / "new.py").write_text("created")
    bad = out_of_bounds(before, tmp_path, ["./ok.py"])
    assert bad == ["new.py", "ro.py"]
    restore(before, tmp_path, bad)
    assert (tmp_path / "ro.py").read_text() == "keep"
    assert not (tmp_path / "new.py").exists()
    assert (tmp_path / "ok.py").read_text() == "changed"


def test_guarded_run_reverts_rogue_agent(tmp_path):
    (tmp_path / "tests.py").write_text("assert real")

    def rogue(request, attempt):
        (tmp_path / "tests.py").write_text("assert True  # weakened")
        (tmp_path / "app.py").write_text("ok")
        return "done"

    request = AgentRequest(role="coder", prompt="p", working_dir=str(tmp_path), editable=["app.py"])
    _, reverted = guarded_run(MockRunner({"coder": rogue}), request)
    assert reverted == ["tests.py"]
    assert (tmp_path / "tests.py").read_text() == "assert real"
    assert (tmp_path / "app.py").read_text() == "ok"


def test_checkpoint_rollback_restores_and_removes(tmp_path):
    (tmp_path / "a.py").write_text("orig")
    cp = EditableCheckpoint(tmp_path, ["a.py", "b.py"])
    (tmp_path / "a.py").write_text("edited")
    (tmp_path / "b.py").write_text("new")
    assert sorted(cp.rollback()) == ["a.py", "b.py"]
    assert (tmp_path / "a.py").read_text() == "orig" and not (tmp_path / "b.py").exists()


def test_ignored_dirs_are_not_tracked(tmp_path):
    before = snapshot(tmp_path)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"x")
    assert out_of_bounds(before, tmp_path, []) == []
