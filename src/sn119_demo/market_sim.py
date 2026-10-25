"""Deterministic, offline validator/miner market simulation."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping


def _get(x: Any, key: str, default: Any = None) -> Any:
    return x.get(key, default) if isinstance(x, Mapping) else getattr(x, key, default)


@dataclass(frozen=True)
class MarketConfig:
    validator_budget: float = 100.0
    miner_count: int = 8
    quality_gate: float = 0.60
    duplicate_rate_limit: float = 0.25
    base_cost: float = 1.0
    validator_fee_rate: float = 0.10
    seed: int = 119


@dataclass(frozen=True)
class MarketSimulation:
    strategy: str
    accepted: int
    submitted: int
    duplicates: int
    duplicate_rate: float
    total_cost: float
    validator_revenue: float
    miner_payout: float
    rejected: int
    budget_remaining: float
    quality_gate: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _quality(x: Any) -> float:
    value = _get(x, "quality", None)
    if value is None:
        value = _get(x, "score", _get(x, "accuracy", 0.0))
    if not isinstance(value, (int, float)):
        value = _get(value, "score", _get(value, "quality_score", None))
    if value is None:
        metadata = _get(x, "metadata", {}) or {}
        value = metadata.get("quality", metadata.get("score", 0.0)) if isinstance(metadata, Mapping) else 0.0
    return max(0.0, min(1.0, float(value)))


def _duplicate_key(x: Any) -> str:
    # Provenance is not a duplicate key: many valid records share one source.
    # Prefer a stable record identifier, then fall back to content for anonymous offers.
    for key in ("record_id", "id", "answer", "response", "content"):
        value = _get(x, key, None)
        if value is not None:
            return str(value).strip().casefold()
    return repr(x)


def simulate_market(candidates: Iterable[Any], strategy: str = "full_generation", config: MarketConfig | None = None) -> MarketSimulation:
    """Run one market round; candidates are ordered miner offers.

    Strategies: ``full_generation``, ``high_confidence``, ``provenance_first``,
    and ``quality_gated``.  Every accepted offer costs ``base_cost`` and gets
    the post-fee share of the validator budget, proportional to quality.
    """
    cfg = config or MarketConfig()
    if strategy not in {"full_generation", "high_confidence", "provenance_first", "quality_gated"}:
        raise ValueError(f"unknown strategy: {strategy}")
    submitted = 0
    seen: set[str] = set()
    accepted_rows: list[Any] = []
    duplicates = 0
    for offer in list(candidates)[: max(0, cfg.miner_count)]:
        confidence = _get(offer, "confidence", _get(_get(offer, "metadata", {}), "confidence", _quality(offer)))
        confidence = float(confidence if isinstance(confidence, (int, float)) else _quality(offer))
        provenance = _get(offer, "provenance_score", None)
        if provenance is None:
            provenance = _get(offer, "provenance", 0.0)
        if not isinstance(provenance, (int, float)):
            provenance = _get(provenance, "score", _get(provenance, "confidence", None))
            if provenance is None and _get(_get(offer, "provenance", None), "source", None):
                provenance = 1.0
            provenance = provenance or 0.0
        provenance = float(provenance)
        quality = _quality(offer)
        if strategy == "high_confidence" and confidence < 0.75:
            continue
        if strategy == "provenance_first" and provenance < 0.50:
            continue
        if strategy == "quality_gated" and quality < cfg.quality_gate:
            continue
        submitted += 1
        key = _duplicate_key(offer)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        if len(accepted_rows) * cfg.base_cost >= cfg.validator_budget:
            break
        accepted_rows.append(offer)
    accepted = len(accepted_rows)
    cost = accepted * cfg.base_cost
    duplicate_rate = duplicates / max(1, submitted)
    # The market's quality gate applies after duplicate filtering as well.
    gated = [x for x in accepted_rows if _quality(x) >= cfg.quality_gate]
    rejected = len(accepted_rows) - len(gated)
    accepted = len(gated)
    cost = accepted * cfg.base_cost
    fee = min(cfg.validator_budget, cost) * cfg.validator_fee_rate
    payout = max(0.0, min(cfg.validator_budget, cost) - fee)
    return MarketSimulation(strategy, accepted, submitted, duplicates, duplicate_rate, cost, fee, payout, rejected, max(0.0, cfg.validator_budget - cost), cfg.quality_gate)


def compare_strategies(candidates: Iterable[Any], config: MarketConfig | None = None) -> dict[str, dict[str, Any]]:
    """Evaluate all four strategy policies on the same frozen offer list."""
    rows = list(candidates)
    return {name: simulate_market(rows, name, config).as_dict() for name in ("full_generation", "high_confidence", "provenance_first", "quality_gated")}
