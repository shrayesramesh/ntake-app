"""The LLM protocol: the one injected effect the local-LLM backend depends on.

``LLM`` is a **Protocol**, not an ABC — the LLD frames the model as "an injected
effect, not a session": a single ``complete(system, user, schema) -> dict`` call
(an OpenAI-style localhost round trip). Structural typing lets both the real
:class:`~app.assistant.local_llm.client.LocalLlmClient` (httpx, a later step) and
the :class:`ScriptedLLM` test double satisfy it without inheriting anything, and
keeps this file free of any transport import — the boundary the whole backend
rests on (``link``/``propose`` depend on THIS, never on httpx).

``ScriptedLLM`` is the fixture every other Track-A step tests against: canned
JSON keyed off the call, so link/propose flows are exercised deterministically
with no model and no network.
"""

from __future__ import annotations

import copy
from typing import Protocol, runtime_checkable

# A JSON-object response from the model (already parsed). Named for what it is at
# the seam; the literal HTTP/JSON handling lives only in ``client.py``.
type Json = dict


@runtime_checkable
class LLM(Protocol):
    """The single injected effect: one constrained-JSON completion.

    ``complete`` sends a ``system`` + ``user`` message pair and a ``schema`` (the
    constrained-output JSON schema the caller wants the model to obey) and returns
    the parsed JSON object. Implementations MUST return a ``dict`` (the parsed
    response); they do NOT raise for an empty/degenerate answer — the parse layer
    above decides what an unusable answer means (graceful-degrade is step 6).
    """

    def complete(self, system: str, user: str, schema: Json) -> Json: ...


class ScriptedLLM:
    """A deterministic :class:`LLM` for tests — canned JSON keyed off the call.

    Two ways to seed it (combinable):

    * ``responses``: an ordered ``{key: json}`` map. ``complete`` returns the
      first response whose ``key`` is a **substring of the ``user`` message**
      (insertion order breaks ties — earliest wins), so different notes yield
      different output without a model.
    * ``default``: the fallback JSON when no key matches.

    A miss with **no default** raises :class:`KeyError` — a miss is a
    test-authoring bug (the note didn't hit any scripted key), so it fails loudly
    rather than silently returning ``{}``. Each call returns a **deep copy**, so
    a caller mutating the result in place (parsing often does) can't poison a
    later call. Every call is recorded in :attr:`calls` as ``(system, user,
    schema)`` for prompt/schema assertions.
    """

    def __init__(
        self,
        responses: dict[str, Json] | None = None,
        *,
        default: Json | None = None,
    ) -> None:
        self._responses: dict[str, Json] = responses or {}
        self._default = default
        self.calls: list[tuple[str, str, Json]] = []

    def complete(self, system: str, user: str, schema: Json) -> Json:
        self.calls.append((system, user, schema))
        for key, response in self._responses.items():
            if key in user:
                return copy.deepcopy(response)
        if self._default is not None:
            return copy.deepcopy(self._default)
        raise KeyError(
            f"ScriptedLLM: no canned response matched user message {user!r} "
            "and no default was set"
        )
