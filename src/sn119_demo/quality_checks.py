"""Deterministic quality gates for dataset patches and evaluation inputs."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .provenance import content_hash, verify_lineage, verify_provenance


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _record_id(item: Any, index: int) -> str:
    return str(_get(item, "record_id", _get(item, "id", index)))


def _text(item: Any) -> str:
    for key in ("text", "content", "task", "prompt", "input", "document", "response", "answer", "output"):
        value = _get(item, key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    record_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["details"] = dict(self.details)
        return result


@dataclass
class QualityResult:
    passed: bool
    findings: list[Finding] = field(default_factory=list)
    checked: int = 0
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checked": self.checked,
                "findings": [f.to_dict() for f in self.findings], "stats": dict(self.stats)}

    def __bool__(self) -> bool:
        return self.passed


def _finding(raw: Mapping[str, Any]) -> Finding:
    return Finding(str(raw["code"]), str(raw.get("severity", "error")), str(raw.get("message", "")),
                   raw.get("record_id"), raw.get("details", {}))


def check_rights(records: Iterable[Any], *, allowed_licenses: Iterable[str] | None = None) -> list[Finding]:
    allowed = {str(x).lower() for x in allowed_licenses} if allowed_licenses is not None else None
    findings: list[Finding] = []
    for index, item in enumerate(records):
        rid = _record_id(item, index)
        license_name = _get(item, "license") or _get(item, "license_id")
        rights = _get(item, "rights") or _get(item, "rights_statement")
        if not license_name and not rights:
            findings.append(Finding("rights.missing", "error", "license or rights statement is required", rid))
        elif allowed is not None and license_name and str(license_name).lower() not in allowed:
            findings.append(Finding("rights.disallowed_license", "error", "license is not allowed", rid, {"license": license_name}))
    return findings


_PII_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "phone": re.compile(r"(?<!\d)(?:\+?\d[\d .()\-]{7,}\d)(?!\d)"),
    "secret": re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})\b"),
}


def check_privacy(records: Iterable[Any]) -> list[Finding]:
    findings: list[Finding] = []
    for index, item in enumerate(records):
        rid, text = _record_id(item, index), _text(item)
        for name, pattern in _PII_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                findings.append(Finding("privacy.pii_detected", "error", f"possible {name} value in record", rid, {"type": name, "count": len(matches)}))
    return findings


def check_duplicates(records: Sequence[Any]) -> list[Finding]:
    findings: list[Finding] = []
    seen: dict[str, str] = {}
    for index, item in enumerate(records):
        rid, text = _record_id(item, index), " ".join(_text(item).casefold().split())
        if not text:
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen:
            findings.append(Finding("duplicate.exact", "error", "record duplicates an earlier record", rid, {"duplicate_of": seen[digest], "hash": digest}))
        else:
            seen[digest] = rid
    return findings


def check_contamination(records: Iterable[Any], *, contamination_terms: Iterable[str] = (), source_terms: Iterable[str] = ()) -> list[Finding]:
    terms = [str(x).strip().casefold() for x in [*contamination_terms, *source_terms] if str(x).strip()]
    findings: list[Finding] = []
    for index, item in enumerate(records):
        text = _text(item).casefold()
        hits = sorted({term for term in terms if term in text})
        if hits:
            findings.append(Finding("contamination.match", "error", "record contains a known contamination marker", _record_id(item, index), {"matches": hits}))
    return findings


def check_evaluation_leakage(records: Iterable[Any], *, evaluation_ids: Iterable[str] = (), evaluation_questions: Iterable[str] = ()) -> list[Finding]:
    ids = {str(x).casefold() for x in evaluation_ids}
    questions = {" ".join(str(x).casefold().split()) for x in evaluation_questions if str(x).strip()}
    findings: list[Finding] = []
    for index, item in enumerate(records):
        rid, text = _record_id(item, index), " ".join(_text(item).casefold().split())
        if rid.casefold() in ids or text in questions:
            findings.append(Finding("evaluation.leakage", "error", "record matches an evaluation item", rid))
    return findings


def check_empty_truncated(records: Iterable[Any], *, min_chars: int = 1) -> list[Finding]:
    findings: list[Finding] = []
    markers = ("[truncated]", "<truncated>", "...", "…")
    for index, item in enumerate(records):
        rid, text = _record_id(item, index), _text(item)
        if len(text) < min_chars:
            findings.append(Finding("content.empty", "error", "record has no usable content", rid, {"length": len(text)}))
        elif text.casefold().endswith(markers):
            findings.append(Finding("content.truncated", "error", "record appears truncated", rid))
    return findings


def run_quality_checks(records: Iterable[Any], *, allowed_licenses: Iterable[str] | None = None,
                       contamination_terms: Iterable[str] = (), source_terms: Iterable[str] = (),
                       evaluation_ids: Iterable[str] = (), evaluation_questions: Iterable[str] = (),
                       min_chars: int = 1, require_provenance: bool = True) -> QualityResult:
    materialized = list(records)
    findings: list[Finding] = []
    findings.extend(check_rights(materialized, allowed_licenses=allowed_licenses))
    findings.extend(check_privacy(materialized))
    findings.extend(check_duplicates(materialized))
    findings.extend(check_contamination(materialized, contamination_terms=contamination_terms, source_terms=source_terms))
    findings.extend(check_evaluation_leakage(materialized, evaluation_ids=evaluation_ids, evaluation_questions=evaluation_questions))
    findings.extend(check_empty_truncated(materialized, min_chars=min_chars))
    if require_provenance:
        hashes = {_get(item, "content_hash") for item in materialized if _get(item, "content_hash")}
        for item in materialized:
            rid = _record_id(item, materialized.index(item))
            findings.extend(_finding(x) for x in verify_provenance(item, _text(item)))
            findings.extend(_finding(x) for x in verify_lineage(item, hashes))
    error_count = sum(f.severity == "error" for f in findings)
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return QualityResult(not error_count, findings, len(materialized), {"errors": error_count, "warnings": len(findings) - error_count, "by_code": counts})


def serialize_result(result: QualityResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(result, QualityResult):
        return result.to_dict()
    return json.loads(json.dumps(result, ensure_ascii=False, default=str))

