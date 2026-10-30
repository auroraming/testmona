"""HTTP origin rules shared by task validation and the Web AI runners.

The result matches the WHATWG origin serialization used by the Node runner:
default ports are omitted, IPv6 addresses stay bracketed, and international
hostnames are punycode. A path, query, fragment, or credential is not an origin.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}
ORIGIN_CONFIG_KEYS = ("app_url", "base_url", "api_url")


def _host_text(hostname: str) -> str:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if isinstance(address, ipaddress.IPv6Address):
        return f"[{address.compressed}]"
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("URL host is not a valid international domain name") from exc


def _origin_from_parts(parts) -> str:
    if parts.scheme not in {"http", "https"} or parts.username or parts.password or not parts.hostname:
        raise ValueError("URL must be an http(s) origin without credentials")
    port = parts.port
    if port == _DEFAULT_PORTS[parts.scheme]:
        port = None
    host = _host_text(parts.hostname)
    return f"{parts.scheme}://{host}:{port}" if port else f"{parts.scheme}://{host}"


def _collapse_dot_segments(path: str) -> str:
    """Match WHATWG URL path normalization, including ``/./`` and ``/foo/../``."""
    if path in {"", "/"}:
        return "/"
    segments: list[str] = []
    for part in path.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if segments:
                segments.pop()
            continue
        segments.append(part)
    return "/" + "/".join(segments) if segments else "/"


def normalize_http_origin(value: str) -> str:
    """Return a scheme/host/port origin, rejecting credentials and extra URL parts."""
    parts = urlsplit(value.strip())
    if _collapse_dot_segments(parts.path) != "/" or parts.query or parts.fragment:
        raise ValueError("URL must be an origin without a path, query, or fragment")
    return _origin_from_parts(parts)


def request_origin(url: str) -> str | None:
    """Origin of a navigated URL, ignoring its path. Unusable URLs return None."""
    try:
        return _origin_from_parts(urlsplit(url.strip()))
    except (ValueError, UnicodeError):
        return None


def validate_origin_fields(config: dict) -> None:
    """Reject web/API target URLs that are not bare http(s) origins."""
    for key in ORIGIN_CONFIG_KEYS:
        value = config.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key} must be an http(s) origin")
        normalize_http_origin(value)
