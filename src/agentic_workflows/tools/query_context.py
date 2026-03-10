from __future__ import annotations

"""Cross-run mission context query tool -- read-only pgvector cascade search."""

from typing import Any

from .base import Tool


class QueryContextTool(Tool):
    """Query cross-run mission context for similar past missions."""

    name = "query_context"
    _args_schema = {
        "query": {"type": "string", "required": "true"},
        "max_results": {"type": "number"},
    }
    description = (
        "Query cross-run mission context for similar past missions. "
        "Required args: query (str). Optional: max_results (int, default 3, max 10)."
    )

    def __init__(self, store: Any, embedding_provider: Any = None) -> None:
        self.store = store
        self.embedding_provider = embedding_provider

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}

        max_results = min(int(args.get("max_results", 3)), 10)

        embedding: list[float] | None = None
        if self.embedding_provider is not None:
            embedding = self.embedding_provider.embed([query])[0]

        hits = self.store.query_cascade(
            goal=query, top_k=max_results, embedding=embedding
        )

        results = [
            {
                "goal": h.get("goal", ""),
                "summary": h.get("summary", ""),
                "tools_used": h.get("tools_used", []),
                "score": h.get("score", 0.0),
                "source_layer": h.get("source_layer", ""),
            }
            for h in hits
        ]

        return {"results": results, "count": len(results)}
