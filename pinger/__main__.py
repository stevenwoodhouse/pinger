"""CLI entry: HTTP server + APScheduler."""

from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from waitress import serve

from pinger import config
from pinger.db import connect, init_schema
from pinger.web import create_app
from pinger.worker import SweepRunner


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    conn = connect(config.DB_PATH)
    init_schema(conn)
    conn.close()

    runner = SweepRunner()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        runner.run_once_sync,
        "interval",
        seconds=max(60, config.INTERVAL_SEC),
        id="sweep",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.start()

    # Kick off shortly after startup so the UI isn't empty long
    threading.Timer(5.0, runner.run_once_sync).start()

    app = create_app(runner)
    logging.getLogger("waitress.queue").setLevel(logging.ERROR)
    logging.getLogger(__name__).info(
        "Pinger listening on http://%s:%s/", config.HOST, config.PORT
    )
    serve(app, host=config.HOST, port=config.PORT, threads=4)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.basicConfig(level=logging.INFO)
        logging.exception("Pinger failed to start")
        raise
