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
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.identity.tokens import generate_token, hash_token, token_secret
from app.persistence.models import DeviceToken, Event, Family, Member


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
    participants: list | None = None,
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
        participants=participants or [],
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

    # Idempotent: with a PERSISTENT DB, this runs on every `make ui-live` launch,
    # so it must NOT keep appending. If the family already has any events, do
    # nothing (a fresh DB has none, so a first run still seeds the samples).
    existing = session.scalars(
        select(Event).where(Event.family_id == family.id).limit(1)
    ).first()
    if existing is not None:
        return []

    now = datetime.now(UTC)

    # Members to attach as participants so the calendar + deep context have real
    # participant data (member_id links, resolved to names in the UI).
    members = session.scalars(
        select(Member).where(Member.family_id == family.id).order_by(Member.id)
    ).all()
    first = [{"member_id": members[0].id}] if members else []
    everyone = [{"member_id": m.id} for m in members]

    timed = seed_event(
        session,
        family.id,
        title="Sample: dentist",
        start_at=now.replace(microsecond=0),
        end_at=(now.replace(microsecond=0)),
        description="Seeded timed event for manual/display testing.",
        location="Downtown clinic",
        participants=first,
    )
    all_day = seed_event(
        session,
        family.id,
        title="Sample: school holiday",
        all_day=True,
        start_date=now.date(),
        participants=everyone,
    )
    return [timed, all_day]


def backup_db(session: Session, dest: Path | str) -> Path:
    """Write a consistent snapshot of the whole database to ``dest`` via
    ``VACUUM INTO`` (NFR-DURABILITY). Returns the destination path.

    ``VACUUM INTO`` produces a fresh, defragmented, self-contained copy in one
    statement — safe under WAL (it reads the live DB through ``session``'s
    connection, so committed data still in the WAL is included) and preferable to
    a raw file copy (which can catch a torn write). The result is a plain
    (non-WAL) single file suitable to move off-machine.

    Creates ``dest``'s parent directories if missing. The SQLite grammar wants a
    string *literal* for the path (no bind param), so the path is quoted with
    SQLite's ``''`` escaping. *Scheduling* (weekly) is a host concern (cron/
    systemd timer) and is intentionally not done here.
    """
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    # SQLite string-literal escaping: single quote -> two single quotes.
    literal = str(dest_path).replace("'", "''")
    session.execute(text(f"VACUUM INTO '{literal}'"))
    return dest_path


def _backup_dest(dest_arg: str | None) -> Path:
    """Resolve the backup destination: the given path, or a timestamped default."""
    if dest_arg:
        return Path(dest_arg)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path("backups") / f"ntake-{stamp}.db"


def run_llm_command(llm_command: str, config) -> tuple[int, str]:
    """Run an ``llm`` op (health/warm/status) over the configured model server.

    Pure-ish core (like the other ``manage`` helpers): takes the resolved config,
    returns ``(exit_code, message)`` — the CLI just prints + exits. Reads
    ``config.base_url`` / ``config.model``. Exit code is 0 when the endpoint is
    reachable-and-serving (health/status) or warmed (warm), else 1 — so a
    scripted host check can gate on it. Never raises (infra degrades internally).
    """
    from app.assistant.local_llm.infra import check_health, warm

    base_url, model = config.base_url, config.model

    if llm_command == "warm":
        ok = warm(base_url, model)
        return (
            (0, f"warm: ok (model {model!r} primed)")
            if ok
            else (
                1,
                f"warm: FAILED — no response from {base_url}",
            )
        )

    # health / status both probe health; status also warms.
    health = check_health(base_url, model)
    lines = [f"health: {'ok' if health.model_ok else 'NOT ok'} — {health.detail}"]
    code = 0 if health.model_ok else 1

    if llm_command == "status":
        if health.reachable:
            warmed = warm(base_url, model)
            lines.append(f"warm: {'ok' if warmed else 'FAILED'}")
            code = 0 if (health.model_ok and warmed) else 1
        else:
            lines.append("warm: skipped (endpoint unreachable)")
    return code, "\n".join(lines)


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

    b = sub.add_parser(
        "backup",
        help="Write a consistent DB snapshot (VACUUM INTO); schedule weekly on host",
    )
    b.add_argument(
        "--dest",
        default=None,
        help="Destination file (default: ./backups/ntake-YYYYMMDD-HHMMSS.db)",
    )

    sub.add_parser(
        "migrate",
        help="Run DB migrations to head (alembic upgrade head on CALENDAR_DB_URL)",
    )

    llm = sub.add_parser(
        "llm",
        help="Local LLM ops over an already-running server (health/warm/status)",
    )
    llm.add_argument(
        "llm_command",
        choices=["health", "warm", "status"],
        help="health: is the endpoint up + serving the model? "
        "warm: prime the model into memory. status: both.",
    )

    args = parser.parse_args(argv)

    # `migrate` is the schema path for the real DB — it must NOT go through
    # init_schema (create_all), which would create tables outside Alembic's
    # tracking. Handle it first, before the create_all + session setup below.
    if args.command == "migrate":
        from app.persistence.database import DB_URL
        from app.persistence.migrations import upgrade_to_head

        upgrade_to_head(DB_URL)
        print(f"Migrated {DB_URL} to head.")
        return 0

    # `llm` ops talk to the model server only — no DB. Handle before session setup.
    if args.command == "llm":
        from app.assistant.factory import default_assistant_config

        code, message = run_llm_command(args.llm_command, default_assistant_config())
        print(message)
        return code

    # Import here so tests that only exercise the core functions don't require
    # the app DB/env to import this module.
    from app.persistence.database import SessionLocal, engine, init_schema

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
            if not events:
                print("Sample events already present — nothing seeded (idempotent).")
            else:
                print(f"Seeded {len(events)} sample event(s):")
                for ev in events:
                    kind = "all-day" if ev.all_day else "timed"
                    print(f"    [{ev.id}] {ev.title} ({kind})")
        elif args.command == "backup":
            out = backup_db(session, _backup_dest(args.dest))
            print(f"Wrote snapshot: {out}")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
