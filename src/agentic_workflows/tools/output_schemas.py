"""Pydantic output-schema validation for tool results.

Validates the *shape* of dicts returned by tool.execute() — complementary to
content_validator.py which checks *semantic* correctness (e.g. fibonacci values).

Usage (called from graph.py after tool.execute()):
    result = validate_tool_output(tool_name, result, tool_args)

Fail-open by default: schema mismatches log a warning and return the original
dict.  Set P1_TOOL_OUTPUT_SCHEMA_STRICT=1 to raise on mismatch.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schemas — write_file
# ---------------------------------------------------------------------------


class WriteFileSuccessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: str
    path: str


# ---------------------------------------------------------------------------
# Schemas — sort_array
# ---------------------------------------------------------------------------


class SortArraySuccessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sorted: list[Any]
    count: int
    order: str
    original: list[Any]


# ---------------------------------------------------------------------------
# Schemas — repeat_message (echo)
# ---------------------------------------------------------------------------


class EchoSuccessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    echo: str


# ---------------------------------------------------------------------------
# Schemas — math_stats
# ---------------------------------------------------------------------------


class MathStatsSuccessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: int | float


# ---------------------------------------------------------------------------
# Schemas — data_analysis (polymorphic by operation)
# ---------------------------------------------------------------------------


class DASummaryStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int
    sum: float
    mean: float
    median: float
    stdev: float
    min: float
    max: float
    range: float


class DAOutliers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outliers: list[float]
    non_outliers: list[float]
    q1: float
    q3: float
    iqr: float
    lower_bound: float
    upper_bound: float
    threshold: float


class DAPercentiles(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float


class DADistribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bins: list[dict[str, Any]]
    bin_width: float = 0.0  # single-value edge case omits bin_width


class DACorrelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correlation: float
    note: str = ""


class DANormalize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    normalized: list[float]


class DAZScores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    z_scores: list[float]


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

_SIMPLE_SCHEMAS: dict[str, type[BaseModel]] = {
    "write_file": WriteFileSuccessResult,
    "sort_array": SortArraySuccessResult,
    "repeat_message": EchoSuccessResult,
    "math_stats": MathStatsSuccessResult,
}

_POLYMORPHIC_SCHEMAS: dict[str, dict[str, type[BaseModel]]] = {
    "data_analysis": {
        "summary_stats": DASummaryStats,
        "outliers": DAOutliers,
        "percentiles": DAPercentiles,
        "distribution": DADistribution,
        "correlation": DACorrelation,
        "normalize": DANormalize,
        "z_scores": DAZScores,
    },
}

_strict_mode: bool | None = None


def _is_strict() -> bool:
    global _strict_mode  # noqa: PLW0603
    if _strict_mode is None:
        _strict_mode = os.getenv("P1_TOOL_OUTPUT_SCHEMA_STRICT", "0") == "1"
    return _strict_mode


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_tool_output(
    tool_name: str,
    result: dict[str, Any],
    tool_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and normalise a tool result dict against its registered schema.

    Returns the (possibly normalised) dict.  On mismatch: logs a warning and
    returns the original dict (fail-open), unless strict mode is enabled.
    """
    # Error results skip validation
    if "error" in result:
        return result

    # Simple-schema lookup
    schema_cls = _SIMPLE_SCHEMAS.get(tool_name)

    # Polymorphic lookup (data_analysis)
    if schema_cls is None and tool_name in _POLYMORPHIC_SCHEMAS:
        operation = (tool_args or {}).get("operation", "")
        schema_cls = _POLYMORPHIC_SCHEMAS[tool_name].get(operation)
        if schema_cls is None:
            # Unknown operation — pass through
            return result

    if schema_cls is None:
        # Unregistered tool — pass through
        return result

    try:
        validated = schema_cls.model_validate(result)
        return validated.model_dump()
    except Exception as exc:
        msg = f"Tool output schema mismatch for '{tool_name}': {exc}"
        if _is_strict():
            raise ValueError(msg) from exc
        logger.warning(msg)
        return result
