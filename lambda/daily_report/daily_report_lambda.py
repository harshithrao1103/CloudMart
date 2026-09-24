# ============================================================
# MILESTONE 5 - DAILY REPORT LAMBDA
# Generates the daily CloudMart sales report.
#
# - Gets today's orders from RDS MySQL.
# - Creates a CSV with order details.
# - Calculates each customer's daily expenditure.
# - Calculates total daily revenue.
# - Uploads the CSV report to the S3 reports bucket.
#
# TRIGGER:
# EventBridge Scheduler runs the Lambda daily at 11:59 PM IST.
#
# OUTPUT:
# daily-report-YYYY-MM-DD.csv
# ============================================================

import os
import csv
import io
import boto3
import pymysql

ssm = boto3.client("ssm")
s3 = boto3.client("s3")

RDS_HOST = os.environ["RDS_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]
REPORTS_BUCKET = os.environ["REPORTS_BUCKET"]


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


def lambda_handler(event, context):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT o.created_at,
                       o.customer_id,
                       o.order_id,
                       oi.product_id,
                       p.name AS product_name,
                       oi.quantity,
                       oi.unit_price,
                       (oi.quantity * oi.unit_price) AS bill
                FROM orders o
                JOIN order_items oi ON o.order_id = oi.order_id
                JOIN products p ON oi.product_id = p.product_id
                WHERE DATE(o.created_at) = CURDATE()
                ORDER BY o.created_at, o.customer_id, o.order_id
            """)

            rows = cursor.fetchall()

        from datetime import date

        today = date.today().isoformat()

        output = io.StringIO()
        #This creates a temporary text area in memory where the CSV content will be written.
        writer = csv.writer(output)
        #creates csv

        writer.writerow(["CLOUDMART DAILY SALES REPORT"])
        writer.writerow(["Report Date", today])
        writer.writerow([])

        writer.writerow(["ORDER DETAILS"])
        writer.writerow([
            "Date",
            "Customer ID",
            "Order ID",
            "Product ID",
            "Product Name",
            "Quantity",
            "Unit Price",
            "Bill"
        ])

        customer_totals = {}
        total_revenue = 0

        for row in rows:
            bill = float(row["bill"])
            total_revenue += bill

            customer_id = row["customer_id"]

            if customer_id not in customer_totals:
                customer_totals[customer_id] = 0

            customer_totals[customer_id] += bill

            writer.writerow([
                row["created_at"].strftime("%Y-%m-%d"),
                customer_id,
                row["order_id"],
                row["product_id"],
                row["product_name"],
                row["quantity"],
                float(row["unit_price"]),
                bill
            ])

        writer.writerow([])
        writer.writerow(["CUSTOMER DAILY EXPENDITURE"])
        writer.writerow(["Customer ID", "Total Expenditure"])

        for customer_id, total in customer_totals.items():
            writer.writerow([
                customer_id,
                round(total, 2)
            ])

        writer.writerow([])
        writer.writerow(["TOTAL DAILY REVENUE"])
        writer.writerow(["Total Revenue", round(total_revenue, 2)])

        key = f"daily-report-{today}.csv"
        #key is the object name/file name inside S3.

        s3.put_object(
            Bucket=REPORTS_BUCKET,
            Key=key,
            Body=output.getvalue().encode("utf-8"),
            ContentType="text/csv"
        )

        return {
            "statusCode": 200,
            "message": "Daily report generated successfully",
            "bucket": REPORTS_BUCKET,
            "key": key,
            "total_revenue": total_revenue
        }

    finally:
        connection.close()