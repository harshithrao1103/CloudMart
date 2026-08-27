

-- ============================================================
-- 1. CUSTOMERS
-- ============================================================

CREATE TABLE IF NOT EXISTS customers (
    customer_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- 2. PRODUCTS
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    product_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
);


-- ============================================================
-- 3. INVENTORY
-- ============================================================

CREATE TABLE IF NOT EXISTS inventory (
    inventory_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT NOT NULL UNIQUE,
    quantity INT NOT NULL,
    low_stock_threshold INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_inventory_product
        FOREIGN KEY (product_id)
        REFERENCES products(product_id)
);


-- ============================================================
-- 4. ORDERS
-- ============================================================

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    status VARCHAR(30) NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_orders_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id),

    INDEX idx_orders_customer_id (customer_id)
);


-- ============================================================
-- 5. ORDER ITEMS
-- ============================================================

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,

    CONSTRAINT fk_order_items_order
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    CONSTRAINT fk_order_items_product
        FOREIGN KEY (product_id)
        REFERENCES products(product_id),

    INDEX idx_order_items_order_id (order_id),
    INDEX idx_order_items_product_id (product_id)
);


-- ============================================================
-- 6. ORDER HISTORY
-- ============================================================

CREATE TABLE IF NOT EXISTS order_history (
    history_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    old_status VARCHAR(30),
    new_status VARCHAR(30) NOT NULL,
    changed_by VARCHAR(30) NOT NULL,
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_order_history_order
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    INDEX idx_order_history_order_id (order_id)
);


-- ============================================================
-- SAMPLE PRODUCT DATA
-- ============================================================

INSERT INTO products
    (name, description, price, is_active)
SELECT
    'Laptop',
    'Business laptop',
    65000.00,
    TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM products
    WHERE name = 'Laptop'
);


INSERT INTO products
    (name, description, price, is_active)
SELECT
    'Wireless Mouse',
    'Wireless optical mouse',
    1200.00,
    TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM products
    WHERE name = 'Wireless Mouse'
);


INSERT INTO products
    (name, description, price, is_active)
SELECT
    'Keyboard',
    'Wireless keyboard',
    2500.00,
    TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM products
    WHERE name = 'Keyboard'
);


-- ============================================================
-- SAMPLE INVENTORY DATA
-- ============================================================

INSERT INTO inventory
    (product_id, quantity, low_stock_threshold)
SELECT
    p.product_id,
    25,
    5
FROM products p
WHERE p.name = 'Laptop'
  AND NOT EXISTS (
      SELECT 1
      FROM inventory i
      WHERE i.product_id = p.product_id
  );


INSERT INTO inventory
    (product_id, quantity, low_stock_threshold)
SELECT
    p.product_id,
    15,
    5
FROM products p
WHERE p.name = 'Wireless Mouse'
  AND NOT EXISTS (
      SELECT 1
      FROM inventory i
      WHERE i.product_id = p.product_id
  );


INSERT INTO inventory
    (product_id, quantity, low_stock_threshold)
SELECT
    p.product_id,
    10,
    5
FROM products p
WHERE p.name = 'Keyboard'
  AND NOT EXISTS (
      SELECT 1
      FROM inventory i
      WHERE i.product_id = p.product_id
  );