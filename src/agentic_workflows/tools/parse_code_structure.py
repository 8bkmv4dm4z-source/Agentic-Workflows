from __future__ import annotations

"""Tool for extracting code structure (functions, classes, imports) from source files."""

import ast
import re
from pathlib import Path
from typing import Any

from .base import Tool

MAX_FILE_BYTES = 500 * 1024  # 500KB


class ParseCodeStructureTool(Tool):
    name = "parse_code_structure"
    description = (
        "Extract functions, classes, and imports from source files using AST (Python) or regex (other). "
        "Required args: path (str). "
        "Optional: operations (list of 'functions', 'classes', 'imports'; default all three)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        path_str = str(args.get("path", "")).strip()
        operations = args.get("operations", ["functions", "classes", "imports"])
        if isinstance(operations, str):
            operations = [operations]
        if not path_str:
            return {"error": "path is required"}

        # Path traversal protection
        cwd = Path.cwd().resolve()
        try:
            target = Path(path_str).resolve()
        except Exception:
            return {"error": f"invalid path: {path_str}"}
        try:
            target.relative_to(cwd)
        except ValueError:
            return {"error": f"path outside working directory: {path_str}"}

        if not target.exists():
            return {"error": f"file not found: {path_str}"}
        if not target.is_file():
            return {"error": f"not a file: {path_str}"}

        size = target.stat().st_size
        truncated = size > MAX_FILE_BYTES
        try:
            raw = target.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
        except Exception as e:
            return {"error": f"cannot read file: {e}"}

        line_count = raw.count("\n") + (1 if raw and not raw.endswith("\n") else 0)
        suffix = target.suffix.lower()

        result: dict[str, Any] = {
            "language": "python" if suffix == ".py" else "other",
            "line_count": line_count,
        }
        if truncated:
            result["truncated"] = True

        if suffix == ".py":
            result.update(_parse_python(raw, operations))
        else:
            result.update(_parse_regex(raw, operations))

        return result


def _parse_python(source: str, operations: list[str]) -> dict[str, Any]:
    """Parse Python source using the ast module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _parse_regex(source, operations)

    result: dict[str, Any] = {}

    if "functions" in operations:
        functions: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorators: list[str] = []
                for d in node.decorator_list:
                    if isinstance(d, ast.Name):
                        decorators.append(d.id)
                    else:
                        try:
                            decorators.append(ast.unparse(d))
                        except Exception:
                            decorators.append("<unknown>")
                functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                    "decorators": decorators,
                })
        result["functions"] = functions

    if "classes" in operations:
        classes: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases: list[str] = []
                for b in node.bases:
                    if isinstance(b, ast.Name):
                        bases.append(b.id)
                    else:
                        try:
                            bases.append(ast.unparse(b))
                        except Exception:
                            bases.append("<unknown>")
                decorators_cls: list[str] = []
                for d in node.decorator_list:
                    if isinstance(d, ast.Name):
                        decorators_cls.append(d.id)
                    else:
                        try:
                            decorators_cls.append(ast.unparse(d))
                        except Exception:
                            decorators_cls.append("<unknown>")
                classes.append({
                    "name": node.name,
                    "line": node.lineno,
                    "bases": bases,
                    "decorators": decorators_cls,
                })
        result["classes"] = classes

    if "imports" in operations:
        imports: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({"module": alias.name, "alias": alias.asname})
            elif isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
                imports.append({"from": node.module or "", "names": names})
        result["imports"] = imports

    return result


def _parse_regex(source: str, operations: list[str]) -> dict[str, Any]:
    """Regex-based fallback for non-Python files."""
    result: dict[str, Any] = {}
    lines = source.splitlines()

    if "functions" in operations:
        functions: list[dict[str, Any]] = []
        for i, line in enumerate(lines, 1):
            if re.match(r"^(\s*)def\s+(\w+)", line):
                m = re.match(r"^(\s*)def\s+(\w+)", line)
                if m:
                    functions.append({"name": m.group(2), "line": i})
            elif re.match(r"^\s*function\s+(\w+)", line):
                m = re.match(r"^\s*function\s+(\w+)", line)
                if m:
                    functions.append({"name": m.group(1), "line": i})
            elif re.match(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", line):
                m = re.match(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", line)
                if m and not any(f["name"] == m.group(1) for f in functions):
                    functions.append({"name": m.group(1), "line": i})
        result["functions"] = functions

    if "classes" in operations:
        classes: list[dict[str, Any]] = []
        for i, line in enumerate(lines, 1):
            m = re.match(r"^\s*class\s+(\w+)", line)
            if m:
                classes.append({"name": m.group(1), "line": i})
        result["classes"] = classes

    if "imports" in operations:
        imports: list[dict[str, Any]] = []
        for i, line in enumerate(lines, 1):
            if (
                re.match(r"^\s*import\s+", line)
                or re.match(r"^\s*from\s+\S+\s+import\s+", line)
                or re.search(r"require\(", line)
            ):
                imports.append({"line": i, "text": line.strip()})
        result["imports"] = imports

    return result
