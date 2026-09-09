import json
import os
import boto3
import pymysql
from decimal import Decimal
from datetime import datetime


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client("ssm")
sqs = boto3.client("sqs")
events = boto3.client("events")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

RDS_HOST = os.environ["RDS_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]

ORDER_FAILURE_QUEUE_URL = os.environ.get(
    "ORDER_FAILURE_QUEUE_URL"
)

ORDER_FAILURE_QUEUE_NAME = os.environ.get(
    "ORDER_FAILURE_QUEUE_NAME",
    "cloudmart-dev-order-failures"
)

EVENT_BUS_NAME = os.environ.get(
    "EVENT_BUS_NAME",
    "default"
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
# DECIMAL / DATETIME CONVERSION
# ============================================================

def decimal_to_float(value):

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime):
        return value.isoformat()

    return value


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
            default=decimal_to_float
        )

    return result


# ============================================================
# REQUEST BODY PARSER
#
# Handles:
#
# 1. Normal JSON object
# 2. JSON string containing JSON
# 3. Multiple JSON encoding levels
#
# This fixes:
# AttributeError: 'str' object has no attribute 'get'
# ============================================================

def parse_request_body(event):

    raw_body = event.get("body")

    if raw_body is None or raw_body == "":
        return {}

    body = raw_body

    # --------------------------------------------------------
    # Decode repeatedly while body is a string.
    #
    # This handles both:
    #
    # {"customer_id": 11, "items": [...]}
    #
    # and JSON encoded versions of the above.
    # --------------------------------------------------------

    for _ in range(5):

        if not isinstance(body, str):
            break

        body = json.loads(body)

    if not isinstance(body, dict):

        raise ValueError(
            "Request body must contain a JSON object"
        )

    return body


# ============================================================
# PATH PARAMETER
# ============================================================

def get_path_parameter(event, name):

    path_parameters = event.get("pathParameters") or {}

    value = path_parameters.get(name)

    if value is None:
        return None

    try:

        value = int(value)

        if value <= 0:
            return None

        return value

    except (ValueError, TypeError):

        return None


# ============================================================
# QUERY STRING PARAMETER
# ============================================================

def get_query_parameter(event, name):

    query_parameters = (
        event.get("queryStringParameters") or {}
    )

    value = query_parameters.get(name)

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    return value


# ============================================================
# AUTHORIZATION CONTEXT
# ============================================================

def get_authorizer_context(event):

    request_context = event.get("requestContext") or {}

    authorizer = request_context.get("authorizer") or {}

    # HTTP API / payload format 2.0
    context = authorizer.get("lambda")

    if context is None:
        context = authorizer

    if not isinstance(context, dict):
        return None

    return context


# ============================================================
# CHECK ADMIN
# ============================================================

def is_admin(event):

    context = get_authorizer_context(event)

    if not context:
        return False

    return context.get("role") == "admin"


# ============================================================
# GET AUTHENTICATED USER
# ============================================================

def get_authenticated_user_id(event):

    context = get_authorizer_context(event)

    if not context:
        return None

    user_id = context.get("userId")

    if user_id is None:
        return None

    return str(user_id)


# ============================================================
# AUTHORIZE CUSTOMER
# ============================================================

def authorize_customer(event, customer_id):

    # Admin can access any customer
    if is_admin(event):
        return True

    authenticated_user_id = get_authenticated_user_id(event)

    if authenticated_user_id is None:
        return False

    return authenticated_user_id == str(customer_id)


# ============================================================
# AUTHORIZE ORDER OWNERSHIP
# ============================================================

def authorize_order(event, order_id):

    # Admin can access any order
    if is_admin(event):
        return True

    authenticated_user_id = get_authenticated_user_id(event)

    if authenticated_user_id is None:
        return False

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT customer_id
                FROM orders
                WHERE order_id = %s
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:
                return None

            return authenticated_user_id == str(
                order["customer_id"]
            )

    except Exception as error:

        print(
            "Authorization order lookup error:",
            str(error)
        )

        return False

    finally:

        connection.close()


# ============================================================
# SEND FAILED ORDER TO SQS
# ============================================================

def send_failure_to_sqs(
    order_id,
    error_message,
    failed_operation
):

    try:

        queue_url = ORDER_FAILURE_QUEUE_URL

        if not queue_url:

            queue_response = sqs.get_queue_url(
                QueueName=ORDER_FAILURE_QUEUE_NAME
            )

            queue_url = queue_response["QueueUrl"]

        message = {
            "order_id": order_id,
            "failed_operation": failed_operation,
            "error": error_message,
            "source": "cloudmart-order-lambda"
        }

        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message)
        )

        print(
            f"Order {order_id} failure sent to SQS"
        )

        return True

    except Exception as sqs_error:

        print(
            f"Failed to send order {order_id} "
            f"to SQS: {str(sqs_error)}"
        )

        return False


# ============================================================
# PUBLISH ORDER EVENT TO EVENTBRIDGE
# ============================================================

def publish_order_event(detail_type, detail):

    try:

        result = events.put_events(
            Entries=[
                {
                    "EventBusName": EVENT_BUS_NAME,
                    "Source": "cloudmart.orders",
                    "DetailType": detail_type,
                    "Detail": json.dumps(
                        detail,
                        default=decimal_to_float
                    )
                }
            ]
        )

        print(
            f"Published EventBridge event: {detail_type}"
        )

        # ----------------------------------------------------
        # Log failed EventBridge entries if any
        # ----------------------------------------------------

        if result.get("FailedEntryCount", 0) > 0:

            print(
                "EventBridge failed entries:",
                json.dumps(result)
            )

            return False

        return True

    except Exception as event_error:

        print(
            f"Failed to publish EventBridge event "
            f"{detail_type}: {str(event_error)}"
        )

        return False


# ============================================================
# CREATE ORDER
# ============================================================

def create_order(event):

    # --------------------------------------------------------
    # Parse request body
    # --------------------------------------------------------

    try:

        body = parse_request_body(event)

    except (json.JSONDecodeError, TypeError, ValueError) as error:

        print(
            "Request body parsing error:",
            str(error)
        )

        return response(
            400,
            {
                "message": "Invalid JSON request body"
            }
        )

    # --------------------------------------------------------
    # Get request values
    # --------------------------------------------------------

    customer_id = body.get("customer_id")
    items = body.get("items")

    # --------------------------------------------------------
    # Validate customer ID
    # --------------------------------------------------------

    try:

        customer_id = int(customer_id)

        if customer_id <= 0:
            raise ValueError

    except (ValueError, TypeError):

        return response(
            400,
            {
                "message": "Invalid customer_id"
            }
        )

    # --------------------------------------------------------
    # Validate items
    # --------------------------------------------------------

    if not isinstance(items, list) or not items:

        return response(
            400,
            {
                "message":
                "customer_id and at least one item are required"
            }
        )

    # --------------------------------------------------------
    # CUSTOMER AUTHORIZATION
    # --------------------------------------------------------

    if not authorize_customer(event, customer_id):

        return response(
            403,
            {
                "message":
                "You are not authorized to create an order "
                "for this customer"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # =================================================
            # CHECK CUSTOMER
            # =================================================

            cursor.execute(
                """
                SELECT
                    user_id,
                    email
                FROM users
                WHERE user_id = %s
                """,
                (customer_id,)
            )

            customer = cursor.fetchone()

            if not customer:

                connection.rollback()

                return response(
                    404,
                    {
                        "message": "Customer not found"
                    }
                )

            total_amount = Decimal("0.00")

            order_items = []

            # =================================================
            # VALIDATE PRODUCTS AND INVENTORY
            # =================================================

            for item_index, item in enumerate(items):

                # ------------------------------------------------
                # Each item must be a JSON object
                # ------------------------------------------------

                if not isinstance(item, dict):

                    connection.rollback()

                    return response(
                        422,
                        {
                            "message":
                            f"Invalid item at index {item_index}"
                        }
                    )

                product_id = item.get("product_id")
                quantity = item.get("quantity")

                # ------------------------------------------------
                # Validate product ID
                # ------------------------------------------------

                try:

                    product_id = int(product_id)
                    quantity = int(quantity)

                    if product_id <= 0 or quantity <= 0:
                        raise ValueError

                except (ValueError, TypeError):

                    connection.rollback()

                    return response(
                        422,
                        {
                            "message":
                            "Invalid product_id or quantity"
                        }
                    )

                # ------------------------------------------------
                # Get product and inventory
                # ------------------------------------------------

                cursor.execute(
                    """
                    SELECT
                        i.product_id,
                        i.quantity,
                        p.price,
                        p.is_active
                    FROM inventory i
                    INNER JOIN products p
                        ON i.product_id = p.product_id
                    WHERE i.product_id = %s
                    FOR UPDATE
                    """,
                    (product_id,)
                )

                product = cursor.fetchone()

                if not product:

                    connection.rollback()

                    return response(
                        404,
                        {
                            "message":
                            f"Product {product_id} not found"
                        }
                    )

                # ------------------------------------------------
                # Check active product
                # ------------------------------------------------

                if not product["is_active"]:

                    connection.rollback()

                    return response(
                        409,
                        {
                            "message":
                            f"Product {product_id} is inactive"
                        }
                    )

                # ------------------------------------------------
                # Check inventory
                # ------------------------------------------------

                if product["quantity"] < quantity:

                    connection.rollback()

                    return response(
                        409,
                        {
                            "message":
                            f"Insufficient inventory for product "
                            f"{product_id}"
                        }
                    )

                unit_price = product["price"]

                item_total = unit_price * quantity

                total_amount += item_total

                order_items.append(
                    {
                        "product_id": product_id,
                        "quantity": quantity,
                        "unit_price": unit_price
                    }
                )

            # =================================================
            # CREATE ORDER
            #
            # Inventory is NOT deducted here.
            # =================================================

            cursor.execute(
                """
                INSERT INTO orders
                (
                    customer_id,
                    status,
                    total_amount
                )
                VALUES
                (
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    customer_id,
                    "CREATED",
                    total_amount
                )
            )

            order_id = cursor.lastrowid

            # =================================================
            # CREATE ORDER ITEMS
            # =================================================

            for item in order_items:

                cursor.execute(
                    """
                    INSERT INTO order_items
                    (
                        order_id,
                        product_id,
                        quantity,
                        unit_price
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        order_id,
                        item["product_id"],
                        item["quantity"],
                        item["unit_price"]
                    )
                )

            # =================================================
            # INITIAL ORDER HISTORY
            # =================================================

            cursor.execute(
                """
                INSERT INTO order_history
                (
                    order_id,
                    old_status,
                    new_status,
                    changed_by
                )
                VALUES
                (
                    %s,
                    NULL,
                    %s,
                    %s
                )
                """,
                (
                    order_id,
                    "CREATED",
                    "API"
                )
            )

        # =====================================================
        # COMMIT
        # =====================================================

        connection.commit()

        # =====================================================
        # PUBLISH EVENT
        # =====================================================

        publish_order_event(
            "OrderCreated",
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "customer_email": customer["email"],
                "status": "CREATED",
                "total_amount": total_amount,
                "items": order_items
            }
        )

        # =====================================================
        # RESPONSE
        # =====================================================

        return response(
            201,
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "status": "CREATED",
                "total_amount": total_amount,
                "items": order_items
            }
        )

    except Exception as error:

        connection.rollback()

        print(
            "Create order error:",
            str(error)
        )

        return response(
            500,
            {
                "message": "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# GET ORDER
# ============================================================

def get_order(event, order_id):

    # --------------------------------------------------------
    # ORDER AUTHORIZATION
    # --------------------------------------------------------

    authorization_result = authorize_order(
        event,
        order_id
    )

    if authorization_result is False:

        return response(
            403,
            {
                "message":
                "You are not authorized to access this order"
            }
        )

    # --------------------------------------------------------
    # If order does not exist
    # --------------------------------------------------------

    if authorization_result is None:

        return response(
            404,
            {
                "message": "Order not found"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # =================================================
            # GET ORDER
            # =================================================

            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.status,
                    o.total_amount,
                    o.created_at,
                    o.updated_at
                FROM orders o
                WHERE o.order_id = %s
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                return response(
                    404,
                    {
                        "message": "Order not found"
                    }
                )

            # =================================================
            # GET ORDER ITEMS
            # =================================================

            cursor.execute(
                """
                SELECT
                    oi.order_item_id,
                    oi.product_id,
                    p.name AS product_name,
                    oi.quantity,
                    oi.unit_price,
                    (
                        oi.quantity * oi.unit_price
                    ) AS item_total
                FROM order_items oi
                INNER JOIN products p
                    ON oi.product_id = p.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.order_item_id
                """,
                (order_id,)
            )

            items = cursor.fetchall()

        order["items"] = items

        return response(
            200,
            order
        )

    except Exception as error:

        print(
            "Get order error:",
            str(error)
        )

        return response(
            500,
            {
                "message": "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# GET CUSTOMER ORDERS
# ============================================================

def get_customer_orders(event, customer_id):

    # --------------------------------------------------------
    # CUSTOMER AUTHORIZATION
    # --------------------------------------------------------

    if not authorize_customer(
        event,
        customer_id
    ):

        return response(
            403,
            {
                "message":
                "You are not authorized to access "
                "these customer orders"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # =================================================
            # CHECK CUSTOMER
            # =================================================

            cursor.execute(
                """
                SELECT
                    user_id
                FROM users
                WHERE user_id = %s
                  AND role = 'customer'
                  AND is_active = 1
                """,
                (customer_id,)
            )

            if not cursor.fetchone():

                return response(
                    404,
                    {
                        "message": "Customer not found"
                    }
                )

            # =================================================
            # GET ORDERS
            # =================================================

            cursor.execute(
                """
                SELECT
                    order_id,
                    customer_id,
                    status,
                    total_amount,
                    created_at,
                    updated_at
                FROM orders
                WHERE customer_id = %s
                ORDER BY created_at DESC
                """,
                (customer_id,)
            )

            orders = cursor.fetchall()

        return response(
            200,
            orders
        )

    except Exception as error:

        print(
            "Get customer orders error:",
            str(error)
        )

        return response(
            500,
            {
                "message": "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# CONFIRM / UPDATE ORDER STATUS
# ============================================================

def update_order(event, order_id):

    # --------------------------------------------------------
    # ADMIN ONLY
    # --------------------------------------------------------

    if not is_admin(event):

        return response(
            403,
            {
                "message":
                "Only admin can update order status"
            }
        )

    # --------------------------------------------------------
    # Parse body
    # --------------------------------------------------------

    try:

        body = parse_request_body(event)

    except (json.JSONDecodeError, TypeError, ValueError) as error:

        print(
            "Update order body parsing error:",
            str(error)
        )

        return response(
            400,
            {
                "message": "Invalid JSON request body"
            }
        )

    new_status = body.get("status")

    if not new_status:

        return response(
            400,
            {
                "message": "status is required"
            }
        )

    # --------------------------------------------------------
    # Allowed statuses
    # --------------------------------------------------------

    allowed_statuses = {
        "CREATED",
        "CONFIRMED",
        "PROCESSING",
        "SHIPPED",
        "DELIVERED",
        "CANCELLED"
    }

    if new_status not in allowed_statuses:

        return response(
            422,
            {
                "message": "Invalid order status"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # =================================================
            # LOCK ORDER
            # =================================================

            cursor.execute(
                """
                SELECT
                    o.status,
                    o.customer_id,
                    c.email AS customer_email
                FROM orders o
                INNER JOIN users c
                    ON o.customer_id = c.user_id
                WHERE o.order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                return response(
                    404,
                    {
                        "message": "Order not found"
                    }
                )

            old_status = order["status"]

            if old_status == new_status:

                return response(
                    409,
                    {
                        "message":
                        "Order is already in this status"
                    }
                )

            # =================================================
            # VALID STATE TRANSITIONS
            # =================================================

            valid_transitions = {

                "CREATED": {
                    "CONFIRMED",
                    "CANCELLED"
                },

                "CONFIRMED": {
                    "PROCESSING",
                    "CANCELLED"
                },

                "PROCESSING": {
                    "SHIPPED",
                    "CANCELLED"
                },

                "SHIPPED": {
                    "DELIVERED"
                },

                "DELIVERED": set(),

                "CANCELLED": set()
            }

            if new_status not in valid_transitions.get(
                old_status,
                set()
            ):

                return response(
                    409,
                    {
                        "message":
                        f"Invalid transition from "
                        f"{old_status} to {new_status}"
                    }
                )

            # =================================================
            # CONFIRM ORDER
            #
            # Deduct inventory only when order is confirmed.
            # =================================================

            if new_status == "CONFIRMED":

                cursor.execute(
                    """
                    SELECT
                        oi.product_id,
                        oi.quantity,
                        i.quantity AS inventory_quantity
                    FROM order_items oi
                    INNER JOIN inventory i
                        ON oi.product_id = i.product_id
                    WHERE oi.order_id = %s
                    FOR UPDATE
                    """,
                    (order_id,)
                )

                items = cursor.fetchall()

                if not items:

                    raise Exception(
                        "Order has no inventory items"
                    )

                # ------------------------------------------------
                # Check all inventory BEFORE deducting anything
                # ------------------------------------------------

                for item in items:

                    if (
                        item["inventory_quantity"]
                        < item["quantity"]
                    ):

                        raise Exception(
                            f"Insufficient inventory for "
                            f"product {item['product_id']}"
                        )

                # ------------------------------------------------
                # Deduct inventory
                # ------------------------------------------------

                for item in items:

                    cursor.execute(
                        """
                        UPDATE inventory
                        SET
                            quantity = quantity - %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE product_id = %s
                        """,
                        (
                            item["quantity"],
                            item["product_id"]
                        )
                    )

            # =================================================
            # UPDATE ORDER STATUS
            # =================================================

            cursor.execute(
                """
                UPDATE orders
                SET
                    status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = %s
                """,
                (
                    new_status,
                    order_id
                )
            )

            # =================================================
            # ORDER HISTORY
            # =================================================

            cursor.execute(
                """
                INSERT INTO order_history
                (
                    order_id,
                    old_status,
                    new_status,
                    changed_by
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    order_id,
                    old_status,
                    new_status,
                    "API"
                )
            )

        # =====================================================
        # COMMIT
        # =====================================================

        connection.commit()

        # =====================================================
        # EVENTBRIDGE EVENT
        # =====================================================

        status_event_map = {

            "CONFIRMED":
                "OrderConfirmed",

            "PROCESSING":
                "OrderProcessing",

            "SHIPPED":
                "OrderShipped",

            "DELIVERED":
                "OrderDelivered"
        }

        event_type = status_event_map.get(
            new_status
        )

        if event_type:

            publish_order_event(
                event_type,
                {
                    "order_id": order_id,
                    "customer_id": order["customer_id"],
                    "customer_email":
                        order["customer_email"],
                    "old_status": old_status,
                    "new_status": new_status
                }
            )

        return response(
            200,
            {
                "order_id": order_id,
                "old_status": old_status,
                "new_status": new_status
            }
        )

    except Exception as error:

        connection.rollback()

        error_message = str(error)

        print(
            "Update order error:",
            error_message
        )

        # ----------------------------------------------------
        # Confirmation failure -> SQS failure queue
        # ----------------------------------------------------

        if new_status == "CONFIRMED":

            send_failure_to_sqs(
                order_id=order_id,
                error_message=error_message,
                failed_operation="CONFIRM_ORDER"
            )

        return response(
            500,
            {
                "message": "Order processing failed",
                "order_id": order_id
            }
        )

    finally:

        connection.close()


# ============================================================
# PATCH ORDER ITEMS
# ============================================================

def update_order_items(event, order_id):

    # --------------------------------------------------------
    # ORDER AUTHORIZATION
    # --------------------------------------------------------

    if not authorize_order(
        event,
        order_id
    ):

        return response(
            403,
            {
                "message":
                "You are not authorized to update "
                "items in this order"
            }
        )

    # --------------------------------------------------------
    # Parse body
    # --------------------------------------------------------

    try:

        body = parse_request_body(event)

    except (json.JSONDecodeError, TypeError, ValueError) as error:

        print(
            "Update order items body parsing error:",
            str(error)
        )

        return response(
            400,
            {
                "message": "Invalid JSON request body"
            }
        )

    items = body.get("items")

    if not isinstance(items, list) or not items:

        return response(
            400,
            {
                "message":
                "items must be a non-empty array"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # =================================================
            # LOCK ORDER
            # =================================================

            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.status,
                    c.email AS customer_email
                FROM orders o
                INNER JOIN users c
                    ON o.customer_id = c.user_id
                WHERE o.order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                return response(
                    404,
                    {
                        "message": "Order not found"
                    }
                )

            # =================================================
            # ONLY CREATED ORDERS CAN CHANGE ITEMS
            # =================================================

            if order["status"] != "CREATED":

                return response(
                    409,
                    {
                        "message":
                        "Order items can only be changed "
                        "while order status is CREATED"
                    }
                )

            new_items = []

            total_amount = Decimal("0.00")

            # =================================================
            # VALIDATE NEW ITEMS
            # =================================================

            for item_index, item in enumerate(items):

                if not isinstance(item, dict):

                    connection.rollback()

                    return response(
                        422,
                        {
                            "message":
                            f"Invalid item at index {item_index}"
                        }
                    )

                product_id = item.get("product_id")
                quantity = item.get("quantity")

                try:

                    product_id = int(product_id)
                    quantity = int(quantity)

                    if product_id <= 0 or quantity <= 0:
                        raise ValueError

                except (ValueError, TypeError):

                    connection.rollback()

                    return response(
                        422,
                        {
                            "message":
                            "Invalid product_id or quantity"
                        }
                    )

                # ------------------------------------------------
                # Get product
                # ------------------------------------------------

                cursor.execute(
                    """
                    SELECT
                        i.product_id,
                        i.quantity,
                        p.price,
                        p.is_active
                    FROM inventory i
                    INNER JOIN products p
                        ON i.product_id = p.product_id
                    WHERE i.product_id = %s
                    FOR UPDATE
                    """,
                    (product_id,)
                )

                product = cursor.fetchone()

                if not product:

                    connection.rollback()

                    return response(
                        404,
                        {
                            "message":
                            f"Product {product_id} not found"
                        }
                    )

                if not product["is_active"]:

                    connection.rollback()

                    return response(
                        409,
                        {
                            "message":
                            f"Product {product_id} is inactive"
                        }
                    )

                if product["quantity"] < quantity:

                    connection.rollback()

                    return response(
                        409,
                        {
                            "message":
                            f"Insufficient inventory for product "
                            f"{product_id}"
                        }
                    )

                unit_price = product["price"]

                total_amount += (
                    unit_price * quantity
                )

                new_items.append(
                    {
                        "product_id": product_id,
                        "quantity": quantity,
                        "unit_price": unit_price
                    }
                )

            # =================================================
            # GET OLD ITEMS
            # =================================================

            cursor.execute(
                """
                SELECT
                    oi.product_id,
                    p.name AS product_name,
                    oi.quantity,
                    oi.unit_price
                FROM order_items oi
                INNER JOIN products p
                    ON oi.product_id = p.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.order_item_id
                """,
                (order_id,)
            )

            old_items = cursor.fetchall()

            # =================================================
            # DELETE OLD ITEMS
            # =================================================

            cursor.execute(
                """
                DELETE FROM order_items
                WHERE order_id = %s
                """,
                (order_id,)
            )

            # =================================================
            # INSERT NEW ITEMS
            # =================================================

            for item in new_items:

                cursor.execute(
                    """
                    INSERT INTO order_items
                    (
                        order_id,
                        product_id,
                        quantity,
                        unit_price
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        order_id,
                        item["product_id"],
                        item["quantity"],
                        item["unit_price"]
                    )
                )

            # =================================================
            # UPDATE TOTAL
            # =================================================

            cursor.execute(
                """
                UPDATE orders
                SET
                    total_amount = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = %s
                """,
                (
                    total_amount,
                    order_id
                )
            )

        # =====================================================
        # COMMIT
        # =====================================================

        connection.commit()

        # =====================================================
        # EVENTBRIDGE
        # =====================================================

        publish_order_event(
            "OrderItemChanged",
            {
                "order_id": order_id,
                "customer_id": order["customer_id"],
                "customer_email":
                    order["customer_email"],
                "status": order["status"],
                "old_items": old_items,
                "new_items": new_items,
                "total_amount": total_amount
            }
        )

        # =====================================================
        # RESPONSE
        # =====================================================

        return response(
            200,
            {
                "order_id": order_id,
                "customer_id": order["customer_id"],
                "status": order["status"],
                "total_amount": total_amount,
                "items": new_items
            }
        )

    except Exception as error:

        connection.rollback()

        print(
            "Update order items error:",
            str(error)
        )

        return response(
            500,
            {
                "message": "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# CANCEL ORDER
# ============================================================

def cancel_order(event, order_id):

    # --------------------------------------------------------
    # ORDER AUTHORIZATION
    # --------------------------------------------------------

    if not authorize_order(
        event,
        order_id
    ):

        return response(
            403,
            {
                "message":
                "You are not authorized to cancel this order"
            }
        )

    # --------------------------------------------------------
    # Parse body
    # --------------------------------------------------------

    try:

        body = parse_request_body(event)

    except (json.JSONDecodeError, TypeError, ValueError) as error:

        print(
            "Cancel order body parsing error:",
            str(error)
        )

        return response(
            400,
            {
                "message": "Invalid JSON request body"
            }
        )

    reason = body.get(
        "reason",
        "CUSTOMER_REQUEST"
    )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # =================================================
            # LOCK ORDER
            # =================================================

            cursor.execute(
                """
                SELECT
                    o.status,
                    o.customer_id,
                    c.email AS customer_email
                FROM orders o
                INNER JOIN users c
                    ON o.customer_id = c.user_id
                WHERE o.order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                return response(
                    404,
                    {
                        "message": "Order not found"
                    }
                )

            old_status = order["status"]

            # ------------------------------------------------
            # Already cancelled
            # ------------------------------------------------

            if old_status == "CANCELLED":

                return response(
                    409,
                    {
                        "message":
                        "Order is already cancelled"
                    }
                )

            # ------------------------------------------------
            # Check cancellable statuses
            # ------------------------------------------------

            if old_status not in {
                "CREATED",
                "CONFIRMED",
                "PROCESSING"
            }:

                return response(
                    409,
                    {
                        "message":
                        "Order cannot be cancelled "
                        "in its current state"
                    }
                )

            # =================================================
            # RESTORE INVENTORY
            #
            # Only CONFIRMED / PROCESSING orders have had
            # inventory deducted.
            # =================================================

            if old_status in {
                "CONFIRMED",
                "PROCESSING"
            }:

                cursor.execute(
                    """
                    SELECT
                        product_id,
                        quantity
                    FROM order_items
                    WHERE order_id = %s
                    FOR UPDATE
                    """,
                    (order_id,)
                )

                items = cursor.fetchall()

                for item in items:

                    cursor.execute(
                        """
                        UPDATE inventory
                        SET
                            quantity = quantity + %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE product_id = %s
                        """,
                        (
                            item["quantity"],
                            item["product_id"]
                        )
                    )

            # =================================================
            # UPDATE ORDER
            # =================================================

            cursor.execute(
                """
                UPDATE orders
                SET
                    status = 'CANCELLED',
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = %s
                """,
                (order_id,)
            )

            # =================================================
            # ORDER HISTORY
            # =================================================

            cursor.execute(
                """
                INSERT INTO order_history
                (
                    order_id,
                    old_status,
                    new_status,
                    changed_by
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    order_id,
                    old_status,
                    "CANCELLED",
                    "API"
                )
            )

        # =====================================================
        # COMMIT
        # =====================================================

        connection.commit()

        # =====================================================
        # EVENTBRIDGE
        # =====================================================

        publish_order_event(
            "OrderCancelled",
            {
                "order_id": order_id,
                "customer_id": order["customer_id"],
                "customer_email":
                    order["customer_email"],
                "old_status": old_status,
                "new_status": "CANCELLED",
                "reason": reason
            }
        )

        return response(
            200,
            {
                "order_id": order_id,
                "status": "CANCELLED",
                "reason": reason
            }
        )

    except Exception as error:

        connection.rollback()

        print(
            "Cancel order error:",
            str(error)
        )

        return response(
            500,
            {
                "message": "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# MAIN HANDLER
# ============================================================

def lambda_handler(event, context):

    print("Order Lambda started")

    # ========================================================
    # HTTP METHOD
    # ========================================================

    method = (
        event.get("httpMethod")
        or
        event.get("requestContext", {})
        .get("http", {})
        .get("method")
    )

    # ========================================================
    # PATH
    # ========================================================

    path = (
        event.get("rawPath")
        or
        event.get("path", "")
    )

    # ========================================================
    # ORDER ID
    # ========================================================

    order_id = get_path_parameter(
        event,
        "orderId"
    )

    # ========================================================
    # CUSTOMER ID FROM QUERY STRING
    #
    # GET /orders?customerId=X
    # ========================================================

    customer_id_value = get_query_parameter(
        event,
        "customerId"
    )

    customer_id = None

    if customer_id_value is not None:

        try:

            customer_id = int(
                customer_id_value
            )

            if customer_id <= 0:
                raise ValueError

        except (ValueError, TypeError):

            return response(
                400,
                {
                    "message":
                    "Invalid customerId"
                }
            )

    # ========================================================
    # LOG REQUEST INFORMATION
    # ========================================================

    print(
        "HTTP method:",
        method
    )

    print(
        "Path:",
        path
    )

    print(
        "Order ID:",
        order_id
    )

    print(
        "Customer ID:",
        customer_id
    )

    print(
        "Authorizer context:",
        get_authorizer_context(event)
    )

    # ========================================================
    # POST /orders
    # ========================================================

    if (
        method == "POST"
        and path.endswith("/orders")
    ):

        return create_order(event)

    # ========================================================
    # GET /orders/{orderId}
    # ========================================================

    if (
        method == "GET"
        and order_id is not None
    ):

        return get_order(
            event,
            order_id
        )

    # ========================================================
    # GET /orders?customerId=X
    # ========================================================

    if (
        method == "GET"
        and path.endswith("/orders")
        and customer_id is not None
    ):

        return get_customer_orders(
            event,
            customer_id
        )

    # ========================================================
    # PUT /orders/{orderId}
    # ========================================================

    if (
        method == "PUT"
        and order_id is not None
    ):

        return update_order(
            event,
            order_id
        )

    # ========================================================
    # PATCH /orders/{orderId}/cancel
    # ========================================================
    #
    # IMPORTANT:
    # Check /cancel BEFORE generic PATCH.
    #
    # ========================================================

    if (
        method == "PATCH"
        and order_id is not None
        and path.endswith("/cancel")
    ):

        return cancel_order(
            event,
            order_id
        )

    # ========================================================
    # PATCH /orders/{orderId}
    # ========================================================

    if (
        method == "PATCH"
        and order_id is not None
    ):

        return update_order_items(
            event,
            order_id
        )

    # ========================================================
    # UNSUPPORTED REQUEST
    # ========================================================

    return response(
        400,
        {
            "message":
            "Unsupported API request"
        }
    )