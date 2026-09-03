"""FastAPI application.

Endpoints:
  * ``GET /health``        — liveness (1a)
  * ``GET /events``        — events read path (1c)
  * ``GET /events/stream`` — Server-Sent Events live-sync stream (1e)

Live sync (DESIGN §4.3): the module-level ``app_emitter`` is bound to the DB
engine via ``register_change_events`` so every commit publishes a change event
(1d). The SSE endpoint subscribes a per-connection queue to that emitter and
streams ``{entity, id, op}`` notifications; the front-end refetches on receipt.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

import app.db as db
from app import __version__
from app.assistant.actions import REGISTRY, ActionError, apply_action
from app.assistant.context import CaptureRequest, FocusedContext
from app.assistant.factory import get_assistant, get_capture_resolver
from app.auth import current_member, current_member_stream
from app.config import config_path, load_config, seed_from_config
from app.db import SessionLocal, get_session, init_schema, register_change_events
from app.event_emitter import InProcessEmitter
from app.models import (
    WORK_ITEM_STATUSES,
    ChecklistItem,
    Event,
    Family,
    Member,
    WorkItem,
    WorkItemUpdate,
)
from app.routing.engine import ProposedAction, propose_bounded
from app.schemas import (
    CaptureCreate,
    CaptureResponse,
    ChecklistItemRead,
    ConfirmAction,
    EventRead,
    ProposalRead,
    WorkItemCreate,
    WorkItemRead,
    WorkItemUpdateCreate,
    WorkItemUpdateRead,
)
from app.web import SHELL_PAGE, render_board, render_calendar


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """On startup: ensure the schema exists, then seed identity from config.

    Schema init is unconditional (a real server needs its tables — the LAN smoke
    500'd on ``no such table`` before this existed). Config seeding is conditional
    on the file existing, so tests that boot the app without ``NTAKE_CONFIG`` set
    don't fail; a real deployment points ``NTAKE_CONFIG`` at its out-of-repo file.
    Reads ``db.engine`` at runtime so a rebound engine (tests) is honored.
    """
    init_schema(db.engine)

    path = config_path()
    if path.exists():
        session = db.SessionLocal()
        try:
            seed_from_config(session, load_config(path))
        finally:
            session.close()

    yield


app = FastAPI(title="Family Calendar", lifespan=lifespan)

# The single live-sync emitter. Bound to the session factory so every committed
# write (from any session it makes) publishes a change event.
app_emitter = InProcessEmitter()
register_change_events(SessionLocal, app_emitter)


@app.get("/health")
def health() -> dict:
    """Liveness check (checkpoint 1a)."""
    return {"status": "ok", "version": __version__}


@app.get("/events", response_model=list[EventRead])
def list_events(
    session: Session = Depends(get_session),
    _member: Member = Depends(current_member),
) -> list[Event]:
    """Return all persisted events as JSON (checkpoint 1c).

    Requires a valid device token (ACCESS-2). Ordered by start time; FastAPI
    serializes each ORM Event via EventRead (from_attributes).
    """
    stmt = select(Event).order_by(Event.start_at)
    return list(session.scalars(stmt).all())


def _format_change(entity: str, entity_id: int, op: str) -> dict:
    """Render a change event as an SSE message dict (client refetches on it)."""
    data = json.dumps({"entity": entity, "id": entity_id, "op": op})
    return {"event": "change", "data": data}


def subscribe(emitter: InProcessEmitter) -> tuple[asyncio.Queue, Callable[[], None]]:
    """Attach a queue listener to the emitter; return the queue + an unsubscribe.

    Kept separate from the endpoint so the subscription wiring is unit-testable
    without opening a real SSE socket (which never completes).
    """
    queue: asyncio.Queue[tuple[str, int, str]] = asyncio.Queue()

    async def listener(entity: str, entity_id: int, op: str) -> None:
        await queue.put((entity, entity_id, op))

    emitter.add_listener(listener)

    def unsubscribe() -> None:
        if listener in emitter.listeners:
            emitter.listeners.remove(listener)

    return queue, unsubscribe


@app.get("/events/stream")
async def events_stream(
    _member: Member = Depends(current_member_stream),
) -> EventSourceResponse:
    """Server-Sent Events stream of change notifications (checkpoint 1e).

    Requires a valid device token (ACCESS-2). Thin transport over
    :func:`subscribe`: each connection gets its own queue, the emitter fans
    committed changes out to it, and we stream them until the client
    disconnects. `EventSource` auto-reconnects.
    """
    queue, unsubscribe = subscribe(app_emitter)

    async def event_generator() -> AsyncIterator[dict]:
        try:
            while True:
                yield _format_change(*await queue.get())
        finally:
            unsubscribe()

    return EventSourceResponse(event_generator())


# --- Work items (Phase 3, checkpoint 2) ----------------------------------


def _load_work_item(session: Session, work_item_id: int) -> WorkItem:
    # REST layer: a missing item on a direct GET/POST is a 404. (The action
    # handlers in app/assistant/actions.py deliberately raise ActionError
    # instead — the confirm endpoint maps that to 422, since a bad target there
    # is an invalid *action*, not a missing *route resource*.)
    wi = session.get(WorkItem, work_item_id)
    if wi is None:
        raise HTTPException(status_code=404, detail="Work item not found.")
    return wi


def _work_item_detail(session: Session, wi: WorkItem) -> WorkItemRead:
    """Build the detail DTO: the item + its update log + checklist."""
    updates = session.scalars(
        select(WorkItemUpdate)
        .where(WorkItemUpdate.work_item_id == wi.id)
        .order_by(WorkItemUpdate.created_at, WorkItemUpdate.id)
    ).all()
    checklist = session.scalars(
        select(ChecklistItem)
        .where(ChecklistItem.work_item_id == wi.id)
        .order_by(ChecklistItem.position)
    ).all()
    dto = WorkItemRead.model_validate(wi)
    dto.updates = [WorkItemUpdateRead.model_validate(u) for u in updates]
    dto.checklist = [ChecklistItemRead.model_validate(c) for c in checklist]
    return dto


@app.post("/work-items", response_model=WorkItemRead, status_code=201)
def create_work_item(
    payload: WorkItemCreate,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
) -> WorkItemRead:
    """Create a work item (WORKITEM). Auth-protected; scoped to the member's family."""
    now = datetime.now(UTC)
    wi = WorkItem(
        family_id=member.family_id,
        title=payload.title,
        description=payload.description,
        tags=payload.tags,
        assigned_to=payload.assigned_to,
        created_at=now,
        updated_at=now,
    )
    session.add(wi)
    session.commit()  # commit publishes {work_items, id, create} via the 1d seam
    session.refresh(wi)
    return _work_item_detail(session, wi)


@app.get("/work-items", response_model=list[WorkItemRead])
def list_work_items(
    session: Session = Depends(get_session),
    _member: Member = Depends(current_member),
) -> list[WorkItemRead]:
    """List work items (detail DTOs, each with its log + checklist)."""
    items = session.scalars(select(WorkItem).order_by(WorkItem.id)).all()
    return [_work_item_detail(session, wi) for wi in items]


@app.get("/work-items/{work_item_id}", response_model=WorkItemRead)
def get_work_item(
    work_item_id: int,
    session: Session = Depends(get_session),
    _member: Member = Depends(current_member),
) -> WorkItemRead:
    """Read one work item with its update log + checklist."""
    wi = _load_work_item(session, work_item_id)
    return _work_item_detail(session, wi)


@app.post(
    "/work-items/{work_item_id}/updates",
    response_model=WorkItemUpdateRead,
    status_code=201,
)
def append_update(
    work_item_id: int,
    payload: WorkItemUpdateCreate,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
) -> WorkItemUpdate:
    """Append a human update — the primary daily interaction (WORKITEM-2).

    Author is the authenticated member; source is 'human'. Appending also bumps
    the item's updated_at (activity signal). Each commit publishes via the seam.
    """
    wi = _load_work_item(session, work_item_id)
    now = datetime.now(UTC)
    upd = WorkItemUpdate(
        work_item_id=wi.id,
        author_id=member.id,
        source="human",
        body=payload.body,
        created_at=now,
    )
    wi.updated_at = now
    session.add(upd)
    session.commit()
    session.refresh(upd)
    return upd


# --- Board (read-only projection, Phase 3 checkpoint 5) ------------------

# Fixed column order (GROOM) — single source of truth in models. Display labels
# are a UI concern (app/web.py); these are the domain status codes.
BOARD_COLUMNS = list(WORK_ITEM_STATUSES)


def _board_columns(session: Session) -> dict[str, list[WorkItem]]:
    """Group non-archived work items into the 4 fixed columns, ordered."""
    columns: dict[str, list[WorkItem]] = {col: [] for col in BOARD_COLUMNS}
    items = session.scalars(
        select(WorkItem)
        .where(WorkItem.archived_at.is_(None))
        .order_by(WorkItem.position, WorkItem.id)
    ).all()
    for wi in items:
        if wi.status in columns:
            columns[wi.status].append(wi)
    return columns


@app.get("/board", response_model=dict[str, list[WorkItemRead]])
def get_board(
    session: Session = Depends(get_session),
    _member: Member = Depends(current_member),
) -> dict[str, list[WorkItemRead]]:
    """Read-only board: non-archived items grouped into the 4 fixed columns.

    Ordered within each column by ``position`` then ``id``. No archive/move
    actions here (GROOM is deferred); updates flow via the Phase 4 capture loop.
    """
    return {
        col: [_work_item_detail(session, wi) for wi in items]
        for col, items in _board_columns(session).items()
    }


# --- Thin HTMX front end (Phase 3 task 6) --------------------------------


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """The shell page: token entry + free-text capture + board container."""
    return SHELL_PAGE


@app.get("/board/view", response_class=HTMLResponse)
def board_view(
    session: Session = Depends(get_session),
    _member: Member = Depends(current_member),
) -> str:
    """Read-only board as an HTML fragment (HTMX swaps it; SSE triggers reload)."""
    return render_board(_board_columns(session))


@app.get("/calendar/view", response_class=HTMLResponse)
def calendar_view(
    session: Session = Depends(get_session),
    _member: Member = Depends(current_member),
) -> str:
    """Events as an HTML fragment — a skinny agenda list (task 11).

    Auth-protected; HTMX swaps it and an SSE change triggers reload, like the
    board. Ordered by start_at then start_date so timed and all-day events sort
    together into one readable list.
    """
    events = list(
        session.scalars(
            select(Event).order_by(Event.start_at, Event.start_date, Event.id)
        ).all()
    )
    return render_calendar(events)


# --- Capture with proposals (Phase 4, task 4) ----------------------------


def _to_proposal_read(
    action: ProposedAction, index: int, target_label: str | None
) -> ProposalRead:
    """Pure map: an engine ProposedAction -> the app's ProposalRead DTO.

    Assigns a batch-local proposal_id from ``index`` (unless the action already
    carries one) and derives ``action_summary`` from the registry (ground truth,
    NOT the model's text). No I/O — unit-testable in isolation.
    """
    return ProposalRead(
        name=action.name,
        params=action.params,
        action_summary=REGISTRY.describe(action.name, action.params),
        llm_rationale=action.llm_rationale,
        target_id=action.target_id,
        target_type=action.target_type,
        proposal_id=action.proposal_id or f"p{index}",
        target_ref=action.target_ref,
        target_label=target_label,
    )


def _propose_bounded(
    ctx: FocusedContext, target_label: str | None
) -> list[ProposalRead]:
    """Get proposals from the configured assistant (bounded; degrade to []) and
    map them to the app DTO.

    Orchestration only: the bounded-timeout + graceful-degrade wrapper is the
    engine's ``propose_bounded``; the per-action mapping is the pure
    :func:`_to_proposal_read`. ``target_label`` is echoed onto each proposal so
    the confirm card shows context.
    """
    timeout = float(os.environ.get("NTAKE_ASSISTANT_TIMEOUT", "4.0"))
    actions = propose_bounded(get_assistant(), ctx, timeout)
    return [
        _to_proposal_read(a, i, target_label) for i, a in enumerate(actions, start=1)
    ]


@app.post("/capture", response_model=CaptureResponse, status_code=201)
def capture_with_proposals(
    payload: CaptureCreate,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
) -> CaptureResponse:
    """Propose changes for a capture; apply nothing without Confirm (ASSIST-2).

    Two-stage, propose-only (v1): stage 1 ``focus()`` resolves the raw text into a
    FocusedContext (DB lookups → calendar window; no target resolved yet, so this
    is always a NEW capture); stage 2 ``propose()`` returns proposals. Nothing is
    persisted — the human confirms via /actions/confirm. Explicit note-append to
    an existing item is POST /work-items/{id}/updates, not here.
    """
    now = datetime.now(UTC)
    fam = session.get(Family, member.family_id)
    request = CaptureRequest(
        text=payload.text,
        timezone=fam.timezone if fam else "UTC",
        now=now,
    )
    ctx = get_capture_resolver().focus(request, session, member)
    proposals = _propose_bounded(ctx, target_label=None)
    return CaptureResponse(item=None, proposals=proposals)


@app.post("/actions/confirm")
def confirm_action(
    payload: ConfirmAction,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
) -> dict:
    """Apply a confirmed proposed action (propose-and-confirm; ASSIST-2).

    The client sends back the chosen action object (proposals aren't persisted).
    We validate + apply via the registry — which mutates AND appends a
    source=assistant update authored by the confirming member — then commit so
    the change publishes via the seam -> SSE. Dismiss needs no call. Invalid
    actions (unknown / missing params / bad target) -> 422.
    """
    try:
        summary = apply_action(
            session,
            member,
            payload.name,
            payload.target_id,
            payload.params,
            target_type=payload.target_type,
        )
    except ActionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    session.commit()  # one commit -> one seam publish -> SSE
    return {"applied": payload.name, "summary": summary}
