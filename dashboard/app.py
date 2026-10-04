from flask import Flask, render_template, request, redirect, session, url_for, Response

import requests

import boto3

import os

import csv

import io

from datetime import datetime

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def format_ist_time(value):

    if not value:

        return ""

    if isinstance(value, str):

        value = datetime.fromisoformat(value)

    if value.tzinfo is None:

        value = value.replace(tzinfo=ZoneInfo("UTC"))

    return value.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")

app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "cloudmart-dashboard-secret")

API_URL = os.environ.get("API_URL")

REPORTS_BUCKET = os.environ.get("REPORTS_BUCKET")

if not API_URL or not REPORTS_BUCKET:

    raise RuntimeError("API_URL and REPORTS_BUCKET environment variables are required")

s3 = boto3.client("s3")

@app.route("/", methods=["GET", "POST"])

def login():

    if request.method == "POST":

        token = request.form.get("token")

        #get token value from login

        if not token:

            return render_template(

                "login.html",

                error="Please enter admin token"

            )

        try:

            response = requests.get(

                f"{API_URL}/dashboard/products",

                headers={

                    "Authorization": f"Bearer {token}"

                },

                timeout=10

            )

        except requests.RequestException:

            return render_template(

                "login.html",

                error="Unable to connect to CloudMart API"

            )

        if response.status_code == 200:

            session["admin_token"] = token

            return redirect(url_for("dashboard"))

        return render_template(

            "login.html",

            error="Invalid admin token"

        )

    return render_template("login.html")

@app.route("/dashboard")

def dashboard():

    token = session.get("admin_token")

    if not token:

        return redirect(url_for("login"))

    headers = {

        "Authorization": f"Bearer {token}"

    }

    try:

        products_response = requests.get(

            f"{API_URL}/dashboard/products",

            headers=headers,

            timeout=10

        )

        orders_response = requests.get(

            f"{API_URL}/dashboard/orders",

            headers=headers,

            timeout=10

        )

    except requests.RequestException:

        return "Unable to connect to CloudMart API.", 502

    if products_response.status_code == 401 or orders_response.status_code == 401:

        session.clear()

        return redirect(url_for("login"))

    if products_response.status_code != 200:

        return "Unable to load products.", 502

    if orders_response.status_code != 200:

        return "Unable to load orders.", 502

    products = products_response.json().get("products", [])

    orders = orders_response.json().get("orders", [])

    # Count distinct orders by status. The API can return one row per

    # product in an order, so order_id is used to avoid duplicate counts.

    status_order_ids = {

        "confirmed": set(),

        "processing": set(),

        "shipped": set(),

        "delivered": set()

    }

    total_sales = 0.0

    revenue_data = []

    revenue_order_ids = set()

    for index, order in enumerate(orders):

        status = str(order.get("status", "")).strip().lower()

        order_id = order.get("order_id")

        unique_id = str(order_id) if order_id is not None else f"row-{index}"

        if status in status_order_ids:

            status_order_ids[status].add(unique_id)

        if status != "cancelled":

            try:

                bill = float(order.get("total_bill") or 0)

                total_sales += bill

                if unique_id not in revenue_order_ids:

                    revenue_order_ids.add(unique_id)

                    raw_created_at = order.get("created_at")

                    if raw_created_at:

                        try:

                            parsed_time = datetime.fromisoformat(str(raw_created_at).replace("Z", "+00:00"))

                            if parsed_time.tzinfo is None:

                                parsed_time = parsed_time.replace(tzinfo=IST)

                            revenue_data.append({"date": parsed_time.astimezone(IST).date().isoformat(), "revenue": bill})

                        except (TypeError, ValueError):

                            app.logger.warning("Skipping invalid created_at for order %s", unique_id)

            except (TypeError, ValueError):

                app.logger.warning(

                    "Skipping invalid total_bill for order row %s", unique_id

                )

        order["created_at"] = format_ist_time(order.get("created_at"))

    order_counts = {

        status: len(order_ids)

        for status, order_ids in status_order_ids.items()

    }

    reports = get_previous_reports()

    report_status = get_today_report_status()

    return render_template(

        "dashboard.html",

        products=products,

        orders=orders,

        reports=reports,

        report_status=report_status,

        order_counts=order_counts,

        total_sales=total_sales,

        revenue_data=revenue_data,

        today_date=datetime.now(IST).date().isoformat()

    )

@app.route("/api/customers")

def customers():

    token = session.get("admin_token")

    if not token:

        return {

            "message": "Unauthorized"

        }, 401

    try:

        response = requests.get(

            f"{API_URL}/dashboard/customers",

            headers={

                "Authorization": f"Bearer {token}"

            },

            timeout=10

        )

    except requests.RequestException:

        return {

            "message": "Unable to connect to CloudMart API"

        }, 502

    if response.status_code == 401:

        session.clear()

        return {

            "message": "Unauthorized"

        }, 401

    return (

        response.text,

        response.status_code,

        {

            "Content-Type": "application/json"

        }

    )

@app.route("/api/customer/<customer_id>")

def customer(customer_id):

    token = session.get("admin_token")

    if not token:

        return {

            "message": "Unauthorized"

        }, 401

    try:

        response = requests.get(

            f"{API_URL}/dashboard/customers",

            params={

                "customer_id": customer_id

            },

            headers={

                "Authorization": f"Bearer {token}"

            },

            timeout=10

        )

    except requests.RequestException:

        return {

            "message": "Unable to connect to CloudMart API"

        }, 502

    if response.status_code == 401:

        session.clear()

        return {

            "message": "Unauthorized"

        }, 401

    return (

        response.text,

        response.status_code,

        {

            "Content-Type": "application/json"

        }

    )

def get_previous_reports():

    try:

        response = s3.list_objects_v2(

            Bucket=REPORTS_BUCKET,

            Prefix="daily-report-"

        )

        reports = []

        for obj in response.get("Contents", []):

            key = obj["Key"]

            #fileame/path

            if key.startswith("daily-report-") and key.endswith(".csv"):

                date_part = key.replace("daily-report-", "").replace(".csv", "")

                try:

                    report_date = datetime.strptime(date_part, "%Y-%m-%d").date()

                    reports.append({

                        "date": report_date.strftime("%d-%m-%Y"),

                        "key": key

                    })

                except ValueError:

                    continue

        reports.sort(

            key=lambda report: datetime.strptime(

                report["date"], "%d-%m-%Y"

            ),

            reverse=True

        )

        return reports

    except Exception as e:

        print("Error fetching previous reports:", e)

        return []

def get_today_report_key():

    today = datetime.now(IST).date().isoformat()

    return f"daily-report-{today}.csv"

def get_today_report_status():

    """Check whether today's report CSV exists in S3."""

    try:

        s3.head_object(Bucket=REPORTS_BUCKET, Key=get_today_report_key())

        return "Ready"

    except s3.exceptions.ClientError as error:

        code = error.response.get("Error", {}).get("Code", "")

        if code in ("404", "NoSuchKey", "NotFound"):

            cutoff = datetime.strptime("15:40", "%H:%M").time()

            return "Not Generated" if datetime.now(IST).time() >= cutoff else "Scheduled"

        app.logger.exception("Unable to check today's report in S3")

        return "Status Unavailable"

    except Exception:

        app.logger.exception("Unable to check today's report in S3")

        return "Status Unavailable"

def get_report_url(download=False):

    key = get_today_report_key()

    try:

        s3.head_object(

            Bucket=REPORTS_BUCKET,

            Key=key

        )

    except s3.exceptions.ClientError:

        return None

    response = s3.generate_presigned_url(

        #head_object() checks the S3 object without downloading the file.

        "get_object",

        Params={

            "Bucket": REPORTS_BUCKET,

            "Key": key,

            "ResponseContentType": "text/csv"

        },

        ExpiresIn=300

    )

    return response

@app.route("/report/data/<report_date>")

def report_data(report_date):

    if not session.get("admin_token"):

        return {"message": "Unauthorized"}, 401

    try:

        parsed_date = datetime.strptime(report_date, "%Y-%m-%d").date()

        if parsed_date.isoformat() != report_date:

            raise ValueError

    except ValueError:

        return {"message": "Invalid report date."}, 400

    key = f"daily-report-{report_date}.csv"

    try:

        obj = s3.get_object(Bucket=REPORTS_BUCKET, Key=key)

        content = obj["Body"].read().decode("utf-8-sig")

        reader = csv.reader(io.StringIO(content))

        rows = list(reader)

        if not rows:

            return {"message": "Report is empty."}, 200

        return {"available": True, "headers": rows[0], "rows": rows[1:]}

    except s3.exceptions.NoSuchKey:

        return {"available": False, "message": "No report is present on that day."}, 404

    except Exception as e:

        # S3 commonly reports missing objects as ClientError rather than NoSuchKey.

        from botocore.exceptions import ClientError

        if isinstance(e, ClientError) and e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):

            return {"available": False, "message": "No report is present on that day."}, 404

        app.logger.exception("Unable to retrieve daily report")

        return {"message": "Unable to retrieve the report."}, 502

@app.route("/report/view")

def view_report():

    if not session.get("admin_token"):

        return redirect(url_for("login"))

    url = get_report_url()

    if not url:

        return "Today's report is not available yet.", 404

    return redirect(url)

@app.route("/report/download")

def download_report():

    if not session.get("admin_token"):

        return redirect(url_for("login"))

    key = get_today_report_key()

    try:

        s3.head_object(

            Bucket=REPORTS_BUCKET,

            Key=key

        )

    except s3.exceptions.ClientError:

        return "Today's report is not available yet.", 404

    url = s3.generate_presigned_url(

        "get_object",

        Params={

            "Bucket": REPORTS_BUCKET,

            "Key": key,

            "ResponseContentType": "text/csv",

            "ResponseContentDisposition": f'attachment; filename="{key}"'

        },

        ExpiresIn=300

    )

    return redirect(url)

@app.route("/report/download/<report_date>")

def download_previous_report(report_date):

    if not session.get("admin_token"):

        return redirect(url_for("login"))

    try:

        report_date_obj = datetime.strptime(

            report_date,

            "%d-%m-%Y"

        )

        key = f"daily-report-{report_date_obj.strftime('%Y-%m-%d')}.csv"

    except ValueError:

        return "Invalid report date.", 400

    try:

        s3.head_object(

            Bucket=REPORTS_BUCKET,

            Key=key

        )

    except s3.exceptions.ClientError:

        return "Report is not available.", 404

    url = s3.generate_presigned_url(

        "get_object",

        Params={

            "Bucket": REPORTS_BUCKET,

            "Key": key,

            "ResponseContentType": "text/csv",

            "ResponseContentDisposition": f'attachment; filename="{key}"'

            #This tells the browser to download the CSV rather than open it.

        },

        ExpiresIn=300

    )

    return redirect(url)

@app.route("/logout")

def logout():

    session.clear()

    return redirect(url_for("login"))

if __name__ == "__main__":

    app.run(

        host="127.0.0.1",

        port=8000

    )
