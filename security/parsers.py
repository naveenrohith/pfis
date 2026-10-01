"""Bounded, scope-aware scanner output parsing and evidence sanitization."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from security.registry import TARGETS

MAX_REPORT_BYTES = 8_000_000
MAX_FINDINGS = 5_000
MAX_EVIDENCE_CHARS = 1_000
_HEADER_SECRET = re.compile(
    r"(?im)^(\s*(?:authorization|proxy-authorization|cookie|set-cookie):\s*).+$"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_CREDENTIAL_PAIR = re.compile(
    r"(?i)(?P<prefix>(?<![A-Za-z0-9_-])['\"]?(?:authorization|proxy-authorization|"
    r"cookie|set-cookie|password|passwd|secret|client[_-]?secret|access[_-]?token|"
    r"refresh[_-]?token|id[_-]?token|token|api[_-]?key|csrf[_-]?token|session)['\"]?"
    r"\s*[=:]\s*)(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)"
)
_SENSITIVE_QUERY = re.compile(r"(?i)(token|code|secret|password|key|csrf|session)")
PRIVATE_CA_TLS_OBSERVATIONS = frozenset(
    {
        "cert_revocation",
        "cert_chain_of_trust",
        "intermediate_cert_expiration",
        "intermediate_cert_notafter",
    }
)


@dataclass(frozen=True)
class ParsedFinding:
    title: str
    severity: str
    confidence: str
    target_id: str
    endpoint: str
    tool: str
    evidence: str
    reproduction: str = ""
    control: bool = False

    @property
    def fingerprint(self) -> str:
        stable = "\0".join((self.target_id, self.endpoint, self.title.casefold(), self.severity))
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def sanitize_url(value: str) -> str:
    """Strip user info and redact sensitive query parameters from a URL."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https", "tcp"} or not parsed.hostname:
            return "[unscoped]"
        host = parsed.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        query = [
            (key, "[redacted]" if _SENSITIVE_QUERY.search(key) else item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ]
        return urlunsplit((parsed.scheme, host + port, parsed.path[:512], urlencode(query), ""))
    except (ValueError, UnicodeError):
        return "[unscoped]"


def sanitize_evidence(value: str) -> str:
    """Remove common credentials, truncate, and normalize hostile scanner output."""
    value = value[: MAX_REPORT_BYTES + 1]
    value = _BEARER.sub("Bearer [redacted]", value)
    value = _JWT.sub("[redacted-token]", value)

    def redact_pair(match: re.Match[str]) -> str:
        secret = match.group("value")
        quote = secret[0] if len(secret) >= 2 and secret[0] == secret[-1] else ""
        if quote not in {'"', "'"}:
            quote = ""
        return f"{match.group('prefix')}{quote}[redacted]{quote}"

    value = _CREDENTIAL_PAIR.sub(redact_pair, value)
    # Redact entire header lines last so the key/value pass cannot leave a
    # partial header value or add a second closing bracket around the marker.
    value = _HEADER_SECRET.sub(r"\1[redacted]", value)
    value = re.sub(r"(?i)(https?://[^\s\"'<>]+)", lambda m: sanitize_url(m.group(1)), value)
    return value[:MAX_EVIDENCE_CHARS]


def _bounded(raw: str | bytes) -> str:
    encoded = raw.encode("utf-8", errors="replace") if isinstance(raw, str) else raw
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("scanner output exceeded the 2 MB parser limit")
    return encoded.decode("utf-8", errors="replace")


def _scoped_endpoint(value: str, allowed_hosts: set[str]) -> str:
    sanitized = sanitize_url(value)
    host = urlsplit(sanitized).hostname
    if host not in allowed_hosts:
        raise ValueError(f"scanner output referenced an out-of-scope host: {host or 'invalid'}")
    return sanitized


def _finding(
    *,
    title: str,
    severity: str,
    target_id: str,
    endpoint: str,
    tool: str,
    evidence: str,
    confidence: str = "medium",
    reproduction: str = "",
    control: bool = False,
) -> ParsedFinding:
    allowed_severity = severity.lower()
    if allowed_severity not in {"critical", "high", "medium", "low", "info", "unknown"}:
        allowed_severity = "unknown"
    if confidence.lower() not in {"high", "medium", "low", "unknown"}:
        confidence = "unknown"
    return ParsedFinding(
        title=sanitize_evidence(title) or "Scanner observation",
        severity=allowed_severity,
        confidence=confidence.lower(),
        target_id=target_id,
        endpoint=endpoint[:512],
        tool=tool,
        evidence=sanitize_evidence(evidence),
        reproduction=sanitize_evidence(reproduction),
        control=control,
    )


def parse_nuclei_jsonl(
    raw: str, *, target_id: str, allowed_hosts: set[str], control: bool = False
) -> list[ParsedFinding]:
    findings: list[ParsedFinding] = []
    for line in _bounded(raw).splitlines():
        if not line.strip():
            continue
        if len(findings) >= MAX_FINDINGS:
            raise ValueError("scanner output exceeded the finding limit")
        item = json.loads(line)
        if not isinstance(item, dict):
            continue
        matched = _scoped_endpoint(
            str(item.get("matched-at") or item.get("host") or ""), allowed_hosts
        )
        info_value = item.get("info")
        info = info_value if isinstance(info_value, dict) else {}
        classification_value = info.get("classification")
        classification = classification_value if isinstance(classification_value, dict) else {}
        cve = classification.get("cve-id") if isinstance(classification, dict) else None
        findings.append(
            _finding(
                title=str(info.get("name") or item.get("template-id") or "Nuclei finding"),
                severity=str(info.get("severity") or "unknown"),
                target_id=target_id,
                endpoint=matched,
                tool="nuclei",
                evidence=json.dumps(
                    {
                        "template": item.get("template-id"),
                        "matcher": item.get("matcher-name"),
                        "cve": cve,
                    },
                    ensure_ascii=True,
                ),
                confidence=str(info.get("confidence") or "medium"),
                reproduction=str(item.get("curl-command") or ""),
                control=control,
            )
        )
    return findings


def parse_zap_json(
    raw: str, *, target_id: str, allowed_hosts: set[str], control: bool = False
) -> list[ParsedFinding]:
    document = json.loads(_bounded(raw))
    sites = document.get("site", []) if isinstance(document, dict) else []
    findings: list[ParsedFinding] = []
    for site in sites:
        alerts = site.get("alerts", []) if isinstance(site, dict) else []
        for alert in alerts:
            if len(findings) >= MAX_FINDINGS:
                raise ValueError("scanner output exceeded the finding limit")
            instances = alert.get("instances") or [{}]
            for instance in instances:
                uri = str(instance.get("uri") or site.get("@name") or "")
                endpoint = _scoped_endpoint(uri, allowed_hosts)
                risk = str(alert.get("riskdesc") or "unknown").split(" ", maxsplit=1)[0].lower()
                if risk == "informational":
                    risk = "info"
                findings.append(
                    _finding(
                        title=str(alert.get("name") or alert.get("alert") or "ZAP finding"),
                        severity=risk,
                        confidence=str(alert.get("confidence") or "medium"),
                        target_id=target_id,
                        endpoint=endpoint,
                        tool="zap",
                        evidence=str(
                            instance.get("evidence")
                            or instance.get("attack")
                            or alert.get("desc")
                            or ""
                        ),
                        reproduction=str(instance.get("method") or ""),
                        control=control,
                    )
                )
    return findings


def parse_nmap_xml(
    raw: str, *, target_id: str, allowed_hosts: set[str], control: bool = False
) -> list[ParsedFinding]:
    source = _bounded(raw)
    # Nmap emits this inert, declaration-free document type in normal XML output.
    source = re.sub(
        r"\A(\s*(?:<\?xml[^?]*\?>\s*)?)<!DOCTYPE\s+nmaprun\s*>\s*",
        r"\1",
        source,
        count=1,
        flags=re.I,
    )
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", source, flags=re.IGNORECASE):
        raise ValueError("DTD and entity declarations are not accepted")
    root = ET.fromstring(source)
    if root.tag != "nmaprun":
        raise ValueError("unexpected Nmap document root")
    findings: list[ParsedFinding] = []
    for host in root.findall("host"):
        names = {entry.get("name", "").lower() for entry in host.findall("./hostnames/hostname")}
        addresses = {entry.get("addr", "").lower() for entry in host.findall("./address")}
        matched_hosts = names.intersection(allowed_hosts) or addresses.intersection(allowed_hosts)
        if not matched_hosts:
            raise ValueError("Nmap output referenced a host outside the registered target")
        scanned_host = sorted(matched_hosts)[0]
        for port in host.findall("./ports/port"):
            state = port.find("state")
            if state is None or state.get("state") != "open":
                continue
            service = port.find("service")
            title = "Open network service"
            evidence = f"port={port.get('portid')} protocol={port.get('protocol')}"
            if service is not None:
                title = str(service.get("name") or title)
                evidence += f" service={service.get('product', '')} {service.get('version', '')}"
            findings.append(
                _finding(
                    title=title,
                    severity="info",
                    target_id=target_id,
                    endpoint=f"tcp://{scanned_host}:{port.get('portid')}",
                    tool="nmap",
                    evidence=evidence,
                    control=control,
                )
            )
            if len(findings) > MAX_FINDINGS:
                raise ValueError("scanner output exceeded the finding limit")
    return findings


def parse_testssl_json(
    raw: str,
    *,
    target_id: str,
    allowed_hosts: set[str],
    control: bool = False,
    private_ca: bool = False,
) -> list[ParsedFinding]:
    source = _bounded(raw)
    try:
        document = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError("testssl output has no complete JSON report") from exc
    if isinstance(document, list):
        items = document
    elif isinstance(document, dict):
        items = document.get("scanResult", [])
    else:
        raise ValueError("unexpected testssl report root")
    if not isinstance(items, list):
        raise ValueError("unexpected testssl scan result collection")
    findings: list[ParsedFinding] = []
    for result in items:
        if not isinstance(result, dict):
            continue
        reported_hosts: set[str] = set()
        for key in ("targetHost", "ip"):
            value = result.get(key)
            if not isinstance(value, str):
                continue
            for candidate in re.split(r"[/,;\s]+", value.strip()):
                if not candidate or candidate in {"?", "n/a"}:
                    continue
                reported = urlsplit("https://" + candidate).hostname
                if reported:
                    reported_hosts.add(reported.lower())
        if reported_hosts and not reported_hosts.issubset(allowed_hosts):
            raise ValueError("testssl output referenced a host outside the registered target")
        title = str(result.get("id") or result.get("finding") or "TLS observation")
        observation_id = title.casefold().split(" ", maxsplit=1)[0]
        severity = str(result.get("severity") or result.get("rating") or "info").lower()
        evidence = str(result.get("finding") or result.get("cve") or result.get("severity") or "")
        if private_ca and observation_id in PRIVATE_CA_TLS_OBSERVATIONS:
            severity = "info"
            evidence = "Expected local private-CA observation: " + evidence
        if private_ca and observation_id == "engine_problem":
            severity = "info"
            evidence = "Optional local testssl engine unavailable: " + evidence
        retained_info = severity == "info" and evidence.startswith(
            ("Expected local private-CA observation:", "Optional local testssl engine unavailable:")
        )
        if severity in {"ok", "good", "info", "not offered", "offered"} and not retained_info:
            continue
        target = TARGETS[target_id]
        host = target.host
        findings.append(
            _finding(
                title=title,
                severity=severity,
                target_id=target_id,
                endpoint=f"https://{host}",
                tool="testssl",
                evidence=evidence,
                control=control,
            )
        )
    return findings[:MAX_FINDINGS]


def parse_greenbone_xml(
    raw: str, *, target_id: str, allowed_hosts: set[str], control: bool = False
) -> list[ParsedFinding]:
    source = _bounded(raw)
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", source, flags=re.IGNORECASE):
        raise ValueError("DTD and entity declarations are not accepted")
    root = ET.fromstring(source)
    if root.tag not in {"get_reports_response", "report", "get_results_response"}:
        raise ValueError("unexpected Greenbone document root")
    findings: list[ParsedFinding] = []
    for result in root.findall(".//result"):
        host = (result.findtext("host") or "").strip().lower()
        if host not in allowed_hosts:
            raise ValueError("Greenbone output referenced a host outside the registered target")
        nvt = result.find("nvt")
        severity = _greenbone_severity(result.findtext("severity") or "unknown")
        title = (nvt.findtext("name") if nvt is not None else None) or "Greenbone finding"
        findings.append(
            _finding(
                title=title,
                severity=severity,
                confidence="medium",
                target_id=target_id,
                endpoint=f"https://{host}",
                tool="greenbone",
                evidence=result.findtext("description") or "",
                reproduction=result.findtext("name") or "",
                control=control,
            )
        )
        if len(findings) > MAX_FINDINGS:
            raise ValueError("scanner output exceeded the finding limit")
    return findings


def _greenbone_severity(value: str) -> str:
    """Normalize Greenbone's numeric CVSS score to the shared severity scale."""
    normalized = value.strip().lower()
    if normalized in {"critical", "high", "medium", "low", "info", "unknown"}:
        return normalized
    try:
        score = float(normalized)
    except ValueError:
        return "unknown"
    if not 0.0 <= score <= 10.0:
        return "unknown"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score > 0.0:
        return "low"
    return "info"


def parse_sqlmap_output(raw: str, *, target_id: str = "sqli-fixture") -> list[ParsedFinding]:
    source = _bounded(raw)
    if not re.search(r"is vulnerable|parameter .* appears to be injectable", source, re.I):
        return []
    return [
        _finding(
            title="SQL injection positive control",
            severity="high",
            confidence="high",
            target_id=target_id,
            endpoint="http://sqli-fixture:8080/item?id=1",
            tool="sqlmap",
            evidence="sqlmap confirmed the isolated in-memory fixture parameter as injectable",
            control=True,
        )
    ]


def parse_metasploit_output(raw: str) -> list[ParsedFinding]:
    source = _bounded(raw)
    if not re.search(
        r"Command shell session .* opened|Meterpreter session .* opened", source, re.I
    ):
        return []
    return [
        _finding(
            title="Metasploit isolated fixture control executed",
            severity="high",
            confidence="high",
            target_id="metasploit-fixture",
            endpoint="tcp://metasploit-fixture:21",
            tool="metasploit",
            evidence="The registered vsftpd training fixture returned a transient test session.",
            reproduction="exploit/unix/ftp/vsftpd_234_backdoor (registered fixture only)",
            control=True,
        )
    ]


PARSERS = {
    "nuclei": parse_nuclei_jsonl,
    "zap": parse_zap_json,
    "nmap": parse_nmap_xml,
    "testssl": parse_testssl_json,
    "greenbone": parse_greenbone_xml,
}
