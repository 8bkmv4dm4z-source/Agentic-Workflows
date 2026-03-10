import os
import re
from typing import Any

from agentic_workflows.tools.base import Tool


class UpdateFileSectionTool(Tool):
    name = "update_file_section"
    _args_schema = {
        "path": {"type": "string", "required": "true"},
        "section_marker": {"type": "string", "required": "true"},
        "new_content": {"type": "string", "required": "true"},
        "end_marker": {"type": "string"},
        "create_if_missing": {"type": "boolean"},
    }
    description = (
        "Updates a section of a file identified by a marker string. "
        "Replaces content from the marker to the next ## heading or EOF."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        path: str = args.get("path", "")
        section_marker: str = args.get("section_marker", "")
        new_content: str = args.get("new_content", "")
        end_marker: str | None = args.get("end_marker")
        create_if_missing: bool = args.get("create_if_missing", False)

        if not path:
            return {"error": "path is required"}
        if not section_marker:
            return {"error": "section_marker is required"}

        target_path = path
        artifact_dir = (os.environ.get("P1_RUN_ARTIFACT_DIR") or os.environ.get("AGENT_WORKDIR") or "").strip()
        if artifact_dir and not os.path.isabs(path) and not os.path.dirname(path):
            os.makedirs(artifact_dir, exist_ok=True)
            target_path = os.path.join(artifact_dir, path)

        file_exists = os.path.exists(target_path)
        if not file_exists:
            if not create_if_missing:
                return {"error": f"File not found: {path}"}
            lines: list[str] = []
        else:
            try:
                with open(target_path, encoding="utf-8") as fh:
                    lines = fh.readlines()
            except OSError as exc:
                return {"error": f"Failed to read file: {str(exc)}"}

        # Find the section marker
        marker_idx: int | None = None
        for i, line in enumerate(lines):
            if section_marker in line:
                marker_idx = i
                break

        nc = new_content if new_content.endswith("\n") else new_content + "\n"

        if marker_idx is None:
            if create_if_missing:
                new_lines = lines + [section_marker + "\n", nc]
                section_found = False
                lines_replaced = 0
            else:
                return {
                    "result": "section not found, no changes made",
                    "path": target_path,
                    "section_found": False,
                    "lines_replaced": 0,
                }
        else:
            section_found = True
            insert_start = marker_idx + 1
            insert_end = len(lines)

            if end_marker:
                for i in range(insert_start, len(lines)):
                    if end_marker in lines[i]:
                        insert_end = i
                        break
            else:
                for i in range(insert_start, len(lines)):
                    if re.match(r"^## ", lines[i]):
                        insert_end = i
                        break

            lines_replaced = insert_end - insert_start
            new_lines = lines[:insert_start] + [nc] + lines[insert_end:]

        try:
            parent = os.path.dirname(target_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
        except OSError as exc:
            return {"error": f"Failed to write file: {str(exc)}"}

        return {
            "result": f"Successfully updated section in {path}",
            "path": target_path,
            "section_found": section_found,
            "lines_replaced": lines_replaced,
        }
