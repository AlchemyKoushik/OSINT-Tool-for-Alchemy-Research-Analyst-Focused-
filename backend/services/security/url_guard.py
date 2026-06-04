from ipaddress import ip_address, ip_network
from typing import Any, Dict
from urllib.parse import urlparse

PRIVATE_NETWORKS = (
    ip_network("127.0.0.0/8"),
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("169.254.0.0/16"),
    ip_network("::1/128"),
)
BLOCKED_HOSTNAMES = {"localhost"}


def inspect_url_risk(url: str) -> Dict[str, Any]:
    normalized_url = str(url or "").strip()
    parsed = urlparse(normalized_url)
    hostname = str(parsed.hostname or "").strip().lower()

    if not normalized_url or parsed.scheme not in {"http", "https"}:
        return {"allowed": False, "reason": "Only http and https URLs are allowed.", "hostname": hostname}
    if hostname in BLOCKED_HOSTNAMES:
        return {"allowed": False, "reason": "Localhost targets are blocked.", "hostname": hostname}

    try:
        resolved_ip = ip_address(hostname)
    except ValueError:
        resolved_ip = None

    if resolved_ip is not None:
        for network in PRIVATE_NETWORKS:
            if resolved_ip in network:
                return {"allowed": False, "reason": f"Private or loopback target blocked: {network}", "hostname": hostname}

    return {"allowed": True, "reason": "", "hostname": hostname}


def assert_public_url(url: str) -> None:
    inspection = inspect_url_risk(url)
    if not inspection.get("allowed", False):
        raise ValueError(str(inspection.get("reason", "Blocked URL target.")))
