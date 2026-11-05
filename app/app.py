"""NEXUS E-COMMERCE - simulated commerce application.

This service is the "componente simulado" required by the AIOps Mission
Control project. It stands in for the real NEXUS storefront and database so
the team can observe application-level telemetry that a host exporter cannot
see:

  * response time per endpoint        -> nexus_app_response_time_seconds
  * HTTP 500 errors                   -> nexus_app_http_500_total
  * active database connections       -> nexus_db_active_connections

It also exposes /chaos endpoints so incidents can be reproduced on demand
during the demo, and /alerts to receive Alertmanager webhook notifications.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time

import psycopg2
from flask import Flask, Response, jsonify, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from psycopg2 import pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("nexus.app")

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "nexus")
DB_USER = os.getenv("DB_USER", "nexus")
DB_PASSWORD = os.getenv("DB_PASSWORD", "nexus")

DB_POLL_SECONDS = float(os.getenv("DB_POLL_SECONDS", "5"))

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
HTTP_REQUESTS = Counter(
    "nexus_app_http_requests_total",
    "Total HTTP requests handled by the NEXUS application.",
    ["method", "endpoint", "status"],
)
HTTP_500 = Counter(
    "nexus_app_http_500_total",
    "Total HTTP 500 responses returned by the NEXUS application.",
)
RESPONSE_TIME = Histogram(
    "nexus_app_response_time_seconds",
    "Response time of the NEXUS application in seconds.",
    ["endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
DB_ACTIVE = Gauge(
    "nexus_db_active_connections",
    "Active (non-idle) connections to the NEXUS database.",
)
DB_UP = Gauge(
    "nexus_db_up",
    "1 when the application can reach the database, 0 otherwise.",
)
APP_UP = Gauge("nexus_app_up", "Application self-reported health (1 = healthy).")
ALERTS_RECEIVED = Counter(
    "nexus_alerts_received_total",
    "Alerts delivered by Alertmanager to this application.",
    ["severity", "alertname", "status"],
)

APP_UP.set(1)

# ---------------------------------------------------------------------------
# Chaos state (demo only)
# ---------------------------------------------------------------------------
_chaos = {"fail_remaining": 0, "latency_ms": 0}
_chaos_lock = threading.Lock()


def chaos_snapshot() -> dict:
    with _chaos_lock:
        return dict(_chaos)


# ---------------------------------------------------------------------------
# Database pool
# ---------------------------------------------------------------------------
_pool: pool.ThreadedConnectionPool | None = None


def init_pool(attempts: int = 30, delay: float = 2.0) -> None:
    """Create the connection pool, tolerating a database that is still starting.

    ThreadedConnectionPool is required because gunicorn serves requests on
    several threads and the metrics poller runs in its own thread; the plain
    SimpleConnectionPool is not thread-safe.
    """
    global _pool
    for attempt in range(1, attempts + 1):
        try:
            _pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=3,
            )
            log.info("database pool ready (attempt %s)", attempt)
            return
        except psycopg2.Error as exc:
            log.warning("database not ready (attempt %s/%s): %s", attempt, attempts, exc)
            time.sleep(delay)
    log.error("database pool could not be created; /api endpoints will fail")


def db_poll_loop() -> None:
    """Publish database connection metrics even when no user traffic exists."""
    while True:
        opened = 0
        healthy = 0
        conn = None
        try:
            if _pool is not None:
                conn = _pool.getconn()
                with conn.cursor() as cur:
                    # Open connections held by this application, including the
                    # poller's own. Excluding the poller was wrong: at idle the
                    # pool holds exactly one connection, so the count collapsed
                    # to zero and the gauge never reflected pool saturation.
                    cur.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = %s AND usename = current_user",
                        (DB_NAME,),
                    )
                    opened = int(cur.fetchone()[0])
                    cur.execute("SELECT 1")
                    cur.fetchone()
                healthy = 1
        except psycopg2.Error as exc:
            log.warning("database poll failed: %s", exc)
        finally:
            if conn is not None and _pool is not None:
                try:
                    _pool.putconn(conn)
                except psycopg2.Error:
                    pass
        DB_ACTIVE.set(opened)
        DB_UP.set(healthy)
        time.sleep(DB_POLL_SECONDS)


def db_call(fn):
    """Run fn(cursor) inside a pooled connection and return its result."""
    if _pool is None:
        raise psycopg2.OperationalError("database pool not initialised")
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            result = fn(cur)
        conn.commit()
        return result
    except psycopg2.Error:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.before_request
def mark_start():
    request.environ["nexus.start"] = time.perf_counter()
    return None


@app.before_request
def apply_latency_chaos():
    if not request.path.startswith("/api/"):
        return None
    latency = chaos_snapshot()["latency_ms"]
    if latency > 0:
        time.sleep(latency / 1000.0)
    return None


@app.before_request
def apply_failure_chaos():
    if not request.path.startswith("/api/"):
        return None
    with _chaos_lock:
        if _chaos["fail_remaining"] > 0:
            _chaos["fail_remaining"] -= 1
            should_fail = True
        else:
            should_fail = False
    if should_fail:
        return jsonify(
            error="internal_server_error",
            message="Simulated failure injected through /chaos/fail",
        ), 500
    return None


@app.after_request
def record_metrics(response: Response) -> Response:
    endpoint = request.endpoint or "unknown"
    RESPONSE_TIME.labels(endpoint=endpoint).observe(
        time.perf_counter() - request.environ.get("nexus.start", time.perf_counter())
    )
    HTTP_REQUESTS.labels(
        method=request.method,
        endpoint=endpoint,
        status=str(response.status_code),
    ).inc()
    # Counted from the real response status so genuine application failures are
    # included, not only the ones injected through /chaos/fail.
    if response.status_code >= 500:
        HTTP_500.inc()
    return response


@app.get("/")
def index():
    return jsonify(
        service="nexus-ecommerce-app",
        team="Sentinel Ops",
        project="AIOps Mission Control",
        endpoints={
            "/api/products": "list catalogue",
            "/api/orders": "create an order",
            "/health": "liveness probe",
            "/metrics": "Prometheus exposition",
            "/chaos/fail": "inject HTTP 500 responses",
            "/chaos/latency": "inject response latency",
            "/chaos/reset": "clear injected chaos",
        },
    )


@app.get("/health")
def health():
    return jsonify(status="ok", chaos=chaos_snapshot())


@app.get("/api/products")
def list_products():
    rows = db_call(
        lambda cur: (
            cur.execute("SELECT id, sku, name, price, stock FROM products ORDER BY id"),
            cur.fetchall(),
        )[1]
    )
    return jsonify(
        products=[
            {"id": r[0], "sku": r[1], "name": r[2], "price": float(r[3]), "stock": r[4]}
            for r in rows
        ]
    )


@app.post("/api/orders")
def create_order():
    payload = request.get_json(silent=True) or {}
    product_id = int(payload.get("product_id", random.randint(1, 5)))
    quantity = int(payload.get("quantity", random.randint(1, 3)))

    def work(cur):
        cur.execute(
            "INSERT INTO orders (product_id, quantity, status) "
            "VALUES (%s, %s, 'confirmed') RETURNING id",
            (product_id, quantity),
        )
        return cur.fetchone()[0]

    order_id = db_call(work)
    return jsonify(order_id=order_id, product_id=product_id, quantity=quantity), 201


@app.route("/alerts", methods=["POST"])
def receive_alert():
    payload = request.get_json(silent=True) or {}
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        ALERTS_RECEIVED.labels(
            severity=labels.get("severity", "unknown"),
            alertname=labels.get("alertname", "unknown"),
            status=alert.get("status", "unknown"),
        ).inc()
        log.info(
            "ALERT %s severity=%s status=%s summary=%s",
            labels.get("alertname"),
            labels.get("severity"),
            alert.get("status"),
            alert.get("annotations", {}).get("summary"),
        )
    return jsonify(status="received"), 200


@app.post("/chaos/fail")
def chaos_fail():
    count = int(request.args.get("count", 20))
    with _chaos_lock:
        _chaos["fail_remaining"] = max(0, count)
    log.info("chaos: %s consecutive HTTP 500 responses armed", count)
    return jsonify(chaos=chaos_snapshot())


@app.post("/chaos/latency")
def chaos_latency():
    ms = int(request.args.get("ms", 1500))
    with _chaos_lock:
        _chaos["latency_ms"] = max(0, ms)
    log.info("chaos: latency %s ms armed", ms)
    return jsonify(chaos=chaos_snapshot())


@app.post("/chaos/reset")
def chaos_reset():
    with _chaos_lock:
        _chaos["fail_remaining"] = 0
        _chaos["latency_ms"] = 0
    log.info("chaos: reset")
    return jsonify(chaos=chaos_snapshot())


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    init_pool()
    threading.Thread(target=db_poll_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
