from __future__ import annotations

"""Rule-based data validation tool."""

import re
from typing import Any

from .base import Tool

_VALID_RULES = {
    "required",
    "type_check",
    "min",
    "max",
    "range",
    "regex",
    "email",
    "url",
    "ip",
    "enum",
    "length",
}

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_URL_RE = re.compile(r"^https?://[^\s]+$")
_IP_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)


class ValidateDataTool(Tool):
    name = "validate_data"
    _args_schema = {
        "data": {"type": "object", "required": "true"},
        "rules": {"type": "object", "required": "true"},
        "mode": {"type": "string"},
    }
    description = (
        "Validate a data dict against declarative rules. "
        "Required args: data (dict), rules (dict of field -> rule or list of rules). "
        "Optional: mode ('strict'|'lenient', default 'strict'). "
        "Rule types: required, type_check, min, max, range, regex, email, url, ip, enum, length."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        data = args.get("data")
        if not isinstance(data, dict):
            return {"error": "data must be a dict"}

        rules = args.get("rules")
        if not isinstance(rules, dict):
            return {"error": "rules must be a dict of field -> rule(s)"}

        mode = str(args.get("mode", "strict")).strip().lower()

        errors: list[dict[str, Any]] = []
        fields_checked: set[str] = set()
        rules_applied = 0

        for field_name, field_rules in rules.items():
            fields_checked.add(field_name)
            if isinstance(field_rules, dict):
                field_rules = [field_rules]
            if isinstance(field_rules, str):
                field_rules = [{"rule": field_rules}]
            if not isinstance(field_rules, list):
                continue

            value = data.get(field_name)

            for rule_spec in field_rules:
                if isinstance(rule_spec, str):
                    rule_spec = {"rule": rule_spec}
                if not isinstance(rule_spec, dict):
                    continue

                rule_name = str(rule_spec.get("rule", "")).strip()
                if not rule_name:
                    continue
                rules_applied += 1

                err = _check_rule(field_name, value, rule_name, rule_spec, data)
                if err:
                    errors.append(err)
                    if mode == "strict":
                        pass  # continue checking all rules

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "fields_checked": sorted(fields_checked),
            "rules_applied": rules_applied,
        }


def _check_rule(
    field: str, value: Any, rule: str, spec: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any] | None:
    if rule == "required":
        if value is None or (isinstance(value, str) and not value.strip()):
            return {"field": field, "rule": "required", "message": f"{field} is required", "value": value}

    elif rule == "type_check":
        expected = str(spec.get("expected", "")).strip()
        type_map = {"str": str, "int": int, "float": (int, float), "bool": bool, "list": list, "dict": dict}
        if expected in type_map and value is not None and not isinstance(value, type_map[expected]):
                return {"field": field, "rule": "type_check", "message": f"{field} must be {expected}", "value": value}

    elif rule == "min":
        threshold = spec.get("value", spec.get("min"))
        if threshold is not None and value is not None:
            try:
                if float(value) < float(threshold):
                    return {"field": field, "rule": "min", "message": f"{field} must be >= {threshold}", "value": value}
            except (TypeError, ValueError):
                return {"field": field, "rule": "min", "message": f"{field} is not numeric", "value": value}

    elif rule == "max":
        threshold = spec.get("value", spec.get("max"))
        if threshold is not None and value is not None:
            try:
                if float(value) > float(threshold):
                    return {"field": field, "rule": "max", "message": f"{field} must be <= {threshold}", "value": value}
            except (TypeError, ValueError):
                return {"field": field, "rule": "max", "message": f"{field} is not numeric", "value": value}

    elif rule == "range":
        low = spec.get("min")
        high = spec.get("max")
        if low is not None and high is not None and value is not None:
            try:
                v = float(value)
                if v < float(low) or v > float(high):
                    return {"field": field, "rule": "range", "message": f"{field} must be between {low} and {high}", "value": value}
            except (TypeError, ValueError):
                return {"field": field, "rule": "range", "message": f"{field} is not numeric", "value": value}

    elif rule == "regex":
        pattern = str(spec.get("pattern", ""))
        if pattern and value is not None and not re.search(pattern, str(value)):
                return {"field": field, "rule": "regex", "message": f"{field} does not match pattern '{pattern}'", "value": value}

    elif rule == "email":
        if value is not None and not _EMAIL_RE.match(str(value)):
            return {"field": field, "rule": "email", "message": f"{field} is not a valid email", "value": value}

    elif rule == "url":
        if value is not None and not _URL_RE.match(str(value)):
            return {"field": field, "rule": "url", "message": f"{field} is not a valid URL", "value": value}

    elif rule == "ip":
        if value is not None and not _IP_RE.match(str(value)):
            return {"field": field, "rule": "ip", "message": f"{field} is not a valid IP address", "value": value}

    elif rule == "enum":
        allowed = spec.get("values", [])
        if isinstance(allowed, list) and value is not None and value not in allowed:
                return {"field": field, "rule": "enum", "message": f"{field} must be one of {allowed}", "value": value}

    elif rule == "length":
        min_len = spec.get("min")
        max_len = spec.get("max")
        if value is not None:
            vlen = len(str(value))
            if min_len is not None and vlen < int(min_len):
                return {"field": field, "rule": "length", "message": f"{field} length must be >= {min_len}", "value": value}
            if max_len is not None and vlen > int(max_len):
                return {"field": field, "rule": "length", "message": f"{field} length must be <= {max_len}", "value": value}

    return None
