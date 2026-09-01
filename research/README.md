# LLD Research & Decisions

> **⚠ HISTORICAL — reasoning trail, not current truth.** These notes capture
> *how* decisions were reached. Some contain **superseded** detail (pre-reframe
> schemas, old `todo`/`TODO-*` naming, pre-simplification event fields). The
> **authoritative, current source of truth is [`../spec/`](../spec/)** — build
> from `spec/`, use these only to understand *why*.

This folder holds **lower-level-design (LLD) research and decisions** made while
the design was being worked out.

## Conventions

- One topic per file: `NN-topic.md` (numeric prefix = rough chronological order).
- Each note states up front whether it is **research** (findings, options, no
  commitment) or a **decision** (chosen, with rationale).
- Reference HLD requirement/design IDs (`F-*`, `NFR-*`, DESIGN §x) rather than
  restating them.

## Index

- `01-tailscale-vs-lan.md` — why Tailscale rather than plain same-WiFi LAN
  (research).
- `02-tailscale-setup-and-test.md` — account/device setup + widening-circle test
  guide; naming guidance (reference / execution guide for checkpoint 1f).
- `03-stack-libraries.md` — pinned library baseline (FastAPI/pytest/SSE/
  SQLAlchemy) + SQLModel-vs-SQLAlchemy note (research/reference for Phase 0/1).
- `04-data-layer.md` — **decision:** SQLAlchemy 2.0 ORM (not SQLModel) +
  Core escape hatch; SQLAlchemy models + Pydantic DTOs (no dataclasses); table →
  ORM model mapping for DESIGN §4.
- `05-dashboard-hardware.md` — **staged decision:** prototype the wall display on
  the existing iPad, upgrade to a larger (24–27") display later; size analysis +
  the open-Android/firmware landmine for smart-calendar devices.
- `06-todo-updatelog-llm.md` — **reframe (supersedes todo parts of `04`):** todos
  as free-text item + append-only update log; labor-visibility purpose (R4);
  inline propose-and-confirm LLM; `due_at` inferred; no suggestions table.
