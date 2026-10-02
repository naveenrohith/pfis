"""Target and redirect scope decisions shared by CLI, controller, and parsers."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from security.registry import PROFILE_TARGETS, TARGETS


class ScopeViolation(ValueError):
    """A command or redirect leaves a committed lab target boundary."""


def resolve_targets(profile_id: str, requested_ids: list[str] | None = None) -> tuple[str, ...]:
    expected = PROFILE_TARGETS.get(profile_id)
    if expected is None:
        raise ScopeViolation("unknown profile")
    requested = tuple(requested_ids or expected)
    if len(requested) != len(set(requested)):
        raise ScopeViolation("duplicate target IDs are not allowed")
    if set(requested) != set(expected):
        raise ScopeViolation("requested targets do not match the profile's registered scope")
    if any(target_id not in TARGETS for target_id in requested):
        raise ScopeViolation("unknown target ID")
    return expected


def resolve_url(target_id: str, candidate: str) -> str:
    target = TARGETS.get(target_id)
    if target is None:
        raise ScopeViolation("unknown target ID")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != target.host:
        raise ScopeViolation("URL leaves the registered lab target")
    if parsed.username is not None or parsed.password is not None:
        raise ScopeViolation("credentials in target URLs are forbidden")
    if parsed.port not in {None, target.port}:
        raise ScopeViolation("target port is outside the registered scope")
    if parsed.fragment:
        raise ScopeViolation("URL fragments are not valid scan targets")
    return f"{target.scheme}://{target.host}:{target.port}{parsed.path or '/'}"


def validate_redirect(target_id: str, source_url: str, location: str) -> str:
    target = TARGETS.get(target_id)
    if target is None:
        raise ScopeViolation("unknown target ID")
    resolved = urljoin(source_url, location)
    parsed = urlsplit(resolved)
    if parsed.hostname != target.host or parsed.scheme != target.scheme:
        raise ScopeViolation("redirect leaves the registered lab target")
    if parsed.port not in {None, target.port} or parsed.username or parsed.password:
        raise ScopeViolation("redirect uses an unregistered port or embedded credentials")
    return resolved
