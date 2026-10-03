"""Aggregate domain action specs and expose the confirm dispatch entry point.

Session 3 port (AWS_LLD §2): ``apply_action`` is rebuilt over the
:class:`core.repository.Repository` seam + the lifted DTOs. There is **no**
``commit``/``flush`` — the repository has no deferred unit of work (AWS_LLD
§2.1); each handler's repo call is atomic, and the single live-sync publish
happens once at the confirm/execute boundary (Session 6), not here.
"""

from __future__ import annotations

from core.engine.engine import ActionError, ActionRegistry, ActionSpec
from core.repository import Repository
from core.schemas import Member, TargetType

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
    repo: Repository,
    member: Member,
    name: str,
    target_id: str | None,
    params: dict,
    target_type: str | None = None,
) -> str:
    """Validate + apply a confirmed action via the engine. Returns a summary.

    Builds the ntake opaque context and calls ``REGISTRY.dispatch``. For
    backwards compatibility, a present ``target_id`` with no explicit
    ``target_type`` is treated as a work-item target, so existing work-item
    confirms keep logging + linking.

    No ``commit`` — each repo write is atomic (AWS_LLD §2.1); the caller owns the
    one post-write publish (Session 6). Raises :class:`ActionError` for unknown
    names / missing params / bad targets.
    """
    if target_type is None and target_id is not None:
        target_type = TargetType.WORK_ITEM
    family = repo.get_family(member.family_id)
    if family is None:
        raise ActionError(f"family not found: {member.family_id}")
    context = NtakeActionContext(
        repo=repo,
        member=member,
        family_timezone=family.timezone,
        target_id=target_id,
        target_type=target_type,
    )
    return REGISTRY.dispatch(name, params, context)
