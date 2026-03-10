from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agentic_workflows.tools.base import Tool

_ISO_OUT = "%Y-%m-%dT%H:%M:%S"
_PARSE_FMTS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_VALID_OPS = {
    "now", "parse", "format", "add", "subtract",
    "diff", "weekday", "to_timestamp", "from_timestamp",
}


class DateTimeOpsTool(Tool):
    name = "datetime_ops"
    _args_schema = {
        "operation": {"type": "string", "required": "true"},
        "dt": {"type": "string"},
        "dt2": {"type": "string"},
        "fmt": {"type": "string"},
        "amount": {"type": "number"},
        "unit": {"type": "string"},
    }
    description = (
        "Temporal operations: now, parse, format, add, subtract, diff, "
        "weekday, to_timestamp, from_timestamp."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        operation: str = args.get("operation", "")

        if operation not in _VALID_OPS:
            return {"error": f"operation must be one of {sorted(_VALID_OPS)}"}

        try:
            return _dispatch(operation, args)
        except (ValueError, TypeError, OSError) as exc:
            return {"error": str(exc)}


def _dispatch(op: str, args: dict[str, Any]) -> dict[str, Any]:
    if op == "now":
        now = datetime.now(UTC)
        return {"result": now.strftime(_ISO_OUT), "operation": "now", "timezone": "UTC"}

    if op == "parse":
        dt = _parse_dt(args.get("dt", ""))
        return {"result": dt.isoformat(), "operation": "parse", "input": args.get("dt", "")}

    if op == "format":
        fmt: str = args.get("fmt", "")
        if not fmt:
            return {"error": "fmt is required for format operation"}
        dt = _parse_dt(args.get("dt", ""))
        return {"result": dt.strftime(fmt), "operation": "format", "fmt": fmt}

    if op in {"add", "subtract"}:
        dt = _parse_dt(args.get("dt", ""))
        unit: str = args.get("unit", "seconds")
        amount = args.get("amount", 0)
        delta = _make_timedelta(float(amount), unit)
        result = dt + delta if op == "add" else dt - delta
        return {"result": result.strftime(_ISO_OUT), "operation": op, "unit": unit, "amount": amount}

    if op == "diff":
        dt1 = _parse_dt(args.get("dt", ""))
        dt2 = _parse_dt(args.get("dt2", ""))
        unit = args.get("unit", "seconds")
        delta = dt2 - dt1
        return {"result": _delta_in_unit(delta, unit), "operation": "diff", "unit": unit}

    if op == "weekday":
        dt = _parse_dt(args.get("dt", ""))
        return {
            "result": _WEEKDAY_NAMES[dt.weekday()],
            "operation": "weekday",
            "weekday_index": dt.weekday(),
        }

    if op == "to_timestamp":
        dt = _parse_dt(args.get("dt", ""))
        return {"result": dt.replace(tzinfo=UTC).timestamp(), "operation": "to_timestamp"}

    if op == "from_timestamp":
        ts = float(args.get("amount", 0))
        dt = datetime.fromtimestamp(ts, tz=UTC)
        return {"result": dt.strftime(_ISO_OUT), "operation": "from_timestamp"}

    return {"error": f"unhandled operation: {op}"}


def _parse_dt(s: str) -> datetime:
    if not s:
        raise ValueError("dt is required")
    for fmt in _PARSE_FMTS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"cannot parse datetime: {s!r}")


def _make_timedelta(amount: float, unit: str) -> timedelta:
    u = unit.lower()
    if u == "days":
        return timedelta(days=amount)
    if u == "hours":
        return timedelta(hours=amount)
    if u == "minutes":
        return timedelta(minutes=amount)
    if u == "seconds":
        return timedelta(seconds=amount)
    raise ValueError(f"unknown unit: {unit!r}")


def _delta_in_unit(delta: timedelta, unit: str) -> float:
    total = delta.total_seconds()
    u = unit.lower()
    if u == "days":
        return total / 86400
    if u == "hours":
        return total / 3600
    if u == "minutes":
        return total / 60
    return total
