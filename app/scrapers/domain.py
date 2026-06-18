import ipaddress
import re
import socket
from urllib.parse import urlparse

_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal")


def _ascii_host(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    if not host:
        raise ValueError("Domain is required")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Enter a valid public domain") from exc


def _reject_ip_literal(host: str) -> None:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return
    raise ValueError("IP addresses are not allowed; enter a public domain")


def _validate_domain_host(host: str) -> str:
    host = _ascii_host(host)
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        raise ValueError("Enter a public domain")
    _reject_ip_literal(host)
    labels = host.split(".")
    if len(labels) < 2 or any(not _DOMAIN_LABEL.match(label) for label in labels):
        raise ValueError("Enter a valid public domain")
    return host


def is_public_ip(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    return bool(address.is_global and not address.is_multicast and not address.is_reserved)


def normalize_domain(raw: str) -> str:
    candidate = raw.strip()
    if not candidate:
        raise ValueError("Domain is required")
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https domains are supported")
    if parsed.username or parsed.password:
        raise ValueError("User info is not allowed in domains")
    if not parsed.hostname:
        raise ValueError("Enter a valid domain")

    host = _validate_domain_host(parsed.hostname)
    if host.startswith("www."):
        host = host[4:]
    return host


def homepage_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}"


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("User info is not allowed in URLs")
    host = _validate_domain_host(parsed.hostname)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid public URL") from exc
    if port and port not in {80, 443}:
        raise ValueError("Only standard web ports are allowed")
    netloc = host if not port else f"{host}:{port}"
    return parsed._replace(netloc=netloc, fragment="").geturl()


def is_same_site_url(url: str, base_url: str) -> bool:
    try:
        host = normalize_domain(urlparse(url).hostname or "")
        base_host = normalize_domain(urlparse(base_url).hostname or base_url)
    except ValueError:
        return False
    return host == base_host or host.endswith(f".{base_host}")


def assert_resolves_to_public_ips(host: str) -> None:
    normalized = normalize_domain(host)
    try:
        resolved = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Domain could not be resolved") from exc

    ips = {item[4][0] for item in resolved}
    if not ips or any(not is_public_ip(ip) for ip in ips):
        raise ValueError("Domain resolves to a non-public network address")
