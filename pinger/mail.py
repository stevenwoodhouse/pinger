"""SMTP alerts for new LAN devices."""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from email.message import EmailMessage

from pinger import config

log = logging.getLogger("pinger.mail")


def _deliver_email(msg: EmailMessage) -> None:
    """Send ``msg`` using configured SMTP. Requires ``PINGER_SMTP_HOST``."""
    host = config.SMTP_HOST
    if not host:
        raise RuntimeError("PINGER_SMTP_HOST is not set")

    if config.SMTP_PORT == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, config.SMTP_PORT, context=context) as smtp:
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, config.SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            if config.SMTP_USE_TLS:
                context = ssl.create_default_context()
                smtp.starttls(context=context)
                smtp.ehlo()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)


def send_new_device_alert(
    to_addr: str,
    *,
    ip: str,
    mac: str | None,
    device_id: int,
    latency_ms: float | None,
    network: str,
) -> None:
    """Send a plain-text email. No-op if ``PINGER_SMTP_HOST`` is unset."""
    if not config.SMTP_HOST:
        return

    from_addr = config.SMTP_FROM or "pinger@localhost"
    subject = f"[Pinger] New device: {ip}"
    lines = [
        "A host responded on the LAN that was not in the database before this sweep.",
        "",
        f"IP: {ip}",
        f"MAC (from ARP if seen): {mac or '(none)'}",
        f"Device row id: {device_id}",
        f"Scan network: {network}",
        f"Ping latency (this sweep): {latency_ms} ms" if latency_ms is not None else "Ping latency (this sweep): (n/a)",
        "",
        f"Server host: {socket.gethostname()}",
    ]
    body = "\n".join(lines)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    _deliver_email(msg)

    log.info("Sent new-device alert to %s for ip=%s", to_addr, ip)


def send_test_email(to_addr: str) -> None:
    """Send a one-off test message to ``to_addr``. Requires SMTP to be configured."""
    from_addr = config.SMTP_FROM or "pinger@localhost"
    host = socket.gethostname()
    subject = "[Pinger] Test email"
    body = (
        "This is a manual test message from Pinger.\n\n"
        f"If you are reading this, outbound SMTP from host {host!r} is working.\n"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    _deliver_email(msg)

    log.info("Sent test email to %s", to_addr)
