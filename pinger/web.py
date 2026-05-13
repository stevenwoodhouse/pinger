"""Flask HTTP UI and JSON API."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from ipaddress import IPv4Address
from collections.abc import Iterable
from typing import Any

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template_string,
    request,
    url_for,
)

from pinger import config
from pinger import db as dbm
from pinger import mail as mailer

STYLES_CORE = r"""
    :root {
      --bg: #0f1419;
      --panel: #1a2332;
      --text: #e7ecf3;
      --muted: #8b9bb4;
      --up: #3ecf8e;
      --down: #f07178;
      --accent: #5aa7ff;
    }
    * { box-sizing: border-box; }
    html { overflow-x: hidden; }
    body {
      margin: 0; font-family: ui-sans-serif, system-ui, sans-serif;
      background: radial-gradient(1200px 600px at 20% -10%, #1b2a44 0%, var(--bg) 55%);
      color: var(--text); min-height: 100vh;
      overflow-x: hidden;
      width: 100%;
    }
    .shell {
      width: min(100%, 52rem);
      margin-inline: auto;
      min-width: 0;
      box-sizing: border-box;
    }
    header {
      padding: 1rem clamp(0.75rem, 3vw, 1.25rem);
      border-bottom: 1px solid #243049;
      display: flex; flex-wrap: wrap; gap: .75rem 1rem;
      align-items: baseline; justify-content: space-between;
      width: 100%;
      min-width: 0;
    }
    h1 { margin: 0; font-size: 1.25rem; letter-spacing: .02em; }
    .muted { color: var(--muted); font-size: .9rem; }
    main {
      padding: 1rem clamp(0.75rem, 3vw, 1.25rem) 2rem;
      width: 100%;
      min-width: 0;
    }
    .toolbar {
      display: flex; flex-wrap: wrap; gap: .75rem;
      align-items: center; margin-bottom: 1rem;
      min-width: 0;
    }
    button, input[type=text], input[type=email], input[type=password] {
      background: var(--panel); border: 1px solid #2c3d5c;
      color: var(--text); padding: .45rem .7rem; border-radius: 8px;
      font: inherit;
    }
    button { cursor: pointer; }
    button.primary { border-color: #3f5e8a; background: #223149; }
    button.primary:hover { background: #2a3c5c; }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: .75rem;
      width: 100%;
      min-width: 0;
    }
    .card {
      background: linear-gradient(160deg, #1c2738 0%, var(--panel) 100%);
      border: 1px solid #263652; border-radius: 12px; padding: 1rem 1.1rem;
      width: 100%;
      min-width: 0;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .row-top {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: .5rem;
    }
    @media (min-width: 36rem) {
      .row-top {
        flex-direction: row;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: flex-start;
      }
    }
    .ip {
      font-family: ui-monospace, monospace;
      font-size: .92rem;
      color: var(--accent);
      word-break: break-word;
      max-width: 100%;
    }
    .ip .also { color: var(--muted); font-size: .82rem; font-family: ui-sans-serif, system-ui, sans-serif; }
    .ip .ip-secondary { font-weight: 400; }
    .nick { font-weight: 600; font-size: 1.05rem; }
    .pill {
      display: inline-block; padding: .15rem .55rem; border-radius: 999px;
      font-size: .75rem; font-weight: 600; letter-spacing: .03em;
    }
    .pill.up { background: #163d2c; color: var(--up); }
    .pill.down { background: #3a1f24; color: var(--down); }
    .pill.unk { background: #2a2f3a; color: var(--muted); }
    pre {
      margin: .6rem 0 0; font-size: .78rem; color: var(--muted);
      white-space: pre-wrap; word-break: break-word;
      max-height: 8rem; overflow: auto;
    }
    .spark {
      display: flex; gap: 2px; align-items: flex-end;
      height: 28px; margin-top: .6rem;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      overflow-x: auto;
      overscroll-behavior-x: contain;
      -webkit-overflow-scrolling: touch;
    }
    .spark i {
      flex: 1 1 3px;
      min-width: 3px;
      border-radius: 2px;
      background: #2c3548;
    }
    .spark i.on { background: var(--up); }
    .spark i.off { background: var(--down); }
    .spark i.unk { background: #2c3548; }
    form.inline { display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .55rem; min-width: 0; }
    form.inline input[type=text] { flex: 1 1 8rem; min-width: 0; }
    .dash-settings {
      width: 100%;
      box-sizing: border-box;
      padding: 0 clamp(0.75rem, 3vw, 1.25rem) 1rem;
    }
    .dash-settings-inner {
      border: 2px solid var(--accent);
      border-radius: 12px;
      padding: 1rem 1.05rem 0.95rem;
      background: #152238;
      box-shadow: 0 6px 28px rgba(0, 0, 0, 0.4);
      max-width: 100%;
    }
    .settings-heading {
      margin: 0 0 0.65rem 0;
      font-size: 1.08rem;
      font-weight: 700;
      color: var(--text);
      letter-spacing: 0.02em;
    }
    .email-prefs-form .notify-field {
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      max-width: 36rem;
      margin: 0 0 0.75rem 0;
    }
    .email-prefs-form .notify-field label {
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--text);
    }
    .email-prefs-form .notify-field input[type=text] {
      width: 100%;
      font-size: 1rem;
      min-height: 2.35rem;
    }
    .settings-sub {
      margin: 1rem 0 0.35rem 0;
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text);
      letter-spacing: 0.02em;
    }
    .smtp-summary {
      margin: 0 0 0.65rem 0;
      font-size: 0.82rem;
      line-height: 1.45;
      word-break: break-word;
    }
    .smtp-grid {
      display: grid;
      gap: 0.65rem;
      max-width: 36rem;
      margin: 0.35rem 0 0.75rem 0;
    }
    .smtp-grid label {
      display: block;
      font-size: 0.82rem;
      font-weight: 500;
      color: var(--muted);
      margin-bottom: 0.2rem;
    }
    .smtp-grid input[type=text],
    .smtp-grid input[type=password],
    .smtp-grid select {
      width: 100%;
      box-sizing: border-box;
      min-height: 2.35rem;
    }
    .smtp-grid select {
      background: var(--panel);
      border: 1px solid #2c3d5c;
      color: var(--text);
      padding: 0.45rem 0.7rem;
      border-radius: 8px;
      font: inherit;
    }
    .smtp-pass-note { font-size: 0.78rem; color: var(--muted); margin: 0.15rem 0 0 0; }
    .smtp-clear-row { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; margin: 0.15rem 0 0 0; }
    .smtp-clear-row input { width: auto; min-height: auto; }
    .email-prefs-form .settings-save-row { margin-top: 0.35rem; }
    .settings-hint {
      margin: 0.35rem 0 0 0;
      font-size: 0.82rem;
      line-height: 1.45;
    }
    @media (max-width: 22rem) {
      form.inline { flex-direction: column; align-items: stretch; }
      form.inline button { width: 100%; }
    }
    a { color: var(--accent); }
    .navlinks { margin-top: .35rem; font-size: .88rem; }
    .navlinks a { font-weight: 500; }
"""

STYLES_UPTIME_EXTRA = r"""
    .upt-filters { display: flex; flex-wrap: wrap; gap: .6rem; align-items: center; margin-bottom: 1.25rem; }
    .upt-filters label { color: var(--muted); font-size: .88rem; }
    select.upt-select {
      background: var(--panel); border: 1px solid #2c3d5c; color: var(--text);
      padding: .45rem .6rem; border-radius: 8px; font: inherit; min-width: 0; flex: 1 1 12rem;
      max-width: 100%;
    }
    .upt-intro { color: var(--muted); font-size: .88rem; margin: 0 0 1rem 0; line-height: 1.45; }
    .upt-card { margin-bottom: 1.75rem; }
    .upt-meta { color: var(--muted); font-size: .82rem; margin: .35rem 0 0 0; line-height: 1.4; }
    .upt-legend {
      font-size: .74rem; color: var(--muted); margin-top: .5rem;
      display: flex; flex-wrap: wrap; gap: .85rem;
    }
    .upt-leg i { font-style: normal; display:inline-block; width:.65rem;height:.65rem;margin-right:.25rem;border-radius:2px;vertical-align:middle;}
    .upt-leg i.up { background: var(--up); }
    .upt-leg i.down { background: var(--down); }
    .upt-leg i.unk { background: #3a465c; border: 1px solid #4d5f7a;}
    .upt-section-title { margin: .75rem 0 .35rem 0; font-size: .95rem; font-weight: 600; letter-spacing:.02em; }
    .upt-hour-head { margin: 1rem 0 .4rem 0; font-size: .9rem; color: var(--text); font-weight: 600;}
    .upt-bar-row {
      display: flex;
      gap: clamp(4px, 1.4vw, 10px); align-items: flex-end; justify-content: space-between;
      min-height: 152px;
      padding: .35rem .15rem .2rem 0;
      border-bottom: 1px solid #2a3548;
      overflow-x: auto;
    }
    .upt-col { flex: 1 1 0; min-width: clamp(38px, 8vw, 52px); max-width: 64px;
      display: flex; flex-direction: column; align-items: center; gap: .38rem;}
    .upt-stack {
      width: 100%; height: 128px;
      border: 1px solid #3a5070; border-radius: 8px; overflow: hidden;
      display: flex; flex-direction: column;
      cursor: pointer; text-decoration: none; color: inherit;
      outline-offset: 2px;
      box-sizing: border-box;
      background: #141c2a;
    }
    .upt-stack:hover { border-color: #5aa7ff; }
    .upt-stack.sel { box-shadow: 0 0 0 2px #5aa7ff; border-color: #5aa7ff; }
    .upt-stack.empty { cursor: pointer; }
    .upt-seg {
      flex: none;
      flex-shrink: 0;
      min-height: 0;
      width: 100%;
    }
    .upt-seg.up { background: linear-gradient(180deg, #4dd69a 0%, #2a8f5f 100%); }
    .upt-seg.down { background: linear-gradient(180deg, #fb9aa4 0%, #c84855 100%); }
    .upt-seg.unk { background: repeating-linear-gradient(
      -45deg, #2c3548, #2c3548 4px, #252f40 4px, #252f40 8px
    ); border-top: 1px solid #3d4a61; border-bottom: 1px solid #3d4a61;
    }
    .upt-stack.empty .upt-seg.fill, .upt-mini .upt-seg.fill {
      height: 100% !important; min-height: 100%; opacity: .55;
    }
    .upt-day-lab { font-size: .62rem; color: var(--muted); text-align: center;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; width:100%; max-width:100%; }
    .upt-day-sub { font-size: .62rem; color: #7286a8; margin-top:.1rem; text-align:center; width:100%;}
    .upt-hour-grid { display: grid; grid-template-columns: repeat(12, minmax(0,1fr)); gap: .4rem;}
    @media (max-width: 26rem){ .upt-hour-grid { grid-template-columns: repeat(6, minmax(0,1fr)); } }
    .upt-hour-slot { font-size:.58rem;color:var(--muted);display:flex;flex-direction:column;align-items:center;gap:.28rem;}
    .upt-mini {
      width:100%; height:76px;border:1px solid #354560;border-radius:6px;overflow:hidden;
      display:flex;flex-direction:column;background:#141c2a;
    }
    .upt-clear-day { margin: .65rem 0 0;font-size:.85rem;display:inline-block;}
"""

INDEX_HTML = (
    r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Pinger — LAN status</title>
  <style>"""
    + STYLES_CORE
    + r"""</style>
</head>
<body>
  <div class="shell">
  <header>
    <div>
      <h1>LAN ping monitor</h1>
      <div class="muted">Scan: {{ network }} · Interval: {{ interval }} · Retention: {{ retention }}d</div>
      <div class="muted" style="font-size:.88rem;margin-top:.35rem">Last sweep: {{ last_sweep }}</div>
      <div class="navlinks">
        <a href="{{ url_for('uptime_page') }}">{{ retention }}d uptime history</a>
        <span class="muted"> · </span>
        <a href="{{ url_for('preferences_page') }}">Preferences</a>
      </div>
    </div>
      <div class="muted">Server time: {{ now }}</div>
  </header>
  <main>
    {% if sweep_started %}
    <p class="muted" style="margin:0 0 1rem 0;">
      Sweep is running in the background. Refresh the page after a short wait to see updates.
      If nothing changes, check <code style="background:#243049;padding:2px 6px;border-radius:4px">sudo journalctl -u pinger -n 120 --no-pager</code>
    </p>
    {% endif %}
    <div class="toolbar">
      <form method="post" action="{{ url_for('trigger_sweep') }}" style="margin:0">
        <button class="primary" type="submit">Run sweep now</button>
      </form>
      <form method="post" action="{{ url_for('add_device') }}" class="inline" style="margin:0">
        <input name="ip" type="text" placeholder="Watch IP (e.g. 192.168.1.50)" required />
        <input name="nickname" type="text" placeholder="Optional nickname" />
        <button type="submit">Add / watch</button>
      </form>
    </div>
    <div class="grid">
      {% for d in devices %}
      <div class="card">
        <div class="row-top">
          <div>
            <div class="nick">{{ d.nickname or 'Unnamed device' }}</div>
            <div class="ip">
              <strong>{{ d.current_ip }}</strong>
              {% if d.other_ips %}<span class="also"> · also </span>{% for oip in d.other_ips %}<span class="ip-secondary">{{ oip }}</span>{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}
              {% if d.mac %}<span class="muted" style="font-family:ui-sans-serif,sans-serif;font-size:.85rem"> · {{ d.mac }}</span>{% endif %}
            </div>
          </div>
          <div>
            {% if d.last is none %}
              <span class="pill unk">no data</span>
            {% elif d.last.reachable %}
              <span class="pill up">up</span>
            {% else %}
              <span class="pill down">down</span>
            {% endif %}
            {% if d.last and d.last.latency_ms is not none %}
              <span class="muted" style="margin-left:.35rem">{{ d.last.latency_ms | round(1) }} ms</span>
            {% endif %}
          </div>
        </div>
        {% if d.bars %}
        <div class="spark" title="Last week (one bar per ~30m slot, newest right)">
          {% for s in d.bars %}<i class="{{ s }}"></i>{% endfor %}
        </div>
        {% endif %}
        {% if d.details %}
        <pre>{{ d.details }}</pre>
        {% endif %}
        <p class="muted" style="margin:.55rem 0 0;font-size:.78rem">Last sweep: {{ last_sweep }}</p>
        <p class="muted" style="margin:.55rem 0 0;font-size:.82rem">
          <a href="{{ url_for('uptime_page', device=d.id) }}">{{ retention }}d timeline for this device</a>
        </p>
        <form class="inline" method="post" action="{{ url_for('set_nickname', device_id=d.id) }}">
          <input name="nickname" type="text" value="{{ d.nickname or '' }}" placeholder="Nickname" />
          <button type="submit">Save name</button>
        </form>
      </div>
      {% else %}
      <p class="muted">No devices yet. Run a sweep or add an IP to watch.</p>
      {% endfor %}
    </div>
  </main>
  </div>
</body>
</html>
"""
)

PREFERENCES_HTML = (
    r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Pinger — Preferences</title>
  <style>"""
    + STYLES_CORE
    + r"""</style>
</head>
<body>
  <div class="shell">
  <header>
    <div>
      <h1>Preferences</h1>
      <div class="muted">Scan: {{ network }} · Retention: {{ retention }}d</div>
      <div class="muted" style="font-size:.88rem;margin-top:.35rem">Last sweep: {{ last_sweep }}</div>
      <div class="navlinks">
        <a href="{{ url_for('index') }}">Dashboard</a>
        <span class="muted"> · </span>
        <a href="{{ url_for('uptime_page') }}">{{ retention }}d uptime history</a>
      </div>
    </div>
    <div class="muted">Server time: {{ now }}</div>
  </header>
  <main>
    <div class="dash-settings-inner" style="max-width:100%;box-sizing:border-box;">
      <h2 class="settings-heading" id="email-alerts-heading">Email &amp; alerts</h2>
      <form method="post" action="{{ url_for('save_email_settings') }}" class="email-prefs-form">
        <div class="notify-field">
          <label for="notify-email">Send new-device alerts to</label>
          <input id="notify-email" name="notify_email" type="text" inputmode="email" autocomplete="email"
            value="{{ notify_email }}" placeholder="you@example.com — leave empty to turn off" />
        </div>

        <h3 class="settings-sub" id="smtp-heading">SMTP sender (optional)</h3>
        <p class="muted smtp-summary">Effective: {{ smtp_summary }}</p>
        <p class="muted settings-hint" style="margin-top:0;margin-bottom:.55rem">
          Values here override the service environment (e.g. <code style="background:#243049;padding:1px 5px;border-radius:4px">PINGER_SMTP_*</code>). Leave a field empty to use the server default. A password stored in the database is kept in plain text — prefer environment variables for production secrets.
        </p>

        <div class="smtp-grid" role="group" aria-labelledby="smtp-heading">
          <div>
            <label for="smtp-host">SMTP host</label>
            <input id="smtp-host" name="smtp_host" type="text" value="{{ smtp_host_override }}"
              placeholder="e.g. smtp.example.com" autocomplete="off" />
          </div>
          <div>
            <label for="smtp-port">Port</label>
            <input id="smtp-port" name="smtp_port" type="text" value="{{ smtp_port_override }}"
              placeholder="587 if empty" inputmode="numeric" autocomplete="off" />
          </div>
          <div>
            <label for="smtp-from">From address</label>
            <input id="smtp-from" name="smtp_from" type="text" value="{{ smtp_from_override }}"
              placeholder="pinger@yourdomain.com" autocomplete="off" />
          </div>
          <div>
            <label for="smtp-user">SMTP username</label>
            <input id="smtp-user" name="smtp_user" type="text" value="{{ smtp_user_override }}" autocomplete="username" />
          </div>
          <div>
            <label for="smtp-password">SMTP password</label>
            <input id="smtp-password" name="smtp_password" type="password" value="" autocomplete="new-password" />
            <p class="smtp-pass-note">{% if smtp_has_stored_password %}A password is saved. Enter a new value to replace it.{% else %}Leave blank to use the server environment password, if any.{% endif %}</p>
            <div class="smtp-clear-row">
              <input type="checkbox" name="clear_smtp_password" value="1" id="smtp-clear-pw" />
              <label for="smtp-clear-pw" style="margin:0;font-weight:400;color:var(--text)">Clear stored password</label>
            </div>
          </div>
          <div>
            <label for="smtp-tls">TLS</label>
            <select id="smtp-tls" name="smtp_use_tls">
              <option value="" {% if smtp_use_tls_choice == "" %}selected{% endif %}>Default (from server environment)</option>
              <option value="1" {% if smtp_use_tls_choice == "1" %}selected{% endif %}>On</option>
              <option value="0" {% if smtp_use_tls_choice == "0" %}selected{% endif %}>Off</option>
            </select>
          </div>
        </div>

        <div class="settings-save-row">
          <button type="submit">Save</button>
        </div>
      </form>

      {% if saved %}
      <p class="muted" style="margin:.35rem 0 0;font-size:.88rem">Saved.</p>
      {% elif err_notify %}
      <p class="muted" style="margin:.35rem 0 0;font-size:.88rem;color:var(--down)">That does not look like a valid alert address (needs @).</p>
      {% elif err_port %}
      <p class="muted" style="margin:.35rem 0 0;font-size:.88rem;color:var(--down)">SMTP port must be a number between 1 and 65535.</p>
      {% endif %}
      {% if notify_email %}
      <form method="post" action="{{ url_for('send_test_notify_email') }}" style="margin:.65rem 0 0">
        <button type="submit">Send test email</button>
      </form>
      {% endif %}
      {% if test_ok %}
      <p class="muted" style="margin:.45rem 0 0;font-size:.88rem">Test email sent — check the inbox (and spam folder).</p>
      {% elif test_err %}
      <p class="muted" style="margin:.45rem 0 0;font-size:.88rem;color:var(--down)">
        {% if test_err_reason == 'noaddr' %}Save an alert address above before sending a test.{% elif test_err_reason == 'nosmtp' %}No SMTP host is configured. Set SMTP host here or <code style="background:#243049;padding:1px 5px;border-radius:4px">PINGER_SMTP_HOST</code> on the server, then try again.{% else %}The test message could not be sent. Check SMTP settings and the service log.{% endif %}
      </p>
      {% endif %}
      <p class="muted settings-hint" style="margin-top:.75rem">
        After the first sweep has completed, Pinger emails the alert address when a new IP responds on the LAN.
      </p>
    </div>
  </main>
  </div>
</body>
</html>
"""
)

UPTIME_HTML = (
    r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Pinger — Uptime history</title>
  <style>"""
    + STYLES_CORE
    + STYLES_UPTIME_EXTRA
    + r"""</style>
</head>
<body>
  <div class="shell">
  <header>
    <div>
      <h1>Uptime history</h1>
      <div class="muted">Scan: {{ network }} · {{ retention }}d window · inferred from pings between sweep intervals</div>
      <div class="muted" style="font-size:.88rem;margin-top:.35rem">Last sweep: {{ last_sweep }}</div>
      <div class="navlinks">
        <a href="{{ url_for('index') }}">Dashboard</a>
        <span class="muted"> · </span>
        <a href="{{ url_for('preferences_page') }}">Preferences</a>
        <span class="muted"> · </span>
        <a href="{{ url_for('uptime_page') }}">All devices</a>
      </div>
    </div>
    <div class="muted">Server time: {{ now }}</div>
  </header>
  <main>
    <form class="upt-filters" method="get" action="{{ url_for('uptime_page') }}">
      <label for="upt-dev">Show</label>
      <select class="upt-select" id="upt-dev" name="device" onchange="this.form.submit()">
        <option value="" {% if filter_device_id is none %}selected{% endif %}>All devices (merge rows with same MAC)</option>
        {% for o in options %}
        <option value="{{ o.id }}" {% if filter_device_id == o.id %}selected{% endif %}>{{ o.label }}</option>
        {% endfor %}
      </select>
    </form>
    <p class="upt-intro">
      Bars are stacked <strong>up</strong> (green) versus <strong>down</strong> (red); hatched fills are stretches with no pings yet (<strong>unknown</strong>). Time is summed from ping to ping across your sweep interval — so short gaps can look bolder than sparse coverage.
      <strong>All devices</strong> merges pings that share the same MAC. Tap a bar to zoom that calendar day into <strong>24 hourly</strong> stacks (same semantics).
    </p>
    <div class="upt-legend"><span class="upt-leg"><i class="up"></i> reachable</span>
      <span class="upt-leg"><i class="down"></i> unreachable</span>
      <span class="upt-leg"><i class="unk"></i> no samples</span></div>

    {% for b in blocks %}
    <section class="card upt-card">
      <div class="nick">{{ b.title }}</div>
      <p class="upt-meta">{{ b.meta }}</p>

      {% if b.hourly_title %}
      <p class="upt-hour-head">{{ b.hourly_title }}</p>
      <div class="upt-hour-grid">
        {% for hr in b.hour_slots %}
        <div class="upt-hour-slot">
          <div class="upt-day-lab" style="font-size:.72rem;color:var(--text)">{{ hr.label }}</div>
          <div class="upt-mini" title="{{ hr.tooltip }}">
            {% if hr.full_unk %}<span class="upt-seg unk fill"></span>{% endif %}
            {% if not hr.full_unk %}
            {% if hr.pct_un > 0 %}<span class="upt-seg unk" style="height: {{ hr.pct_un }}%;"></span>{% endif %}
            {% if hr.pct_dn > 0 %}<span class="upt-seg down" style="height: {{ hr.pct_dn }}%;"></span>{% endif %}
            {% if hr.pct_up > 0 %}<span class="upt-seg up" style="height: {{ hr.pct_up }}%;"></span>{% endif %}
            {% endif %}
          </div>
        </div>
        {% endfor %}
      </div>
      <a class="upt-clear-day" href="{{ b.clear_hourly_url }}">← Back to week view</a>
      {% endif %}

      <div class="upt-section-title">Last {{ retention }} days (calendar days)</div>
      {% if b.day_slots %}
      <div class="upt-bar-row">
        {% for d in b.day_slots %}
        <div class="upt-col">
          {% if d.empty %}
          <a href="{{ d.pick_url }}" class="upt-stack empty {{ d.sel_class }}" title="{{ d.tooltip }}"{% if d.selected %} aria-current="true"{% endif %}>
            <span class="upt-seg unk fill"></span>
          </a>
          {% else %}
          <a href="{{ d.pick_url }}" class="upt-stack {{ d.sel_class }}" title="{{ d.tooltip }}"{% if d.selected %} aria-current="true"{% endif %}>
            {% if d.pct_un > 0 %}<span class="upt-seg unk" style="height: {{ d.pct_un }}%;"></span>{% endif %}
            {% if d.pct_dn > 0 %}<span class="upt-seg down" style="height: {{ d.pct_dn }}%;"></span>{% endif %}
            {% if d.pct_up > 0 %}<span class="upt-seg up" style="height: {{ d.pct_up }}%;"></span>{% endif %}
          </a>
          {% endif %}
          <span class="upt-day-lab">{{ d.col_label }}</span>
          {% if not d.empty %}
          <span class="upt-day-sub">{{ "%.1f"|format(d.pct_known_up) }}% up · {{ "%.1f"|format(d.pct_known_down) }}% down</span>
          {% endif %}
        </div>
        {% endfor %}
      </div>
      {% elif not b.no_logs_hint %}
      <p class="muted" style="margin:.5rem 0 0">No calendar days intersect the retention window.</p>
      {% endif %}
      {% if b.no_logs_hint %}
      <p class="muted" style="margin:.5rem 0 0">No ping samples in this retention window yet — run a sweep and check back.</p>
      {% endif %}
    </section>
    {% else %}
    <p class="muted">No devices yet.</p>
    {% endfor %}
  </main>
  </div>
</body>
</html>
"""
)


def _fmt_details(details_json: str | None) -> str:
    if not details_json:
        return ""
    try:
        obj = json.loads(details_json)
    except json.JSONDecodeError:
        return details_json
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _bucket_key(ts: float, bucket: int) -> int:
    return int(ts // bucket)


def _uptime_bars(
    logs: list[Any],
    *,
    now_ts: float,
    retention_sec: float,
    bucket_sec: int,
) -> list[str]:
    """Return list of 'on'|'off'|'unk' for each time bucket in the retention window."""
    start = now_ts - retention_sec
    n_buckets = max(1, int(retention_sec // bucket_sec))
    # bucket_index -> best known state: None unknown, True up, False down
    state: list[bool | None] = [None] * n_buckets

    for row in logs:
        ts = float(row["ts"])
        if ts < start:
            continue
        idx = int((ts - start) // bucket_sec)
        if idx < 0 or idx >= n_buckets:
            continue
        state[idx] = bool(row["reachable"])

    return ["unk" if v is None else ("on" if v else "off") for v in state]


def _squash_logs_by_timestamp(logs: Iterable[Any]) -> list[Any]:
    ls = sorted(logs, key=lambda r: float(r["ts"]))
    out: list[Any] = []
    for r in ls:
        if out and abs(float(out[-1]["ts"]) - float(r["ts"])) < 5e-2:
            out[-1] = r
        else:
            out.append(r)
    return out


def _coverage_segments(
    sorted_logs: list[Any],
    *,
    t0: float,
    t1: float,
    prior_reachable: bool | None,
) -> list[tuple[float, float, bool | None]]:
    """Half-open semantics on [lo, hi) cover [t0, t1) from ping-derived hold states."""
    segs: list[tuple[float, float, bool | None]] = []
    state = prior_reachable
    t = t0
    for row in sorted_logs:
        ts_r = float(row["ts"])
        if ts_r < t0:
            state = bool(row["reachable"])
            t = max(t, ts_r)
            continue
        boundary = min(ts_r, t1)
        if boundary > t:
            segs.append((t, boundary, state))
        if ts_r >= t1:
            return segs
        state = bool(row["reachable"])
        t = ts_r
    if t < t1:
        segs.append((t, t1, state))
    return segs


def _pour_segment_into_daily(
    seg_lo: float,
    seg_hi: float,
    state: bool | None,
    daily: defaultdict[str, dict[str, float]],
) -> None:
    t = seg_lo
    while t < seg_hi:
        lt = datetime.fromtimestamp(t)
        dday = lt.date()
        midnight = datetime(dday.year, dday.month, dday.day).timestamp()
        next_mid = (datetime(dday.year, dday.month, dday.day) + timedelta(days=1)).timestamp()
        chunk_end = min(seg_hi, next_mid)
        dur = chunk_end - t
        if dur > 0:
            key = dday.isoformat()
            b = daily[key]
            if state is True:
                b["up"] += dur
            elif state is False:
                b["dn"] += dur
            else:
                b["un"] += dur
        t = chunk_end


def _pour_segment_into_hourly_for_day(
    seg_lo: float,
    seg_hi: float,
    state: bool | None,
    chosen: date,
    hourly: dict[int, dict[str, float]],
) -> None:
    day0 = datetime(chosen.year, chosen.month, chosen.day).timestamp()
    day1 = (datetime(chosen.year, chosen.month, chosen.day) + timedelta(days=1)).timestamp()
    lo = max(seg_lo, day0)
    hi = min(seg_hi, day1)
    t = lo
    while t < hi:
        lt = datetime.fromtimestamp(t)
        hod = lt.hour
        nf = lt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        chunk_end = min(hi, nf.timestamp())
        dur = chunk_end - t
        if dur > 0:
            b = hourly[hod]
            if state is True:
                b["up"] += dur
            elif state is False:
                b["dn"] += dur
            else:
                b["un"] += dur
        t = chunk_end


def _daily_from_segments(
    segments: list[tuple[float, float, bool | None]],
) -> defaultdict[str, dict[str, float]]:
    daily: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"up": 0.0, "dn": 0.0, "un": 0.0}
    )
    for lo, hi, st in segments:
        _pour_segment_into_daily(lo, hi, st, daily)
    return daily


def _hourly_from_segments_for_day(
    segments: list[tuple[float, float, bool | None]],
    chosen: date,
) -> dict[int, dict[str, float]]:
    hourly = {h: {"up": 0.0, "dn": 0.0, "un": 0.0} for h in range(24)}
    for lo, hi, st in segments:
        _pour_segment_into_hourly_for_day(lo, hi, st, chosen, hourly)
    return hourly


def _stack_percents(
    up: float, dn: float, unk: float
) -> tuple[float, float, float, bool]:
    total = max(0.0, float(up)) + max(0.0, float(dn)) + max(0.0, float(unk))
    if total < 1e-9:
        return 0.0, 0.0, 0.0, True
    pu = 100.0 * float(up) / total
    pd = 100.0 * float(dn) / total
    pun = 100.0 * float(unk) / total
    s = pu + pd + pun
    if abs(s - 100.0) > 1e-3:
        m = max(pu, pd, pun)
        if m == pu:
            pu += 100.0 - s
        elif m == pd:
            pd += 100.0 - s
        else:
            pun += 100.0 - s
    return pu, pd, pun, False


def _uptime_kw(
    device_id: int | None, grp_ix: int | None, *, day_iso: str | None
) -> dict[str, Any]:
    qs: dict[str, Any] = {}
    if device_id is not None:
        qs["device"] = device_id
    if device_id is None and grp_ix is not None:
        qs["grp"] = grp_ix
    if day_iso:
        qs["day"] = day_iso
    return qs


def _calendar_span_days(since_ts: float, now_ts: float) -> list[date]:
    d0 = datetime.fromtimestamp(since_ts).date()
    d1 = datetime.fromtimestamp(now_ts).date()
    out: list[date] = []
    cur = d0
    while cur <= d1:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _build_day_slots_for_block(
    *,
    since_ts: float,
    now_ts: float,
    daily: defaultdict[str, dict[str, float]],
    filter_device_id: int | None,
    grp_ix: int | None,
    outlined_day: date | None,
) -> list[dict[str, Any]]:
    span = _calendar_span_days(since_ts, now_ts)
    slots: list[dict[str, Any]] = []
    for dday in span:
        iso = dday.isoformat()
        b = daily.get(
            iso, {"up": 0.0, "dn": 0.0, "un": 0.0}
        )
        up, dn, un = b["up"], b["dn"], b["un"]
        pu, pd, pun, zmt = _stack_percents(up, dn, un)
        known = up + dn
        pk_up = 100.0 * up / known if known > 1e-9 else 0.0
        pk_dn = 100.0 * dn / known if known > 1e-9 else 0.0
        pick = url_for("uptime_page", **_uptime_kw(filter_device_id, grp_ix, day_iso=iso))
        sel = outlined_day is not None and dday == outlined_day
        col = dday.strftime("%a %d")
        tip = f"{dday.isoformat()}: {up/3600:.2f}h up, {dn/3600:.2f}h down, {un/3600:.2f}h unknown"
        slots.append(
            {
                "empty": zmt,
                "pick_url": pick,
                "selected": sel,
                "sel_class": "sel" if sel else "",
                "col_label": col,
                "tooltip": tip,
                "pct_up": round(pu, 2),
                "pct_dn": round(pd, 2),
                "pct_un": round(pun, 2),
                "pct_known_up": round(pk_up, 1),
                "pct_known_down": round(pk_dn, 1),
            }
        )
    return slots


def _build_hour_slots_for_day(
    detail: date, hourly: dict[int, dict[str, float]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for h in range(24):
        b = hourly[h]
        up, dn, un = b["up"], b["dn"], b["un"]
        pu, pd, pun, zmt = _stack_percents(up, dn, un)
        known = up + dn
        pk_up = 100.0 * up / known if known > 1e-9 else 0.0
        tip = f"{h:02d}:00–{h:02d}:59 — {pk_up:.0f}% up (of known), {un/60:.0f}m unknown"
        rows.append(
            {
                "label": f"{h:02d}",
                "tooltip": tip,
                "pct_up": round(pu, 2),
                "pct_dn": round(pd, 2),
                "pct_un": round(pun, 2),
                "full_unk": zmt,
            }
        )
    return rows


def _group_by_mac(rows: list[Any]) -> list[dict[str, Any]]:
    by_mac: dict[str, list[Any]] = defaultdict(list)
    singles_no_mac: list[Any] = []
    for row in rows:
        m = (row["mac"] or "").strip().lower()
        if m:
            by_mac[m].append(row)
        else:
            singles_no_mac.append(row)
    groups: list[dict[str, Any]] = []
    for _mk, rlist in by_mac.items():
        primary = max(rlist, key=lambda r: float(r["updated_at"]))
        groups.append({"rows": rlist, "primary": primary})
    for row in singles_no_mac:
        groups.append({"rows": [row], "primary": row})

    def sort_key(g: dict[str, Any]) -> tuple[str, str]:
        p = g["primary"]
        return ((p["nickname"] or "").lower(), str(p["ip"]))

    groups.sort(key=sort_key)
    return groups


def _uptime_group_captions(g: dict[str, Any]) -> tuple[str, str]:
    rows = g["rows"]
    primary = g["primary"]
    nick = (primary["nickname"] or "").strip() or "Unnamed device"
    mac = (primary["mac"] or "").strip()
    if len(rows) == 1:
        ip = str(primary["ip"])
        if mac:
            meta = f"MAC {mac} · current IP {ip}"
        else:
            meta = f"No MAC on file yet (tracked by this IP row) · current IP {ip}"
        return nick, meta
    ips = sorted({str(r["ip"]) for r in rows}, key=lambda s: IPv4Address(s))
    ip_join = ", ".join(ips)
    title = f"{nick} ({len(rows)} rows, same MAC)"
    meta = f"MAC {mac} · current IPs on file: {ip_join}"
    return title, meta


def _fmt_ts_local(ts: float | None) -> str:
    if ts is None or ts <= 0:
        return "never"
    return datetime.fromtimestamp(ts).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )


def _device_select_label(row: Any) -> str:
    nick = (row["nickname"] or "").strip() or "Unnamed"
    mac = (row["mac"] or "").strip()
    ip = row["ip"]
    if mac:
        return f"{nick} — {mac} — {ip}"
    return f"{nick} — (no MAC) — {ip}"


def _smtp_prefs_template_context(conn: Any) -> dict[str, Any]:
    """DB override field values + resolved SMTP summary for the preferences page."""
    smtp_host_override = (dbm.get_setting(conn, "smtp_host") or "").strip()
    smtp_port_override = (dbm.get_setting(conn, "smtp_port") or "").strip()
    smtp_user_override = (dbm.get_setting(conn, "smtp_user") or "").strip()
    smtp_from_override = (dbm.get_setting(conn, "smtp_from") or "").strip()
    tls_stored = dbm.get_setting(conn, "smtp_use_tls")
    if tls_stored is None:
        smtp_use_tls_choice = ""
    else:
        smtp_use_tls_choice = (
            "0"
            if str(tls_stored).strip().lower() in ("0", "false", "no", "off")
            else "1"
        )
    p = mailer.load_smtp_params()
    if p:
        tls_l = "TLS on" if p.use_tls else "TLS off"
        auth_l = f"auth as {p.user}" if p.user else "no SMTP auth"
        smtp_summary = (
            f"{p.host}:{p.port}, {tls_l}, {auth_l}, From {p.from_addr}"
        )
    else:
        smtp_summary = (
            "No SMTP host configured yet — set fields below or "
            "PINGER_SMTP_HOST on the server."
        )
    smtp_has_stored_password = dbm.get_setting(conn, "smtp_password") is not None
    return {
        "smtp_host_override": smtp_host_override,
        "smtp_port_override": smtp_port_override,
        "smtp_user_override": smtp_user_override,
        "smtp_from_override": smtp_from_override,
        "smtp_use_tls_choice": smtp_use_tls_choice,
        "smtp_summary": smtp_summary,
        "smtp_has_stored_password": smtp_has_stored_password,
    }


def create_app(runner: object) -> Flask:
    app = Flask(__name__)
    app.config["PINGER_RUNNER"] = runner
    slog = logging.getLogger("pinger.web")

    @app.before_request
    def _open_db() -> None:
        g.db = dbm.connect(config.DB_PATH)
        dbm.init_schema(g.db)

    @app.teardown_appcontext
    def _close_db(_exc: object | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def network_label() -> str:
        try:
            from pinger.discovery import get_scan_network

            return str(get_scan_network(config.NETWORK_CIDR))
        except Exception as exc:  # noqa: BLE001
            return f"(auto-detect error: {exc})"

    @app.get("/")
    def index():
        c = g.db
        dbm.sync_nicknames_for_shared_macs(c)
        devices = []
        now_ts = time.time()
        retention_sec = float(config.RETENTION_DAYS) * 86400.0
        bucket_sec = max(60, min(config.INTERVAL_SEC, 3600))
        since = now_ts - retention_sec

        for grp in _group_by_mac(dbm.list_devices(c)):
            rows = grp["rows"]
            primary = grp["primary"]
            ids = [int(r["id"]) for r in rows]
            p_ip = str(primary["ip"])
            other_ips = sorted(
                (str(r["ip"]) for r in rows if str(r["ip"]) != p_ip),
                key=lambda s: IPv4Address(s),
            )
            last = dbm.last_log_among(c, ids)
            logs = dbm.fetch_logs_for_devices(c, ids, since)
            bars = _uptime_bars(
                logs, now_ts=now_ts, retention_sec=retention_sec, bucket_sec=bucket_sec
            )
            if len(bars) > 400:
                bars = bars[-400:]
            devices.append(
                {
                    "id": int(primary["id"]),
                    "current_ip": p_ip,
                    "other_ips": other_ips,
                    "mac": primary["mac"],
                    "nickname": (primary["nickname"] or "").strip() or None,
                    "details": _fmt_details(primary["details_json"]),
                    "last": (
                        {
                            "reachable": bool(last["reachable"]),
                            "latency_ms": last["latency_ms"],
                        }
                        if last
                        else None
                    ),
                    "bars": bars,
                }
            )

        return render_template_string(
            INDEX_HTML,
            devices=devices,
            network=network_label(),
            interval=f"{config.INTERVAL_SEC // 60} min",
            retention=config.RETENTION_DAYS,
            last_sweep=_fmt_ts_local(dbm.get_last_sweep_finished(c)),
            now=datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            sweep_started=request.args.get("sweep") == "1",
        )

    @app.get("/preferences")
    def preferences_page():
        c = g.db
        ctx = _smtp_prefs_template_context(c)
        return render_template_string(
            PREFERENCES_HTML,
            network=network_label(),
            retention=config.RETENTION_DAYS,
            last_sweep=_fmt_ts_local(dbm.get_last_sweep_finished(c)),
            now=datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            notify_email=(dbm.get_setting(c, "notify_email") or ""),
            saved=request.args.get("saved") == "1"
            or request.args.get("notify") == "1",
            err_notify=request.args.get("notify") == "0"
            or request.args.get("err") == "notify",
            err_port=request.args.get("err") == "port",
            test_ok=request.args.get("test") == "1",
            test_err=request.args.get("test") == "0",
            test_err_reason=(request.args.get("reason") or "").strip(),
            **ctx,
        )

    @app.get("/uptime")
    def uptime_page():
        c = g.db
        raw = (request.args.get("device") or "").strip()
        filter_id: int | None = int(raw) if raw.isdigit() else None
        filter_row: Any | None = None
        if filter_id is not None:
            filter_row = dbm.get_device_by_id(c, filter_id)
            if not filter_row:
                abort(404)

        grp_raw = (request.args.get("grp") or "").strip()
        grp_idx_global: int | None = int(grp_raw) if grp_raw.isdigit() else None

        now_ts = time.time()
        retention_sec = float(config.RETENTION_DAYS) * 86400.0
        since = now_ts - retention_sec

        detail_day: date | None = None
        raw_day = (request.args.get("day") or "").strip()
        if raw_day:
            try:
                cand = date.fromisoformat(raw_day)
                lo_d = datetime.fromtimestamp(since).date()
                hi_d = datetime.fromtimestamp(now_ts).date()
                if lo_d <= cand <= hi_d:
                    detail_day = cand
            except ValueError:
                detail_day = None

        # "All devices" needs grp= to know which MAC group to expand by hour.
        if detail_day is not None and filter_id is None and grp_idx_global is None:
            detail_day = None

        all_rows = dbm.list_devices(c)
        options = [
            {"id": int(grp["primary"]["id"]), "label": _device_select_label(grp["primary"])}
            for grp in _group_by_mac(all_rows)
        ]

        blocks: list[dict[str, Any]] = []

        def add_block_from_ids(
            title: str,
            meta_str: str,
            *,
            device_ids: list[int],
            filter_for_urls: int | None,
            grp_ix_for_urls: int | None,
            no_rows_in_retention: bool,
        ) -> None:
            prior = dbm.last_ping_before_many(c, tuple(device_ids), since)
            prior_state: bool | None = (
                bool(prior["reachable"]) if prior is not None else None
            )
            logs_any = dbm.fetch_logs_for_devices(c, tuple(device_ids), since)
            squash = _squash_logs_by_timestamp(logs_any)
            segs = _coverage_segments(
                squash, t0=since, t1=now_ts, prior_reachable=prior_state
            )
            daily = _daily_from_segments(segs)

            show_hours = detail_day is not None and (
                filter_for_urls is not None or grp_ix_for_urls == grp_idx_global
            )
            outlines_day = detail_day if show_hours else None

            hourly_title = ""
            hour_slots: list[Any] | None = None
            clear_url = url_for(
                "uptime_page",
                **_uptime_kw(filter_for_urls, grp_ix_for_urls, day_iso=None),
            )
            if show_hours and detail_day is not None:
                hou = _hourly_from_segments_for_day(segs, detail_day)
                hour_slots = _build_hour_slots_for_day(detail_day, hou)
                hourly_title = detail_day.strftime("%A %d %B — hourly (local)")

            blocks.append(
                {
                    "title": title,
                    "meta": meta_str,
                    "day_slots": _build_day_slots_for_block(
                        since_ts=since,
                        now_ts=now_ts,
                        daily=daily,
                        filter_device_id=filter_for_urls,
                        grp_ix=grp_ix_for_urls,
                        outlined_day=outlines_day,
                    ),
                    "hourly_title": hourly_title if hour_slots else "",
                    "hour_slots": hour_slots or [],
                    "clear_hourly_url": clear_url,
                    "no_logs_hint": no_rows_in_retention,
                }
            )

        if filter_id is not None and filter_row is not None:
            gid_list = dbm.expand_device_group_ids(c, filter_id)
            row_objs = [
                dbm.get_device_by_id(c, i) for i in gid_list
            ]
            row_objs = [r for r in row_objs if r is not None]
            prim = max(row_objs, key=lambda r: float(r["updated_at"]))
            logs_any = dbm.fetch_logs_for_devices(c, gid_list, since)
            title, meta = _uptime_group_captions({"rows": row_objs, "primary": prim})
            add_block_from_ids(
                title,
                meta,
                device_ids=gid_list,
                filter_for_urls=filter_id,
                grp_ix_for_urls=None,
                no_rows_in_retention=len(logs_any) == 0,
            )
        else:
            for gx, grp in enumerate(_group_by_mac(all_rows)):
                ids_list = [int(r["id"]) for r in grp["rows"]]
                logs_any = dbm.fetch_logs_for_devices(c, ids_list, since)
                title, meta = _uptime_group_captions(grp)
                add_block_from_ids(
                    title,
                    meta,
                    device_ids=ids_list,
                    filter_for_urls=None,
                    grp_ix_for_urls=gx,
                    no_rows_in_retention=len(logs_any) == 0,
                )

        return render_template_string(
            UPTIME_HTML,
            blocks=blocks,
            options=options,
            filter_device_id=filter_id,
            retention=config.RETENTION_DAYS,
            last_sweep=_fmt_ts_local(dbm.get_last_sweep_finished(c)),
            network=network_label(),
            now=datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        )

    @app.post("/action/sweep")
    def trigger_sweep():
        runner = app.config["PINGER_RUNNER"]

        def sweep_job() -> None:
            try:
                runner.run_once_sync()
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                slog.exception("Manual sweep failed in background")

        threading.Thread(
            target=sweep_job, name="pinger-manual-sweep", daemon=True
        ).start()
        return redirect(url_for("index", sweep="1"))

    @app.post("/devices/<int:device_id>/nickname")
    def set_nickname(device_id: int):
        nick = (request.form.get("nickname") or "").strip()
        c = g.db
        row = dbm.get_device_by_id(c, device_id)
        if not row:
            return ("Not found", 404)
        dbm.update_nickname_mac_group(c, device_id, nick)
        return redirect(url_for("index"))

    @app.post("/devices/add")
    def add_device():
        ip = (request.form.get("ip") or "").strip()
        nick = (request.form.get("nickname") or "").strip() or None
        if not ip:
            return redirect(url_for("index"))
        c = g.db
        try:
            did, _created = dbm.get_or_create_device(c, ip)
            if nick:
                dbm.update_nickname(c, did, nick)
        except Exception as exc:  # noqa: BLE001
            return (f"Invalid IP: {exc}", 400)
        return redirect(url_for("index"))

    @app.post("/settings/email")
    @app.post("/settings/notify-email")
    def save_email_settings():
        notify = (request.form.get("notify_email") or "").strip()
        if notify and ("@" not in notify or len(notify) > 254):
            return redirect(url_for("preferences_page", err="notify"))

        smtp_host = (request.form.get("smtp_host") or "").strip()
        smtp_port_raw = (request.form.get("smtp_port") or "").strip()
        smtp_user = (request.form.get("smtp_user") or "").strip()
        smtp_from = (request.form.get("smtp_from") or "").strip()
        smtp_pass = (request.form.get("smtp_password") or "").strip()
        clear_pw = request.form.get("clear_smtp_password") == "1"
        smtp_tls = (request.form.get("smtp_use_tls") or "").strip()

        if smtp_port_raw:
            try:
                pt = int(smtp_port_raw, 10)
                if pt < 1 or pt > 65535:
                    raise ValueError
            except ValueError:
                return redirect(url_for("preferences_page", err="port"))

        c = g.db
        with dbm.transaction(c):
            if notify:
                dbm.set_setting(c, "notify_email", notify)
            else:
                dbm.set_setting(c, "notify_email", "")

            if smtp_host:
                dbm.set_setting(c, "smtp_host", smtp_host)
            else:
                dbm.delete_setting(c, "smtp_host")

            if smtp_port_raw:
                dbm.set_setting(c, "smtp_port", smtp_port_raw)
            else:
                dbm.delete_setting(c, "smtp_port")

            if smtp_user:
                dbm.set_setting(c, "smtp_user", smtp_user)
            else:
                dbm.delete_setting(c, "smtp_user")

            if smtp_from:
                dbm.set_setting(c, "smtp_from", smtp_from)
            else:
                dbm.delete_setting(c, "smtp_from")

            if smtp_pass:
                dbm.set_setting(c, "smtp_password", smtp_pass)
            elif clear_pw:
                dbm.delete_setting(c, "smtp_password")

            if smtp_tls == "1":
                dbm.set_setting(c, "smtp_use_tls", "1")
            elif smtp_tls == "0":
                dbm.set_setting(c, "smtp_use_tls", "0")
            else:
                dbm.delete_setting(c, "smtp_use_tls")

        return redirect(url_for("preferences_page", saved="1"))

    @app.post("/settings/test-email")
    def send_test_notify_email():
        c = g.db
        to_addr = (dbm.get_setting(c, "notify_email") or "").strip()
        if not to_addr:
            return redirect(url_for("preferences_page", test="0", reason="noaddr"))
        if not mailer.smtp_configured():
            return redirect(url_for("preferences_page", test="0", reason="nosmtp"))
        try:
            mailer.send_test_email(to_addr)
        except Exception:
            slog.exception("Test email failed for %s", to_addr)
            return redirect(url_for("preferences_page", test="0", reason="send"))
        return redirect(url_for("preferences_page", test="1"))

    @app.get("/api/status")
    def api_status():
        c = g.db
        out = []
        for row in dbm.list_devices(c):
            did = int(row["id"])
            last = dbm.last_log(c, did)
            details = None
            if row["details_json"]:
                try:
                    details = json.loads(row["details_json"])
                except json.JSONDecodeError:
                    details = row["details_json"]
            out.append(
                {
                    "id": did,
                    "ip": row["ip"],
                    "mac": row["mac"],
                    "nickname": row["nickname"],
                    "details": details,
                    "last_ping": (
                        {
                            "ts": last["ts"],
                            "reachable": bool(last["reachable"]),
                            "latency_ms": last["latency_ms"],
                        }
                        if last
                        else None
                    ),
                }
            )
        return jsonify(
            {
                "network": network_label(),
                "interval_seconds": config.INTERVAL_SEC,
                "retention_days": config.RETENTION_DAYS,
                "devices": out,
            }
        )

    @app.get("/api/devices/<int:device_id>/history")
    def api_history(device_id: int):
        c = g.db
        row = dbm.get_device_by_id(c, device_id)
        if not row:
            return jsonify({"error": "not found"}), 404
        gid_list = dbm.expand_device_group_ids(c, device_id)
        rows_all = [dbm.get_device_by_id(c, i) for i in gid_list]
        rows_all = [r for r in rows_all if r is not None]
        primary = max(rows_all, key=lambda r: float(r["updated_at"]))
        now_ts = time.time()
        since = now_ts - float(config.RETENTION_DAYS) * 86400.0
        logs = dbm.fetch_logs_for_devices(c, gid_list, since)
        points = [
            {
                "ts": r["ts"],
                "reachable": bool(r["reachable"]),
                "latency_ms": r["latency_ms"],
                "raw_output": r["raw_output"],
            }
            for r in logs
        ]
        payload = {
            "device": {
                "id": int(primary["id"]),
                "ip": primary["ip"],
                "mac": primary["mac"],
                "nickname": primary["nickname"],
            },
            "device_ids": gid_list,
            "points": points,
        }
        return jsonify(payload)

    return app
