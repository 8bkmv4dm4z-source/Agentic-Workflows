from __future__ import annotations

"""Encode/decode tool: base64, URL, hex, HTML escape/unescape."""

import base64
import binascii
import html
import urllib.parse
from typing import Any

from .base import Tool

_VALID_OPERATIONS = {
    "base64_encode",
    "base64_decode",
    "url_encode",
    "url_decode",
    "hex_encode",
    "hex_decode",
    "html_escape",
    "html_unescape",
}


class EncodeDecodeTool(Tool):
    name = "encode_decode"
    _args_schema = {
        "content": {"type": "string", "required": "true"},
        "operation": {"type": "string", "required": "true"},
    }
    description = (
        "Encode or decode content. "
        "Required args: content (str), operation (str). "
        "Operations: base64_encode, base64_decode, url_encode, url_decode, "
        "hex_encode, hex_decode, html_escape, html_unescape."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        content = args.get("content")
        if content is None or (isinstance(content, str) and not content):
            return {"error": "content is required"}
        content = str(content)

        operation = str(args.get("operation", "")).strip().lower()
        if not operation:
            return {"error": "operation is required"}
        if operation not in _VALID_OPERATIONS:
            return {"error": f"unknown operation '{operation}'. Valid: {sorted(_VALID_OPERATIONS)}"}

        try:
            result = _DISPATCH[operation](content)
        except Exception as exc:
            return {"error": f"{operation} failed: {exc}"}

        return {"result": result, "operation": operation}


def _base64_encode(content: str) -> str:
    return base64.b64encode(content.encode()).decode()


def _base64_decode(content: str) -> str:
    return base64.b64decode(content).decode()


def _url_encode(content: str) -> str:
    return urllib.parse.quote(content, safe="")


def _url_decode(content: str) -> str:
    return urllib.parse.unquote(content)


def _hex_encode(content: str) -> str:
    return binascii.hexlify(content.encode()).decode()


def _hex_decode(content: str) -> str:
    return binascii.unhexlify(content).decode()


def _html_escape(content: str) -> str:
    return html.escape(content)


def _html_unescape(content: str) -> str:
    return html.unescape(content)


_DISPATCH = {
    "base64_encode": _base64_encode,
    "base64_decode": _base64_decode,
    "url_encode": _url_encode,
    "url_decode": _url_decode,
    "hex_encode": _hex_encode,
    "hex_decode": _hex_decode,
    "html_escape": _html_escape,
    "html_unescape": _html_unescape,
}
