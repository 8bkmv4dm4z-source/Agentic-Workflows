import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from agentic_workflows.tools._security import check_http_domain
from agentic_workflows.tools.base import Tool

_PRIVATE_PREFIXES = (
    "10.", "127.", "169.254.", "192.168.",
    "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.",
    "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
)
_MAX_TIMEOUT = 30
_VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class HttpRequestTool(Tool):
    name = "http_request"
    description = "Makes HTTP requests (GET/POST/PUT/PATCH/DELETE). Private IPs are blocked."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        url: str = args.get("url", "")
        method: str = str(args.get("method", "GET")).upper()
        headers: dict = args.get("headers") or {}
        body = args.get("body")
        timeout: int = min(int(args.get("timeout", 10)), _MAX_TIMEOUT)
        response_format: str = args.get("response_format", "json")

        if not url:
            return {"error": "url is required", "status_code": None}
        if not url.startswith(("http://", "https://")):
            return {"error": "url must start with http:// or https://", "status_code": None}
        if method not in _VALID_METHODS:
            return {"error": f"invalid method: {method}", "status_code": None}

        # SSRF protection: resolve hostname and reject private IPs
        try:
            hostname = urlparse(url).hostname or ""
            ip = socket.gethostbyname(hostname)
            if _is_private(ip):
                return {"error": f"blocked: private IP address {ip}", "status_code": None}
        except socket.gaierror as exc:
            return {"error": f"DNS resolution failed: {str(exc)}", "status_code": None}

        # Security: domain allowlist check
        domain_err = check_http_domain(url)
        if domain_err is not None:
            domain_err["status_code"] = None
            return domain_err

        # Build request body
        data: bytes | None = None
        req_headers = dict(headers)
        if body is not None:
            if isinstance(body, dict):
                data = json.dumps(body).encode("utf-8")
                req_headers.setdefault("Content-Type", "application/json")
            else:
                data = str(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            max_response = int(os.getenv("P1_HTTP_MAX_RESPONSE_BYTES", "0") or "0")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_bytes = resp.read(max_response) if max_response > 0 else resp.read()
                raw = raw_bytes.decode("utf-8", errors="replace")
                resp_headers = dict(resp.headers)
                status_code: int = resp.status
                if response_format == "json":
                    try:
                        body_out: Any = json.loads(raw)
                    except json.JSONDecodeError:
                        body_out = raw
                else:
                    body_out = raw
                return {
                    "status_code": status_code,
                    "body": body_out,
                    "headers": resp_headers,
                    "url": url,
                }
        except urllib.error.HTTPError as exc:
            return {"error": str(exc), "status_code": exc.code}
        except urllib.error.URLError as exc:
            return {"error": str(exc.reason), "status_code": None}
        except Exception as exc:
            return {"error": str(exc), "status_code": None}


def _is_private(ip: str) -> bool:
    return ip.startswith(_PRIVATE_PREFIXES)
