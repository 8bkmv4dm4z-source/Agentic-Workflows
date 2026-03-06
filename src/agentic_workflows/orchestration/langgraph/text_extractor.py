from __future__ import annotations

"""Pure text-extraction helpers extracted from graph.py.

All functions are stateless and depend only on ``re`` and ``math``.
No project imports required.
"""

import re


def extract_quoted_text(text: str) -> str:
    """Return the first single- or double-quoted substring, stripped."""
    match = re.search(r"""["']([^"']+)["']""", text)
    if not match:
        return ""
    return match.group(1).strip()


def extract_numbers_from_text(text: str) -> list[int]:
    """Return all integer tokens (including negatives) found in *text*."""
    return [int(token) for token in re.findall(r"-?\d+", text)]


def extract_fibonacci_count(mission: str) -> int:
    """Infer the requested Fibonacci count from a mission description."""
    patterns = (
        r"(\d+)(?:st|nd|rd|th)\s+number",
        r"first\s+(\d+)\s+(?:fibonacci\s+)?(?:numbers|terms)",
        r"first\s+(\d+)\s+fibonacci",
        r"until\s+the\s+(\d+)\s+(?:number|numbers|terms)",
        r"(\d+)\s+fibonacci\s+(?:numbers|terms)?",
        r"(\d+)\s+(?:numbers|terms)",
    )
    mission_lower = mission.lower()
    for pattern in patterns:
        match = re.search(pattern, mission_lower)
        if match:
            value = int(match.group(1))
            return max(2, value)
    return 100


def fibonacci_csv(count: int) -> str:
    """Return a comma-separated string of the first *count* Fibonacci numbers."""
    numbers = [0, 1]
    while len(numbers) < count:
        numbers.append(numbers[-1] + numbers[-2])
    return ", ".join(str(value) for value in numbers[:count])


def extract_missions(user_input: str) -> list[str]:
    """Extract mission lines from user input for per-mission reporting."""
    lines = [line.strip() for line in user_input.splitlines() if line.strip()]
    task_lines: list[str] = []
    for line in lines:
        if re.match(r"^(task\s*\d+\s*:)", line, flags=re.IGNORECASE):
            task_lines.append(line)
            continue
        if re.match(r"^\d+[\)\.:\-\s]", line):
            task_lines.append(line)
    if task_lines:
        return task_lines
    return ["Primary mission"]


def extract_write_path_from_mission(mission: str) -> str:
    """Extract target file path from mission text when present.

    Prefers filenames associated with write/save/create/generate verbs so that
    missions like "delete foo.py then write bar.py" resolve to bar.py, not foo.py.
    """
    ext = r"[A-Za-z][A-Za-z0-9]{0,9}"
    quoted_matches = re.findall(rf"""["']([^"']+\.(?:{ext}))["']""", mission)
    if quoted_matches:
        return quoted_matches[-1].strip()
    # Prefer filename after redirect/pipe keywords (e.g. "redirect that to test.txt")
    redirect_re = re.compile(
        r"\b(?:redirect(?:\s+(?:that|output|stdout))?\s+to|pipe\s+to)\s+"
        rf"(/?[A-Za-z0-9_.\\/-]+\.(?:{ext}))",
        re.IGNORECASE,
    )
    m = redirect_re.search(mission)
    if m:
        return m.group(1).strip().rstrip(".,;:")
    # Prefer filename immediately following a write/save/create/generate verb
    write_verb_re = re.compile(
        r"\b(?:write|save|create|generate|produce|output)\b\s+(?:to\s+)?"
        rf"(/?[A-Za-z0-9_.\\/-]+\.(?:{ext}))",
        re.IGNORECASE,
    )
    m = write_verb_re.search(mission)
    if m:
        return m.group(1).strip().rstrip(".,;:")
    # Prefer filename after "write ... to" with intervening words
    write_to_re = re.compile(
        r"\bwrite\b.{1,60}?\bto\s+"
        rf"(/?[A-Za-z0-9_.\\/-]+\.(?:{ext}))",
        re.IGNORECASE,
    )
    m = write_to_re.search(mission)
    if m:
        return m.group(1).strip().rstrip(".,;:")
    # Fall back to first filename found
    for match in re.finditer(rf"(/?[A-Za-z0-9_./\\-]+\.(?:{ext}))", mission):
        candidate = match.group(1).strip().rstrip(".,;:")
        # Guard against decimal numbers being interpreted as file paths.
        if re.fullmatch(r"\d+\.\d+", candidate):
            continue
        return candidate
    return ""


def parse_csv_int_list(content: str) -> list[int] | None:
    """Parse a comma-separated integer list; return None on malformed tokens."""
    tokens = [token.strip() for token in content.split(",") if token.strip()]
    if not tokens:
        return []
    numbers: list[int] = []
    for token in tokens:
        if not re.match(r"^-?\d+$", token):
            return None
        numbers.append(int(token))
    return numbers
