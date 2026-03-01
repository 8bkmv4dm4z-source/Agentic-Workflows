from __future__ import annotations

"""Text analytics tool: word count, sentence count, key terms, complexity, etc."""

import re
from collections import Counter
from typing import Any

from agentic_workflows.tools.base import Tool

# Common English stop words for key term extraction
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "it",
        "this",
        "that",
        "was",
        "are",
        "be",
        "has",
        "had",
        "have",
        "not",
        "no",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "so",
        "if",
        "then",
        "than",
        "as",
        "up",
        "out",
        "about",
        "into",
        "over",
        "after",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "they",
        "them",
        "its",
        "his",
        "her",
        "their",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "just",
        "also",
        "very",
        "even",
        "how",
        "what",
        "which",
        "who",
        "when",
        "where",
        "why",
        "been",
        "being",
        "because",
        "between",
        "through",
        "during",
        "before",
        "while",
        "these",
        "those",
        "am",
    }
)

_VALID_OPERATIONS = {
    "word_count",
    "sentence_count",
    "char_count",
    "key_terms",
    "complexity_score",
    "paragraph_count",
    "avg_word_length",
    "unique_words",
    "full_report",
}


class TextAnalysisTool(Tool):
    name = "text_analysis"
    description = (
        "Analyze text for word count, sentence count, key terms, complexity, and more. "
        "Required args: text (string), operation (string). "
        "Operations: word_count, sentence_count, char_count, key_terms, "
        "complexity_score, paragraph_count, avg_word_length, unique_words, full_report."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text", ""))
        operation = str(args.get("operation", "")).strip().lower()

        if not text:
            return {"error": "text is required"}
        if not operation:
            return {"error": "operation is required"}
        if operation not in _VALID_OPERATIONS:
            return {"error": f"unknown operation '{operation}'. Valid: {sorted(_VALID_OPERATIONS)}"}

        if operation == "full_report":
            return self._full_report(text)

        dispatch = {
            "word_count": self._word_count,
            "sentence_count": self._sentence_count,
            "char_count": self._char_count,
            "key_terms": self._key_terms,
            "complexity_score": self._complexity_score,
            "paragraph_count": self._paragraph_count,
            "avg_word_length": self._avg_word_length,
            "unique_words": self._unique_words,
        }
        return dispatch[operation](text)

    def _word_count(self, text: str) -> dict[str, Any]:
        words = text.split()
        return {"word_count": len(words)}

    def _sentence_count(self, text: str) -> dict[str, Any]:
        sentences = re.split(r"[.!?]+", text)
        count = sum(1 for s in sentences if s.strip())
        return {"sentence_count": count}

    def _char_count(self, text: str) -> dict[str, Any]:
        return {"char_count": len(text), "char_count_no_spaces": len(text.replace(" ", ""))}

    def _key_terms(self, text: str, top_n: int = 10) -> dict[str, Any]:
        words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
        filtered = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
        counter = Counter(filtered)
        top = counter.most_common(top_n)
        return {"key_terms": [{"term": t, "count": c} for t, c in top]}

    def _complexity_score(self, text: str) -> dict[str, Any]:
        words = text.split()
        word_count = len(words)
        if word_count == 0:
            return {"complexity_score": 0.0, "level": "trivial"}
        sentences = re.split(r"[.!?]+", text)
        sentence_count = max(1, sum(1 for s in sentences if s.strip()))
        avg_word_len = sum(len(w) for w in words) / word_count
        avg_sentence_len = word_count / sentence_count
        # Simple readability heuristic: longer words and sentences = higher complexity
        score = round((avg_word_len * 1.5) + (avg_sentence_len * 0.5), 2)
        level = "simple" if score < 12 else "moderate" if score < 20 else "complex"
        return {
            "complexity_score": score,
            "level": level,
            "avg_word_length": round(avg_word_len, 2),
            "avg_sentence_length": round(avg_sentence_len, 2),
        }

    def _paragraph_count(self, text: str) -> dict[str, Any]:
        paragraphs = re.split(r"\n\s*\n", text)
        count = sum(1 for p in paragraphs if p.strip())
        return {"paragraph_count": max(count, 1 if text.strip() else 0)}

    def _avg_word_length(self, text: str) -> dict[str, Any]:
        words = text.split()
        if not words:
            return {"avg_word_length": 0.0}
        avg = sum(len(w) for w in words) / len(words)
        return {"avg_word_length": round(avg, 2)}

    def _unique_words(self, text: str) -> dict[str, Any]:
        words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
        unique = sorted(set(words))
        return {"unique_words": unique, "unique_count": len(unique), "total_count": len(words)}

    def _full_report(self, text: str) -> dict[str, Any]:
        report: dict[str, Any] = {"operation": "full_report"}
        report.update(self._word_count(text))
        report.update(self._sentence_count(text))
        report.update(self._char_count(text))
        report.update(self._key_terms(text))
        report.update(self._complexity_score(text))
        report.update(self._paragraph_count(text))
        report.update(self._unique_words(text))
        return report
