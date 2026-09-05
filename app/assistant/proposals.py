"""Present assistant proposals at the API boundary.

This app-coupled adapter resolves family display labels, converts generic engine
actions to response DTOs, and runs the configured bounded proposal call.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.actions.registry import REGISTRY
from app.assistant.capture import FocusedContext
from app.assistant.factory import AssistantConfig, get_assistant
from app.persistence.models import Event, Member, WorkItem
from app.routing.engine import ProposedAction, propose_bounded
from app.schemas import ProposalRead


def to_proposal_read(
    action: ProposedAction,
    index: int,
    target_label: str | None,
    member_names: dict[int, str] | None = None,
    labels: dict[str, dict[int, str]] | None = None,
) -> ProposalRead:
    """Pure map: an engine ProposedAction -> the app's ProposalRead DTO.

    Assigns a batch-local proposal_id from ``index`` (unless the action already
    carries one) and derives ``action_summary`` from the registry (ground truth,
    NOT the model's text). If the action's params carry a ``member_id`` and
    ``member_names`` resolves it, the summary is enriched with the member's name
    (so a card reads "…to Sam", not "…to member 2") — the describe fns stay pure
    (no session); the session-derived name map is applied here. No I/O.
    """
    summary = REGISTRY.describe(action.name, action.params)
    names = member_names or {}
    # Resolve the target's title from the per-type label map if not passed in.
    if target_label is None and action.target_id is not None and action.target_type:
        label_maps = labels or {}
        target_label = (label_maps.get(action.target_type) or {}).get(action.target_id)
    mid = action.params.get("member_id")
    if isinstance(mid, int) and mid in names:
        summary = f"{summary} ({names[mid]})"

    # Verbose, id-resolved card body: the action's OWN render_card (pure), given a
    # resolved bag built from the ALREADY-existing member-name map + target_label
    # (DRY — no new resolution here). None ⇒ no extra lines.
    spec = REGISTRY.get(action.name)
    detail_lines: list[str] = []
    if spec is not None and spec.render_card is not None:
        resolved = {"member_names": names, "target_label": target_label}
        detail_lines = spec.render_card(action.params, resolved)

    return ProposalRead(
        name=action.name,
        params=action.params,
        action_summary=summary,
        llm_rationale=action.llm_rationale,
        target_id=action.target_id,
        target_type=action.target_type,
        proposal_id=action.proposal_id or f"p{index}",
        target_ref=action.target_ref,
        target_label=target_label,
        detail_lines=detail_lines,
    )


def family_member_names(session: Session, family_id: int) -> dict[int, str]:
    """Member id -> display name for a family (for enriching proposal summaries
    like assign_work_item, and any other member-id-bearing render)."""
    return {
        m.id: m.display_name
        for m in session.scalars(
            select(Member).where(Member.family_id == family_id)
        ).all()
    }


def family_target_labels(session: Session, family_id: int) -> dict[str, dict[int, str]]:
    """Per-type id -> title maps for resolving a proposal's target_label on the
    card: ``{"work_item": {id: title}, "event": {id: title}}``. Reused (DRY) by
    _to_proposal_read to name the target of reschedule/assign/etc."""
    wi = {
        w.id: w.title
        for w in session.scalars(
            select(WorkItem).where(WorkItem.family_id == family_id)
        ).all()
    }
    ev = {
        e.id: e.title
        for e in session.scalars(
            select(Event).where(Event.family_id == family_id)
        ).all()
    }
    return {"work_item": wi, "event": ev}


def propose(
    ctx: FocusedContext,
    target_label: str | None,
    config: AssistantConfig,
    member_names: dict[int, str] | None = None,
    labels: dict[str, dict[int, str]] | None = None,
) -> list[ProposalRead]:
    """Get proposals from the configured assistant (bounded; degrade to []) and
    map them to the app DTO.

    Orchestration only: the bounded-timeout + graceful-degrade wrapper is the
    engine's ``propose_bounded`` (the per-call bound is ``config.timeout``); the
    per-action mapping is the pure :func:`to_proposal_read`. ``target_label`` is
    echoed onto each proposal so the confirm card shows context; ``member_names``
    resolves member ids and ``labels`` resolves the target's title.
    """
    actions = propose_bounded(get_assistant(config), ctx, config.timeout)
    return [
        to_proposal_read(a, i, target_label, member_names, labels)
        for i, a in enumerate(actions, start=1)
    ]
