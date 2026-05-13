"""Environment-driven configuration."""

from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw, 10)


def _path_from_env(var: str, default: Path) -> Path:
    raw = os.environ.get(var)
    if raw:
        return Path(raw).expanduser()
    return default


DATA_DIR = _path_from_env("PINGER_DATA_DIR", Path("/var/lib/pinger"))
DB_PATH = _path_from_env("PINGER_DB_PATH", DATA_DIR / "pinger.db")

HOST = os.environ.get("PINGER_HOST", "0.0.0.0")
# Override with env PINGER_PORT (e.g. in systemd unit). Ports <1024 need extra caps with User=.
PORT = _int("PINGER_PORT", 8765)

# Default: 30 minutes
INTERVAL_SEC = _int("PINGER_INTERVAL_SEC", 30 * 60)
RETENTION_DAYS = _int("PINGER_RETENTION_DAYS", 7)

# Empty string = auto-detect first private IPv4 interface prefix
NETWORK_CIDR = os.environ.get("PINGER_NETWORK_CIDR", "").strip()

MAX_CONCURRENT_PINGS = _int("PINGER_MAX_CONCURRENT", 48)
PING_DEADLINE_SEC = _int("PINGER_PING_DEADLINE_SEC", 2)

# Empty = locate `ping` on PATH (/usr/bin/ping, etc.). Systemd units often omit PATH otherwise.
PING_EXECUTABLE = os.environ.get("PINGER_PING_EXECUTABLE", "").strip()

# New-device email alerts (recipient is stored in SQLite via the web UI).
SMTP_HOST = os.environ.get("PINGER_SMTP_HOST", "").strip()
SMTP_PORT = _int("PINGER_SMTP_PORT", 587)
SMTP_USER = os.environ.get("PINGER_SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("PINGER_SMTP_PASSWORD", "").strip()
SMTP_FROM = os.environ.get("PINGER_SMTP_FROM", "").strip()
_raw_tls = (os.environ.get("PINGER_SMTP_USE_TLS", "1") or "").strip().lower()
SMTP_USE_TLS = _raw_tls not in ("0", "false", "no", "off")
