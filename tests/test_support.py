"""Shared helpers for PFIS verification scripts."""

import json
import urllib.request
import uuid


BASE = "http://localhost:8000"


def api_get(path: str):
    response = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(response.read())


def api_post(path: str, data=None):
    payload = json.dumps(data).encode() if data is not None else b"{}"
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    response = urllib.request.urlopen(request)
    return json.loads(response.read())


def api_patch(path: str, data):
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    response = urllib.request.urlopen(request)
    return json.loads(response.read())


def create_test_user(prefix: str):
    suffix = uuid.uuid4().hex[:8]
    return api_post(
        "/api/users/",
        {
            "email": f"{prefix}-{suffix}@pfis.local",
            "name": f"{prefix.replace('-', ' ').title()} {suffix}",
            "currency": "INR",
        },
    )