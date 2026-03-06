from __future__ import annotations

"""Format conversion tool: JSON, YAML (basic), TOML, CSV, INI."""

import configparser
import csv
import io
import json
import tomllib
from typing import Any

from .base import Tool

_SUPPORTED_FORMATS = {"json", "yaml", "toml", "csv", "ini"}


class FormatConverterTool(Tool):
    name = "format_converter"
    description = (
        "Convert content between data formats. "
        "Required args: content (str), to_format (str). "
        "Optional: from_format (str, auto-detected if omitted). "
        "Supported formats: json, yaml, toml, csv, ini."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        content = args.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            return {"error": "content is required"}
        content = str(content)

        to_fmt = str(args.get("to_format", "")).strip().lower()
        if not to_fmt:
            return {"error": "to_format is required"}
        if to_fmt not in _SUPPORTED_FORMATS:
            return {"error": f"unsupported to_format '{to_fmt}'. Supported: {sorted(_SUPPORTED_FORMATS)}"}

        from_fmt = str(args.get("from_format", "")).strip().lower()
        if not from_fmt:
            from_fmt = _detect_format(content)
            if not from_fmt:
                return {"error": "cannot auto-detect from_format; please specify it explicitly"}

        if from_fmt not in _SUPPORTED_FORMATS:
            return {"error": f"unsupported from_format '{from_fmt}'. Supported: {sorted(_SUPPORTED_FORMATS)}"}

        if from_fmt == to_fmt:
            return {"result": content, "from_format": from_fmt, "to_format": to_fmt}

        # Parse source
        try:
            data = _parse(content, from_fmt)
        except Exception as exc:
            return {"error": f"parse error ({from_fmt}): {exc}"}

        # Emit target
        try:
            result = _emit(data, to_fmt)
        except Exception as exc:
            return {"error": f"emit error ({to_fmt}): {exc}"}

        return {"result": result, "from_format": from_fmt, "to_format": to_fmt}


def _detect_format(content: str) -> str:
    """Best-effort format detection."""
    stripped = content.strip()
    if stripped.startswith(("{", "[")):
        return "json"
    if stripped.startswith("[") and "=" in stripped:
        return "ini"
    # TOML-like: key = "value" or [section]
    if any(line.strip().startswith("[") and "]" in line for line in stripped.splitlines()[:5]):
        lines = stripped.splitlines()
        if any("=" in line and not line.strip().startswith("#") for line in lines[:10]):
            # Could be INI or TOML; check for TOML-specific patterns
            if any(line.strip().startswith("[[") for line in lines[:10]):
                return "toml"
            return "ini"
    # CSV-like: multiple commas on first line
    first_line = stripped.split("\n", 1)[0] if stripped else ""
    if "," in first_line and first_line.count(",") >= 1:
        return "csv"
    return ""


def _parse(content: str, fmt: str) -> Any:
    if fmt == "json":
        return json.loads(content)
    elif fmt == "yaml":
        return _parse_yaml(content)
    elif fmt == "toml":
        return _parse_toml(content)
    elif fmt == "csv":
        return _parse_csv(content)
    elif fmt == "ini":
        return _parse_ini(content)
    raise ValueError(f"unknown format: {fmt}")


def _emit(data: Any, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(data, indent=2, default=str)
    elif fmt == "yaml":
        return _emit_yaml(data)
    elif fmt == "toml":
        return _emit_toml(data)
    elif fmt == "csv":
        return _emit_csv(data)
    elif fmt == "ini":
        return _emit_ini(data)
    raise ValueError(f"unknown format: {fmt}")


# --- YAML (basic, no PyYAML dependency) ---

def _parse_yaml(content: str) -> Any:
    """Minimal YAML parser for simple key: value documents."""
    result: dict[str, Any] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        # Strip quotes
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        elif val.lower() == "true":
            result[key] = True
            continue
        elif val.lower() == "false":
            result[key] = False
            continue
        elif val.lower() in ("null", "~", ""):
            result[key] = None
            continue
        else:
            try:
                result[key] = int(val)
                continue
            except ValueError:
                pass
            try:
                result[key] = float(val)
                continue
            except ValueError:
                pass
        result[key] = val
    return result


def _emit_yaml(data: Any) -> str:
    """Minimal YAML emitter for flat dicts/lists."""
    if isinstance(data, dict):
        lines = []
        for k, v in data.items():
            if v is None:
                lines.append(f"{k}: null")
            elif isinstance(v, bool):
                lines.append(f"{k}: {'true' if v else 'false'}")
            elif isinstance(v, str):
                lines.append(f'{k}: "{v}"')
            else:
                lines.append(f"{k}: {v}")
        return "\n".join(lines) + "\n"
    elif isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, dict):
                parts = ", ".join(f"{k}: {v}" for k, v in item.items())
                lines.append(f"- {{{parts}}}")
            else:
                lines.append(f"- {item}")
        return "\n".join(lines) + "\n"
    return str(data)


# --- TOML ---

def _parse_toml(content: str) -> dict[str, Any]:
    return tomllib.loads(content)


def _emit_toml(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data)
    lines: list[str] = []
    # Top-level scalars first
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_value(v)}")
    # Then sections
    for k, v in data.items():
        if isinstance(v, dict):
            lines.append(f"\n[{k}]")
            for sk, sv in v.items():
                lines.append(f"{sk} = {_toml_value(sv)}")
    return "\n".join(lines) + "\n"


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    if v is None:
        return '""'
    return str(v)


# --- CSV ---

def _parse_csv(content: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(content))
    return [dict(row) for row in reader]


def _emit_csv(data: Any) -> str:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)
        return out.getvalue()
    if isinstance(data, dict):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(data.keys()))
        writer.writeheader()
        writer.writerow(data)
        return out.getvalue()
    return str(data)


# --- INI ---

def _parse_ini(content: str) -> dict[str, Any]:
    parser = configparser.ConfigParser()
    parser.read_string(content)
    result: dict[str, Any] = {}
    for section in parser.sections():
        result[section] = dict(parser[section])
    if parser.defaults():
        result["DEFAULT"] = dict(parser.defaults())
    return result


def _emit_ini(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data)
    parser = configparser.ConfigParser()
    for section, values in data.items():
        if isinstance(values, dict):
            if section != "DEFAULT":
                parser.add_section(section)
            for k, v in values.items():
                parser.set(section, str(k), str(v) if v is not None else "")
    out = io.StringIO()
    parser.write(out)
    return out.getvalue()
