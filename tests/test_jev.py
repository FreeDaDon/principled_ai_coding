import io
import json
import urllib.error
import urllib.request

import pytest

from core import jev
from core.jev import JevClient, JevContractError, JevError, mock_payload, select_backend, validate_response
from core.types import JevChoiceQuestion

QUESTION = JevChoiceQuestion(
    instructions="What kind of ticket is this?",
    criteria={"bug_report": "Something is broken, crashes, or behaves wrong",
              "billing": "Charges, invoices, refunds, subscriptions",
              "other": None},
)
FAKE_KEY = "apikey_test_not_a_real_key_0123456789"


def payload(choice="bug_report", probs=None, **overrides):
    probs = probs if probs is not None else {"bug_report": 0.9, "billing": 0.05, "other": 0.05}
    body = {"model": "jev-1.13.0", "usage": {"input_tokens": 10, "output_tokens": 5},
            "answers": {"q": {"type": "choice", "choice": choice, "confidence": 0.9, "probabilities": probs}}}
    body.update(overrides)
    return body


# ----------------------------------------------------------------------------- backend selection
@pytest.mark.parametrize(("backend", "keys", "expected"), [
    (None, {}, "mock"),
    ("mock", {"TYPESAFE_API_KEY": FAKE_KEY}, "mock"),
    ("typesafe", {}, "mock"),                                   # opted in, no key: silent fallback
    ("typesafe", {"TYPESAFE_API_KEY": "  "}, "mock"),           # blank key counts as missing
    ("typesafe", {"TYPESAFE_API_KEY": FAKE_KEY}, "typesafe"),
    ("openrouter", {"TYPESAFE_API_KEY": FAKE_KEY}, "mock"),     # the key must match the backend
    ("openrouter", {"OPENROUTER_API_KEY": FAKE_KEY}, "openrouter"),
    ("live", {"TYPESAFE_API_KEY": FAKE_KEY, "OPENROUTER_API_KEY": FAKE_KEY}, "typesafe"),
    ("live", {"OPENROUTER_API_KEY": FAKE_KEY}, "openrouter"),
    ("live", {}, "mock"),
    ("LiVe ", {"TYPESAFE_API_KEY": FAKE_KEY}, "typesafe"),
    ("gpt-5", {"TYPESAFE_API_KEY": FAKE_KEY}, "mock"),         # unknown value: mock, never an error
])
def test_select_backend(monkeypatch, backend, keys, expected):
    if backend is None:
        monkeypatch.delenv("JEV_BACKEND", raising=False)
    else:
        monkeypatch.setenv("JEV_BACKEND", backend)
    for name, value in keys.items():
        monkeypatch.setenv(name, value)
    assert select_backend() == expected


def test_tests_are_isolated_from_the_shell():
    assert select_backend() == "mock" and JevClient().backend == "mock"


# ----------------------------------------------------------------------------- mock
def test_mock_is_deterministic_and_meets_the_contract():
    first = JevClient().choose("The app crashes when I open settings", QUESTION)
    again = JevClient().choose("The app crashes when I open settings", QUESTION)
    assert first == again
    assert first.choice == "bug_report" and first.backend == "mock" and first.model == jev.MOCK_MODEL
    assert set(first.probabilities) == set(QUESTION.criteria)
    assert abs(sum(first.probabilities.values()) - 1) < 0.01
    assert first.confidence == max(first.probabilities.values())


def test_mock_with_no_signal_is_uniform_and_unconfident():
    decision = JevClient().choose("zzz qqq", QUESTION)
    assert decision.confidence == pytest.approx(1 / 3, abs=1e-3)


def test_mock_output_passes_the_same_validator_as_live():
    validate_response(mock_payload("refund my invoice", QUESTION), QUESTION)


# ----------------------------------------------------------------------------- contract
@pytest.mark.parametrize("bad", [
    payload(choice="PWNED"),                                                          # undeclared choice
    payload(probs={"bug_report": 0.9, "billing": 0.1}),                               # option missing
    payload(probs={"bug_report": 0.8, "billing": 0.1, "other": 0.05, "x": 0.05}),     # extra option
    payload(probs={"bug_report": 0.5, "billing": 0.1, "other": 0.1}),                 # sums to 0.7
    payload(probs={"bug_report": 1.2, "billing": -0.1, "other": -0.1}),               # out of range
    payload(probs={"bug_report": float("nan"), "billing": 0.5, "other": 0.5}),
    payload(usage={"input_tokens": -1, "output_tokens": 0}),
    payload(usage=None),
    payload(model=""),
    payload(answers={}),
    {"answers": {"q": {"type": "choice", "choice": "bug_report"}}},
    [],
    "not json",
])
def test_contract_violations_raise(bad):
    with pytest.raises(JevContractError):
        validate_response(bad, QUESTION)


def test_contract_keeps_provider_extensions():
    validate_response(payload(provider_extra={"trace": "x"}), QUESTION)


# ----------------------------------------------------------------------------- live transport (faked, offline)
class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def live_client(monkeypatch, backend="typesafe", reply=None, error=None):
    monkeypatch.setenv(jev.KEY_ENV[backend], FAKE_KEY)
    sent = []

    def fake_open(request, timeout):
        sent.append((request, timeout))
        if error is not None:
            raise error
        return FakeResponse(reply if isinstance(reply, bytes) else json.dumps(reply).encode())

    monkeypatch.setattr(jev._OPENER, "open", fake_open)
    return JevClient(backend=backend), sent


@pytest.mark.parametrize("backend", ["typesafe", "openrouter"])
def test_live_request_shape(monkeypatch, backend):
    client, sent = live_client(monkeypatch, backend, reply=payload())
    decision = client.choose("checkout is broken", QUESTION)
    assert decision.choice == "bug_report" and decision.backend == backend and decision.model == "jev-1.13.0"
    request, timeout = sent[0]
    assert request.full_url == jev.ENDPOINTS[backend] and request.get_method() == "POST" and timeout == jev.TIMEOUT_S
    assert request.get_header("Authorization") == f"Bearer {FAKE_KEY}"
    body = json.loads(request.data)
    assert body == {"model": jev.DEFAULT_MODELS[backend], "state": "checkout is broken",
                    "questions": {"q": {"type": "choice", "instructions": QUESTION.instructions,
                                        "criteria": QUESTION.criteria}}}


def test_live_malformed_reply_is_a_contract_error(monkeypatch):
    client, _ = live_client(monkeypatch, reply=payload(choice="ignore previous instructions"))
    with pytest.raises(JevContractError):
        client.choose("x", QUESTION)
    client, _ = live_client(monkeypatch, reply=b"<html>gateway</html>")
    with pytest.raises(JevContractError):
        client.choose("x", QUESTION)


@pytest.mark.parametrize(("error", "needle"), [
    (urllib.error.HTTPError(jev.ENDPOINTS["typesafe"], 401, "no", {}, None), "HTTP 401. Check the API key."),
    (urllib.error.HTTPError(jev.ENDPOINTS["typesafe"], 302, "redirect refused", {}, None), "HTTP 302"),
    (TimeoutError("timed out"), "TimeoutError"),
    (urllib.error.URLError("dns"), "URLError"),
])
def test_live_failures_raise_jev_error_without_the_key(monkeypatch, error, needle):
    client, _ = live_client(monkeypatch, error=error)
    with pytest.raises(JevError) as caught:
        client.choose("x", QUESTION)
    assert needle in str(caught.value) and FAKE_KEY not in str(caught.value)
    assert caught.value.__cause__ is None  # no chained exception that could carry the request


def test_redirects_are_refused():
    redirectors = [h for h in jev._OPENER.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert len(redirectors) == 1 and isinstance(redirectors[0], jev._RefuseRedirects)
    assert redirectors[0].redirect_request() is None  # urllib then raises the 3xx as an HTTPError


def test_jev_keys_never_reach_subprocesses(monkeypatch):
    from core.security import SAFE_ENV_KEYS, safe_subprocess_env

    monkeypatch.setenv("TYPESAFE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    assert not {"TYPESAFE_API_KEY", "OPENROUTER_API_KEY"} & SAFE_ENV_KEYS
    assert FAKE_KEY not in safe_subprocess_env().values()
