"""Aggregate domain action specs and expose the confirm dispatch entry point."""

# ⚠️ PARKED (AWS rebuild). Still imports `sqlalchemy` and the
# deleted `app.persistence.models`, and `apply_action` is written around a
# SQLAlchemy `Session`. Not yet rewired to the DynamoDB repository + DTOs
# (AWS_LLD §2) — excluded from the gate. Session 3 rebuilds
# `apply_action` over the `Repository` seam (built in Session 2) and the lifted
# DTOs, re-registers the ported work-item/event/meta specs, and brings this back
# under the gate. Old behavior: `git show main:app/assistant/actions/registry.py`.

from __future__ import annotations

from app.persistence.models import Family, Member
from app.routing.engine import ActionError, ActionRegistry, ActionSpec
from sqlalchemy.orm import Session

from .context import NtakeActionContext
from .events import EVENT_ACTIONS
from .meta import META_ACTIONS
from .work_items import WORK_ITEM_ACTIONS

# Preserve the public flat mapping while authoring specs in domain modules.
ACTIONS: dict[str, ActionSpec[NtakeActionContext]] = {
    **WORK_ITEM_ACTIONS,
    **EVENT_ACTIONS,
    **META_ACTIONS,
}

REGISTRY: ActionRegistry[NtakeActionContext] = ActionRegistry(list(ACTIONS.values()))


def apply_action(
    session: Session,
    member: Member,
    name: str,
    target_id: int | None,
    params: dict,
    target_type: str | None = None,
) -> str:
    """Validate + apply a confirmed action via the engine. Returns a summary.

    Builds the ntake opaque context and calls ``REGISTRY.dispatch``. For
    backwards compatibility, a present ``target_id`` with no explicit
    ``target_type`` is treated as a work-item target, so existing work-item
    confirms keep logging + linking.

    Does not commit — the caller commits so the write publishes once via the seam.
    Raises ActionError for unknown names / missing params / bad targets.
    """
    if target_type is None and target_id is not None:
        target_type = "work_item"
    family = session.get(Family, member.family_id)
    if family is None:
        raise ActionError(f"family not found: {member.family_id}")
    context = NtakeActionContext(
        session=session,
        member=member,
        family_timezone=family.timezone,
        target_id=target_id,
        target_type=target_type,
    )
    summary = REGISTRY.dispatch(name, params, context)
    session.flush()  # autoflush is off; make all pending rows visible pre-commit
    return summary
