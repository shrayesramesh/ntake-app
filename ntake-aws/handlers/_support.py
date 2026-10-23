"""Shared handler support — DTO conversions + the capture/confirm core logic.

The thin AWS Lambda shells (one per route group, design B) parse their event and
delegate here, so the request logic is pure and Tier-1-testable with no Lambda
envelope, no network: it takes an injected ``Repository`` + (for capture) an
``AnthropicClient`` + (for writes) a ``ConnectionPoster``, mirroring the reference
FastAPI handlers on ``main`` but over the ``core`` seams.

Re-created here (the reference ``app/assistant/proposals.py`` + ``app/main.py``
helpers were not lifted to ``core``):

* **to_proposal_read** — ``ProposedAction`` → ``ProposalRead``: ``action_summary``
  from the registry's ground-truth ``describe``; ``detail_lines`` from the action's
  ``render_card``; ``target_label`` from a family title map.
* **event_read / work_item_read** — repository DTOs → the API ``*Read`` DTOs, with
  stored-UTC → family-local conversion (``local_start_at``/``local_end_at``/
  ``local_due_at``) and the nested log/checklist mapped to their Read shapes
  (handling ``WorkItemUpdate.update_id`` → ``WorkItemUpdateRead.id`` + injected
  ``work_item_id``, and ``ChecklistEntry`` → ``ChecklistItemRead`` ids).
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.actions.registry import REGISTRY, apply_action
from core.assistant.anthropic_client import AnthropicClient
from core.assistant.anthropic_link import AnthropicCaptureResolver
from core.assistant.anthropic_propose import AnthropicAssistant
from core.assistant.capture import CaptureRequest, ProposedAction
from core.engine.engine import propose_bounded
from core.identity import Principal
from core.live_sync import ConnectionPoster, publish_change
from core.repository import Repository
from core.schemas import (
    CaptureResponse,
    ChecklistItemRead,
    Event,
    EventRead,
    Member,
    ProposalRead,
    WorkItem,
    WorkItemRead,
    WorkItemUpdate,
    WorkItemUpdateRead,
)
from core.temporal import stored_utc_to_family_local

# The capture path spends LINK + PROPOSE sequentially inside the Lambda budget
# (AWS_LLD §3.5); the engine's bounded wrapper caps PROPOSE wall-clock.
_PROPOSE_TIMEOUT_S = 25.0


def family_timezone(repo: Repository, family_id: str) -> str:
    """The family's IANA timezone, or ``UTC`` if the family record is missing."""
    fam = repo.get_family(family_id)
    return fam.timezone if fam is not None else "UTC"


def member_for(repo: Repository, principal: Principal) -> Member | None:
    """Resolve the authorizer's principal to the full ``Member`` DTO."""
    return repo.get_member(principal.family_id, principal.member_id)


# --- capture (LINK -> PROPOSE, propose-only) -------------------------------


def run_capture(
    repo: Repository, client: AnthropicClient, member: Member, text: str
) -> CaptureResponse:
    """Run the two-stage capture over the seams and return propose-only results.

    Server-side ``now`` (UTC) + the family timezone frame the request; LINK
    grounds, PROPOSE plans. **Nothing is persisted** — v1 capture is propose-only
    (``item=None``); the human confirms a proposal via ``/actions/confirm``.
    """
    now = datetime.now(UTC)
    tz = family_timezone(repo, member.family_id)
    request = CaptureRequest(text=text, timezone=tz, now=now)

    resolver = AnthropicCaptureResolver(client)
    ctx = resolver.focus(request, repo, member)
    actions = propose_bounded(AnthropicAssistant(client), ctx, _PROPOSE_TIMEOUT_S)

    labels = _target_labels(repo, member.family_id)
    member_names = {m.id: m.display_name for m in repo.list_members(member.family_id)}
    proposals = [to_proposal_read(a, labels, member_names) for a in actions]
    return CaptureResponse(item=None, proposals=proposals)


def _target_labels(repo: Repository, family_id: str) -> dict[str, dict[str, str]]:
    """Title maps for target labelling: ``{work_item|event: {id: title}}``."""
    return {
        "work_item": {wi.id: wi.title for wi in repo.list_work_items(family_id)},
        "event": {ev.id: ev.title for ev in repo.list_events(family_id)},
    }


def to_proposal_read(
    action: ProposedAction,
    labels: dict[str, dict[str, str]],
    member_names: dict[str, str],
) -> ProposalRead:
    """Map a ``ProposedAction`` to the API ``ProposalRead`` (ground-truth summary).

    ``action_summary`` is the registry's deterministic ``describe`` (what the
    action WILL do — never the model's narration); ``detail_lines`` come from the
    action's own ``render_card`` (given a ``resolved`` map of id→name/label);
    ``target_label`` is the target entity's title.
    """
    resolved = {"member_names": member_names}
    spec = REGISTRY.get(action.name)
    detail_lines: list[str] = []
    if spec is not None and spec.render_card is not None:
        detail_lines = spec.render_card(action.params, resolved)
    target_label: str | None = None
    if action.target_type is not None and action.target_id is not None:
        target_label = labels.get(action.target_type, {}).get(action.target_id)
    return ProposalRead(
        name=action.name,
        params=action.params,
        action_summary=REGISTRY.describe(action.name, action.params),
        llm_rationale=action.llm_rationale,
        target_id=action.target_id,
        target_type=action.target_type,
        target_label=target_label,
        detail_lines=detail_lines,
    )


# --- confirm (execute -> write -> publish once) ----------------------------


def run_confirm(
    repo: Repository,
    member: Member,
    *,
    name: str,
    params: dict,
    target_id: str | None,
    target_type: str | None,
    poster: ConnectionPoster,
) -> dict[str, str]:
    """Execute a confirmed action, then publish the change once (AWS_LLD §4.2).

    Delegates to ``apply_action`` (which validates + writes atomically), then —
    on success — fans out a single ``{entity, id, op}`` nudge to the family's live
    connections. The publish is the handler's job, not the engine's, keeping the
    one publish call site at the confirm/execute boundary (§4.3). ``ActionError``
    propagates to the shell (→ 422).
    """
    summary = apply_action(repo, member, name, target_id, params, target_type)
    entity, entity_id, op = _change_for(name, target_id, target_type)
    if entity is not None and entity_id is not None:
        publish_change(repo, member.family_id, entity, entity_id, op, poster=poster)
    return {"applied": name, "summary": summary}


def _change_for(
    name: str, target_id: str | None, target_type: str | None
) -> tuple[str | None, str | None, str]:
    """The ``{entity, id, op}`` a confirmed action announces (best-effort shape).

    A targeted action announces its target; a create/meta action announces the
    broad entity class so clients refetch the affected board/calendar. ``no_action``
    announces nothing (no write happened).
    """
    if name == "no_action":
        return None, None, "noop"
    if target_type == "event":
        return "event", target_id, "update"
    if target_type == "work_item":
        return "work_item", target_id, "update"
    # Creators / archive_all_done: no single target id; nudge the entity class so
    # the client refetches (id echoes the family-level change as the action name).
    if "event" in name:
        return "event", name, "create"
    return "work_item", name, "create"


# --- REST read conversions (repository DTO -> API *Read DTO) ---------------


def event_read(event: Event, timezone: str) -> EventRead:
    """Repository ``Event`` → API ``EventRead`` (UTC → family-local timing)."""
    return EventRead(
        id=event.id,
        family_id=event.family_id,
        title=event.title,
        description=event.description,
        location=event.location,
        all_day=event.all_day,
        local_start_at=(
            stored_utc_to_family_local(event.start_at, timezone)
            if event.start_at is not None
            else None
        ),
        local_end_at=(
            stored_utc_to_family_local(event.end_at, timezone)
            if event.end_at is not None
            else None
        ),
        start_date=event.start_date,
        end_date=event.end_date,
        participants=list(event.participants),
        tags=list(event.tags),
    )


def work_item_read(work_item: WorkItem, timezone: str) -> WorkItemRead:
    """Repository ``WorkItem`` → API ``WorkItemRead`` (local due + nested log/list).

    ``due_at`` (stored UTC) becomes ``local_due_at`` (family-local wall time). The
    nested log/checklist are mapped to their Read shapes: ``WorkItemUpdate.update_id``
    → ``WorkItemUpdateRead.id`` with the ``work_item_id`` injected, and each
    ``ChecklistEntry`` → a ``ChecklistItemRead`` whose id is its position (stable
    within the item).
    """
    local_due_at = (
        stored_utc_to_family_local(work_item.due_at, timezone)
        if work_item.due_at is not None
        else None
    )
    return WorkItemRead(
        id=work_item.id,
        family_id=work_item.family_id,
        assigned_to=work_item.assigned_to,
        title=work_item.title,
        description=work_item.description,
        status=work_item.status,
        position=work_item.position,
        local_due_at=local_due_at,
        tags=list(work_item.tags),
        created_at=work_item.created_at,
        updated_at=work_item.updated_at,
        completed_at=work_item.completed_at,
        archived_at=work_item.archived_at,
        updates=[_update_read(u, work_item.id) for u in work_item.updates],
        checklist=[
            ChecklistItemRead(
                id=f"{work_item.id}:{entry.position}",
                text=entry.text,
                checked=entry.checked,
                position=entry.position,
            )
            for entry in work_item.checklist
        ],
    )


def _update_read(update: WorkItemUpdate, work_item_id: str) -> WorkItemUpdateRead:
    """Map a nested ``WorkItemUpdate`` to ``WorkItemUpdateRead`` (id + parent id)."""
    return WorkItemUpdateRead(
        id=update.update_id,
        work_item_id=work_item_id,
        author_id=update.author_id,
        source=update.source,
        body=update.body,
        created_at=update.created_at,
    )
