"""Typed synthetic benchmark and prompt-variant data for the external tool."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Stage = Literal["link", "propose"]


class WorldEntity(BaseModel):
    """One synthetic entity used to ground IDs in an authored case."""

    id: int
    name: str | None = None
    title: str | None = None
    role: str | None = None


class SyntheticWorld(BaseModel):
    """Minimal ID-bearing fictional world supplied by an authoring agent."""

    members: list[WorldEntity] = Field(default_factory=list)
    work_items: list[WorldEntity] = Field(default_factory=list)
    events: list[WorldEntity] = Field(default_factory=list)


class LinkLabels(BaseModel):
    """Expected or forbidden LINK output IDs."""

    work_item_ids: list[int] = Field(default_factory=list)
    event_ids: list[int] = Field(default_factory=list)
    member_ids: list[int] = Field(default_factory=list)


class ActionCall(BaseModel):
    """An id-free model action envelope used by the PROPOSE prompt."""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class PromptCase(BaseModel):
    """One complete synthetic LINK or PROPOSE prompt benchmark case."""

    case_id: str
    stage: Stage
    tags: list[str] = Field(default_factory=list)
    timezone: str
    now: datetime
    capture_author: str
    world: SyntheticWorld
    world_view: str
    deep_context: str
    capture: str
    required_links: LinkLabels = Field(default_factory=LinkLabels)
    forbidden_links: LinkLabels = Field(default_factory=LinkLabels)
    required_actions: list[ActionCall] = Field(default_factory=list)
    forbidden_actions: list[ActionCall] = Field(default_factory=list)


class BenchmarkManifest(BaseModel):
    """Stable metadata describing one imported, reusable benchmark directory."""

    benchmark_id: str
    stages: list[Stage]
    case_count: int
    validation_count: int
    registry_hash: str
    train_hash: str
    validate_hash: str
    source_hash: str
    schema_version: int = 1


class Variant(BaseModel):
    """One full replacement template for a single prompt stage."""

    name: str
    stage: Stage
    template: str | None = None
    rationale: str = ""
    expected_tags_to_improve: list[str] = Field(default_factory=list)


class VariantSet(BaseModel):
    """Control plus stage-scoped candidate templates supplied by an author."""

    stage: Stage
    variants: list[Variant]


class Score(BaseModel):
    """Deterministic score for one case or aggregate."""

    required_recall: float
    forbidden_precision: float
    unexpected: list[str] = Field(default_factory=list)
