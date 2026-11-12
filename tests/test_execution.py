import os
import shutil
import sys
from pathlib import Path

import pytest

import core.execution as execution
from core.execution import run_command
from core.security import safe_subprocess_env

PROBE = "{python} -c \"import os, sys; print(os.environ.get('ANTHROPIC_API_KEY', 'no-key')); print(os.environ['HOME'])\""


def test_agent_code_gets_no_api_key_and_a_throwaway_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-key-for-tests-0000000000")
    result = run_command(PROBE, tmp_path)
    key, home = result.output.split()
    assert result.exit_code == 0 and key == "no-key"
    assert home != str(Path.home()) and "pac-home-" in home and not os.path.exists(home)


def test_operator_commands_can_keep_the_agent_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-key-for-tests-0000000000")
    result = run_command(PROBE, tmp_path, env=safe_subprocess_env())
    assert result.output.split()[0].startswith("sk-ant-fake")


def test_missing_bwrap_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(execution.shutil, "which", lambda name: None)
    result = run_command("{python} -c pass", tmp_path, sandbox="bwrap")
    assert result.exit_code == 126 and "not installed" in result.output


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap not installed")
def test_bwrap_blocks_network_and_hides_home_but_keeps_the_workdir(tmp_path):
    kept = [str(tmp_path), sys.prefix, sys.base_prefix]
    secrets = [p for p in Path.home().iterdir() if not any(k.startswith(str(p)) for k in kept)]
    if not secrets:
        pytest.skip("nothing in the home directory to hide")
    script = tmp_path / "probe.py"
    script.write_text(
        "import os, socket\n"
        "open('written.txt', 'w').write('ok')\n"
        f"print('home-visible' if os.path.lexists({str(secrets[0])!r}) else 'home-hidden')\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
        "    print('net-open')\n"
        "except OSError:\n"
        "    print('net-blocked')\n"
    )
    result = run_command(f"{{python}} {script.name}", tmp_path, sandbox="bwrap")
    assert result.exit_code == 0, result.output
    assert result.output.split() == ["home-hidden", "net-blocked"]
    assert (tmp_path / "written.txt").read_text() == "ok"


def test_interpreter_placeholder_expands(tmp_path):
    assert sys.executable in run_command("{python} -c pass", tmp_path).command
