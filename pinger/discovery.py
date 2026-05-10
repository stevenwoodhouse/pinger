"""Subnet detection and enumeration."""

from __future__ import annotations

import ipaddress
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path


PRIVATE_RANGES = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def _candidate_privates() -> Iterator[ipaddress.IPv4Interface]:
    out = subprocess.run(
        ["ip", "-4", "addr", "show", "up", "scope", "global"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    lines = out.stdout.splitlines()

    inet_re = re.compile(
        r"^\s+inet\s+(?P<addr>\d+\.\d+\.\d+\.\d+)/(?P<prefix>\d+)\s"
    )
    for line in lines:
        m = inet_re.match(line)
        if not m:
            continue
        iface = ipaddress.IPv4Interface(
            f"{m.group('addr')}/{m.group('prefix')}"
        )
        net = iface.network
        if any(net.overlaps(p) for p in PRIVATE_RANGES):
            yield iface


def detect_network() -> ipaddress.IPv4Network:
    """Pick the first private global IPv4 network from `ip addr`."""
    for iface in _candidate_privates():
        return iface.network
    raise RuntimeError(
        "Could not auto-detect a private IPv4 network. "
        "Set PINGER_NETWORK_CIDR, e.g. 192.168.1.0/24"
    )


def get_scan_network(cidr_override: str) -> ipaddress.IPv4Network:
    if cidr_override:
        return ipaddress.IPv4Network(cidr_override, strict=False)
    return detect_network()


def iter_host_addresses(net: ipaddress.IPv4Network) -> Iterator[ipaddress.IPv4Address]:
    hosts = list(net.hosts())
    if not hosts:
        return
    for h in hosts:
        yield h


def read_arp_table() -> dict[str, str]:
    """Map IPv4 string -> MAC from /proc/net/arp (Linux)."""
    try:
        raw = Path("/proc/net/arp").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    rows: dict[str, str] = {}
    for i, line in enumerate(raw.splitlines()):
        if i == 0:
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        ip, hw_type, flags, mac, mask, device = parts[:6]
        if flags != "0x0" and mac != "00:00:00:00:00:00":
            rows[ip] = mac.lower()
    return rows
