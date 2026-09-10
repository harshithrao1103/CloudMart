import json
import boto3
import os
import pymysql
from decimal import Decimal


# ============================================================
# AWS CLIENTS
# ============================================================

ses = boto3.client("ses")
ssm = boto3.client("ssm")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

SENDER_EMAIL = os.environ["SENDER_EMAIL"]

RDS_HOST = os.environ["RDS_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]


# ============================================================
# GET DATABASE PASSWORD FROM SSM
# ============================================================

def get_db_password():

    response = ssm.get_parameter(
        Name=DB_PASSWORD_PARAMETER,
        WithDecryption=True
    )

    return response["Parameter"]["Value"]


# ============================================================
# RDS DATABASE CONNECTION
# ============================================================

def get_db_connection():

    return pymysql.connect(
        host=RDS_HOST,
        user=DB_USER,
        password=get_db_password(),
        database=DB_NAME,
        port=3306,
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor
    )


# ============================================================
# GET ORDER DETAILS FROM RDS
# ============================================================

def get_order_details(order_id):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Get order information
            # ------------------------------------------------

            order_query = """
                SELECT
                    order_id,
                    status,
                    total_amount
                FROM orders
                WHERE order_id = %s
            """

            cursor.execute(order_query, (order_id,))

            order = cursor.fetchone()

            if not order:
                print(f"Order {order_id} not found in RDS")
                return None


            # ------------------------------------------------
            # Get order items and product names
            # ------------------------------------------------

            items_query = """
                SELECT
                    p.name AS product_name,
                    oi.quantity,
                    oi.unit_price AS price,
                    (oi.quantity * oi.unit_price) AS item_total
                FROM order_items oi
                JOIN products p
                    ON oi.product_id = p.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.order_item_id
            """

            cursor.execute(items_query, (order_id,))

            items = cursor.fetchall()


            return {
                "order_id": order["order_id"],
                "status": order["status"],
                "total_amount": order["total_amount"],
                "items": items
            }

    finally:

        if connection:
            connection.close()


# ============================================================
# FORMAT ORDER ITEMS FOR EMAIL
# ============================================================

def build_order_items_text(items):

    if not items:
        return "Order Items:\nNo order items found."

    lines = []

    lines.append("Order Items:")
    lines.append("--------------------------------")

    for item in items:

        product_name = item["product_name"]
        quantity = item["quantity"]
        price = item["price"]
        item_total = item["item_total"]

        if isinstance(price, Decimal):
            price = float(price)

        if isinstance(item_total, Decimal):
            item_total = float(item_total)

        lines.append(f"Product: {product_name}")
        lines.append(f"Quantity: {quantity}")
        lines.append(f"Price: ${price:.2f}")
        lines.append(f"Item Total: ${item_total:.2f}")
        lines.append("")

    lines.append("--------------------------------")

    return "\n".join(lines)


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    print("Received EventBridge event:")
    print(json.dumps(event))


    # --------------------------------------------------------
    # Read EventBridge event details
    # --------------------------------------------------------

    detail = event.get("detail", {})

    event_type = event.get(
        "detail-type",
        "OrderEvent"
    )

    customer_email = detail.get("customer_email")

    order_id = detail.get("order_id")


    # --------------------------------------------------------
    # Validate customer email
    # --------------------------------------------------------

    if not customer_email:

        print("Customer email not found in event")

        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Customer email is missing"
            })
        }


    # --------------------------------------------------------
    # Validate order ID
    # --------------------------------------------------------

    if not order_id:

        print("Order ID not found in event")

        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Order ID is missing"
            })
        }


    # --------------------------------------------------------
    # Query RDS using order_id
    # --------------------------------------------------------

    try:

        order_details = get_order_details(order_id)

        if not order_details:

            return {
                "statusCode": 404,
                "body": json.dumps({
                    "message": f"Order {order_id} not found"
                })
            }

    except Exception as error:

        print(
            f"Error retrieving order {order_id} "
            f"from RDS: {error}"
        )

        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Failed to retrieve order details"
            })
        }


    # --------------------------------------------------------
    # Build order items section
    # --------------------------------------------------------

    order_items_text = build_order_items_text(
        order_details["items"]
    )


    # --------------------------------------------------------
    # Get order total
    # --------------------------------------------------------

    total_amount = order_details["total_amount"]

    if isinstance(total_amount, Decimal):
        total_amount = float(total_amount)


    # --------------------------------------------------------
    # Build email subject
    # --------------------------------------------------------

    subject = (
        f"CloudMart Order #{order_id} - {event_type}"
    )


    # --------------------------------------------------------
    # Build email body
    # --------------------------------------------------------

    body = f"""
Hello,

Your CloudMart order #{order_id} has been updated.

Order Status: {event_type}

{order_items_text}

Total Amount: ${total_amount:.2f}

Thank you for shopping with CloudMart.

Regards,
CloudMart Team
"""


    # --------------------------------------------------------
    # Send email using SES
    # --------------------------------------------------------

    response = ses.send_email(
        Source=SENDER_EMAIL,
        Destination={
            "ToAddresses": [
                customer_email
            ]
        },
        Message={
            "Subject": {
                "Data": subject
            },
            "Body": {
                "Text": {
                    "Data": body
                }
            }
        }
    )


    # --------------------------------------------------------
    # Log SES response
    # --------------------------------------------------------

    print(
        f"Email sent successfully to "
        f"{customer_email}"
    )

    print(
        f"SES Message ID: "
        f"{response['MessageId']}"
    )


    # --------------------------------------------------------
    # Return response
    # --------------------------------------------------------

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Notification email sent successfully",
            "message_id": response["MessageId"]
        })
    }