import hashlib
from typing import Any

from agentic_workflows.tools.base import Tool

_ALGORITHMS = {"sha256", "md5", "sha1", "sha512", "sha3_256"}


class HashContentTool(Tool):
    name = "hash_content"
    _args_schema = {
        "content": {"type": "string", "required": "true"},
        "algorithm": {"type": "string"},
    }
    description = "Hashes a string using sha256, md5, sha1, sha512, or sha3_256."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        content: str = args.get("content", "")
        algorithm: str = str(args.get("algorithm", "sha256")).lower()

        if not isinstance(content, str):
            return {"error": "content must be a string"}
        if algorithm not in _ALGORITHMS:
            return {"error": f"algorithm must be one of {sorted(_ALGORITHMS)}"}

        h = hashlib.new(algorithm)
        h.update(content.encode("utf-8"))
        return {
            "hash": h.hexdigest(),
            "algorithm": algorithm,
            "input_length": len(content),
        }
