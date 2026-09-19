import json
import os
import boto3
import pymysql
from decimal import Decimal

ssm = boto3.client("ssm")

RDS_HOST = os.environ["RDS_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]


def get_db_connection():
    response = ssm.get_parameter(
        Name=DB_PASSWORD_PARAMETER,
        WithDecryption=True
    )

    password = response["Parameter"]["Value"]

    return pymysql.connect(
        host=RDS_HOST,
        user=DB_USER,
        password=password,
        database=DB_NAME,
        port=3306,
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor
    )


def serialize(value):
    if isinstance(value, Decimal):
        return float(value)

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return value


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=serialize)
    }


def get_products():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    p.product_id,
                    p.name,
                    i.quantity AS inventory,
                    p.price AS cost,
                    p.description
                FROM products p
                LEFT JOIN inventory i
                    ON p.product_id = i.product_id
                WHERE p.is_active = 1
                ORDER BY p.product_id
                LIMIT 100
            """)

            products = cursor.fetchall()

        return response(
            200,
            {
                "products": products
            }
        )

    finally:
        connection.close()


def get_recent_orders():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    o.order_id,
                    o.customer_id,
                    oi.product_id,
                    p.name AS product_name,
                    oi.quantity,
                    (oi.quantity * oi.unit_price) AS total_bill,
                    o.status,
                    o.created_at
                FROM orders o
                JOIN order_items oi
                    ON o.order_id = oi.order_id
                JOIN products p
                    ON oi.product_id = p.product_id
                ORDER BY o.created_at DESC
                LIMIT 100
            """)

            orders = cursor.fetchall()

        return response(
            200,
            {
                "orders": orders
            }
        )

    finally:
        connection.close()


def lambda_handler(event, context):

    method = (
        event.get("httpMethod")
        or
        event.get("requestContext", {})
        .get("http", {})
        .get("method")
    )

    path = (
        event.get("rawPath")
        or
        event.get("path", "")
    )

    if method == "GET" and path.endswith("/dashboard/products"):
        return get_products()

    if method == "GET" and path.endswith("/dashboard/orders"):
        return get_recent_orders()

    return response(
        404,
        {
            "message": "Dashboard route not found"
        }
    )