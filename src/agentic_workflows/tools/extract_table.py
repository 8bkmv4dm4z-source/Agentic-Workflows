import csv
import io
from typing import Any

from agentic_workflows.tools.base import Tool

_VALID_OPS = {"parse", "to_json", "column", "filter", "summary"}


class ExtractTableTool(Tool):
    name = "extract_table"
    _args_schema = {
        "text": {"type": "string", "required": "true"},
        "delimiter": {"type": "string"},
        "has_header": {"type": "boolean"},
        "operation": {"type": "string"},
        "column": {"type": "string"},
        "filter_col": {"type": "string"},
        "filter_value": {"type": "string"},
    }
    description = "Parses and queries CSV/TSV/delimited tabular data."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        text: str = args.get("text", "")
        delimiter: str = args.get("delimiter", ",")
        has_header: bool = args.get("has_header", True)
        operation: str = args.get("operation", "parse")
        column = args.get("column")
        filter_col = args.get("filter_col")
        filter_value = args.get("filter_value")

        if operation not in _VALID_OPS:
            return {"error": f"operation must be one of {sorted(_VALID_OPS)}"}
        if not text:
            return {"error": "text is required"}

        try:
            reader = csv.reader(io.StringIO(text.strip()), delimiter=delimiter)
            raw_rows = list(reader)
        except csv.Error as exc:
            return {"error": f"CSV parse error: {str(exc)}"}

        if not raw_rows:
            return {"error": "no data found"}

        if has_header:
            headers = raw_rows[0]
            rows = raw_rows[1:]
        else:
            headers = [str(i) for i in range(len(raw_rows[0]))]
            rows = raw_rows

        if operation in {"parse", "to_json"}:
            return {
                "headers": headers,
                "rows": rows,
                "row_count": len(rows),
                "col_count": len(headers),
            }

        if operation == "column":
            if column is None:
                return {"error": "column is required for column operation"}
            col_idx = _resolve_col(column, headers)
            if col_idx is None:
                return {"error": f"column not found: {column!r}"}
            values = [r[col_idx] if col_idx < len(r) else "" for r in rows]
            return {"column": column, "values": values, "count": len(values)}

        if operation == "filter":
            if filter_col is None:
                return {"error": "filter_col is required for filter operation"}
            col_idx = _resolve_col(filter_col, headers)
            if col_idx is None:
                return {"error": f"column not found: {filter_col!r}"}
            matched = [r for r in rows if col_idx < len(r) and r[col_idx] == filter_value]
            return {"headers": headers, "rows": matched, "matched": len(matched)}

        if operation == "summary":
            return {
                "headers": headers,
                "row_count": len(rows),
                "col_count": len(headers),
                "sample": rows[:3],
            }

        return {"error": f"unhandled operation: {operation}"}


def _resolve_col(column: Any, headers: list[str]) -> int | None:
    if isinstance(column, int):
        return column if 0 <= column < len(headers) else None
    try:
        return headers.index(str(column))
    except ValueError:
        return None
