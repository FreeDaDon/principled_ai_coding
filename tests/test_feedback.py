from director_loop.feedback import extract_failures, failure_signature, truncate

PYTEST_OUT = """....F
=================================== FAILURES ===================================
___________________________ test_rank ___________________________
    def test_rank():
>       assert rank() == [1]
E       AssertionError: assert [] == [1]
tests/test_x.py:5: AssertionError
=========================== short test summary info ============================
FAILED tests/test_x.py::test_rank - AssertionError: assert [] == [1]
1 failed, 4 passed in 0.10s
"""


def test_pytest_failures_section_is_extracted():
    out = extract_failures("lots of noise\n" * 50 + PYTEST_OUT)
    assert out.startswith("=====") and "AssertionError" in out and "noise" not in out


def test_traceback_tail_is_extracted():
    out = extract_failures("setup ok\nTraceback (most recent call last):\n  File x\nKeyError: 'id'\n")
    assert out.startswith("Traceback") and "KeyError" in out


def test_lint_lines_are_extracted():
    out = extract_failures("Checking...\nsrc/a.py:3:1: F401 unused import\nsrc/b.py:9:5: E711 comparison\nFound 2 errors.")
    assert out.splitlines() == ["src/a.py:3:1: F401 unused import", "src/b.py:9:5: E711 comparison"]


def test_truncate_keeps_head_and_tail():
    t = truncate("A" * 100 + "B" * 100, 50)
    assert t.startswith("A" * 25) and t.endswith("B" * 25) and "omitted" in t


def test_signature_ignores_timing_but_tracks_failures():
    a = failure_signature(PYTEST_OUT)
    b = failure_signature(PYTEST_OUT.replace("0.10s", "0.31s"))
    c = failure_signature(PYTEST_OUT.replace("test_rank", "test_score"))
    assert a == b != c
