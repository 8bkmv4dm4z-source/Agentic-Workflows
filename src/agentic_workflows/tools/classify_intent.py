from __future__ import annotations

"""Deterministic keyword-based intent classification tool."""

import re
from typing import Any

from .base import Tool

_BUILTIN_CATEGORIES: dict[str, list[str]] = {
    "question": ["what", "how", "why", "when", "where", "who", "which", "is it", "can you", "could you", "does", "do you"],
    "command": ["run", "execute", "start", "stop", "restart", "deploy", "install", "build", "compile", "launch"],
    "data_request": ["show", "get", "fetch", "retrieve", "list", "display", "return", "give me", "provide"],
    "file_operation": ["read", "write", "save", "open", "close", "create", "delete", "copy", "move", "rename", "upload", "download"],
    "analysis": ["analyze", "analysis", "statistics", "stats", "trend", "pattern", "insight", "metric", "measure", "evaluate"],
    "search": ["search", "find", "look for", "locate", "grep", "filter", "query", "seek"],
    "report": ["report", "summary", "summarize", "overview", "digest", "brief", "recap", "status"],
    "transform": ["convert", "transform", "format", "encode", "decode", "parse", "translate", "map", "sort", "merge"],
}


class ClassifyIntentTool(Tool):
    name = "classify_intent"
    description = (
        "Classify text intent using keyword matching. "
        "Required args: text (str). "
        "Optional: categories (dict of category -> keyword list for custom categories)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text", "")).strip()
        if not text:
            return {"error": "text is required"}

        custom = args.get("categories")
        categories = dict(_BUILTIN_CATEGORIES)
        if isinstance(custom, dict):
            for cat, keywords in custom.items():
                if isinstance(keywords, list):
                    categories[str(cat)] = [str(k) for k in keywords]

        text_lower = text.lower()
        scores: dict[str, float] = {}
        matched_keywords: dict[str, list[str]] = {}

        for category, keywords in categories.items():
            hits: list[str] = []
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw.lower()) + r"\b", text_lower):
                    hits.append(kw)
            score = len(hits) / max(len(keywords), 1)
            scores[category] = round(score, 4)
            if hits:
                matched_keywords[category] = hits

        sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_intent = sorted_cats[0][0] if sorted_cats and sorted_cats[0][1] > 0 else "unknown"
        top_score = sorted_cats[0][1] if sorted_cats else 0.0

        # Ambiguity: top two scores are within 0.05 of each other
        is_ambiguous = False
        if len(sorted_cats) >= 2 and sorted_cats[0][1] > 0:
            is_ambiguous = abs(sorted_cats[0][1] - sorted_cats[1][1]) < 0.05

        return {
            "top_intent": top_intent,
            "confidence": round(top_score, 4),
            "scores": {cat: sc for cat, sc in sorted_cats if sc > 0},
            "matched_keywords": matched_keywords,
            "is_ambiguous": is_ambiguous,
        }
