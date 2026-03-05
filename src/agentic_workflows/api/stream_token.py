"""Stateless HMAC stream tokens for SSE reconnect authorization."""

from __future__ import annotations

import hashlib
import hmac
import time


def generate_token(run_id: str, secret: str, ttl: int = 600) -> str:
    """Return a signed token: '<run_id>:<expiry_epoch>:<hmac_sha256_hex>'.

    TTL defaults to 600 seconds (10 minutes).
    """
    expiry = int(time.time()) + ttl
    message = f"{run_id}:{expiry}".encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"{run_id}:{expiry}:{signature}"


def validate_token(token: str, run_id: str, secret: str) -> bool:
    """Return True iff token is structurally valid, unexpired, and HMAC matches.

    Uses hmac.compare_digest to prevent timing attacks.
    """
    try:
        parts = token.split(":")
        # Token format: <run_id>:<expiry>:<hmac> where run_id itself may contain colons
        # run_id is everything up to the last two colon-delimited parts
        if len(parts) < 3:
            return False
        token_hmac = parts[-1]
        expiry_str = parts[-2]
        token_run_id = ":".join(parts[:-2])

        if token_run_id != run_id:
            return False

        expiry = int(expiry_str)
        if time.time() > expiry:
            return False

        message = f"{run_id}:{expiry_str}".encode()
        expected_hmac = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(token_hmac, expected_hmac)
    except (ValueError, AttributeError):
        return False
