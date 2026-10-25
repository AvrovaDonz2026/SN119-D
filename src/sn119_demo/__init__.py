"""SN119 demo pipeline.

The package intentionally uses only the Python standard library so it can be
run in a clean environment while the optional pipeline stages are developed.
"""

__version__ = "0.1.0"

try:
    from .schema import (
        EvaluationLeakage, Lineage, Privacy, Provenance, QualityFlags, Rights,
        TaskRecord,
    )
except ImportError:
    # Schema is an optional parallel stage during incremental checkouts.
    __all__ = []
else:
    __all__ = [
        "EvaluationLeakage", "Lineage", "Privacy", "Provenance",
        "QualityFlags", "Rights", "TaskRecord",
    ]

from .evaluator import EvaluationReport, FrozenBaselineEvaluator, evaluate
from .market_sim import MarketConfig, MarketSimulation, compare_strategies, simulate_market

__all__ = [*__all__, "EvaluationReport", "FrozenBaselineEvaluator", "evaluate",
           "MarketConfig", "MarketSimulation", "compare_strategies", "simulate_market"]

