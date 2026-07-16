"""Stable identifiers shared by deterministic recommendation surfaces."""

import hashlib


def recommendation_id(kind: str, target: str, title: str) -> str:
    digest = hashlib.sha256(f"{kind}|{target}|{title}".lower().encode()).hexdigest()[:16]
    return f"{kind}:{digest}"
