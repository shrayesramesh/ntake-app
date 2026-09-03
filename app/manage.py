"""Device-token management CLI (Phase 2, ACCESS — no admin UI).

Operator tool run on the home PC to enroll and revoke devices. Members come from
the config (seeded on startup); this mints per-device tokens for them.

    python -m app.manage gen-token "Shrayes" --label "Pixel phone"
    python -m app.manage list-tokens
    python -m app.manage revoke 3
    python -m app.manage seed-events

gen-token prints the plaintext token ONCE — it is never stored or logged; only
its hash is persisted (DESIGN §2). Deliver the printed token to the device
(QR/paste/tailnet link — operator's choice).

``seed-events`` populates the calendar with a couple of sample events (one timed,
one all-day) for manual/display testing — the only non-assistant way to create
events (there is deliberately no human event-CRUD UI; events arrive via the
assistant or this seed path). See ``seed_event`` for the reusable helper the
tests + fixtures also use.

Core functions take a Session so they are unit-testable; ``main`` wraps them and
uses the app's real DB + the per-install secret.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeviceToken, Event, Family, Member
from app.tokens import generate_token, hash_token, token_secret


def gen_token_for(
    session: Session, member_name: str, *, label: str, secret: str
) -> str:
    """Mint a device token for the named member; store its hash, return plaintext.

    Raises ValueError if no member matches ``member_name``.
    """
    member = session.scalar(select(Member).where(Member.display_name == member_name))
    if member is None:
        raise ValueError(f"No member named {member_name!r}. Check the family config.")

    token = generate_token()
    session.add(
        DeviceToken(
            member_id=member.id,
            token_hash=hash_token(token, secret=secret),
            label=label,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()
    return token


def revoke_token(session: Session, token_id: int) -> None:
    """Revoke a device token by id (sets revoked_at). No-op if already revoked."""
    dt = session.get(DeviceToken, token_id)
    if dt is None:
        raise ValueError(f"No device token with id {token_id}.")
    if dt.revoked_at is None:
        dt.revoked_at = datetime.now(UTC)
        session.commit()


def list_tokens(session: Session) -> list[dict]:
    """List device tokens with status — never the hash or plaintext."""
    rows: list[dict] = []
    stmt = select(DeviceToken).order_by(DeviceToken.id)
    for dt in session.scalars(stmt):
        member = session.get(Member, dt.member_id)
        rows.append(
            {
                "id": dt.id,
                "member": member.display_name if member else "(removed)",
                "label": dt.label,
                "active": dt.revoked_at is None,
            }
        )
    return rows


def seed_event(
    session: Session,
    family_id: int,
    *,
    title: str,
    all_day: bool = False,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    description: str | None = None,
    location: str | None = None,
) -> Event:
    """Create + commit an Event directly (no assistant), returning it.

    The only non-assistant way to create events: used by the ``seed-events`` CLI,
    the pytest fixtures, and the host smoke to populate the calendar for manual
    testing. Enforces the event timing invariant (DESIGN §3.1): exactly one
    timing pair keyed by ``all_day`` —

    * **timed** (``all_day=False``): requires ``start_at`` (UTC); ``end_at``
      defaults to ``start_at`` (a point-in-time event).
    * **all-day** (``all_day=True``): requires ``start_date``; ``end_date``
      defaults to ``start_date`` (a single-day event).

    Raises ValueError if the required timing for the chosen mode is missing.
    """
    if all_day:
        if start_date is None:
            raise ValueError("all-day event requires start_date")
        end_date = end_date or start_date
        start_at = end_at = None
    else:
        if start_at is None:
            raise ValueError("timed event requires start_at")
        end_at = end_at or start_at
        start_date = end_date = None

    now = datetime.now(UTC)
    ev = Event(
        family_id=family_id,
        title=title,
        description=description,
        location=location,
        all_day=all_day,
        start_at=start_at,
        end_at=end_at,
        start_date=start_date,
        end_date=end_date,
        created_at=now,
        updated_at=now,
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def seed_sample_events(session: Session) -> list[Event]:
    """Populate the first family with a sample timed + all-day event.

    The CLI/smoke seed path (task 9). Deterministic sample data so a fresh
    install has something on the calendar to look at. Raises ValueError if no
    family exists yet (identity is config-seeded on startup — DESIGN §2).
    """
    family = session.scalars(select(Family).order_by(Family.id)).first()
    if family is None:
        raise ValueError("No family found. Seed the family config first (startup).")

    now = datetime.now(UTC)
    timed = seed_event(
        session,
        family.id,
        title="Sample: dentist",
        start_at=now.replace(microsecond=0),
        end_at=(now.replace(microsecond=0)),
        description="Seeded timed event for manual/display testing.",
        location="Downtown clinic",
    )
    all_day = seed_event(
        session,
        family.id,
        title="Sample: school holiday",
        all_day=True,
        start_date=now.date(),
    )
    return [timed, all_day]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gen-token", help="Mint a device token for a member")
    g.add_argument("member", help="Member display name (from the family config)")
    g.add_argument("--label", required=True, help="Device label, e.g. 'Pixel phone'")

    r = sub.add_parser("revoke", help="Revoke a device token by id")
    r.add_argument("token_id", type=int)

    sub.add_parser("list-tokens", help="List device tokens and their status")

    sub.add_parser(
        "seed-events", help="Populate the calendar with sample events (dev/manual)"
    )

    args = parser.parse_args(argv)

    # Import here so tests that only exercise the core functions don't require
    # the app DB/env to import this module.
    from app.db import SessionLocal, engine, init_schema

    init_schema(engine)
    session = SessionLocal()
    try:
        if args.command == "gen-token":
            token = gen_token_for(
                session, args.member, label=args.label, secret=token_secret()
            )
            print("Device token (shown once — store it now):\n")
            print(f"    {token}\n")
            print(f"Enrolled '{args.member}' device '{args.label}'.")
        elif args.command == "revoke":
            revoke_token(session, args.token_id)
            print(f"Revoked token {args.token_id}.")
        elif args.command == "list-tokens":
            for row in list_tokens(session):
                status = "active" if row["active"] else "revoked"
                line = "[{:>3}] {:<20} {:<24} {}".format(
                    row["id"], row["member"], row["label"], status
                )
                print(line)
        elif args.command == "seed-events":
            events = seed_sample_events(session)
            print(f"Seeded {len(events)} sample event(s):")
            for ev in events:
                kind = "all-day" if ev.all_day else "timed"
                print(f"    [{ev.id}] {ev.title} ({kind})")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
