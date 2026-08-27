import json
import os
import boto3
import pymysql
from decimal import Decimal


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client("ssm")
events = boto3.client("events")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

RDS_HOST = os.environ["RDS_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]

EVENT_BUS_NAME = os.environ.get(
    "EVENT_BUS_NAME",
    "default"
)


# ============================================================
# STRUCTURED JSON LOGGING
# ============================================================

def log(level, message, **kwargs):

    log_entry = {
        "level": level,
        "service": "product",
        "message": message,
        **kwargs
    }

    print(
        json.dumps(
            log_entry,
            default=str
        )
    )


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():

    response = ssm.get_parameter(
        Name=DB_PASSWORD_PARAMETER,
        WithDecryption=True
    )

    db_password = response["Parameter"]["Value"]

    return pymysql.connect(
        host=RDS_HOST,
        user=DB_USER,
        password=db_password,
        database=DB_NAME,
        port=3306,
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor
    )


# ============================================================
# JSON SERIALIZATION
# ============================================================

def json_serializer(value):

    if isinstance(value, Decimal):
        return float(value)

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


# ============================================================
# HTTP RESPONSE
# ============================================================

def response(status_code, body=None):

    result = {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        }
    }

    if body is not None:

        result["body"] = json.dumps(
            body,
            default=json_serializer
        )

    return result


# ============================================================
# PRODUCT ID
# ============================================================

def get_product_id(event):

    path_parameters = event.get("pathParameters") or {}

    product_id = path_parameters.get("productId")

    if product_id is None:
        return None

    try:

        product_id = int(product_id)

        if product_id <= 0:
            return None

        return product_id

    except (ValueError, TypeError):

        return None


# ============================================================
# EVENTBRIDGE - INVENTORY CHANGE
# ============================================================

def publish_inventory_event(
    product_id,
    quantity,
    low_stock_threshold
):

    low_stock = quantity < low_stock_threshold

    event_detail = {

        "product_id": product_id,

        "quantity": quantity,

        "low_stock_threshold": low_stock_threshold,

        "low_stock": low_stock
    }

    try:

        events.put_events(

            Entries=[

                {
                    "EventBusName": EVENT_BUS_NAME,

                    "Source": "cloudmart.product",

                    "DetailType": "Inventory Changed",

                    "Detail": json.dumps(
                        event_detail
                    )
                }

            ]
        )

        log(
            "INFO",
            "Inventory change event published",
            product_id=product_id,
            quantity=quantity,
            low_stock_threshold=low_stock_threshold,
            low_stock=low_stock
        )

    except Exception as error:

        log(
            "ERROR",
            "Failed to publish inventory change event",
            product_id=product_id,
            error=str(error)
        )

        # Do not fail the product transaction
        # because EventBridge is unavailable.


# ============================================================
# CREATE PRODUCT
# ============================================================

def create_product(event):

    try:

        body = json.loads(
            event.get("body") or "{}"
        )

    except json.JSONDecodeError:

        return response(
            400,
            {
                "message":
                "Invalid JSON request body"
            }
        )

    name = body.get("name")

    description = body.get("description")

    price = body.get("price")

    quantity = body.get("inventory")

    if not name or price is None or quantity is None:

        return response(
            400,
            {
                "message":
                "name, price and inventory are required"
            }
        )

    try:

        price = Decimal(str(price))

        quantity = int(quantity)

        if price < 0 or quantity < 0:
            raise ValueError

    except (ValueError, TypeError):

        return response(
            422,
            {
                "message":
                "Invalid price or inventory value"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Check duplicate product name
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT product_id
                FROM products
                WHERE name = %s
                """,
                (name,)
            )

            if cursor.fetchone():

                return response(
                    409,
                    {
                        "message":
                        "Product already exists"
                    }
                )

            # ------------------------------------------------
            # Insert product
            # ------------------------------------------------

            cursor.execute(
                """
                INSERT INTO products
                    (name, description, price)
                VALUES
                    (%s, %s, %s)
                """,
                (
                    name,
                    description,
                    price
                )
            )

            product_id = cursor.lastrowid

            # ------------------------------------------------
            # Insert inventory
            # ------------------------------------------------

            low_stock_threshold = 5

            cursor.execute(
                """
                INSERT INTO inventory
                    (
                        product_id,
                        quantity,
                        low_stock_threshold
                    )
                VALUES
                    (%s, %s, %s)
                """,
                (
                    product_id,
                    quantity,
                    low_stock_threshold
                )
            )

        connection.commit()

        log(
            "INFO",
            "Product created successfully",
            operation="create_product",
            product_id=product_id,
            quantity=quantity
        )

        # ----------------------------------------------------
        # Publish inventory event
        # ----------------------------------------------------

        publish_inventory_event(
            product_id,
            quantity,
            low_stock_threshold
        )

        return response(
            201,
            {
                "product_id": product_id,
                "name": name,
                "description": description,
                "price": price,
                "inventory": quantity
            }
        )

    except pymysql.err.IntegrityError as error:

        connection.rollback()

        log(
            "ERROR",
            "Create product integrity error",
            operation="create_product",
            error=str(error)
        )

        return response(
            409,
            {
                "message":
                "Product could not be created"
            }
        )

    except Exception as error:

        connection.rollback()

        log(
            "ERROR",
            "Create product error",
            operation="create_product",
            error=str(error)
        )

        return response(
            500,
            {
                "message":
                "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# GET ALL PRODUCTS
# ============================================================

def get_all_products():

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    p.product_id,
                    p.name,
                    p.description,
                    p.price,
                    p.is_active,
                    p.created_at,
                    p.updated_at,
                    i.quantity AS inventory,
                    i.low_stock_threshold
                FROM products p
                LEFT JOIN inventory i
                    ON p.product_id = i.product_id
                ORDER BY p.product_id
                """
            )

            products = cursor.fetchall()

        log(
            "INFO",
            "Products retrieved successfully",
            operation="get_all_products",
            count=len(products)
        )

        return response(
            200,
            products
        )

    except Exception as error:

        log(
            "ERROR",
            "Get all products error",
            operation="get_all_products",
            error=str(error)
        )

        return response(
            500,
            {
                "message":
                "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# GET PRODUCT
# ============================================================

def get_product(product_id):

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    p.product_id,
                    p.name,
                    p.description,
                    p.price,
                    p.is_active,
                    p.created_at,
                    p.updated_at,
                    i.quantity AS inventory,
                    i.low_stock_threshold
                FROM products p
                LEFT JOIN inventory i
                    ON p.product_id = i.product_id
                WHERE p.product_id = %s
                """,
                (product_id,)
            )

            product = cursor.fetchone()

        if not product:

            return response(
                404,
                {
                    "message":
                    "Product not found"
                }
            )

        log(
            "INFO",
            "Product retrieved successfully",
            operation="get_product",
            product_id=product_id
        )

        return response(
            200,
            product
        )

    except Exception as error:

        log(
            "ERROR",
            "Get product error",
            operation="get_product",
            product_id=product_id,
            error=str(error)
        )

        return response(
            500,
            {
                "message":
                "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# UPDATE PRODUCT
# ============================================================

def update_product(event, product_id):

    try:

        body = json.loads(
            event.get("body") or "{}"
        )

    except json.JSONDecodeError:

        return response(
            400,
            {
                "message":
                "Invalid JSON request body"
            }
        )

    name = body.get("name")

    description = body.get("description")

    price = body.get("price")

    quantity = body.get("inventory")

    if not name or price is None or quantity is None:

        return response(
            400,
            {
                "message":
                "name, price and inventory are required"
            }
        )

    try:

        price = Decimal(str(price))

        quantity = int(quantity)

        if price < 0 or quantity < 0:
            raise ValueError

    except (ValueError, TypeError):

        return response(
            422,
            {
                "message":
                "Invalid price or inventory value"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Check product exists
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT product_id
                FROM products
                WHERE product_id = %s
                """,
                (product_id,)
            )

            if not cursor.fetchone():

                return response(
                    404,
                    {
                        "message":
                        "Product not found"
                    }
                )

            # ------------------------------------------------
            # Get existing inventory threshold
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT low_stock_threshold
                FROM inventory
                WHERE product_id = %s
                """,
                (product_id,)
            )

            inventory_row = cursor.fetchone()

            if inventory_row:

                low_stock_threshold = inventory_row[
                    "low_stock_threshold"
                ]

            else:

                low_stock_threshold = 5

            # ------------------------------------------------
            # Update product
            # ------------------------------------------------

            cursor.execute(
                """
                UPDATE products
                SET
                    name = %s,
                    description = %s,
                    price = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s
                """,
                (
                    name,
                    description,
                    price,
                    product_id
                )
            )

            # ------------------------------------------------
            # Update inventory
            # ------------------------------------------------

            cursor.execute(
                """
                UPDATE inventory
                SET
                    quantity = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s
                """,
                (
                    quantity,
                    product_id
                )
            )

        connection.commit()

        log(
            "INFO",
            "Product updated successfully",
            operation="update_product",
            product_id=product_id,
            quantity=quantity
        )

        # ----------------------------------------------------
        # Publish inventory event
        # ----------------------------------------------------

        publish_inventory_event(
            product_id,
            quantity,
            low_stock_threshold
        )

        return response(
            200,
            {
                "product_id": product_id,
                "name": name,
                "description": description,
                "price": price,
                "inventory": quantity
            }
        )

    except Exception as error:

        connection.rollback()

        log(
            "ERROR",
            "Update product error",
            operation="update_product",
            product_id=product_id,
            error=str(error)
        )

        return response(
            500,
            {
                "message":
                "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# DELETE PRODUCT
# ============================================================

def delete_product(product_id):

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Check product exists
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT product_id
                FROM products
                WHERE product_id = %s
                """,
                (product_id,)
            )

            if not cursor.fetchone():

                return response(
                    404,
                    {
                        "message":
                        "Product not found"
                    }
                )

            # ------------------------------------------------
            # Check whether product is referenced by orders
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT order_item_id
                FROM order_items
                WHERE product_id = %s
                LIMIT 1
                """,
                (product_id,)
            )

            if cursor.fetchone():

                return response(
                    409,
                    {
                        "message":
                        "Product cannot be deleted because "
                        "it is referenced by existing orders"
                    }
                )

            # ------------------------------------------------
            # Delete inventory first
            # ------------------------------------------------

            cursor.execute(
                """
                DELETE FROM inventory
                WHERE product_id = %s
                """,
                (product_id,)
            )

            # ------------------------------------------------
            # Delete product
            # ------------------------------------------------

            cursor.execute(
                """
                DELETE FROM products
                WHERE product_id = %s
                """,
                (product_id,)
            )

        connection.commit()

        log(
            "INFO",
            "Product deleted successfully",
            operation="delete_product",
            product_id=product_id
        )

        return response(204)

    except Exception as error:

        connection.rollback()

        log(
            "ERROR",
            "Delete product error",
            operation="delete_product",
            product_id=product_id,
            error=str(error)
        )

        return response(
            500,
            {
                "message":
                "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    log(
        "INFO",
        "Product Lambda started"
    )

    method = (
        event.get("httpMethod")
        or
        event.get("requestContext", {})
        .get("http", {})
        .get("method")
    )

    path_parameters = (
        event.get("pathParameters") or {}
    )

    product_id = get_product_id(event)

    log(
        "INFO",
        "API request received",
        method=method,
        path_parameters=path_parameters,
        product_id=product_id
    )

    # --------------------------------------------------------
    # POST /products
    # --------------------------------------------------------

    if method == "POST" and product_id is None:

        return create_product(event)

    # --------------------------------------------------------
    # GET /products
    # --------------------------------------------------------

    if method == "GET" and product_id is None:

        return get_all_products()

    # --------------------------------------------------------
    # GET /products/{productId}
    # --------------------------------------------------------

    if method == "GET" and product_id is not None:

        return get_product(product_id)

    # --------------------------------------------------------
    # PUT /products/{productId}
    # --------------------------------------------------------

    if method == "PUT" and product_id is not None:

        return update_product(
            event,
            product_id
        )

    # --------------------------------------------------------
    # DELETE /products/{productId}
    # --------------------------------------------------------

    if method == "DELETE" and product_id is not None:

        return delete_product(
            product_id
        )

    # --------------------------------------------------------
    # Unsupported request
    # --------------------------------------------------------

    log(
        "WARN",
        "Unsupported API request",
        method=method,
        path_parameters=path_parameters
    )

    return response(
        400,
        {
            "message":
            "Unsupported API request"
        }
    )