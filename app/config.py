"""Family config: load the out-of-repo TOML and seed it into the DB (Phase 2).

The real config lives outside the repo (default ``~/.config/ntake/family.toml``,
overridable via ``NTAKE_CONFIG``) so family PII is never committed to this public
repo. It holds the household + members only — **no token secrets** (tokens are
minted by the manage CLI). On startup the app seeds these rows so the members
table is populated (option B), keeping the Phase 3 ``author`` FK valid.

Loading and seeding are pure functions (path/dict in) so tests need no external
dir and no env var; only the app resolves the default path via ``config_path()``.
"""

from __future__ import annotations

import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import Family, Member


class MemberConfig(BaseModel):
    display_name: str
    role: Literal["adult", "child"]
    phone_number: str | None = None


class FamilyMeta(BaseModel):
    name: str
    timezone: str


class FamilyConfig(BaseModel):
    family: FamilyMeta
    members: list[MemberConfig]


def config_path() -> Path:
    """Resolve the config file path: ``NTAKE_CONFIG`` env, else the default.

    Default is the user config dir so the real (PII-bearing) file lives outside
    this repo. Tests pass a path directly and do not rely on this.
    """
    override = os.environ.get("NTAKE_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".config" / "ntake" / "family.toml"


def load_config(path: Path) -> FamilyConfig:
    """Parse + validate the TOML config. Pure: path in, validated model out."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    try:
        return FamilyConfig.model_validate(data)
    except ValidationError as e:
        # Surface as ValueError so callers/tests need not import pydantic.
        raise ValueError(f"Invalid family config at {path}: {e}") from e


def seed_from_config(session: Session, cfg: FamilyConfig) -> Family:
    """Idempotently upsert the family + members from config into the DB.

    Matches the family by name and members by (family_id, display_name), so
    repeated startups don't duplicate and adding a member to the config on a
    later run simply inserts the new one.
    """
    now = datetime.now(UTC)

    family = session.scalar(select(Family).where(Family.name == cfg.family.name))
    if family is None:
        family = Family(name=cfg.family.name, timezone=cfg.family.timezone)
        session.add(family)
        session.flush()  # assign family.id for member FKs
    else:
        family.timezone = cfg.family.timezone

    for mc in cfg.members:
        existing = session.scalar(
            select(Member).where(
                Member.family_id == family.id,
                Member.display_name == mc.display_name,
            )
        )
        if existing is None:
            session.add(
                Member(
                    family_id=family.id,
                    display_name=mc.display_name,
                    role=mc.role,
                    phone_number=mc.phone_number,
                    created_at=now,
                )
            )
        else:
            existing.role = mc.role
            existing.phone_number = mc.phone_number

    session.commit()
    return family
