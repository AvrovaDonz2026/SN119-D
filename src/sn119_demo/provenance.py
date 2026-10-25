"""Content hashes and lineage checks for SN119 dataset records.

The functions accept ordinary mappings as well as objects exposing attributes.  This
keeps the module independent of the evolving task schema while still producing stable,
JSON-serializable evidence for validators.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def canonical_json(value: Any) -> str:
    """Encode JSON deterministically for reproducible hashes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def content_hash(value: Any) -> str:
    """Hash text/bytes directly, or hash a canonical JSON representation."""
    if isinstance(value, bytes):
        return sha256_bytes(value)
    if isinstance(value, str):
        return sha256_text(value)
    return sha256_text(canonical_json(value))


@dataclass(frozen=True)
class ProvenanceRecord:
    record_id: str
    source_uri: str | None = None
    source_id: str | None = None
    license: str | None = None
    rights: str | None = None
    collected_at: str | None = None
    content_hash: str | None = None
    parent_hashes: tuple[str, ...] = ()
    transform_chain: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["parent_hashes"] = list(self.parent_hashes)
        result["transform_chain"] = list(self.transform_chain)
        result["metadata"] = dict(self.metadata)
        return result


def _as_provenance(record: Any) -> ProvenanceRecord:
    if isinstance(record, ProvenanceRecord):
        return record
    nested = _value(record, "provenance")
    lineage = _value(record, "lineage")
    parents = _value(record, "parent_hashes", _value(record, "parents", ())) or ()
    if not parents and lineage is not None:
        parents = _value(lineage, "parent_hashes", _value(lineage, "parent_ids", ())) or ()
    transforms = _value(record, "transform_chain", _value(record, "transforms", ())) or ()
    return ProvenanceRecord(
        record_id=str(_value(record, "record_id", _value(record, "id", "")) or ""),
        source_uri=_value(record, "source_uri", _value(record, "uri", _value(nested, "source_uri"))),
        source_id=_value(record, "source_id", _value(nested, "source")),
        license=_value(record, "license", _value(_value(record, "rights"), "license", _value(nested, "license"))),
        rights=_value(record, "rights_statement", _value(nested, "rights")),
        collected_at=_value(record, "collected_at", _value(record, "timestamp", _value(nested, "retrieved_at"))),
        content_hash=_value(record, "content_hash", _value(record, "hash")),
        parent_hashes=tuple(str(v) for v in parents),
        transform_chain=tuple(str(v) for v in transforms),
        metadata=_value(record, "metadata", {}) or {},
    )


def record_provenance(record: Any, content: Any = None, *, source_uri: str | None = None,
                      license: str | None = None, rights: str | None = None,
                      transform: str | None = None, parent_hashes: Iterable[str] = ()) -> dict[str, Any]:
    """Return a normalized provenance document and calculate its content hash."""
    base = _as_provenance(record).to_dict()
    if source_uri is not None:
        base["source_uri"] = source_uri
    if license is not None:
        base["license"] = license
    if rights is not None:
        base["rights"] = rights
    if content is not None:
        base["content_hash"] = content_hash(content)
    if parent_hashes:
        base["parent_hashes"] = list(parent_hashes)
    if transform:
        base.setdefault("transform_chain", []).append(transform)
    if not base.get("collected_at"):
        base["collected_at"] = datetime.now(timezone.utc).isoformat()
    return base


def verify_provenance(record: Any, content: Any = None) -> list[dict[str, Any]]:
    """Return structured provenance findings; an empty list means valid metadata."""
    item = _as_provenance(record)
    findings: list[dict[str, Any]] = []
    if not item.record_id:
        findings.append({"code": "provenance.missing_record_id", "severity": "error", "message": "record_id is required"})
    if not (item.source_uri or item.source_id):
        findings.append({"code": "provenance.missing_source", "severity": "error", "message": "source_uri or source_id is required", "record_id": item.record_id})
    if not item.content_hash:
        findings.append({"code": "provenance.missing_hash", "severity": "error", "message": "content_hash is required", "record_id": item.record_id})
    elif content is not None and item.content_hash != content_hash(content):
        findings.append({"code": "provenance.hash_mismatch", "severity": "error", "message": "content_hash does not match content", "record_id": item.record_id})
    if item.collected_at:
        try:
            datetime.fromisoformat(str(item.collected_at).replace("Z", "+00:00"))
        except ValueError:
            findings.append({"code": "provenance.invalid_timestamp", "severity": "error", "message": "collected_at is not ISO-8601", "record_id": item.record_id})
    return findings


def lineage_hash(parent_hashes: Sequence[str], transform_chain: Sequence[str] = ()) -> str:
    return content_hash({"parents": list(parent_hashes), "transforms": list(transform_chain)})


def verify_lineage(record: Any, known_hashes: Iterable[str] = ()) -> list[dict[str, Any]]:
    item = _as_provenance(record)
    known = set(known_hashes)
    findings: list[dict[str, Any]] = []
    for parent in item.parent_hashes:
        if len(parent) != 64 or any(c not in "0123456789abcdef" for c in parent.lower()):
            findings.append({"code": "lineage.invalid_parent_hash", "severity": "error", "message": "parent hash is not SHA-256", "record_id": item.record_id, "details": {"parent": parent}})
        elif known and parent not in known:
            findings.append({"code": "lineage.unknown_parent", "severity": "error", "message": "parent hash is not present in the supplied lineage", "record_id": item.record_id, "details": {"parent": parent}})
    if item.parent_hashes and not item.transform_chain:
        findings.append({"code": "lineage.missing_transform", "severity": "warning", "message": "derived record has parents but no transform_chain", "record_id": item.record_id})
    return findings


def serialize_provenance(value: Any) -> dict[str, Any]:
    """Convert a provenance object or finding collection to JSON-safe data."""
    if isinstance(value, ProvenanceRecord):
        return value.to_dict()
    if isinstance(value, Mapping):
        return json.loads(canonical_json(value))
    return json.loads(canonical_json(asdict(value)))


# Friendly aliases used by validators that call all gates ``check_*``.
check_provenance = verify_provenance
check_lineage = verify_lineage

