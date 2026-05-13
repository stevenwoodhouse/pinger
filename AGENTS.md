# AGENTS.md

Notes for humans and coding agents working in this repo.

## Project overview

Pinger is a small LAN ping monitor service designed to run on a Raspberry Pi (or any Linux box) under systemd. It periodically pings every host on the configured CIDR, persists results in SQLite, exposes a Flask web UI + JSON API, and can email alerts when a previously-unseen IP responds.

Key modules:

- `pinger/config.py` — environment-driven configuration constants.
- `pinger/db.py` — SQLite schema and all data-access helpers. `init_schema` is idempotent (every `CREATE` uses `IF NOT EXISTS`), so on-disk databases auto-upgrade in place.
- `pinger/icmp.py` / `pinger/discovery.py` — ping execution and ARP/network discovery.
- `pinger/worker.py` — `SweepRunner` orchestrates each sweep (ping all targets, persist results, fire new-device alerts).
- `pinger/mail.py` — SMTP plumbing and the new-device / test email senders.
- `pinger/web.py` — Flask app: dashboard, uptime history, preferences, MAC groups, and the JSON API. Templates live inline in this file as `*_HTML` strings rendered via `render_template_string`.
- `pinger/__main__.py` — entrypoint that wires the scheduler and Waitress together.

## Versioning

This project follows [Semantic Versioning](https://semver.org/): **`MAJOR.MINOR.PATCH`**. The version is the single source of truth for what's deployed and is shown in the footer of every web page.

| Change category | Bump |
|---|---|
| Bug fix, log/CSS tweak, internal refactor, dependency bump, docs | **PATCH** (`1.1.0` → `1.1.1`) |
| New page, new setting, new email field, new column you populate but ignore if missing, additive JSON field | **MINOR** (`1.1.0` → `1.2.0`) |
| Change to JSON API shape (renamed/removed field, changed type), removed/renamed route, removed/renamed setting key (`PINGER_*` env var or `pinger_settings` row), DB change requiring a manual migration | **MAJOR** (`1.1.0` → `2.0.0`) |

### Where the version lives

Two files must stay in sync. Bump both in the same commit:

1. `pinger/__init__.py` — `__version__ = "X.Y.Z"`
2. `pyproject.toml` — `version = "X.Y.Z"`

`pinger.web` imports `__version__` and surfaces it (plus the deploy timestamp, derived from the latest `.py` mtime in the package) in the footer of every page.

### When to bump

Bump in the same commit (or PR) that ships the user-visible change. Don't batch up multiple features under one bump unless they ship together.

If a change you're making feels ambiguous, prefer the more cautious bump (MINOR over PATCH, MAJOR over MINOR). It's far cheaper than surprising an operator with a breaking change behind a patch bump.

## Database conventions

- `pinger/db.py:init_schema` is run on every connection open in the web app and at sweep start. All schema is `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` — new tables and indexes added this way are a MINOR change.
- Backwards-incompatible schema work (renaming columns, splitting tables, etc.) needs an explicit migration step in `init_schema` and is a MAJOR change. Document the migration in the bump commit.
- Settings live in `pinger_settings` (key/value strings) and can also be supplied via `PINGER_*` env vars. The DB override wins; removing or renaming a key is MAJOR.

## Email alerts

`pinger.mail.send_new_device_alert` is the canonical alert path. It accepts a `nickname` parameter; the worker (`pinger/worker.py`) resolves the effective nickname using, in order:

1. The MAC supergroup nickname (`mac_group_for_mac`), if the device's MAC belongs to a group.
2. The device row's own nickname (which is propagated across rows sharing a MAC by `sync_nicknames_for_shared_macs`).
3. `"Unknown Device"` as the literal fallback in the email body and subject.

Changes to the subject line or to the set of fields included in the body are at minimum a MINOR bump because operators may parse alerts.

## UI conventions

- All templates are server-rendered Jinja strings in `pinger/web.py`. No client-side framework.
- Styles are centralized in `STYLES_CORE` (and `STYLES_UPTIME_EXTRA` for the uptime page).
- The header on every page shows `Server time:` only; the footer shows `Pinger v{version} · Deployed: {deployed}`.
- Navigation links across the four pages (Dashboard, Uptime, MAC groups, Preferences) should stay symmetric — when adding a new top-level page, add it to the `.navlinks` block in every existing template.

## Local sanity check

A quick smoke check before opening a PR:

```bash
python -c "import pinger.db, pinger.web, pinger.worker, pinger.mail; print('OK')"
```

A fuller check spins up the Flask test client against a temp DB; the patterns in recent commits show how to do this.
