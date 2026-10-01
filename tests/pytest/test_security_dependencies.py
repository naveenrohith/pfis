"""Regression tests for patched security-sensitive third-party dependencies."""

from __future__ import annotations

import base64

import jwt
import pytest


def test_deeply_nested_unverified_jwt_payload_uses_pyjwt_error_boundary() -> None:
    """PyJWT must not leak a raw RecursionError from attacker-controlled claims."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(b"[" * 1_200 + b"0" + b"]" * 1_200).rstrip(b"=")
    token = b".".join((header, payload, b"unsigned-test-signature")).decode("ascii")

    with pytest.raises(jwt.DecodeError):
        jwt.decode(token, options={"verify_signature": False})
