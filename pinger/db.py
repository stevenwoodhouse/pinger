"""SQLite persistence."""

from __future__ import annotations

import ipaddress
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Generator


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        check_same_thread=False,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 8000;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL UNIQUE,
            nickname TEXT,
            mac TEXT,
            details_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ping_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            ts REAL NOT NULL,
            reachable INTEGER NOT NULL,
            latency_ms REAL,
            raw_output TEXT,
            FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_ping_logs_device_ts
            ON ping_logs(device_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_ping_logs_ts ON ping_logs(ts);

        CREATE TABLE IF NOT EXISTS pinger_meta (
            key TEXT PRIMARY KEY NOT NULL,
            value REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pinger_settings (
            key TEXT PRIMARY KEY NOT NULL,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mac_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mac_group_members (
            group_id INTEGER NOT NULL,
            mac TEXT NOT NULL,
            PRIMARY KEY (group_id, mac),
            FOREIGN KEY (group_id) REFERENCES mac_groups(id) ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_mac_group_members_mac
            ON mac_group_members(mac);
        """
    )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[None, None, None]:
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


def now() -> float:
    return time.time()


def set_last_sweep_finished(conn: sqlite3.Connection, ts: float) -> None:
    conn.execute(
        "INSERT INTO pinger_meta (key, value) VALUES ('last_sweep_at', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (ts,),
    )


def get_last_sweep_finished(conn: sqlite3.Connection) -> float | None:
    row = conn.execute(
        "SELECT value FROM pinger_meta WHERE key = 'last_sweep_at'"
    ).fetchone()
    if not row:
        return None
    v = float(row["value"])
    return None if v <= 0 else v


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM pinger_settings WHERE key = ?", (key,)
    ).fetchone()
    if not row:
        return None
    return str(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO pinger_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def delete_setting(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM pinger_settings WHERE key = ?", (key,))


def get_or_create_device(conn: sqlite3.Connection, ip: str) -> tuple[int, bool]:
    ip = str(ipaddress.IPv4Address(ip))
    row = conn.execute("SELECT id FROM devices WHERE ip = ?", (ip,)).fetchone()
    if row:
        return int(row["id"]), False
    t = now()
    cur = conn.execute(
        "INSERT INTO devices (ip, nickname, mac, details_json, created_at, updated_at) "
        "VALUES (?, NULL, NULL, NULL, ?, ?)",
        (ip, t, t),
    )
    return int(cur.lastrowid), True


def touch_device(
    conn: sqlite3.Connection,
    device_id: int,
    *,
    mac: str | None = None,
) -> None:
    t = now()
    if mac:
        conn.execute(
            "UPDATE devices SET mac = COALESCE(?, mac), updated_at = ? WHERE id = ?",
            (mac, t, device_id),
        )
    else:
        conn.execute(
            "UPDATE devices SET updated_at = ? WHERE id = ?",
            (t, device_id),
        )


def update_nickname(conn: sqlite3.Connection, device_id: int, nickname: str) -> None:
    conn.execute(
        "UPDATE devices SET nickname = ?, updated_at = ? WHERE id = ?",
        (nickname or None, now(), device_id),
    )


def _normalize_mac(mac: str | None) -> str:
    return (mac or "").strip().lower()


def mac_group_for_mac(
    conn: sqlite3.Connection, mac: str | None
) -> sqlite3.Row | None:
    m = _normalize_mac(mac)
    if not m:
        return None
    return conn.execute(
        "SELECT g.id, g.nickname "
        "FROM mac_groups g JOIN mac_group_members m ON m.group_id = g.id "
        "WHERE LOWER(TRIM(m.mac)) = ? LIMIT 1",
        (m,),
    ).fetchone()


def list_mac_group_members(
    conn: sqlite3.Connection, group_id: int
) -> list[str]:
    return [
        str(r["mac"])
        for r in conn.execute(
            "SELECT mac FROM mac_group_members WHERE group_id = ? ORDER BY mac",
            (group_id,),
        )
    ]


def list_mac_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Groups with their member MACs (sorted)."""
    out: list[dict[str, Any]] = []
    for grow in conn.execute(
        "SELECT id, nickname FROM mac_groups ORDER BY LOWER(nickname), id"
    ).fetchall():
        out.append(
            {
                "id": int(grow["id"]),
                "nickname": str(grow["nickname"]),
                "members": list_mac_group_members(conn, int(grow["id"])),
            }
        )
    return out


def mac_group_membership_map(
    conn: sqlite3.Connection,
) -> dict[str, dict[str, Any]]:
    """MAC (lowercased) -> {'group_id': int, 'nickname': str}."""
    out: dict[str, dict[str, Any]] = {}
    for r in conn.execute(
        "SELECT LOWER(TRIM(m.mac)) AS mac, g.id AS gid, g.nickname AS nick "
        "FROM mac_group_members m JOIN mac_groups g ON g.id = m.group_id"
    ).fetchall():
        out[str(r["mac"])] = {"group_id": int(r["gid"]), "nickname": str(r["nick"])}
    return out


def create_mac_group(conn: sqlite3.Connection, nickname: str) -> int:
    name = (nickname or "").strip()
    if not name:
        raise ValueError("mac group nickname is required")
    t = now()
    cur = conn.execute(
        "INSERT INTO mac_groups (nickname, created_at, updated_at) VALUES (?, ?, ?)",
        (name, t, t),
    )
    return int(cur.lastrowid)


def rename_mac_group(
    conn: sqlite3.Connection, group_id: int, nickname: str
) -> None:
    name = (nickname or "").strip()
    if not name:
        raise ValueError("mac group nickname is required")
    conn.execute(
        "UPDATE mac_groups SET nickname = ?, updated_at = ? WHERE id = ?",
        (name, now(), group_id),
    )


def delete_mac_group(conn: sqlite3.Connection, group_id: int) -> None:
    conn.execute("DELETE FROM mac_groups WHERE id = ?", (group_id,))


def add_mac_to_group(
    conn: sqlite3.Connection, group_id: int, mac: str
) -> None:
    m = _normalize_mac(mac)
    if not m:
        return
    conn.execute(
        "DELETE FROM mac_group_members WHERE LOWER(TRIM(mac)) = ?", (m,)
    )
    conn.execute(
        "INSERT INTO mac_group_members (group_id, mac) VALUES (?, ?)",
        (group_id, m),
    )
    conn.execute(
        "UPDATE mac_groups SET updated_at = ? WHERE id = ?", (now(), group_id)
    )


def remove_mac_from_group(
    conn: sqlite3.Connection, group_id: int, mac: str
) -> None:
    m = _normalize_mac(mac)
    if not m:
        return
    conn.execute(
        "DELETE FROM mac_group_members WHERE group_id = ? AND LOWER(TRIM(mac)) = ?",
        (group_id, m),
    )
    conn.execute(
        "UPDATE mac_groups SET updated_at = ? WHERE id = ?", (now(), group_id)
    )


def known_macs(conn: sqlite3.Connection) -> list[str]:
    """Distinct non-empty MACs (lowercased) seen on devices, sorted."""
    seen: set[str] = set()
    for r in conn.execute("SELECT mac FROM devices WHERE mac IS NOT NULL"):
        m = _normalize_mac(r["mac"])
        if m:
            seen.add(m)
    return sorted(seen)


def expand_device_group_ids(
    conn: sqlite3.Connection, device_id: int
) -> list[int]:
    """All device rows in the same MAC supergroup (or MAC) as device_id."""
    row = get_device_by_id(conn, device_id)
    if not row:
        return [device_id]
    mac = _normalize_mac(row["mac"])
    if not mac:
        return [device_id]
    grp = mac_group_for_mac(conn, mac)
    if grp is not None:
        macs = list_mac_group_members(conn, int(grp["id"]))
        if macs:
            placeholders = ",".join("?" * len(macs))
            out = [
                int(r["id"])
                for r in conn.execute(
                    f"SELECT id FROM devices WHERE LOWER(TRIM(mac)) IN ({placeholders}) "
                    "ORDER BY id",
                    tuple(macs),
                )
            ]
            return out or [device_id]
    out = [
        int(r["id"])
        for r in conn.execute(
            "SELECT id FROM devices WHERE LOWER(TRIM(mac)) = ? ORDER BY id",
            (mac,),
        )
    ]
    return out or [device_id]


def update_nickname_mac_group(
    conn: sqlite3.Connection, anchor_device_id: int, nickname: str
) -> None:
    """Apply nickname to every row with the same MAC as anchor (or single row if no MAC)."""
    row = get_device_by_id(conn, anchor_device_id)
    if not row:
        return
    nick = (nickname or "").strip() or ""
    mac = (row["mac"] or "").strip().lower()
    t = now()
    if mac:
        conn.execute(
            "UPDATE devices SET nickname = ?, updated_at = ? "
            "WHERE LOWER(TRIM(mac)) = ?",
            (nick or None, t, mac),
        )
    else:
        conn.execute(
            "UPDATE devices SET nickname = ?, updated_at = ? WHERE id = ?",
            (nick or None, t, anchor_device_id),
        )


def sync_nicknames_for_shared_macs(conn: sqlite3.Connection) -> None:
    """If several rows share a MAC and at least one has a nickname, copy it to empty rows."""
    by_mac: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in conn.execute("SELECT id, nickname, mac FROM devices"):
        m = (row["mac"] or "").strip().lower()
        if m:
            by_mac[m].append(row)
    for rlist in by_mac.values():
        if len(rlist) < 2:
            continue
        chosen = ""
        for r in sorted(rlist, key=lambda x: int(x["id"])):
            n = (r["nickname"] or "").strip()
            if n:
                chosen = n
                break
        if not chosen:
            continue
        for r in rlist:
            if not (r["nickname"] or "").strip():
                update_nickname(conn, int(r["id"]), chosen)


def update_details(conn: sqlite3.Connection, device_id: int, details: Any) -> None:
    payload = json.dumps(details, ensure_ascii=False, sort_keys=True)
    conn.execute(
        "UPDATE devices SET details_json = ?, updated_at = ? WHERE id = ?",
        (payload, now(), device_id),
    )


def append_ping_log(
    conn: sqlite3.Connection,
    device_id: int,
    *,
    reachable: bool,
    latency_ms: float | None,
    raw_output: str,
) -> None:
    conn.execute(
        "INSERT INTO ping_logs (device_id, ts, reachable, latency_ms, raw_output) "
        "VALUES (?, ?, ?, ?, ?)",
        (device_id, now(), 1 if reachable else 0, latency_ms, raw_output),
    )


def purge_old_logs(conn: sqlite3.Connection, retention_seconds: float) -> int:
    cutoff = now() - retention_seconds
    cur = conn.execute("DELETE FROM ping_logs WHERE ts < ?", (cutoff,))
    return int(cur.rowcount or 0)


def list_devices(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM devices ORDER BY "
            "CASE WHEN nickname IS NULL OR nickname = '' THEN 1 ELSE 0 END, "
            "nickname COLLATE NOCASE, ip"
        )
    )


def get_device_by_ip(conn: sqlite3.Connection, ip: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM devices WHERE ip = ?", (ip,)).fetchone()


def get_device_by_id(conn: sqlite3.Connection, device_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()


def known_ips(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT ip FROM devices").fetchall()
    return {str(r["ip"]) for r in rows}


def fetch_logs_since(
    conn: sqlite3.Connection, device_id: int, since_ts: float
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT ts, reachable, latency_ms, raw_output FROM ping_logs "
            "WHERE device_id = ? AND ts >= ? ORDER BY ts ASC",
            (device_id, since_ts),
        )
    )


def fetch_logs_for_devices(
    conn: sqlite3.Connection, device_ids: Sequence[int], since_ts: float
) -> list[sqlite3.Row]:
    """All ping samples for several device rows, merged in chronological order."""
    ids = tuple(int(x) for x in device_ids)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    return list(
        conn.execute(
            f"SELECT ts, reachable, latency_ms, raw_output FROM ping_logs "
            f"WHERE device_id IN ({placeholders}) AND ts >= ? ORDER BY ts ASC",
            (*ids, since_ts),
        )
    )


def last_log(conn: sqlite3.Connection, device_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT ts, reachable, latency_ms, raw_output FROM ping_logs "
        "WHERE device_id = ? ORDER BY ts DESC LIMIT 1",
        (device_id,),
    ).fetchone()


def last_log_among(
    conn: sqlite3.Connection, device_ids: Sequence[int]
) -> sqlite3.Row | None:
    ids = tuple(int(x) for x in device_ids)
    if not ids:
        return None
    if len(ids) == 1:
        return last_log(conn, ids[0])
    placeholders = ",".join("?" * len(ids))
    return conn.execute(
        f"SELECT ts, reachable, latency_ms, raw_output FROM ping_logs "
        f"WHERE device_id IN ({placeholders}) ORDER BY ts DESC LIMIT 1",
        ids,
    ).fetchone()


def last_ping_before_many(
    conn: sqlite3.Connection,
    device_ids: Sequence[int],
    before_ts: float,
) -> sqlite3.Row | None:
    """Most recent ping among device_ids strictly before before_ts."""
    ids = tuple(int(x) for x in device_ids)
    if not ids:
        return None
    placeholders = ",".join("?" * len(ids))
    return conn.execute(
        f"SELECT ts, reachable FROM ping_logs WHERE device_id IN ({placeholders}) "
        "AND ts < ? ORDER BY ts DESC LIMIT 1",
        (*ids, before_ts),
    ).fetchone()
