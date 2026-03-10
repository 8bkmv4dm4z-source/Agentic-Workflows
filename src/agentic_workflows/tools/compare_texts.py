from __future__ import annotations

"""Text comparison tool using stdlib difflib."""

import difflib
from pathlib import Path
from typing import Any

from .base import Tool


class CompareTextsTool(Tool):
    name = "compare_texts"
    _args_schema = {
        "text1": {"type": "string"},
        "text2": {"type": "string"},
        "file1": {"type": "string"},
        "file2": {"type": "string"},
        "mode": {"type": "string"},
    }
    description = (
        "Compare two texts and show differences. "
        "Args: text1/text2 (str) OR file1/file2 (str paths). "
        "Optional: mode ('line'|'word'|'char', default 'line')."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        text1 = args.get("text1")
        text2 = args.get("text2")
        file1 = args.get("file1")
        file2 = args.get("file2")

        # Resolve from files if text not provided
        if text1 is None and file1:
            try:
                text1 = Path(file1).read_text(encoding="utf-8")
            except Exception as exc:
                return {"error": f"cannot read file1: {exc}"}
        if text2 is None and file2:
            try:
                text2 = Path(file2).read_text(encoding="utf-8")
            except Exception as exc:
                return {"error": f"cannot read file2: {exc}"}

        if text1 is None:
            return {"error": "text1 or file1 is required"}
        if text2 is None:
            return {"error": "text2 or file2 is required"}

        text1 = str(text1)
        text2 = str(text2)
        mode = str(args.get("mode", "line")).strip().lower()
        if mode not in ("line", "word", "char"):
            return {"error": f"unknown mode '{mode}'. Valid: line, word, char"}

        if mode == "line":
            return _compare_lines(text1, text2)
        elif mode == "word":
            return _compare_words(text1, text2)
        else:
            return _compare_chars(text1, text2)


def _compare_lines(text1: str, text2: str) -> dict[str, Any]:
    lines1 = text1.splitlines(keepends=True)
    lines2 = text2.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines1, lines2, fromfile="text1", tofile="text2"))
    sm = difflib.SequenceMatcher(None, lines1, lines2)
    additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

    return {
        "diff": "".join(diff),
        "similarity": round(sm.ratio(), 4),
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
        "mode": "line",
    }


def _compare_words(text1: str, text2: str) -> dict[str, Any]:
    words1 = text1.split()
    words2 = text2.split()
    sm = difflib.SequenceMatcher(None, words1, words2)

    additions = 0
    deletions = 0
    diff_parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            diff_parts.append(" ".join(words1[i1:i2]))
        elif tag == "insert":
            additions += j2 - j1
            diff_parts.append(f"[+{' '.join(words2[j1:j2])}]")
        elif tag == "delete":
            deletions += i2 - i1
            diff_parts.append(f"[-{' '.join(words1[i1:i2])}]")
        elif tag == "replace":
            deletions += i2 - i1
            additions += j2 - j1
            diff_parts.append(f"[-{' '.join(words1[i1:i2])}][+{' '.join(words2[j1:j2])}]")

    return {
        "diff": " ".join(diff_parts),
        "similarity": round(sm.ratio(), 4),
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
        "mode": "word",
    }


def _compare_chars(text1: str, text2: str) -> dict[str, Any]:
    sm = difflib.SequenceMatcher(None, text1, text2)
    additions = 0
    deletions = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            additions += j2 - j1
        elif tag == "delete":
            deletions += i2 - i1
        elif tag == "replace":
            deletions += i2 - i1
            additions += j2 - j1

    diff = list(difflib.unified_diff(
        text1.splitlines(keepends=True),
        text2.splitlines(keepends=True),
        fromfile="text1",
        tofile="text2",
    ))

    return {
        "diff": "".join(diff),
        "similarity": round(sm.ratio(), 4),
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
        "mode": "char",
    }
