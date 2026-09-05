"""The opaque application context passed to confirmed assistant actions."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.persistence.models import Member
from app.routing.engine import ActionContext


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
    target_id: int | None
    target_type: str | None
