"""Unit tests for HMAC stream-token generation and validation."""

from __future__ import annotations

from agentic_workflows.api.stream_token import generate_token, validate_token

SECRET = "test-secret-key"


def test_valid_token_roundtrip():
    """generate → validate returns True for matching run_id and secret."""
    token = generate_token("run-1", SECRET)
    assert validate_token(token, "run-1", SECRET)


def test_wrong_run_id_rejected():
    """Token generated for run-1 must not validate against run-2."""
    token = generate_token("run-1", SECRET)
    assert not validate_token(token, "run-2", SECRET)


def test_expired_token_rejected():
    """Token with ttl=-1 is already expired and must fail validation."""
    token = generate_token("run-1", SECRET, ttl=-1)
    assert not validate_token(token, "run-1", SECRET)


def test_tampered_hmac_rejected():
    """Flipping one char in the HMAC portion must fail validation."""
    token = generate_token("run-1", SECRET)
    parts = token.rsplit(":", 1)
    tampered = parts[0] + ":" + ("0" if parts[1][0] != "0" else "1") + parts[1][1:]
    assert not validate_token(tampered, "run-1", SECRET)


def test_empty_token_rejected():
    """Empty string must not validate."""
    assert not validate_token("", "run-1", SECRET)


def test_malformed_token_rejected():
    """Token without enough colon-delimited parts must fail."""
    assert not validate_token("just-one-part", "run-1", SECRET)
    assert not validate_token("two:parts", "run-1", SECRET)


def test_colons_in_run_id():
    """Run IDs containing colons (e.g. pub_abc:123) must roundtrip correctly."""
    run_id = "pub_abc:123"
    token = generate_token(run_id, SECRET)
    assert validate_token(token, run_id, SECRET)


def test_wrong_secret_rejected():
    """Token generated with one secret must not validate with a different secret."""
    token = generate_token("run-1", SECRET)
    assert not validate_token(token, "run-1", "wrong-secret")
