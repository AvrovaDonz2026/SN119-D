"""Command line entry point for the SN119 offline demo pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .evaluator import evaluate as evaluate_records
from .market_sim import MarketConfig, compare_strategies
from .patch_generator import generate_patch
from .quality_checks import run_quality_checks
from .schema import TaskRecord


STAGES = ("seed", "generate", "validate", "evaluate", "simulate", "report")


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _read(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _seed_rows(count: int) -> list[dict[str, Any]]:
    path = _repo_root() / "data" / "seed_tasks.jsonl"
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows[: max(0, count)]


def _records(value: Any) -> list[TaskRecord]:
    return [TaskRecord.from_dict(row) for row in value if isinstance(row, dict)]


def _candidate_rows(records: list[TaskRecord]) -> list[dict[str, Any]]:
    """Expose quality/provenance scores used by the offline market model."""
    rows: list[dict[str, Any]] = []
    for record in records:
        row = record.to_dict()
        row["reference"] = record.answer or ""
        row["reasoning"] = record.task
        row["confidence"] = 0.85 if not record.quality.needs_review else 0.45
        row["provenance_score"] = 1.0 if record.provenance.source else 0.0
        row["quality"] = 0.9 if not record.quality.needs_review else 0.35
        rows.append(row)
    return rows


def run_pipeline(command: str, reports_dir: Path, *, seed: int = 119, count: int = 8) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    prior: dict[str, Any] = {"seed": seed, "count": count}
    if command == "report":
        files = sorted(reports_dir.glob("*.json"))
        data = {f.stem: _read(f, {}) for f in files if f.stem != "report"}
        result = {"stages": data, "offline": True, "disclaimer": "Offline simulation; not real TAO earnings."}
        _write(reports_dir / "report.json", result)
        return result
    order = STAGES[: STAGES.index(command) + 1]
    for stage in order:
        existing = _read(reports_dir / f"{stage}.json")
        if stage != command and existing is not None and not (command == "generate" and stage == "seed"):
            prior.update(existing)
            continue
        if stage == "seed":
            result = {"seed": seed, "count": count, "rows": _seed_rows(count), "offline": True}
        elif stage == "generate":
            seed_report = _read(reports_dir / "seed.json", {}) or {}
            records = _records(seed_report.get("rows", []))
            operations = generate_patch(records)
            accepted = [op["record"] for op in (operation.to_dict() for operation in operations) if op.get("record")]
            result = {"records": accepted, "patch": [operation.to_dict() for operation in operations], "offline": True}
        elif stage == "validate":
            generated = _read(reports_dir / "generate.json", {}) or {}
            records = generated.get("records", [])
            quality = run_quality_checks(records, require_provenance=False)
            result = quality.to_dict()
            valid = quality.passed and bool(records)
            if not records:
                result["findings"].append({"code": "dataset.empty", "severity": "error", "message": "patch contains no accepted records"})
                result["stats"]["errors"] = int(result["stats"].get("errors", 0)) + 1
            result.update({"valid": valid, "quality_gate": "pass" if valid else "fail", "offline": True})
        elif stage == "evaluate":
            generated = _read(reports_dir / "generate.json", {}) or {}
            candidates = _candidate_rows(_records(generated.get("records", [])))
            result = evaluate_records(candidates)
            result.update({"offline": True, "candidate_count": len(candidates)})
        elif stage == "simulate":
            generated = _read(reports_dir / "generate.json", {}) or {}
            candidates = _candidate_rows(_records(generated.get("records", [])))
            result = {"strategies": compare_strategies(candidates, MarketConfig(seed=seed)), "offline": True,
                      "disclaimer": "Offline simulation; not real TAO earnings."}
        _write(reports_dir / f"{stage}.json", result)
        prior.update(result)
    return prior


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sn119-demo", description="SN119 offline demo pipeline")
    parser.add_argument("command", choices=STAGES, help="pipeline stage to run")
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"), help="directory for JSON reports")
    parser.add_argument("--seed", type=int, default=119)
    parser.add_argument("--count", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_pipeline(args.command, args.reports_dir, seed=args.seed, count=args.count)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    sys.exit(main())

