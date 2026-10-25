"""Dataclasses and JSON conversion helpers for SN119 patch records.

The schema deliberately uses only JSON-compatible scalar values and lists so a
record can be stored as one JSONL line without a custom serializer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Provenance:
    """Where a record came from, including a stable source version."""

    source: str
    source_uri: str | None = None
    source_revision: str | None = None
    retrieved_at: str | None = None
    author: str | None = None


@dataclass(frozen=True)
class Rights:
    """Usage rights and attribution requirements for the source material."""

    license: str = "unknown"
    attribution_required: bool = False
    permitted_use: str = "unknown"
    notes: str | None = None


@dataclass(frozen=True)
class Privacy:
    """Privacy review status for a record."""

    pii_present: bool = False
    pii_types: tuple[str, ...] = ()
    redacted: bool = False
    review_status: str = "unreviewed"

    def __post_init__(self) -> None:
        object.__setattr__(self, "pii_types", tuple(self.pii_types))


@dataclass(frozen=True)
class Lineage:
    """Processing history for the current record."""

    parent_ids: tuple[str, ...] = ()
    transform: str = "source"
    generated_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent_ids", tuple(self.parent_ids))


@dataclass(frozen=True)
class EvaluationLeakage:
    """Potential overlap between training material and evaluation data."""

    suspected: bool = False
    match_type: str | None = None
    matched_record_ids: tuple[str, ...] = ()
    evidence: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched_record_ids", tuple(self.matched_record_ids))


@dataclass(frozen=True)
class QualityFlags:
    """Flags used by the patch planner and downstream review."""

    duplicate: bool = False
    contamination: bool = False
    evaluation_leakage: EvaluationLeakage = field(default_factory=EvaluationLeakage)
    needs_review: bool = False
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "notes", tuple(self.notes))


@dataclass(frozen=True)
class TaskRecord:
    """Canonical SN119 item consumed by the patch generator."""

    record_id: str
    task: str
    answer: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=lambda: Provenance(source="unknown"))
    rights: Rights = field(default_factory=Rights)
    privacy: Privacy = field(default_factory=Privacy)
    lineage: Lineage = field(default_factory=Lineage)
    quality: QualityFlags = field(default_factory=QualityFlags)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation with tuple fields as lists."""
        result = asdict(self)
        result["metadata"] = dict(self.metadata)
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskRecord":
        """Build a record from a JSON object, accepting omitted optional fields."""
        provenance_value = dict(value.get("provenance") or {})
        provenance = Provenance(source=str(provenance_value.pop("source", "unknown")), **provenance_value)
        rights = Rights(**dict(value.get("rights") or {}))
        privacy = Privacy(**dict(value.get("privacy") or {}))
        lineage = Lineage(**dict(value.get("lineage") or {}))
        quality_value = dict(value.get("quality") or {})
        leakage = EvaluationLeakage(**dict(quality_value.pop("evaluation_leakage", {}) or {}))
        quality = QualityFlags(evaluation_leakage=leakage, **quality_value)
        return cls(
            record_id=str(value["record_id"]),
            task=str(value["task"]),
            answer=value.get("answer"),
            metadata=dict(value.get("metadata") or {}),
            provenance=provenance,
            rights=rights,
            privacy=privacy,
            lineage=lineage,
            quality=quality,
        )
