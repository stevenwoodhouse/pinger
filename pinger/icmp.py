"""ICMP reachability checks via system ping."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_TIME_RE = re.compile(r"time[=<]\s*(?P<ms>\d+(?:\.\d+)?)\s*ms", re.I)

log = logging.getLogger("pinger.icmp")


@dataclass(frozen=True)
class PingOutcome:
    ip: str
    reachable: bool
    latency_ms: float | None
    stdout: str
    stderr: str


def resolve_ping_executable() -> str:
    """Return an absolute ping path. systemd services sometimes have no PATH, so PATH alone fails."""
    from pinger import config

    candidates: list[str] = []

    override = (config.PING_EXECUTABLE or "").strip()
    if override:
        candidates.append(override)
    w = shutil.which("ping")
    if w:
        candidates.append(w)
    candidates.extend(
        (
            "/usr/bin/ping",
            "/bin/ping",
        )
    )

    seen: set[str] = set()
    for p in candidates:
        if not p or p in seen:
            continue
        seen.add(p)
        path = Path(p)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())

    raise RuntimeError(
        "Cannot find executable 'ping'. Install iproute2/iputils (e.g. "
        "`sudo apt install iputils-ping`) or set PINGER_PING_EXECUTABLE to the full "
        "path (often /usr/bin/ping). systemd: add PATH=/usr/bin:/bin to the unit."
    )


async def ping_once(
    ip: str,
    ping_exe: str,
    *,
    deadline_sec: float = 2.0,
) -> PingOutcome:
    """Linux: `ping -c 1 -W <sec>`."""

    w_arg = max(1, min(10, int(round(deadline_sec))))
    try:
        proc = await asyncio.create_subprocess_exec(
            ping_exe,
            "-c",
            "1",
            "-W",
            str(w_arg),
            ip,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return PingOutcome(
            ip=ip,
            reachable=False,
            latency_ms=None,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
        )

    try:
        out_b, err_b = await asyncio.wait_for(
            proc.communicate(), timeout=deadline_sec + 1.0
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return PingOutcome(
            ip=ip,
            reachable=False,
            latency_ms=None,
            stdout="",
            stderr="timeout",
        )

    out = (out_b or b"").decode("utf-8", errors="replace")
    err = (err_b or b"").decode("utf-8", errors="replace")
    code = 0 if proc.returncode is None else int(proc.returncode)

    if code == 0:
        m = _TIME_RE.search(out)
        ms = float(m.group("ms")) if m else None
        return PingOutcome(ip=ip, reachable=True, latency_ms=ms, stdout=out, stderr=err)

    return PingOutcome(
        ip=ip, reachable=False, latency_ms=None, stdout=out, stderr=err
    )


async def ping_many(
    ips: list[str],
    *,
    max_concurrent: int,
    deadline_sec: float,
    ping_exe: str | None = None,
) -> list[PingOutcome]:
    if not ips:
        return []
    exe = ping_exe or resolve_ping_executable()
    sem = asyncio.Semaphore(max_concurrent)

    async def one(target_ip: str) -> PingOutcome:
        async with sem:
            try:
                return await ping_once(
                    target_ip, exe, deadline_sec=deadline_sec
                )
            except Exception:
                log.exception("Unexpected ping failure for %s", target_ip)
                return PingOutcome(
                    ip=target_ip,
                    reachable=False,
                    latency_ms=None,
                    stdout="",
                    stderr="unexpected error (see logs)",
                )

    raw = await asyncio.gather(*(one(ip) for ip in ips), return_exceptions=True)
    outcomes: list[PingOutcome] = []
    for ip, item in zip(ips, raw):
        if isinstance(item, Exception):
            log.error("Ping gather error for %s: %s", ip, item)
            outcomes.append(
                PingOutcome(
                    ip=ip,
                    reachable=False,
                    latency_ms=None,
                    stdout="",
                    stderr=f"{type(item).__name__}: {item}",
                )
            )
        else:
            outcomes.append(item)
    return outcomes
