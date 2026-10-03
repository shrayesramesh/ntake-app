"""The opaque application context passed to confirmed assistant actions."""

# ⚠️ PARKED (AWS rebuild). This module still imports `sqlalchemy`
# and the deleted `app.persistence.models`; it is NOT yet rewired to the DynamoDB
# repository + DTOs (AWS_LLD §2). It is deliberately excluded from the gate
# (mypy/coverage/lint scope + not imported by any live module or test).
# Session 3 replaces the `Session`/ORM-model dependency with the `Repository`
# protocol (built in Session 2) and the lifted Pydantic DTOs, then brings it back
# under the gate.
# Reference for the old behavior: `git show main:app/assistant/actions/context.py`.

from __future__ import annotations

from dataclasses import dataclass

from app.persistence.models import Member
from app.routing.engine import ActionContext
from sqlalchemy.orm import Session


@dataclass
class NtakeActionContext(ActionContext):
    """The opaque context ntake injects into the engine at dispatch time.

    The engine never inspects this; the handlers below unpack it. ``target_type``
    ("work_item" | "event" | None) generalizes the target (task 12): the
    conditional log rule lives in the handlers (only a work-item target appends a
    source=assistant update).
    """

    session: Session
    member: Member
    family_timezone: str
    target_id: int | None
    target_type: str | None
