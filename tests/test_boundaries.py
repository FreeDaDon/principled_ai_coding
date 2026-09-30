import os

import pytest

import core.boundaries as b
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


def test_large_files_are_tracked_and_restored_without_holding_them_in_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "MAX_FILE_BYTES", 10)
    (tmp_path / "data.bin").write_bytes(b"L" * 100)
    (tmp_path / "gone.bin").write_bytes(b"G" * 100)
    before = snapshot(tmp_path)
    assert "data.bin" not in before.files and "data.bin" in before.large  # fingerprint + disk backup
    (tmp_path / "data.bin").write_bytes(b"tampered" * 20)
    (tmp_path / "gone.bin").unlink()
    (tmp_path / "huge_new.bin").write_bytes(b"N" * 100)
    bad = out_of_bounds(before, tmp_path, [])
    assert bad == ["data.bin", "gone.bin", "huge_new.bin"]
    restore(before, tmp_path, bad)
    assert (tmp_path / "data.bin").read_bytes() == b"L" * 100 and (tmp_path / "gone.bin").read_bytes() == b"G" * 100
    assert not (tmp_path / "huge_new.bin").exists()
    backups = before.backups.name
    before.close()
    assert not os.path.exists(backups)


def test_an_unchanged_large_file_is_not_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "MAX_FILE_BYTES", 10)
    (tmp_path / "data.bin").write_bytes(b"L" * 100)
    before = snapshot(tmp_path)
    (tmp_path / "data.bin").write_bytes(b"L" * 100)  # rewritten with identical content
    assert out_of_bounds(before, tmp_path, []) == []


def test_symlinks_are_tracked_by_target_and_never_written_through(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside stays untouched")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "link").symlink_to("a.txt")
    (tmp_path / "doomed").symlink_to("b.txt")
    before = snapshot(tmp_path)
    assert before.links == {"doomed": "b.txt", "link": "a.txt"}
    (tmp_path / "link").unlink()
    (tmp_path / "link").symlink_to(outside)           # retargeted out of the tree
    (tmp_path / "doomed").unlink()
    (tmp_path / "doomed").write_text("replaced by a file")
    (tmp_path / "new_link").symlink_to(outside)       # created
    bad = out_of_bounds(before, tmp_path, [])
    assert bad == ["doomed", "link", "new_link"]
    restore(before, tmp_path, bad)
    assert (tmp_path / "link").readlink().as_posix() == "a.txt" and (tmp_path / "doomed").readlink().as_posix() == "b.txt"
    assert not (tmp_path / "new_link").exists() and not (tmp_path / "new_link").is_symlink()
    assert outside.read_text() == "outside stays untouched"


def test_restore_replaces_a_symlink_instead_of_writing_through_it(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-victim.txt"
    outside.write_text("victim")
    (tmp_path / "ro.py").write_text("keep")
    before = snapshot(tmp_path)
    (tmp_path / "ro.py").unlink()
    (tmp_path / "ro.py").symlink_to(outside)          # a regular file swapped for a link out of the tree
    restore(before, tmp_path, out_of_bounds(before, tmp_path, []))
    assert not (tmp_path / "ro.py").is_symlink() and (tmp_path / "ro.py").read_text() == "keep"
    assert outside.read_text() == "victim"


def test_guarded_run_cleans_up_backups_even_when_the_agent_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "MAX_FILE_BYTES", 10)
    (tmp_path / "data.bin").write_bytes(b"L" * 100)
    made = []
    real = b.snapshot
    monkeypatch.setattr(b, "snapshot", lambda root, backup=True: made.append(real(root, backup)) or made[-1])

    def boom(request, attempt):
        raise RuntimeError("agent crashed")

    request = AgentRequest(role="coder", prompt="p", working_dir=str(tmp_path), editable=[])
    with pytest.raises(RuntimeError):
        guarded_run(MockRunner({"coder": boom}), request)
    assert not os.path.exists(made[0].backups.name)
