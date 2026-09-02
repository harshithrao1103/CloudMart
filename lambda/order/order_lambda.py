import json
import os
import boto3
import pymysql
from decimal import Decimal


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
# DECIMAL CONVERSION
# ============================================================

def decimal_to_float(value):

    if isinstance(value, Decimal):
        return float(value)

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

        events.put_events(
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

    try:

        body = json.loads(
            event.get("body") or "{}"
        )

    except json.JSONDecodeError:

        return response(
            400,
            {
                "message": "Invalid JSON request body"
            }
        )

    customer_id = body.get("customer_id")
    items = body.get("items")

    if not customer_id or not isinstance(items, list) or not items:

        return response(
            400,
            {
                "message":
                "customer_id and at least one item are required"
            }
        )

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

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Check customer
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT customer_id, email
                FROM customers
                WHERE customer_id = %s
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

            # ------------------------------------------------
            # Validate products and inventory
            # ------------------------------------------------

            for item in items:

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

                item_total = unit_price * quantity

                total_amount += item_total

                order_items.append(
                    {
                        "product_id": product_id,
                        "quantity": quantity,
                        "unit_price": unit_price
                    }
                )

            # ------------------------------------------------
            # Create order
            #
            # IMPORTANT:
            # Inventory is NOT deducted here.
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Create order items
            #
            # Inventory remains unchanged until CONFIRMED.
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Initial order history
            # ------------------------------------------------

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

        connection.commit()

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

def get_order(order_id):

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

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

            cursor.execute(
                """
                SELECT
                    oi.order_item_id,
                    oi.product_id,
                    p.name AS product_name,
                    oi.quantity,
                    oi.unit_price,
                    (oi.quantity * oi.unit_price) AS item_total
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

def get_customer_orders(customer_id):

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Check customer
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT customer_id
                FROM customers
                WHERE customer_id = %s
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

            # ------------------------------------------------
            # Get orders
            # ------------------------------------------------

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

    try:

        body = json.loads(
            event.get("body") or "{}"
        )

    except json.JSONDecodeError:

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

            # ------------------------------------------------
            # Lock order
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    o.status,
                    o.customer_id,
                    c.email AS customer_email
                FROM orders o
                INNER JOIN customers c
                    ON o.customer_id = c.customer_id
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

            # ------------------------------------------------
            # Valid state transitions
            # ------------------------------------------------

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

            # ------------------------------------------------
            # CONFIRM ORDER
            #
            # This is where inventory is deducted.
            # ------------------------------------------------

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

                for item in items:

                    if (
                        item["inventory_quantity"]
                        < item["quantity"]
                    ):

                        raise Exception(
                            f"Insufficient inventory for "
                            f"product {item['product_id']}"
                        )

                # --------------------------------------------
                # Deduct inventory
                # --------------------------------------------

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

            # ------------------------------------------------
            # Update order status
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Add order history
            # ------------------------------------------------

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

        connection.commit()

        status_event_map = {
            "CONFIRMED": "OrderConfirmed",
            "PROCESSING": "OrderProcessing",
            "SHIPPED": "OrderShipped",
            "DELIVERED": "OrderDelivered"
        }

        event_type = status_event_map.get(new_status)

        if event_type:
            publish_order_event(
                event_type,
                {
                    "order_id": order_id,
                    "customer_id": order["customer_id"],
                    "customer_email": order["customer_email"],
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
        # If confirmation processing failed,
        # send the failed order to the ONE SQS failure queue.
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

    try:

        body = json.loads(
            event.get("body") or "{}"
        )

    except json.JSONDecodeError:

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
                "message": "items must be a non-empty array"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.status,
                    c.email AS customer_email
                FROM orders o
                INNER JOIN customers c
                    ON o.customer_id = c.customer_id
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

            for item in items:

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
                total_amount += unit_price * quantity

                new_items.append(
                    {
                        "product_id": product_id,
                        "quantity": quantity,
                        "unit_price": unit_price
                    }
                )

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

            cursor.execute(
                """
                DELETE FROM order_items
                WHERE order_id = %s
                """,
                (order_id,)
            )

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

        connection.commit()

        publish_order_event(
            "OrderItemChanged",
            {
                "order_id": order_id,
                "customer_id": order["customer_id"],
                "customer_email": order["customer_email"],
                "status": order["status"],
                "old_items": old_items,
                "new_items": new_items,
                "total_amount": total_amount
            }
        )

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

    try:

        body = json.loads(
            event.get("body") or "{}"
        )

    except json.JSONDecodeError:

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

            # ------------------------------------------------
            # Lock order
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    o.status,
                    o.customer_id,
                    c.email AS customer_email
                FROM orders o
                INNER JOIN customers c
                    ON o.customer_id = c.customer_id
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

            # ------------------------------------------------
            # Restore inventory
            #
            # Only orders that have been confirmed/processed
            # should have inventory deducted.
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Update order
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Add history
            # ------------------------------------------------

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

        connection.commit()

        publish_order_event(
            "OrderCancelled",
            {
                "order_id": order_id,
                "customer_id": order["customer_id"],
                "customer_email": order["customer_email"],
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

    method = (
        event.get("httpMethod")
        or
        event.get("requestContext", {})
        .get("http", {})
        .get("method")
    )

    path = event.get("rawPath") or event.get("path", "")

    order_id = get_path_parameter(
        event,
        "orderId"
    )

    # --------------------------------------------------------
    # Query-string customerId
    #
    # Required API:
    # GET /orders?customerId=X
    # --------------------------------------------------------

    customer_id_value = get_query_parameter(
        event,
        "customerId"
    )

    customer_id = None

    if customer_id_value is not None:

        try:

            customer_id = int(customer_id_value)

            if customer_id <= 0:
                raise ValueError

        except (ValueError, TypeError):

            return response(
                400,
                {
                    "message": "Invalid customerId"
                }
            )

    print("HTTP method:", method)
    print("Path:", path)
    print("Order ID:", order_id)
    print("Customer ID:", customer_id)

    # ========================================================
    # POST /orders
    # ========================================================

    if method == "POST" and path.endswith("/orders"):

        return create_order(event)

    # ========================================================
    # GET /orders/{orderId}
    # ========================================================

    if (
        method == "GET"
        and order_id is not None
    ):

        return get_order(order_id)

    # ========================================================
    # GET /orders?customerId=X
    # ========================================================

    if (
        method == "GET"
        and path.endswith("/orders")
        and customer_id is not None
    ):

        return get_customer_orders(customer_id)

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
    # PATCH /orders/{orderId}
    # ========================================================

    if (
        method == "PATCH"
        and order_id is not None
        and not path.endswith("/cancel")
    ):

        return update_order_items(
            event,
            order_id
        )

    # ========================================================
    # PATCH /orders/{orderId}/cancel
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
    # UNSUPPORTED REQUEST
    # ========================================================

    return response(
        400,
        {
            "message": "Unsupported API request"
        }
    )