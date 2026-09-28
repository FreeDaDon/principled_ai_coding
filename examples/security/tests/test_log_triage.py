from datetime import datetime
from pathlib import Path

from log_triage import evaluate_rule, load_rule, parse_line, sanitize
from triage_types import AuthEvent

ROOT = Path(__file__).resolve().parents[1]
RULE = ROOT / "rules" / "ssh_bruteforce.yaml"


def events(name: str) -> list[AuthEvent]:
    lines = (ROOT / "fixtures" / name).read_text().splitlines()
    return [e for e in (parse_line(ln, 2026) for ln in lines) if e is not None]


def test_sanitize_strips_ansi_controls_and_secrets():
    raw = "\x1b[31mFailed\x1b[0m login\x07 password=hunter2 key AKIAABCDEFGHIJKLMNOP\ttab"
    assert sanitize(raw) == "Failed login password=[REDACTED] key [REDACTED_AWS_KEY] tab"
    assert len(sanitize("A" * 2000)) == 512


def test_parse_failure_invalid_user_and_success():
    e = parse_line("Sep 28 10:00:09 web1 sshd[1202]: Failed password for invalid user admin from 203.0.113.5 port 50023 ssh2", 2026)
    assert e is not None
    assert (e.outcome, e.user, e.source_ip, e.host) == ("failure", "admin", "203.0.113.5", "web1")
    assert e.timestamp == datetime(2026, 9, 28, 10, 0, 9)
    ok = parse_line("Sep  8 10:01:10 web1 sshd[1210]: Accepted publickey for deploy from 10.0.0.4 port 51000 ssh2", 2026)
    assert ok is not None and ok.outcome == "success" and ok.timestamp.day == 8
    inv = parse_line("Sep 28 10:02:00 web1 sshd[9]: Invalid user test from 198.51.100.7 port 4000", 2026)
    assert inv is not None and inv.outcome == "invalid_user"


def test_parse_ignores_non_auth_and_ansi_wrapped_lines():
    assert parse_line("Sep 28 10:12:30 web1 CRON[1300]: pam_unix(cron:session): session opened", 2026) is None
    e = parse_line("\x1b[1mSep 28 10:00:01 web1 sshd[1]: Failed password for root from 203.0.113.5 port 1 ssh2\x1b[0m", 2026)
    assert e is not None and e.user == "root"


def test_load_rule_is_typed():
    rule = load_rule(RULE)
    assert (rule.id, rule.threshold, rule.window_seconds, rule.group_by) == ("SSH-BF-001", 5, 60, "source_ip")


def test_rule_fires_on_positive_fixture():
    alerts = evaluate_rule(load_rule(RULE), events("auth_positive.log"))
    assert [(a.key, a.count) for a in alerts] == [("203.0.113.5", 6)]
    assert alerts[0].users == ["admin", "oracle", "root", "ubuntu"]
    assert alerts[0].first_seen == datetime(2026, 9, 28, 10, 0, 1)


def test_rule_silent_on_negative_fixture():
    assert evaluate_rule(load_rule(RULE), events("auth_negative.log")) == []
