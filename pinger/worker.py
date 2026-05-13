"""Scheduled network sweep and logging."""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import threading
from ipaddress import IPv4Address

from pinger import config
from pinger import db as dbm
from pinger import mail as mailer
from pinger.discovery import get_scan_network, iter_host_addresses, read_arp_table
from pinger.icmp import ping_many

log = logging.getLogger("pinger.worker")

_TTL_RE = re.compile(r"ttl[=\s]+(?P<ttl>\d+)", re.I)


def _ping_details(out: str, latency_ms: float | None) -> dict:
    d: dict = {"latency_ms": latency_ms}
    m = _TTL_RE.search(out)
    if m:
        d["ttl"] = int(m.group("ttl"))
    return d


class SweepRunner:
    """Runs sweeps on a fresh SQLite connection each time so Waitress threads stay safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def run_once_sync(self) -> None:
        with self._lock:
            conn = dbm.connect(config.DB_PATH)
            try:
                asyncio.run(self._run_async(conn))
            finally:
                conn.close()

    async def _run_async(self, conn: sqlite3.Connection) -> None:
        net = get_scan_network(config.NETWORK_CIDR)
        host_ips = [str(ip) for ip in iter_host_addresses(net)]
        known = dbm.known_ips(conn)
        # Always include watched devices that might not be in current CIDR (manual entries)
        extra = [ip for ip in known if ip not in set(host_ips)]
        targets = sorted(set(host_ips) | set(extra), key=lambda s: IPv4Address(s))

        log.info(
            "Sweep %s — %d addresses (+%d off-range watched)",
            net,
            len(host_ips),
            len(extra),
        )

        outcomes = await ping_many(
            targets,
            max_concurrent=config.MAX_CONCURRENT_PINGS,
            deadline_sec=float(config.PING_DEADLINE_SEC),
        )

        arp = read_arp_table()
        had_prior_sweep = dbm.get_last_sweep_finished(conn) is not None
        new_device_alerts: list[tuple[str, str | None, int, float | None]] = []

        with dbm.transaction(conn):
            retention = float(config.RETENTION_DAYS) * 86400.0
            pruned = dbm.purge_old_logs(conn, retention)
            if pruned:
                log.debug(
                    "Purged %d ping log rows older than %s days",
                    pruned,
                    config.RETENTION_DAYS,
                )

            for o in outcomes:
                row = dbm.get_device_by_ip(conn, o.ip)
                tracked = row is not None

                if o.reachable:
                    device_id, created = dbm.get_or_create_device(conn, o.ip)
                    mac = arp.get(o.ip)
                    if created and had_prior_sweep:
                        new_device_alerts.append(
                            (o.ip, mac, device_id, o.latency_ms)
                        )
                    dbm.touch_device(conn, device_id, mac=mac)
                    dbm.update_details(
                        conn, device_id, _ping_details(o.stdout, o.latency_ms)
                    )

                    snippet = (
                        (o.stdout or "").strip().splitlines()[-3:]
                        if (o.stdout or "").strip()
                        else []
                    )
                    raw_compact = "\n".join(snippet)
                    dbm.append_ping_log(
                        conn,
                        device_id,
                        reachable=True,
                        latency_ms=o.latency_ms,
                        raw_output=raw_compact,
                    )
                elif tracked:
                    device_id = int(row["id"])
                    dbm.update_details(
                        conn,
                        device_id,
                        {
                            "reachable": False,
                            "stderr": (o.stderr or "").strip(),
                            "stdout_tail": "\n".join(
                                (o.stdout or "").strip().splitlines()[-5:]
                            ),
                        },
                    )
                    dbm.append_ping_log(
                        conn,
                        device_id,
                        reachable=False,
                        latency_ms=None,
                        raw_output=(o.stdout or o.stderr or "").strip()[:4000],
                    )

            dbm.sync_nicknames_for_shared_macs(conn)
            dbm.set_last_sweep_finished(conn, dbm.now())

        to_addr = (dbm.get_setting(conn, "notify_email") or "").strip()
        if new_device_alerts and to_addr and mailer.smtp_configured():
            net_label = str(net)
            for ip_a, mac_a, did, lat in new_device_alerts:
                row = dbm.get_device_by_id(conn, did)
                nick = (row["nickname"] or "").strip() if row else ""
                grp = dbm.mac_group_for_mac(conn, mac_a)
                if grp is not None:
                    super_nick = str(grp["nickname"]).strip()
                    if super_nick:
                        nick = super_nick
                try:
                    mailer.send_new_device_alert(
                        to_addr,
                        ip=ip_a,
                        mac=mac_a,
                        device_id=did,
                        latency_ms=lat,
                        network=net_label,
                        nickname=nick or None,
                    )
                except Exception:
                    log.exception(
                        "Failed to send new-device alert for ip=%s", ip_a
                    )
        elif new_device_alerts and to_addr and not mailer.smtp_configured():
            log.warning(
                "notify_email is set but no SMTP host is configured "
                "(preferences or PINGER_SMTP_HOST); "
                "skipping %d new-device alert(s)",
                len(new_device_alerts),
            )
