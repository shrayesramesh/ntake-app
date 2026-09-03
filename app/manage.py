"""Device-token management CLI (Phase 2, ACCESS — no admin UI).

Operator tool run on the home PC to enroll and revoke devices. Members come from
the config (seeded on startup); this mints per-device tokens for them.

    python -m app.manage gen-token "Shrayes" --label "Pixel phone"
    python -m app.manage list-tokens
    python -m app.manage revoke 3

gen-token prints the plaintext token ONCE — it is never stored or logged; only
its hash is persisted (DESIGN §2). Deliver the printed token to the device
(QR/paste/tailnet link — operator's choice).

Core functions take a Session so they are unit-testable; ``main`` wraps them and
uses the app's real DB + the per-install secret.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeviceToken, Member
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gen-token", help="Mint a device token for a member")
    g.add_argument("member", help="Member display name (from the family config)")
    g.add_argument("--label", required=True, help="Device label, e.g. 'Pixel phone'")

    r = sub.add_parser("revoke", help="Revoke a device token by id")
    r.add_argument("token_id", type=int)

    sub.add_parser("list-tokens", help="List device tokens and their status")

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
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
