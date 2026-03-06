from __future__ import annotations

"""Deterministic extractive text summarization tool."""

import re
from collections import Counter
from typing import Any

from .base import Tool

# Reuse the stop-words set from text_analysis
from .text_analysis import _STOP_WORDS


class SummarizeTextTool(Tool):
    name = "summarize_text"
    description = (
        "Summarize text using extractive methods. "
        "Required args: text (str). "
        "Optional: max_sentences (int, default 5), method ('frequency'|'position'|'combined', default 'combined')."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text", "")).strip()
        if not text:
            return {"error": "text is required"}

        max_sentences = min(int(args.get("max_sentences", 5)), 50)
        if max_sentences < 1:
            max_sentences = 1

        method = str(args.get("method", "combined")).strip().lower()
        if method not in ("frequency", "position", "combined"):
            return {"error": f"unknown method '{method}'. Valid: frequency, position, combined"}

        sentences = _split_sentences(text)
        if not sentences:
            return {"summary": text, "sentences": 0, "key_topics": [], "compression_ratio": 1.0}

        if len(sentences) <= max_sentences:
            topics = _extract_topics(text)
            return {
                "summary": text,
                "sentences": len(sentences),
                "key_topics": topics,
                "compression_ratio": 1.0,
            }

        # Score sentences
        scores = _score_sentences(sentences, method)

        # Select top-N preserving original order
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        top_indices = sorted([idx for idx, _ in indexed[:max_sentences]])
        selected = [sentences[i] for i in top_indices]

        summary = " ".join(selected)
        topics = _extract_topics(text)
        ratio = round(len(summary) / len(text), 4) if text else 1.0

        return {
            "summary": summary,
            "sentences": len(selected),
            "key_topics": topics,
            "compression_ratio": ratio,
        }


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    raw = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in raw if s.strip()]


def _extract_topics(text: str, top_n: int = 5) -> list[str]:
    """Extract top keywords as topic indicators."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    counter = Counter(filtered)
    return [term for term, _ in counter.most_common(top_n)]


def _score_sentences(sentences: list[str], method: str) -> list[float]:
    """Score each sentence by the selected method."""
    n = len(sentences)

    if method == "frequency":
        return _frequency_scores(sentences)
    elif method == "position":
        return _position_scores(n)
    else:  # combined
        freq = _frequency_scores(sentences)
        pos = _position_scores(n)
        return [0.7 * f + 0.3 * p for f, p in zip(freq, pos, strict=True)]


def _frequency_scores(sentences: list[str]) -> list[float]:
    """TF-based scoring: sentences with more important words score higher."""
    all_words = []
    for s in sentences:
        all_words.extend(re.findall(r"\b[a-zA-Z]{3,}\b", s.lower()))
    filtered = [w for w in all_words if w not in _STOP_WORDS]
    freq = Counter(filtered)
    if not freq:
        return [1.0] * len(sentences)
    max_freq = max(freq.values())

    scores: list[float] = []
    for s in sentences:
        words = [w for w in re.findall(r"\b[a-zA-Z]{3,}\b", s.lower()) if w not in _STOP_WORDS]
        if not words:
            scores.append(0.0)
        else:
            score = sum(freq.get(w, 0) / max_freq for w in words) / len(words)
            scores.append(score)
    return scores


def _position_scores(n: int) -> list[float]:
    """First and last sentences get highest positional weight."""
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    scores: list[float] = []
    for i in range(n):
        if i == 0:
            scores.append(1.0)
        elif i == n - 1:
            scores.append(0.8)
        else:
            scores.append(max(0.1, 1.0 - (i / n)))
    return scores
