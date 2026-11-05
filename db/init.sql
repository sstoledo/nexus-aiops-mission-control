-- NEXUS E-COMMERCE - seed schema for the simulated database.
-- The application reads these tables and exports connection metrics from
-- pg_stat_activity, so the data must exist before the demo starts.

CREATE TABLE IF NOT EXISTS products (
    id      SERIAL PRIMARY KEY,
    sku     TEXT    NOT NULL UNIQUE,
    name    TEXT    NOT NULL,
    price   NUMERIC(10, 2) NOT NULL,
    stock   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products (id),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    status      TEXT NOT NULL DEFAULT 'confirmed',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO products (sku, name, price, stock)
VALUES
    ('NX-1001', 'Teclado mecanico Nexus Pro', 249.90, 40),
    ('NX-1002', 'Mouse inalambrico Nexus Air', 129.50, 120),
    ('NX-1003', 'Monitor Nexus Vision 27"', 1099.00, 15),
    ('NX-1004', 'Audifonos Nexus Sound', 349.00, 60),
    ('NX-1005', 'Webcam Nexus Stream HD', 199.90, 30)
ON CONFLICT (sku) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders (product_id);
