"""The opaque application context passed to confirmed assistant actions.

Session 3 port (AWS_LLD §2): the SQLAlchemy ``Session`` the handlers used to
unpack is replaced by the :class:`core.repository.Repository` seam, and the ORM
``Member`` by the lifted Pydantic DTO. ``target_id`` is now a ULID **string**
(AWS_LLD §1). The engine never inspects this; the handlers below unpack it.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.engine.engine import ActionContext
from core.repository import Repository
from core.schemas import Member


@dataclass
class NtakeActionContext(ActionContext):
    """The opaque context ntake injects into the engine at dispatch time.

    The engine never inspects this; the handlers below unpack it. ``target_type``
    ("work_item" | "event" | None) generalizes the target (task 12): the
    conditional log rule lives in the handlers (only a work-item target appends a
    source=assistant update).
    """

    repo: Repository
    member: Member
    family_timezone: str
    target_id: str | None
    target_type: str | None
