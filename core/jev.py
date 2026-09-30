"""Jev: one cheap, schema-validated typed decision in place of a full agent call, for fixed-option judgments.

Ported from the Jev reference codebase (ten-levels-of-jev: src/core/{types,client,mock}.ts, the level 2
multiple-choice and level 4 confidence-gated patterns). Choice questions only, one isolated state per call.

Backends (JEV_BACKEND):
  mock        default. Offline, deterministic, $0: token overlap through a softmax, a stand-in for the
              wire contract's SHAPE, not for intelligence
  typesafe    POST https://api.typesafe.ai/v1/systemone with TYPESAFE_API_KEY
  openrouter  POST https://openrouter.ai/api/alpha/decisions with OPENROUTER_API_KEY
  live        typesafe if its key is set, else openrouter
A live backend without its key, or an unknown value, silently falls back to mock: Jev is advisory, so a
misconfiguration must never fail a workflow. Mock and live answers pass the same contract check, and a
violation raises JevContractError; nothing degrades silently. Callers treat any JevError, and any answer
under their confidence floor, as "fall back to the full agent path".

Boundary: Jev never gates a test verdict, a security check or a release step. The Director's evaluator and
the domain packs' --fail-on gate stay deterministic or agent-judged, and never consult Jev.
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Literal

from pydantic import ValidationError

from .types import JevBackend, JevChoiceQuestion, JevDecision, JevResponse

LiveBackend = Literal["typesafe", "openrouter"]

ENDPOINTS: dict[LiveBackend, str] = {
    "typesafe": "https://api.typesafe.ai/v1/systemone",
    "openrouter": "https://openrouter.ai/api/alpha/decisions",
}
DEFAULT_MODELS: dict[LiveBackend, str] = {"typesafe": "jev-latest", "openrouter": "~typesafe/jev-latest"}
KEY_ENV: dict[LiveBackend, str] = {"typesafe": "TYPESAFE_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
MOCK_MODEL = "jev-1.13.0-mock"
DISTRIBUTION_TOLERANCE = 0.025
TIMEOUT_S = 15
QUESTION_ID = "q"


class JevError(RuntimeError):
    """The call failed (network, HTTP status, timeout). Callers fall back to the agent path."""


class JevContractError(JevError):
    """The response violated the wire contract. Its answer is never used; the caller falls back."""


# ----------------------------------------------------------------------------- backend selection
def _key(backend: LiveBackend) -> str:
    return os.getenv(KEY_ENV[backend], "").strip()


def select_backend() -> JevBackend:
    raw = os.getenv("JEV_BACKEND", "mock").strip().lower()
    if raw in ("typesafe", "openrouter"):
        live: LiveBackend = "typesafe" if raw == "typesafe" else "openrouter"
        return live if _key(live) else "mock"
    if raw == "live":
        if _key("typesafe"):
            return "typesafe"
        return "openrouter" if _key("openrouter") else "mock"
    return "mock"


# ----------------------------------------------------------------------------- contract
def validate_response(payload: object, question: JevChoiceQuestion) -> JevResponse:
    """The strict live contract (client.ts validateResponse, choice branch). Raises JevContractError."""
    try:
        response = JevResponse.model_validate(payload)
    except ValidationError as exc:
        raise JevContractError(f"invalid response envelope: {exc.error_count()} error(s)") from exc
    answer = response.answers.get(QUESTION_ID)
    if answer is None:
        raise JevContractError("missing answer")
    options = set(question.criteria)
    probs = answer.probabilities
    if set(probs) != options or any(not (0.0 <= p <= 1.0) or math.isnan(p) for p in probs.values()):
        raise JevContractError("distribution keys must match the declared options")
    total = sum(probs.values())
    if abs(total - 1.0) > DISTRIBUTION_TOLERANCE:
        raise JevContractError(f"distribution does not sum to one ({total:.4f})")
    if answer.choice not in options:
        raise JevContractError("undeclared choice returned")
    return response


# ----------------------------------------------------------------------------- mock (port of mock.ts)
_STOPWORDS = frozenset("""
the a an and or but if then than of to in on at for with without is are was were be been being do does did done
this that these those it its as by from into about against between through during before after above below up
down out off over under again further once here there when where why how all any both each few more most other
some such no nor not only own same so too very s t can will just don should now d ll m o re ve y i you we they he
she what which who whom am has have had having message text given
""".split())
_PUNCT = re.compile(r"[`_*#>/\[\]{}()\"',.;:!?\\\-]")


def _stem(t: str) -> str:
    if len(t) > 4 and t.endswith("ing"):
        return t[:-3]
    if len(t) > 4 and t.endswith("ed"):
        return t[:-2]
    if len(t) > 3 and t.endswith("es"):
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _tokens(text: str) -> set[str]:
    return {_stem(t) for t in _PUNCT.sub(" ", text.lower()).split() if len(t) > 1 and t not in _STOPWORDS}


def _softmax(values: list[float], temperature: float = 0.6) -> list[float]:
    if all(v == 0 for v in values):
        return [1 / len(values)] * len(values)
    top = max(values)
    exps = [math.exp((v - top) / temperature) for v in values]
    total = sum(exps)
    return [e / total for e in exps]


def mock_payload(state: str, question: JevChoiceQuestion) -> dict[str, object]:
    """Deterministic wire-shaped reply: key overlap weighs 1.5, rubric overlap 1.0, softmax at 0.6."""
    state_tokens = _tokens(state)
    options = list(question.criteria.items())
    affinities = [1.5 * len(state_tokens & _tokens(opt.replace("_", " "))) + len(state_tokens & _tokens(desc or ""))
                  for opt, desc in options]
    probs = _softmax(affinities)
    best = max(range(len(options)), key=lambda i: probs[i])
    return {
        "model": MOCK_MODEL,
        "answers": {QUESTION_ID: {
            "type": "choice", "choice": options[best][0], "confidence": round(probs[best], 4),
            "probabilities": {opt: round(p, 4) for (opt, _), p in zip(options, probs, strict=True)},
        }},
        "usage": {"input_tokens": math.ceil(len(state) / 4) + 20, "output_tokens": 20},
    }


# ----------------------------------------------------------------------------- live transport
class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the bearer token to another host; refuse it (it surfaces as an HTTPError)."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def _post(backend: LiveBackend, body: bytes, timeout_s: float) -> object:
    request = urllib.request.Request(  # noqa: S310 - fixed https endpoints only
        ENDPOINTS[backend], data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_key(backend)}"},
    )
    try:
        with _OPENER.open(request, timeout=timeout_s) as resp:
            text = resp.read()
    except urllib.error.HTTPError as exc:
        hint = " Check the API key." if exc.code == 401 else " Check account credits." if exc.code == 402 else ""
        raise JevError(f"jev {backend} HTTP {exc.code}.{hint}") from None
    except (OSError, ValueError) as exc:
        raise JevError(f"jev {backend} call failed: {type(exc).__name__}") from None
    try:
        return json.loads(text)
    except ValueError:
        raise JevContractError("invalid response JSON") from None


# ----------------------------------------------------------------------------- client
class JevClient:
    """One typed choice per call. The backend is resolved once, at construction."""

    def __init__(self, backend: JevBackend | None = None, timeout_s: float = TIMEOUT_S) -> None:
        self.backend: JevBackend = backend or select_backend()
        self.timeout_s = timeout_s
        self.calls = 0

    def choose(self, state: str, question: JevChoiceQuestion) -> JevDecision:
        self.calls += 1
        if self.backend == "mock":
            payload: object = mock_payload(state, question)
        else:
            body = {"model": DEFAULT_MODELS[self.backend], "state": state,
                    "questions": {QUESTION_ID: question.model_dump()}}
            payload = _post(self.backend, json.dumps(body).encode(), self.timeout_s)
        response = validate_response(payload, question)
        answer = response.answers[QUESTION_ID]
        return JevDecision(choice=answer.choice, confidence=answer.confidence, probabilities=answer.probabilities,
                           backend=self.backend, model=response.model, usage=response.usage)
