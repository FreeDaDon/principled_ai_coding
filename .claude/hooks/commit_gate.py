"""Claude Code PreToolUse hook: no `git commit` from a session gets past scripts/check.sh.

Exit 2 blocks the tool call and shows stderr to the model. When the clone already runs the gate as a git hook
(core.hooksPath = .githooks), only the bypass flags are blocked, so the gate never runs twice.
"""

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMIT = re.compile(r"\bgit\b[^;&|\n]*\bcommit\b")
VALUE_FLAGS = {"-m", "-F", "-c", "-C", "-t", "--message", "--file", "--author", "--date", "--template"}
SEPARATORS = {"&&", "||", ";", "|"}


def bypasses(args: str) -> bool:
    """True if the git commit arguments skip hooks. Only the command line is read: a heredoc body and the value of
    -m/-F are message text, so a message that mentions --no-verify is not a bypass."""
    line = args.split("\n", 1)[0]
    try:
        tokens = shlex.split(line)
    except ValueError:
        tokens = line.split()
    skip = False
    for tok in tokens:
        if tok in SEPARATORS:
            break
        if skip:
            skip = False
        elif tok in VALUE_FLAGS:
            skip = True
        elif tok == "--no-verify" or (tok.startswith("-") and not tok.startswith("--") and "n" in tok[1:]):
            return True
    return False


def main() -> int:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    match = COMMIT.search(command)
    if not match:
        return 0
    if bypasses(command[match.end():]):
        print("Blocked: `git commit --no-verify` / `-n` skips the gate. Fix the failures instead.", file=sys.stderr)
        return 2
    hooks_path = subprocess.run(["git", "-C", str(ROOT), "config", "core.hooksPath"], capture_output=True, text=True)
    if hooks_path.stdout.strip() == ".githooks":
        return 0
    gate = subprocess.run([str(ROOT / "scripts" / "check.sh")], capture_output=True, text=True, cwd=ROOT)
    if gate.returncode != 0:
        print("Blocked: scripts/check.sh failed; fix it before committing.\n" + (gate.stdout + gate.stderr)[-3000:],
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
