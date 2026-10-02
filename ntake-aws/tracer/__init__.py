"""⚠️ THROWAWAY TRACER-BULLET SCAFFOLDING (AWS_PLAN Part II, Session 1.5). ⚠️

This whole package is a **walking skeleton**, not the real application. It exists
only to de-risk the three cloud-only assumptions local tests structurally cannot
prove, *before* Sessions 2-7 build on them (AWS_HLD §11, AWS_LLD §8):

  1. IAM        — a per-Lambda scoped role actually works end-to-end (no AccessDenied).
  2. Bedrock    — one real Converse **tool-use** call: response shape, whether one
                  turn returns multiple ``toolUse`` blocks (AWS_LLD §3.5), and
                  enum-over-whitelist adherence.
  3. WebSocket  — the API-GW → authorizer → ``$connect`` → hard-coded post-back loop.

None of this is the real handler/repository/Bedrock design. It is **deleted or
replaced** as the real sessions land (Session 5 builds the real stack into the
empty ``NtakeStack``; this ``tracer/`` package and its ``TracerStack`` go away).

The ONE non-throwaway thing it exercises is the lifted ``core.tokens.hash_token``
in the authorizer — that import is the real token-hashing path (AWS_LLD §5.1),
validated here so the authorizer→member resolution is proven on the deployed
slice.

Do NOT build on anything in here. See ``infra/lib/tracer-stack.ts`` for the CDK.
"""

from __future__ import annotations
