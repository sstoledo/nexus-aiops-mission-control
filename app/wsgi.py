"""Gunicorn entrypoint: starts the database poller once per process."""

import threading

from app import app, db_poll_loop, init_pool

init_pool()
threading.Thread(target=db_poll_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
