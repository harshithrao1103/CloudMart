-- ============================================================
-- 1. USERS
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'customer',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
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
-- 3. LOGIN HISTORY
-- ============================================================

CREATE TABLE IF NOT EXISTS login_history (
    login_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    login_status VARCHAR(20) NOT NULL,

    CONSTRAINT fk_login_history_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
);


-- ============================================================
-- 4. INVENTORY
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
-- 5. ORDERS
-- ============================================================

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    status VARCHAR(30) NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_orders_user
        FOREIGN KEY (customer_id)
        REFERENCES users(user_id),

    INDEX idx_orders_customer_id (customer_id)
);


-- ============================================================
-- 6. ORDER ITEMS
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
-- 7. ORDER HISTORY
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
-- SAMPLE USERS
-- ============================================================

INSERT INTO users
    (name, email, password_hash, role, is_active)
SELECT
    'CloudMart Admin',
    'harshith.rao1103@gmail.com',
    NULL,
    'admin',
    TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM users
    WHERE email = 'harshith.rao1103@gmail.com'
);


INSERT INTO users
    (name, email, password_hash, role, is_active)
SELECT
    'Shoshek',
    'harshithrao10.1103@gmail.com',
    NULL,
    'customer',
    TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM users
    WHERE email = 'harshithrao10.1103@gmail.com'
);


INSERT INTO users
    (name, email, password_hash, role, is_active)
SELECT
    'Sidhesh',
    'harshithrao1.1103@gmail.com',
    NULL,
    'customer',
    TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM users
    WHERE email = 'harshithrao1.1103@gmail.com'
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


-- ============================================================
-- SAMPLE ORDERS
-- ============================================================

INSERT INTO orders
    (customer_id, status, total_amount)
SELECT
    u.user_id,
    'delivered',
    67400.00
FROM users u
WHERE u.email = 'harshithrao10.1103@gmail.com'
  AND NOT EXISTS (
      SELECT 1
      FROM orders o
      WHERE o.customer_id = u.user_id
        AND o.total_amount = 67400.00
        AND o.status = 'delivered'
  );


INSERT INTO orders
    (customer_id, status, total_amount)
SELECT
    u.user_id,
    'confirmed',
    3700.00
FROM users u
WHERE u.email = 'harshithrao1.1103@gmail.com'
  AND NOT EXISTS (
      SELECT 1
      FROM orders o
      WHERE o.customer_id = u.user_id
        AND o.total_amount = 3700.00
        AND o.status = 'confirmed'
  );


-- ============================================================
-- SAMPLE ORDER ITEMS
-- ============================================================

INSERT INTO order_items
    (order_id, product_id, quantity, unit_price)
SELECT
    o.order_id,
    p.product_id,
    1,
    65000.00
FROM orders o
JOIN users u
    ON o.customer_id = u.user_id
JOIN products p
    ON p.name = 'Laptop'
WHERE u.email = 'harshithrao10.1103@gmail.com'
  AND o.total_amount = 67400.00
  AND o.status = 'delivered'
  AND NOT EXISTS (
      SELECT 1
      FROM order_items oi
      WHERE oi.order_id = o.order_id
        AND oi.product_id = p.product_id
  );


INSERT INTO order_items
    (order_id, product_id, quantity, unit_price)
SELECT
    o.order_id,
    p.product_id,
    2,
    1200.00
FROM orders o
JOIN users u
    ON o.customer_id = u.user_id
JOIN products p
    ON p.name = 'Wireless Mouse'
WHERE u.email = 'harshithrao10.1103@gmail.com'
  AND o.total_amount = 67400.00
  AND o.status = 'delivered'
  AND NOT EXISTS (
      SELECT 1
      FROM order_items oi
      WHERE oi.order_id = o.order_id
        AND oi.product_id = p.product_id
  );


INSERT INTO order_items
    (order_id, product_id, quantity, unit_price)
SELECT
    o.order_id,
    p.product_id,
    1,
    2500.00
FROM orders o
JOIN users u
    ON o.customer_id = u.user_id
JOIN products p
    ON p.name = 'Keyboard'
WHERE u.email = 'harshithrao1.1103@gmail.com'
  AND o.total_amount = 3700.00
  AND o.status = 'confirmed'
  AND NOT EXISTS (
      SELECT 1
      FROM order_items oi
      WHERE oi.order_id = o.order_id
        AND oi.product_id = p.product_id
  );


INSERT INTO order_items
    (order_id, product_id, quantity, unit_price)
SELECT
    o.order_id,
    p.product_id,
    1,
    1200.00
FROM orders o
JOIN users u
    ON o.customer_id = u.user_id
JOIN products p
    ON p.name = 'Wireless Mouse'
WHERE u.email = 'harshithrao1.1103@gmail.com'
  AND o.total_amount = 3700.00
  AND o.status = 'confirmed'
  AND NOT EXISTS (
      SELECT 1
      FROM order_items oi
      WHERE oi.order_id = o.order_id
        AND oi.product_id = p.product_id
  );


-- ============================================================
-- SAMPLE ORDER HISTORY
-- ============================================================

INSERT INTO order_history
    (order_id, old_status, new_status, changed_by)
SELECT
    o.order_id,
    NULL,
    'delivered',
    'system'
FROM orders o
JOIN users u
    ON o.customer_id = u.user_id
WHERE u.email = 'harshithrao10.1103@gmail.com'
  AND o.total_amount = 67400.00
  AND o.status = 'delivered'
  AND NOT EXISTS (
      SELECT 1
      FROM order_history oh
      WHERE oh.order_id = o.order_id
        AND oh.new_status = 'delivered'
  );


INSERT INTO order_history
    (order_id, old_status, new_status, changed_by)
SELECT
    o.order_id,
    NULL,
    'confirmed',
    'system'
FROM orders o
JOIN users u
    ON o.customer_id = u.user_id
WHERE u.email = 'harshithrao1.1103@gmail.com'
  AND o.total_amount = 3700.00
  AND o.status = 'confirmed'
  AND NOT EXISTS (
      SELECT 1
      FROM order_history oh
      WHERE oh.order_id = o.order_id
        AND oh.new_status = 'confirmed'
  );


-- ============================================================
-- LOGIN HISTORY
-- ============================================================
-- Intentionally left empty.
-- No sample login records are inserted.