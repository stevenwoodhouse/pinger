"""SMTP alerts for new LAN devices."""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from pinger import config

log = logging.getLogger("pinger.mail")


@dataclass(frozen=True)
class SMTPParams:
    host: str
    port: int
    user: str
    password: str
    from_addr: str
    use_tls: bool


def _smtp_local_hostname() -> str | None:
    return config.SMTP_LOCAL_HOSTNAME


def _auth_user(smtp: SMTPParams) -> str:
    """Username for SMTP AUTH. Gmail needs the full address; we fall back to From if set."""
    u = (smtp.user or "").strip()
    if u:
        return u
    if (smtp.password or "").strip() and "@" in (smtp.from_addr or ""):
        return smtp.from_addr.strip()
    return ""


def _use_starttls(smtp: SMTPParams) -> bool:
    """STARTTLS is required on standard submission ports (Gmail, etc.)."""
    if smtp.port == 465:
        return False
    if smtp.port in (587, 2525):
        return True
    return smtp.use_tls


def load_smtp_params() -> SMTPParams | None:
    """Resolve SMTP from DB overrides, then environment. Returns None if no host is configured."""
    from pinger import db as dbm

    conn = dbm.connect(config.DB_PATH)
    try:

        def row(key: str) -> str | None:
            v = dbm.get_setting(conn, key)
            if v is None:
                return None
            s = str(v).strip()
            return s if s else None

        h = row("smtp_host")
        host = (h if h is not None else config.SMTP_HOST).strip()
        if not host:
            return None

        p = row("smtp_port")
        if p is not None:
            try:
                port = int(p, 10)
            except ValueError:
                port = config.SMTP_PORT
        else:
            port = config.SMTP_PORT
        if port < 1 or port > 65535:
            port = config.SMTP_PORT

        u = row("smtp_user")
        user = u if u is not None else config.SMTP_USER

        pw_raw = dbm.get_setting(conn, "smtp_password")
        if pw_raw is None:
            password = config.SMTP_PASSWORD
        else:
            password = str(pw_raw)

        f = row("smtp_from")
        from_addr = (
            f if f is not None else (config.SMTP_FROM or "pinger@localhost")
        ).strip() or "pinger@localhost"

        tls_raw = dbm.get_setting(conn, "smtp_use_tls")
        if tls_raw is None:
            use_tls = config.SMTP_USE_TLS
        else:
            use_tls = str(tls_raw).strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )

        return SMTPParams(
            host=host,
            port=port,
            user=user,
            password=password,
            from_addr=from_addr,
            use_tls=use_tls,
        )
    finally:
        conn.close()


def smtp_configured() -> bool:
    p = load_smtp_params()
    return p is not None and bool(p.host.strip())


def _deliver_email(msg: EmailMessage, smtp: SMTPParams) -> None:
    host = smtp.host
    local = _smtp_local_hostname()
    auth_user = _auth_user(smtp)
    pw = smtp.password or ""

    try:
        if smtp.port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                host, smtp.port, context=context, local_hostname=local
            ) as server:
                if auth_user and pw:
                    server.login(auth_user, pw)
                elif pw and not auth_user:
                    raise RuntimeError(
                        "SMTP password is set but username is empty — "
                        "use your full Gmail address as the username (or set From to that address)."
                    )
                server.send_message(msg)
        else:
            with smtplib.SMTP(
                host, smtp.port, timeout=30, local_hostname=local
            ) as server:
                server.ehlo()
                if _use_starttls(smtp):
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()
                if auth_user and pw:
                    server.login(auth_user, pw)
                elif pw and not auth_user:
                    raise RuntimeError(
                        "SMTP password is set but username is empty — "
                        "use your full Gmail address as the username (or set From to that address)."
                    )
                server.send_message(msg)
    except smtplib.SMTPException as exc:
        log.warning("SMTP error to %s:%s: %s", host, smtp.port, exc)
        raise


def send_new_device_alert(
    to_addr: str,
    *,
    ip: str,
    mac: str | None,
    device_id: int,
    latency_ms: float | None,
    network: str,
) -> None:
    """Send a plain-text email. No-op if SMTP host is not configured."""
    smtp = load_smtp_params()
    if not smtp:
        return

    subject = f"[Pinger] New device: {ip}"
    lines = [
        "A host responded on the LAN that was not in the database before this sweep.",
        "",
        f"IP: {ip}",
        f"MAC (from ARP if seen): {mac or '(none)'}",
        f"Device row id: {device_id}",
        f"Scan network: {network}",
        f"Ping latency (this sweep): {latency_ms} ms"
        if latency_ms is not None
        else "Ping latency (this sweep): (n/a)",
        "",
        f"Server host: {socket.gethostname()}",
    ]
    body = "\n".join(lines)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    _deliver_email(msg, smtp)

    log.info("Sent new-device alert to %s for ip=%s", to_addr, ip)


def send_test_email(to_addr: str) -> None:
    """Send a one-off test message to ``to_addr``. Requires SMTP to be configured."""
    smtp = load_smtp_params()
    if not smtp:
        raise RuntimeError("smtp_not_configured")

    hn = socket.gethostname()
    subject = "[Pinger] Test email"
    body = (
        "This is a manual test message from Pinger.\n\n"
        f"If you are reading this, outbound SMTP from host {hn!r} is working.\n"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    _deliver_email(msg, smtp)

    log.info("Sent test email to %s", to_addr)
