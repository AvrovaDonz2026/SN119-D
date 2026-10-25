"""Deterministic JSONL patch generation for SN119 records."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .schema import TaskRecord


@dataclass(frozen=True)
class PatchOperation:
    """One operation in a patch manifest."""

    op: str
    record_id: str
    record: dict | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}


def read_jsonl(path: str | Path) -> Iterator[TaskRecord]:
    """Read non-empty JSONL lines as ``TaskRecord`` objects."""
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number} of {path}") from exc
            if not isinstance(value, Mapping):
                raise ValueError(f"line {line_number} of {path} is not a JSON object")
            yield TaskRecord.from_dict(value)


def _canonical_record(record: TaskRecord) -> str:
    return json.dumps(record.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def record_fingerprint(record: TaskRecord) -> str:
    """Return a stable SHA-256 fingerprint for a canonical record."""
    return hashlib.sha256(_canonical_record(record).encode("utf-8")).hexdigest()


def generate_patch(
    records: Iterable[TaskRecord],
    *,
    baseline: Mapping[str, TaskRecord] | None = None,
) -> list[PatchOperation]:
    """Create stable add/update/skip operations sorted by record id.

    Duplicate IDs in the input are marked as skips. A baseline with an equal
    canonical record produces a skip; changed records produce an update.
    Records flagged for contamination or evaluation leakage are also skipped,
    preserving their reason for a reviewer.
    """
    baseline = baseline or {}
    seen: set[str] = set()
    operations: list[PatchOperation] = []
    for record in sorted(records, key=lambda item: item.record_id):
        if record.record_id in seen:
            operations.append(PatchOperation("skip", record.record_id, reason="duplicate_input_id"))
            continue
        seen.add(record.record_id)
        if record.quality.duplicate:
            operations.append(PatchOperation("skip", record.record_id, reason="duplicate"))
            continue
        if record.quality.contamination:
            operations.append(PatchOperation("skip", record.record_id, reason="contamination"))
            continue
        if record.quality.evaluation_leakage.suspected:
            operations.append(PatchOperation("skip", record.record_id, reason="evaluation_leakage"))
            continue
        old = baseline.get(record.record_id)
        if old is not None and _canonical_record(old) == _canonical_record(record):
            operations.append(PatchOperation("skip", record.record_id, reason="unchanged"))
        elif old is None:
            operations.append(PatchOperation("add", record.record_id, record=record.to_dict()))
        else:
            operations.append(PatchOperation("update", record.record_id, record=record.to_dict()))
    return operations


def write_patch(path: str | Path, operations: Iterable[PatchOperation]) -> None:
    """Write a deterministic patch JSONL file."""
    with Path(path).open("w", encoding="utf-8") as handle:
        for operation in operations:
            handle.write(json.dumps(operation.to_dict(), ensure_ascii=True, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="input JSONL file")
    parser.add_argument("output", type=Path, help="output patch JSONL file")
    args = parser.parse_args(argv)
    write_patch(args.output, generate_patch(read_jsonl(args.input)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
